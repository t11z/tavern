"""extract.py — Chunk SRD PDF sections into text files for Claude processing.

Usage:
    python scripts/srd_import/extract.py --input srd/SRD_CC_v5.2.1.pdf --section spells
    python scripts/srd_import/extract.py --input srd/SRD_CC_v5.2.1.pdf --section monsters
    python scripts/srd_import/extract.py --input srd/SRD_CC_v5.2.1.pdf --section all

Output:
    scripts/srd_import/chunks/{section}_{NNN}.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# SRD 5.2.1 section → approximate page ranges
# These are best-effort estimates; validate against the actual PDF TOC.
# Page numbers are 1-indexed as reported by pypdf.
# ---------------------------------------------------------------------------

SECTION_PAGES: dict[str, tuple[int, int]] = {
    "rules_tables": (1, 27),  # Introduction, reference tables, character creation
    "classes": (28, 82),  # Class descriptions (Barbarian → Wizard)
    "backgrounds": (83, 83),  # Character Backgrounds (Acolyte, Criminal, Sage, Soldier)
    "species": (84, 86),  # Character Species (Dragonborn → Tiefling; page 84 is first entry)
    "feats": (87, 88),  # Feat Descriptions
    "equipment": (89, 106),  # Equipment: weapons, armor, adventuring gear
    "spells": (107, 175),  # Spell Descriptions (Acid Arrow → Wish)
    "conditions": (176, 203),  # Rules Glossary (conditions defined here)
    "magic_items": (204, 257),  # Magic Items
    "monsters": (258, 364),  # Monsters A–Z
}

CHUNK_SIZE = 20  # pages per chunk (override with --chunk-size)


def _require_pypdf() -> object:
    try:
        import pypdf  # type: ignore[import-untyped]

        return pypdf
    except ImportError:
        print(
            "ERROR: pypdf is not installed. Run: uv sync --group dev",
            file=sys.stderr,
        )
        sys.exit(1)


def extract_section(
    pdf_path: Path, section: str, output_dir: Path, chunk_size: int = CHUNK_SIZE
) -> list[Path]:
    """Extract pages for *section* from *pdf_path* and write chunks to *output_dir*.

    Returns the list of chunk files written.
    """
    pypdf = _require_pypdf()

    if not pdf_path.exists():
        print(
            f"ERROR: PDF not found at '{pdf_path}'.\n"
            "Download SRD_CC_v5.2.1.pdf and place it at the expected path.",
            file=sys.stderr,
        )
        sys.exit(1)

    if section not in SECTION_PAGES:
        print(
            f"ERROR: Unknown section '{section}'. Valid sections: {sorted(SECTION_PAGES)}",
            file=sys.stderr,
        )
        sys.exit(1)

    first_page, last_page = SECTION_PAGES[section]

    output_dir.mkdir(parents=True, exist_ok=True)

    reader = pypdf.PdfReader(str(pdf_path))  # type: ignore[attr-defined]
    total_pages = len(reader.pages)

    if last_page > total_pages:
        print(
            f"WARNING: Section '{section}' specifies pages up to {last_page}, "
            f"but PDF only has {total_pages} pages. Clamping to {total_pages}.",
            file=sys.stderr,
        )
        last_page = total_pages

    pages = range(first_page - 1, last_page)  # pypdf uses 0-based indexing
    chunks = [pages[i : i + chunk_size] for i in range(0, len(pages), chunk_size)]

    written: list[Path] = []
    for chunk_idx, chunk_pages in enumerate(chunks):
        text_parts: list[str] = []
        for page_num in chunk_pages:
            page = reader.pages[page_num]
            text = page.extract_text() or ""
            text_parts.append(f"--- Page {page_num + 1} ---\n{text}")

        chunk_text = "\n\n".join(text_parts)
        chunk_file = output_dir / f"{section}_{chunk_idx:03d}.txt"
        chunk_file.write_text(chunk_text, encoding="utf-8")
        print(f"  Wrote {chunk_file.name} (pages {chunk_pages[0] + 1}–{chunk_pages[-1] + 1})")
        written.append(chunk_file)

    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract SRD PDF sections into text chunks for Claude processing."
    )
    parser.add_argument(
        "--input",
        required=True,
        metavar="PDF_PATH",
        help="Path to SRD_CC_v5.2.1.pdf",
    )
    parser.add_argument(
        "--section",
        required=True,
        metavar="SECTION",
        help=f"Section to extract, or 'all'. Valid: {sorted(SECTION_PAGES)}",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        metavar="N",
        help=f"Pages per chunk (default: {CHUNK_SIZE}). Use smaller values for dense sections.",
    )
    args = parser.parse_args()

    pdf_path = Path(args.input)
    chunks_dir = Path(__file__).parent / "chunks"
    sections = list(SECTION_PAGES) if args.section == "all" else [args.section]

    for section in sections:
        print(f"\nExtracting section: {section}")
        files = extract_section(pdf_path, section, chunks_dir, chunk_size=args.chunk_size)
        print(f"  → {len(files)} chunk(s) written to {chunks_dir}")


if __name__ == "__main__":
    main()
