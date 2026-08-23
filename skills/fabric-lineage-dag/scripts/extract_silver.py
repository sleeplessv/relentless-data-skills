#!/usr/bin/env python3
"""Extractor 2: JSON-config-driven Silver layer -> extract-silver.json.

Two config shapes: orchestration files (integrationName + etlTasks[].procedureName) and
table definitions (databaseMapping + tables[]). Wires pipeline -> orchestration config ->
table config -> Bronze source, and reports configs nothing references.

    python3 extract_silver.py --repo <repo> --out <scratch> [--config lineage.config.json]
"""
import glob
import json
import os
import re

from lineage_common import Graph, build_guid_map, parse_args

a = parse_args("Extract config-driven Silver lineage")
CFG, REPO, OUT = a.cfg, a.repo, a.out
S = CFG["silver"]
CC = CFG["countryPrefixes"]
PER_COUNTRY = set(CFG["perCountryBronzeDatabases"])
PARTNER_RE = re.compile(S["partnerPattern"], re.I) if S.get("partnerPattern") else None
os.chdir(REPO)
G = Graph()
report = {"found": 0, "parsed": 0, "skipped": [], "variants": set(), "partners": set(), "countries": set()}

guid_map = build_guid_map(REPO)
NB_BY_LOGICAL = {e["logicalId"]: (e["displayName"], e["path"]) for e in guid_map.values() if e.get("type") == "Notebook" and e.get("logicalId")}
nb_path = {dn: p for dn, p in NB_BY_LOGICAL.values()}

# ---------------------------------------------------------------- pipelines -> orchestration configs
orch_to_pipelines = {}
for p in glob.glob("**/*.DataPipeline/pipeline-content.json", recursive=True):
    txt = open(p).read()
    refs = set(re.findall(r"Files/config/[A-Za-z0-9/_.-]+\.json", txt))
    refs = {r for r in refs if "/Gold/" not in r}
    if not refs:
        continue
    folder = os.path.dirname(p)
    dn = json.load(open(os.path.join(folder, ".platform")))["metadata"]["displayName"]
    nid = f"pipeline.{dn}"
    nbs = sorted({NB_BY_LOGICAL[x][0] for x in re.findall(r'"notebookId":\s*"([^"]+)"', txt) if x in NB_BY_LOGICAL})
    G.node(nid, dn, "pipeline", "pipeline", folder, details={"silverConfigs": sorted(refs), "notebooks": nbs})
    for nb in nbs:
        G.node(f"notebook.{nb}", nb, "notebook", "notebook", nb_path.get(nb))
        G.edge(nid, f"notebook.{nb}", "runs", dn, folder)
    for r in refs:
        orch_to_pipelines.setdefault(r, []).append(dn)
        # case-insensitive existence check: a parameter may say LgEnergy where the repo has LGEnergy
        local = r.replace("Files/config/", "files/config/")
        if not os.path.exists(local):
            ci = [f for f in glob.glob("files/config/**/*.json", recursive=True) if f.lower() == local.lower()]
            report["variants"].add(f"pipeline {dn} references {r}: " + (f"case mismatch, repo has {ci[0]}" if ci else "MISSING from repo"))

# ---------------------------------------------------------------- orchestration configs -> table configs
table_to_orch = {}
all_cfgs = sorted({f for g in S["configGlobs"] for f in glob.glob(g, recursive=True)})
report["found"] = len(all_cfgs)
table_cfgs = []
for p in all_cfgs:
    try:
        d = json.load(open(p))
    except Exception as e:
        report["skipped"].append(f"{p}: invalid JSON ({e})")
        continue
    if "etlTasks" in d:
        for t in d["etlTasks"]:
            pn = t.get("procedureName", "")
            key = pn if pn.startswith("Files/") else os.path.join(os.path.dirname(p), pn)
            key = key.replace("Files/config/", "files/config/")
            table_to_orch.setdefault(key, []).append((p, d.get("integrationName"), t.get("defaultDaysToProcess"), t.get("critical")))
        report["parsed"] += 1
    elif "databaseMapping" in d and "tables" in d:
        table_cfgs.append((p, d))
    else:
        report["skipped"].append(f"{p}: unknown shape keys={list(d.keys())}")

# .py orchestration steps that drive a JSON config through a hard-coded path (declared in config)
py_driver = {}
for step, (cfg_path, nb) in S.get("pyStepConfigs", {}).items():
    for okey, v in list(table_to_orch.items()):
        if okey.endswith("/" + step):
            table_to_orch.setdefault(cfg_path, []).extend(v)
            py_driver[cfg_path] = nb

WRAPPER = S["wrapperNotebook"]
G.node(f"notebook.{WRAPPER}", WRAPPER, "notebook", "notebook", nb_path.get(WRAPPER), details={"role": "Silver entry point: runs every JSON table config"})

# ---------------------------------------------------------------- table configs
for p, d in table_cfgs:
    dm = d["databaseMapping"]
    parts = p.split("/")
    area = parts[3] if len(parts) > 4 else parts[-2]
    fork = bool(re.match(r"^(Test|Old)", os.path.basename(p), re.I))
    srcLayer, srcDb, tgtDb = dm.get("sourceLayer"), dm.get("sourceDatabase"), dm.get("targetDatabase")
    tcs = dm.get("tableCountries") or ["N/A"]
    if isinstance(tcs, str):
        tcs = [tcs]
    if not srcLayer or not srcDb:
        report["variants"].add(f"{p}: missing sourceLayer/sourceDatabase")
    orchs = table_to_orch.get(p, [])
    pipelines = sorted({pl for (op, _, _, _) in orchs for pl in orch_to_pipelines.get(op.replace("files/config/", "Files/config/"), [])})
    partner = None
    if area == "Partners" and PARTNER_RE:
        m = PARTNER_RE.match(os.path.basename(p))
        partner = m.group(1) if m else None
    elif area in S["processAreaPartners"]:
        partner = area
    country = None
    mc = re.search(r"(Uk|De|Es|Fr)\.json$", os.path.basename(p))
    if mc:
        country = mc.group(1).upper()
    elif len(tcs) == 1 and tcs[0] in CC:
        country = CC[tcs[0]]
    if partner:
        report["partners"].add(partner)
    for c in tcs:
        if c in CC:
            report["countries"].add(CC[c])
    via_nb = py_driver.get(p, WRAPPER)
    if via_nb != WRAPPER:
        G.node(f"notebook.{via_nb}", via_nb, "notebook", "notebook", nb_path.get(via_nb, ""),
               details={"role": f"custom .py step run by {WRAPPER}; reads this JSON via a hard-coded path"})
    for t in d["tables"]:
        st, tt, lt = t.get("sourceTable"), t.get("targetTable"), t.get("loadType")
        if not tt:
            report["skipped"].append(f"{p}: table without targetTable")
            continue
        if lt and lt not in ("Full", "Delta"):
            report["variants"].add(f"{p}: loadType casing '{lt}'")
        if not t.get("targetTableSurrogateKeys"):
            report["variants"].add(f"{p}: empty targetTableSurrogateKeys")
        sid = f"silver.{tgtDb.lower()}_{tt.lower()}" if tgtDb and tgtDb.lower() != "dbo" else f"silver.{tt.lower()}"
        details = {
            "configPath": [p], "processArea": area, "schema": tgtDb, "keys": t.get("targetTableSurrogateKeys"),
            "partitionColumn": t.get("partitionColumn"), "active": t.get("active"), "tableCountries": tcs,
            "columnCount": len(t.get("columns", [])), "transformProcedure": dm.get("transformProcedure"),
            "additionalProcedure": dm.get("additionalProcedure"), "notebook": via_nb, "engine": f"generic insert (via {WRAPPER})",
            "orchestrationConfigs": sorted({op for (op, _, _, _) in orchs}),
            "integrationNames": sorted({i for (_, i, _, _) in orchs if i}),
            "pipelines": pipelines, "fork": fork, "sourceLayer": srcLayer, "sourceDatabase": srcDb,
        }
        details = {k: v for k, v in details.items() if v not in (None, [], "")}
        G.node(sid, f"{tgtDb}.{tt}", "silver", "delta_table", p, partner=partner, country=country, loadType=lt, details=details)
        if (srcLayer or "").lower() == "bronze" and st:
            if srcDb in PER_COUNTRY:
                for c in tcs:
                    bid = f"bronze.{srcDb.lower()}_{c.lower()}_{st.lower()}"
                    G.node(bid, f"{srcDb}.{c}_{st}", "bronze", "delta_table", "", country=CC.get(c),
                           details={"lakehouse": "Bronze", "schema": srcDb, "path": f"{srcDb}/{c}_{st}"})
                    G.edge(bid, sid, "transform", via_nb, p)
            else:
                bid = f"bronze.{srcDb.lower()}_{st.lower()}"
                G.node(bid, f"{srcDb}.{st}", "bronze", "delta_table", "", partner=partner if area == "Partners" else None,
                       details={"lakehouse": "Bronze", "schema": srcDb, "path": f"{srcDb}/{st}"})
                G.edge(bid, sid, "transform", via_nb, p)
        elif st:
            uid = f"unresolved.{(srcDb or 'na').lower()}_{st.lower()}"
            G.node(uid, f"{srcLayer}.{srcDb}.{st}", "source", "delta_table", "",
                   details={"raw": f"sourceLayer={srcLayer} sourceDatabase={srcDb} sourceTable={st}",
                            "note": "no Bronze source; self-generated or notebook-computed"})
            G.edge(uid, sid, "transform", via_nb, p)
        G.edge(f"notebook.{via_nb}", sid, "writes", via_nb, p)
        if via_nb != WRAPPER:
            G.edge(f"notebook.{WRAPPER}", f"notebook.{via_nb}", "runs", WRAPPER, p)
        report["parsed"] += 1

# ---------------------------------------------------------------- generic Config.conf note node
conf_path = S.get("genericConf")
if conf_path and os.path.exists(conf_path):
    conf = open(conf_path).read()
    G.node("config.generic_conf", os.path.basename(conf_path), "metadata", "config", conf_path,
           details={"note": "Runtime settings + lakehouse abfss layer paths",
                    "layerPaths": dict(re.findall(r'^(\w+(?:DBFS)?Path)\s*=\s*"?([^"\n]+)"?', conf, re.M)),
                    "lakehouseGuids": sorted(set(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", conf)))})
    G.edge(f"notebook.{WRAPPER}", "config.generic_conf", "reads", WRAPPER, conf_path)

G.dump(os.path.join(OUT, "extract-silver.json"))
print("configs found", report["found"], "parsed", report["parsed"], "skipped", len(report["skipped"]))
for s in report["skipped"]:
    print("  SKIP", s)
print("nodes", len(G.nodes), G.layer_counts(), "edges", len(G.edges))
print("partners", sorted(report["partners"]), "countries", sorted(report["countries"]))
print("variants:")
for v in sorted(report["variants"]):
    print("  ", v)
silver = [n for n in G.nodes.values() if n["layer"] == "silver"]
print("table configs referenced by no orchestration file:", sorted({n["path"] for n in silver if not n["details"].get("orchestrationConfigs")}))
print("orchestrated but no pipeline in repo:", sorted({n["path"] for n in silver if n["details"].get("orchestrationConfigs") and not n["details"].get("pipelines")}))
