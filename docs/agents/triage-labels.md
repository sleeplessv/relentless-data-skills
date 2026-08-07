# Triage Labels

The skills speak in terms of six canonical triage roles: five inherited from mattpocock/skills, plus `awaiting-verification`, which is ours. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |
| (none, ours only)          | `awaiting-verification` | Built, awaiting human verification    |

`awaiting-verification` is the sixth canonical role, added by this repo beyond the upstream five: the implement skills apply it (to the spec in a feature run — or, when the run has no spec, to each work-set ticket — and to the ticket in a solo run) when a PR ships with a Verification plan. Only a human removes it, once verification is done; skills never clear it, and on resume they treat it as information, not a stop.

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.
