import sys, html
sys.path.insert(0, sys.path[0])
from data import SKILLS, NODES, EDGES, COMMITS, SHARES

def n(v): return f"{v:,}"

# Table 1
rows = []
for s, ver, lines, refs, scr, dmi, com, tl, tf in SKILLS:
    rows.append(
        f'<tr><td class="id">{s}</td><td class="id num">{ver}</td><td class="num">{n(lines)}</td>'
        f'<td class="num">{refs}</td><td class="num">{scr}</td><td>{"yes" if dmi else "no"}</td>'
        f'<td class="num">{com}</td><td class="num">{tf}</td><td class="num">{n(tl)}</td></tr>')
t1 = "\n".join(rows)
tot = (sum(x[2] for x in SKILLS), sum(x[3] for x in SKILLS), sum(x[4] for x in SKILLS),
       sum(1 for x in SKILLS if x[5]), sum(x[6] for x in SKILLS), sum(x[8] for x in SKILLS), sum(x[7] for x in SKILLS))
t1_foot = (f'<tr><td>Total</td><td></td><td class="num">{n(tot[0])}</td><td class="num">{tot[1]}</td>'
           f'<td class="num">{tot[2]}</td><td>{tot[3]} yes</td><td class="num">{tot[4]}</td>'
           f'<td class="num">{tot[5]}</td><td class="num">{n(tot[6])}</td></tr>')

# Table 2
rows = []
for i, (nid, label, group, deg) in enumerate(NODES):
    extra = ' class="extra"' if i >= 20 else ''
    rows.append(f'<tr{extra}><td class="id">{html.escape(nid)}</td><td class="id">{html.escape(label)}</td>'
                f'<td>{group}</td><td class="num">{deg}</td></tr>')
t2 = "\n".join(rows)

# Mermaid DAG
mid = lambda s: s.replace("-", "_")
cls = {"skill":"skill","root-script":"root","manifest":"manifest","ci":"ci","test":"test","skill-script":"sscript","reference":"ref"}
lines = []
for nid, label, group, deg in NODES:
    lines.append(f'  {mid(nid)}["{label}"]')
for e in EDGES:
    a, b = e.split()
    lines.append(f'  {mid(a)} --> {mid(b)}')
for g, c in cls.items():
    ids = [mid(x[0]) for x in NODES if x[2] == g]
    lines.append(f'  class {",".join(ids)} {c}')
dag = "\n".join(lines)

# Timeline
rows = []
prev = ""
for h, d, subj, note, piv in COMMITS:
    month = d[:7]
    mark = ' class="pivot"' if piv else ''
    note_html = f'<span class="t-note">{html.escape(note)}</span>' if note else ''
    rows.append(f'<li{mark}><span class="t-date">{d}</span><span class="t-dot"></span>'
                f'<span class="t-body"><code class="t-hash">{h}</code> <span class="t-subj">{html.escape(subj)}</span>{note_html}</span></li>')
tl_html = "\n".join(rows)

# Bars
mx = max(p for _, _, p in SHARES)
rows = []
for s, l, p in SHARES:
    w = p / mx * 76
    rows.append(f'<div class="bar-row"><span class="bar-label">{s}</span><span class="bar-area">'
                f'<span class="bar" style="width:{w:.1f}%"></span><span class="bar-val">{n(l)} <small>{p}%</small></span></span></div>')
rows.append('<div class="bar-row other"><span class="bar-label">other 8 skills</span><span class="bar-area">'
            f'<span class="bar" style="width:{13.4/mx*76:.1f}%"></span><span class="bar-val">{n(17001-sum(l for _,l,_ in SHARES))} <small>13.4%</small></span></span></div>')
bars = "\n".join(rows)

src = open(sys.argv[1]).read()
out = (src.replace("@@TABLE1@@", t1).replace("@@TABLE1FOOT@@", t1_foot).replace("@@TABLE2@@", t2)
          .replace("@@DAG@@", dag).replace("@@TIMELINE@@", tl_html).replace("@@BARS@@", bars))
assert "@@" not in out, "placeholder left"
open(sys.argv[2], "w").write(out)
print("wrote", sys.argv[2], len(out), "bytes; other-8 lines =", 17001-sum(l for _,l,_ in SHARES))
