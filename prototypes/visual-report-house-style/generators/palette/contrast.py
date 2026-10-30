"""Palette tokens, WCAG contrast check, and palette-test.html generator.

One source of truth: PALETTES below. The script checks every fg/bg pair the page
uses, prints a table (also written to contrast.txt), and writes the page with
CSS variables generated from the same tokens, so page and check cannot drift.

Usage: python contrast.py   (exits 1 if any pair fails)
"""
import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent / "proto" / "palette-test.html"
B_PAPER = "#fbfbf9"  # variant B's page background, the reference paper tone

# fmt: off
# supplied: the user's hexes verbatim. derived: (hex, source, role) for every colour not supplied.
PALETTES = [
  dict(key="p1", name="Navy & coral", sub="User palette 1",
       supplied=["#102542", "#f87060", "#cdd7d6", "#b3a394", "#ffffff"],
       paper_note="Paper is the supplied #ffffff (B's #fbfbf9 not needed); answer box on a #cdd7d6 tint",
       derived=[("#c2493a", "#f87060", "coral text (accent labels)"), ("#d95646", "#f87060", "coral line/series (3:1)"),
                ("#5f5348", "#b3a394", "muted text"), ("#8a7766", "#b3a394", "taupe series"),
                ("#24514e", "#cdd7d6", "code text"), ("#4f7f7c", "#cdd7d6", "sage series"),
                ("#a3123a", "new", "problem crimson"), ("#b7791f", "new", "note amber")],
       notes=["Coral vs problem red: coral stays a warm fill (#f87060 with navy text); problems move to a blue-leaning crimson #a3123a and always carry a cross icon and the word Problem.",
              "Code family: the supplied sage #cdd7d6 as the pill, deep sage #24514e text."],
       t=dict(
    paper="#ffffff", surface="#f4f7f7", ink="#102542", muted="#5f5348", line="#e1e7e7", rule="#7b8786",
    struct="#102542", on_struct="#ffffff",
    accent="#c2493a", accent_fill="#f87060", on_accent="#102542", accent_line="#d95646", accent_soft="#feebe7", bar="#edf1f1",
    th_bg="#edf1f1",
    code_fg="#24514e", code_pill="#cdd7d6", code_bg="#eef3f3", code_line="#cdd7d6",
    tk_text="#102542", tk_kw="#24514e", tk_str="#6b5a48", tk_num="#3d5a8a", tk_com="#55625f", tk_fn="#7a3e5c", tk_gut="#55625f",
    red="#a3123a", red_soft="#fbe7ec", red_text="#8c0f32",
    amber="#b7791f", amber_soft="#fcf2dd", amber_text="#714800",
    group_soft="#edf1f1",
    c1="#102542", c2="#d95646", c3="#4f7f7c", c4="#8a7766",
  )),
  dict(key="p2", name="Green-blue ramp", sub="User palette 2 (sequential ramp)",
       supplied=["#d9ed92", "#b5e48c", "#99d98c", "#76c893", "#52b69a", "#34a0a4", "#168aad", "#1a759f", "#1e6091", "#184e77"],
       seq=["#d9ed92", "#b5e48c", "#99d98c", "#76c893", "#52b69a", "#34a0a4", "#168aad", "#1a759f", "#1e6091", "#184e77"],
       paper_note="Paper is B's #fbfbf9 unchanged; pale ramp steps used only as tints",
       derived=[("#102a3f", "#184e77", "ink"), ("#3f5566", "#184e77", "muted text"),
                ("#2f5f2a", "#99d98c", "code text"), ("#eaf6d6", "#d9ed92", "code pill"),
                ("#3f8f4f", "#76c893", "green series"), ("#6b8a1f", "#b5e48c", "olive series"),
                ("#b0241c", "new", "problem red"), ("#b7791f", "new", "note amber")],
       notes=["Only #34a0a4 to #184e77 pass 3:1 on paper, and they are all blue-teal. Two series are darkened from the green end so the four categories are distinct.",
              "Code family: the green end of the ramp (#2f5f2a on #eaf6d6), apart from the blue accent."],
       t=dict(
    paper="#fbfbf9", surface="#ffffff", ink="#102a3f", muted="#3f5566", line="#dfe7e9", rule="#6c8590",
    struct="#184e77", on_struct="#ffffff",
    accent="#1a759f", accent_fill="#1a759f", on_accent="#ffffff", accent_line="#168aad", accent_soft="#e2f1f5", bar="#e9f1ec",
    th_bg="#ecf2f4",
    code_fg="#2f5f2a", code_pill="#eaf6d6", code_bg="#f3f9e8", code_line="#d9ed92",
    tk_text="#1f2d22", tk_kw="#2f5f2a", tk_str="#6b4a10", tk_num="#1e6091", tk_com="#55625a", tk_fn="#165a66", tk_gut="#55625a",
    red="#b0241c", red_soft="#fbeae7", red_text="#94201a",
    amber="#b7791f", amber_soft="#fcf2dd", amber_text="#714800",
    group_soft="#e8f5ec",
    c1="#184e77", c2="#168aad", c3="#3f8f4f", c4="#6b8a1f",
  )),
  dict(key="p3", name="Sky & amber", sub="User palette 3",
       supplied=["#8ecae6", "#219ebc", "#023047", "#ffb703", "#fb8500"],
       paper_note="Paper is B's #fbfbf9 unchanged",
       derived=[("#17758e", "#219ebc", "accent text and cell fill"), ("#3f5866", "#023047", "muted text"),
                ("#126782", "#219ebc", "deep sky series"), ("#6b7f86", "#023047", "slate series"),
                ("#c46a00", "#fb8500", "note border (3:1)"), ("#fff1cc", "#ffb703", "note fill"), ("#7a4300", "#fb8500", "note text"),
                ("#5a3a78", "new", "code text"), ("#b0241c", "new", "problem red")],
       notes=["#ffb703 and #fb8500 are the amber role, so they appear only in note callouts: never as a series or accent. The accent is sky blue. Trade-off: the palette's warm colours are rarely visible, and the four series are blues plus a slate.",
              "#219ebc with navy text is 4.41:1, so the highlighted cell uses #17758e with white text.",
              "Code family: plum #5a3a78 (not supplied); the palette has no non-blue hue left that is not amber."],
       t=dict(
    paper="#fbfbf9", surface="#ffffff", ink="#023047", muted="#3f5866", line="#dfe9ee", rule="#6d8794",
    struct="#023047", on_struct="#ffffff",
    accent="#17758e", accent_fill="#17758e", on_accent="#ffffff", accent_line="#219ebc", accent_soft="#e3f2f9", bar="#e7f3f9",
    th_bg="#e9f3f8",
    code_fg="#5a3a78", code_pill="#efe8f4", code_bg="#f6f2f8", code_line="#ddd0e6",
    tk_text="#231a30", tk_kw="#5a3a78", tk_str="#2f6b3a", tk_num="#1e5a8a", tk_com="#615a6b", tk_fn="#7a2f5a", tk_gut="#615a6b",
    red="#b0241c", red_soft="#fbeae7", red_text="#94201a",
    amber="#c46a00", amber_soft="#fff1cc", amber_text="#7a4300",
    group_soft="#e3f2f9",
    c1="#023047", c2="#219ebc", c3="#6b7f86", c4="#126782",
  )),
  dict(key="p4", name="Relentless Data", sub="Brand palette (primary candidate)",
       supplied=["#1D3B57", "#101418", "#EFEDE8", "#B4552D", "#A34D29", "#7FA6C9", "#FFFFFF", "#6B675C", "#55524A", "#6F6B60", "#DFDCD4",
                 "#15619D", "#00958F", "#A0832A"],
       seq=["#CFE0F2", "#9ABBDD", "#5F91C1", "#2F6799", "#1D3B57"],
       paper_note="Paper is the brand #EFEDE8 (darker than B's #fbfbf9); white #FFFFFF for the answer box and DAG nodes. Brand tokens used as given",
       derived=[("#e6e3dc", "#DFDCD4", "table header fill"), ("#f6e7de", "#B4552D", "focus fill"),
                ("#dde8f3", "#CFE0F2", "code pill"), ("#00756f", "#00958F", "code string"), ("#7a6320", "#A0832A", "code number"),
                ("#7d786d", "#6B675C", "DAG border/edge (3:1)"),
                ("#a8182f", "new", "problem crimson"), ("#b7791f", "new", "note amber")],
       notes=["Signal #B4552D vs problem red: problems use crimson #a8182f with a cross icon. Signal is 4.20:1 on paper, so it is fills and lines only; accent text is signal-text #A34D29 (4.92).",
              "Brand muted #6B675C (4.83) and label #6F6B60 (4.55) pass on paper. Label fails on hair #DFDCD4 (3.88), so labels never sit on hair.",
              "Ochre series #A0832A is close to the amber note colour: flagged, kept because it is a brand value.",
              "#5F91C1 (sequential/ordinal step 3) is 2.85:1 on paper: fills next to other steps only, not a standalone line. Pale #7FA6C9 (2.19) is fill-only.",
              "Code family: the brand blue (#15619D on #dde8f3), apart from the burnt-orange signal."],
       t=dict(
    paper="#EFEDE8", surface="#FFFFFF", ink="#101418", muted="#6B675C", label="#6F6B60", secondary="#55524A", line="#DFDCD4", rule="#7d786d",
    struct="#1D3B57", on_struct="#FFFFFF",
    accent="#A34D29", accent_fill="#B4552D", on_accent="#FFFFFF", accent_line="#B4552D", accent_soft="#f6e7de", bar="#e3e0d8",
    th_bg="#e6e3dc",
    code_fg="#15619D", code_pill="#dde8f3", code_bg="#f5f8fb", code_line="#CFE0F2",
    tk_text="#101418", tk_kw="#15619D", tk_str="#00756f", tk_num="#7a6320", tk_com="#5d6470", tk_fn="#2F6799", tk_gut="#5d6470",
    red="#a8182f", red_soft="#f9e4e7", red_text="#8f1428",
    amber="#b7791f", amber_soft="#fbf0d5", amber_text="#6e4a00",
    group_soft="#e3eaf2",
    c1="#15619D", c2="#B4552D", c3="#00958F", c4="#A0832A",
  )),
]

# (label, fg token, bg token, kind)  kind: text (4.5), large (3.0), graphic (3.0)
PAIRS = [
  ("body text",              "ink",        "paper",       "text"),
  ("muted text",             "muted",      "paper",       "text"),
  ("caption how-to-read",    "muted",      "paper",       "text"),
  ("so-what text",           "ink",        "paper",       "text"),
  ("so-what / labels",       "accent",     "paper",       "text"),
  ("answer text",            "ink",        "surface",     "text"),
  ("answer label",           "accent",     "surface",     "text"),
  ("answer border",          "struct",     "paper",       "graphic"),
  ("badge text",             "on_struct",  "struct",      "text"),
  ("table header text",      "ink",        "th_bg",       "text"),
  ("table cell bar text",    "ink",        "bar",         "text"),
  ("highlight cell numeral", "on_accent",  "accent_fill", "text"),
  ("brand label",            "label",      "paper",       "text"),
  ("brand label on panel",   "label",      "surface",     "text"),
  ("brand secondary",        "secondary",  "paper",       "text"),
  ("chart axis labels",      "muted",      "paper",       "text"),
  ("inline code",            "code_fg",    "code_pill",   "text"),
  ("code: text",             "tk_text",    "code_bg",     "text"),
  ("code: keyword",          "tk_kw",      "code_bg",     "text"),
  ("code: string",           "tk_str",     "code_bg",     "text"),
  ("code: number",           "tk_num",     "code_bg",     "text"),
  ("code: comment",          "tk_com",     "code_bg",     "text"),
  ("code: function",         "tk_fn",      "code_bg",     "text"),
  ("code: gutter",           "tk_gut",     "code_bg",     "text"),
  ("problem text",           "red",        "paper",       "text"),
  ("problem callout text",   "red_text",   "red_soft",    "text"),
  ("note callout text",      "amber_text", "amber_soft",  "text"),
  ("DAG node text",          "ink",        "surface",     "text"),
  ("DAG focus text",         "ink",        "accent_soft", "text"),
  ("DAG group text",         "ink",        "group_soft",  "text"),
  ("DAG problem text",       "red_text",   "red_soft",    "text"),
  ("DAG node border",        "rule",       "paper",       "graphic"),
  ("DAG focus border",       "accent_line","paper",       "graphic"),
  ("cell bar edge",          "accent_line","paper",       "graphic"),
  ("DAG group border",       "struct",     "paper",       "graphic"),
  ("DAG problem border",     "red",        "paper",       "graphic"),
  ("DAG edge",               "rule",       "paper",       "graphic"),
  ("note callout border",    "amber",      "paper",       "graphic"),
  ("chart series 1",         "c1",         "paper",       "graphic"),
  ("chart series 2",         "c2",         "paper",       "graphic"),
  ("chart series 3",         "c3",         "paper",       "graphic"),
  ("chart series 4",         "c4",         "paper",       "graphic"),
  ("chart series 5",         "c5",         "paper",       "graphic"),
  ("so-what on panel",       "ink",        "surface",     "text"),
]
# fmt: on
MIN = {"text": 4.5, "large": 3.0, "graphic": 3.0}


def lum(hexc):
    h = hexc.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = out
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check(p):
    t = p["t"]
    return [(lab, fg, bg, k, t[fg], t[bg], ratio(t[fg], t[bg])) for lab, fg, bg, k in PAIRS if fg in t and bg in t]


def report():
    lines, ok = [], True
    for p in PALETTES:
        rows = check(p)
        lines.append(f"\n== {p['name']} ({p['key']}) ==  paper {p['t']['paper']}  [{p['paper_note']}]")
        lines.append(f"{'pair':26} {'fg':8} {'bg':8} {'kind':8} {'ratio':>6}  min  result")
        for lab, _, _, k, f, b, r in rows:
            res = "PASS" if r >= MIN[k] else "FAIL"
            ok &= res == "PASS"
            lines.append(f"{lab:26} {f:8} {b:8} {k:8} {r:6.2f}  {MIN[k]:<4} {res}")
        lo = min(rows, key=lambda x: x[6] / MIN[x[3]])
        lines.append(f"lowest (vs its minimum): {lo[0]} {lo[6]:.2f}:1 (min {MIN[lo[3]]})")
    lines.append("\nALL PASS" if ok else "\nSOME FAIL")
    return "\n".join(lines), ok


# ---------------------------------------------------------------- page

def css_vars(p):
    return "\n".join(f"  --{k.replace('_', '-')}: {v};" for k, v in p["t"].items())


CHART = [("Mar", 4, 2, 3, 1), ("Apr", 6, 3, 2, 2), ("May", 5, 4, 4, 3)]


def chart_svg():
    # grouped bars, 3 months x 5 series, inline SVG
    w, h, base = 300, 130, 108
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Commits per month by series" class="chart">']
    for gy in (0, 2, 4, 6):
        y = base - gy * 14
        out.append(f'<line x1="26" x2="{w-4}" y1="{y}" y2="{y}" class="grid"/>')
        out.append(f'<text x="20" y="{y+3.5}" class="ax" text-anchor="end">{gy}</text>')
    for gi, (m, *vals) in enumerate(CHART):
        x0 = 40 + gi * 88
        for si, v in enumerate(vals):
            x = x0 + si * 16
            out.append(f'<rect x="{x}" y="{base - v*14}" width="13" height="{v*14}" fill="var(--c{si+1})"/>')
        out.append(f'<text x="{x0+30}" y="{base+15}" class="ax" text-anchor="middle">{m}</text>')
    out.append(f'<line x1="26" x2="{w-4}" y1="{base}" y2="{base}" class="axis"/>')
    out.append("</svg>")
    return "".join(out)


def dag_svg():
    # 4 nodes: default -> focus <- group ; focus -> problem
    return """<svg viewBox="0 0 300 150" class="dag" role="img" aria-label="DAG node set">
  <defs><marker id="ARW" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" class="arrow"/></marker></defs>
  <path d="M96,32 C122,32 122,62 146,66" class="edge" marker-end="url(#ARW)"/>
  <path d="M96,118 C122,118 122,88 146,84" class="edge" marker-end="url(#ARW)"/>
  <path d="M226,82 C232,90 232,118 240,118" class="edge" marker-end="url(#ARW)"/>
  <g class="n-default"><rect x="6" y="16" width="90" height="32" rx="5"/><text x="51" y="36">lint_skill.py</text></g>
  <g class="n-group"><rect x="6" y="100" width="90" height="36" rx="5"/><text x="51" y="116">tests/ (6)</text><text x="51" y="129" class="sub">merged group</text></g>
  <g class="n-focus"><rect x="148" y="56" width="78" height="38" rx="5"/><text x="187" y="79">SKILL.md</text></g>
  <g class="n-problem"><rect x="242" y="102" width="54" height="32" rx="5"/><text x="269" y="122">✕ CI</text></g>
</svg>"""


def code_panel():
    L = [
        '<span class="com"># verdict from the collected checks</span>',
        '<span class="kw">def</span> <span class="fn">verdict</span>(fails, blocked):',
        '    <span class="kw">if</span> fails:',
        '        <span class="kw">return</span> <span class="str">"FAIL"</span>, <span class="num">1</span>',
        '    <span class="kw">if</span> blocked:',
        '        <span class="kw">return</span> <span class="str">"BLOCKED"</span>, <span class="num">2</span>',
        '    <span class="kw">return</span> <span class="str">"PASS"</span>, <span class="num">0</span>',
    ]
    return '<pre class="code">' + "".join(f'<span class="l">{x}</span>' for x in L) + "</pre>"


def column(p):
    t = p["t"]
    rows = check(p)
    lo = min(rows, key=lambda x: x[6] / MIN[x[3]])
    keyhex = [("paper", "paper"), ("ink", "ink"), ("muted", "muted"), ("structure", "struct"),
              ("accent text", "accent"), ("accent fill", "accent_fill"), ("code", "code_fg"), ("code pill", "code_pill"), ("code bg", "code_bg"), ("red", "red"), ("amber", "amber")]
    chips = "".join(
        f'<li><span class="sw" style="background:var(--{tok.replace("_", "-")})"></span>{lab}<code class="hx">{t[tok]}</code></li>'
        for lab, tok in keyhex)
    cats = "".join(f'<span class="cat" style="background:var(--c{i})" title="{t["c"+str(i)]}"></span>' for i in range(1, 6) if f"c{i}" in t)
    sup = "".join(f'<span title="{c}" style="background:{c}"></span>' for c in p["supplied"])
    seq = ""
    if p.get("seq"):
        seq = '<div class="seq" title="sequential ramp">' + "".join(f'<span style="background:{c}"></span>' for c in p["seq"]) + '</div>'
    der = "".join(f'<li><span class="sw" style="background:{h}"></span><code class="hx">{h}</code> from {"new" if src == "new" else f"<code class=hx>{src}</code>"}, {html.escape(role)}</li>' for h, src, role in p["derived"])
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in p["notes"])
    ctab = "".join(
        f'<li><span>{html.escape(lab)}</span><b class="{"ok" if r >= MIN[k] else "bad"}">{r:.1f}{"" if r >= MIN[k] else " FAIL"}</b></li>'
        for lab, _, _, k, _, _, r in rows)
    return f"""
<article class="pal {p['key']}" aria-label="{p['name']}">
  <header class="pal-head">
    <h2>{p['name']}</h2>
    <p class="pal-sub">{p['sub']}</p>
    <div class="supplied" aria-label="supplied colours">{sup}</div>
    <ul class="chips">{chips}</ul>
    <details class="derived"><summary>Derived colours ({len(p["derived"])})</summary><ul>{der}</ul></details>
    <p class="pal-note">{p['paper_note']}.</p>
  </header>

  <section class="answer">
    <p class="label">Answer</p>
    <p class="claim">Every SKILL.md fits the 150-line budget that <code>lint_skill.py</code> enforces, and five of 18 sit exactly on it.</p>
  </section>

  <h3 class="sec-head"><span class="badge">2</span><span>The 150-line budget</span><span class="count">Table 1</span></h3>

  <p class="prose">The linter reads <code>LINE_BUDGET</code> from <code>scripts/lint_skill.py</code> and fails CI on any file over it.</p>

  <table class="data">
    <thead><tr><th class="txt">Skill</th><th class="num">SKILL.md lines</th><th class="num">Scripts</th></tr></thead>
    <tbody>
      <tr><td class="id">dbt-runner</td><td class="lines at"><span class="cbar" style="--w:100%">150</span></td><td class="num">4</td></tr>
      <tr><td class="id">ship</td><td class="lines"><span class="cbar" style="--w:61%">92</span></td><td class="num">0</td></tr>
    </tbody>
  </table>
  <p class="caption"><span class="figno">Table 1.</span> SKILL.md size per skill against the budget. <span class="how">Bars are scaled to 150 lines; a filled bar sits exactly on the budget.</span></p>
  <p class="sowhat"><span class="sw-label">So what.</span> The budget caps the prompt, not the skill: scripts carry the weight.</p>

  <pre class="code-wrap">{code_panel()}</pre>

  <div class="figpair">
    <div class="fig-dag">{dag_svg()}
      <ul class="legend"><li><i class="k-default"></i>node</li><li><i class="k-focus"></i>focus</li><li><i class="k-group"></i>merged group</li><li><i class="k-problem"></i>problem</li></ul>
    </div>
  </div>
  <p class="caption"><span class="figno">Figure 3.</span> What depends on SKILL.md. <span class="how">The focus node is filled; the dashed box merges six test files; red marks the broken edge.</span></p>

  <div class="fig-chart">
    <div class="cats">{cats}</div>{seq}
    {chart_svg()}
  </div>
  <p class="caption"><span class="figno">Figure 2.</span> Commits per month, four series. <span class="how">Red and amber never appear as a series.</span></p>

  <div class="callout problem"><p><b>✕ Problem.</b> <code>check_render.py</code> exits 1: the DAG is wider than its container.</p></div>
  <div class="callout note"><p><b>Note.</b> Exactly one commit followed <code>088a29f</code>; the source said three.</p></div>

  <ul class="notes">{notes}</ul>

  <details class="ratios" open>
    <summary>WCAG contrast, {"all pass" if all(r >= MIN[k] for _, _, _, k, _, _, r in rows) else "FAILURES"} (lowest: {html.escape(lo[0])} {lo[6]:.1f}:1)</summary>
    <ul class="rlist">{ctab}</ul>
  </details>
</article>"""


STYLE = """
:root { --display: "Helvetica Neue", Helvetica, Arial, system-ui, sans-serif;
  --body: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --shell: #ebe7df; --shell-ink: #23201d; --shell-muted: #4e4943; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--shell); color: var(--shell-ink); font: 15px/1.5 var(--body); -webkit-font-smoothing: antialiased; }
.top { max-width: 1680px; margin: 0 auto; padding: 28px 16px 8px; }
.top h1 { font-family: var(--display); font-size: 1.95rem; letter-spacing: -0.02em; margin: 0 0 6px; line-height: 1.1; }
.top p { margin: 0 0 6px; max-width: 92ch; color: var(--shell-muted); }
.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; max-width: 1680px; margin: 0 auto; padding: 16px 16px 48px; align-items: start; }
@media (max-width: 1360px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 720px) { .grid { grid-template-columns: minmax(0, 1fr); } }

.pal { background: var(--paper); color: var(--ink); font-family: var(--body); padding: 20px 18px 16px; border: 1px solid var(--line); border-radius: 6px; min-width: 0; }
.pal code { font-family: var(--mono); font-size: 0.86em; background: var(--code-pill); color: var(--code-fg); padding: 0.08em 0.38em; border-radius: 4px; font-weight: 500; }
.pal-head h2 { font-family: var(--display); font-size: 1.45rem; letter-spacing: -0.02em; margin: 0; line-height: 1.15; }
.pal-sub { margin: 2px 0 10px; color: var(--muted); font-size: 0.86rem; }
.chips { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; font-size: 0.78rem; }
.chips li { display: flex; align-items: center; gap: 6px; min-width: 0; }
.chips .sw { width: 14px; height: 14px; border-radius: 3px; border: 1px solid var(--rule); flex: none; }
.chips .hx { margin-left: auto; background: none !important; color: var(--muted) !important; padding: 0 !important; }
.supplied { display: flex; height: 18px; border-radius: 4px; overflow: hidden; border: 1px solid var(--line); margin: 0 0 10px; }
.supplied span, .seq span { flex: 1; }
.seq { display: flex; height: 10px; border-radius: 3px; overflow: hidden; margin: 0 0 8px; }
.derived { font-size: 0.76rem; margin: 8px 0 0; color: var(--ink); }
.derived summary { cursor: pointer; font-weight: 600; }
.derived ul { list-style: none; padding: 0; margin: 4px 0 0; }
.derived li { display: flex; align-items: center; gap: 5px; padding: 1px 0; flex-wrap: wrap; }
.derived .sw { width: 12px; height: 12px; border-radius: 3px; border: 1px solid var(--rule); flex: none; }
.derived .hx, .notes .hx { background: none !important; color: var(--ink) !important; padding: 0 !important; }
.notes { margin: 14px 0 0; padding: 10px 0 0 16px; border-top: 1px solid var(--line); font-size: 0.8rem; line-height: 1.45; color: var(--ink); }
.notes li { margin: 0 0 5px; }
.pal-note { font-size: 0.78rem; color: var(--muted); margin: 8px 0 16px; padding-bottom: 14px; border-bottom: 1px solid var(--line); }

.answer { background: var(--surface); border: 1px solid var(--struct); border-radius: 6px; padding: 14px 16px; margin: 0 0 20px; }
.answer .label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.14em; font-weight: 700; color: var(--accent); margin: 0 0 6px; }
.answer .claim { font-family: var(--display); font-size: 1.12rem; line-height: 1.3; font-weight: 600; letter-spacing: -0.01em; margin: 0; }

.sec-head { display: flex; align-items: center; gap: 10px; font-family: var(--display); font-size: 1.05rem; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 10px; padding: 0 0 8px; border-bottom: 1px solid var(--line); }
.sec-head .badge { width: 26px; height: 26px; border-radius: 50%; background: var(--struct); color: var(--on-struct); display: inline-grid; place-items: center; font-size: 0.82rem; font-variant-numeric: tabular-nums; flex: none; }
.sec-head .count { margin-left: auto; font-family: var(--body); font-size: 0.72rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }
.prose { margin: 0 0 12px; font-size: 0.95rem; }

table.data { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
table.data th { background: var(--th-bg); color: var(--ink); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; text-align: left; padding: 6px 8px; border-bottom: 1.5px solid var(--struct); }
table.data td { padding: 4px 8px; border-bottom: 1px solid var(--line); }
table.data .num { text-align: right; font-variant-numeric: tabular-nums; }
table.data td.id { font-family: var(--mono); font-size: 0.82rem; }
table.data td.lines { padding: 3px 8px; font-variant-numeric: tabular-nums; }
.cbar { position: relative; display: block; padding: 2px 6px; border-radius: 3px; z-index: 0; text-align: right; }
.cbar::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: var(--w); background: var(--bar); border-radius: 3px; z-index: -1; }
td.at .cbar { color: var(--on-accent); font-weight: 700; }
td.at .cbar::before { background: var(--accent-fill); box-shadow: inset 0 0 0 1px var(--accent-line); }

.caption { font-size: 0.84rem; line-height: 1.45; margin: 8px 0 0; color: var(--ink); }
.caption .figno { font-weight: 700; }
.caption .how { color: var(--muted); }
.sowhat { font-size: 0.92rem; line-height: 1.4; margin: 6px 0 18px; color: var(--ink); font-weight: 500; }
.sowhat .sw-label { color: var(--accent); font-weight: 700; }

pre.code-wrap { margin: 0 0 18px; padding: 0; background: none; }
pre.code { margin: 0; padding: 8px 0; background: var(--code-bg); border: 1px solid var(--code-line); border-radius: 6px; font: 0.76rem/1.6 var(--mono); color: var(--tk-text); counter-reset: ln 353; overflow-x: auto; }
pre.code .l { display: block; white-space: pre; padding: 0 10px 0 40px; position: relative; }
pre.code .l::before { counter-increment: ln; content: counter(ln); position: absolute; left: 0; width: 28px; text-align: right; color: var(--tk-gut); font-variant-numeric: tabular-nums; }
pre.code .kw { color: var(--tk-kw); font-weight: 700; } pre.code .fn { color: var(--tk-fn); }
pre.code .str { color: var(--tk-str); } pre.code .num { color: var(--tk-num); } pre.code .com { color: var(--tk-com); font-style: italic; }

.fig-dag, .fig-chart { border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 10px 0 8px; }
svg.dag, svg.chart { display: block; width: 100%; height: auto; }
.dag text { font: 600 11px var(--mono); text-anchor: middle; fill: var(--ink); }
.dag text.sub { font: 500 9.5px var(--body); fill: var(--ink); }
.dag .edge { fill: none; stroke: var(--rule); stroke-width: 1.4; } .dag .arrow { fill: var(--rule); }
.n-default rect { fill: var(--surface); stroke: var(--rule); stroke-width: 1.2; }
.n-focus rect { fill: var(--accent-soft); stroke: var(--accent-line); stroke-width: 2.4; }
.n-group rect { fill: var(--group-soft); stroke: var(--struct); stroke-width: 1.3; stroke-dasharray: 4 3; }
.n-problem rect { fill: var(--red-soft); stroke: var(--red); stroke-width: 2; }
.n-problem text { fill: var(--red-text); }
.legend { list-style: none; display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 6px 0 0; padding: 0; font-size: 0.76rem; color: var(--ink); }
.legend i { display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 5px; vertical-align: -2px; }
.k-default { background: var(--surface); border: 1.2px solid var(--rule); }
.k-focus { background: var(--accent-soft); border: 2px solid var(--accent-line); }
.k-group { background: var(--group-soft); border: 1.3px dashed var(--struct); }
.k-problem { background: var(--red-soft); border: 2px solid var(--red); }
.fig-chart { margin-top: 18px; }
.cats { display: flex; gap: 6px; margin: 0 0 6px; }
.cat { width: 28px; height: 14px; border-radius: 3px; }
.chart .grid { stroke: var(--line); stroke-width: 1; } .chart .axis { stroke: var(--ink); stroke-width: 1; }
.chart .ax { font: 10px var(--body); fill: var(--muted); }
.fig-chart + .caption { margin-bottom: 18px; }

.callout { border-radius: 6px; padding: 9px 12px; margin: 0 0 10px; font-size: 0.86rem; line-height: 1.45; border: 1px solid; }
.callout p { margin: 0; }
.callout.problem { background: var(--red-soft); color: var(--red-text); border-color: var(--red); }
.callout.note { background: var(--amber-soft); color: var(--amber-text); border-color: var(--amber); }
.callout code { background: rgba(255,255,255,0.7); color: inherit; }

.ratios { margin-top: 16px; border-top: 1px solid var(--line); padding-top: 8px; font-size: 0.74rem; }
.ratios summary { cursor: pointer; font-weight: 700; color: var(--ink); padding: 2px 0 6px; }
.rlist { list-style: none; margin: 0; padding: 0; columns: 2; column-gap: 14px; }
.rlist li { display: flex; justify-content: space-between; gap: 6px; padding: 1px 0; border-bottom: 1px solid var(--line); break-inside: avoid; color: var(--ink); }
.rlist b { font-weight: 600; font-variant-numeric: tabular-nums; color: var(--ink); } .rlist b.bad { color: var(--red); }
"""


def page():
    vars_css = "\n".join(f".{p['key']} {{\n{css_vars(p)}\n}}" for p in PALETTES)
    cols = "".join(column(p) for p in PALETTES)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Palette test</title>
<!-- Generated by palette/contrast.py from the same tokens the contrast check uses. Do not hand-edit. -->
<style>
{vars_css}
{STYLE}
</style>
</head>
<body>
<header class="top">
  <h1>User palettes for the visual-report house style, round 2</h1>
  <p>Each column renders the same sample in one palette: answer box, section header, table with a highlighted cell, inline code, code panel, DAG nodes, chart series and the two semantic callouts. Fonts follow variant B. The strip under each name is the supplied palette verbatim; colours that fail as text are used only as fills or lines, and their darker same-hue text variants are listed under "Derived colours". Paper is B's <code style="font-family:var(--mono)">{B_PAPER}</code>, the supplied white, or the brand paper. Every text pair passes WCAG AA (4.5:1) and every graphic pair 3:1; the ratio table sits under each column.</p>
</header>
<main class="grid">{cols}
</main>
</body>
</html>
"""


if __name__ == "__main__":
    txt, ok = report()
    print(txt)
    (HERE / "contrast.txt").write_text(txt + "\n")
    PAGE.write_text(page())
    print(f"wrote {PAGE}")
    sys.exit(0 if ok else 1)
