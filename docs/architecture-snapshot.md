# Architecture Snapshot

> Last updated: YYYY-MM-DD — [describe what changed]
>
> This document is maintained by Claude Code per the rules in CLAUDE.md.
> It is consumed by the architecture consultant to inform decisions without
> direct code access. Keep it factual and current. Do not add rationale —
> that belongs in ADRs.

## Module Structure

```
backend/tavern/
├── core/           # Rules Engine — SRD 5.2.1 mechanics, no LLM dependency
│   ├── ...
│   └── ...
├── dm/             # DM layer — Narrator, Context Builder, LLM provider
│   ├── ...
│   └── ...
├── api/            # FastAPI endpoints and WebSocket handlers
│   ├── ...
│   └── ...
├── models/         # SQLAlchemy models (database schema)
│   ├── ...
│   └── ...
└── ...

frontend/src/
├── ...
└── ...
```

> Update this tree when modules are added or removed. Include only
> directories, not individual files.

## Dependency Graph

```
api/ ──→ core/
api/ ──→ dm/
dm/  ──→ core/
core/ ──→ (no internal dependencies)
```

> Constraint: core/ must never import from dm/ (see ADR-0001).
> Update this section if new inter-module dependencies are introduced.

## External Dependencies

### Backend (pyproject.toml)

| Dependency | Purpose | Locked to |
|---|---|---|
| fastapi | Web framework, WebSocket support | ^x.y |
| sqlalchemy | ORM, async sessions | ^x.y |
| anthropic | Claude API (Narrator) | ^x.y |
| ... | ... | ... |

### Frontend (package.json)

| Dependency | Purpose | Locked to |
|---|---|---|
| react | UI framework | ^x.y |
| vite | Build tool | ^x.y |
| ... | ... | ... |

> Only list direct dependencies, not transitive ones.
> Update when a dependency is added or removed.

## API Surface

### REST Endpoints

| Method | Path | Purpose | Auth |
|---|---|---|---|
| ... | ... | ... | ... |

### WebSocket Events

| Event | Direction | Payload summary |
|---|---|---|
| ... | ... | ... |

> Update when endpoints or events are added, removed, or change contract.

## Database Models

| Model | Table | Key relations |
|---|---|---|
| ... | ... | ... |

> Update when models are added, removed, or schema changes.

## ADR Status

| ADR | Title | Status |
|---|---|---|
| 0000 | ADR Process and Template | Accepted |
| 0001 | ... | Accepted |
| ... | ... | ... |

> Update when an ADR is added, superseded, or deprecated.

## Known Deviations

> List any intentional deviations from accepted ADRs, with a brief
> explanation of why the deviation exists and whether it is temporary.
> Remove entries when the deviation is resolved.

| ADR | Deviation | Reason | Temporary? |
|---|---|---|---|
| — | — | — | — |

## Architecture Questions

> If Claude Code encounters a situation where an architecture decision
> seems needed but no ADR covers it, note it here instead of making the
> decision. The architecture consultant will pick these up.

| Date | Question | Context |
|---|---|---|
| — | — | — |
