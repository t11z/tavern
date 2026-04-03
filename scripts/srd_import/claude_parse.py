"""claude_parse.py — Claude-assisted extraction of structured SRD data.

Usage:
    python scripts/srd_import/claude_parse.py --section spells
    python scripts/srd_import/claude_parse.py --section monsters --model claude-haiku-4-5-20251001

Output:
    scripts/srd_import/extracted/{section}.json

Requires:
    ANTHROPIC_API_KEY environment variable.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
CHUNKS_DIR = HERE / "chunks"
EXTRACTED_DIR = HERE / "extracted"
SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"

DEFAULT_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
You are a precise data extraction assistant. Your task is to extract structured \
game data from SRD 5.2.1 (System Reference Document) text and return it as a \
JSON array.

Rules:
- Extract data FAITHFULLY from the source text. Do not invent, infer beyond what \
  is written, or add data not present in the text.
- Return ONLY a JSON array of objects. No markdown fences, no commentary, no \
  explanation — just the raw JSON array.
- If a required field is not present in the text for an entry, omit that entry \
  entirely rather than guessing.
- Use the schema provided as the output format specification. Every object in the \
  array must conform to the schema.
- Field names must match the schema exactly (case-sensitive).
- String enum values must match exactly (e.g. "STR" not "Strength").
- Numeric values must be numbers, not strings.
- If you are unsure about a value, omit the optional field rather than guess.
"""


def _require_anthropic() -> object:
    try:
        import anthropic  # type: ignore[import-untyped]
        return anthropic
    except ImportError:
        print(
            "ERROR: anthropic package not installed. Run: uv sync",
            file=sys.stderr,
        )
        sys.exit(1)


def _load_schema(section: str) -> dict:
    schema_path = SCHEMAS_DIR / f"{section}.json"
    if not schema_path.exists():
        # Try without plural (e.g. 'spells' → 'spell.json')
        singular = section.rstrip("s")
        schema_path = SCHEMAS_DIR / f"{singular}.json"
    if not schema_path.exists():
        print(
            f"ERROR: Schema not found for section '{section}'. "
            f"Expected {SCHEMAS_DIR / (section + '.json')}",
            file=sys.stderr,
        )
        sys.exit(1)
    return json.loads(schema_path.read_text())


def _build_user_prompt(schema: dict, chunk_text: str) -> str:
    schema_str = json.dumps(schema, indent=2)
    return (
        f"Extract all entries from the following SRD text as a JSON array.\n\n"
        f"JSON Schema for each entry:\n```json\n{schema_str}\n```\n\n"
        f"SRD text to extract from:\n\n{chunk_text}\n\n"
        f"Return ONLY the JSON array. No explanation."
    )


def parse_chunk(
    anthropic_client: object,
    model: str,
    schema: dict,
    chunk_text: str,
    chunk_name: str,
    retry: int = 3,
) -> list[dict]:
    """Send one chunk to Claude and return extracted records."""
    for attempt in range(1, retry + 1):
        try:
            response = anthropic_client.messages.create(  # type: ignore[attr-defined]
                model=model,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": _build_user_prompt(schema, chunk_text),
                    }
                ],
            )
            raw = response.content[0].text.strip()

            # Strip accidental markdown fences
            if raw.startswith("```"):
                lines = raw.splitlines()
                raw = "\n".join(
                    line for line in lines if not line.startswith("```")
                )

            records = json.loads(raw)
            if not isinstance(records, list):
                print(
                    f"  WARNING: {chunk_name} response was not a JSON array — skipping.",
                    file=sys.stderr,
                )
                return []
            return records  # type: ignore[return-value]

        except json.JSONDecodeError as exc:
            print(
                f"  WARNING: {chunk_name} attempt {attempt}/{retry} JSON parse error: {exc}",
                file=sys.stderr,
            )
            if attempt < retry:
                time.sleep(2**attempt)
        except Exception as exc:  # noqa: BLE001
            print(
                f"  ERROR: {chunk_name} attempt {attempt}/{retry} failed: {exc}",
                file=sys.stderr,
            )
            if attempt < retry:
                time.sleep(2**attempt)
    return []


def deduplicate(records: list[dict]) -> list[dict]:
    """Remove duplicate records by name (case-insensitive), keeping first occurrence."""
    seen: set[str] = set()
    out: list[dict] = []
    for rec in records:
        key = str(rec.get("name", "")).lower()
        if key and key not in seen:
            seen.add(key)
            out.append(rec)
        elif not key:
            out.append(rec)  # Records without a name are kept as-is
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract structured SRD data from text chunks using Claude."
    )
    parser.add_argument("--section", required=True, help="Section name (e.g. spells, monsters)")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Claude model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print chunk filenames and schema but do not call Claude",
    )
    args = parser.parse_args()

    section = args.section
    chunk_files = sorted(CHUNKS_DIR.glob(f"{section}_*.txt"))
    if not chunk_files:
        print(
            f"ERROR: No chunks found for section '{section}' in {CHUNKS_DIR}.\n"
            f"Run extract.py first: python scripts/srd_import/extract.py "
            f"--input <pdf> --section {section}",
            file=sys.stderr,
        )
        sys.exit(1)

    schema = _load_schema(section)
    print(f"Section:  {section}")
    print(f"Schema:   {SCHEMAS_DIR / (section + '.json')}")
    print(f"Chunks:   {len(chunk_files)} file(s)")
    print(f"Model:    {args.model}")

    if args.dry_run:
        print("\nDry run — no API calls made.")
        for f in chunk_files:
            print(f"  {f.name}")
        return

    anthropic = _require_anthropic()
    client = anthropic.Anthropic()  # type: ignore[attr-defined]

    all_records: list[dict] = []
    for chunk_file in chunk_files:
        print(f"\nProcessing {chunk_file.name} …")
        chunk_text = chunk_file.read_text(encoding="utf-8")
        records = parse_chunk(client, args.model, schema, chunk_text, chunk_file.name)
        print(f"  Extracted {len(records)} record(s)")
        all_records.extend(records)

    all_records = deduplicate(all_records)
    print(f"\nTotal records after deduplication: {len(all_records)}")

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXTRACTED_DIR / f"{section}.json"
    out_path.write_text(json.dumps(all_records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
