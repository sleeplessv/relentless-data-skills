---
name: implement-backlog
argument-hint: "[goal | ticket#...] [stop at ready]"
disable-model-invocation: true
description: "Work a ticket backlog as chief of staff: each ticket goes to one ticket owner subagent that runs implement-ticket from claim to merged PR, so the main thread only orchestrates."
---

# Implement backlog

Run this session as chief of staff over a ticket backlog. Each ticket goes to one **ticket
owner**: a background subagent that coordinates a whole solo `implement-ticket` run for that
ticket in its own thread and reports once. The main thread triages, picks what runs next,
carries the owners' questions to the user, and keeps the wiki.

The argument is the goal, or the ticket numbers to work. With none, the goal is to triage and
implement the repository's open tickets.

## Start

1. Locate the installed roots of `chief-of-staff` and `implement-ticket` on disk, following
   symlinks (`find -L`). Both are user-only, so the skill catalog lists neither. If one is
   missing, report it with the install command from this skill's README and stop.
2. Read `chief-of-staff`'s `SKILL.md` and follow it for the whole session, with the goal above.
   One of its procedures changes: tickets are implemented by ticket owners, where it names
   `implement-spec`. A large chunk of work still becomes a spec and tickets first.
3. Hold `implement-ticket`'s root path and nothing else of it. Its text addresses a
   coordinator, and a main thread that reads it starts coordinating each ticket's workers and
   reviews itself. The owner reads it.
4. Keep every file the session writes in `.agents/` at the main checkout's root: the wiki in
   `.agents/wiki/`, each ticket's run directory in `.agents/runs/<ticket>/`. This replaces
   `chief-of-staff`'s search for a shared wiki and its question about where to keep one, so
   never ask the user where to store anything. Use the wiki already there, or create it. When
   git does not ignore `.agents/`, add it to `.git/info/exclude`, never to `.gitignore`.

Done when the wiki is located and the first frontier is listed.

## Authority

Invoking this skill grants each dispatched ticket what invoking `implement-ticket` grants, and
also merging its PR under [Merge](references/ticket-owner.md#merge). `stop at ready` in the
argument, or said later, withholds merging: owners then end at a ready PR. Every other limit
`implement-ticket` sets still needs the user's go-ahead.

## Loop

Repeat until the goal is met. A frontier that is empty with no owner in flight ends the loop:
tell the user which tickets remain and what blocks each, or that none are open.

- **Triage.** A subagent works the issues awaiting triage with the installed `triage` skill,
  read by path. Without that skill, say so and work only tickets already marked ready. Ticket
  numbers in the argument skip triage.
- **Frontier.** A subagent lists every eligible ticket: the query in `implement-ticket`'s
  `references/auto-pick.md` without its final single pick, each ticket's open blockers, and
  the paths it expects to touch. The frontier is the eligible tickets with no owner in
  flight and no open blocker. Explicit ticket numbers in the argument are the work-set.
- **Dispatch.** One owner per frontier ticket, three at once unless the user sets another
  number: an owner runs four or five agents of its own at its check wave, and the harness
  caps the total. Two tickets that touch the same paths run one after the other. The message
  follows [Dispatch](#dispatch).
- **Answer.** An owner that returns early carries a decision for the user. Put it to the user
  as the owner wrote it, then resume that owner with the answer, so the ticket stays in its
  thread. Dispatch a fresh owner, pointed at the run directory, only when the first cannot be
  resumed.
- **Report.** Check an owner's final report against the PR and the ticket, then record it in
  the wiki, its lessons on the owner notes page. Offer the user the follow-up issues owners
  drafted together, when the loop ends.
- **Merge fallback.** An owner that reports `ready, merge denied` leaves the merge to you:
  run [Merge](references/ticket-owner.md#merge) on its `final_sha` from the main checkout.
- **No nesting.** An owner that reports `nested dispatch unavailable` has changed nothing.
  Read `implement-ticket` then, and coordinate that ticket from the main thread as a solo
  run; tell the user the session lost its per-ticket threads.

## Dispatch

Send each owner as a background general-purpose worker, with no model unless the user named
one, so `implement-ticket`'s model classes resolve as they do in a solo run. The message is
pointers and this ticket's facts:

- The absolute path of this skill's `references/ticket-owner.md`, to read first.
- The `implement-ticket` root from Start.
- The repository (`<owner>/<repo>`), its main checkout path, and the ticket number.
- `RUN_DIR`: the absolute path of `.agents/runs/<ticket>/` in the main checkout.
- A resource block no other owner holds, such as a port range, and any limit on heavy
  checks running at once on this machine.
- Owners in flight, with the paths their tickets touch.
- Whether merging is granted.
- The wiki pages that bear on the ticket, and the owner notes page below.

Rules a repository teaches the run, such as a command that must not run or a check that is
flaky under load, go on one wiki page of owner notes as dated entries, and every dispatch
points at it. The dispatch message carries no rule of its own.
