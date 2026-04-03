# Contributing to Tavern

Tavern is an open source project and contributions are welcome — bug fixes, new features, rules corrections, world presets, documentation improvements, and new client integrations.

This guide covers what you need to know before contributing.

## Before You Start

### Read the Architecture Decision Records

All significant architecture decisions are documented in `docs/adr/`. Accepted ADRs are binding constraints — contributions that contradict an accepted ADR will be asked to either conform or include a superseding ADR with the pull request.

Start with [ADR-0000](adr/ADR-0000-adr-process-and-template.md) to understand the ADR process, then read the ADRs relevant to the area you want to contribute to.

### Understand the Layer Boundary

Tavern's core architectural principle is the separation between the **Rules Engine** (`backend/tavern/core/`) and the **Narrator** (`backend/tavern/dm/`). The Rules Engine handles deterministic game mechanics. The Narrator handles Claude's narrative output. The dependency is one-directional: `dm/` may import from `core/`, never the reverse.

If you're unsure which layer a change belongs to, ask: "Is this a mechanical outcome or a narrative decision?" Mechanical → `core/`. Narrative → `dm/`.

## Development Setup

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [Python 3.12+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/) (Python dependency manager)
- [Node.js 20+](https://nodejs.org/) and npm (for the web client)

### Getting Started

```bash
git clone https://github.com/t11z/tavern
cd tavern

# Start the database
docker compose -f docker-compose.dev.yml up db -d

# Install Python dependencies
uv sync

# Run database migrations
alembic upgrade head

# Start the backend
uv run uvicorn backend.tavern.main:app --reload

# In a separate terminal — install and start the web client
cd frontend
npm install
npm run dev
```

### Running Tests

```bash
# All tests
uv run pytest

# Rules Engine tests only
uv run pytest backend/tavern/tests/core/

# With coverage
uv run pytest --cov=backend/tavern/core
```

### Linting and Formatting

```bash
# Python
uv run ruff check .
uv run ruff format .
uv run mypy backend/tavern/core/

# Frontend
cd frontend
npm run lint
npm run format
```

## What to Contribute

### Good First Contributions

- **Rules Engine mechanics**: Implement missing SRD mechanics (spells, conditions, class features). Every mechanic needs unit tests.
- **SRD data corrections**: Fix errors in spell data, monster stats, or class feature tables via the import pipeline schemas.
- **World presets**: Create a new world for the community (see `docs/game-design/worlds/` for the format).
- **Documentation**: Improve ADRs, game design specs, or this guide.

### Larger Contributions

- **New client integrations**: Build a mobile app, CLI client, or alternative bot using the API.
- **Rules Engine subsystems**: Area-of-effect geometry, condition interactions, multiclass validation.
- **Narrator improvements**: Better system prompts, new tone presets, improved rolling summary compression.
- **Discord bot features**: New slash commands, improved voice handling, character sheet embeds.

### What Requires an ADR

If your contribution introduces a significant architecture decision — a new dependency, a change to the layer boundary, a new data model pattern, a deployment topology change — it needs an ADR. If you're unsure, open an issue to discuss before writing code.

See [ADR-0000](adr/ADR-0000-adr-process-and-template.md) for the full governance process.

## Pull Request Process

### Before Submitting

1. **Run the full test suite.** PRs with failing tests will not be reviewed.
2. **Run linters.** Ruff, mypy (for `core/`), and ESLint must pass.
3. **Write tests for new mechanics.** Changes to `backend/tavern/core/` without corresponding tests are not mergeable.
4. **Check ADR compliance.** Does your change contradict an accepted ADR? If so, include a superseding ADR or adjust your approach.

### PR Guidelines

- **One concern per PR.** A PR that fixes a combat bug and adds a new spell is two PRs.
- **Describe what and why.** The PR description should explain what the change does and why it's needed. Link to issues if applicable.
- **Keep it reviewable.** PRs over 500 lines are hard to review. Break large changes into smaller, sequential PRs where possible.

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
feat(core): implement concentration tracking for spells
fix(dm): correct rolling summary truncation at scene boundaries
docs: add ADR-0008 for API versioning strategy
test(core): add edge cases for multiclass spell slot calculation
refactor(core): extract condition state machine from combat.py
chore: update SQLAlchemy to 2.1
```

### Review Process

All PRs are reviewed by a maintainer. The review checks:

1. **ADR compliance** — does the PR contradict an accepted ADR?
2. **Unrecorded architecture decisions** — does the PR introduce something that should be an ADR?
3. **Test coverage** — do `core/` changes include tests?
4. **Layer boundary** — does `core/` remain independent of `dm/`?
5. **SRD compliance** — do new game mechanics match the SRD 5.2.1?

## Community World Presets

World presets are a great way to contribute without touching code. A preset is a Markdown file that defines a campaign setting — geography, factions, NPCs, world rules, and campaign hooks.

See `docs/game-design/worlds/shattered-coast.md` for the format and a complete example.

**Requirements for world presets:**
- Must not use WotC-protected intellectual property (see the SRD compliance reference in `docs/game-design/campaign-design.md`).
- Must include an Attribution section with the author and license.
- Must be mechanically compatible with the SRD 5.2.1 — no homebrew mechanics without corresponding import pipeline data.

Community presets are welcome as PRs to `docs/game-design/worlds/`.

## SRD Content Contributions

Corrections to SRD game data (spell stats, monster blocks, class features) should be made through the import pipeline schemas in `scripts/schemas/`, not by editing database seed files directly.

If you find an error in the imported SRD data:

1. Check whether the error is in the source PDF or in the extraction.
2. If it's an extraction error, fix the relevant schema or extraction logic and submit a PR.
3. If it's a source PDF error, note it in the PR description — we track SRD errata separately.

## Code of Conduct

Be respectful. Assume good intent. Give constructive feedback. We're here to build a game that people enjoy playing — the contribution process should reflect that spirit.

## Questions?

Open an issue or start a discussion. There are no stupid questions — especially about the ADR process, the layer boundary, or SRD mechanics.