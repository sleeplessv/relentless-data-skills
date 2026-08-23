#!/usr/bin/env python3
"""Merge + validate the five extracts -> graph.json, graph-compact.json, validation-report.md.

Union nodes by id (details merged, sources recorded), edges by (from, to, kind) with via/path
as arrays; alias schema-less table ids to the unique schema-prefixed id with the same table
name; stub dangling refs; derive isFork and isLive (reachable forwards or backwards from an
enabled schedule); inherit partner/country downstream when every input agrees; write the
validation report with the extractor coverage text verbatim.

    python3 merge_graph.py --out <scratch> [--config lineage.config.json] [--coverage coverage.txt] [--alias old=new ...]

Fork rules come from lineage.config.json (forkNamePattern, forkDirPattern, notebooks.forkDirs,
notebooks.forkNamePrefixes), the same keys the extractors use; --fork-pattern / --fork-dirs override.
"""
import argparse
import collections
import copy
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lineage_common import DEFAULT_CONFIG, deep_merge  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--out", required=True, help="scratch dir holding extract-*.json; outputs go here too")
ap.add_argument("--config", default=None, help="lineage.config.json; fork rules read from forkNamePattern, forkDirPattern, notebooks.forkDirs, notebooks.forkNamePrefixes")
ap.add_argument("--coverage", default=None, help="text file with the extractors' coverage summaries, copied verbatim into the report")
ap.add_argument("--alias", action="append", default=[], help="extra id alias old=new (e.g. semantic.dataset-<guid>=semantic.<Model>)")
ap.add_argument("--fork-pattern", default=None, help="regex over node name marking forks (overrides config forkNamePattern)")
ap.add_argument("--fork-dirs", default=None, help="regex over node path marking developer folders (overrides config forkDirPattern)")
a = ap.parse_args()
D = a.out
EXTRACTS = ["extract-pipelines", "extract-silver", "extract-gold", "extract-notebooks", "extract-semantic"]
LINEAGE_KINDS = {"runs", "invokes", "copy", "transform", "reads", "writes", "directlake", "refreshes", "triggers", "calls", "binds", "partof"}
CFG = DEFAULT_CONFIG
if a.config:
    with open(a.config) as f:
        CFG = deep_merge(CFG, json.load(f))
FORK_RE = re.compile(a.fork_pattern or CFG["forkNamePattern"], re.I)
FORK_DIRS = re.compile(a.fork_dirs or CFG["forkDirPattern"], re.I)
NB_FORK_DIRS = CFG["notebooks"]["forkDirs"]
NB_FORK_PREFIXES = [p.lower() for p in CFG["notebooks"]["forkNamePrefixes"]]


def looks_fork(name, path):
    return bool(FORK_DIRS.search(path) or FORK_RE.search(name)
                or any(path.startswith(d) for d in NB_FORK_DIRS)
                or any(name.lower().startswith(p) for p in NB_FORK_PREFIXES))
TABLE_LAYERS = {"bronze", "silver", "gold"}
COVERAGE = open(a.coverage).read().strip() if a.coverage else "(no coverage file supplied: pass --coverage)"


def load(name):
    p = os.path.join(D, name + ".json")
    if not os.path.exists(p):
        print(f"WARNING: {p} missing, treated as empty")
        return {"nodes": [], "edges": []} if name.startswith("extract") else []
    with open(p) as f:
        return json.load(f)


raw = {e: load(e) for e in EXTRACTS}
inventory = load("notebook-inventory")
inv_by_name = {x["displayName"]: x for x in inventory}

# ---------------------------------------------------------------- 1. aliases
all_ids = set()
for d in raw.values():
    for n in d["nodes"]:
        all_ids.add(n["id"])
    for e in d["edges"]:
        all_ids.add(e["from"]); all_ids.add(e["to"])

aliases, alias_log = {}, []
by_suffix = collections.defaultdict(list)
for i in all_ids:
    layer, _, rest = i.partition(".")
    if layer in TABLE_LAYERS and "_" in rest and not rest.startswith("files/"):
        by_suffix[rest.partition("_")[2]].append(i)
for i in sorted(all_ids):
    layer, _, rest = i.partition(".")
    if layer not in TABLE_LAYERS or rest.startswith("files/") or "_" in rest:
        continue
    cands = by_suffix.get(rest.lower(), [])
    same_layer = [c for c in cands if c.startswith(layer + ".")]
    pick = same_layer[0] if len(same_layer) == 1 else (cands[0] if not same_layer and len(cands) == 1 else None)
    if pick:
        aliases[i] = pick
        alias_log.append(f"`{i}` -> `{pick}` (schema-less id, unique suffix match; layer {'kept' if pick.startswith(layer + '.') else 'CHANGED'})")
    else:
        alias_log.append(f"`{i}` left as-is: schema-less, candidates={cands or 'none'}")

nb_norm = collections.defaultdict(list)
for i in all_ids:
    if i.startswith("notebook."):
        nb_norm[re.sub(r"\s+", " ", i).strip().lower()].append(i)
for v in nb_norm.values():
    if len(v) > 1:
        canon = next((x for x in v if x[len("notebook."):] in inv_by_name), sorted(v)[0])
        for x in v:
            if x != canon:
                aliases[x] = canon
                alias_log.append(f"`{x}` -> `{canon}` (notebook case/whitespace variant)")
for spec in a.alias:
    old, _, new = spec.partition("=")
    aliases[old] = new
    alias_log.append(f"`{old}` -> `{new}` (explicit --alias; identity NOT verified from the repo)")


def A(i):
    return aliases.get(i, i)


# ---------------------------------------------------------------- 2. nodes
nodes = {}


def merge_details(dst, src):
    for k, v in (src or {}).items():
        if k not in dst or dst[k] in (None, "", [], {}):
            dst[k] = copy.deepcopy(v)
        elif isinstance(dst[k], dict) and isinstance(v, dict):
            merge_details(dst[k], v)
        elif isinstance(dst[k], list) and isinstance(v, list):
            for x in v:
                if x not in dst[k]:
                    dst[k].append(x)
        elif dst[k] != v and not isinstance(v, (dict, list)):
            alt = dst.setdefault("_conflicts", {}).setdefault(k, [])
            if v not in alt and v not in (None, ""):
                alt.append(v)


for ex, d in raw.items():
    for n in d["nodes"]:
        nid = A(n["id"])
        if nid not in nodes:
            nodes[nid] = {"id": nid, "name": "", "layer": "", "type": "", "path": "", "partner": None, "country": None,
                          "loadType": None, "details": {}, "sources": []}
        m = nodes[nid]
        for k in ("name", "layer", "type", "path", "partner", "country", "loadType"):
            if not m.get(k) and n.get(k):
                m[k] = n[k]
        merge_details(m["details"], n.get("details"))
        if nid != n["id"]:
            m["details"].setdefault("aliasedFrom", [])
            if n["id"] not in m["details"]["aliasedFrom"]:
                m["details"]["aliasedFrom"].append(n["id"])
        if ex not in m["sources"]:
            m["sources"].append(ex)

# ---------------------------------------------------------------- 3. edges
edges, edge_sources = {}, collections.defaultdict(set)
for ex, d in raw.items():
    for e in d["edges"]:
        key = (A(e["from"]), A(e["to"]), e["kind"])
        m = edges.setdefault(key, {"from": key[0], "to": key[1], "kind": key[2], "via": [], "path": [], "details": {}})
        for fld in ("via", "path"):
            v = e.get(fld)
            if v and v not in m[fld]:
                m[fld].append(v)
        if e.get("details"):
            merge_details(m["details"], e["details"])
        if e.get("note"):
            m["details"].setdefault("notes", [])
            if e["note"] not in m["details"]["notes"]:
                m["details"]["notes"].append(e["note"])
        edge_sources[key].add(ex)
for k, m in edges.items():
    m["sources"] = sorted(edge_sources[k])
    if not m["details"]:
        del m["details"]

# ---------------------------------------------------------------- 4. stubs
stubs = []
for (f, t, k) in list(edges):
    for i in (f, t):
        if i not in nodes:
            nodes[i] = {"id": i, "name": i.split(".", 1)[1] if "." in i else i, "layer": i.split(".", 1)[0], "type": "unknown",
                        "path": "", "partner": None, "country": None, "loadType": None, "details": {"stub": True}, "sources": [], "stub": True}
            stubs.append(i)

# ---------------------------------------------------------------- 5. isFork
for n in nodes.values():
    nm, path, det = n["name"] or "", n["path"] or "", n["details"]
    if n["layer"] == "notebook":
        inv = inv_by_name.get(n["id"][len("notebook."):])
        fork = bool(inv.get("isFork")) if inv is not None else (bool(det["isFork"]) if det.get("isFork") is not None else looks_fork(nm, path))
    elif n["layer"] == "pipeline" or n["type"] in ("pipeline", "dataflow", "config"):
        fork = bool(det.get("isDevFork") or det.get("fork") or looks_fork(nm, path))
    elif n["layer"] == "report":
        fork = looks_fork(nm, path)
    else:
        fork = bool(det.get("fork"))
    n["isFork"] = fork

# ---------------------------------------------------------------- 6. isLive
fwd, bwd = collections.defaultdict(set), collections.defaultdict(set)
for (f, t, k) in edges:
    if k in LINEAGE_KINDS:
        fwd[f].add(t); bwd[t].add(f)


def enabled_sched(n):
    d = n["details"]
    if n["id"].startswith("trigger.schedule."):
        return bool(d.get("enabled"))
    return any(s.get("enabled") for s in d.get("schedules") or [])


roots = set()
for n in nodes.values():
    if n["id"].startswith("trigger.schedule.") and enabled_sched(n):
        roots.add(n["id"]); roots |= fwd[n["id"]]
    elif n["layer"] == "pipeline" and n["type"] == "pipeline" and enabled_sched(n):
        roots.add(n["id"])


def reach(starts, adj):
    seen, st = set(starts), list(starts)
    while st:
        x = st.pop()
        for y in adj[x]:
            if y not in seen:
                seen.add(y); st.append(y)
    return seen


live = reach(roots, fwd) | reach(roots, bwd)
for n in nodes.values():
    n["isLive"] = n["id"] in live
    n["isScheduledRoot"] = n["id"] in roots

# ---------------------------------------------------------------- 7. inheritance
inherit_in = collections.defaultdict(set)
for (f, t, k) in edges:
    if k in ("transform", "copy"):
        inherit_in[t].add(f)
inherited, changed, rounds = collections.Counter(), True, 0
while changed and rounds < 20:
    changed, rounds = False, rounds + 1
    for t, srcs in inherit_in.items():
        n = nodes[t]
        for fld in ("partner", "country"):
            if n.get(fld):
                continue
            vals = {nodes[s].get(fld) for s in srcs}
            if len(vals) == 1 and None not in vals and "" not in vals:
                n[fld] = vals.pop(); n["details"].setdefault("inherited", []).append(fld)
                inherited[fld] += 1; changed = True

# ---------------------------------------------------------------- 8. validation
deg = collections.Counter()
in_by, out_by = collections.defaultdict(list), collections.defaultdict(list)
for (f, t, k) in edges:
    deg[f] += 1; deg[t] += 1; in_by[t].append((f, k)); out_by[f].append((t, k))

tables = [n for n in nodes.values() if n["layer"] in TABLE_LAYERS and n["type"] in ("delta_table", "sql_table", "unknown")
          and not n["id"].startswith(("bronze.files", "unresolved."))]
orphans = [n["id"] for n in tables if deg[n["id"]] == 0]
gold_no_up = [n["id"] for n in tables if n["layer"] == "gold" and not any(k in ("transform", "writes", "copy") for _, k in in_by[n["id"]])]
silver_no_bronze = [n["id"] for n in tables if n["layer"] == "silver" and not any(f.startswith("bronze.") and k in ("transform", "copy") for f, k in in_by[n["id"]])]
silver_no_up = [i for i in silver_no_bronze if not any(k in ("transform", "writes", "copy") for _, k in in_by[i])]
bronze_no_src = [n["id"] for n in tables if n["layer"] == "bronze" and not any(k in ("copy", "writes") for _, k in in_by[n["id"]])]
sem_tables = [n for n in nodes.values() if n["type"] == "semantic_table"]
sem_no_gold = [n["id"] for n in sem_tables if not any(f.startswith("gold.") and k == "directlake" for f, k in in_by[n["id"]])]
sem_calc = [n["id"] for n in sem_tables if n["details"].get("partitionType") in ("calculated", "calculationGroup", "m")]
notebooks = [n for n in nodes.values() if n["layer"] == "notebook"]
nb_never_run = [n["id"] for n in notebooks if not n["isFork"] and not any(k in ("runs", "calls", "invokes") for _, k in in_by[n["id"]])]
pipelines = [n for n in nodes.values() if n["type"] == "pipeline"]
pipe_no_sched_no_invoker = [n["id"] for n in pipelines if not any(k in ("triggers", "invokes", "runs") for _, k in in_by[n["id"]])]
pipe_disabled_only = [n["id"] for n in pipelines if n["id"] not in pipe_no_sched_no_invoker and not n["isScheduledRoot"]
                      and not any(k in ("invokes", "runs") for _, k in in_by[n["id"]])]
unresolved = [n["id"] for n in nodes.values() if n["layer"] == "unresolved" or n["id"].startswith("unresolved.")]
notlive_pipes = [n["id"] for n in pipelines if not n["isLive"] and not n["isFork"]]
gold_not_live = [n["id"] for n in tables if n["layer"] == "gold" and not n["isLive"]]
directlake_unwritten = sorted({f for (f, t, k) in edges if k == "directlake" and not any(kk in ("transform", "writes") for _, kk in in_by[f])})
conflicts = [n["id"] for n in nodes.values() if "_conflicts" in n["details"]]

layer_nodes = collections.Counter(n["layer"] for n in nodes.values())
layer_edges = collections.Counter(f"{nodes[f]['layer']}->{nodes[t]['layer']}" for (f, t, k) in edges)
kind_counts = collections.Counter(k for (_, _, k) in edges)
live_by_layer = collections.Counter(n["layer"] for n in nodes.values() if n["isLive"])
fork_by_layer = collections.Counter(n["layer"] for n in nodes.values() if n["isFork"])

# ---------------------------------------------------------------- 9. graph.json (capped)
TRUNC = {"strings": 0, "arrays": 0}


def cap(v):
    if isinstance(v, str):
        if len(v) > 600:
            TRUNC["strings"] += 1; return v[:600] + f"…[truncated {len(v) - 600} chars]"
        return v
    if isinstance(v, list):
        out = [cap(x) for x in v[:60]]
        if len(v) > 60:
            TRUNC["arrays"] += 1; out.append(f"…[truncated {len(v) - 60} more items]")
        return out
    if isinstance(v, dict):
        return {k: cap(x) for k, x in v.items()}
    return v


node_list = sorted(nodes.values(), key=lambda n: n["id"])
edge_list = sorted(edges.values(), key=lambda e: (e["from"], e["to"], e["kind"]))
meta = {
    "generatedFrom": EXTRACTS + ["notebook-inventory"], "generator": "merge_graph.py",
    "counts": {"nodes": len(nodes), "edges": len(edges), "stubs": len(stubs), "aliases": len(aliases),
               "nodesByLayer": dict(layer_nodes), "edgesByKind": dict(kind_counts), "edgesByLayerPair": dict(layer_edges),
               "liveNodes": sum(1 for n in nodes.values() if n["isLive"]), "forkNodes": sum(1 for n in nodes.values() if n["isFork"]),
               "scheduledRoots": len(roots), "inheritedPartner": inherited["partner"], "inheritedCountry": inherited["country"],
               "unresolved": len(unresolved)},
    "coverage": COVERAGE, "aliases": aliases, "lineageKindsForIsLive": sorted(LINEAGE_KINDS),
    "gaps": {"pipelinesNoScheduleNoInvoker": pipe_no_sched_no_invoker, "pipelinesDisabledScheduleOnly": pipe_disabled_only,
             "bronzeNoSource": bronze_no_src, "goldNoUpstream": gold_no_up, "silverNoUpstream": silver_no_up,
             "silverNoBronze": silver_no_bronze, "notebooksNeverRun": nb_never_run, "semanticNoGold": sem_no_gold,
             "orphanTables": orphans, "directLakeUnwritten": directlake_unwritten, "stubs": stubs},
}
with open(os.path.join(D, "graph.json"), "w") as f:
    json.dump({"meta": meta, "nodes": [dict(n, details=cap(n["details"])) for n in node_list],
               "edges": [dict(e, details=cap(e["details"])) if "details" in e else e for e in edge_list]}, f, ensure_ascii=False)
meta["counts"]["truncatedStrings"], meta["counts"]["truncatedArrays"] = TRUNC["strings"], TRUNC["arrays"]

# ---------------------------------------------------------------- 10. graph-compact.json
SHORT_KEYS = ["schedule", "schedules", "scheduled", "notebook", "notebooks", "configPath", "config", "silverConfigs", "keys",
              "lakehouse", "pipelines", "pipeline", "description", "role", "note", "logicalId", "loadType", "processArea",
              "targetTable", "sourceTable", "stub", "unqualified", "missingInRepo", "aliasedFrom", "inherited", "isDevFork",
              "enabled", "type", "times", "weekdays", "frequency", "unresolvedRefs", "datasetId", "workspaceId"]


def short(v, depth=0):
    if isinstance(v, str):
        return v if len(v) <= 200 else v[:200] + "…"
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    if isinstance(v, list):
        return [short(x, depth + 1) for x in v[:12]] + (["…"] if len(v) > 12 else [])
    if isinstance(v, dict):
        items = list(v.items())[:8] if depth >= 1 else v.items()
        return {k: short(x, depth + 1) for k, x in items}
    return str(v)


c_nodes = [{"id": n["id"], "name": n["name"], "layer": n["layer"], "type": n["type"], "path": n["path"], "partner": n["partner"],
            "country": n["country"], "loadType": n["loadType"], "isFork": n["isFork"], "isLive": n["isLive"],
            "details": {k: short(n["details"][k]) for k in SHORT_KEYS if n["details"].get(k) not in (None, "", [], {})}} for n in node_list]
c_edges = [{"from": e["from"], "to": e["to"], "kind": e["kind"], "via": e["via"][:5]} for e in edge_list]
cpath = os.path.join(D, "graph-compact.json")
with open(cpath, "w") as f:
    json.dump({"meta": {"counts": meta["counts"], "coverage": COVERAGE, "gaps": meta["gaps"]}, "nodes": c_nodes, "edges": c_edges},
              f, ensure_ascii=False, separators=(",", ":"))
compact_size = os.path.getsize(cpath)


# ---------------------------------------------------------------- 11. report
def lst(items, cap_n=80):
    items = sorted(items)
    s = "\n".join(f"- `{i}`" for i in items[:cap_n])
    if len(items) > cap_n:
        s += f"\n- … and {len(items) - cap_n} more"
    return s or "- (none)"


R = ["# Lineage graph validation report\n", f"Generated by `merge_graph.py` from: {', '.join(EXTRACTS)} (+ notebook-inventory).\n",
     "## Coverage (from extraction agents, verbatim)\n", COVERAGE + "\n", "## Totals\n",
     f"- Nodes: **{len(nodes)}**, edges: **{len(edges)}** (raw inputs: {sum(len(d['nodes']) for d in raw.values())} node rows / {sum(len(d['edges']) for d in raw.values())} edge rows)",
     f"- Dangling edge refs after merge: **{len(stubs)}** stub nodes: {', '.join(stubs[:40]) or 'none'}",
     f"- Aliased ids: **{len(aliases)}**; live nodes: {meta['counts']['liveNodes']}; fork nodes: {meta['counts']['forkNodes']}; scheduled roots: {len(roots)}",
     f"- partner inherited onto {inherited['partner']} nodes, country onto {inherited['country']} nodes",
     f"- graph.json truncation: {TRUNC['strings']} strings capped at 600 chars, {TRUNC['arrays']} arrays capped at 60 items",
     f"- graph-compact.json size: **{compact_size / 1e6:.2f} MB**\n", "## Per-layer counts\n", "| layer | nodes | live | fork |\n|---|---:|---:|---:|"]
R += [f"| {l} | {c} | {live_by_layer[l]} | {fork_by_layer[l]} |" for l, c in sorted(layer_nodes.items(), key=lambda x: -x[1])]
R += ["\n| edge kind | count |\n|---|---:|"] + [f"| {k} | {c} |" for k, c in sorted(kind_counts.items(), key=lambda x: -x[1])]
R += ["\n| from-layer -> to-layer | edges |\n|---|---:|"] + [f"| {k} | {c} |" for k, c in sorted(layer_edges.items(), key=lambda x: -x[1])]
R += ["\n## Aliases\n"] + [f"- {l}" for l in alias_log]
R.append(f"\nNodes whose scalar details disagreed between extracts (first kept, rest under `details._conflicts`): {len(conflicts)}\n" + lst(conflicts, 30))
sections = [
    (f"Orphan table nodes (no edges at all): {len(orphans)}", orphans, ""),
    (f"Gold tables with no upstream transform/writes: {len(gold_no_up)}", gold_no_up, ""),
    (f"Semantic tables with no Gold DirectLake source: {len(sem_no_gold)}", sem_no_gold, f"(expected: {len(sem_calc)} calculated / calc-group tables: {', '.join(sem_calc)})"),
    (f"Bronze tables with no source (no copy/writes in): {len(bronze_no_src)}", bronze_no_src, "Runtime table lists (INFORMATION_SCHEMA lookups) leave their Bronze targets as `unresolved.*`."),
    (f"Silver tables with no Bronze transform/copy input: {len(silver_no_bronze)} (of which {len(silver_no_up)} have no upstream at all)", silver_no_bronze, ""),
    (f"Notebooks never run by a pipeline nor %run-called (non-fork): {len(nb_never_run)}", nb_never_run, ""),
    (f"Pipelines with no schedule trigger and no invoker: {len(pipe_no_sched_no_invoker)}", pipe_no_sched_no_invoker, ""),
    (f"Pipelines whose only trigger is a disabled schedule: {len(pipe_disabled_only)}", pipe_disabled_only, ""),
    (f"Unresolved nodes (dynamic refs kept as-is): {len(unresolved)}", unresolved, ""),
    (f"Non-fork pipelines not reachable from any enabled schedule: {len(notlive_pipes)}", notlive_pipes, ""),
    (f"Gold tables not live: {len(gold_not_live)}", gold_not_live, ""),
    (f"DirectLake Gold sources no ETL writes: {len(directlake_unwritten)}", directlake_unwritten, ""),
]
for title, items, note in sections:
    R.append(f"\n## {title}\n" + (note + "\n" if note else "") + lst(items, 120))
with open(os.path.join(D, "validation-report.md"), "w") as f:
    f.write("\n".join(R) + "\n")

print(json.dumps({"layers": dict(layer_nodes), "edges": len(edges), "stubs": len(stubs), "aliases": len(aliases), "compactBytes": compact_size,
                  "orphans": len(orphans), "goldNoUp": len(gold_no_up), "semNoGold": len(sem_no_gold), "bronzeNoSrc": len(bronze_no_src),
                  "silverNoBronze": len(silver_no_bronze), "nbNeverRun": len(nb_never_run), "pipeNoSchedNoInvoker": len(pipe_no_sched_no_invoker),
                  "unresolved": len(unresolved), "live": meta["counts"]["liveNodes"], "roots": len(roots), "conflicts": len(conflicts)}, indent=1))
