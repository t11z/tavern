"""Rolling summary module — turn line construction and budget enforcement.

The rolling summary is the 500-token window of recent events that Claude
receives as context on every turn (ADR-0002, component 4).  Its quality
directly affects narrative coherence: a vague summary ("action completed")
gives Claude nothing to work with; a well-structured one preserves names,
mechanics, and story beats across the 2,400-token context window.

Two public functions:

    build_turn_summary_input()
        Constructs one structured line from the components of a completed turn.
        The line is passed to Narrator.update_summary() as a recent_turns entry.

    trim_summary()
        Enforces the 500-token hard limit on any summary text by dropping the
        oldest entries (newline-delimited for accumulated lines, sentence-
        delimited for LLM-compressed prose).

Token estimation uses the same heuristic as context_builder.estimate_tokens():
    tokens ≈ len(text) // 4
"""

from __future__ import annotations

import re

# Mirror of context_builder._BUDGET_SUMMARY — kept local to avoid circular import.
_BUDGET_SUMMARY_TOKENS = 500

# ~4 chars/token × 500 tokens = ~2000 chars before trimming is needed.
_BUDGET_SUMMARY_CHARS = _BUDGET_SUMMARY_TOKENS * 4

# Action is truncated to this many words to keep lines compact.
_MAX_ACTION_WORDS = 50

# Narrative excerpt: first N sentences, up to this many characters.
_MAX_EXCERPT_SENTENCES = 2
_MAX_EXCERPT_CHARS = 140

# Sentence-boundary splitter (conservative — split on .  !  ? followed by whitespace).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _truncate_words(text: str, max_words: int) -> str:
    """Return *text* truncated to *max_words* words, appending '…' if trimmed."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"


def _first_sentences(text: str, max_sentences: int, max_chars: int) -> str:
    """Extract the first *max_sentences* sentences from *text*.

    Caps the result at *max_chars* characters, breaking at a word boundary
    and appending '…' if the cap is reached before the sentence limit.
    """
    text = text.strip()
    if not text:
        return ""

    sentences = _SENTENCE_SPLIT_RE.split(text)
    selected = " ".join(sentences[:max_sentences]).strip()

    if len(selected) > max_chars:
        # Break at a word boundary.
        truncated = selected[:max_chars].rsplit(" ", 1)[0]
        selected = truncated.rstrip(".,;:") + "…"

    return selected


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: len(text) // 4 (mirrors context_builder)."""
    return len(text) // 4


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_turn_summary_input(
    character_name: str,
    player_action: str,
    rules_result: str | None,
    narrative_excerpt: str,
    sequence_number: int,
) -> str:
    """Build a structured turn line for rolling summary compression.

    Produces a concise but information-dense line like::

        Turn 5: Kael attacked Goblin A with longsword — Attack roll 18 — hit!
        Deals 14 Slashing damage. Goblin A fell. The party moved deeper into
        the crypt.

    The line is intended to be passed to ``Narrator.update_summary()`` as a
    ``recent_turns`` entry.  Haiku compresses it into the rolling summary.

    Args:
        character_name:   Character who acted this turn.
        player_action:    Verbatim player input, truncated to 50 words.
        rules_result:     Human-readable Rules Engine output, e.g.
                          "Attack roll 18 — hit! Deals 14 Slashing damage."
                          ``None`` for non-mechanical actions.
        narrative_excerpt: Full narrative text from the Narrator.  Only the
                          first 1-2 sentences are included to capture the
                          story beat without bloating the line.
        sequence_number:  Global turn counter (used as the Turn N: prefix).

    Returns:
        A single-line string, typically 60-200 characters.
    """
    action_short = _truncate_words(player_action, _MAX_ACTION_WORDS)

    parts: list[str] = [f"Turn {sequence_number}: {character_name} — {action_short}"]

    if rules_result:
        # Strip trailing period so the join reads cleanly.
        parts.append(rules_result.rstrip("."))

    excerpt = _first_sentences(
        narrative_excerpt,
        max_sentences=_MAX_EXCERPT_SENTENCES,
        max_chars=_MAX_EXCERPT_CHARS,
    )
    if excerpt:
        parts.append(excerpt)

    return ". ".join(parts) + "."


def trim_summary(summary: str, max_tokens: int = _BUDGET_SUMMARY_TOKENS) -> tuple[str, dict]:
    """Trim *summary* to fit within *max_tokens* by dropping the oldest entries.

    Splitting strategy:
    1. Prefer newline-delimited entries (accumulated turn lines, not yet
       LLM-compressed).
    2. Fall back to sentence-delimited splitting when the text is a prose
       block (e.g., the output of ``Narrator.update_summary()``).

    Entries are dropped from the front (oldest first) until the token
    estimate is within budget.  If the summary cannot be reduced below the
    budget without removing everything, the most-recent single entry is
    returned as a last resort.

    Args:
        summary:    Rolling summary text (may be multi-line or prose).
        max_tokens: Hard token cap (default: 500, matching _BUDGET_SUMMARY).

    Returns:
        A tuple of (trimmed_text, diagnostic_dict).

        trimmed_text is the summary text that fits within the token budget.

        diagnostic_dict keys:
            before_tokens (int): estimated token count before trimming.
            after_tokens (int): estimated token count after trimming.
    """
    before_tokens = _estimate_tokens(summary)

    if not summary:
        return summary, {"before_tokens": 0, "after_tokens": 0}

    if before_tokens <= max_tokens:
        return summary, {"before_tokens": before_tokens, "after_tokens": before_tokens}

    # Prefer newline-delimited entries (multi-line accumulated format).
    entries = [e.strip() for e in summary.split("\n") if e.strip()]

    # Fall back to sentence splitting if the text is a prose block.
    if len(entries) <= 1:
        entries = [s.strip() for s in _SENTENCE_SPLIT_RE.split(summary.strip()) if s.strip()]

    # Drop oldest entries until within budget.
    while len(entries) > 1 and _estimate_tokens("\n".join(entries)) > max_tokens:
        entries = entries[1:]

    result = "\n".join(entries)
    after_tokens = _estimate_tokens(result)
    return result, {"before_tokens": before_tokens, "after_tokens": after_tokens}
