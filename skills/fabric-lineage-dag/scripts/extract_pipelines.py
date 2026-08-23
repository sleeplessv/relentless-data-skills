#!/usr/bin/env python3
"""Extractor 1: pipelines, schedules, dataflows -> extract-pipelines.json (+ guid-map.json).

Walks every *.DataPipeline/pipeline-content.json (activities recursively), .schedules,
and *.Dataflow/mashup.pq. Resolves item GUIDs through the .platform map built first.

    python3 extract_pipelines.py --repo <repo> --out <scratch> [--config lineage.config.json]
"""
import glob
import json
import os
import re
from collections import Counter

from lineage_common import (Graph, build_guid_map, country_detector, is_fork_name, layer_of_lakehouse,
                            make_resolver, parse_args)

a = parse_args("Extract Fabric pipelines, schedules and dataflows into the lineage schema")
CFG, REPO, OUT = a.cfg, a.repo, a.out
os.chdir(REPO)
guid_map = build_guid_map(REPO, OUT)
resolve = make_resolver(guid_map)
detect_country = country_detector(CFG)
G = Graph()
partial = {}


def val(x):
    """Collapse {value, type: Expression} wrappers to the raw value."""
    if isinstance(x, dict) and "value" in x and "type" in x:
        return val(x["value"])
    return x


def clean_ident(s):
    return str(s).strip().strip("[]").lower()


def lakehouse_name(ds):
    for key in ("linkedService", "connectionSettings"):
        props = (ds.get(key) or {}).get("properties", {})
        tp = props.get("typeProperties", {})
        aid = tp.get("artifactId")
        if not aid:
            continue
        r = resolve(aid)
        return (r["displayName"] if r else (ds.get(key) or {}).get("name")), aid, tp.get("rootFolder")
    return None, None, None


def layer_of(name):
    return layer_of_lakehouse(CFG, name)


# ---------------------------------------------------------------- expression helpers
def lookup_items(ctx, expr):
    """@variables('X') / @pipeline().parameters.X -> (name, default array) when it is a list."""
    if not isinstance(expr, str):
        return None
    m = re.search(r"@variables\('([^']+)'\)", expr) or re.search(r"@pipeline\(\)\.parameters\.(\w+)", expr)
    if not m:
        return None
    v = ctx["vars"].get(m.group(1)) or ctx["params"].get(m.group(1)) or {}
    dv = val(v.get("defaultValue")) if isinstance(v, dict) else None
    return (m.group(1), dv) if isinstance(dv, list) else None


def resolve_expr(ctx, v):
    """Substitute scalar variable/parameter defaults into an expression string."""
    if not isinstance(v, str):
        return v

    def rep(m):
        name = m.group(1) or m.group(2)
        d = ctx["vars"].get(name) or ctx["params"].get(name) or {}
        dv = val(d.get("defaultValue")) if isinstance(d, dict) else None
        return str(dv) if isinstance(dv, (str, int, float)) else m.group(0)
    return re.sub(r"@variables\('([^']+)'\)|@pipeline\(\)\.parameters\.(\w+)", rep, v)


def item_get(item, path):
    cur = item
    for p in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def substitute(obj, item):
    """Replace @item().a.b with values from a concrete ForEach item."""
    if isinstance(obj, str) and "@item()" in obj:
        return re.sub(r"@item\(\)\.([A-Za-z0-9_.]+)", lambda m: str(item_get(item, m.group(1)) if item_get(item, m.group(1)) is not None else m.group(0)), obj)
    if isinstance(obj, dict):
        return {k: substitute(v, item) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute(v, item) for v in obj]
    return obj


def expansions(ctx, params):
    """One resolved parameter dict per ForEach scalar item when @item() is used, else one."""
    params = {k: resolve_expr(ctx, v) for k, v in params.items()}
    fe = ctx["foreach"][-1] if ctx["foreach"] else None
    if fe and any(isinstance(v, str) and "@item()" in v for v in params.values()):
        name, items = fe
        if all(isinstance(i, (str, int)) for i in items):
            return [({k: (str(i) if v == "@item()" else v) for k, v in params.items()}, str(i)) for i in items]
    return [(params, None)]


# ---------------------------------------------------------------- notebook-driven ingest parameters
def emit_param_lineage(ctx, nid, params, item, via, parent):
    """Partner-drop sources and Bronze targets declared as notebook parameters (no Copy activity)."""
    pid, ppath = ctx["id"], ctx["path"]
    bp, tt = params.get("BasePathPattern"), params.get("TargetTable")
    ctry = item or (params.get("Countries") if isinstance(params.get("Countries"), str) and len(params.get("Countries")) == 2 else None)
    ctry = ctry.upper() if isinstance(ctry, str) and ctry.upper() in CFG["countries"] else None
    partner, sid = None, None
    if isinstance(bp, str) and bp.startswith("Files/Partners/"):
        rest = bp[len("Files/Partners/"):].replace("{Country}", item or "{Country}")
        partner = rest.split("/")[0]
        sid = f"source.partnerdrop.{rest}".lower()
        G.node(sid, f"Bronze/Files/Partners/{rest}", "source", "csv_drop", None, partner=partner, country=ctry,
               details={"basePathPattern": bp})
        G.edge(sid, pid, "reads", via, ppath, parent=parent, resolvedBy=nid)
    if isinstance(tt, str) and "@" not in tt:
        tid = f"bronze.{tt.replace('.', '_')}".lower()
        G.node(tid, tt, "bronze", "delta_table", None, partner=partner or tt.split(".")[-1], country=ctry,
               details={"lakehouse": "Bronze", "surrogateKeyColumns": params.get("SurrogateKeyColumns")})
        G.edge(pid, tid, "writes", via, ppath, parent=parent, resolvedBy=nid, country=ctry)
        if sid:
            G.edge(sid, tid, "copy", f"{ctx['name']}/{via}", ppath, parent=parent, resolvedBy=nid, country=ctry, loadType="notebook-ingest")
    return partner


# ---------------------------------------------------------------- activities
def walk(acts, ctx, parent=None):
    for act in acts:
        tp = act.get("typeProperties", {})
        if act["type"] == "ForEach":
            ctx["foreach"].append(lookup_items(ctx, val(tp.get("items"))))
        handle(act, ctx, parent)
        for k in ("activities", "ifTrueActivities", "ifFalseActivities", "defaultActivities"):
            if k in tp:
                walk(tp[k], ctx, act["name"])
        for c in tp.get("cases", []):
            walk(c.get("activities", []), ctx, act["name"])
        if act["type"] == "ForEach":
            ctx["foreach"].pop()


def handle(act, ctx, parent):
    t, name, tp = act["type"], act["name"], act.get("typeProperties", {})
    pid, ppath = ctx["id"], ctx["path"]
    deps = [(d["activity"], d.get("dependencyConditions")) for d in act.get("dependsOn", [])]
    rec = {"name": name, "type": t, "parent": parent, "dependsOn": [d[0] for d in deps]}
    ctx["activities"].append(rec)

    if t == "TridentNotebook":
        nb = resolve(tp.get("notebookId"))
        params = {k: val(v) for k, v in (tp.get("parameters") or {}).items()}
        rec["parameters"] = params
        if nb:
            nid = f"notebook.{nb['displayName']}"
            G.node(nid, nb["displayName"], "notebook", "notebook", nb["path"], details={"logicalId": tp.get("notebookId")})
            rec["notebook"] = nb["displayName"]
        else:
            nid = f"unresolved.notebook.{tp.get('notebookId')}"
            G.node(nid, f"notebook {tp.get('notebookId')}", "notebook", "notebook", None, details={"raw": tp.get("notebookId")})
            ctx["issues"].append(f"notebook GUID {tp.get('notebookId')} unresolved (activity {name})")
        for rp, item in expansions(ctx, params):
            partner = emit_param_lineage(ctx, nid, rp, item, name, parent)
            G.edge(pid, nid, "runs", name, ppath, parameters=params, resolvedParameters=rp, foreachItem=item, parent=parent,
                   loadingLayer=rp.get("loadingLayer"), processArea=rp.get("processArea"), jsonFileName=rp.get("jsonFileName"), partner=partner)
    elif t in ("InvokePipeline", "ExecutePipeline"):
        cg = tp.get("pipelineId") or (tp.get("pipeline") or {}).get("referenceName")
        child = resolve(cg)
        params = {k: val(v) for k, v in (tp.get("parameters") or {}).items()}
        rec["parameters"] = params
        if child:
            cid = f"pipeline.{child['displayName']}"
            G.node(cid, child["displayName"], "pipeline", "pipeline", child["path"])
            rec["childPipeline"] = child["displayName"]
        else:
            cid = f"unresolved.pipeline.{cg}"
            G.node(cid, f"pipeline {cg}", "pipeline", "pipeline", None, details={"raw": cg})
            ctx["issues"].append(f"child pipeline GUID {cg} unresolved (activity {name})")
        for rp, item in expansions(ctx, params):
            partner = emit_param_lineage(ctx, cid, rp, item, name, parent)
            G.edge(pid, cid, "invokes", name, ppath, parameters=params, resolvedParameters=rp, foreachItem=item, parent=parent,
                   waitOnCompletion=tp.get("waitOnCompletion"), partner=partner)
    elif t == "RefreshDataflow":
        df = resolve(tp.get("dataflowId"))
        did = f"dataflow.{df['displayName']}" if df else f"unresolved.dataflow.{tp.get('dataflowId')}"
        G.node(did, df["displayName"] if df else f"dataflow {tp.get('dataflowId')}", "dataflow", "dataflow", df["path"] if df else None)
        if not df:
            ctx["issues"].append(f"dataflow GUID {tp.get('dataflowId')} unresolved")
        G.edge(pid, did, "triggers", name, ppath, parent=parent)
    elif t in ("PBISemanticModelRefresh", "RefreshDataset", "SemanticModelRefresh"):
        dsid = tp.get("datasetId") or tp.get("semanticModelId")
        sm = resolve(dsid)
        sid = f"semantic.{sm['displayName']}" if sm else f"unresolved.semantic.{dsid}"
        G.node(sid, sm["displayName"] if sm else str(dsid), "semantic", "semantic_model", sm["path"] if sm else None)
        G.edge(pid, sid, "refreshes", name, ppath, parent=parent)
    elif t == "Copy":
        handle_copy(act, ctx, parent, rec)
    elif t == "Lookup":
        src = tp.get("source", {})
        rec["lookup"] = {"sourceType": src.get("type"), "query": val(src.get("sqlReaderQuery"))}
        q = str(rec["lookup"]["query"] or "")
        if "INFORMATION_SCHEMA" in q.upper():
            ctx["issues"].append(f"lookup {name}: table list resolved at runtime ({q[:120]})")
    elif t == "WebActivity":
        rec["web"] = {"method": tp.get("method"), "url": val(tp.get("url")) or val(tp.get("relativeUrl"))}
    elif t == "Office365Email":
        rec["email"] = {"to": tp.get("to"), "subject": tp.get("subject")}
    elif t == "SetVariable":
        rec["variable"] = {"name": tp.get("variableName"), "value": val(tp.get("value"))}
    elif t == "ForEach":
        rec["items"] = val(tp.get("items"))
    elif t in ("IfCondition", "Until", "Switch", "Filter", "Delete", "SqlServerStoredProcedure", "Script", "Wait"):
        pass
    else:
        ctx["issues"].append(f"unhandled activity type {t} ({name})")


def handle_copy(act, ctx, parent, rec):
    fe = ctx["foreach"][-1] if ctx["foreach"] else None
    if fe and "@item()" in json.dumps(act["typeProperties"]):
        listname, items = fe
        rec["expandedFrom"], rec["expandedCount"], rec["copies"] = listname, len(items), []
        for it in items:
            a2 = dict(act, typeProperties=substitute(act["typeProperties"], it))
            sub = {}
            handle_copy_one(a2, ctx, parent, sub, listname)
            rec["copies"].append(sub.get("copy"))
        return
    handle_copy_one(act, ctx, parent, rec, None)


def handle_copy_one(act, ctx, parent, rec, listname):
    def deep(o):
        if isinstance(o, str):
            return resolve_expr(ctx, o)
        if isinstance(o, dict):
            return {k: deep(v) for k, v in o.items()}
        if isinstance(o, list):
            return [deep(v) for v in o]
        return o
    tp, name = deep(act["typeProperties"]), act["name"]
    pid, ppath = ctx["id"], ctx["path"]
    src, snk = tp.get("source", {}), tp.get("sink", {})
    sds, kds = src.get("datasetSettings", {}), snk.get("datasetSettings", {})
    stype, ktype = sds.get("type"), kds.get("type")
    sprops = {k: val(v) for k, v in (sds.get("typeProperties") or {}).items()}
    kprops = {k: val(v) for k, v in (kds.get("typeProperties") or {}).items()}
    sconn = (sds.get("externalReferences") or {}).get("connection")
    kconn = (kds.get("externalReferences") or {}).get("connection")
    query = val(src.get("sqlReaderQuery")) or val(src.get("query"))
    store = src.get("storeSettings", {})
    country = detect_country(ctx["name"], name, json.dumps(sprops), json.dumps(kprops), ctx["path"])

    # ---- source node
    if stype in ("AzureSqlTable", "SqlServerTable"):
        db = sprops.get("database") or "unknown"
        schema, table = sprops.get("schema") or "dbo", sprops.get("table")
        if not table and isinstance(query, str):
            m = re.search(r"from\s+\[?([A-Za-z0-9_]+)\]?\.\[?([A-Za-z0-9_]+)\]?", query, re.I)
            if m:
                schema, table = m.group(1), m.group(2)
        if (not table) or "@" in str(table) or "@" in str(schema):
            sid = f"unresolved.source.{clean_ident(db)}.{clean_ident(schema)}.{clean_ident(table or '?')}"
            G.node(sid, f"{db}.{schema}.{table}", "source", "sql_table", None,
                   details={"raw": {"schema": schema, "table": table, "query": query}, "database": db, "connection": sconn, "dynamic": True})
            ctx["issues"].append(f"copy {name}: dynamic source table expression ({table})")
        else:
            sid = f"source.{clean_ident(db)}.{clean_ident(schema)}.{clean_ident(table)}"
            G.node(sid, f"{db}.{schema}.{table}", "source", "sql_table", None, country=detect_country(db) or country,
                   details={"database": db, "schema": schema, "table": table, "connection": sconn, "datasetType": stype})
    elif stype in ("Json", "Binary", "DelimitedText", "Parquet"):
        loc = {k: val(v) for k, v in (sprops.get("location") or {}).items()}
        lh, _, root = lakehouse_name(sds)
        folder = val(store.get("wildcardFolderPath")) or loc.get("folderPath") or ""
        fname = val(store.get("wildcardFileName")) or loc.get("fileName") or ""
        p = "/".join(x for x in (folder, fname) if x)
        if loc.get("type") == "AzureBlobStorageLocation":
            sid = f"source.blob.{loc.get('container', '?')}/{p}".lower()
            G.node(sid, f"blob:{loc.get('container')}/{p}", "source", "blob", None, country=country,
                   details={"container": loc.get("container"), "path": p, "connection": sconn})
        else:
            layer = layer_of(lh)
            sid = f"{layer}.files/{p}".lower()
            G.node(sid, f"{lh}/{root}/{p}", layer, "csv_drop", None, country=country, details={"lakehouse": lh, "path": p})
    elif stype == "LakehouseTable":
        lh, _, _ = lakehouse_name(sds)
        layer = layer_of(lh)
        tbl = f"{sprops.get('schema') + '.' if sprops.get('schema') else ''}{sprops.get('table')}"
        sid = f"{layer}.{tbl.replace('.', '_')}".lower()
        G.node(sid, tbl, layer, "delta_table", None, country=country, details={"lakehouse": lh})
    else:
        sid = f"unresolved.source.{ctx['name']}.{name}".lower()
        G.node(sid, str(stype), "source", "blob", None, details={"raw": sds})
        ctx["issues"].append(f"copy {name}: unknown source dataset type {stype}")

    # ---- sink node
    if ktype == "LakehouseTable":
        lh, aid, _ = lakehouse_name(kds)
        layer = layer_of(lh)
        schema, table = kprops.get("schema"), kprops.get("table")
        tbl = f"{schema}.{table}" if schema else f"{table}"
        tid = f"{schema}_{table}" if schema else f"{table}"
        if (not table) or "@" in str(table) or "@" in str(schema or ""):
            kid = f"unresolved.{layer}.{tid}".lower()
            G.node(kid, tbl, layer, "delta_table", None, details={"raw": {"schema": schema, "table": table}, "lakehouse": lh, "dynamic": True})
        else:
            kid = f"{layer}.{tid}".lower()
            G.node(kid, tbl, layer, "delta_table", None, country=country or detect_country(tbl),
                   details={"lakehouse": lh, "lakehouseId": aid, "schema": schema, "table": table})
    elif ktype in ("Binary", "DelimitedText", "Json", "Parquet"):
        loc = {k: val(v) for k, v in (kprops.get("location") or {}).items()}
        lh, _, _ = lakehouse_name(kds)
        p = "/".join(x for x in (loc.get("folderPath"), loc.get("fileName")) if x)
        if loc.get("type") == "AzureBlobStorageLocation":
            kid = f"export.blob.{loc.get('container')}/{p}".lower()
            G.node(kid, f"blob:{loc.get('container')}/{p}", "export", "blob", None, country=country, details={"container": loc.get("container"), "path": p})
        elif loc.get("type") == "SftpLocation" or "Sftp" in json.dumps(kds):
            kid = f"export.sftp.{p}".lower()
            G.node(kid, f"sftp:{p}", "export", "csv_drop", None, country=country, details={"path": p})
        else:
            layer = layer_of(lh)
            kid = f"{layer}.files/{p}".lower()
            G.node(kid, f"{lh}/Files/{p}", layer, "csv_drop", None, country=country, details={"lakehouse": lh, "path": p})
    else:
        kid = f"unresolved.sink.{ctx['name']}.{name}".lower()
        G.node(kid, str(ktype), "unresolved", "delta_table", None, details={"raw": kds})
        ctx["issues"].append(f"copy {name}: unknown sink dataset type {ktype}")

    rec["copy"] = {"source": sid, "sink": kid, "query": query}
    G.edge(sid, kid, "copy", f"{ctx['name']}/{name}", ppath, activity=name, parent=parent, query=query, sourceType=stype, sinkType=ktype,
           tableActionOption=snk.get("tableActionOption"), sourceConnection=sconn, sinkConnection=kconn, tableList=listname)
    G.edge(pid, kid, "writes", name, ppath, parent=parent)
    G.edge(pid, sid, "reads", name, ppath, parent=parent)


def describe_schedule(s):
    c = s.get("configuration", {})
    return {"enabled": s.get("enabled"), "type": c.get("type"), "times": c.get("times"), "weekdays": c.get("weekdays"),
            "interval": c.get("interval"), "startDateTime": c.get("startDateTime"), "endDateTime": c.get("endDateTime"),
            "timezone": c.get("localTimeZoneId")}


# ---------------------------------------------------------------- pipelines
folders = sorted(glob.glob("**/*.DataPipeline", recursive=True))
sched_count = 0
for folder in folders:
    plat = json.load(open(os.path.join(folder, ".platform")))
    name, lid = plat["metadata"]["displayName"], plat["config"]["logicalId"].lower()
    pid = f"pipeline.{name}"
    sched = []
    if os.path.exists(os.path.join(folder, ".schedules")):
        sched = json.load(open(os.path.join(folder, ".schedules"))).get("schedules", [])
    det = {"logicalId": lid, "schedules": [describe_schedule(s) for s in sched],
           "scheduled": any(s.get("enabled") for s in sched), "isDevFork": is_fork_name(CFG, name, folder)}
    try:
        content = json.load(open(os.path.join(folder, "pipeline-content.json")))
    except Exception as e:
        det["parseError"] = str(e); partial[folder] = f"json error {e}"
        G.node(pid, name, "pipeline", "pipeline", folder, details=det)
        continue
    props = content.get("properties", {})

    def trim(v):
        dv = val(v.get("defaultValue")) if isinstance(v, dict) else v
        if isinstance(dv, list):
            dv = [({k2: v2 for k2, v2 in x.items() if k2 != "copyActivity"} if isinstance(x, dict) else x) for x in dv]
        return dv
    det["parameters"] = {k: trim(v) for k, v in (props.get("parameters") or {}).items()}
    det["variables"] = {k: trim(v) for k, v in (props.get("variables") or {}).items()}
    n = G.node(pid, name, "pipeline", "pipeline", folder, country=detect_country(name), details=det)
    ctx = {"id": pid, "path": folder, "name": name, "activities": [], "issues": [], "foreach": [],
           "params": props.get("parameters") or {}, "vars": props.get("variables") or {}}
    walk(props.get("activities", []), ctx)
    n["details"]["activities"] = ctx["activities"]
    if ctx["issues"]:
        n["details"]["issues"] = ctx["issues"]
        partial[folder] = "; ".join(ctx["issues"])
    for s in n["details"]["schedules"]:
        sched_count += 1
        tid = f"trigger.schedule.{name}"
        G.node(tid, f"schedule {name} {s.get('type')} {s.get('times')}", "pipeline", "trigger", folder + "/.schedules", details=s)
        G.edge(tid, pid, "triggers", "schedule", folder + "/.schedules")

# ---------------------------------------------------------------- dataflows
df_count = 0
for mp in glob.glob("**/*.Dataflow/mashup.pq", recursive=True):
    folder = os.path.dirname(mp)
    plat = json.load(open(os.path.join(folder, ".platform")))
    dname = plat["metadata"]["displayName"]
    did = f"dataflow.{dname}"
    txt = open(mp, encoding="utf-8").read()
    df_count += 1
    G.node(did, dname, "dataflow", "dataflow", folder, country=detect_country(dname, folder),
           details={"logicalId": plat["config"]["logicalId"], "queries": re.findall(r'^shared (#"[^"]+"|[A-Za-z0-9_]+) =', txt, re.M)})
    for m in re.finditer(r'Sql\.Database\("([^"]+)",\s*"([^"]+)"(?:,\s*\[Query\s*=\s*"((?:[^"\\]|\\.|"")*)"\])?', txt):
        server, db, q = m.group(1), m.group(2), m.group(3) or ""
        tables = set(re.findall(r"(?:from|join)\s+\[?([A-Za-z0-9_]+)\]?\.\[?([A-Za-z0-9_]+)\]?", q, re.I))
        if not tables:
            tables = {("dbo", t) for t in re.findall(r"(?:from|join)\s+\[?([A-Za-z0-9_]+)\]?(?!\.)\b", q, re.I)}
        for sch, tbl in tables:
            sid = f"source.{db.lower()}.{sch.lower()}.{tbl.lower()}"
            G.node(sid, f"{db}.{sch}.{tbl}", "source", "sql_table", None, country=detect_country(db),
                   details={"server": server, "database": db, "schema": sch, "table": tbl})
            G.edge(sid, did, "reads", dname, folder, query=q[:2000].replace("#(lf)", "\n"))
    for m in re.finditer(r'lakehouseId = "([0-9a-f-]+)"', txt):
        lh = resolve(m.group(1))
        lhname = lh["displayName"] if lh else m.group(1)
        seg = txt[m.end(): m.end() + 1200]
        nxt = seg.find("lakehouseId =")
        seg = seg[:nxt] if nxt > 0 else seg
        names = re.findall(r'\{\[Name = "([^"]+)"\]\}', seg)
        if 'Id = "Files"' in seg and names:
            p = "/".join(names[:2])
            fid = f"{layer_of(lhname)}.files/{p}".lower()
            G.node(fid, f"{lhname}/Files/{p}", layer_of(lhname), "csv_drop", None, details={"lakehouse": lhname, "path": p})
            G.edge(fid, did, "reads", dname, folder)
    for lhid, nm in re.findall(r'_DataDestination\b[^;]*?lakehouseId = "([0-9a-f-]+)"[^;]*?(?:\{\[Name = "([^"]+)"\]\})', txt, re.S):
        lh = resolve(lhid)
        lhname = lh["displayName"] if lh else lhid
        fid = f"{layer_of(lhname)}.files/{nm}".lower()
        G.node(fid, f"{lhname}/Files/{nm}", layer_of(lhname), "csv_drop", None, details={"lakehouse": lhname, "path": nm})
        G.edge(did, fid, "writes", dname, folder)

# ---------------------------------------------------------------- semantic refresh via REST from a notebook
for nid, n in list(G.nodes.items()):
    if n["layer"] != "notebook" or not n.get("path") or not os.path.exists(os.path.join(n["path"], "notebook-content.py")):
        continue
    src = open(os.path.join(n["path"], "notebook-content.py"), encoding="utf-8", errors="replace").read()
    if "datasets" not in src and "refreshes" not in src.lower():
        continue
    ds = re.search(r'^\s*dataset_id\s*=\s*"([0-9a-f-]{36})"', src, re.M) or re.search(r'datasets/([0-9a-f-]{36})/refreshes', src)
    ws = re.search(r'^\s*workspace_id\s*=\s*"([0-9a-f-]{36})"', src, re.M) or re.search(r'groups/([0-9a-f-]{36})', src)
    if not ds:
        continue
    sm = resolve(ds.group(1))
    sid = f"semantic.{sm['displayName']}" if sm else f"semantic.dataset-{ds.group(1)}"
    G.node(sid, sm["displayName"] if sm else f"semantic model {ds.group(1)}", "semantic", "semantic_model", sm["path"] if sm else None,
           details={"datasetId": ds.group(1), "workspaceId": ws.group(1) if ws else None,
                    "note": None if sm else "refreshed via Power BI REST API from a notebook; dataset id not in this repo (deployed workspace?)"})
    G.edge(nid, sid, "refreshes", n["name"], n["path"], datasetId=ds.group(1))
    for e in list(G.edges):
        if e["to"] == nid and e["kind"] == "runs":
            G.edge(e["from"], sid, "refreshes", e["via"], e["path"], viaNotebook=n["name"])

G.dump(os.path.join(OUT, "extract-pipelines.json"))
enabled = sum(1 for n in G.nodes.values() if n["type"] == "trigger" and n["details"].get("enabled"))
print(f"platform files: {len(glob.glob('**/.platform', recursive=True))}, guid keys: {len(guid_map)}")
print(f"pipelines: {len(folders)} found / {len(folders) - len(partial)} fully parsed / {len(partial)} partial; "
      f"schedule entries: {sched_count} ({enabled} enabled); dataflows: {df_count}")
for k, v in partial.items():
    print("  PARTIAL", k, "->", v[:300])
print(f"nodes {len(G.nodes)} edges {len(G.edges)}")
print(G.layer_counts())
print(dict(Counter(e["kind"] for e in G.edges)))
print("UNRESOLVED:", [n["id"] for n in G.nodes.values() if n["id"].startswith("unresolved.")][:40])
