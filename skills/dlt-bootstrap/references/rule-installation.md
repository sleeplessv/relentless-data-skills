# Discover and install the house rule

Use this procedure before setup and whenever you write or update the rule.
Inspect the active agent's actual project configuration. Upstream rule placement
can change, so a neighboring file alone does not prove that a house rule is active.

## Discover existing state

Search project instruction files, including uncommitted files, for
`managed_by: dlt-bootstrap` and the `dlt house conventions` heading.
Check `dlt-house-conventions.md`, `dlt-house-conventions.mdc`, `AGENTS.md`,
and `CLAUDE.md`. A managed section has the same bookkeeping as a standalone file.

Read its source types and installed toolkit record. Compare these with the
active agent, the workbench's `.dlt/.toolkits` record, installed files, and MCP
configuration. Missing files require repair even when recorded as installed.
Use current CLI help for repair options. Preserve existing project configuration.

If several owned copies disagree, compare their settings and project additions
before choosing the active representation. Preserve unresolved differences and
report the conflict instead of appending another copy.

## Write the active representation

Fill the rule template, then use the format for the active agent:

| Agent | Output | Activation |
| --- | --- | --- |
| Claude Code | `.claude/rules/dlt-house-conventions.md` | Project rule without a path filter |
| Cursor | `.cursor/rules/dlt-house-conventions.mdc` | Add `alwaysApply: true` to frontmatter |
| Codex | Project-root `AGENTS.md` | Put the filled template inside the managed section below |

Use these stable markers when an existing project keeps the rule in `AGENTS.md`
or `CLAUDE.md`:

```markdown
<!-- BEGIN dlt-bootstrap -->
<filled rule template>
<!-- END dlt-bootstrap -->
```

Replace that section in place. Preserve all text outside it and any project-specific
rule additions. If a legacy section lacks markers, add them around the identified
house rule before updating it. If its boundary is ambiguous, resolve that boundary
without overwriting neighboring instructions. Reuse an active managed section
instead of creating a second standalone rule.

For an owned Cursor `.md` rule, preserve its content while migrating to `.mdc`
and adding the activation field. Remove only the superseded owned copy after
verifying the replacement. If the intended output is unchanged, leave it unchanged.

## Verify the written rule

- Re-read the resulting file or section. Check every bookkeeping key and filled
  placeholder, the selected destination, and the credential-safety instruction.
- Check the extension, path, and activation metadata for the active agent.
- Run discovery again. It must return the same active rule and bookkeeping
  without creating a duplicate or selecting full bootstrap.
- Inspect the diff for lost project instructions or unintended file changes.

The [Cursor rule contract](https://cursor.com/docs/rules) describes `.mdc` and
`alwaysApply`. The [workbench toolkit reference](https://raw.githubusercontent.com/dlt-hub/dlthub-ai-harness/master/TOOLKITS.md)
describes upstream transforms and installation tracking. Keep the house rule's
active representation independent of upstream's generated skill layout.
