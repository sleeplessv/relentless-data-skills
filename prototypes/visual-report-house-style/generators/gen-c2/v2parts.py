"""v2 additions: GitHub-coloured diff (Figure 8) and the tag-badge DAG nodes (Figure 3) as static SVG."""
import difflib, html, re, subprocess

REPO = "/Users/tumul/projects_repo/relentless-data-skills"
def esc(s): return html.escape(s, quote=True)

# ---------------- Figure 8: SKILL.md Verify step before and after 088a29f ----------------
def _show(rev):
    return subprocess.run(["git", "-C", REPO, "show", f"{rev}:skills/visual-report/SKILL.md"],
                          capture_output=True, text=True, check=True).stdout.splitlines()
OLD, NEW = _show("088a29f^"), _show("088a29f")
assert OLD[34].startswith("- **House style:**") and OLD[35].startswith("- **Verify:**") and OLD[36] == ""
assert NEW[34] == OLD[34] and NEW[35].startswith("- **Verify:**") and NEW[48] == ""

def _words(a, b):
    """Word-level highlight of a paired removed/added line, GitHub style."""
    ta, tb = re.split(r"(\s+)", a), re.split(r"(\s+)", b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    oa, ob = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        x, y = esc("".join(ta[i1:i2])), esc("".join(tb[j1:j2]))
        if op == "equal": oa.append(x); ob.append(y)
        else:
            if x: oa.append(f'<span class="w">{x}</span>')
            if y: ob.append(f'<span class="w">{y}</span>')
    return "".join(oa), "".join(ob)

DIFF_MARKS = {("del", 36): 1, ("add", 39): 2, ("add", 44): 3, ("add", 45): 4, ("add", 46): 5}
def diff_html():
    del_w, add_w = _words(OLD[35], NEW[35])
    rows = [("hunk", "", "", "&#64;&#64; -35,3 +35,15 &#64;&#64; Write one self-contained HTML file and open it.", None)]
    rows.append(("ctx", 35, 35, esc(OLD[34]), None))
    rows.append(("del", 36, "", del_w, None))
    for k in range(35, 48):
        rows.append(("add", "", k + 1, add_w if k == 35 else esc(NEW[k]), None))
    rows.append(("ctx", 37, 49, "", None))
    out = []
    for kind, o, n, text, _ in rows:
        m = DIFF_MARKS.get((kind, o if kind == "del" else n))
        sign = {"add": "+", "del": "-", "ctx": " ", "hunk": ""}[kind]
        attr = f' data-m="{m}"' if m else ""
        out.append(f'<span class="l {kind}{" mark" if m else ""}"{attr}><span class="o">{o}</span><span class="n">{n}</span>'
                   f'<span class="sg">{sign}</span><span class="t">{text or " "}</span></span>')
    return "".join(out)
DIFF = diff_html()
DIFF_COUNTS = (1, 13)  # removed, added

# ---------------- Figure 3: tag-badge nodes, hand-built SVG ----------------
# Node anatomy: rounded box, row 1 = filled type badge + name, row 2 = mono caption. No side strip (house rule).
W, H = 200, 46
NODES = {  # id: (name, tag, caption)
  "check_sh": ("check.sh", "SCR", "scripts/ · degree 4"),
  "ci_lint": ("skill-lint", "CI", "CI job · degree 1"),
  "ci_tests": ("tests", "CI", "CI job · degree 13"),
  "test_lint_skill": ("test_lint_skill.py", "TST", "tests/ · degree 2"),
  "test_visual_report": ("test_visual_report.py", "TST", "tests/ · degree 2"),
  "lint_skill": ("lint_skill.py", "SCR", "scripts/ · degree 21"),
  "other_skills": ("other skills", "SKL", "skills/ · 17 folders"),
  "visual_report": ("visual-report", "SKL", "skills/ · degree 4"),
  "check_render": ("check_render.py", "SKS", "scripts/ · degree 2"),
  "html_report": ("HTML-REPORT.md", "REF", "references/ · degree 1"),
  "visual_language": ("VISUAL-LANGUAGE.md", "REF", "references/ · degree 1"),
}
EDGES = [("ci_tests", "test_lint_skill"), ("ci_tests", "test_visual_report"), ("check_sh", "lint_skill"),
         ("ci_lint", "lint_skill"), ("test_lint_skill", "lint_skill"), ("lint_skill", "other_skills"),
         ("lint_skill", "visual_report"), ("visual_report", "html_report"), ("visual_report", "visual_language"),
         ("visual_report", "check_render"), ("test_visual_report", "check_render")]
RANK = {"check_sh": 0, "ci_lint": 0, "ci_tests": 0, "test_lint_skill": 1, "test_visual_report": 1, "lint_skill": 2,
        "other_skills": 3, "visual_report": 3, "html_report": 4, "visual_language": 4, "check_render": 4}
# badge fill, badge text, border (all pairs in contrast_c.py)
TAGS = {"SKL": ("#102542", "#ffffff"), "SCR": ("#4f7f7c", "#ffffff"), "CI": ("#1a759f", "#ffffff"),
        "TST": ("#5f5348", "#ffffff"), "SKS": ("#24514e", "#ffffff"), "REF": ("#ffffff", "#4a5755"),
        "FOCUS": ("#f87060", "#102542")}
TAG_NAMES = [("SKL", "skill"), ("SCR", "root script"), ("CI", "CI job"), ("TST", "test"), ("SKS", "skill script"), ("REF", "reference")]

# LR: rank -> x, hand-placed y centres; TB: rank -> y, slot -> x
LR_Y = {"check_sh": 0, "ci_lint": 60, "ci_tests": 150, "test_lint_skill": 120, "test_visual_report": 210,
        "lint_skill": 75, "other_skills": 30, "visual_report": 120, "html_report": 60, "visual_language": 120, "check_render": 180}
LR_GAP = 26
TB_SLOT = {"ci_tests": 0, "ci_lint": 1, "check_sh": 2, "test_visual_report": 0, "test_lint_skill": 1, "lint_skill": 1.5,
           "visual_report": 1, "other_skills": 2, "check_render": 0, "html_report": 1, "visual_language": 2}
TB_GX, TB_GY = 16, 44

def _node(i, x, y, uid):
    name, tag, cap = NODES[i]
    focus, group = i == "visual_report", i == "other_skills"
    fill, fg = TAGS["FOCUS" if focus else tag]
    tw = len(tag) * 6.4 + 9
    stroke = ' stroke="#4a5755"' if tag == "REF" else ""
    cls = "dn" + (" focus" if focus else "") + (" group" if group else "")
    s = [f'<g class="{cls}" transform="translate({x - W/2:.1f},{y - H/2:.1f})">',
         f'<rect class="box" width="{W}" height="{H}" rx="5"/>',
         f'<rect class="tag" x="10" y="8" width="{tw:.1f}" height="14" rx="2.5" fill="{fill}"{stroke}/>',
         f'<text class="tg" x="{10 + tw/2:.1f}" y="18.6" text-anchor="middle" fill="{fg}">{tag}</text>',
         f'<text class="nm" x="{10 + tw + 6:.1f}" y="19.5">{esc(name)}</text>',
         f'<text class="cp" x="10" y="37">{esc(cap)}</text>']
    if group:
        s.append(f'<rect class="cnt" x="{W - 32}" y="{H/2 - 10}" width="24" height="20" rx="3"/>'
                 f'<text class="cn" x="{W - 20}" y="{H/2 + 4.2}" text-anchor="middle">17</text>')
    s.append(f"<title>{esc(i)}</title></g>")
    return "".join(s)

def _svg(mode):
    pos = {}
    if mode == "lr":
        for i, r in RANK.items(): pos[i] = (W/2 + r * (W + LR_GAP), LR_Y[i])
    else:
        for i, r in RANK.items(): pos[i] = (W/2 + TB_SLOT[i] * (W + TB_GX), H/2 + r * (H + TB_GY))
    xs = [p[0] for p in pos.values()]; ys = [p[1] for p in pos.values()]
    pad = 6
    minx, maxx = min(xs) - W/2 - pad, max(xs) + W/2 + pad + 4
    miny, maxy = min(ys) - H/2 - pad, max(ys) + H/2 + pad
    vw, vh = maxx - minx, maxy - miny
    mid = f"arr-{mode}"
    paths = []
    for a, b in EDGES:
        (ax, ay), (bx, by) = pos[a], pos[b]
        if mode == "lr":
            x0, x1 = ax + W/2, bx - W/2 - 2
            if RANK[b] - RANK[a] > 1:  # long edge: run along its own lane, then curve in
                lx0, lx1 = x0 + LR_GAP, x1 - LR_GAP
                d = (f"M{x0},{ay} L{lx1:.1f},{ay} C{lx1 + LR_GAP/2:.1f},{ay} {lx1 + LR_GAP/2:.1f},{by} {x1},{by}")
            else:
                dx = (x1 - x0) / 2
                d = f"M{x0},{ay} C{x0 + dx:.1f},{ay} {x1 - dx:.1f},{by} {x1},{by}"
        else:
            y0, y1 = ay + H/2, by - H/2 - 2
            if RANK[b] - RANK[a] > 1:
                ly1 = y1 - TB_GY
                d = f"M{ax},{y0} L{ax},{ly1:.1f} C{ax},{ly1 + TB_GY/2:.1f} {bx},{ly1 + TB_GY/2:.1f} {bx},{y1}"
            else:
                dy = (y1 - y0) / 2
                d = f"M{ax},{y0} C{ax},{y0 + dy:.1f} {bx},{y1 - dy:.1f} {bx},{y1}"
        paths.append(f'<path d="{d}" marker-end="url(#{mid})"/>')
    nodes = "".join(_node(i, *pos[i], mode) for i in NODES)
    return (f'<svg class="dag dag-{mode}" viewBox="{minx:.1f} {miny:.1f} {vw:.1f} {vh:.1f}" width="{vw:.0f}" '
            f'style="max-width:{vw:.0f}px" role="img" aria-label="Dependency graph: two-hop neighbourhood of visual-report, 11 nodes">'
            f'<defs><marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0,1 L9,5 L0,9 z" fill="#7b8786"/></marker></defs>'
            f'<g class="edges">{"".join(paths)}</g><g class="nodes">{nodes}</g></svg>')

DAG_SVG = _svg("lr") + "\n" + _svg("tb")
DAG_DRAWN = len(NODES)
assert DAG_DRAWN == 11
LEGEND = "".join(f'<span class="k"><span class="tgk" style="background:{TAGS[t][0]};color:{TAGS[t][1]}{";box-shadow:inset 0 0 0 1px #4a5755" if t == "REF" else ""}">{t}</span>{n}</span>' for t, n in TAG_NAMES) \
  + f'<span class="k"><span class="tgk" style="background:{TAGS["FOCUS"][0]};color:{TAGS["FOCUS"][1]}">SKL</span>subject</span>' \
  + '<span class="k"><span class="grpk"></span>merged group, count at right</span>'
