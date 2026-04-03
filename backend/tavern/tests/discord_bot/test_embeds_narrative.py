"""Tests for embeds/narrative.py — split_narrative."""

from __future__ import annotations

from tavern.discord_bot.embeds.narrative import split_narrative

# ---------------------------------------------------------------------------
# Basic cases
# ---------------------------------------------------------------------------


def test_short_text_returned_as_single_chunk() -> None:
    result = split_narrative("Hello, world!")
    assert result == ["Hello, world!"]


def test_empty_string_returns_empty_list() -> None:
    assert split_narrative("") == []


def test_whitespace_only_returns_empty_list() -> None:
    assert split_narrative("   \n  ") == []


def test_text_exactly_at_max_length_is_single_chunk() -> None:
    text = "x" * 2000
    result = split_narrative(text)
    assert len(result) == 1
    assert result[0] == text


def test_text_one_over_max_length_splits() -> None:
    text = "x" * 2001
    result = split_narrative(text)
    assert len(result) == 2
    for chunk in result:
        assert len(chunk) <= 2000


# ---------------------------------------------------------------------------
# Sentence boundary splitting
# ---------------------------------------------------------------------------


def test_splits_at_sentence_boundary() -> None:
    # Put a ". " near the 1990 mark so it is chosen as the split point.
    part1 = "A" * 1800 + ". "
    part2 = "B" * 300
    text = part1 + part2
    assert len(text) > 2000

    result = split_narrative(text)
    assert len(result) == 2
    # First chunk ends with the sentence (period only, no trailing space after strip).
    assert result[0].endswith(".")
    # Second chunk starts with B.
    assert result[1].startswith("B")


def test_splits_at_last_sentence_boundary_before_limit() -> None:
    # Multiple sentences within the first 2000 chars; the last ". " before
    # position 1990 should be chosen.
    sentences = [f"Sentence number {i:04d}. " for i in range(100)]
    text = "".join(sentences)
    assert len(text) > 2000

    result = split_narrative(text)
    for chunk in result:
        assert len(chunk) <= 2000
    # Reconstruct and verify no content is lost (modulo whitespace normalisation).
    rejoined = " ".join(result)
    # All original sentences are present somewhere in the output.
    assert "Sentence number 0000" in rejoined
    assert "Sentence number 0099" in rejoined


def test_hard_split_when_no_sentence_boundary() -> None:
    # A single long word with no periods.
    text = "A" * 5000
    result = split_narrative(text)
    for chunk in result:
        assert len(chunk) <= 2000
    assert "".join(result) == text


# ---------------------------------------------------------------------------
# Custom max_length
# ---------------------------------------------------------------------------


def test_custom_max_length() -> None:
    text = "Hello. World. Foo. Bar."
    # Small max_length to force splitting.
    result = split_narrative(text, max_length=12)
    for chunk in result:
        assert len(chunk) <= 12


def test_custom_max_length_single_sentence() -> None:
    text = "Hello."
    result = split_narrative(text, max_length=100)
    assert result == ["Hello."]


# ---------------------------------------------------------------------------
# Whitespace trimming
# ---------------------------------------------------------------------------


def test_leading_trailing_whitespace_stripped_from_input() -> None:
    result = split_narrative("  Hello, world!  ")
    assert result == ["Hello, world!"]


def test_chunks_are_stripped() -> None:
    part1 = "A" * 1800 + ".   "
    part2 = "   B" * 50
    text = part1 + part2
    result = split_narrative(text)
    for chunk in result:
        assert chunk == chunk.strip()


# ---------------------------------------------------------------------------
# Multiple splits (text > 2 × max_length)
# ---------------------------------------------------------------------------


def test_three_way_split() -> None:
    # Build a text that needs at least 3 chunks.
    sentence = "The quick brown fox jumps over the lazy dog. "
    text = sentence * 200  # well over 6000 chars
    result = split_narrative(text)
    assert len(result) >= 3
    for chunk in result:
        assert len(chunk) <= 2000


def test_all_content_preserved_after_split() -> None:
    """Verify no characters are silently dropped between chunks."""
    # Use a repetitive pattern where we can check total meaningful length.
    part = "Word "
    text = part * 1000  # 5000 chars
    result = split_narrative(text)
    total = sum(len(c) for c in result)
    # Allow for some whitespace to be stripped at boundaries.
    assert total >= len(text) - len(result) * 2
