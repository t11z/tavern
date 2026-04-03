"""seed.py — Seed validated SRD data into the PostgreSQL database.

Usage:
    python scripts/srd_import/seed.py --section spells
    python scripts/srd_import/seed.py --section monsters --dry-run

Idempotent: re-running updates existing records (upsert by name).

Requires DATABASE_URL environment variable (default: local dev postgres).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add backend/ to sys.path so tavern package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

HERE = Path(__file__).parent
REVIEW_DIR = HERE / "review"

SECTION_MODEL_MAP: dict[str, str] = {
    "species": "SrdSpecies",
    "classes": "SrdClass",
    "class_features": "SrdClassFeature",
    "subclasses": "SrdSubclass",
    "backgrounds": "SrdBackground",
    "feats": "SrdFeat",
    "weapons": "SrdWeapon",
    "armor": "SrdArmor",
    "equipment": "SrdEquipment",
    "spells": "SrdSpell",
    "monsters": "SrdMonster",
    "monster_actions": "SrdMonsterAction",
    "conditions": "SrdCondition",
    "magic_items": "SrdMagicItem",
    "rules_tables": "SrdRulesTable",
}

# For rules_tables, the unique key is table_name, not name
UNIQUE_KEY: dict[str, str] = {
    "rules_tables": "table_name",
}


def _get_model(section: str) -> type:
    """Import and return the SQLAlchemy model class for *section*."""
    model_name = SECTION_MODEL_MAP.get(section)
    if model_name is None:
        # Try singular
        singular = section.rstrip("s")
        model_name = SECTION_MODEL_MAP.get(singular)
    if model_name is None:
        print(
            f"ERROR: No model mapping found for section '{section}'. "
            f"Valid sections: {sorted(SECTION_MODEL_MAP)}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from tavern.models.srd_data import (  # type: ignore[import]
            SrdArmor,
            SrdBackground,
            SrdClass,
            SrdClassFeature,
            SrdCondition,
            SrdEquipment,
            SrdFeat,
            SrdMagicItem,
            SrdMonster,
            SrdMonsterAction,
            SrdRulesTable,
            SrdSpecies,
            SrdSpell,
            SrdSubclass,
            SrdWeapon,
        )
    except ImportError as exc:
        print(
            f"ERROR: Could not import tavern models: {exc}\n"
            "Make sure you are running from the project root with `uv run`.",
            file=sys.stderr,
        )
        sys.exit(1)

    model_map: dict[str, type] = {
        "SrdSpecies": SrdSpecies,
        "SrdClass": SrdClass,
        "SrdClassFeature": SrdClassFeature,
        "SrdSubclass": SrdSubclass,
        "SrdBackground": SrdBackground,
        "SrdFeat": SrdFeat,
        "SrdWeapon": SrdWeapon,
        "SrdArmor": SrdArmor,
        "SrdEquipment": SrdEquipment,
        "SrdSpell": SrdSpell,
        "SrdMonster": SrdMonster,
        "SrdMonsterAction": SrdMonsterAction,
        "SrdCondition": SrdCondition,
        "SrdMagicItem": SrdMagicItem,
        "SrdRulesTable": SrdRulesTable,
    }
    return model_map[model_name]


def _upsert(session: object, model: type, records: list[dict], unique_key: str) -> tuple[int, int]:
    """Upsert *records* into the table backing *model*.

    Returns (inserted, updated) counts.
    """
    from sqlalchemy import select  # type: ignore[import]

    inserted = 0
    updated = 0
    for rec in records:
        key_value = rec.get(unique_key)
        if key_value is None:
            continue  # Skip records missing the unique key

        stmt = select(model).where(  # type: ignore[call-overload]
            getattr(model, unique_key) == key_value
        )
        existing = session.execute(stmt).scalar_one_or_none()  # type: ignore[union-attr]
        if existing is None:
            obj = model(data=rec, **{unique_key: key_value})
            session.add(obj)  # type: ignore[union-attr]
            inserted += 1
        else:
            existing.data = rec  # type: ignore[assignment]
            updated += 1
    return inserted, updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed validated SRD data into the database (idempotent upsert)."
    )
    parser.add_argument("--section", required=True, help="Section name (e.g. spells, monsters)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate input but do not write to the database",
    )
    args = parser.parse_args()

    section = args.section
    input_path = REVIEW_DIR / f"{section}.json"
    if not input_path.exists():
        print(
            f"ERROR: Reviewed data not found at {input_path}.\n"
            f"Run validate.py first: "
            f"python scripts/srd_import/validate.py --section {section}",
            file=sys.stderr,
        )
        sys.exit(1)

    records: list[dict] = json.loads(input_path.read_text())
    print(f"Section:  {section}")
    print(f"Records:  {len(records)}")

    if args.dry_run:
        print("\nDry run — no database writes.")
        return

    try:
        import asyncio
        import os

        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker
    except ImportError as exc:
        print(f"ERROR: Missing dependency: {exc}", file=sys.stderr)
        sys.exit(1)

    model = _get_model(section)
    unique_key = UNIQUE_KEY.get(section, "name")

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://tavern:tavern@localhost:5432/tavern",
    )

    async def _run() -> tuple[int, int]:
        engine = create_async_engine(database_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            async with session.begin():
                inserted, updated = _upsert(session, model, records, unique_key)
        await engine.dispose()
        return inserted, updated

    inserted, updated = asyncio.run(_run())
    print(f"Inserted: {inserted}")
    print(f"Updated:  {updated}")
    print("Done.")


if __name__ == "__main__":
    main()
