import json, html

OUT = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto/variant-navy-coral-v2.html"

SKILLS = json.loads('''[
 {"skill":"candidate-to-spec","version":"0.1.1","skill_md_lines":129,"references_files":3,"scripts_files":0,"disable_model_invocation":true,"commits":2,"total_tracked_lines":728,"tracked_files":6},
 {"skill":"dbt-runner","version":"0.1.8","skill_md_lines":134,"references_files":3,"scripts_files":1,"disable_model_invocation":false,"commits":15,"total_tracked_lines":1064,"tracked_files":7},
 {"skill":"dlt-bootstrap","version":"0.1.1","skill_md_lines":133,"references_files":3,"scripts_files":0,"disable_model_invocation":false,"commits":10,"total_tracked_lines":388,"tracked_files":6},
 {"skill":"fabric-lineage-dag","version":"0.1.2","skill_md_lines":89,"references_files":3,"scripts_files":17,"disable_model_invocation":false,"commits":6,"total_tracked_lines":3635,"tracked_files":23},
 {"skill":"gh-weekly-report","version":"0.1.2","skill_md_lines":119,"references_files":1,"scripts_files":2,"disable_model_invocation":true,"commits":8,"total_tracked_lines":1060,"tracked_files":6},
 {"skill":"implement-feature","version":"0.2.5","skill_md_lines":142,"references_files":1,"scripts_files":0,"disable_model_invocation":true,"commits":21,"total_tracked_lines":513,"tracked_files":4},
 {"skill":"implement-ticket","version":"0.2.8","skill_md_lines":150,"references_files":4,"scripts_files":0,"disable_model_invocation":true,"commits":22,"total_tracked_lines":538,"tracked_files":7},
 {"skill":"metabase","version":"0.1.0","skill_md_lines":150,"references_files":3,"scripts_files":1,"disable_model_invocation":false,"commits":4,"total_tracked_lines":1803,"tracked_files":7},
 {"skill":"orchestrator-mode","version":"0.5.4","skill_md_lines":147,"references_files":1,"scripts_files":0,"disable_model_invocation":false,"commits":25,"total_tracked_lines":306,"tracked_files":4},
 {"skill":"prefect","version":"0.2.2","skill_md_lines":150,"references_files":0,"scripts_files":0,"disable_model_invocation":false,"commits":9,"total_tracked_lines":241,"tracked_files":3},
 {"skill":"qualify-delegation","version":"0.1.0","skill_md_lines":123,"references_files":0,"scripts_files":0,"disable_model_invocation":false,"commits":1,"total_tracked_lines":183,"tracked_files":3},
 {"skill":"review-pbi-diff","version":"0.1.3","skill_md_lines":150,"references_files":1,"scripts_files":2,"disable_model_invocation":true,"commits":8,"total_tracked_lines":1927,"tracked_files":6},
 {"skill":"ship","version":"0.1.7","skill_md_lines":148,"references_files":0,"scripts_files":0,"disable_model_invocation":true,"commits":17,"total_tracked_lines":260,"tracked_files":3},
 {"skill":"smart-git-commit","version":"0.1.3","skill_md_lines":114,"references_files":0,"scripts_files":0,"disable_model_invocation":false,"commits":13,"total_tracked_lines":183,"tracked_files":3},
 {"skill":"snowman","version":"0.1.4","skill_md_lines":143,"references_files":3,"scripts_files":1,"disable_model_invocation":false,"commits":23,"total_tracked_lines":1601,"tracked_files":7},
 {"skill":"statusline","version":"0.5.0","skill_md_lines":64,"references_files":0,"scripts_files":1,"disable_model_invocation":true,"commits":10,"total_tracked_lines":1038,"tracked_files":8},
 {"skill":"student-mode","version":"0.2.0","skill_md_lines":150,"references_files":0,"scripts_files":0,"disable_model_invocation":true,"commits":4,"total_tracked_lines":215,"tracked_files":3},
 {"skill":"visual-report","version":"0.1.3","skill_md_lines":56,"references_files":2,"scripts_files":1,"disable_model_invocation":false,"commits":12,"total_tracked_lines":1318,"tracked_files":6}
]''')

MONTHS = [{"month":"2026-05","commits":4},{"month":"2026-06","commits":37},{"month":"2026-07","commits":14},{"month":"2026-08","commits":10},{"month":"2026-09","commits":23},{"month":"2026-10","commits":36}]

NODES = [l.split("|") for l in '''candidate-to-spec|candidate-to-spec|skill|4
dbt-runner|dbt-runner|skill|3
dlt-bootstrap|dlt-bootstrap|skill|5
fabric-lineage-dag|fabric-lineage-dag|skill|2
gh-weekly-report|gh-weekly-report|skill|3
implement-feature|implement-feature|skill|5
implement-ticket|implement-ticket|skill|3
metabase|metabase|skill|2
orchestrator-mode|orchestrator-mode|skill|4
prefect|prefect|skill|2
qualify-delegation|qualify-delegation|skill|1
review-pbi-diff|review-pbi-diff|skill|3
ship|ship|skill|5
smart-git-commit|smart-git-commit|skill|3
snowman|snowman|skill|3
statusline|statusline|skill|2
student-mode|student-mode|skill|1
visual-report|visual-report|skill|4
lint_skill|scripts/lint_skill.py|root-script|21
sync_registry|scripts/sync_registry.py|root-script|5
skill_versions|scripts/skill_versions.py|root-script|5
check_doc_urls|scripts/check_doc_urls.py|root-script|2
check_sh|scripts/check.sh|root-script|4
statusline_shots|scripts/statusline_screenshots.py|root-script|1
plugin_json|skills/*/plugin.json (18 manifests)|manifest|2
ci_version|CI job skill-version-check|ci|2
ci_tests|CI job tests (py3.9 + 3.13)|ci|13
ci_lint|CI job skill-lint|ci|1
ci_plugin|CI job plugin-validate|ci|0
ci_urls|CI job doc-url-liveness|ci|1
test_candidate_to_spec_commands|tests/test_candidate_to_spec_commands.py|test|3
test_dbt_runner|tests/test_dbt_runner.py|test|2
test_dlt_bootstrap|tests/test_dlt_bootstrap.py|test|2
test_gh_weekly_report|tests/test_gh_weekly_report.py|test|3
test_lint_skill|tests/test_lint_skill.py|test|2
test_metabase|tests/test_metabase.py|test|2
test_review_pbi_diff|tests/test_review_pbi_diff.py|test|3
test_skill_git_sequences|tests/test_skill_git_sequences.py|test|5
test_skill_versions|tests/test_skill_versions.py|test|2
test_snowman|tests/test_snowman.py|test|2
test_statusline|tests/test_statusline.py|test|2
test_sync_registry|tests/test_sync_registry.py|test|2
test_visual_report|tests/test_visual_report.py|test|2
check_render|visual-report/scripts/check_render.py|skill-script|2
snowman_py|snowman/scripts/snowman.py|skill-script|2
mb_py|metabase/scripts/mb.py|skill-script|2
preflight_py|dbt-runner/scripts/preflight.py|skill-script|2
extract_changes|review-pbi-diff/scripts/extract_changes.py|skill-script|2
check_artifact|review-pbi-diff/scripts/check_artifact.py|skill-script|2
statusline_sh|statusline/scripts/statusline.sh|skill-script|3
collect_py|gh-weekly-report/scripts/collect.py|skill-script|2
render_py|gh-weekly-report/scripts/render.py|skill-script|2
fld_scripts|fabric-lineage-dag/scripts/ (17 files)|skill-script|1
html_report|visual-report/references/HTML-REPORT.md|reference|1
visual_language|visual-report/references/VISUAL-LANGUAGE.md|reference|1
if_reference|implement-feature/references/reference.md|reference|2'''.split("\n")]
assert len(NODES) == 56

EDGES = '''candidate-to-spec --> implement-feature
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
lint_skill --> visual-report'''.split("\n")
assert len(EDGES) == 84

COMMITS = [
 ("6db3ef0","2026-06-09","feat: add visual-report skill","skill created",False),
 ("f9b72a8","2026-06-09","docs(skills): add prefect debug/CLI protocol and visual-report improvements","",False),
 ("dc10b07","2026-06-09","chore: remove license and version from multiple skill files","",False),
 ("49a91cc","2026-06-12","Generate marketplace.json and the README skills table from plugin.json (#27)","plugin.json becomes source of truth",False),
 ("5961bf5","2026-06-18","docs(skills): quality pass across all 9 skills (#28)","catalogue had 9 skills",False),
 ("83b2c2b","2026-07-24","docs(skills): tune all skills for Opus 5 prompting guidance (#41)","",False),
 ("fa5e069","2026-09-03","docs: remove em dashes from skill docs prose (#59)","",False),
 ("ebdcdce","2026-09-03","snowman: token-efficient CSV output, cleaner errors, plain-language docs (#61)","",False),
 ("207218c","2026-09-16","docs(skills): refresh descriptions and documentation links (#69)","",False),
 ("3db5ecb","2026-09-23","chore(skills): apply prompt audit for Fable 5.1 (#71)","",False),
 ("088a29f","2026-10-03","feat(skills): add prove-it-works checks (#75)","adds scripts/check_render.py (+985) and tests/test_visual_report.py (+345); 16 files, +2,605 / -41",True),
 ("dc788de","2026-10-18","chore: migrate agent config to GLOSSARY.md and AGENTS.md (#91)","",False),
]

SHARES = [("fabric-lineage-dag",3635,21.4),("review-pbi-diff",1927,11.3),("metabase",1803,10.6),("snowman",1601,9.4),("visual-report",1318,7.8),("dbt-runner",1064,6.3),("gh-weekly-report",1060,6.2),("statusline",1038,6.1),("candidate-to-spec",728,4.3),("implement-ticket",538,3.2)]

MATRIX = [
 (1,"Diagram is Mermaid's error diagram","status: error (DRAWN_BAD)","FAIL","defect"),
 (2,"Diagram collapsed to a speck or shows no labels","status: empty (DRAWN_BAD)","FAIL","defect"),
 (3,"Diagram shrunk until labels are unreadable (under 6 px)","status: illegible (DRAWN_BAD)","FAIL","defect"),
 (4,"Diagram cut off by an overflow:hidden box","status: clipped (DRAWN_BAD)","FAIL","defect"),
 (5,"Broken image","broken_images non-empty","FAIL","defect"),
 (6,"Resource answers 404, or a non-CDN host does not exist while others loaded","requests[].kind == \"defect\"","FAIL","defect"),
 (7,"Page freezes its tab (a query takes over 10 s)","hung set","FAIL","defect"),
 (8,"Diagram never rendered or still rendering (network fine)","status: unrendered or rendering (NOT_DRAWN)","FAIL","soft"),
 (9,"Page error or console error (network fine)","page_errors, console_errors","FAIL","soft"),
 (10,"No Playwright import or no browser could launch","blocked set","BLOCKED","environment"),
 (11,"A CDN host unreachable or answering HTTP 5xx","requests[].kind == \"blocked\" or diagram env","BLOCKED","environment"),
 (12,"Check did not finish within 140 s (or watchdog at 160 s)","incomplete set","BLOCKED","environment"),
 (13,"Diagram still hidden after reveal (listed, not judged)","unverified","PASS*","note"),
 (14,"None of the above","","PASS",""),
]

# ---------- theme (c: P1 Navy & coral; answer box from P2, set in the template) ----------
THEME = dict(ink="#102542", muted="#5f5348", paper="#ffffff", surface="#f4f7f7", line="#e1e7e7", rule="#7b8786",
             coral_text="#c2493a", coral_fill="#f87060", coral_line="#d95646", coral_soft="#fff1ed",
             th_bg="#edf1f1", code_fg="#24514e", code_bg="#eef3f3", sage="#4f7f7c", taupe="#8a7766",
             amber="#b7791f", amber_soft="#fcf2dd")
MM_THEME = json.dumps({
  "fontFamily": '-apple-system, "Segoe UI", Helvetica, Arial, sans-serif', "fontSize": "13px",
  "primaryColor": "#ffffff", "primaryBorderColor": THEME["ink"], "primaryTextColor": THEME["ink"],
  "secondaryColor": THEME["th_bg"], "tertiaryColor": THEME["paper"], "lineColor": THEME["rule"], "textColor": THEME["ink"],
  "noteBkgColor": THEME["amber_soft"], "noteBorderColor": THEME["amber"], "noteTextColor": THEME["ink"],
  "actorBkg": THEME["th_bg"], "actorBorder": THEME["ink"], "actorTextColor": THEME["ink"], "actorLineColor": THEME["rule"],
  "signalColor": THEME["ink"], "signalTextColor": THEME["ink"],
  "labelBoxBkgColor": THEME["th_bg"], "labelBoxBorderColor": THEME["rule"], "labelTextColor": THEME["ink"], "loopTextColor": THEME["ink"],
  "activationBorderColor": THEME["coral_line"], "activationBkgColor": THEME["coral_soft"], "sequenceNumberColor": "#ffffff"})

def n(x): return f"{x:,}"
def esc(s): return html.escape(s, quote=True)
def vkey(v):
    a,b,c = v.split("."); return f"{int(a):03d}.{int(b):03d}.{int(c):03d}"

# ---------- Table 1 ----------
t1_rows = []
for s in SKILLS:
    dmi = "yes" if s["disable_model_invocation"] else "no"
    t1_rows.append(
      f'<tr><td class="id">{s["skill"]}</td>'
      f'<td class="num" data-v="{vkey(s["version"])}"><code>{s["version"]}</code></td>'
      f'<td class="num lines{" at" if s["skill_md_lines"]==150 else ""}"><span class="cbar" style="--w:{s["skill_md_lines"]/150*100:.1f}%">{s["skill_md_lines"]}</span></td>'
      f'<td class="num">{s["references_files"]}</td>'
      f'<td class="num">{s["scripts_files"]}</td>'
      f'<td class="txt" data-v="{1 if s["disable_model_invocation"] else 0}">{dmi}</td>'
      f'<td class="num">{s["commits"]}</td>'
      f'<td class="num">{s["tracked_files"]}</td>'
      f'<td class="num">{n(s["total_tracked_lines"])}</td></tr>')
tot = dict(l=sum(s["skill_md_lines"] for s in SKILLS), r=sum(s["references_files"] for s in SKILLS),
           sc=sum(s["scripts_files"] for s in SKILLS), d=sum(1 for s in SKILLS if s["disable_model_invocation"]),
           c=sum(s["commits"] for s in SKILLS), tf=sum(s["tracked_files"] for s in SKILLS), tl=sum(s["total_tracked_lines"] for s in SKILLS))
assert (tot["l"],tot["r"],tot["sc"],tot["d"],tot["c"],tot["tl"]) == (2291,28,26,8,210,17001), tot
TABLE1 = f'''<table class="data sortable" id="table-1">
<thead><tr>
<th class="txt" data-type="txt">Skill</th>
<th class="num" data-type="txt">Version</th>
<th class="num" data-type="num">SKILL.md (lines)</th>
<th class="num" data-type="num">references/ (files)</th>
<th class="num" data-type="num">scripts/ (files)</th>
<th class="txt" data-type="num">DMI</th>
<th class="num" data-type="num">Commits</th>
<th class="num" data-type="num">Tracked (files)</th>
<th class="num" data-type="num">Tracked (lines)</th>
</tr></thead>
<tbody>
{chr(10).join(t1_rows)}
</tbody>
<tfoot><tr><td class="txt">Total, 18 skills</td><td></td><td class="num">{n(tot["l"])}</td><td class="num">{tot["r"]}</td><td class="num">{tot["sc"]}</td><td class="txt">{tot["d"]} yes</td><td class="num">{tot["c"]}</td><td class="num">{tot["tf"]}</td><td class="num">{n(tot["tl"])}</td></tr></tfoot>
</table>'''

# ---------- Table 2 (node table), sorted by degree desc, stable ----------
nodes_sorted = sorted(enumerate(NODES), key=lambda t: (-int(t[1][3]), t[0]))
def noderow(nd):
    i,l,g,d = nd
    return f'<tr><td class="id"><code>{esc(i).replace("_", "_<wbr>")}</code></td><td class="txt">{esc(l).replace("/", "/<wbr>")}</td><td class="txt">{g}</td><td class="num">{d}</td></tr>'
main_rows = [noderow(nd) for _,nd in nodes_sorted[:20]]
rest_rows = [noderow(nd) for _,nd in nodes_sorted[20:]]
assert len(rest_rows) == 36
TABLE2 = f'''<table class="data sortable" id="table-2" data-show="20">
<colgroup><col class="c-id"><col class="c-label"><col class="c-group"><col class="c-deg"></colgroup>
<thead><tr>
<th class="txt" data-type="txt">Node id</th>
<th class="txt" data-type="txt">Label</th>
<th class="txt" data-type="txt">Group</th>
<th class="num" data-type="num">Degree (edges)</th>
</tr></thead>
<tbody id="t2-main">
{chr(10).join(main_rows)}
</tbody>
<tbody id="t2-rest" hidden>
{chr(10).join(rest_rows)}
</tbody>
</table>
<details class="more" data-target="t2-rest"><summary><span class="when-closed">Show the remaining 36 rows (56 nodes in total)</span><span class="when-open">Hide the remaining 36 rows (showing all 56)</span></summary></details>'''

# ---------- Figure 3 Mermaid DAG: two-hop neighbourhood of visual-report ----------
import collections
def mid(s): return s.replace("-","_")
ADJ = collections.defaultdict(set)
for e in EDGES:
    a,b = e.split(" --> "); ADJ[a].add(b); ADJ[b].add(a)
HOOD = {"visual-report"}; frontier = {"visual-report"}
for _ in range(2):
    nxt = set()
    for x in frontier: nxt |= ADJ[x]
    frontier = nxt - HOOD
    HOOD |= nxt
HOOD.add("ci_tests")   # the CI job that runs tests/test_visual_report.py, three hops away but part of the agreed neighbourhood
HOOD_EDGES = [e for e in EDGES if all(x in HOOD for x in e.split(" --> "))]
NODE_BY_ID = {i:(l,g,d) for i,l,g,d in NODES}
DAG_N, DAG_E = len(HOOD), len(HOOD_EDGES)
assert DAG_N == 27, DAG_N

# DAG classes from P1. No red or amber: red is for problems, amber for callouts.
CAT = {"skill":"c1", "root-script":"c2", "manifest":"c2", "ci":"c3", "test":"c4", "skill-script":"c5", "reference":"c6"}
CLASSDEF = {
  "c1": "fill:#ffffff,stroke:#102542,color:#102542",
  "c2": "fill:#edf1f1,stroke:#4f7f7c,color:#102542",
  "c3": "fill:#e3e8f0,stroke:#102542,color:#102542",
  "c4": "fill:#f3efeb,stroke:#8a7766,color:#102542",
  "c5": "fill:#eef3f3,stroke:#24514e,color:#24514e",
  "c6": "fill:#ffffff,stroke:#8a7766,color:#102542,stroke-dasharray:4 3",
  "grp": "fill:#edf1f1,stroke:#102542,color:#102542,stroke-dasharray:5 4",
}
SHORT = {"visual-report":"visual-report", "lint_skill":"lint_skill.py", "check_sh":"check.sh", "ci_tests":"CI: tests",
         "ci_lint":"CI: skill-lint", "test_lint_skill":"test_lint_skill.py", "test_visual_report":"test_visual_report.py",
         "check_render":"check_render.py", "html_report":"HTML-REPORT.md", "visual_language":"VISUAL-LANGUAGE.md"}

def dag_source():
    mer = ["---","config:","  layout: elk","  elk:","    mergeEdges: true","    nodePlacementStrategy: LINEAR_SEGMENTS","  flowchart:","    useMaxWidth: false","    padding: 8","  themeVariables:","    fontSize: 12px","---","flowchart TB"]
    ids = sorted(HOOD, key=lambda i: [n[0] for n in NODES].index(i))
    others = [i for i in ids if NODE_BY_ID[i][1]=="skill" and i!="visual-report"]
    cls = collections.defaultdict(list)
    for i in ids:
        if i in others: continue
        mer.append(f'  {mid(i)}["{SHORT[i]}"]')
        cls[CAT[NODE_BY_ID[i][1]]].append(mid(i))
    mer.append(f'  other_skills["{len(others)} other skills"]'); cls["grp"].append("other_skills")
    seen = set()
    for e in HOOD_EDGES:
        a,b = e.split(" --> ")
        if a in others and b in others: continue
        a = "other_skills" if a in others else a
        b = "other_skills" if b in others else b
        if (a,b) in seen: continue
        seen.add((a,b)); mer.append(f"  {mid(a)} --> {mid(b)}")
    for c, d in CLASSDEF.items():
        mer.append(f"  classDef {c} {d};")
    mer.append("  classDef hub stroke-width:3px;")
    mer.append("  classDef focus fill:#f87060,stroke:#d95646,color:#102542,stroke-width:2px,font-weight:bold;")
    for c, items in cls.items():
        mer.append(f"  class {','.join(items)} {c};")
    mer.append("  class lint_skill,ci_tests hub;")
    mer.append("  class visual_report focus;")
    return "\n".join(mer)

MERMAID_DAG = dag_source()
DAG_DRAWN = MERMAID_DAG.count('["')
assert DAG_DRAWN == 11, DAG_DRAWN
# v2: Figure 3 is hand-built SVG with tag-badge nodes; Figure 8 is a GitHub-coloured diff
import sys; sys.path.insert(0, "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/gen-c2")
from v2parts import DAG_SVG, LEGEND, DIFF
LEGEND_CSS = ""

# ---------- Figure 4 sequence, condensed to 12 messages ----------
MERMAID_SEQ = """sequenceDiagram
  autonumber
  participant A as Agent
  participant S as Script (check_render.py)
  participant R as Report file
  participant C as Chromium (Playwright)
  participant N as CDNs
  A->>S: run check_render.py
  S->>R: read_source(report)
  alt cannot read it, or no playwright
    S-->>A: FAIL, exit 1, or BLOCKED, exit 2
  end
  S->>+C: launch, then goto file URL (load, 30 s)
  C->>N: GET scripts and modules
  N-->>C: reached or failed
  S->>C: settle() 2 s quiet, facts(), reveal(), facts()
  C-->>S: diagram facts, twice
  S->>C: images(), screenshots(), probe() 15 s each
  C-->>S: error text, or env
  alt a request failed and no host answered
    S->>N: fetch package.json, no-cors, 5 s
  end
  deactivate C
  S-->>A: PASS, FAIL or BLOCKED, exit 0, 1, 2"""
SEQ_STEPS = sum(1 for l in MERMAID_SEQ.splitlines() if "->>" in l)
assert SEQ_STEPS == 12, SEQ_STEPS

# ---------- Figure 5 code ----------
CODE_LINES = [
 'def verdict(result):',
 '    """Proof of a defect beats an environment problem, which beats softer evidence.',
 '',
 '    An error diagram, a 404, or a broken image is a defect whatever else went',
 '    wrong. An unreachable CDN explains unrendered diagrams and script errors,',
 '    so those count only when the network was fine.',
 '    """',
 '    if result.get("blocked"):',
 '        return BLOCKED',
 '    diagrams = result.get("diagrams", [])',
 '    requests = result.get("requests", [])',
 '    if (any(d["status"] in DRAWN_BAD and not d.get("env") for d in diagrams)',
 '            or any(r["kind"] == "defect" for r in requests)',
 '            or result.get("broken_images") or result.get("hung")):',
 '        return FAIL',
 '    if (any(r["kind"] == "blocked" for r in requests)',
 '            or any(d.get("env") for d in diagrams) or result.get("incomplete")):',
 '        return BLOCKED',
 '    if (any(d["status"] in NOT_DRAWN for d in diagrams)',
 '            or result.get("page_errors") or result.get("console_errors")):',
 '        return FAIL',
 '    return PASS',
]
assert len(CODE_LINES) == 22
MARKS = {361:1, 365:2, 367:3, 369:4, 372:5}
code_html = []
for k, line in enumerate(CODE_LINES):
    ln = 354 + k
    m = MARKS.get(ln)
    cls = ' class="l mark"' if m else ' class="l"'
    attr = f' data-m="{m}"' if m else ''
    code_html.append(f'<span{cls}{attr}>{esc(line) if line else " "}</span>')
CODE = "".join(code_html)

# ---------- Figure 6 matrix ----------
mrows = []
prev_tier = None
for num, cond, field, verdict, tier in MATRIX:
    def cell(v):
        sym = {"PASS":"&#9679;","FAIL":"&#10005;","BLOCKED":"&#9670;"}[v]
        if verdict == "PASS*" and v == "PASS": return f'<td class="mark pass">{sym}<span class="mark-note">listed</span></td>'
        if verdict == v: return f'<td class="mark {v.lower()}">{sym}</td>'
        return '<td class="mark"></td>'
    tier_cls = f' class="tier-{tier}"' if tier else ''
    first = ' data-first="1"' if tier != prev_tier else ''
    prev_tier = tier
    mrows.append(f'<tr{tier_cls}{first}><td class="num">{num}</td><td class="txt">{esc(cond)}</td><td class="txt">{"<code>"+esc(field)+"</code>" if field else ""}</td>{cell("PASS")}{cell("FAIL")}{cell("BLOCKED")}<td class="txt tier">{tier}</td></tr>')
MATRIX_HTML = f'''<table class="data matrix" id="matrix">
<thead><tr><th class="num">#</th><th class="txt">Condition</th><th class="txt">Status or field in <code>result</code></th><th class="mark">PASS</th><th class="mark">FAIL</th><th class="mark">BLOCKED</th><th class="txt">Tier</th></tr></thead>
<tbody>
{chr(10).join(mrows)}
</tbody></table>'''

# ---------- Figure 7 timeline ----------
tl = []
for k,(h,d,subj,note,key) in enumerate(COMMITS, 1):
    cls = ' class="key"' if key else ''
    note_html = f'<span class="tl-note">{esc(note)}</span>' if note else ''
    tl.append(f'<li{cls}><span class="tl-n">{k}</span><span class="tl-date">{d}</span><span class="tl-dot"></span><span class="tl-body"><code>{h}</code> {esc(subj)}{note_html}</span></li>')
TIMELINE = '<ol class="timeline">\n' + "\n".join(tl) + '\n</ol>'

# ---------- Figure 8 bars ----------
bars = []
mx = SHARES[0][2]
for s,l,p in SHARES:
    w = p / mx * 70
    bars.append(f'<div class="bar-row"><span class="bar-label">{s}</span><div class="bar-track"><div class="bar-fill" style="width:{w:.1f}%"></div><span class="bar-num"><b>{p}%</b> <span class="bar-sub">{n(l)} lines</span></span></div></div>')
others = [s for s in SKILLS if s["skill"] not in {x[0] for x in SHARES}]
other_lines = sum(s["total_tracked_lines"] for s in others)
assert len(others) == 8 and abs(100 - sum(x[2] for x in SHARES) - 13.4) < 0.01, other_lines
w = 13.4 / mx * 70
bars.append(f'<div class="bar-row other"><span class="bar-label">8 other skills</span><div class="bar-track"><div class="bar-fill" style="width:{w:.1f}%"></div><span class="bar-num"><b>13.4%</b> <span class="bar-sub">{n(other_lines)} lines</span></span></div></div>')
BARS = "\n".join(bars)

VL_BAR = json.dumps({
  "$schema":"https://vega.github.io/schema/vega-lite/v6.json",
  "width":"container","height":400,
  "data":{"values":[{"skill":s["skill"],"lines":s["skill_md_lines"]} for s in sorted(SKILLS,key=lambda s:-s["skill_md_lines"])]},
  "layer":[
    {"mark":{"type":"bar","height":14},
     "encoding":{
       "y":{"field":"skill","type":"nominal","sort":None,"title":None,"axis":{"labelFont":"ui-monospace, Menlo, monospace","labelFontSize":11.5}},
       "x":{"field":"lines","type":"quantitative","title":"SKILL.md length (lines)","scale":{"domain":[0,182]},"axis":{"values":[0,50,100,150],"tickCount":4}},
       "color":{"condition":{"test":"datum.lines == 150","value":THEME["coral_line"]},"value":THEME["ink"]}}},
    {"mark":{"type":"text","align":"right","fontSize":11,"fontWeight":"bold","font":"ui-monospace, Menlo, monospace"},
     "encoding":{"y":{"field":"skill","type":"nominal","sort":None},"x":{"datum":180},"text":{"field":"lines"},"color":{"condition":{"test":"datum.lines == 150","value":THEME["coral_text"]},"value":THEME["muted"]}}},
    {"data":{"values":[{"budget":150}]},"mark":{"type":"rule","strokeDash":[4,3],"color":THEME["ink"],"strokeWidth":1.2},
     "encoding":{"x":{"field":"budget","type":"quantitative"}}},
    {"data":{"values":[{"budget":150,"label":"LINE_BUDGET = 150"}]},
     "mark":{"type":"text","align":"right","baseline":"bottom","dx":-4,"dy":-2,"fontSize":10,"fontWeight":"bold","color":THEME["ink"]},
     "encoding":{"x":{"field":"budget","type":"quantitative"},"y":{"value":0},"text":{"field":"label"}}}
  ]
})

VL_LINE = json.dumps({
  "$schema":"https://vega.github.io/schema/vega-lite/v6.json",
  "width":"container","height":280,
  "data":{"values":MONTHS},
  "layer":[
    {"mark":{"type":"line","point":{"size":70,"filled":True},"strokeWidth":2.5,"color":THEME["ink"]},
     "encoding":{
       "x":{"field":"month","type":"ordinal","title":"Author month (2026)","axis":{"labelAngle":0,"labelExpr":"slice(datum.value, 5)"}},
       "y":{"field":"commits","type":"quantitative","title":"Commits on main","scale":{"domain":[0,40]}}}},
    {"mark":{"type":"text","dy":-13,"fontSize":12,"fontWeight":"bold","color":THEME["ink"]},
     "encoding":{"x":{"field":"month","type":"ordinal"},"y":{"field":"commits","type":"quantitative"},"text":{"field":"commits"}}}
  ]
})

def build():
  HTML = open("/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/gen-c2/template.html").read()
  for k,v in {"@@TABLE1@@":TABLE1,"@@TABLE2@@":TABLE2,"@@DAG_SVG@@":DAG_SVG,"@@DIFF@@":DIFF,"@@SEQ@@":MERMAID_SEQ,"@@CODE@@":CODE,"@@MATRIX@@":MATRIX_HTML,"@@TIMELINE@@":TIMELINE,"@@BARS@@":BARS,"@@VL_BAR@@":VL_BAR,"@@VL_LINE@@":VL_LINE,"@@LEGEND@@":LEGEND,"@@MM_THEME@@":MM_THEME,"@@LEGEND_CSS@@":LEGEND_CSS,"@@VL_CFG@@":json.dumps(dict(font='-apple-system, "Segoe UI", Helvetica, Arial, sans-serif', mark={"color":THEME["ink"]}, axis={"labelColor":THEME["muted"],"titleColor":THEME["ink"],"gridColor":THEME["line"],"domainColor":THEME["rule"],"tickColor":THEME["rule"],"labelFontSize":11.5,"titleFontSize":11.5}, range={"category":["#102542","#d95646","#4f7f7c","#8a7766"]}, view={"stroke":None}))}.items():
    assert k in HTML, k
    HTML = HTML.replace(k, v)
  assert "@@" not in HTML
  open(OUT,"w").write(HTML)
  print("wrote", OUT, len(HTML), "bytes")

if __name__ == "__main__":
  build()
