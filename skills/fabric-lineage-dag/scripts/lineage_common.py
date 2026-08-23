"""Shared helpers for the fabric-lineage-dag extractors.

Every extractor imports this module for: CLI args (--repo, --out, --config),
the optional lineage.config.json, the item GUID -> displayName map built from
.platform files, node/edge builders in the agreed schema, and the country /
layer heuristics. Standard library only.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import OrderedDict

GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

DEFAULT_CONFIG = {
    # two-letter country codes that appear in names, and the prefixes they hide behind (FGUK -> UK)
    "countries": ["UK", "DE", "FR", "ES"],
    "countryPrefixes": {"FGUK": "UK", "FGDE": "DE", "FGFR": "FR", "FGES": "ES"},
    # lakehouse displayName (lower) -> layer. Anything containing bronze/silver/gold/metadata resolves by substring.
    "lakehouseNameLayers": {"bronze": "bronze", "silver": "silver", "gold": "gold", "metadata": "metadata",
                            "meta": "metadata", "awsstaging": "awsstaging", "staging": "awsstaging"},
    # lakehouse item GUID (any form) -> layer; filled from .platform files when omitted
    "lakehouseLayers": {},
    # names / folders that mark developer forks rather than live items
    "forkNamePattern": r"(^Test|Test$|Stage|Copy|bkp|backup|\bold\b|\d{8})",
    "forkDirPattern": r"^(Test)[/ ]",
    # Bronze databases stored as <db>/<country>_<table> instead of <db>/<table>; set per repo
    "perCountryBronzeDatabases": [],
    "silver": {
        "configGlobs": ["files/config/Silver/**/*.json"],
        "wrapperNotebook": "wrapperMain.py",
        "genericConf": "files/config/Generic/Config.conf",
        # python orchestration steps -> (table config json, notebook that implements the step)
        "pyStepConfigs": {},
        "partnerPattern": "",
        "processAreaPartners": ["Aloha", "Menulink", "Slang", "Rewards"],
    },
    "gold": {
        "configGlobs": ["files/config/Gold/**/*.json"],
        "wrapperNotebook": "GoldWrapperMain.py",
        "notebookGlobs": ["Main/Gold/**/.platform"],
        "factScriptsDir": "Main/Gold/FactScripts",
        "orchestrationForkPattern": r"(Test|Stage|SingleJob|SinglePartner)",
        "orchestrationPipelines": {},
        "storeMappingSchema": "Slang",
        "storeMappingTables": ["FgIntegrationPartnerStore", "FgStore"],
        "partnerPattern": r"^FgFact([A-Z][a-z]+)",
        "handWritten": [],
    },
    "semantic": {
        "modelsGlob": "Models/*.SemanticModel",
        "workspaceId": None,
        "sandboxReportDirs": [],
    },
    "notebooks": {
        "knownSchemas": ["aloha", "slang", "reference", "partners", "menulink", "rewards", "dimension", "fact", "dim",
                         "dbo", "meta", "dq", "staging"],
        "schemaLayerHints": {"dimension": "gold", "fact": "gold", "dim": "gold", "meta": "metadata"},
        "unqualifiedTablePrefixes": r"(?i)^(fg|ref|dim|fact|etl)",
        "forkDirs": [],
        "forkNamePrefixes": [],
    },
}


def deep_merge(base, over):
    out = json.loads(json.dumps(base))
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def parse_args(description, extra=None):
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--repo", required=True, help="root of the Fabric Git-exported workspace")
    ap.add_argument("--out", required=True, help="scratch directory for extract-*.json outputs")
    ap.add_argument("--config", default=None, help="lineage.config.json with repo-specific knobs (optional)")
    if extra:
        extra(ap)
    a = ap.parse_args()
    a.repo = os.path.abspath(a.repo)
    os.makedirs(a.out, exist_ok=True)
    cfg = DEFAULT_CONFIG
    if a.config:
        with open(a.config) as f:
            cfg = deep_merge(cfg, json.load(f))
    a.cfg = cfg
    return a


# ---------------------------------------------------------------- GUID map
def swap_guid(g):
    """Little-endian byte swap of the first three groups (one form Fabric uses)."""
    p = g.lower().split("-")
    if len(p) != 5:
        return None
    rev = lambda h: "".join(reversed([h[i:i + 2] for i in range(0, len(h), 2)]))
    return "-".join([rev(p[0]), rev(p[1]), rev(p[2]), p[3], p[4]])


def alt_guid(g):
    """Segment-reversal transform: pipelines and TMDL expressions reference items by this form.
    logicalId 14aedf53-5d85-8100-4f82-5c29aee97a45 -> aee97a45-5c29-4f82-8100-5d8514aedf53
    i.e. g1-g2-g3-g4-g5 -> g5[4:]-g5[:4]-g4-g3-g2+g1. The transform is its own inverse."""
    p = g.lower().split("-")
    if len(p) != 5:
        return None
    return f"{p[4][4:]}-{p[4][:4]}-{p[3]}-{p[2]}-{p[1]}{p[0]}"


def build_guid_map(repo, out_dir=None):
    """Every .platform file, keyed by logicalId, folder GUID, and both transforms of each."""
    guid_map = {}
    cwd = os.getcwd()
    os.chdir(repo)
    try:
        for pf in glob.glob("**/.platform", recursive=True):
            try:
                d = json.load(open(pf))
            except Exception as e:
                print("bad platform", pf, e, file=sys.stderr)
                continue
            md, cfg = d.get("metadata", {}), d.get("config", {})
            folder = os.path.dirname(pf)
            entry = {"displayName": md.get("displayName"), "type": md.get("type"), "path": folder,
                     "logicalId": (cfg.get("logicalId") or "").lower()}
            keys = set()
            if entry["logicalId"]:
                keys.add(entry["logicalId"])
            fname = os.path.basename(folder).split(".")[0].lower()
            if GUID_RE.match(fname):
                keys.add(fname)
            for k in list(keys):
                keys.add(swap_guid(k)); keys.add(alt_guid(k))
            for k in keys:
                if k and k not in guid_map:
                    guid_map[k] = entry
                elif k and guid_map[k]["path"] != folder:
                    guid_map[k].setdefault("collisions", []).append(folder)
    finally:
        os.chdir(cwd)
    if out_dir:
        json.dump(guid_map, open(os.path.join(out_dir, "guid-map.json"), "w"), indent=1)
    return guid_map


def make_resolver(guid_map):
    def resolve(guid):
        if not guid:
            return None
        g = str(guid).lower()
        return guid_map.get(g) or guid_map.get(swap_guid(g) or "") or guid_map.get(alt_guid(g) or "")
    return resolve


def lakehouse_layers(cfg, guid_map):
    """GUID (all forms) -> layer for every Lakehouse item, merged with cfg['lakehouseLayers']."""
    out = {k.lower(): v for k, v in (cfg.get("lakehouseLayers") or {}).items()}
    for g, e in guid_map.items():
        if e.get("type") == "Lakehouse":
            layer = layer_of_lakehouse(cfg, e["displayName"])
            if layer != "unresolved":
                out.setdefault(g, layer)
    return out


def layer_of_lakehouse(cfg, name):
    if not name:
        return "unresolved"
    n = name.lower()
    names = cfg["lakehouseNameLayers"]
    if n in names:
        return names[n]
    for k in ("bronze", "silver", "gold", "metadata", "staging"):
        if k in n:
            return names.get(k, k)
    return n


# ---------------------------------------------------------------- graph builders
class Graph:
    def __init__(self):
        self.nodes = OrderedDict()
        self.edges = []
        self._ekeys = set()

    def node(self, nid, name, layer, typ, path=None, **kw):
        if nid not in self.nodes:
            n = {"id": nid, "name": name, "layer": layer, "type": typ, "path": path, "details": {}}
            for k, v in kw.items():
                if k == "details":
                    n["details"].update({a: b for a, b in v.items() if b is not None})
                elif v is not None:
                    n[k] = v
            self.nodes[nid] = n
        else:
            n = self.nodes[nid]
            for k, v in kw.items():
                if k == "details":
                    for dk, dv in v.items():
                        if dv is None:
                            continue
                        cur = n["details"].get(dk)
                        if isinstance(cur, list) and isinstance(dv, list):
                            n["details"][dk] = cur + [x for x in dv if x not in cur]
                        else:
                            n["details"].setdefault(dk, dv)
                elif v is not None and k not in n:
                    n[k] = v
            if path and not n.get("path"):
                n["path"] = path
        return self.nodes[nid]

    def edge(self, f, t, kind, via, path, **details):
        e = {"from": f, "to": t, "kind": kind, "via": via, "path": path}
        details = {k: v for k, v in details.items() if v is not None}
        if details:
            e["details"] = details
        key = (f, t, kind, via, path)
        if key in self._ekeys:
            return
        self._ekeys.add(key)
        self.edges.append(e)

    def dump(self, path, **meta):
        out = {"nodes": list(self.nodes.values()), "edges": self.edges}
        if meta:
            out["meta"] = meta
        json.dump(out, open(path, "w"), indent=1, default=str)

    def layer_counts(self):
        from collections import Counter
        return dict(Counter(n["layer"] for n in self.nodes.values()))


# ---------------------------------------------------------------- naming helpers
def table_id(layer, schema, table):
    """<layer>.<schema>_<table> lower-case; schema-less when schema is empty or dbo."""
    table = str(table).strip("`\"'[] ").lower()
    schema = (schema or "").strip("`\"'[] ").lower()
    if schema in ("", "dbo"):
        return f"{layer}.{table}"
    return f"{layer}.{schema}_{table}"


def country_detector(cfg):
    cs = cfg["countries"]
    alts = "|".join(cs)
    plain = re.compile(rf"(?<![A-Za-z])({alts})(?![A-Za-z])")
    prefixes = cfg["countryPrefixes"]
    pref = re.compile("|".join(re.escape(p) for p in prefixes), re.I) if prefixes else None

    def detect(*texts):
        for t in texts:
            if not t:
                continue
            s = str(t)
            m = plain.search(s)
            if m:
                return m.group(1)
            if pref:
                m = pref.search(s)
                if m:
                    return prefixes[m.group(0).upper()]
        return None
    return detect


def is_fork_name(cfg, name, path=""):
    if re.search(cfg["forkNamePattern"], name or "", re.I):
        return True
    if path and re.search(cfg["forkDirPattern"], path, re.I):
        return True
    return False
