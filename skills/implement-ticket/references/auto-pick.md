# Implement Ticket: Auto-pick Query

Disclosed from [SKILL.md](../SKILL.md) step 0, solo runs only (an orchestrated dispatch always names its ticket).

The body-heading regex is the primary spec detector. Current `to-spec` puts `ready-for-agent` on the spec itself and applies no `spec` label; the `spec`/`prd` labels are extra hints some repos carry:

```bash
gh issue list --state open --label ready-for-agent --limit 200 --json number,title,body,labels,assignees \
  --jq 'sort_by(.number)
        | map(select((.assignees | length) == 0))
        | map(select([.labels[].name] | any(. == "spec" or . == "prd" or . == "needs-info" or . == "wontfix" or . == "needs-triage" or . == "blocked") | not))
        | map(select(((.body // "") | gsub("(?s)```.*?```"; "")) | test("(?im)^#{2,3} (Problem Statement|User Stories|Implementation Decisions|Testing Decisions|Out of Scope)") | not))
        | .[0]'
```

- The inline `(?im)` flags are load-bearing: line-anchored and case-insensitive in jq; the `; "m"` flag form does not work.
- The `gsub` strips fenced code blocks so a ticket *quoting* a spec template is not excluded.
- `--limit` matters: the default 30 newest issues can miss the lowest-numbered ticket entirely.
- Assigned tickets and stop-condition labels are filtered up front so step 1 doesn't immediately stop on them.
