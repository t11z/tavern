# CLAUDE.md

## Project

Tavern is an open source, self-hosted, SRD 5e-compatible RPG engine with an LLM-powered narrator. Apache 2.0 licensed. Target audience: hobbyist tabletop RPG players who want a capable, always-available DM at sub-dollar session costs.

## Binding Constraints

Before starting any task, read all accepted ADRs in `docs/adr/`. They are binding architectural constraints — not background reading, not suggestions. Do not contradict an accepted ADR without including a superseding ADR in the same changeset.

### SRD Data Source (ADR-0010)
 
- Tavern's SRD data comes from `t11z/5e-database` (fork of `5e-bits/5e-database`), **not** the upstream image.
- All MongoDB collection names use the `2024-` prefix: `2024-classes`, `2024-spells`, `2024-monsters`, etc.
- **Never** use unprefixed collection names (`classes`, `spells`). These do not exist.
- **Never** use `2014-` prefixed collections. Tavern implements 2024 SRD mechanics.
- `db.levels` (attribute access) does not work for prefixed collections. Always use `db["2024-levels"]` (bracket notation).
 
### Temporary Python Constants (ADR-0010 §7)
 
- `srd_data.py` may contain Python constants as fallback for data not yet in the fork's MongoDB.
- Every constant **must** include an SRD 5.2.1 page reference in a comment.
- Constants are temporary — remove them when the fork's database includes the data.
- When adding a new constant, also add a TODO comment: `# TODO(ADR-0010): Remove when 2024-{collection} includes this data`.

## Update existing MongoDB references
 
Any existing reference to `5e-bits/5e-database` or `bagelbits/5e-database` should be updated to `t11z/5e-database` / `ghcr.io/t11z/5e-database`.
 
Any existing reference to collection names without the `2024-` prefix should be flagged as incorrect.

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

### Pull Requests

When creating PRs, apply labels that match the change. Use component labels for what is affected and type labels for what kind of work it is:

Component: `rules-engine`, `narrator`, `web-client`, `discord-bot`, `srd-data`, `world-preset`, `api`, `infrastructure`
Type: `bug`, `enhancement`, `documentation`, `adr`, `refactor`, `test`

A PR can have multiple labels. A bugfix in the Rules Engine gets `bug` + `rules-engine`. A new API endpoint gets `enhancement` + `api`. Use `gh pr edit --add-label` or set labels at PR creation time.

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

## Architecture Snapshot

The file `docs/architecture-snapshot.md` is a structured summary of the
current system architecture. It exists to bridge context between Claude Code
(which sees the codebase) and the architecture consultant (which does not).
The architecture consultant uses this document to make informed decisions
without needing direct code access.

### When to update

Update `docs/architecture-snapshot.md` as part of the same commit when any
of the following changes occur:

- A new module or package is created (new directory under `backend/tavern/`
  or `frontend/src/`)
- An external dependency is added or removed in `pyproject.toml` or
  `package.json`
- An API endpoint is added, removed, or its contract changes
- A database model is added, removed, or its schema changes
- A WebSocket event type is added or its payload changes
- The dependency direction between modules changes
- An ADR is added, superseded, or deprecated
- A deviation from an accepted ADR is introduced intentionally

Do **not** update the snapshot for: bug fixes, test additions, documentation
changes, refactors that preserve interfaces, dependency version bumps, or
code style changes.

### How to update

Follow the structure defined in `docs/architecture-snapshot.md`. Update only
the sections affected by the change. Do not rewrite unchanged sections —
unnecessary rewrites obscure what actually changed in the diff.

When updating, include a `Last updated` timestamp and reference the commit
scope (e.g., "Added `/api/v1/sessions` endpoint" or "New dependency:
`redis`").

### What not to put in the snapshot

- Implementation details (function signatures, internal algorithms)
- TODOs or speculative plans
- Opinions or recommendations — the snapshot is descriptive, not prescriptive
- Anything that belongs in an ADR

The snapshot answers "what exists and how it connects." It does not answer
"why it was built this way" (that's ADRs) or "how to use it" (that's API
docs).

## What This File Is Not

- Not a substitute for reading the ADRs
- Not game design documentation (see `docs/game-design/`)
- Not user-facing documentation (see `README.md`)
