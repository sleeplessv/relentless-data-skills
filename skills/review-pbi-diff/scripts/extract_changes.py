#!/usr/bin/env python3
"""Extract a structured change model from a git diff of a PBIP (Power BI Project) repo.

Parses PBIR report JSON (pages/visuals) and TMDL semantic-model files on both
sides of a git ref range and emits:

  <out>/change_model.json                 -- the structured change model
  <out>/objects/<repo-path>.before|.after -- raw before/after of every changed file

Usage:
  python3 extract_changes.py [RANGE] --out DIR [--repo ROOT]

RANGE forms (default: main...HEAD):
  A...B   merge-base(A,B) vs B
  A..B    A vs B
  A       A vs working tree
Stdlib only. Requires git.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

WORKTREE = "<worktree>"

# ---------------------------------------------------------------- git helpers


def git(repo, *args, check=True):
    res = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True
    )
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout


def resolve_range(repo, rng):
    """Return (base_ref, head_ref); head_ref may be WORKTREE."""
    if "..." in rng:
        a, b = rng.split("...", 1)
        b = b or "HEAD"
        base = git(repo, "merge-base", a, b).strip()
        return base, b
    if ".." in rng:
        a, b = rng.split("..", 1)
        return a, b or "HEAD"
    return rng, WORKTREE


def list_changed(repo, base, head):
    """[(status, path)] with status in A/M/D."""
    cmd = ["diff", "--name-status", "--no-renames"]
    out = git(repo, *cmd, base) if head == WORKTREE else git(repo, *cmd, base, head)
    changes = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            changes.append((parts[0][0], parts[1]))
    if head == WORKTREE:
        # plain `git diff` never lists untracked files
        seen = {p for _, p in changes}
        for path in git(repo, "ls-files", "--others", "--exclude-standard").splitlines():
            if path and path not in seen:
                changes.append(("A", path))
    return changes


def read_at(repo, ref, path):
    """File content at ref (or worktree), None if absent."""
    if ref == WORKTREE:
        full = os.path.join(repo, path)
        if not os.path.isfile(full):
            return None
        with open(full, encoding="utf-8-sig") as f:
            return f.read()
    res = subprocess.run(
        ["git", "-C", repo, "show", f"{ref}:{path}"], capture_output=True, text=True
    )
    return res.stdout if res.returncode == 0 else None


def ls_dir(repo, ref, prefix):
    """All file paths under prefix/ at ref."""
    if ref == WORKTREE:
        full = os.path.join(repo, prefix)
        out = []
        for root, _dirs, files in os.walk(full):
            for f in files:
                out.append(os.path.relpath(os.path.join(root, f), repo))
        return out
    res = subprocess.run(
        ["git", "-C", repo, "ls-tree", "-r", "--name-only", ref, "--", prefix],
        capture_output=True,
        text=True,
    )
    return res.stdout.splitlines() if res.returncode == 0 else []


def load_json(text):
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ------------------------------------------------------------ path classifiers

RE_VISUAL = re.compile(
    r"^(?P<rdir>.*/(?P<report>[^/]+)\.Report)/definition/pages/(?P<page>[^/]+)/visuals/(?P<visual>[^/]+)/visual\.json$"
)
RE_PAGE = re.compile(
    r"^(?P<rdir>.*/(?P<report>[^/]+)\.Report)/definition/pages/(?P<page>[^/]+)/page\.json$"
)
RE_REPORT_FILE = re.compile(r"^(?P<rdir>.*/(?P<report>[^/]+)\.Report)/")
RE_TABLE = re.compile(
    r"^(?P<mdir>.*/(?P<model>[^/]+)\.SemanticModel)/definition/tables/(?P<table>.+)\.tmdl$"
)
RE_MODEL_FILE = re.compile(r"^(?P<mdir>.*/(?P<model>[^/]+)\.SemanticModel)/")


# --------------------------------------------------------- PBIR visual parsing


def safe_get(obj, *keys):
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            obj = obj[k]
        elif isinstance(obj, list) and isinstance(k, int) and len(obj) > k:
            obj = obj[k]
        else:
            return None
    return obj


def literal_value(v):
    """Unwrap a PBIR literal like 'Some text' or 12D."""
    if not isinstance(v, str):
        return v
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return v[1:-1]
    return v


def visual_title(obj):
    t = safe_get(
        obj, "visual", "visualContainerObjects", "title", 0, "properties",
        "text", "expr", "Literal", "Value",
    )
    return literal_value(t)


def textbox_text(obj):
    paras = safe_get(obj, "visual", "objects", "general", 0, "properties", "paragraphs")
    if not isinstance(paras, list):
        return None
    runs = []
    for p in paras:
        for r in p.get("textRuns", []):
            if isinstance(r.get("value"), str):
                runs.append(r["value"])
    text = " ".join(runs).strip()
    return text or None


def visual_fields(obj):
    """{role: [queryRef, ...]} from query.queryState."""
    qs = safe_get(obj, "visual", "query", "queryState") or {}
    fields = {}
    for role, spec in qs.items():
        refs = []
        for proj in spec.get("projections", []):
            ref = proj.get("queryRef") or proj.get("nativeQueryRef")
            if ref:
                refs.append(ref)
        if refs:
            fields[role] = refs
    return fields


def field_ref(field):
    """'Entity.Property' (or 'Entity.Hierarchy.Level') from a PBIR field
    expression, best effort. Walks the expression tree generically so it
    handles Measure, Column, HierarchyLevel, Aggregation, etc."""

    def walk(node):
        entity, names = None, []
        if not isinstance(node, dict):
            return None, []
        for k, v in node.items():
            if k == "SourceRef" and isinstance(v, dict) and v.get("Entity"):
                entity = v["Entity"]
            elif k in ("Property", "Hierarchy", "Level") and isinstance(v, str):
                names.append(v)
            elif isinstance(v, dict):
                e2, n2 = walk(v)
                entity = entity or e2
                names = n2 + names
        return entity, names

    entity, names = walk(field if isinstance(field, dict) else {})
    if entity:
        return f"{entity}.{'.'.join(names)}" if names else entity
    return None


def parse_filters(cfg):
    """Compact list of filters from a filterConfig block."""
    out = []
    for f in (cfg or {}).get("filters", []):
        entry = {
            "field": field_ref(f.get("field")),
            "type": f.get("type"),
        }
        cond = f.get("filter")
        if cond is not None:
            s = json.dumps(cond, separators=(",", ":"))
            entry["condition"] = s if len(s) <= 400 else s[:400] + "...(truncated)"
        if f.get("isHiddenInViewMode"):
            entry["hidden_in_view"] = True
        out.append(entry)
    return out


def summarize_visual(obj):
    if obj is None:
        return None
    pos = obj.get("position", {})
    s = {
        "name": obj.get("name"),
        "x": pos.get("x"),
        "y": pos.get("y"),
        "z": pos.get("z"),
        "width": pos.get("width"),
        "height": pos.get("height"),
    }
    if obj.get("isHidden"):
        s["hidden"] = True
    if obj.get("parentGroupName"):
        s["parent_group"] = obj["parentGroupName"]
    if "visualGroup" in obj:
        s["visual_type"] = "visualGroup"
        s["title"] = safe_get(obj, "visualGroup", "displayName")
    else:
        s["visual_type"] = safe_get(obj, "visual", "visualType")
        s["title"] = visual_title(obj)
        if s["visual_type"] == "textbox" and not s["title"]:
            s["title"] = textbox_text(obj)
        fields = visual_fields(obj)
        if fields:
            s["fields"] = fields
    filters = parse_filters(obj.get("filterConfig"))
    if filters:
        s["filters"] = filters
    return s


def changed_paths(a, b, max_depth=3, cap=40):
    """Dotted paths (to max_depth) where two JSON values differ."""
    out = []

    def rec(x, y, path, depth):
        if len(out) >= cap or x == y:
            return
        if depth >= max_depth or type(x) is not type(y) or not isinstance(x, (dict, list)):
            out.append(path or "(root)")
            return
        if isinstance(x, dict):
            for k in sorted(set(x) | set(y)):
                rec(x.get(k), y.get(k), f"{path}.{k}" if path else k, depth + 1)
        else:
            if len(x) != len(y):
                out.append(f"{path}[items {len(x)}->{len(y)}]")
                return
            for i, (xi, yi) in enumerate(zip(x, y)):
                rec(xi, yi, f"{path}[{i}]", depth + 1)

    rec(a, b, "", 0)
    return out


def resolve_group_offsets(visuals):
    """Add abs_x/abs_y by walking parent_group chains (positions of grouped
    visuals are relative to their group)."""
    by_name = {v["name"]: v for v in visuals.values() if v}

    def abs_pos(v, seen):
        x, y = v.get("x") or 0, v.get("y") or 0
        parent = v.get("parent_group")
        if parent and parent in by_name and parent not in seen:
            px, py = abs_pos(by_name[parent], seen | {parent})
            return x + px, y + py
        return x, y

    for v in visuals.values():
        if v:
            v["abs_x"], v["abs_y"] = abs_pos(v, set())


# ------------------------------------------------------------- TMDL parsing


def indent_of(line):
    return len(line) - len(line.lstrip("\t"))


def unquote(name):
    name = name.strip()
    if len(name) >= 2 and name[0] == "'" and name[-1] == "'":
        return name[1:-1]
    return name


MEMBER_RE = re.compile(
    r"^(?P<kw>measure|column|function|calculationItem)\s+"
    r"(?P<name>'[^']*'|\"[^\"]*\"|[^=\s]+)\s*(?P<eq>=\s*(?P<expr>.*))?$"
)
PROP_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9]*)\s*(?::\s*(?P<val>.*)|(?P<bare>)|=.*)$")
SKIP_MEMBERS = {
    "partition", "hierarchy", "refreshPolicy", "annotation", "extendedProperty",
    "changedProperty", "variation", "calculationGroup", "level",
}
KEEP_PROPS = {
    "formatString", "displayFolder", "dataType", "sourceColumn", "summarizeBy",
    "sortByColumn", "dataCategory", "isHidden", "description",
    # relationship properties
    "fromColumn", "toColumn", "fromCardinality", "toCardinality", "isActive",
    "crossFilteringBehavior", "securityFilteringBehavior", "joinOnDateBehavior",
    "relyOnReferentialIntegrity",
}


def dedent_expr(lines):
    lines = [ln for ln in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    # TMDL verbatim expressions are fenced with ``` lines
    if len(lines) >= 2 and lines[0].strip() == "```" and lines[-1].strip() == "```":
        lines = lines[1:-1]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
    if not lines:
        return ""
    common = min(indent_of(ln) for ln in lines if ln.strip())
    return "\n".join(ln[common:] if ln.strip() else "" for ln in lines)


def parse_tmdl(text):
    """Parse table/relationship/function TMDL. Returns
    {tables: {name: {measures: {..}, columns: {..}, calculation_items: {..}}},
     functions: {name: {dax, ...}}, relationships: {id: {props}}}"""
    result = {"tables": {}, "functions": {}, "relationships": {}}
    if text is None:
        return result
    lines = text.replace("\r\n", "\n").split("\n")

    cur_table = None
    member = None          # dict being filled
    member_indent = None   # indent of member header
    expr_lines = None      # collecting expression lines (or None)
    props_started = False
    pending_desc = []

    def close_member():
        nonlocal member, expr_lines, props_started
        if member is not None and expr_lines is not None:
            member["dax"] = dedent_expr(expr_lines)
        member, expr_lines, props_started = None, None, False

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        ind = indent_of(line)

        # blank lines: may separate expression parts; keep if collecting expr
        if not stripped:
            if member is not None and expr_lines is not None and not props_started:
                expr_lines.append("")
            continue

        if stripped.startswith("///"):
            pending_desc.append(stripped[3:].strip())
            continue

        # inside a member: expression continuation is anything indented at
        # least two levels below the header, before the first property line
        if member is not None:
            if ind >= member_indent + 2 and not props_started:
                expr_lines.append(line) if expr_lines is not None else None
                continue
            if ind == member_indent + 1:
                props_started = True
                m = PROP_RE.match(stripped)
                if m and m.group("key") in KEEP_PROPS:
                    val = m.group("val")
                    member["props"][m.group("key")] = (
                        True if val is None else val.strip()
                    )
                continue
            if ind > member_indent + 1:
                continue  # sub-block of a property; ignore
            close_member()  # dedent past the member: fall through

        # top-level constructs
        if ind == 0:
            if stripped.startswith("table "):
                cur_table = unquote(stripped[len("table "):])
                result["tables"][cur_table] = {
                    "measures": {}, "columns": {}, "calculation_items": {},
                }
                pending_desc = []
                continue
            if stripped.startswith("relationship "):
                rel_id = stripped[len("relationship "):].strip()
                member = {"props": {}}
                member_indent = 0
                expr_lines = None
                result["relationships"][rel_id] = member["props"]
                # relationships have no expression; reuse prop collection
                # by treating props as member_indent+1 lines
                continue
            m = MEMBER_RE.match(stripped)
            if m and m.group("kw") == "function":
                name = unquote(m.group("name"))
                member = {"props": {}}
                if pending_desc:
                    member["description"] = " ".join(pending_desc)
                member_indent = 0
                expr_lines = [m.group("expr")] if m.group("expr") else []
                result["functions"][name] = member
                pending_desc = []
                continue
            pending_desc = []
            continue

        # table members (indent 1) / calc items (indent 2 under calculationGroup)
        m = MEMBER_RE.match(stripped)
        if m and cur_table and m.group("kw") in ("measure", "column", "calculationItem"):
            kw = m.group("kw")
            name = unquote(m.group("name"))
            member = {"props": {}}
            if pending_desc:
                member["description"] = " ".join(pending_desc)
            member_indent = ind
            expr_lines = [m.group("expr")] if m.group("expr") else []
            if not m.group("eq"):
                expr_lines = None  # plain column: no expression
            bucket = {
                "measure": "measures", "column": "columns",
                "calculationItem": "calculation_items",
            }[kw]
            result["tables"][cur_table][bucket][name] = member
            pending_desc = []
            continue

        first_word = stripped.split(" ")[0].split("(")[0]
        if first_word in SKIP_MEMBERS:
            member = {"props": {}}  # throwaway sink so sub-lines are consumed
            member_indent = ind
            expr_lines = None
        pending_desc = []

    close_member()
    # flatten member dicts: promote dax/props
    for t in result["tables"].values():
        for bucket in ("measures", "columns", "calculation_items"):
            for name, m in t[bucket].items():
                t[bucket][name] = _flatten_member(m)
    for name, m in result["functions"].items():
        result["functions"][name] = _flatten_member(m)
    return result


def _flatten_member(m):
    out = dict(m.get("props", {}))
    if "dax" in m and m["dax"]:
        out["dax"] = m["dax"]
    if "description" in m:
        out["description"] = m["description"]
    return out


def diff_members(before, after):
    """Diff two {name: member} dicts -> added/modified/deleted lists."""
    added, modified, deleted = [], [], []
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name), after.get(name)
        if b is None:
            added.append({"name": name, **a})
        elif a is None:
            deleted.append({"name": name, **b})
        elif a != b:
            entry = {"name": name}
            if a.get("dax") != b.get("dax"):
                entry["dax_before"] = b.get("dax")
                entry["dax_after"] = a.get("dax")
            prop_changes = {
                k: {"before": b.get(k), "after": a.get(k)}
                for k in (set(a) | set(b)) - {"dax"}
                if a.get(k) != b.get(k)
            }
            if prop_changes:
                entry["prop_changes"] = prop_changes
            for k in ("formatString", "displayFolder", "dataType"):
                if k in a:
                    entry.setdefault(k, a[k])
            modified.append(entry)
    return added, modified, deleted


def rel_key(props):
    return f"{props.get('fromColumn')} -> {props.get('toColumn')}"


def diff_relationships(before, after):
    b = {rel_key(p): p for p in before.values()}
    a = {rel_key(p): p for p in after.values()}
    added = [{"relationship": k, **a[k]} for k in sorted(set(a) - set(b))]
    deleted = [{"relationship": k, **b[k]} for k in sorted(set(b) - set(a))]
    modified = [
        {"relationship": k, "before": b[k], "after": a[k]}
        for k in sorted(set(a) & set(b))
        if a[k] != b[k]
    ]
    return added, modified, deleted


# ---------------------------------------------------------------- main build


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("range", nargs="?", default="main...HEAD")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--repo", default=".", help="repo root (default: cwd)")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    base, head = resolve_range(repo, args.range)
    changes = list_changed(repo, base, head)
    if not changes:
        print(f"No changes in range {args.range}", file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)
    obj_dir = os.path.join(args.out, "objects")

    def dump_object(path, status):
        """Write raw before/after of a changed file for drill-down."""
        dest = os.path.join(obj_dir, path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if status in ("M", "D"):
            b = read_at(repo, base, path)
            if b is not None:
                with open(dest + ".before", "w", encoding="utf-8") as f:
                    f.write(b)
        if status in ("A", "M"):
            a = read_at(repo, head, path)
            if a is not None:
                with open(dest + ".after", "w", encoding="utf-8") as f:
                    f.write(a)

    reports = defaultdict(lambda: {
        "report_dir": None,
        "pages": {},
        "other_files": [],
    })
    models = defaultdict(lambda: {
        "model_dir": None,
        "tables": {},
        "functions": None,
        "relationships": None,
        "other_files": [],
    })
    other_changes = []

    visual_status = {}   # (rdir, page, visual) -> status
    page_status = {}     # (rdir, page) -> status
    touched_pages = set()
    table_files = {}     # path -> (model, table, status)
    rel_files = {}       # path -> (model, status)
    func_files = {}      # path -> (model, status)

    for status, path in changes:
        dump_object(path, status)
        mv = RE_VISUAL.match(path)
        if mv:
            key = (mv.group("rdir"), mv.group("page"))
            touched_pages.add(key)
            visual_status[(mv.group("rdir"), mv.group("page"), mv.group("visual"))] = status
            reports[mv.group("report")]["report_dir"] = mv.group("rdir")
            continue
        mp = RE_PAGE.match(path)
        if mp:
            key = (mp.group("rdir"), mp.group("page"))
            touched_pages.add(key)
            page_status[key] = status
            reports[mp.group("report")]["report_dir"] = mp.group("rdir")
            continue
        mt = RE_TABLE.match(path)
        if mt:
            models[mt.group("model")]["model_dir"] = mt.group("mdir")
            table_files[path] = (mt.group("model"), mt.group("table"), status)
            continue
        mm = RE_MODEL_FILE.match(path)
        if mm:
            models[mm.group("model")]["model_dir"] = mm.group("mdir")
            if path.endswith("/definition/relationships.tmdl"):
                rel_files[path] = (mm.group("model"), status)
            elif path.endswith("/definition/functions.tmdl"):
                func_files[path] = (mm.group("model"), status)
            else:
                models[mm.group("model")]["other_files"].append(
                    {"path": path, "status": status}
                )
            continue
        mr = RE_REPORT_FILE.match(path)
        if mr:
            reports[mr.group("report")]["report_dir"] = mr.group("rdir")
            entry = {"path": path, "status": status}
            if path.endswith(".json") and status == "M":
                cp = changed_paths(
                    load_json(read_at(repo, base, path)),
                    load_json(read_at(repo, head, path)),
                )
                if cp:
                    entry["changed_sections"] = cp
            reports[mr.group("report")]["other_files"].append(entry)
            continue
        other_changes.append({"path": path, "status": status})

    # ---- report pages: full page inventory for every touched page
    for rdir, page in sorted(touched_pages):
        report = re.match(r".*/([^/]+)\.Report$", rdir).group(1)
        pstat = page_status.get((rdir, page))
        page_ref = base if pstat == "D" else head
        pjson = load_json(read_at(repo, page_ref, f"{rdir}/definition/pages/{page}/page.json")) or {}

        p = {
            "display_name": pjson.get("displayName"),
            "status": {"A": "added", "D": "deleted", "M": "modified"}.get(
                pstat, "visuals-changed"
            ),
            "width": pjson.get("width"),
            "height": pjson.get("height"),
        }
        if pjson.get("visibility"):
            p["visibility"] = pjson["visibility"]
        # Power BI default page names mark developer scratch work
        if re.fullmatch(r"Page \d+", p["display_name"] or ""):
            p["scratch"] = True
        if pjson.get("pageBinding"):
            p["page_binding"] = safe_get(pjson, "pageBinding", "type")
        pfilters = parse_filters(pjson.get("filterConfig"))
        if pfilters:
            p["filters"] = pfilters
        if pstat == "M":
            cp = changed_paths(
                load_json(read_at(repo, base, f"{rdir}/definition/pages/{page}/page.json")),
                pjson,
            )
            if cp:
                p["page_json_changes"] = cp
            old_name = (load_json(
                read_at(repo, base, f"{rdir}/definition/pages/{page}/page.json")
            ) or {}).get("displayName")
            if old_name and old_name != p["display_name"]:
                p["renamed_from"] = old_name

        # enumerate every visual on the page at head (for wireframes),
        # plus deleted ones from base
        visuals = {}
        vis_prefix = f"{rdir}/definition/pages/{page}/visuals"
        head_paths = [
            pth for pth in ls_dir(repo, head, vis_prefix) if pth.endswith("/visual.json")
        ]
        for vpath in head_paths:
            vid = vpath.split("/")[-2]
            status = visual_status.get((rdir, page, vid))
            summ = summarize_visual(load_json(read_at(repo, head, vpath)))
            if summ is None:
                continue
            summ["status"] = {"A": "added", "M": "modified"}.get(status, "unchanged")
            if status == "M":
                before = load_json(read_at(repo, base, vpath))
                after = load_json(read_at(repo, head, vpath))
                cp = changed_paths(before, after)
                if cp:
                    summ["changed_sections"] = cp
                before_summ = summarize_visual(before)
                if before_summ:
                    for k in ("visual_type", "title", "fields", "filters"):
                        if before_summ.get(k) != summ.get(k):
                            summ[f"{k}_before"] = before_summ.get(k)
            visuals[vid] = summ
        for (r2, p2, vid), status in visual_status.items():
            if (r2, p2) == (rdir, page) and status == "D":
                summ = summarize_visual(
                    load_json(read_at(repo, base, f"{vis_prefix}/{vid}/visual.json"))
                )
                if summ:
                    summ["status"] = "deleted"
                    visuals[vid] = summ

        resolve_group_offsets(visuals)
        counts = defaultdict(int)
        for v in visuals.values():
            counts[v["status"]] += 1
        p["visual_counts"] = dict(counts)
        p["visuals"] = visuals
        reports[report]["pages"][page] = p

    # ---- model layer
    for path, (model, table, status) in sorted(table_files.items()):
        before = parse_tmdl(read_at(repo, base, path))
        after = parse_tmdl(read_at(repo, head, path))
        bt = next(iter(before["tables"].values()), {"measures": {}, "columns": {}, "calculation_items": {}})
        at = next(iter(after["tables"].values()), {"measures": {}, "columns": {}, "calculation_items": {}})
        entry = {
            "status": {"A": "added", "D": "deleted", "M": "modified"}[status],
            "path": path,
        }
        any_member_change = False
        for bucket in ("measures", "columns", "calculation_items"):
            added, modified, deleted = diff_members(bt[bucket], at[bucket])
            for label, items in (("added", added), ("modified", modified), ("deleted", deleted)):
                if items:
                    entry[f"{bucket}_{label}"] = items
                    any_member_change = True
        if not any_member_change and status == "M":
            entry["note"] = (
                "table file changed but no measure/column/calc-item diffs parsed "
                "(partition, hierarchy, refresh policy or annotation change) -- "
                "drill into objects/ before/after files"
            )
        models[model]["tables"][table] = entry

    for path, (model, status) in rel_files.items():
        before = parse_tmdl(read_at(repo, base, path))["relationships"]
        after = parse_tmdl(read_at(repo, head, path))["relationships"]
        added, modified, deleted = diff_relationships(before, after)
        models[model]["relationships"] = {
            "added": added, "modified": modified, "deleted": deleted,
        }

    for path, (model, status) in func_files.items():
        before = parse_tmdl(read_at(repo, base, path))["functions"]
        after = parse_tmdl(read_at(repo, head, path))["functions"]
        added, modified, deleted = diff_members(before, after)
        models[model]["functions"] = {
            "added": added, "modified": modified, "deleted": deleted,
        }

    # ---- assemble + write
    head_sha = (
        git(repo, "rev-parse", "HEAD").strip() if head == WORKTREE
        else git(repo, "rev-parse", head).strip()
    )
    authors = git(
        repo, "log", "--format=%an <%ae>", f"{base}..{'HEAD' if head == WORKTREE else head}"
    ).splitlines()
    commits = git(
        repo, "log", "--format=%h %s", f"{base}..{'HEAD' if head == WORKTREE else head}"
    ).splitlines()

    model_out = {
        "range": args.range,
        "base": git(repo, "rev-parse", base).strip(),
        "head": head_sha if head != WORKTREE else f"{head_sha} + working tree",
        "authors": sorted(set(authors)),
        "commits": commits,
        "total_files_changed": len(changes),
        "reports": {k: v for k, v in sorted(reports.items())},
        "models": {k: v for k, v in sorted(models.items())},
        "other_changes": other_changes,
    }

    out_path = os.path.join(args.out, "change_model.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(model_out, f, indent=1)

    # ---- stdout summary
    print(f"Range: {args.range}  ({len(changes)} files changed, {len(commits)} commits)")
    for name, r in sorted(reports.items()):
        n_pages = len(r["pages"])
        counts = defaultdict(int)
        for p in r["pages"].values():
            for k, v in p.get("visual_counts", {}).items():
                counts[k] += v
        print(
            f"  Report {name}: {n_pages} page(s) touched | visuals "
            + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        )
    for name, m in sorted(models.items()):
        parts = []
        for t, entry in m["tables"].items():
            for key in list(entry):
                if key.endswith(("_added", "_modified", "_deleted")) and entry[key]:
                    parts.append(f"{t}:{key}={len(entry[key])}")
        print(f"  Model {name}: " + (", ".join(parts) if parts else "non-member changes only"))
        if m["relationships"]:
            r = m["relationships"]
            print(
                f"    relationships: +{len(r['added'])} ~{len(r['modified'])} -{len(r['deleted'])}"
            )
        if m["functions"]:
            fn = m["functions"]
            print(
                f"    functions: +{len(fn['added'])} ~{len(fn['modified'])} -{len(fn['deleted'])}"
            )
    print(f"\nChange model: {out_path}")
    print(f"Raw before/after objects: {obj_dir}/")


if __name__ == "__main__":
    main()
