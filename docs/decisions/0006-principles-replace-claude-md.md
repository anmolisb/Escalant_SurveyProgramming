# 0006: Replace CLAUDE.md with docs/principles.md

**Date:** 2026-10-13
**Status:** Accepted
**Affects:** `CLAUDE.md` (removed), `docs/principles.md`, `README.md`, code comments

## Context

`CLAUDE.md` was the instruction file the team wrote for Claude Code at the
start of the project. By October it no longer matched the code: it described
Agents 3 to 5 as stubs not to be built, set Agent 1 Part 1 as the current
priority, and laid out folders that do not exist. The README pointed clients to
it as the authoritative project document, and about twenty code comments cited
its section numbers.

The client may not use Claude to maintain the project, so instructions written
for a coding assistant are the wrong place for the rules a maintainer needs.

## Decision

The rules that explain the code were kept, shortened and numbered in
`docs/principles.md`: record before interpreting, every value's origin,
provenance, never invent, keep what cannot be read, code before the model, a
visible failure over a silent wrong answer, the canonical specification as the
contract, never hard-coding samples, the holdout, the readiness check, and
security. Code comments now cite principles by number. The security rules are
also written out in the README. `CLAUDE.md` was deleted.

The rest (scope and planning for the August phase, a target folder layout,
development stages) described a plan that has since been carried out or
changed, and was not kept.

## Consequences

- Older records in this folder cite `CLAUDE.md` section numbers. The table at
  the end of `docs/principles.md` maps them to principles.
- Anyone on the team who relied on `CLAUDE.md` for Claude Code can recreate a
  short one from `docs/principles.md`; it is no longer part of the delivered
  repository.
