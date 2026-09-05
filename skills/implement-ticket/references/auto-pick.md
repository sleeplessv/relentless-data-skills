# Auto-pick a ticket

Read only when no ticket number was supplied. Resolve the repository owner and name first.
Fetch every page of open ready issues before filtering and sorting by number:

```bash
gh api --paginate --slurp 'repos/<owner>/<repo>/issues?state=open&labels=ready-for-agent&per_page=100' \
  --jq 'add
        | map(select(has("pull_request") | not))
        | map(select((.assignees | length) == 0))
        | map(select([.labels[].name] | any(. == "spec" or . == "prd" or . == "needs-info" or . == "wontfix" or . == "needs-triage" or . == "blocked") | not))
        | map(select(((.body // "") | gsub("(?s)```.*?```"; "")) | test("(?im)^#{2,3} (Problem Statement|User Stories|Implementation Decisions|Testing Decisions|Out of Scope)") | not))
        | sort_by(.number) | .[0]'
```

These headings identify spec templates even where the spec itself has `ready-for-agent`
and no `spec` label. Strip fenced examples before matching. Keep line-anchored,
case-insensitive regex flags. Confirm the resulting body has concrete ticket criteria.
A command failure is a lookup error, not an empty candidate set. A successful null result
means no eligible ticket. Exclude user-declined numbers before selecting the next result.
