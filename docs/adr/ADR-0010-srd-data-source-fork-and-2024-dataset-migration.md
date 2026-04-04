# ADR-0010: SRD Data Source Fork and 2024 Dataset Migration

- **Status**: Accepted
- **Date**: 2026-04-04
- **Deciders**: [@t11z](https://github.com/t11z)
- **Scope**: `docker-compose.yml` (5e-database image reference), `backend/tavern/core/srd_data.py` (collection names), `t11z/5e-database` (new fork repository), CI/CD (GHCR image publishing)
- **Amends**: ADR-0001 (SRD Rules Engine), ADR-0003 (Technology Stack)

## Context

ADR-0001 adopted the [5e-bits/5e-database](https://github.com/5e-bits/5e-database) project (MIT license) as Tavern's SRD data source. The decision assumed that the database provided a complete SRD 5.2.1 dataset. A compatibility audit (2026-04-04) against the pinned version v4.6.3 revealed two problems:

**Problem 1 — Collection naming**: The 5e-database organises its data in `2014-`-prefixed collections (`2014-classes`, `2014-spells`, etc.) to distinguish them from the newer `2024-*` collections. Tavern's `srd_data.py` queries unprefixed collection names (`classes`, `spells`), which do not exist. All SRD lookups return `None`.

**Problem 2 — 2014 vs. 2024 data model mismatch**: Tavern's game design specifications — character creation, backgrounds, species, subclass progression — are designed around the **2024 SRD mechanics** (SRD 5.2.1). These include:

- Background Ability Score Bonuses (+2/+1 or +1/+1/+1) and Origin Feats — a 2024 mechanic that does not exist in 2014 data.
- Goliath and Orc as playable species — added in the 2024 SRD, absent from `2014-races`.
- Unified subclass selection at level 3 for all classes — 2024 rule. In 2014, Cleric, Sorcerer, and Warlock choose at level 1; Wizard at level 2.
- Four SRD backgrounds (Acolyte, Criminal, Sage, Soldier) with the 2024 structure — `2014-backgrounds` contains only Acolyte, in the 2014 schema (no ability bonuses, no Origin Feat).

The `2014-*` collections are complete for 2014 mechanics but structurally incompatible with the game Tavern is designed to be. The `2024-*` collections exist in v4.6.3 but are incomplete — the upstream project is actively building them (v4.6.0 added Magic Items and initial Subclass data for 2024; the 5e-srd-api notes that `/api/2024` is not yet available).

Continuing to build the Rules Engine against `2014-*` data would require rewriting the character creation spec, the frontend, and portions of the Rules Engine to match 2014 mechanics — undoing months of design work. Waiting for upstream to complete the `2024-*` dataset has no defined timeline. Neither option is acceptable.

## Decision

### 1. Fork 5e-database

Tavern maintains a fork at `t11z/5e-database`. The fork serves two purposes:

- **Immediately unblock Tavern development** by completing the `2024-*` collections with data from the SRD 5.2.1 PDF.
- **Contribute completed data upstream** via pull requests to `5e-bits/5e-database`, benefiting the broader community.

The fork is not a permanent divergence. It is a forward-investment in data that upstream will eventually contain. Every document added to the fork is a candidate for an upstream PR.

### 2. Switch Tavern to `2024-*` collections

`srd_data.py` switches from unprefixed collection names to `2024-*`-prefixed collections:

| Current (broken) | New |
|---|---|
| `classes` | `2024-classes` |
| `levels` | `2024-levels` |
| `races` | `2024-species` |
| `backgrounds` | `2024-backgrounds` |
| `spells` | `2024-spells` |
| `monsters` | `2024-monsters` |
| `conditions` | `2024-conditions` |
| `equipment` | `2024-equipment` |
| `feats` | `2024-feats` |
| `magic-items` | `2024-magic-items` |

Note: If the 5e-database uses a different collection name for 2024 species (e.g., `2024-species` vs. `2024-races`), Tavern follows whatever naming the fork establishes. The Tavern API continues to expose `species` regardless of the underlying collection name.

### 3. Tavern-suffixed version tags

The fork publishes Docker images to GHCR (`ghcr.io/t11z/5e-database`) with version tags that encode both the upstream base and Tavern's amendments:

```
v{upstream_version}-tavern.{patch}
```

Example progression:
- `v4.6.3-tavern.1` — first Tavern release: collection name fixes, M1-critical 2024 data (backgrounds, species, XP thresholds).
- `v4.6.3-tavern.2` — additional 2024 data (spells, monsters for levels 1-3).
- `v4.7.0-tavern.1` — rebased on upstream v4.7.0, merged with Tavern amendments.

`docker-compose.yml` pins to the Tavern-suffixed tag. The pinning discipline from ADR-0001 is preserved — upgrades remain explicit PRs verified against the test suite.

### 4. GHCR publishing via GitHub Actions

The fork repository contains a GitHub Actions workflow that builds and publishes the MongoDB Docker image to GHCR on tagged releases. No manual image building or pushing.

The same GHCR + GitHub Actions pattern will be adopted for the Tavern application image itself in a future ADR.

### 5. Data completion strategy

The fork completes the `2024-*` collections in two phases:

**Phase 1 — Manual, M1-critical (days)**: Hand-write the JSON documents needed to unblock Tavern M1. This is a small, bounded set:
- 4 Background documents (Acolyte, Criminal, Sage, Soldier) with 2024 schema (ability bonuses, Origin Feat, skill proficiencies, tool proficiency).
- 2 Species documents (Goliath, Orc) if absent from `2024-species`/`2024-races`.
- XP threshold data in level documents (if absent from 2024 level docs).
- Level documents with unified level-3 subclass selection.

These documents follow the existing 5e-database JSON schema for `2024-*` collections. Each document includes a comment referencing the SRD 5.2.1 page number for verification.

**Phase 2 — LLM-assisted ingestion pipeline (weeks)**: For the bulk of the data — ~400 spells, ~300 monsters, equipment tables, magic items — a pipeline in the fork repository extracts structured data from the SRD 5.2.1 PDF using Claude, validates against the 5e-database JSON schemas, and produces MongoDB-ready documents after human review.

The pipeline lives in the `t11z/5e-database` fork repository, not in `t11z/tavern`. It is a data-production tool, not a Tavern runtime component. Tavern never runs the pipeline — it consumes the published Docker image.

### 6. Upstream contribution

Every document added to the fork is evaluated for an upstream PR to `5e-bits/5e-database`. The upstream project is actively building 2024 data — Tavern's contributions accelerate their work rather than competing with it.

If upstream merges Tavern's contributions and releases a version with complete 2024 data, the fork's purpose is fulfilled. At that point, Tavern can evaluate switching back to the upstream image directly — see Review Triggers.

### 7. Amendment to ADR-0001 hardcoding constraint

ADR-0001 states: "SRD data must never be hardcoded in Python."

This constraint is **relaxed** for a specific, bounded case: If the upstream database (including the fork) is missing data that the Rules Engine requires and the data is stable SRD content that will not change between errata, `srd_data.py` may define Python constants as a temporary fallback. Each constant must:
- Reference the SRD 5.2.1 page number in a comment.
- Be removed when the fork's database includes the data.
- Be covered by a test that verifies consistency with the database (once the database has the data).

The primary example is the XP threshold table — 20 integers that have been identical across every edition of the SRD and are trivially verified.

This is a pragmatic concession, not a change in philosophy. The goal remains: all SRD data in MongoDB, accessed through the three-tier resolution chain. Python constants are a bridge, not a destination.

## Rationale

**Fork over waiting for upstream**: The 5e-database `2024-*` collections have no published completion timeline. The upstream API explicitly states `/api/2024` is not yet available. Tavern's M1 is blocked today. Forking unblocks development immediately while contributing back to the upstream effort.

**Fork over alternative data sources**: Open5e has some 2024 data (backgrounds, creature initiative values) but uses a completely different schema (Django/PostgreSQL, JSON fixtures). Adopting Open5e would require replacing MongoDB with PostgreSQL for SRD data, rewriting the entire data access layer, and abandoning the three-tier resolution model. The migration cost exceeds the cost of completing the 5e-database fork.

**`2024-*` collections over `2014-*` with patches**: Tavern's specs, frontend, and Rules Engine are designed around 2024 mechanics. Patching 2014 data with 2024 fields (e.g., adding `ability_bonuses` to 2014-format backgrounds) creates hybrid documents that belong to neither schema, are confusing for upstream PRs, and would need to be migrated again when the fork eventually moves to proper 2024 collections.

**GHCR over Docker Hub**: GHCR is free for public repositories, integrated with GitHub Actions, and does not require a separate Docker Hub account. The Tavern project already lives on GitHub — GHCR is the natural registry.

**Tavern-suffixed tags over independent versioning**: The `v4.6.3-tavern.1` scheme makes the upstream base version visible in every tag. This simplifies rebasing decisions ("are we still on 4.6.3 upstream?") and communicates to users that the image is a superset of a known upstream version.

**Pipeline in fork repo over pipeline in Tavern repo**: The ingestion pipeline produces data for the 5e-database, not for Tavern directly. Placing it in the fork repo keeps Tavern's repository focused on the game engine. It also means the pipeline's output (JSON documents) can be committed directly alongside the data it produces, and upstream PRs can reference the pipeline's validation as evidence of data quality.

## Alternatives Considered

**Wait for upstream 5e-bits/5e-database to complete 2024 data**: No published timeline. The upstream project is volunteer-driven and has been working on 2024 data incrementally across multiple releases. Waiting blocks Tavern development indefinitely for a milestone that may be months away. Rejected — unacceptable for a project that needs to reach M1.

**Switch to Open5e as data source**: Open5e has 2024 backgrounds and is actively maintained. However, it uses Django/PostgreSQL with a completely different document schema. Adopting it would require: replacing MongoDB with a second PostgreSQL instance (or transforming Open5e's schema into MongoDB documents), rewriting `srd_data.py` entirely, abandoning the three-tier resolution model (Open5e has no concept of Campaign Overrides or Instance Library), and adding a Django dependency or building a custom import pipeline. The architectural cost is disproportionate to the data gap. Rejected.

**Build an independent SRD database from scratch**: Extract all data from the SRD 5.2.1 PDF, define a custom MongoDB schema optimised for Tavern, and maintain independently. This eliminates all upstream dependencies but creates a permanent maintenance burden for ~1,000+ documents, sacrifices community contributions to the 5e-bits ecosystem, and duplicates work that the 5e-bits community is actively doing. Rejected — the fork achieves the same independence with a fraction of the ongoing cost.

**Use `2014-*` collections and rewrite Tavern specs to match 2014 mechanics**: Would require rewriting the Character Creation spec (backgrounds → features instead of ability bonuses, subclass levels differ per class, Half-Elf/Half-Orc instead of Goliath/Orc), the frontend (`constants.ts`), and portions of the Rules Engine. Estimated impact: 2-4 weeks of rework with no forward progress. The 2014 rules are also not what new players in 2026 expect — the 2024 PHB is the current product. Rejected.

**Hybrid approach — `2014-*` for spells/monsters, `2024-*` for backgrounds/species**: Mixing collections from different rule editions within a single Rules Engine creates a consistency hazard. Spell interactions, class features, and monster stat blocks are balanced against each other within an edition. Cross-edition mixing introduces subtle incompatibilities (e.g., a 2024 spell referencing a condition mechanic that differs from the 2014 implementation). Additionally, `srd_data.py` would need per-collection edition routing logic, adding complexity to every lookup. Rejected.

## Consequences

### What becomes easier

- Tavern M1 development is unblocked within days, not weeks or months.
- The project controls its SRD data timeline — no external dependency for shipping gameplay features.
- Upstream contributions position Tavern as a contributor to the 5e-bits ecosystem, not just a consumer. This builds community goodwill and ensures Tavern's data needs are represented in upstream schema decisions.
- The version tagging scheme (`v4.6.3-tavern.1`) makes the relationship to upstream transparent for users and contributors.
- The ingestion pipeline, once built, can be reused for future SRD versions or for other structured data extraction tasks.

### What becomes harder

- Tavern now maintains a fork of an external project. This is a permanent maintenance commitment until upstream catches up (or the fork is abandoned). Upstream merges require manual rebasing and test verification.
- The ingestion pipeline is non-trivial infrastructure: PDF parsing, LLM extraction, schema validation, human review. Building it is a multi-week effort that competes for attention with Tavern core development.
- Contributors must understand that Tavern's SRD data image is not the upstream 5e-database image. Documentation must be clear about this.
- Two GitHub repositories (`t11z/tavern` + `t11z/5e-database`) instead of one. CI/CD, issue tracking, and contributor onboarding span two repos.

### New constraints

- `docker-compose.yml` references `ghcr.io/t11z/5e-database:{tag}`, not `bagelbits/5e-database:{tag}`.
- The fork's GHCR image must be publicly accessible (GHCR default for public repos).
- `srd_data.py` uses `2024-*`-prefixed collection names. All existing code that references unprefixed collection names must be updated.
- Python constants in `srd_data.py` for missing SRD data are temporary and must include SRD page references. A CI check or code comment convention tracks which constants are awaiting database inclusion.
- The fork must not include non-SRD content. Only content from the SRD 5.2.1 (CC-BY-4.0) and the upstream 5e-database (MIT) is permitted. This ensures upstream PRs are legally clean and Tavern's Apache-2.0 license is unaffected.
- The ingestion pipeline must produce documents that conform to the 5e-database's existing JSON schema for `2024-*` collections. Tavern does not invent a new schema — it fills existing schema with data.

## Review Trigger

- If `5e-bits/5e-database` releases a version with complete `2024-*` collections (all SRD 5.2.1 entity types present and queryable via `/api/2024`), evaluate switching back to the upstream image directly and archiving the fork.
- If the fork's maintenance burden (merge conflicts, schema divergence from upstream) exceeds the cost of maintaining an independent database, evaluate decoupling from upstream entirely and owning the schema.
- If the ingestion pipeline's LLM extraction produces error rates above 5% after human review on a sample of 50+ documents, evaluate whether manual transcription is more cost-effective for the remaining data.
- If upstream adopts a fundamentally different schema for `2024-*` collections that is incompatible with Tavern's data access layer, evaluate whether to follow upstream's schema or freeze the fork at the last compatible version.
- If the GHCR image size exceeds 500MB (current 5e-database is ~100MB), evaluate whether unused collections (e.g., `2014-*` data that Tavern does not use) should be stripped from the fork's image.
