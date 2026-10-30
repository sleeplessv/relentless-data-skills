# Data copied from content.md, commit a590a62. Nothing invented.
SKILLS = [
 ("candidate-to-spec","0.1.1",129,3,0,True,2,728,6),
 ("dbt-runner","0.1.8",134,3,1,False,15,1064,7),
 ("dlt-bootstrap","0.1.1",133,3,0,False,10,388,6),
 ("fabric-lineage-dag","0.1.2",89,3,17,False,6,3635,23),
 ("gh-weekly-report","0.1.2",119,1,2,True,8,1060,6),
 ("implement-feature","0.2.5",142,1,0,True,21,513,4),
 ("implement-ticket","0.2.8",150,4,0,True,22,538,7),
 ("metabase","0.1.0",150,3,1,False,4,1803,7),
 ("orchestrator-mode","0.5.4",147,1,0,False,25,306,4),
 ("prefect","0.2.2",150,0,0,False,9,241,3),
 ("qualify-delegation","0.1.0",123,0,0,False,1,183,3),
 ("review-pbi-diff","0.1.3",150,1,2,True,8,1927,6),
 ("ship","0.1.7",148,0,0,True,17,260,3),
 ("smart-git-commit","0.1.3",114,0,0,False,13,183,3),
 ("snowman","0.1.4",143,3,1,False,23,1601,7),
 ("statusline","0.5.0",64,0,1,True,10,1038,8),
 ("student-mode","0.2.0",150,0,0,True,4,215,3),
 ("visual-report","0.1.3",56,2,1,False,12,1318,6),
]
NODES = [
 ("candidate-to-spec","candidate-to-spec","skill",4),
 ("dbt-runner","dbt-runner","skill",3),
 ("dlt-bootstrap","dlt-bootstrap","skill",5),
 ("fabric-lineage-dag","fabric-lineage-dag","skill",2),
 ("gh-weekly-report","gh-weekly-report","skill",3),
 ("implement-feature","implement-feature","skill",5),
 ("implement-ticket","implement-ticket","skill",3),
 ("metabase","metabase","skill",2),
 ("orchestrator-mode","orchestrator-mode","skill",4),
 ("prefect","prefect","skill",2),
 ("qualify-delegation","qualify-delegation","skill",1),
 ("review-pbi-diff","review-pbi-diff","skill",3),
 ("ship","ship","skill",5),
 ("smart-git-commit","smart-git-commit","skill",3),
 ("snowman","snowman","skill",3),
 ("statusline","statusline","skill",2),
 ("student-mode","student-mode","skill",1),
 ("visual-report","visual-report","skill",4),
 ("lint_skill","scripts/lint_skill.py","root-script",21),
 ("sync_registry","scripts/sync_registry.py","root-script",5),
 ("skill_versions","scripts/skill_versions.py","root-script",5),
 ("check_doc_urls","scripts/check_doc_urls.py","root-script",2),
 ("check_sh","scripts/check.sh","root-script",4),
 ("statusline_shots","scripts/statusline_screenshots.py","root-script",1),
 ("plugin_json","skills/*/plugin.json (18 manifests)","manifest",2),
 ("ci_version","CI job skill-version-check","ci",2),
 ("ci_tests","CI job tests (py3.9 + 3.13)","ci",13),
 ("ci_lint","CI job skill-lint","ci",1),
 ("ci_plugin","CI job plugin-validate","ci",0),
 ("ci_urls","CI job doc-url-liveness","ci",1),
 ("test_candidate_to_spec_commands","tests/test_candidate_to_spec_commands.py","test",3),
 ("test_dbt_runner","tests/test_dbt_runner.py","test",2),
 ("test_dlt_bootstrap","tests/test_dlt_bootstrap.py","test",2),
 ("test_gh_weekly_report","tests/test_gh_weekly_report.py","test",3),
 ("test_lint_skill","tests/test_lint_skill.py","test",2),
 ("test_metabase","tests/test_metabase.py","test",2),
 ("test_review_pbi_diff","tests/test_review_pbi_diff.py","test",3),
 ("test_skill_git_sequences","tests/test_skill_git_sequences.py","test",5),
 ("test_skill_versions","tests/test_skill_versions.py","test",2),
 ("test_snowman","tests/test_snowman.py","test",2),
 ("test_statusline","tests/test_statusline.py","test",2),
 ("test_sync_registry","tests/test_sync_registry.py","test",2),
 ("test_visual_report","tests/test_visual_report.py","test",2),
 ("check_render","visual-report/scripts/check_render.py","skill-script",2),
 ("snowman_py","snowman/scripts/snowman.py","skill-script",2),
 ("mb_py","metabase/scripts/mb.py","skill-script",2),
 ("preflight_py","dbt-runner/scripts/preflight.py","skill-script",2),
 ("extract_changes","review-pbi-diff/scripts/extract_changes.py","skill-script",2),
 ("check_artifact","review-pbi-diff/scripts/check_artifact.py","skill-script",2),
 ("statusline_sh","statusline/scripts/statusline.sh","skill-script",3),
 ("collect_py","gh-weekly-report/scripts/collect.py","skill-script",2),
 ("render_py","gh-weekly-report/scripts/render.py","skill-script",2),
 ("fld_scripts","fabric-lineage-dag/scripts/ (17 files)","skill-script",1),
 ("html_report","visual-report/references/HTML-REPORT.md","reference",1),
 ("visual_language","visual-report/references/VISUAL-LANGUAGE.md","reference",1),
 ("if_reference","implement-feature/references/reference.md","reference",2),
]
EDGES = """candidate-to-spec implement-feature
candidate-to-spec orchestrator-mode
dbt-runner ship
dlt-bootstrap prefect
dlt-bootstrap ship
dlt-bootstrap snowman
implement-feature implement-ticket
implement-feature orchestrator-mode
implement-ticket orchestrator-mode
ship smart-git-commit
dbt-runner preflight_py
metabase mb_py
review-pbi-diff extract_changes
review-pbi-diff check_artifact
gh-weekly-report collect_py
gh-weekly-report render_py
fabric-lineage-dag fld_scripts
statusline statusline_sh
snowman snowman_py
visual-report check_render
visual-report html_report
visual-report visual_language
implement-feature if_reference
test_lint_skill lint_skill
test_skill_versions skill_versions
test_sync_registry sync_registry
test_dbt_runner preflight_py
test_metabase mb_py
test_review_pbi_diff extract_changes
test_review_pbi_diff check_artifact
test_snowman snowman_py
test_statusline statusline_sh
test_visual_report check_render
test_gh_weekly_report collect_py
test_gh_weekly_report render_py
test_dlt_bootstrap dlt-bootstrap
test_candidate_to_spec_commands candidate-to-spec
test_candidate_to_spec_commands test_skill_git_sequences
test_skill_git_sequences if_reference
test_skill_git_sequences ship
test_skill_git_sequences smart-git-commit
ci_version skill_versions
ci_version sync_registry
ci_lint lint_skill
ci_urls check_doc_urls
ci_tests test_candidate_to_spec_commands
ci_tests test_dbt_runner
ci_tests test_dlt_bootstrap
ci_tests test_gh_weekly_report
ci_tests test_lint_skill
ci_tests test_metabase
ci_tests test_review_pbi_diff
ci_tests test_skill_git_sequences
ci_tests test_skill_versions
ci_tests test_snowman
ci_tests test_statusline
ci_tests test_sync_registry
ci_tests test_visual_report
check_sh lint_skill
check_sh sync_registry
check_sh skill_versions
check_sh check_doc_urls
skill_versions sync_registry
skill_versions plugin_json
sync_registry plugin_json
statusline_shots statusline_sh
lint_skill candidate-to-spec
lint_skill dbt-runner
lint_skill dlt-bootstrap
lint_skill fabric-lineage-dag
lint_skill gh-weekly-report
lint_skill implement-feature
lint_skill implement-ticket
lint_skill metabase
lint_skill orchestrator-mode
lint_skill prefect
lint_skill qualify-delegation
lint_skill review-pbi-diff
lint_skill ship
lint_skill smart-git-commit
lint_skill snowman
lint_skill statusline
lint_skill student-mode
lint_skill visual-report""".split("\n")
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
 ("088a29f","2026-10-03","feat(skills): add prove-it-works checks (#75)","adds scripts/check_render.py (+985) and tests/test_visual_report.py (+345); 16 files, +2,605 and -41",True),
 ("dc788de","2026-10-18","chore: migrate agent config to GLOSSARY.md and AGENTS.md (#91)","",False),
]
SHARES = [("fabric-lineage-dag",3635,21.4),("review-pbi-diff",1927,11.3),("metabase",1803,10.6),("snowman",1601,9.4),("visual-report",1318,7.8),("dbt-runner",1064,6.3),("gh-weekly-report",1060,6.2),("statusline",1038,6.1),("candidate-to-spec",728,4.3),("implement-ticket",538,3.2)]
