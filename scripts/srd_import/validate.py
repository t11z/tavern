"""validate.py — Schema validation, cross-references, and baseline comparison.

Usage:
    python scripts/srd_import/validate.py --section spells
    python scripts/srd_import/validate.py --section monsters --strict

Output:
    scripts/srd_import/review/{section}.json  (validated records only)
    Validation report printed to stdout.

Requires:
    jsonschema (dev dependency)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
EXTRACTED_DIR = HERE / "extracted"
REVIEW_DIR = HERE / "review"
SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"

# ---------------------------------------------------------------------------
# Baseline data from core/ srd_tables.py for cross-checking
# ---------------------------------------------------------------------------

BASELINE_HIT_DICE: dict[str, int] = {
    "Barbarian": 12, "Fighter": 10, "Paladin": 10, "Ranger": 10,
    "Bard": 8, "Cleric": 8, "Druid": 8, "Monk": 8, "Rogue": 8,
    "Warlock": 8, "Sorcerer": 6, "Wizard": 6,
}

# CR → XP table per SRD 5.2.1
CR_XP: dict[float, int] = {
    0: 10, 0.125: 25, 0.25: 50, 0.5: 100,
    1: 200, 2: 450, 3: 700, 4: 1100, 5: 1800,
    6: 2300, 7: 3900, 8: 3900, 9: 5000, 10: 5900,
    11: 7200, 12: 8400, 13: 10000, 14: 11500, 15: 13000,
    16: 15000, 17: 18000, 18: 20000, 19: 22000, 20: 25000,
    21: 33000, 22: 41000, 23: 50000, 24: 62000, 30: 155000,
}

# Plausible HP ranges per CR band (min, max) for sanity checking
CR_HP_RANGES: dict[int, tuple[int, int]] = {
    0: (1, 20), 1: (1, 85), 2: (50, 120), 5: (100, 250),
    10: (180, 350), 15: (230, 500), 20: (300, 700), 30: (500, 1000),
}


def _require_jsonschema() -> object:
    try:
        import jsonschema  # type: ignore[import-untyped]
        return jsonschema
    except ImportError:
        print(
            "ERROR: jsonschema not installed. Run: uv sync --group dev",
            file=sys.stderr,
        )
        sys.exit(1)


def _load_schema(section: str) -> dict:
    # Try exact name first, then singular
    for name in [section, section.rstrip("s")]:
        path = SCHEMAS_DIR / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text())
    print(
        f"ERROR: Schema not found for '{section}' in {SCHEMAS_DIR}",
        file=sys.stderr,
    )
    sys.exit(1)


def validate_schema(
    records: list[dict],
    schema: dict,
    jsonschema: Any,
) -> tuple[list[dict], list[str]]:
    """Validate each record against *schema*. Return (valid_records, error_messages)."""
    validator_cls = jsonschema.Draft202012Validator
    try:
        validator_cls.check_schema(schema)
    except jsonschema.SchemaError as exc:
        return [], [f"Schema itself is invalid: {exc.message}"]

    valid: list[dict] = []
    errors: list[str] = []
    for idx, record in enumerate(records):
        name = record.get("name", f"<record #{idx}>")
        record_errors = sorted(
            validator_cls(schema).iter_errors(record),
            key=lambda e: e.path,
        )
        if record_errors:
            for err in record_errors:
                path = " → ".join(str(p) for p in err.absolute_path) or "(root)"
                errors.append(f"  [{name}] {path}: {err.message}")
        else:
            valid.append(record)
    return valid, errors


def cross_reference_spells(records: list[dict]) -> list[str]:
    """Verify spell conditions_applied reference known condition names."""
    known_conditions = {
        "blinded", "charmed", "deafened", "exhaustion", "frightened",
        "grappled", "incapacitated", "invisible", "paralyzed", "petrified",
        "poisoned", "prone", "restrained", "stunned", "unconscious",
    }
    issues: list[str] = []
    for rec in records:
        for cond in rec.get("conditions_applied") or []:
            if cond not in known_conditions:
                issues.append(
                    f"  [{rec.get('name')}] Unknown condition '{cond}'"
                )
    return issues


def cross_reference_classes(records: list[dict], section: str) -> list[str]:
    """Check that class references in spells/features point to known class names."""
    known_classes = {
        "Barbarian", "Bard", "Cleric", "Druid", "Fighter", "Monk",
        "Paladin", "Ranger", "Rogue", "Sorcerer", "Warlock", "Wizard",
    }
    issues: list[str] = []
    for rec in records:
        for cls in rec.get("classes") or []:
            if cls not in known_classes:
                issues.append(
                    f"  [{rec.get('name')}] Unknown class '{cls}'"
                )
        if section in ("class_feature", "subclass"):
            cls = rec.get("class_name", "")
            if cls and cls not in known_classes:
                issues.append(
                    f"  [{rec.get('name')}] Unknown class_name '{cls}'"
                )
    return issues


def plausibility_checks_monsters(records: list[dict]) -> list[str]:
    """Flag monsters with XP that doesn't match expected CR→XP table."""
    issues: list[str] = []
    for rec in records:
        name = rec.get("name", "<unnamed>")
        cr = rec.get("cr")
        xp = rec.get("xp")
        if cr is not None and xp is not None:
            expected_xp = CR_XP.get(float(cr))
            if expected_xp is not None and xp != expected_xp:
                issues.append(
                    f"  [{name}] XP mismatch: got {xp}, expected {expected_xp} for CR {cr}"
                )
        hp = rec.get("hp")
        if cr is not None and hp is not None:
            cr_band = max((k for k in CR_HP_RANGES if k <= float(cr)), default=0)
            lo, hi = CR_HP_RANGES[cr_band]
            if not (lo <= hp <= hi * 2):
                issues.append(
                    f"  [{name}] HP {hp} is outside plausible range for CR {cr}"
                )
    return issues


def baseline_check_classes(records: list[dict]) -> list[str]:
    """Compare extracted class hit_die against core/ baseline."""
    issues: list[str] = []
    for rec in records:
        name = rec.get("name", "")
        hit_die = rec.get("hit_die")
        baseline = BASELINE_HIT_DICE.get(name)
        if baseline is not None and hit_die != baseline:
            issues.append(
                f"  [{name}] hit_die mismatch: extracted {hit_die}, "
                f"core/srd_tables.py baseline {baseline}"
            )
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate extracted SRD JSON against schema and run plausibility checks."
    )
    parser.add_argument("--section", required=True, help="Section name (e.g. spells, monsters)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero code if any warnings are found",
    )
    args = parser.parse_args()

    section = args.section
    jsonschema = _require_jsonschema()

    input_path = EXTRACTED_DIR / f"{section}.json"
    if not input_path.exists():
        print(
            f"ERROR: Extracted data not found at {input_path}.\n"
            f"Run claude_parse.py first: "
            f"python scripts/srd_import/claude_parse.py --section {section}",
            file=sys.stderr,
        )
        sys.exit(1)

    records: list[dict] = json.loads(input_path.read_text())
    schema = _load_schema(section)

    print(f"Section:        {section}")
    print(f"Input records:  {len(records)}")
    print()

    # --- Schema validation ---
    valid_records, schema_errors = validate_schema(records, schema, jsonschema)
    print(f"Schema validation: {len(valid_records)}/{len(records)} passed")
    if schema_errors:
        print(f"  {len(schema_errors)} error(s):")
        for err in schema_errors[:50]:
            print(err)
        if len(schema_errors) > 50:
            print(f"  ... and {len(schema_errors) - 50} more errors.")

    # --- Cross-reference checks ---
    warnings: list[str] = []
    if section in ("spells", "spell"):
        warnings.extend(cross_reference_spells(valid_records))
    if section in ("spells", "spell", "class_feature", "subclass"):
        warnings.extend(cross_reference_classes(valid_records, section))
    if section in ("classes", "class"):
        warnings.extend(baseline_check_classes(valid_records))
    if section in ("monsters", "monster"):
        warnings.extend(plausibility_checks_monsters(valid_records))

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings[:50]:
            print(w)
        if len(warnings) > 50:
            print(f"  ... and {len(warnings) - 50} more warnings.")
    else:
        print("\nNo warnings.")

    # --- Write reviewed output ---
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REVIEW_DIR / f"{section}.json"
    out_path.write_text(
        json.dumps(valid_records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(valid_records)} valid record(s) → {out_path}")

    if schema_errors:
        print(f"\nFAIL: {len(schema_errors)} record(s) failed schema validation.")
        sys.exit(1)

    if args.strict and warnings:
        print(f"\nFAIL: --strict mode, {len(warnings)} warning(s) found.")
        sys.exit(1)

    print("\nOK")


if __name__ == "__main__":
    main()
