# Version the whole skill once per merged pull request

Skill versions identify revisions and support updates to installed copies. Each merged pull request that changes a skill requires one version bump for that skill, covering every tracked file in its folder, including documentation. Counting documentation changes avoids deciding whether each edit affects execution and gives those changes a distinct version too.

## Version numbers and enforcement

Keep the existing `major.minor.patch` format. Every update defaults to a patch bump, with deliberate minor or major bumps allowed. Each skill's `plugin.json` remains authoritative, and the registry generator copies its version into the marketplace entry. The marketplace's own version and the nested renderer package's version remain independent.

The author or agent will run one command to bump changed skills and regenerate the registry before merging. CI will reject changes that require a bump but do not include one. This keeps version changes in the reviewed pull request without requiring a bot to edit it.

## Concurrent changes

An updated skill must have a version higher than its version on the current `main`. If two pull requests choose `0.2.1` and the first merges, the second must advance to `0.2.2`. Re-running the bump command preserves an already sufficient bump, so repeated runs do not keep increasing versions.

## Skill lifecycle

- Existing skills keep their current versions until changed.
- New skills start at `0.1.0`.
- Deleting a skill removes its registry entry and requires no version bump.
- Renaming a skill creates a new identity starting at `0.1.0`.
- Reverting content produces a newer version. It never restores an older version number.

## Merge enforcement

Require pull requests into `main`, a passing version check, and an up-to-date branch. These rules prevent direct pushes and merges that would bypass version validation. A CI job alone would only report some violations after they reached `main`.

## Update delivery

Version bumps make changed skills eligible for version-based client updates. They do not update installed copies automatically. [Claude Code uses declared versions to detect plugin updates](https://code.claude.com/docs/en/plugin-marketplaces#version-resolution-and-release-channels), and users control [marketplace auto-update settings](https://code.claude.com/docs/en/discover-plugins#configure-auto-updates).

## Status

Accepted. The implementation uses `scripts/skill_versions.py` and the
`skill-version-check` CI job. The job also checks registry consistency so the
required status covers both the authoritative version and its published entry.
