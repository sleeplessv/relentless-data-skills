import json, html

OUT = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto/variant-c.html"

skills = json.loads(open("/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/work-c/skills.json").read())

def n(v):
    return f"{v:,}"

# ---------- Table 1 ----------
t1_rows = []
for i, s in enumerate(skills):
    dmi = "yes" if s["disable_model_invocation"] else "no"
    t1_rows.append(
        f'<tr data-i="{i}"><td><code>{s["skill"]}</code></td><td class="num">{s["version"]}</td>'
        f'<td class="num">{s["skill_md_lines"]}</td><td class="num">{s["references_files"]}</td>'
        f'<td class="num">{s["scripts_files"]}</td><td>{dmi}</td><td class="num">{s["commits"]}</td>'
        f'<td class="num">{s["tracked_files"]}</td><td class="num">{n(s["total_tracked_lines"])}</td></tr>')
tot = dict(lines=sum(s["skill_md_lines"] for s in skills), refs=sum(s["references_files"] for s in skills),
           scr=sum(s["scripts_files"] for s in skills), dmi=sum(1 for s in skills if s["disable_model_invocation"]),
           commits=sum(s["commits"] for s in skills), files=sum(s["tracked_files"] for s in skills),
           tl=sum(s["total_tracked_lines"] for s in skills))
assert tot["lines"] == 2291 and tot["refs"] == 28 and tot["scr"] == 26 and tot["dmi"] == 8 and tot["commits"] == 210 and tot["tl"] == 17001, tot
table1 = f'''
<table class="sortable" id="table-1">
<thead><tr>
<th data-type="text">Skill</th><th data-type="text" class="num">Version</th>
<th data-type="num" class="num">SKILL.md (lines)</th><th data-type="num" class="num">references/ (files)</th>
<th data-type="num" class="num">scripts/ (files)</th><th data-type="text">DMI</th>
<th data-type="num" class="num">Commits</th><th data-type="num" class="num">Tracked (files)</th><th data-type="num" class="num">Tracked (lines)</th>
</tr></thead>
<tbody>
{chr(10).join(t1_rows)}
</tbody>
<tfoot><tr><td>Total, 18 skills</td><td></td><td class="num">{n(tot["lines"])}</td><td class="num">{tot["refs"]}</td><td class="num">{tot["scr"]}</td><td>{tot["dmi"]} yes</td><td class="num">{tot["commits"]}</td><td class="num">{tot["files"]}</td><td class="num">{n(tot["tl"])}</td></tr></tfoot>
</table>'''

# ---------- Node table (Table 2) and DAG ----------
nodes_raw = """candidate-to-spec | candidate-to-spec | skill | 4
dbt-runner | dbt-runner | skill | 3
dlt-bootstrap | dlt-bootstrap | skill | 5
fabric-lineage-dag | fabric-lineage-dag | skill | 2
gh-weekly-report | gh-weekly-report | skill | 3
implement-feature | implement-feature | skill | 5
implement-ticket | implement-ticket | skill | 3
metabase | metabase | skill | 2
orchestrator-mode | orchestrator-mode | skill | 4
prefect | prefect | skill | 2
qualify-delegation | qualify-delegation | skill | 1
review-pbi-diff | review-pbi-diff | skill | 3
ship | ship | skill | 5
smart-git-commit | smart-git-commit | skill | 3
snowman | snowman | skill | 3
statusline | statusline | skill | 2
student-mode | student-mode | skill | 1
visual-report | visual-report | skill | 4
lint_skill | scripts/lint_skill.py | root-script | 21
sync_registry | scripts/sync_registry.py | root-script | 5
skill_versions | scripts/skill_versions.py | root-script | 5
check_doc_urls | scripts/check_doc_urls.py | root-script | 2
check_sh | scripts/check.sh | root-script | 4
statusline_shots | scripts/statusline_screenshots.py | root-script | 1
plugin_json | skills/*/plugin.json (18 manifests) | manifest | 2
ci_version | CI job skill-version-check | ci | 2
ci_tests | CI job tests (py3.9 + 3.13) | ci | 13
ci_lint | CI job skill-lint | ci | 1
ci_plugin | CI job plugin-validate | ci | 0
ci_urls | CI job doc-url-liveness | ci | 1
test_candidate_to_spec_commands | tests/test_candidate_to_spec_commands.py | test | 3
test_dbt_runner | tests/test_dbt_runner.py | test | 2
test_dlt_bootstrap | tests/test_dlt_bootstrap.py | test | 2
test_gh_weekly_report | tests/test_gh_weekly_report.py | test | 3
test_lint_skill | tests/test_lint_skill.py | test | 2
test_metabase | tests/test_metabase.py | test | 2
test_review_pbi_diff | tests/test_review_pbi_diff.py | test | 3
test_skill_git_sequences | tests/test_skill_git_sequences.py | test | 5
test_skill_versions | tests/test_skill_versions.py | test | 2
test_snowman | tests/test_snowman.py | test | 2
test_statusline | tests/test_statusline.py | test | 2
test_sync_registry | tests/test_sync_registry.py | test | 2
test_visual_report | tests/test_visual_report.py | test | 2
check_render | visual-report/scripts/check_render.py | skill-script | 2
snowman_py | snowman/scripts/snowman.py | skill-script | 2
mb_py | metabase/scripts/mb.py | skill-script | 2
preflight_py | dbt-runner/scripts/preflight.py | skill-script | 2
extract_changes | review-pbi-diff/scripts/extract_changes.py | skill-script | 2
check_artifact | review-pbi-diff/scripts/check_artifact.py | skill-script | 2
statusline_sh | statusline/scripts/statusline.sh | skill-script | 3
collect_py | gh-weekly-report/scripts/collect.py | skill-script | 2
render_py | gh-weekly-report/scripts/render.py | skill-script | 2
fld_scripts | fabric-lineage-dag/scripts/ (17 files) | skill-script | 1
html_report | visual-report/references/HTML-REPORT.md | reference | 1
visual_language | visual-report/references/VISUAL-LANGUAGE.md | reference | 1
if_reference | implement-feature/references/reference.md | reference | 2"""
nodes = [[p.strip() for p in line.split("|")] for line in nodes_raw.splitlines()]
assert len(nodes) == 56
nodes_sorted = sorted(nodes, key=lambda r: (-int(r[3]), r[0]))
t2_rows = []
for i, (nid, label, group, deg) in enumerate(nodes_sorted):
    t2_rows.append(f'<tr data-i="{i}"><td><code>{html.escape(nid)}</code></td><td>{html.escape(label)}</td><td>{group}</td><td class="num">{deg}</td></tr>')
SHOW = 20
table2 = f'''
<table class="sortable" id="table-2" data-split="{SHOW}">
<thead><tr><th data-type="text">Node id</th><th data-type="text">Label (path or job)</th><th data-type="text">Group</th><th data-type="num" class="num">Degree (edges)</th></tr></thead>
<tbody>
{chr(10).join(t2_rows[:SHOW])}
</tbody>
<tbody class="extra" hidden>
{chr(10).join(t2_rows[SHOW:])}
</tbody>
</table>
<details class="more" data-for="table-2"><summary>{56 - SHOW} more rows are hidden. The {SHOW} rows above are the top {SHOW} in the current sort.</summary></details>'''

edges_raw = """candidate-to-spec --> implement-feature
candidate-to-spec --> orchestrator-mode
dbt-runner --> ship
dlt-bootstrap --> prefect
dlt-bootstrap --> ship
dlt-bootstrap --> snowman
implement-feature --> implement-ticket
implement-feature --> orchestrator-mode
implement-ticket --> orchestrator-mode
ship --> smart-git-commit
dbt-runner --> preflight_py
metabase --> mb_py
review-pbi-diff --> extract_changes
review-pbi-diff --> check_artifact
gh-weekly-report --> collect_py
gh-weekly-report --> render_py
fabric-lineage-dag --> fld_scripts
statusline --> statusline_sh
snowman --> snowman_py
visual-report --> check_render
visual-report --> html_report
visual-report --> visual_language
implement-feature --> if_reference
test_lint_skill --> lint_skill
test_skill_versions --> skill_versions
test_sync_registry --> sync_registry
test_dbt_runner --> preflight_py
test_metabase --> mb_py
test_review_pbi_diff --> extract_changes
test_review_pbi_diff --> check_artifact
test_snowman --> snowman_py
test_statusline --> statusline_sh
test_visual_report --> check_render
test_gh_weekly_report --> collect_py
test_gh_weekly_report --> render_py
test_dlt_bootstrap --> dlt-bootstrap
test_candidate_to_spec_commands --> candidate-to-spec
test_candidate_to_spec_commands --> test_skill_git_sequences
test_skill_git_sequences --> if_reference
test_skill_git_sequences --> ship
test_skill_git_sequences --> smart-git-commit
ci_version --> skill_versions
ci_version --> sync_registry
ci_lint --> lint_skill
ci_urls --> check_doc_urls
ci_tests --> test_candidate_to_spec_commands
ci_tests --> test_dbt_runner
ci_tests --> test_dlt_bootstrap
ci_tests --> test_gh_weekly_report
ci_tests --> test_lint_skill
ci_tests --> test_metabase
ci_tests --> test_review_pbi_diff
ci_tests --> test_skill_git_sequences
ci_tests --> test_skill_versions
ci_tests --> test_snowman
ci_tests --> test_statusline
ci_tests --> test_sync_registry
ci_tests --> test_visual_report
check_sh --> lint_skill
check_sh --> sync_registry
check_sh --> skill_versions
check_sh --> check_doc_urls
skill_versions --> sync_registry
skill_versions --> plugin_json
sync_registry --> plugin_json
statusline_shots --> statusline_sh
lint_skill --> candidate-to-spec
lint_skill --> dbt-runner
lint_skill --> dlt-bootstrap
lint_skill --> fabric-lineage-dag
lint_skill --> gh-weekly-report
lint_skill --> implement-feature
lint_skill --> implement-ticket
lint_skill --> metabase
lint_skill --> orchestrator-mode
lint_skill --> prefect
lint_skill --> qualify-delegation
lint_skill --> review-pbi-diff
lint_skill --> ship
lint_skill --> smart-git-commit
lint_skill --> snowman
lint_skill --> statusline
lint_skill --> student-mode
lint_skill --> visual-report"""
edges = [tuple(p.strip() for p in e.split("-->")) for e in edges_raw.splitlines()]
assert len(edges) == 84
ids = {r[0] for r in nodes}
for a, b in edges:
    assert a in ids and b in ids, (a, b)
# degree check against the node table
deg = {r[0]: 0 for r in nodes}
for a, b in edges:
    deg[a] += 1; deg[b] += 1
for r in nodes:
    assert deg[r[0]] == int(r[3]), (r[0], deg[r[0]], r[3])

mid = lambda s: s.replace("-", "_")
group_class = {"skill": "gSkill", "root-script": "gRoot", "manifest": "gManifest", "ci": "gCi", "test": "gTest", "skill-script": "gScript", "reference": "gRef"}
dag_lines = ["---", "config:", "  layout: elk", "  theme: base", "  themeVariables:",
             "    fontFamily: '\"Helvetica Neue\", Arial, system-ui, sans-serif'",
             "    primaryTextColor: \"#1a1c1e\"", "    lineColor: \"#8a8f98\"",
             "  flowchart:", "    useMaxWidth: false", "    nodeSpacing: 4", "    rankSpacing: 45", "    padding: 2",
             "  elk:", "    mergeEdges: true", "    nodePlacementStrategy: SIMPLE",
             "---", "flowchart LR"]
def short_label(nid, label):
    fixed = {"plugin_json": "plugin.json (18)", "fld_scripts": "fabric-lineage-dag/scripts (17)"}
    if nid in fixed: return fixed[nid]
    if label.startswith("CI job "): return "CI " + label[7:].split(" (")[0]
    if label.startswith("tests/"): return label[6:-3]
    if label.startswith("scripts/"): return label[8:]
    if "/scripts/" in label: return label.split("/scripts/")[1]
    if "/references/" in label: return label.split("/")[0].split("-")[0] + "/" + label.split("/references/")[1]
    return label
for nid, label, group, d in nodes:
    dag_lines.append(f'  {mid(nid)}["{short_label(nid, label)}"]')
for a, b in edges:
    dag_lines.append(f"  {mid(a)} --> {mid(b)}")
dag_lines += [
    "  classDef gSkill fill:#e3efe9,stroke:#0b6e4f,color:#1a1c1e",
    "  classDef gRoot fill:#e1eaf3,stroke:#30638e,color:#1a1c1e",
    "  classDef gManifest fill:#f1efe8,stroke:#8a8f98,color:#1a1c1e",
    "  classDef gCi fill:#ebe4f3,stroke:#7b5ea7,color:#1a1c1e",
    "  classDef gTest fill:#ededef,stroke:#8a8f98,color:#1a1c1e",
    "  classDef gScript fill:#fbf0d9,stroke:#edae49,color:#1a1c1e",
    "  classDef gRef fill:#f8e3e6,stroke:#d1495b,color:#1a1c1e",
    "  classDef hub stroke-width:3px",
]
for g, cls in group_class.items():
    members = ",".join(mid(r[0]) for r in nodes if r[2] == g)
    dag_lines.append(f"  class {members} {cls}")
dag_lines.append("  class lint_skill,ci_tests hub")
dag_src = "\n".join(dag_lines)

# ---------- Figure 7 timeline ----------
commits = [
 ("6db3ef0","2026-06-09","feat: add visual-report skill","skill created",False),
 ("f9b72a8","2026-06-09","docs(skills): add prefect debug/CLI protocol and visual-report improvements","",False),
 ("dc10b07","2026-06-09","chore: remove license and version from multiple skill files","",False),
 ("49a91cc","2026-06-12","Generate marketplace.json and the README skills table from plugin.json (#27)","plugin.json becomes the source of truth",False),
 ("5961bf5","2026-06-18","docs(skills): quality pass across all 9 skills (#28)","the catalogue had 9 skills",False),
 ("83b2c2b","2026-07-24","docs(skills): tune all skills for Opus 5 prompting guidance (#41)","",False),
 ("fa5e069","2026-09-03","docs: remove em dashes from skill docs prose (#59)","",False),
 ("ebdcdce","2026-09-03","snowman: token-efficient CSV output, cleaner errors, plain-language docs (#61)","",False),
 ("207218c","2026-09-16","docs(skills): refresh descriptions and documentation links (#69)","",False),
 ("3db5ecb","2026-09-23","chore(skills): apply prompt audit for Fable 5.1 (#71)","",False),
 ("088a29f","2026-10-03","feat(skills): add prove-it-works checks (#75)","Pivotal. Adds scripts/check_render.py (+985) and tests/test_visual_report.py (+345); 16 files, +2,605 and -41.",True),
 ("dc788de","2026-10-18","chore: migrate agent config to GLOSSARY.md and AGENTS.md (#91)","",False),
]
tl = []
for k, (h, d, s, note, piv) in enumerate(commits, 1):
    cls = ' class="pivotal"' if piv else ""
    note_html = f'<span class="tl-note">{html.escape(note)}</span>' if note else ""
    tl.append(f'<li{cls}><span class="tl-n">{k}</span><span class="tl-date">{d}</span><span class="tl-dot"></span><span class="tl-body"><code>{h}</code> <span class="tl-subj">{html.escape(s)}</span>{note_html}</span></li>')
timeline = '<ol class="timeline">\n' + "\n".join(tl) + "\n</ol>"

# ---------- Figure 8 bars ----------
bars_data = [("fabric-lineage-dag",3635,21.4),("review-pbi-diff",1927,11.3),("metabase",1803,10.6),("snowman",1601,9.4),("visual-report",1318,7.8),("dbt-runner",1064,6.3),("gh-weekly-report",1060,6.2),("statusline",1038,6.1),("candidate-to-spec",728,4.3),("implement-ticket",538,3.2)]
rest_lines = 17001 - sum(b[1] for b in bars_data)
assert rest_lines == 2289
bars = ['<div class="bars">']
for name, lines, pct in bars_data:
    bars.append(f'<div class="bar-row"><span class="bar-label"><code>{name}</code></span><span class="bar-track"><span class="bar" style="--w:{pct}"></span><span class="bar-val">{n(lines)} <span class="bar-pct">{pct}%</span></span></span></div>')
bars.append(f'<div class="bar-row other"><span class="bar-label">8 other skills</span><span class="bar-track"><span class="bar" style="--w:13.4"></span><span class="bar-val">{n(rest_lines)} <span class="bar-pct">13.4%</span></span></span></div>')
bars.append('</div>')
bars_html = "\n".join(bars)

# ---------- Figure 6 matrix ----------
matrix_rows = [
 (1,"Diagram is Mermaid's error diagram","<code>status: error</code> (DRAWN_BAD)","FAIL","defect"),
 (2,"Diagram collapsed to a speck or shows no labels","<code>status: empty</code> (DRAWN_BAD)","FAIL","defect"),
 (3,"Diagram shrunk until labels are unreadable (under 6 px)","<code>status: illegible</code> (DRAWN_BAD)","FAIL","defect"),
 (4,"Diagram cut off by an <code>overflow: hidden</code> box","<code>status: clipped</code> (DRAWN_BAD)","FAIL","defect"),
 (5,"Broken image","<code>broken_images</code> non-empty","FAIL","defect"),
 (6,"Resource answers 404, or a non-CDN host does not exist while others loaded","<code>requests[].kind == \"defect\"</code>","FAIL","defect"),
 (7,"Page freezes its tab (a query takes over 10 s)","<code>hung</code> set","FAIL","defect"),
 (8,"Diagram never rendered or still rendering, network fine","<code>status: unrendered</code> or <code>rendering</code> (NOT_DRAWN)","FAIL","soft"),
 (9,"Page error or console error, network fine","<code>page_errors</code>, <code>console_errors</code>","FAIL","soft"),
 (10,"No Playwright import, or no browser could launch","<code>blocked</code> set","BLOCKED","environment"),
 (11,"A CDN host unreachable or answering HTTP 5xx","<code>requests[].kind == \"blocked\"</code> or diagram <code>env</code>","BLOCKED","environment"),
 (12,"Check did not finish within 140 s (watchdog at 160 s)","<code>incomplete</code> set","BLOCKED","environment"),
 (13,"Diagram still hidden after reveal (listed, not judged)","<code>unverified</code>","PASS","note"),
 (14,"None of the above","","PASS",""),
]
mrows = []
for i, (k, cond, field, verdict, tier) in enumerate(matrix_rows):
    def cell(v):
        if verdict == v:
            extra = " listed" if (k == 13) else ""
            return f'<td class="mark" data-v="1"><span class="dot {v.lower()}" title="{v}"></span>{extra}</td>'
        return '<td class="mark" data-v="0"></td>'
    mrows.append(f'<tr data-i="{i}"><td class="num">{k}</td><td>{cond}</td><td>{field}</td>{cell("PASS")}{cell("FAIL")}{cell("BLOCKED")}<td>{tier}</td></tr>')
matrix = f'''
<table class="sortable matrix" id="fig6-table">
<thead><tr><th data-type="num" class="num">#</th><th data-type="text">Condition (docstring wording)</th><th data-type="text">Status or field in <code>result</code></th><th data-type="num" class="mark">PASS</th><th data-type="num" class="mark">FAIL</th><th data-type="num" class="mark">BLOCKED</th><th data-type="text">Tier</th></tr></thead>
<tbody>
{chr(10).join(mrows)}
</tbody>
</table>'''

# ---------- Figure 5 code ----------
code_lines = [
 (354, 'def verdict(result):', None),
 (355, '    """Proof of a defect beats an environment problem, which beats softer evidence.', None),
 (356, '', None),
 (357, '    An error diagram, a 404, or a broken image is a defect whatever else went', None),
 (358, '    wrong. An unreachable CDN explains unrendered diagrams and script errors,', None),
 (359, '    so those count only when the network was fine.', None),
 (360, '    """', None),
 (361, '    if result.get("blocked"):', 1),
 (362, '        return BLOCKED', None),
 (363, '    diagrams = result.get("diagrams", [])', None),
 (364, '    requests = result.get("requests", [])', None),
 (365, '    if (any(d["status"] in DRAWN_BAD and not d.get("env") for d in diagrams)', 2),
 (366, '            or any(r["kind"] == "defect" for r in requests)', None),
 (367, '            or result.get("broken_images") or result.get("hung")):', 3),
 (368, '        return FAIL', None),
 (369, '    if (any(r["kind"] == "blocked" for r in requests)', 4),
 (370, '            or any(d.get("env") for d in diagrams) or result.get("incomplete")):', None),
 (371, '        return BLOCKED', None),
 (372, '    if (any(d["status"] in NOT_DRAWN for d in diagrams)', 5),
 (373, '            or result.get("page_errors") or result.get("console_errors")):', None),
 (374, '        return FAIL', None),
 (375, '    return PASS', None),
]
assert code_lines[0][0] == 354 and code_lines[-1][0] == 375 and len(code_lines) == 22
code_html = '<pre class="code" style="counter-reset: line 353"><code>' + "".join(
    f'<span class="l"{(" data-mark=%d" % m) if m else ""}>{html.escape(t) or " "}</span>' for _, t, m in code_lines) + "</code></pre>"

# ---------- Sequence diagram ----------
seq_src = """---
config:
  theme: base
  themeVariables:
    fontFamily: '"Helvetica Neue", Arial, system-ui, sans-serif'
    fontSize: 13px
    primaryColor: "#f1efe8"
    primaryBorderColor: "#1a1c1e"
    primaryTextColor: "#1a1c1e"
    lineColor: "#1a1c1e"
    signalColor: "#1a1c1e"
    signalTextColor: "#1a1c1e"
    actorBorder: "#1a1c1e"
    actorBkg: "#f1efe8"
    actorTextColor: "#1a1c1e"
    actorLineColor: "#8a8f98"
    noteBkgColor: "#fff4d6"
    noteBorderColor: "#b7791f"
    noteTextColor: "#1a1c1e"
    activationBkgColor: "#e3efe9"
    activationBorderColor: "#0b6e4f"
    labelBoxBkgColor: "#fbfaf7"
    labelBoxBorderColor: "#8a8f98"
    altSectionBkgColor: "#fbfaf7"
  sequence:
    useMaxWidth: true
    mirrorActors: false
    wrap: true
    width: 110
    actorMargin: 30
    messageMargin: 22
    boxMargin: 6
    height: 40
---
sequenceDiagram
  autonumber
  participant A as Agent
  participant S as Script
  participant C as Chromium
  participant N as CDNs
  participant R as Report file
  A->>+S: check REPORT.html
  S->>R: read_source()
  R-->>S: HTML text
  alt OSError
    S-->>A: FAIL, exit 1
  end
  alt no browser
    S-->>A: BLOCKED, exit 2
  end
  S->>+C: launch(), new_page()
  S->>C: goto(report), 30 s
  C->>N: GET scripts
  N-->>C: responses
  S->>C: settle(), 20 s
  S->>C: facts(), reveal(),<br/>facts() again
  Note over S,C: diagram_status(),<br/>images(), screenshots()
  S->>C: probe(), 15 s each
  alt a request failed
    S->>C: fetch(jsDelivr), 5 s
    C->>N: GET package.json
    N-->>C: network_ok
  end
  S->>C: close(), 10 s cap
  deactivate C
  S->>S: emit(), verdict()
  S-->>-A: PASS, FAIL or BLOCKED"""

# ---------- Charts data ----------
fig1_data = json.dumps([{"skill": s["skill"], "lines": s["skill_md_lines"]} for s in sorted(skills, key=lambda s: -s["skill_md_lines"])])
fig2_data = json.dumps([{"month": "2026-05", "commits": 4}, {"month": "2026-06", "commits": 37}, {"month": "2026-07", "commits": 14}, {"month": "2026-08", "commits": 10}, {"month": "2026-09", "commits": 23}, {"month": "2026-10", "commits": 36}])

tpl = open("/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/work-c/template.html").read()
out = (tpl.replace("@@TABLE1@@", table1).replace("@@TABLE2@@", table2).replace("@@DAG@@", dag_src)
          .replace("@@TIMELINE@@", timeline).replace("@@BARS@@", bars_html).replace("@@MATRIX@@", matrix)
          .replace("@@CODE@@", code_html).replace("@@SEQ@@", seq_src)
          .replace("@@FIG1DATA@@", fig1_data).replace("@@FIG2DATA@@", fig2_data))
assert "@@" not in out, [l for l in out.splitlines() if "@@" in l][:3]
open(OUT, "w").write(out)
print("wrote", OUT, len(out), "bytes")
