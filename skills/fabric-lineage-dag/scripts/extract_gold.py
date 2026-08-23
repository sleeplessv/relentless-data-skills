#!/usr/bin/env python3
"""Extractor 3: JSON-config-driven Gold layer + wrapper notebooks -> extract-gold.json.

Orchestration JSONs list steps; table JSONs name source Silver tables, the target, and an
`additionalProcedure` (a FUNCTION name resolved via globals(), never a notebook name). A
wrapper is wired when the Gold wrapper notebook `%run`s a notebook that defines that
function; otherwise the config + notebook are orphaned. Hand-written loaders get their
sources from config-declared Silver tables plus qualified names in their SQL, and can be
overridden by `gold.handWritten` in lineage.config.json.

    python3 extract_gold.py --repo <repo> --out <scratch> [--config lineage.config.json]
"""
import glob
import json
import os
import re

from lineage_common import Graph, parse_args, table_id

a = parse_args("Extract config-driven Gold lineage")
CFG, REPO, OUT = a.cfg, a.repo, a.out
GC = CFG["gold"]
WRAPPER = GC["wrapperNotebook"]
os.chdir(REPO)
G = Graph()

# ---------------------------------------------------------------- displayName -> folder for Gold notebooks
disp = {}
for g in GC["notebookGlobs"]:
    for pf in glob.glob(g, recursive=True):
        disp[json.load(open(pf))["metadata"]["displayName"]] = os.path.dirname(pf)


def nb_src(dn):
    p = disp.get(dn)
    return open(os.path.join(p, "notebook-content.py"), encoding="utf-8", errors="replace").read() if p else ""


# ---------------------------------------------------------------- wrapper %run list and the functions each defines
wrap = nb_src(WRAPPER)
runs = re.findall(r"^%run \./(\S+)", wrap, re.M) if wrap else []
if not wrap:
    print(f"WARNING: wrapper notebook {WRAPPER} not found under {GC['notebookGlobs']}")
FUNCS = {}
for r_ in runs:
    for fn in re.findall(r"^def (\w+)", nb_src(r_), re.M):
        FUNCS.setdefault(fn, r_)
ALL_FUNCS = {}
for dn in disp:
    for fn in re.findall(r"^def (\w+)", nb_src(dn), re.M):
        ALL_FUNCS.setdefault(fn, dn)


def fn_name(proc):
    return proc.split(".")[0]


G.node(f"notebook.{WRAPPER}", WRAPPER, "notebook", "notebook", disp.get(WRAPPER),
       details={"role": "Gold entry point", "runOrder": runs,
                "dispatch": "config additionalProcedure is a function name resolved via globals() from the %run'd notebooks"})

# ---------------------------------------------------------------- orchestration files
cfg_files = sorted({f for g in GC["configGlobs"] for f in glob.glob(g, recursive=True)})
orch, table_cfgs, rules = {}, [], []
for f in cfg_files:
    try:
        d = json.load(open(f))
    except Exception as e:
        print("SKIP invalid JSON", f, e)
        continue
    if "etlTasks" in d:
        orch[f] = d
    elif d.get("databaseMapping"):
        table_cfgs.append((f, d))
    else:
        rules.append((f, d))

regs = {}
for rel, d in orch.items():
    base = os.path.basename(rel)
    G.node(f"config.{base}", base, "gold", "config", rel,
           details={"integrationName": d.get("integrationName"), "orchestration": True,
                    "fork": bool(re.search(GC["orchestrationForkPattern"], base, re.I)),
                    "pipeline": GC["orchestrationPipelines"].get(base),
                    "steps": [{"stepNumber": t.get("stepNumber"), "procedureName": t.get("procedureName"),
                               "critical": t.get("critical")} for t in d["etlTasks"]]})
    for t in d["etlTasks"]:
        regs.setdefault(os.path.basename(t["procedureName"]), []).append(
            {"orchestration": rel, "stepNumber": t.get("stepNumber"), "critical": t.get("critical")})

for f, d in rules:
    base = os.path.basename(f)
    G.node(f"config.{base}", base, "gold", "config", f, details={"kind": "rules", "keys": list(d.keys())[:20]})

# ---------------------------------------------------------------- table configs
STORE_SCHEMA, STORE_TABLES = GC["storeMappingSchema"], GC["storeMappingTables"]
partner_re = re.compile(GC["partnerPattern"]) if GC.get("partnerPattern") else None
NAME_Q = re.compile(r"(?i)\b(?:from|join)\s+(?:delta\.`[^`]*/(Dimension|Fact)/([A-Za-z_]+)/?`|(Gold|Silver)\.([A-Za-z_]+)\.([A-Za-z_]+))")

for rel, d in table_cfgs:
    base = os.path.basename(rel)
    dm = d["databaseMapping"]
    fork = bool(re.search(GC["orchestrationForkPattern"], base, re.I))
    for t in d.get("tables", []):
        tgt = t["targetTable"]
        schema = "Dimension" if dm.get("targetLayer") == "Dimension" else (dm.get("targetDatabase") if dm.get("targetDatabase") not in (None, "Gold") else "Fact")
        tgt_id = table_id("gold", schema, tgt)
        proc = dm.get("additionalProcedure") or ""
        wired = fn_name(proc) in FUNCS if proc else None
        defining = FUNCS.get(fn_name(proc)) or ALL_FUNCS.get(fn_name(proc)) if proc else None
        details = {"configPath": rel, "sourceLayer": dm.get("sourceLayer"), "sourceDatabase": dm.get("sourceDatabase"),
                   "partitionColumn": t.get("partitionColumn"), "active": t.get("active"), "fork": fork,
                   "registeredIn": regs.get(base, []),
                   "pipeline": [GC["orchestrationPipelines"].get(os.path.basename(r["orchestration"])) for r in regs.get(base, [])
                                if GC["orchestrationPipelines"].get(os.path.basename(r["orchestration"]))]}
        if proc:
            details.update({"additionalProcedure": proc, "wrapperNotebook": WRAPPER, "wiredInWrapper": wired,
                            "definingNotebook": defining, "order": runs.index(defining) if wired and defining in runs else None})
            if defining is None:
                details["note"] = f"additionalProcedure {proc} defined by no notebook in repo"
            elif not wired:
                details["note"] = f"{defining} defines {fn_name(proc)} but {WRAPPER} never %runs it -> orphaned"
        keys = {k: dm[k] for k in ("naturalKeyColumns", "naturalKeySourceColumns", "surrogateKeyColumn", "hashKeyColumn",
                                   "storeCodeColumn", "integrationPartnerId", "dateColumn", "sourceTableName") if k in dm}
        for k in ("targetTableSurrogateKeys", "sourceColumnsToCombine"):
            if t.get(k):
                keys[k] = t[k]
        details["keys"] = keys
        details["columnCount"] = len(t.get("columns", []) or t.get("sourceIncludeColumns", []))
        partner = None
        if partner_re and dm.get("sourceLayer") == "Partners":
            m = partner_re.match(tgt)
            partner = m.group(1) if m else None
        G.node(tgt_id, tgt, "gold", "delta_table", rel, partner=partner, loadType=t.get("loadType"), details=details)
        G.node(f"config.{base}", base, "gold", "config", rel, details={"targetTable": tgt_id, "additionalProcedure": proc or None})
        via = proc if proc else f"{WRAPPER} (generic dim engine)"
        src_layers = dm.get("sourceLayer") if isinstance(dm.get("sourceLayer"), list) else [dm.get("sourceLayer")]
        src_schema = src_layers[0]
        declared = []
        if "sourceTable" in t:
            declared = t["sourceTable"] if isinstance(t["sourceTable"], list) else [t["sourceTable"]]
        elif dm.get("sourceTableName"):
            declared = [dm["sourceTableName"]]
        src_layer = "gold" if (dm.get("sourceDatabase") or "").lower() == "gold" else "silver"
        for st in declared:
            sid = table_id(src_layer, src_schema, st)
            G.node(sid, st, src_layer, "delta_table", None, details={"schema": src_schema})
            G.edge(sid, tgt_id, "transform", via, rel)
        if dm.get("storeCodeColumn"):
            for x in STORE_TABLES:
                xid = table_id("silver", STORE_SCHEMA, x)
                G.node(xid, x, "silver", "delta_table", None, details={"schema": STORE_SCHEMA})
                G.edge(xid, tgt_id, "transform", via, rel)
            details["storeMapping"] = f"src.{dm['storeCodeColumn']} -> {STORE_SCHEMA}.{' -> '.join(STORE_TABLES)} (SCD2) -> SkStoreId"
        # hand-written loader: qualified names in its SQL (unqualified names are temp views over the declared tables)
        if defining:
            src = nb_src(defining)
            for m in NAME_Q.finditer(src):
                if m.group(1):
                    sid = table_id("gold", m.group(1), m.group(2))
                    G.node(sid, m.group(2), "gold", "delta_table", None, details={"schema": m.group(1)})
                else:
                    layer = m.group(3).lower()
                    sid = table_id(layer, m.group(4), m.group(5))
                    G.node(sid, m.group(5), layer, "delta_table", None, details={"schema": m.group(4)})
                if sid != tgt_id:
                    G.edge(sid, tgt_id, "transform", defining, rel)
            G.node(f"notebook.{defining}", defining, "notebook", "notebook", disp.get(defining),
                   details={"configPath": rel, "target": tgt_id, "wiredInWrapper": wired, "order": runs.index(defining) if defining in runs else None})
            G.edge(f"notebook.{defining}", tgt_id, "writes", defining, rel)

# ---------------------------------------------------------------- curated hand-written overrides
for h in GC.get("handWritten", []):
    tgt_id = table_id("gold", h["targetSchema"], h["targetTable"])
    dn = h["notebook"]
    wired = dn in runs
    G.node(f"notebook.{dn}", dn, "notebook", "notebook", disp.get(dn),
           details={"handWritten": True, "configPath": h.get("configPath"), "target": tgt_id, "wiredInWrapper": wired,
                    "order": runs.index(dn) if wired else None, "note": h.get("note")})
    G.node(tgt_id, h["targetTable"], "gold", "delta_table", h.get("configPath"), details={"handWrittenNotebook": dn})
    G.edge(f"notebook.{dn}", tgt_id, "writes", dn, h.get("configPath"))
    for layer, sch, st in h.get("sources", []):
        sid = table_id(layer, sch, st)
        G.node(sid, st, layer, "delta_table", None, details={"schema": sch})
        G.edge(sid, tgt_id, "transform", dn, h.get("configPath"))

# ---------------------------------------------------------------- orchestration -> config "runs", wrapper run edges
for rel, d in orch.items():
    for t in d["etlTasks"]:
        b = os.path.basename(t["procedureName"])
        if f"config.{b}" in G.nodes:
            G.edge(f"config.{os.path.basename(rel)}", f"config.{b}", "runs", WRAPPER, rel)
for r_ in runs:
    G.node(f"notebook.{r_}", r_, "notebook", "notebook", disp.get(r_), details={"wiredInWrapper": True, "order": runs.index(r_), "missingInRepo": r_ not in disp or None})
    G.edge(f"notebook.{WRAPPER}", f"notebook.{r_}", "calls", WRAPPER, disp.get(WRAPPER))
for dn, p in disp.items():
    if p.startswith(GC["factScriptsDir"]) and f"notebook.{dn}" not in G.nodes:
        G.node(f"notebook.{dn}", dn, "notebook", "notebook", p, details={"wiredInWrapper": False, "note": f"never %run by {WRAPPER}"})

G.dump(os.path.join(OUT, "extract-gold.json"))
print(f"configs {len(cfg_files)} found / {len(orch)} orchestration + {len(table_cfgs)} table + {len(rules)} rules; nodes {len(G.nodes)} edges {len(G.edges)}")
print(G.layer_counts())
print("wrapper %run targets missing from repo:", [r for r in runs if r not in disp])
print("configs whose additionalProcedure is not wired:",
      [(n["name"], n["details"].get("additionalProcedure"), n["details"].get("definingNotebook")) for n in G.nodes.values()
       if n["layer"] == "gold" and n["type"] == "delta_table" and n["details"].get("additionalProcedure") and not n["details"].get("wiredInWrapper")])
