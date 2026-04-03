"""Narrative text utilities.

Provides ``split_narrative`` for slicing long Claude narrations into
Discord-safe chunks (≤ 2000 characters) while preserving sentence
boundaries.  No discord.py imports needed — this is pure text logic.
"""

from __future__ import annotations

# Split before this position so the chunk stays ≤ max_length after .strip().
_LOOK_BACK_FROM = 10


def split_narrative(text: str, max_length: int = 2000) -> list[str]:
    """Split *text* into chunks no longer than *max_length* characters.

    Splitting is done at sentence boundaries (". ") wherever possible,
    searching backwards from ``max_length - 10``.  If no sentence boundary
    is found in that window the text is hard-split at that position.

    Args:
        text:       The full narrative string to split.
        max_length: Maximum length of each returned chunk (default: 2000,
                    Discord's per-message limit).

    Returns:
        A list of one or more non-empty strings.  Each string is stripped
        of leading and trailing whitespace and has length ≤ *max_length*.
    """
    text = text.strip()
    if not text:
        return []

    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text
    search_up_to = max_length - _LOOK_BACK_FROM

    while len(remaining) > max_length:
        # Look for the last ". " before the safe split position.
        pos = remaining.rfind(". ", 0, search_up_to)

        if pos != -1:
            # Cut after the period so the period stays with the chunk.
            cut = pos + 1
        else:
            # No sentence boundary — hard split at the safe position.
            cut = search_up_to

        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks
