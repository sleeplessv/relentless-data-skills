#!/usr/bin/env python3
"""Draw a dependency graph as static SVG for a dossier figure.

Reads a small graph as JSON and prints an HTML fragment: a
`.figframe.dag-frame` holding two SVGs of the same graph, left-to-right
(`svg.dag.dag-lr`) and top-to-bottom (`svg.dag.dag-tb`), then a
`p.legend`. The scaffold's container query shows the LR drawing when the
frame is at least 980px wide and the TB drawing below that. Every colour comes
from the scaffold's classes; the SVG carries no colour of its own.

    python3 dag_svg.py graph.json [--out dag.html]      # - reads stdin

graph.json:

    {
      "nodes": [{"id": "lint", "name": "lint_skill.py", "tag": "SCR",
                 "caption": ["scripts/", "degree 21"],     # or one string
                 "group_count": 17,                        # optional: a merged node
                 "rank": 2}],                              # optional lower bound
      "edges": [["ci", "lint"]],                           # from reader to read
      "groups": [{"id": "rest", "name": "other skills", "tag": "SKL",
                  "caption": "skills/", "members": ["a", "b", "c"]}],
      "focus": "lint",                                     # the subject node
      "legend": {"SKL": "skill", "SCR": "root script"},    # tag order = badge slot
      "label": "Two-hop neighbourhood of lint_skill.py",   # aria-label
      "total_nodes": 56,                                   # nodes in the full graph
      "id": "fig-3"                                        # optional marker-id prefix
    }

A group's members collapse into one dashed node with a count; their edges move
to it. Layout is layered and deterministic: rank by longest path from a
source, order inside a rank by barycentre sweeps, then positions that pull
each node towards its neighbours. Edges that span several ranks run through
their own lane. Names and captions are cut with an ellipsis to fit the box.

Exit codes: 0 fragment written (warnings, such as more than 11 nodes, go to
stderr), 1 the graph is invalid or too big (reason on stderr), 2 usage error.
Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path

W, H = 200, 46            # node box
RX = 5
PAD = 8                   # viewBox margin round the drawing
GEOMETRY = {              # main = along the ranks, cross = across them
    "lr": {"main_gap": 26, "cross_gap": 14},
    "tb": {"main_gap": 44, "cross_gap": 16},
}
WARN_ABOVE = 11           # more nodes than this: warn and suggest groups
MAX_NODES = 15            # more nodes than this: refuse
SLOTS = 6                 # badge colour slots in the scaffold: tag-1 .. tag-6

# Text metrics, in em, measured in Chromium on the scaffold's font stacks
# (system sans 600 for names, ui-monospace for captions) and padded 5% so
# Arial-class fallbacks still fit.
SANS_EM = {
    **dict.fromkeys("0689", 0.64), "1": 0.47, "2": 0.59, "3": 0.62, "4": 0.63, "5": 0.61, "7": 0.56,
    "a": 0.53, "b": 0.58, "c": 0.53, "d": 0.58, "e": 0.54, "f": 0.34, "g": 0.58, "h": 0.57,
    "i": 0.23, "j": 0.23, "k": 0.52, "l": 0.23, "m": 0.84, "n": 0.56, "o": 0.56, "p": 0.58,
    "q": 0.58, "r": 0.35, "s": 0.50, "t": 0.34, "u": 0.56, "v": 0.52, "w": 0.77, "x": 0.51,
    "y": 0.53, "z": 0.49, "A": 0.67, "B": 0.63, "C": 0.70, "D": 0.69, "E": 0.57, "F": 0.54,
    "G": 0.72, "H": 0.72, "I": 0.25, "J": 0.54, "K": 0.64, "L": 0.54, "M": 0.85, "N": 0.71,
    "O": 0.75, "P": 0.60, "Q": 0.75, "R": 0.63, "S": 0.62, "T": 0.59, "U": 0.70, "V": 0.66,
    "W": 0.95, "X": 0.67, "Y": 0.65, "Z": 0.63, " ": 0.28, ".": 0.23, ",": 0.23, ":": 0.23,
    ";": 0.23, "-": 0.44, "_": 0.55, "/": 0.30, "\\": 0.30, "(": 0.36, ")": 0.36, "[": 0.36,
    "]": 0.36, "{": 0.36, "}": 0.36, "'": 0.27, '"': 0.44, "!": 0.30, "?": 0.52, "|": 0.23,
    "@": 0.88, "%": 0.86, "&": 0.69, "·": 0.23, "…": 0.65,
}
SANS_DEFAULT_EM = 0.65    # other ASCII symbols; wide scripts use 1.0
SANS_PAD = 1.05
MONO_EM = 0.61
NAME_PX, CAPTION_PX, COUNT_PX = 12.5, 10.5, 11
TAG_CHAR_PX = 6.4         # badge: 9.5px bold mono with 0.05em tracking, plus margin
ELLIPSIS = "…"


class GraphError(ValueError):
    """The graph cannot be drawn: bad input, a cycle, or too many nodes."""


def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- loading

def _caption(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " · ".join(str(v) for v in value if str(v))
    return str(value)


def _node(raw, where):
    if not isinstance(raw, dict):
        raise GraphError(f"{where}: expected an object")
    nid = raw.get("id")
    if not isinstance(nid, str) or not nid:
        raise GraphError(f"{where}: needs a string id")
    name, tag = raw.get("name"), raw.get("tag")
    if not isinstance(name, str) or not name.strip():
        raise GraphError(f"node {nid}: needs a name")
    if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9]{1,4}", tag):
        raise GraphError(f"node {nid}: tag must be 1 to 4 letters or digits, as SKL or CI")
    count = raw.get("group_count")
    if count is not None and (not isinstance(count, int) or count < 1):
        raise GraphError(f"node {nid}: group_count must be a positive whole number")
    rank = raw.get("rank")
    if rank is not None and (not isinstance(rank, int) or rank < 0):
        raise GraphError(f"node {nid}: rank must be a whole number from 0")
    return {"id": nid, "name": name.strip(), "tag": tag.upper(), "caption": _caption(raw.get("caption")),
            "count": count, "rank": rank}


def load(data):
    """Validate a graph dict and return it normalised; raises GraphError.

    The result holds nodes (after groups collapse), deduplicated edges, the
    badge slot of each tag, the legend, and a list of warnings.
    """
    if not isinstance(data, dict):
        raise GraphError("the graph must be a JSON object with nodes and edges")
    nodes = [_node(n, f"nodes[{i}]") for i, n in enumerate(data.get("nodes") or [])]
    if not nodes:
        raise GraphError("the graph has no nodes")
    ids = [n["id"] for n in nodes]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise GraphError("duplicate node id: " + ", ".join(dupes))
    known = set(ids)
    edges = []
    for i, e in enumerate(data.get("edges") or []):
        if not (isinstance(e, (list, tuple)) and len(e) == 2):
            raise GraphError(f"edges[{i}]: expected [from, to]")
        a, b = e
        for end in (a, b):
            if end not in known:
                raise GraphError(f"edges[{i}]: unknown node {end!r}")
        if a == b:
            raise GraphError(f"edges[{i}]: {a} points at itself")
        edges.append((a, b))

    owner, group_ids = {}, set()
    for gi, grp in enumerate(data.get("groups") or []):
        members = grp.get("members") if isinstance(grp, dict) else None
        if not isinstance(members, list) or len(members) < 2:
            raise GraphError(f"groups[{gi}]: needs a members list of at least two node ids")
        gnode = _node(dict(grp, group_count=grp.get("group_count", len(members))), f"groups[{gi}]")
        if gnode["id"] in known:
            raise GraphError(f"groups[{gi}]: id {gnode['id']} is already a node")
        for m in members:
            if m not in known:
                raise GraphError(f"groups[{gi}]: unknown member {m!r}")
            if m in group_ids:
                raise GraphError(f"node {m} is a group; groups cannot nest")
            if m in owner:
                raise GraphError(f"node {m} is in two groups")
            owner[m] = gnode["id"]
        first = min(ids.index(m) for m in members)
        nodes.insert(first, gnode)
        ids.insert(first, gnode["id"])
        known.add(gnode["id"])
        group_ids.add(gnode["id"])
    if owner:
        nodes = [n for n in nodes if n["id"] not in owner]
        moved = [(owner.get(a, a), owner.get(b, b)) for a, b in edges]
        edges = [(a, b) for a, b in moved if a != b]
    seen, unique = set(), []
    for e in edges:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    edges = unique

    order = [n["id"] for n in nodes]
    cycle = _find_cycle(order, edges)
    if cycle:
        raise GraphError("the graph has a cycle: " + " -> ".join(cycle))

    focus = data.get("focus", data.get("subject"))
    if focus is not None and focus not in order:
        focus = owner.get(focus, focus)
        if focus not in order:
            raise GraphError(f"focus {focus!r} is not a node")

    legend_in = data.get("legend") or {}
    if not isinstance(legend_in, dict):
        raise GraphError("legend must be an object of tag: label")
    used = {n["tag"] for n in nodes}
    slots, legend = {}, []
    for tag, label in list((str(t).upper(), str(l)) for t, l in legend_in.items()) + \
            [(n["tag"], n["tag"]) for n in nodes]:
        if tag in used and tag not in slots:
            slots[tag] = len(slots) + 1
            legend.append((tag, label))
    if len(used) > SLOTS:
        raise GraphError(f"{len(used)} node types; the scaffold has {SLOTS} badge colours. "
                         "Merge types or drop the rarest.")

    warnings = []
    drawn = len(nodes)
    if drawn > MAX_NODES:
        raise GraphError(f"{drawn} nodes; a dossier DAG draws at most {MAX_NODES}. "
                         + _merge_hint(nodes, edges, focus))
    if drawn > WARN_ABOVE:
        warnings.append(f"{drawn} nodes; aim for {WARN_ABOVE} or fewer. " + _merge_hint(nodes, edges, focus))

    total = data.get("total_nodes")
    if total is not None and (not isinstance(total, int) or total < drawn):
        raise GraphError("total_nodes must be a whole number no smaller than the nodes drawn")
    label = str(data.get("label") or "Dependency graph")
    uid = data.get("id")
    if uid is None:
        canon = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
        uid = "dag-" + hashlib.sha1(canon.encode("utf-8")).hexdigest()[:8]
    uid = re.sub(r"[^A-Za-z0-9_-]", "-", str(uid))
    return {"nodes": nodes, "edges": edges, "focus": focus, "slots": slots, "legend": legend,
            "label": label, "total": total, "uid": uid, "warnings": warnings}


def _find_cycle(order, edges):
    succ = {i: [] for i in order}
    for a, b in edges:
        succ[a].append(b)
    state, stack = {}, []

    def visit(n):
        state[n] = 1
        stack.append(n)
        for m in succ[n]:
            if state.get(m) == 1:
                return stack[stack.index(m):] + [m]
            if m not in state:
                found = visit(m)
                if found:
                    return found
        state[n] = 2
        stack.pop()
        return None

    for n in order:
        if n not in state:
            found = visit(n)
            if found:
                return found
    return None


def _merge_hint(nodes, edges, focus):
    """Name sibling sets (same type, same neighbours) that could become one group."""
    pred = {n["id"]: set() for n in nodes}
    succ = {n["id"]: set() for n in nodes}
    for a, b in edges:
        succ[a].add(b)
        pred[b].add(a)
    sets = {}
    for n in nodes:
        if n["id"] == focus or n["count"]:
            continue
        key = (n["tag"], frozenset(pred[n["id"]]), frozenset(succ[n["id"]]))
        sets.setdefault(key, []).append(n["id"])
    found = sorted((v for v in sets.values() if len(v) > 1), key=lambda v: (-len(v), v))
    if not found:
        return "Draw a smaller neighbourhood, or merge nodes into groups."
    return "Merge siblings into groups: " + "; ".join(", ".join(v) for v in found) + "."


# ---------------------------------------------------------------- layout

def _ranks(g):
    order = [n["id"] for n in g["nodes"]]
    pred = {i: [] for i in order}
    for a, b in g["edges"]:
        pred[b].append(a)
    floor = {n["id"]: n["rank"] or 0 for n in g["nodes"]}
    rank = {}

    def r(n):
        if n not in rank:
            rank[n] = max([floor[n]] + [r(p) + 1 for p in pred[n]])
        return rank[n]

    for n in order:
        r(n)
    return {n: rank[n] for n in order}


def _crossings(layer_a, layer_b, links):
    pos_a = {v: i for i, v in enumerate(layer_a)}
    pos_b = {v: i for i, v in enumerate(layer_b)}
    pairs = [(pos_a[u], pos_b[v]) for u, v in links if u in pos_a and v in pos_b]
    return sum(1 for i in range(len(pairs)) for j in range(i + 1, len(pairs))
               if (pairs[i][0] - pairs[j][0]) * (pairs[i][1] - pairs[j][1]) < 0)


def _isotonic(targets, weights):
    """Non-decreasing values closest to targets (weighted least squares), pool adjacent violators."""
    blocks = []  # [weighted sum, weight, count]
    for t, w in zip(targets, weights):
        blocks.append([t * w, w, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, ww, c = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += ww
            blocks[-1][2] += c
    out = []
    for s, w, c in blocks:
        out.extend([s / w] * c)
    return out


def layout(g, mode):
    """Positions for a loaded graph in mode "lr" or "tb".

    Returns a dict: ranks (id -> rank), boxes (id -> (x, y) top-left of a W x H
    box), paths (list of (from, to, svg path d)), and viewbox (x, y, w, h).
    """
    if mode not in GEOMETRY:
        raise ValueError(f"mode must be lr or tb, not {mode!r}")
    geo = GEOMETRY[mode]
    main_size, cross_size = (W, H) if mode == "lr" else (H, W)
    ranks = _ranks(g)
    order_index = {n["id"]: i for i, n in enumerate(g["nodes"])}

    # layered graph: a dummy item holds an edge's place in each rank it crosses
    item_rank = dict(ranks)
    chains, links = [], []
    for ei, (a, b) in enumerate(g["edges"]):
        chain = [a]
        for r in range(ranks[a] + 1, ranks[b]):
            d = f"\0{ei}:{r}"
            item_rank[d] = r
            order_index[d] = order_index[a] + 0.5
            chain.append(d)
        chain.append(b)
        chains.append((a, b, chain))
        links.extend(zip(chain, chain[1:]))
    depth = max(item_rank.values()) + 1
    up = {v: [] for v in item_rank}
    down = {v: [] for v in item_rank}
    for u, v in links:
        down[u].append(v)
        up[v].append(u)

    # order inside each rank: barycentre sweeps, keep the order with fewest crossings
    layers = [sorted((v for v in item_rank if item_rank[v] == r), key=lambda v: order_index[v])
              for r in range(depth)]

    def sweep(layers, downward):
        layers = [list(l) for l in layers]
        rng = range(1, depth) if downward else range(depth - 2, -1, -1)
        for r in rng:
            ref = {v: i for i, v in enumerate(layers[r - 1 if downward else r + 1])}
            cur = {v: i for i, v in enumerate(layers[r])}

            def bary(v, ref=ref, cur=cur):
                nb = [ref[u] for u in (up[v] if downward else down[v]) if u in ref]
                return sum(nb) / len(nb) if nb else cur[v]
            layers[r].sort(key=bary)
        return layers

    def total_crossings(layers):
        return sum(_crossings(layers[r], layers[r + 1], links) for r in range(depth - 1))

    layers = sweep(layers, True)
    best, best_x = layers, total_crossings(layers)
    for it in range(12):
        layers = sweep(layers, it % 2 == 1)
        x = total_crossings(layers)
        if x < best_x:
            best, best_x = layers, x
    layers = best

    # cross-axis positions: pull towards neighbours, keep order and spacing
    size = {v: (0 if v.startswith("\0") else cross_size) for v in item_rank}
    weight = {v: (2.0 if v.startswith("\0") else 1.0) for v in item_rank}
    centre = {}
    for layer in layers:
        c = 0.0
        for i, v in enumerate(layer):
            if i:
                c += size[layer[i - 1]] / 2 + geo["cross_gap"] + size[v] / 2
            centre[v] = c
    for it in range(40):
        rng = range(depth) if it % 2 == 0 else range(depth - 1, -1, -1)
        for r in rng:
            layer = layers[r]
            offsets, off = [], 0.0
            for i, v in enumerate(layer):
                if i:
                    off += size[layer[i - 1]] / 2 + geo["cross_gap"] + size[v] / 2
                offsets.append(off)
            targets = []
            for v, o in zip(layer, offsets):
                nb = up[v] + down[v]
                want = sum(centre[u] for u in nb) / len(nb) if nb else centre[v]
                targets.append(want - o)
            for v, d, o in zip(layer, _isotonic(targets, [weight[v] for v in layer]), offsets):
                centre[v] = d + o
    low = min(centre[v] - size[v] / 2 for v in centre)
    for v in centre:
        centre[v] = round(centre[v] - low, 1)

    def main_at(v):
        return item_rank[v] * (main_size + geo["main_gap"])

    def point(m, c):  # (main, cross) -> (x, y)
        return (m, c) if mode == "lr" else (c, m)

    boxes = {}
    for n in g["nodes"]:
        v = n["id"]
        boxes[v] = point(main_at(v), centre[v] - cross_size / 2)

    paths = []
    for a, b, chain in chains:
        pts = [(main_at(a) + main_size, centre[a])]       # leave from the far side of a
        for d in chain[1:-1]:
            pts.append((main_at(d), centre[d]))
            pts.append((main_at(d) + main_size, centre[d]))
        pts.append((main_at(b) - 2, centre[b]))           # stop short: the arrowhead ends here
        d = "M" + _xy(point(*pts[0]))
        for i in range(1, len(pts)):
            (m0, c0), (m1, c1) = pts[i - 1], pts[i]
            if i % 2 == 0:                                # straight run through a dummy's rank
                d += " L" + _xy(point(m1, c1))
                continue
            mid = (m1 - m0) / 2
            d += (" C" + _xy(point(m0 + mid, c0)) + " " + _xy(point(m1 - mid, c1))
                  + " " + _xy(point(m1, c1)))
        paths.append((a, b, d))

    mains = [main_at(v) for v in item_rank]
    lo_c = min(centre[v] - size[v] / 2 for v in centre)
    hi_c = max(centre[v] + size[v] / 2 for v in centre)
    lo, hi = point(min(mains), lo_c), point(max(mains) + main_size, hi_c)
    viewbox = (lo[0] - PAD, lo[1] - PAD, hi[0] - lo[0] + 2 * PAD, hi[1] - lo[1] + 2 * PAD)
    return {"ranks": ranks, "boxes": boxes, "paths": paths, "viewbox": viewbox}


def _f(v):
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _xy(p):
    return f"{_f(p[0])},{_f(p[1])}"


# ---------------------------------------------------------------- drawing

def text_width(text, px, mono=False):
    """Estimated rendered width of text in px; errs wide so text never spills."""
    if mono:
        return len(text) * MONO_EM * px
    em = 0.0
    for ch in text:
        if ch in SANS_EM:
            em += SANS_EM[ch]
        else:
            em += 1.0 if ord(ch) > 0x2E80 else SANS_DEFAULT_EM
    return em * px * SANS_PAD


def fit(text, limit, px, mono=False):
    """Text cut with an ellipsis so its estimated width is at most limit px."""
    if text_width(text, px, mono) <= limit:
        return text
    while text and text_width(text.rstrip() + ELLIPSIS, px, mono) > limit:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS if text.strip() else ELLIPSIS


def _tag_width(tag):
    return len(tag) * TAG_CHAR_PX + 9


def _chip_width(count):
    return max(24, len(str(count)) * 7 + 10)


def _node_svg(n, x, y, slot, focus):
    tag, count = n["tag"], n["count"]
    tw = _tag_width(tag)
    right = W - 8 - (_chip_width(count) + 6 if count else 0)
    name_x = 10 + tw + 6
    name = fit(n["name"], right - name_x, NAME_PX)
    caption = fit(n["caption"], right - 10, CAPTION_PX, mono=True)
    cls = f"dn tag-{slot}" + (" focus" if focus else "") + (" group" if count else "")
    s = [f'<g class="{cls}" transform="translate({_f(x)},{_f(y)})">',
         f'<rect class="box" width="{W}" height="{H}" rx="{RX}"/>',
         f'<rect class="tag" x="10" y="8" width="{_f(tw)}" height="14" rx="2.5"/>',
         f'<text class="tg" x="{_f(10 + tw / 2)}" y="18.6" text-anchor="middle">{esc(tag)}</text>',
         f'<text class="nm" x="{_f(name_x)}" y="19.5">{esc(name)}</text>']
    if caption:
        s.append(f'<text class="cp" x="10" y="37">{esc(caption)}</text>')
    if count:
        cw = _chip_width(count)
        s.append(f'<rect class="cnt" x="{_f(W - 8 - cw)}" y="{_f(H / 2 - 10)}" width="{cw}" height="20" rx="3"/>'
                 f'<text class="cn" x="{_f(W - 8 - cw / 2)}" y="{_f(H / 2 + 4.2)}" text-anchor="middle">{count}</text>')
    title = n["name"] + (f" · {n['caption']}" if n["caption"] else "")
    s.append(f"<title>{esc(title)}</title></g>")
    return "".join(s)


def _svg(g, mode):
    lay = layout(g, mode)
    vx, vy, vw, vh = lay["viewbox"]
    mid = f"{g['uid']}-{mode}-arrow"
    drawn = len(g["nodes"])
    count = f"{drawn} of {g['total']} nodes drawn" if g["total"] else f"{drawn} nodes"
    edges = "".join(f'<path d="{d}" marker-end="url(#{mid})"/>' for _, _, d in lay["paths"])
    nodes = "".join(_node_svg(n, *lay["boxes"][n["id"]], g["slots"][n["tag"]], n["id"] == g["focus"])
                    for n in g["nodes"])
    return (f'<svg class="dag dag-{mode}" viewBox="{_f(vx)} {_f(vy)} {_f(vw)} {_f(vh)}" '
            f'width="{vw:.0f}" style="max-width:{vw:.0f}px" role="img" '
            f'aria-label="{esc(g["label"])}: {count}">'
            f'<defs><marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path class="arrow" d="M0,1 L9,5 L0,9 z"/></marker></defs>'
            f'<g class="edges">{edges}</g><g class="nodes">{nodes}</g></svg>')


def _legend(g):
    keys = [f'<span class="k"><span class="tgk tag-{g["slots"][t]}">{esc(t)}</span>{esc(label)}</span>'
            for t, label in g["legend"]]
    focus = next((n for n in g["nodes"] if n["id"] == g["focus"]), None)
    if focus:
        keys.append(f'<span class="k"><span class="tgk focus">{esc(focus["tag"])}</span>subject</span>')
    if any(n["count"] for n in g["nodes"]):
        keys.append('<span class="k"><span class="grpk"></span>merged group, count at right</span>')
    return '<p class="legend">' + "".join(keys) + "</p>"


def render(g):
    """The HTML fragment for a loaded graph: dag-frame with LR and TB SVGs, then the legend."""
    return ('<div class="figframe dag-frame">\n' + _svg(g, "lr") + "\n" + _svg(g, "tb")
            + "\n</div>\n" + _legend(g))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draw a dependency graph (JSON) as static SVG for a dossier.")
    ap.add_argument("graph", help="graph JSON file, or - for stdin")
    ap.add_argument("--out", help="write the fragment here instead of stdout")
    args = ap.parse_args(argv)
    try:
        raw = sys.stdin.read() if args.graph == "-" else Path(args.graph).read_text(encoding="utf-8")
        g = load(json.loads(raw))
    except (OSError, ValueError) as e:  # GraphError and JSONDecodeError are ValueErrors
        print(f"dag_svg: {e}", file=sys.stderr)
        return 1
    for w in g["warnings"]:
        print(f"dag_svg: warning: {w}", file=sys.stderr)
    fragment = render(g)
    if args.out:
        Path(args.out).write_text(fragment + "\n", encoding="utf-8")
    else:
        print(fragment)
    return 0


if __name__ == "__main__":
    sys.exit(main())
