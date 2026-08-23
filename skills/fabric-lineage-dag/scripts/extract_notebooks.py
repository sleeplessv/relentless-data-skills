#!/usr/bin/env python3
"""Extractor 4: notebook code -> extract-notebooks.json + notebook-inventory.json.

For every *.Notebook/notebook-content.py: spark.read.table / spark.table / DeltaTable.forName,
SQL FROM/JOIN/MERGE INTO/INSERT INTO/CREATE (python strings and %%sql), saveAsTable,
.save/.load(abfss...), %run and notebookutils.notebook.run. Layer resolution order: lakehouse
GUID in the path, Lakehouse.Schema.Table, schema hints, the notebook's default lakehouse, then
a catalog built from the config JSONs. f-string names become unresolved.{template} after one
level of variable substitution.

    python3 extract_notebooks.py --repo <repo> --out <scratch> [--config lineage.config.json]
"""
import collections
import glob
import json
import os
import re

from lineage_common import build_guid_map, lakehouse_layers, parse_args

a = parse_args("Extract table reads/writes/calls from notebook code")
CFG, REPO, OUT = a.cfg, a.repo, a.out
NC = CFG["notebooks"]
LH_NAME = CFG["lakehouseNameLayers"]
SCHEMA_LAYER_HINT = {k.lower(): v for k, v in NC["schemaLayerHints"].items()}
KNOWN_SCHEMAS = {s.lower() for s in NC["knownSchemas"]}
UNQUAL_RE = re.compile(NC["unqualifiedTablePrefixes"]) if NC.get("unqualifiedTablePrefixes") else None
os.chdir(REPO)
guid_map = build_guid_map(REPO)
LH_GUID = lakehouse_layers(CFG, guid_map)

SQL_KW = {"select", "where", "set", "values", "as", "on", "and", "or", "not", "if", "exists", "delta", "table", "view",
          "temp", "temporary", "into", "from", "join", "left", "right", "inner", "outer", "full", "cross", "lateral", "using",
          "with", "when", "matched", "then", "update", "insert", "delete", "only", "this", "that", "each", "which", "all",
          "source", "target", "src", "tgt", "dbo", "type", "name", "null", "true", "false", "json", "csv", "parquet",
          "file", "files", "config", "order", "group", "columns", "rows", "schema", "database", "string", "int", "date",
          "list", "dict", "df", "sql", "query", "case", "else", "end", "distinct", "limit", "having", "union", "except",
          "lakehouse", "fabric", "onelake", "gold", "silver", "bronze", "metadata", "layer", "partition", "location",
          "history", "detail", "step", "log", "run", "status", "error", "result", "main", "cache", "plan", "explain",
          "prod", "test", "dev", "function", "python", "pyspark", "spark", "notebook", "pipeline", "tables", "the", "a", "to"}


def layer_from_guid(s):
    for g, l in LH_GUID.items():
        if g[:8] in s:
            return l
    return None


def tid(layer, schema, table):
    table = table.strip("`\"' ").lower()
    schema = (schema or "").strip("`\"' ").lower()
    return f"{layer}.{table}" if schema in ("", "dbo") else f"{layer}.{schema}_{table}"


# ---------------------------------------------------------------- catalog from config JSONs
catalog = {}


def add_cat(name, layer, schema):
    if not name or not isinstance(name, str) or "{" in name:
        return
    layer = LH_NAME.get((layer or "").lower())
    if layer:
        catalog.setdefault(name.lower(), (layer, (schema or "").lower()))


def norm_mapping(dm, f):
    """Gold configs write sourceLayer=<schema> sourceDatabase=<lakehouse>; swap to (lakehouse, schema)."""
    dm = {k: (v if isinstance(v, str) else None) for k, v in dm.items()}
    sl, sd, tl, td = dm.get("sourceLayer"), dm.get("sourceDatabase"), dm.get("targetLayer"), dm.get("targetDatabase")
    if sl and sl.lower() not in LH_NAME and sd and sd.lower() in LH_NAME:
        sl, sd = sd, sl
    if not tl and td and td.lower() in LH_NAME:
        tl, td = td, None
    if tl and tl.lower() in LH_NAME and td and td.lower() in LH_NAME:
        td = None
    if td is None and tl and tl.lower() == "gold":
        td = "Dimension" if "/Dim/" in f else "Fact"
    return sl, sd, tl, td


config_files = glob.glob("files/config/**/*.json", recursive=True)
for f in config_files:
    try:
        j = json.load(open(f))
    except Exception:
        continue
    dm = j.get("databaseMapping") or {}
    if not isinstance(dm, dict):
        continue
    sl, sd, tl, td = norm_mapping(dm, f)
    for t in j.get("tables", []):
        add_cat(t.get("targetTable"), tl, td)
        add_cat(t.get("sourceTable") if isinstance(t.get("sourceTable"), str) else None, sl, sd)
    add_cat(dm.get("sourceTableName") if isinstance(dm.get("sourceTableName"), str) else None, sl, sd)
config_index = {os.path.basename(f).lower(): f for f in config_files}

# ---------------------------------------------------------------- notebook inventory
nbs = []
for plat in glob.glob("**/*.Notebook/.platform", recursive=True):
    d = os.path.dirname(plat)
    p = json.load(open(plat))
    nbs.append({"dir": d, "rel": d, "displayName": p["metadata"]["displayName"], "logicalId": p["config"]["logicalId"]})
by_name = {n["displayName"].lower(): n for n in nbs}
by_name_nopy = {n["displayName"].lower().removesuffix(".py"): n for n in nbs}


def find_nb(name):
    k = name.strip().strip("\"'").split("/")[-1].strip().lower()
    return by_name.get(k) or by_name_nopy.get(k.removesuffix(".py")) or by_name.get(k + ".py")


def is_fork(n):
    rel, dn = n["rel"], n["displayName"]
    if any(rel.startswith(d) for d in NC["forkDirs"]):
        return True
    if re.search(CFG["forkDirPattern"], rel, re.I):
        return True
    if re.search(r"(?i)\b(test|stage)", dn[:6]) or re.search(r"(?i)(bkp|copy|_copy|\d{8})", dn):
        return True
    if any(dn.lower().startswith(p.lower()) for p in NC["forkNamePrefixes"]):
        return True
    return False


# ---------------------------------------------------------------- name / path resolution
LAYER_VAR = r"(?i)(bronze|silver|gold|meta|metadata)\w*(?:path|base)\w*(?:\.rstrip\('/'\))?\}/?([A-Za-z]+)/([A-Za-z_]+)/?$"


def path_to_id(path, default_layer):
    raw = path
    if "{" in path:
        m = re.search(LAYER_VAR, path)
        if m:
            return tid(LH_NAME.get(m.group(1).lower(), m.group(1).lower()), m.group(2), m.group(3)), "delta_table"
        if not re.search(r"Tables/[A-Za-z]", path):
            return "unresolved." + re.sub(r"\s+", "", raw), "delta_table"
    layer = layer_from_guid(path)
    if not layer and "Tables" in path:
        m = re.search(r"(?i)(bronze|silver|gold|metadata|meta|staging)", path.split("Tables")[0])
        if m:
            layer = LH_NAME.get(m.group(1).lower(), "awsstaging")
    m = re.search(r"Tables/([^/`'\"]+)(?:/([^/`'\"]+))?/?$", path) or re.search(r"\}/?([A-Za-z]+)/([A-Za-z_]+)/?$", path)
    if m and m.group(1) and "{" not in (m.group(1) + (m.group(2) or "")):
        schema, table = (m.group(1), m.group(2)) if m.group(2) else (None, m.group(1))
        if layer is None and schema:
            layer = SCHEMA_LAYER_HINT.get(schema.lower())
        if layer is None:
            c = catalog.get(table.lower())
            layer = c[0] if c else default_layer
        if layer:
            return tid(layer, schema, table), "delta_table"
    if "Files/" in path and "{" not in path:
        return f"file.{layer or 'unknown'}:{path.split('Files/')[1].rstrip('/')}", "file"
    return "unresolved." + re.sub(r"\s+", "", raw), "delta_table"


def subst(name, ctx, depth=0):
    if depth > 3:
        return name
    new = re.sub(r"\{([A-Za-z_]\w*)\}", lambda m: ctx["vars"].get(m.group(1), m.group(0)), name)
    return subst(new, ctx, depth + 1) if new != name else new


PY_MODULES = {"pyspark", "concurrent", "datetime", "os", "typing", "collections", "functools", "itertools", "tables", "delta"}


def name_to_id(name, default_layer, ctx):
    name = name.strip().strip("`\"'").rstrip(";,)")
    if "{" in name:
        name2 = subst(name, ctx)
        if "{" not in name2 or re.search(r"Tables/|/[A-Za-z]+/[A-Za-z_]+$", name2):
            name = name2
    if "{" in name and not name.lower().startswith("delta."):
        m = re.search(LAYER_VAR, name)
        if m:
            return tid(LH_NAME.get(m.group(1).lower(), m.group(1).lower()), m.group(2), m.group(3))
    if not name or "$" in name or name.startswith("%") or ("{" in name and not name.lower().startswith("delta.")):
        return ("unresolved." + name.replace(" ", "")) if name else None
    if name.lower().startswith("delta."):
        p = name[6:].strip("`")
        if "{" in p:
            m = re.search(LAYER_VAR, p)
            return tid(LH_NAME.get(m.group(1).lower(), m.group(1).lower()), m.group(2), m.group(3)) if m else "unresolved." + name.replace(" ", "")
        return path_to_id(p, default_layer)[0]
    parts = [p.strip("`") for p in name.split(".")]
    if parts[0].lower() in PY_MODULES:
        return None
    if len(parts) == 3:
        lh, sch, tb = parts
        layer = LH_NAME.get(lh.lower())
        return tid(layer, sch, tb) if layer else f"unresolved.{name}"
    if len(parts) == 2:
        a_, b = parts
        if a_.lower() in LH_NAME:
            return tid(LH_NAME[a_.lower()], None, b)
        if a_.lower() in KNOWN_SCHEMAS:
            layer = SCHEMA_LAYER_HINT.get(a_.lower())
            if not layer:
                c = catalog.get(b.lower())
                if c and c[1] == a_.lower():
                    layer = c[0]
                elif a_.lower() == "staging":
                    layer = "awsstaging"
                else:
                    layer = default_layer if default_layer in ("bronze", "silver") else "silver"
            return tid(layer, a_, b)
        return f"unresolved.{name}"
    if len(parts) == 1:
        t = parts[0]
        if t.lower() in ctx["views"] or t.lower() in SQL_KW or len(t) < 3 or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t):
            return None
        c = catalog.get(t.lower())
        if c:
            return tid(c[0], c[1], t)
        if default_layer and UNQUAL_RE and UNQUAL_RE.match(t):
            return tid(default_layer, None, t) + "?"  # unqualified, unsure
        return None
    return None


# ---------------------------------------------------------------- walk notebooks
nodes, edges, inventory = {}, [], []


def add_node(nid, ntype="delta_table", **details):
    if nid not in nodes:
        layer = nid.split(".")[0]
        if ntype == "file":
            layer = nid[5:].split(":")[0]
            layer = "source" if layer == "unknown" else layer
        nodes[nid] = {"id": nid, "name": nid.split(".", 1)[1], "layer": layer, "type": ntype, "path": "", "details": {}}
    nodes[nid]["details"].update({k: v for k, v in details.items() if v})


NAME = r"((?:delta\.`[^`]+`)|(?:`[^`]+`(?:\.`?[\w{}]+`?)*)|(?:[\w{}$]+(?:\.[\w{}$]+){0,2}))"
WRITE_PATTERNS = [("merge", r"merge\s+into"), ("insert", r"insert\s+(?:into|overwrite)(?:\s+table)?"), ("update", r"update"),
                  ("delete", r"delete\s+from"), ("drop", r"drop\s+table(?:\s+if\s+exists)?"),
                  ("create", r"create\s+(?:or\s+replace\s+)?(?:external\s+)?table(?:\s+if\s+not\s+exists)?"),
                  ("truncate", r"truncate\s+table"), ("alter", r"alter\s+table"), ("optimize", r"optimize"), ("vacuum", r"vacuum")]

for n in nbs:
    src = open(f"{n['dir']}/notebook-content.py", encoding="utf-8", errors="replace").read()
    meta_hdr = "\n".join(l[7:] for l in src.split("\n# CELL")[0].splitlines() if l.startswith("# META "))
    default_lh = (re.search(r'"default_lakehouse":\s*"([^"]+)"', meta_hdr) or [None, None])[1]
    default_name = (re.search(r'"default_lakehouse_name":\s*"([^"]+)"', meta_hdr) or [None, None])[1]
    known = [layer_from_guid(g) or g for g in re.findall(r'"id":\s*"([0-9a-f-]{36})"', meta_hdr)]
    default_layer = layer_from_guid(default_lh) if default_lh else LH_NAME.get((default_name or "").lower())
    conf = re.search(r"%%configure.*?(?=\n# (?:CELL|METADATA|MARKDOWN))", src, re.S)
    configure = re.sub(r"^# MAGIC ?", "", conf.group(0), flags=re.M)[:600] if conf else None
    if configure and not default_layer:
        default_layer = layer_from_guid(configure)
    pm = re.search(r"# PARAMETERS CELL \*+\n(.*?)(?=\n# (?:CELL|METADATA|MARKDOWN) \*+)", src, re.S)
    params = "\n".join(l for l in pm.group(1).splitlines() if not l.startswith("# META") and l.strip())[:1500] if pm else None
    code = "\n".join(l for l in src.splitlines() if not l.startswith("# META"))
    code = re.sub(r"# MARKDOWN \*+\n.*?(?=\n# (?:CELL|PARAMETERS CELL) \*+|\Z)", "", code, flags=re.S)
    code_nomagic = re.sub(r"^# MAGIC ?", "", code, flags=re.M)
    code_nc = "\n".join(l for l in code_nomagic.splitlines() if not l.lstrip().startswith(("#", "--")))

    ctx = {"views": set(), "vars": {}}
    for m in re.finditer(r"^\s*([A-Za-z_]\w*)\s*=\s*f?[\"']([^\"'\n]+)[\"']\s*$", code_nc, re.M):
        ctx["vars"].setdefault(m.group(1), m.group(2))
    for pat in (r"createOrReplaceTempView\(\s*[\"']([^\"']+)[\"']",
                r"(?i)create\s+(?:or\s+replace\s+)?(?:global\s+)?temp(?:orary)?\s+view\s+(?:if\s+not\s+exists\s+)?([A-Za-z_][\w]*)",
                r"(?i)(?:with|,)\s+([A-Za-z_][\w]*)\s+as\s*\(", r"(?i)\b([A-Za-z_][\w]*)\s+as\s*\(\s*select", r"(?i)\b(view\w+|vw\w+)\b"):
        for v in re.findall(pat, code_nc):
            ctx["views"].add(v.lower())

    reads, writes, calls, unresolved, viaconfig = set(), set(), set(), set(), set()
    abfss = set(re.findall(r"abfss://[^\s\"'`,)\]]+", code_nc))

    def rec(kind, ident, note=None):
        if not ident:
            return
        unsure = ident.endswith("?")
        ident = ident.rstrip("?")
        if ident.startswith("unresolved.") and re.search(r"(?i)view|\bvw|^unresolved\.tables$", ident):
            return
        tail = ident.split(".", 1)[1].split("_")[-1] if not ident.startswith("unresolved.") else ""
        if tail and (tail in by_name_nopy or tail + ".py" in by_name):
            return  # a notebook name, not a table
        if unsure and "_" in ident.split(".", 1)[1]:
            return
        if unsure:
            nm = ident.split(".", 1)[1]
            for prefix, schema in SCHEMA_LAYER_HINT.items():
                if nm.startswith(prefix) or nm.startswith("fg" + prefix):
                    ident, unsure = f"{schema}.{prefix}_{nm}" if prefix in ("dimension", "fact") else ident, False
                    break
        if ident.startswith("unresolved."):
            unresolved.add(ident)
        (reads if kind == "reads" else writes).add(ident)
        add_node(ident, "file" if ident.startswith("file.") else "delta_table", unqualified=unsure or None)
        edges.append({"from": f"notebook.{n['displayName']}", "to": ident, "kind": kind, "via": n["displayName"], "path": n["rel"],
                      **({"note": note} if note else {})})

    for m in re.finditer(r"(?i)\b(?:from|join)\s+" + NAME, code_nc):
        nm = m.group(1)
        if nm.lower() in ("(", "select") or nm.startswith("("):
            continue
        rec("reads", name_to_id(nm, default_layer, ctx))
    for kw, pat in WRITE_PATTERNS:
        for m in re.finditer(r"(?i)(?<![\w.])" + pat + r"\s+" + NAME, code_nc):
            nm = m.group(1)
            if nm.lower() in ("set", "*", "when"):
                continue
            rec("writes", name_to_id(nm, default_layer, ctx), kw)
    for m in re.finditer(r"(?:spark\.read\.table|spark\.table|DeltaTable\.forName\(\s*spark\s*,)\s*\(?\s*(f?[\"'])([^\"']+)[\"']", code_nc):
        rec("reads", name_to_id(m.group(2), default_layer, ctx))
    for m in re.finditer(r"\.saveAsTable\(\s*(f?[\"'])([^\"']+)[\"']", code_nc):
        rec("writes", name_to_id(m.group(2), default_layer, ctx), "saveAsTable")
    for m in re.finditer(r"(?:spark\.read\.table|spark\.table|\.saveAsTable)\(\s*([A-Za-z_][\w.\[\]\"']*)\s*\)", code_nc):
        rec("writes" if "saveAsTable" in m.group(0) else "reads", "unresolved.{" + m.group(1) + "}")
    for m in re.finditer(r"(?:DeltaTable\.forPath\(\s*spark\s*,|\.load\(|\.save\(|\.parquet\(|\.csv\(|\.json\()\s*(f?[\"'])([^\"']+)[\"']", code_nc):
        p = subst(m.group(2), ctx) if "{" in m.group(2) else m.group(2)
        kind = "writes" if ".save(" in m.group(0) else "reads"
        if kind == "reads" and re.search(r"\.(csv|json|parquet|xlsx)$|/Files/", p) and "Tables" not in p:
            nid = f"file.{layer_from_guid(p) or default_layer or 'unknown'}:{p.split('Files/')[-1] if 'Files/' in p else p}"
            rec("reads", nid if "{" not in p else "unresolved." + p.replace(" ", ""))
            continue
        rec(kind, path_to_id(p, default_layer)[0], "path")
    for m in re.finditer(r"(?:DeltaTable\.forPath\(\s*spark\s*,|\.load\(|\.save\()\s*([A-Za-z_][\w.]*)\s*[,)]", code_nc):
        v = "{" + m.group(1) + "}"
        v2 = subst(v, ctx)
        kind = "writes" if ".save(" in m.group(0) else "reads"
        if v2 != v and ("{" not in v2 or re.search(r"(?i)(path|base)\w*\}", v2)):
            rec(kind, path_to_id(v2, default_layer)[0], "path-var")
        else:
            rec(kind, "unresolved." + v, "path-var")
    for m in re.finditer(r"^\s*%run\s+([^\s#]+)", code_nomagic, re.M):
        t = find_nb(m.group(1))
        target = f"notebook.{t['displayName']}" if t else f"notebook.{m.group(1).split('/')[-1]}"
        calls.add(target)
        edges.append({"from": f"notebook.{n['displayName']}", "to": target, "kind": "calls", "via": n["displayName"], "path": n["rel"],
                      **({} if t else {"note": "%run target not found in repo"})})
    for m in re.finditer(r"(?:notebookutils|mssparkutils)\.notebook\.run\(\s*(f?[\"']([^\"']+)[\"']|[\w\[\]\"'.]+)", code_nc):
        nm = m.group(2)
        t = find_nb(nm) if nm else None
        target = f"notebook.{t['displayName']}" if t else (f"notebook.{nm}" if nm else "unresolved.notebook.{" + m.group(1) + "}")
        calls.add(target)
        edges.append({"from": f"notebook.{n['displayName']}", "to": target, "kind": "calls", "via": n["displayName"], "path": n["rel"], "note": "notebookutils.notebook.run"})
    # config-driven: a notebook naming a config JSON reads/writes what that config declares
    for m in re.finditer(r"[\"']([\w]+\.json)[\"']", code_nc):
        cf = config_index.get(m.group(1).lower())
        if not cf:
            continue
        try:
            j = json.load(open(cf))
        except Exception:
            continue
        dm = j.get("databaseMapping") or {}
        if not isinstance(dm, dict) or not dm:
            continue
        sl, sd, tl, td = norm_mapping(dm, cf)
        for t in j.get("tables", []):
            st = t.get("sourceTable") or dm.get("sourceTableName")
            for s in (st if isinstance(st, list) else [st]):
                if s and sl and LH_NAME.get(sl.lower()):
                    rec("reads", tid(LH_NAME[sl.lower()], sd, s), f"via config {m.group(1)}")
                    viaconfig.add(tid(LH_NAME[sl.lower()], sd, s))
            tt = t.get("targetTable")
            if tt and tl and LH_NAME.get(tl.lower()):
                rec("writes", tid(LH_NAME[tl.lower()], td, tt), f"via config {m.group(1)}")
                viaconfig.add(tid(LH_NAME[tl.lower()], td, tt))

    fork = is_fork(n)
    nid = f"notebook.{n['displayName']}"
    nodes[nid] = {"id": nid, "name": n["displayName"], "layer": "notebook", "type": "notebook", "path": n["rel"],
                  "details": {"logicalId": n["logicalId"], "lakehouse": default_layer, "defaultLakehouseId": default_lh,
                              "knownLakehouses": known, "isFork": fork, "configure": configure, "params": params,
                              "abfssPaths": sorted(abfss)[:20], "unresolvedRefs": sorted(unresolved), "resolvedViaConfig": sorted(viaconfig)}}
    inventory.append({"displayName": n["displayName"], "logicalId": n["logicalId"], "path": n["rel"], "isFork": fork,
                      "lakehouse": default_layer, "reads": sorted(reads), "writes": sorted(writes), "calls": sorted(calls)})

seen, ded = set(), []
for e in edges:
    k = (e["from"], e["to"], e["kind"])
    if k not in seen:
        seen.add(k); ded.append(e)
edges = ded
for e in edges:
    if e["to"] not in nodes:
        add_node(e["to"], "notebook" if e["to"].startswith("notebook.") else "delta_table")
        if e["to"].startswith("notebook."):
            nodes[e["to"]]["layer"] = "notebook"
            nodes[e["to"]]["details"]["missingInRepo"] = True

json.dump({"nodes": list(nodes.values()), "edges": edges}, open(os.path.join(OUT, "extract-notebooks.json"), "w"), indent=1)
json.dump(sorted(inventory, key=lambda x: x["path"]), open(os.path.join(OUT, "notebook-inventory.json"), "w"), indent=1)

tot = len(inventory)
resolved = sum(1 for i in inventory if any(not r.startswith("unresolved.") for r in i["reads"] + i["writes"]))
only_unres = sum(1 for i in inventory if (i["reads"] or i["writes"]) and all(r.startswith("unresolved.") for r in i["reads"] + i["writes"]))
none = sum(1 for i in inventory if not i["reads"] and not i["writes"])
forks = sum(1 for i in inventory if i["isFork"])
print(f"notebooks={tot} resolvedRW={resolved} onlyUnresolved={only_unres} noRW={none} forks={forks} live={tot - forks}")
print(f"nodes={len(nodes)} edges={len(edges)} tableNodes={sum(1 for v in nodes.values() if v['type'] == 'delta_table')}")
print("lakehouse GUIDs known:", {k: v for k, v in LH_GUID.items() if len(k) == 36})
print("unqualified-unsure:", sorted(k for k, v in nodes.items() if v["details"].get("unqualified"))[:40])
