# CLAUDE.md

## Project

Tavern is an open source, self-hosted, SRD 5e-compatible RPG engine with an LLM-powered narrator. Apache 2.0 licensed. Target audience: hobbyist tabletop RPG players who want a capable, always-available DM at sub-dollar session costs.

## Binding Constraints

Before starting any task, read all accepted ADRs in `docs/adr/`. They are binding architectural constraints — not background reading, not suggestions. Do not contradict an accepted ADR without including a superseding ADR in the same changeset.

## Architecture Decision Authority

Claude Code must not make architecture decisions. Architecture decisions are made by the project maintainer and documented as ADRs.

If a task requires a decision that is not covered by an existing ADR:

1. **Stop.** Do not proceed with the implementation.
2. **Explain.** State what decision is needed and why.
3. **Recommend.** Provide a brief, reasoned recommendation — but do not act on it.

A decision is architectural if reversing it later would require non-trivial rework: introducing dependencies, changing interfaces between layers, altering data models, changing the deployment topology, or choosing libraries that create lock-in.

A decision is not architectural if it operates within established patterns: implementing a new mechanic within the existing Rules Engine, adding an API endpoint that follows existing conventions, fixing bugs, adding tests, updating dependencies.

When in doubt, stop and ask. A false positive costs minutes. A false negative costs hours of rework and an untracked constraint.

## Development Conventions

### Commits

Conventional Commits format. Scope is optional but encouraged:

```
feat(core): implement opportunity attack detection
fix(dm): correct rolling summary truncation
docs: add ADR-0005 for authentication strategy
test(core): add edge cases for death saving throws
refactor(core): extract condition state machine from combat.py
chore: update dependencies
```

### Dependency Direction

`core/` must never import from `dm/`. The Rules Engine has no knowledge of the narrator, the LLM provider, or prompt construction. The dependency is strictly one-directional: `dm/` depends on `core/`, never the reverse.

### Test Requirements

All public functions in `core/` must have unit tests. Untested mechanics are unshipped mechanics — they must not be used by any other component. PRs that add or modify `core/` without corresponding tests are not mergeable.

### Code Review Priorities

When reviewing PRs:
1. Does the PR contradict an accepted ADR?
2. Does the PR introduce an architecture decision that lacks a corresponding ADR?
3. Do `core/` changes include tests?
4. Is the dependency direction maintained?

## What This File Is Not

- Not a substitute for reading the ADRs
- Not game design documentation (see `docs/game-design/`)
- Not user-facing documentation (see `README.md`)