#!/usr/bin/env python3
"""Extractor 5: TMDL semantic models + PBIR reports -> extract-semantic.json.

Partitions: entityName / schemaName / expressionSource -> expressions.tmdl holds the
AzureStorage.DataLake OneLake URL whose lakehouse GUID matches a .platform logicalId only
after the segment-reversal transform. Calculated tables and calc groups have no Gold
source (expected unresolved). relationships.tmdl -> relationship edges; *.Report/definition.pbir
binds byPath or byConnection.

    python3 extract_semantic.py --repo <repo> --out <scratch> [--config lineage.config.json]
"""
import glob
import json
import os
import re
from collections import Counter

from lineage_common import alt_guid, layer_of_lakehouse, parse_args

a = parse_args("Extract semantic-model and report lineage")
CFG, REPO, OUT = a.cfg, a.repo, a.out
SC = CFG["semantic"]
WORKSPACE = SC.get("workspaceId")
os.chdir(REPO)
nodes, edges, summary = [], [], {}


def unq(s):
    return s.strip().strip("'")


lh_names = {}
for lp in glob.glob("**/*.Lakehouse/.platform", recursive=True):
    p = json.load(open(lp))
    lh_names[p["config"]["logicalId"].lower()] = p["metadata"]["displayName"]


def resolve_lh(guid):
    g = guid.lower()
    return lh_names.get(g) or lh_names.get(alt_guid(g) or "")


def parse_refs(expr, all_tables):
    found = set()
    for m in re.finditer(r"'([^']+)'", expr):
        if m.group(1) in all_tables:
            found.add(m.group(1))
    for t in all_tables:
        if re.search(r"(?<![\w'])" + re.escape(t) + r"(?=\s*\[|\s*[,)\s]|$)", expr):
            found.add(t)
    return found


for mdir in sorted(glob.glob(SC["modelsGlob"])):
    model = os.path.basename(mdir).replace(".SemanticModel", "")
    mid = f"semantic.{model}"
    plat = json.load(open(f"{mdir}/.platform"))
    exprs, lakehouses = {}, {}
    epath = f"{mdir}/definition/expressions.tmdl"
    if os.path.exists(epath):
        etxt = open(epath).read()
        for m in re.finditer(r"expression '?([^'=\n]+?)'? =\s*(.*?)(?=\n\texpression|\n\tlineageTag|\Z)", etxt, re.S):
            exprs[m.group(1).strip()] = m.group(2).strip()
    for name, body in exprs.items():
        g = re.search(r"onelake\.dfs\.fabric\.microsoft\.com/([0-9a-f-]+)/([0-9a-f-]+)", body)
        if g:
            lakehouses[name] = {"workspace": g.group(1), "lakehouse": g.group(2), "lakehouseItem": resolve_lh(g.group(2))}

    tables = {}
    for tf in sorted(glob.glob(f"{mdir}/definition/tables/*.tmdl")):
        txt = open(tf).read()
        tname = unq(re.search(r"^table (.+?)\s*$", txt, re.M).group(1))
        cols = re.findall(r"^\tcolumn (.+?)(?:\s*=\s*(.*))?$", txt, re.M)
        meas = re.findall(r"^\tmeasure (.+?)\s*=", txt, re.M)
        calc_items = re.findall(r"^\t\tcalculationItem (.+?)\s*=", txt, re.M)
        pm = re.search(r"^\tpartition (.+?) = (\w+)\s*\n(.*?)(?=\n\t\S|\Z)", txt, re.M | re.S)
        ptype, pbody = (pm.group(2), pm.group(3)) if pm else (None, "")
        if ptype is None and re.search(r"^\tcalculationGroup\s*$", txt, re.M):
            ptype = "calculationGroup"
        src = {"partitionType": ptype}
        if ptype == "entity":
            src["entity"] = re.search(r"entityName: (.+)", pbody).group(1).strip()
            sm = re.search(r"schemaName: (.+)", pbody)
            src["schema"] = sm.group(1).strip() if sm else None
            es = re.search(r"expressionSource: (.+)", pbody)
            src["expressionSource"] = unq(es.group(1)) if es else None
        elif ptype in ("calculated", "m"):
            sm = re.search(r"source\s*=\s*\n(.*)", pbody, re.S)
            src["expression"] = (sm.group(1) if sm else pbody).strip()
        calc_cols = [(unq(c), e) for c, e in cols if e]
        for cm in re.finditer(r"^\tcolumn (.+?) =\s*\n((?:\t\t\t.*\n?)+)", txt, re.M):
            calc_cols.append((unq(cm.group(1)), cm.group(2)))
        tables[tname] = dict(file=tf, hidden=bool(re.search(r"^\tisHidden\s*$", txt, re.M)), columns=len(cols),
                             measures=len(meas), calcItems=len(calc_items), src=src, calc_cols=calc_cols)

    rels = []
    rpath = f"{mdir}/definition/relationships.tmdl"
    if os.path.exists(rpath):
        for rm in re.finditer(r"relationship (\S+)\n((?:\t.*\n?)+)", open(rpath).read()):
            body = rm.group(2)

            def g(k, d=None):
                x = re.search(rf"^\t{k}: (.+)$", body, re.M)
                return x.group(1).strip() if x else d

            def split(c):
                m2 = re.match(r"^('([^']+)'|([^.]+))\.(.+)$", c)
                return (m2.group(2) or m2.group(3), unq(m2.group(4)))
            ft, fcol = split(g("fromColumn"))
            tt, tcol = split(g("toColumn"))
            rels.append(dict(id=rm.group(1), fromTable=ft, fromColumn=fcol, toTable=tt, toColumn=tcol,
                             fromCardinality=g("fromCardinality", "many"), toCardinality=g("toCardinality", "one"),
                             crossFilteringBehavior=g("crossFilteringBehavior", "oneDirection"),
                             isActive=not re.search(r"^\tisActive: false", body, re.M)))

    total_meas = sum(t["measures"] for t in tables.values())
    nodes.append(dict(id=mid, name=model, layer="semantic", type="semantic_model", path=mdir,
                      details=dict(model=model, logicalId=plat["config"]["logicalId"], workspace=WORKSPACE, expressions=lakehouses,
                                   tables=len(tables), measures=total_meas, relationships=len(rels))))
    resolved, unresolved, seen_ids = 0, [], set()
    for tname, t in tables.items():
        tid = f"semantic.{model}.{tname}"
        src = t["src"]
        trels = [dict(r, direction="from" if r["fromTable"] == tname else "to") for r in rels if tname in (r["fromTable"], r["toTable"])]
        d = dict(model=model, partitionType=src["partitionType"], entity=src.get("entity"), schema=src.get("schema"),
                 expressionSource=src.get("expressionSource"), columns=t["columns"], measures=t["measures"],
                 calculationItems=t["calcItems"], hidden=t["hidden"], relationships=trels, workspace=WORKSPACE)
        if src.get("expression"):
            d["expression"] = src["expression"][:600]
        nodes.append(dict(id=tid, name=tname, layer="semantic", type="semantic_table", path=t["file"], details=d))
        edges.append({"from": tid, "to": mid, "kind": "partof", "via": model, "path": t["file"]})
        if src["partitionType"] == "entity":
            lh = lakehouses.get(src["expressionSource"], {})
            item = lh.get("lakehouseItem") or ""
            layer = layer_of_lakehouse(CFG, item) if item else "unresolved"
            sch = (src.get("schema") or "dbo").lower()
            ent = src["entity"].lower()
            gid = f"{layer}.{ent}" if sch == "dbo" else f"{layer}.{sch}_{ent}"
            if layer == "gold":
                resolved += 1
            else:
                unresolved.append((tname, json.dumps(src)))
            if gid not in seen_ids:
                seen_ids.add(gid)
                nodes.append(dict(id=gid, name=src["entity"], layer=layer, type="delta_table",
                                  path=f"{item}.Lakehouse/Tables/{src.get('schema') or 'dbo'}/{src['entity']}" if item else "",
                                  details=dict(schema=src.get("schema"), entity=src["entity"], lakehouse=item,
                                               lakehouseGuid=lh.get("lakehouse"), workspace=lh.get("workspace"))))
            edges.append({"from": gid, "to": tid, "kind": "directlake", "via": model, "path": t["file"],
                          "details": dict(expression=src["expressionSource"], schema=src.get("schema"), entity=src["entity"])})
        else:
            unresolved.append((tname, f"{src['partitionType']}: {src.get('expression', '')[:100]!r}"))
        others = [x for x in tables if x != tname]
        seen = {}
        dax_src = ([("partition", src["expression"])] if src.get("expression") else []) + [(f"column:{c}", e) for c, e in t["calc_cols"]]
        for kind, expr in dax_src:
            for ref in parse_refs(expr, others):
                seen.setdefault(ref, []).append(kind)
        for ref, kinds in seen.items():
            edges.append({"from": tid, "to": f"semantic.{model}.{ref}", "kind": "dax", "via": model, "path": t["file"], "details": dict(references=kinds)})
    for r in rels:
        edges.append({"from": f"semantic.{model}.{r['fromTable']}", "to": f"semantic.{model}.{r['toTable']}", "kind": "relationship",
                      "via": model, "path": rpath, "details": {k: v for k, v in r.items() if k not in ("fromTable", "toTable")}})
    summary[model] = dict(tables=len(tables), measures=total_meas, relationships=len(rels), resolvedGold=resolved,
                          unresolved=unresolved, lakehouses=lakehouses, hidden=[t for t, v in tables.items() if v["hidden"]])

# ---------------------------------------------------------------- reports
model_names = {n["name"] for n in nodes if n["type"] == "semantic_model"}
rep_summary = []
for pbir in sorted(glob.glob("**/*.Report/definition.pbir", recursive=True)):
    rdir = os.path.dirname(pbir)
    name = os.path.basename(rdir).replace(".Report", "").replace("&#47;", "/")
    ds = json.load(open(pbir)).get("datasetReference", {})
    mname = None
    if "byPath" in ds:
        target = os.path.normpath(os.path.join(rdir, ds["byPath"]["path"]))
        mname = os.path.basename(target).replace(".SemanticModel", "")
        if not os.path.isdir(target):
            mname += " (missing path)"
    elif "byConnection" in ds:
        cm = re.search(r"initial catalog=([^;]+)", ds["byConnection"].get("connectionString", ""))
        mname = cm.group(1) if cm else "byConnection"
    rid = f"report.{name}"
    folder = os.path.dirname(rdir)
    nodes.append(dict(id=rid, name=name, layer="report", type="report", path=rdir,
                      details=dict(model=mname, folder=folder, datasetReference=ds, workspace=WORKSPACE,
                                   sandbox=folder.split("/")[0] in SC["sandboxReportDirs"])))
    if mname in model_names:
        edges.append({"from": f"semantic.{mname}", "to": rid, "kind": "binds", "via": mname, "path": pbir})
    rep_summary.append((rdir, mname))

json.dump(dict(nodes=nodes, edges=edges), open(os.path.join(OUT, "extract-semantic.json"), "w"), indent=1)
print(json.dumps(summary, indent=1, default=str))
ids = [n["id"] for n in nodes]
print("reports:", len(rep_summary), "bindings:", dict(Counter(m for _, m in rep_summary)))
print("dup node ids:", {i for i in ids if ids.count(i) > 1})
print(dict(Counter(e["kind"] for e in edges)), dict(Counter(n["type"] for n in nodes)))
