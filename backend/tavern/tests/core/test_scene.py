"""Tests for core/scene.py — scene identifier normalisation (ADR-0017)."""

from __future__ import annotations

import pytest

from tavern.core.scene import normalise_scene_id, validate_scene_id

# ---------------------------------------------------------------------------
# normalise_scene_id — happy-path transformations
# ---------------------------------------------------------------------------


class TestNormaliseSceneId:
    def test_spaces_and_mixed_case(self) -> None:
        assert normalise_scene_id("Guard Room B") == "guard_room_b"

    def test_hyphens(self) -> None:
        assert normalise_scene_id("dungeon-level-2") == "dungeon_level_2"

    def test_consecutive_separators_collapsed(self) -> None:
        # spaces, hyphens, and combinations collapse to one underscore
        assert normalise_scene_id("room  --  B") == "room_b"

    def test_already_canonical_is_noop(self) -> None:
        assert normalise_scene_id("guard_room_b") == "guard_room_b"

    def test_leading_trailing_whitespace_stripped(self) -> None:
        assert normalise_scene_id("  town_square  ") == "town_square"

    def test_dots_stripped(self) -> None:
        # dots are non-conforming and removed
        assert normalise_scene_id("room.b") == "roomb"

    def test_slashes_stripped(self) -> None:
        assert normalise_scene_id("dungeon/level_2") == "dungeonlevel_2"

    def test_digits_preserved(self) -> None:
        assert normalise_scene_id("room_17") == "room_17"

    def test_all_uppercase(self) -> None:
        assert normalise_scene_id("TOWN SQUARE") == "town_square"

    # ---------------------------------------------------------------------------
    # Unicode stripping
    # ---------------------------------------------------------------------------

    def test_unicode_non_ascii_stripped(self) -> None:
        # Non-ASCII characters are removed entirely.
        # "große_halle" — ß is non-ASCII, gets stripped; the rest is lowercased.
        assert normalise_scene_id("große_halle") == "groe_halle"

    def test_unicode_accented_letters_stripped(self) -> None:
        # é is non-ASCII; only ASCII letters/digits/underscores survive.
        assert normalise_scene_id("château") == "chteau"

    def test_unicode_only_raises(self) -> None:
        # Input consisting solely of non-ASCII characters normalises to empty string.
        with pytest.raises(ValueError, match="normalises to an empty string"):
            normalise_scene_id("日本語")

    # ---------------------------------------------------------------------------
    # Truncation
    # ---------------------------------------------------------------------------

    def test_exactly_64_characters_passes(self) -> None:
        raw = "a" * 64
        result = normalise_scene_id(raw)
        assert len(result) == 64

    def test_65_characters_raises(self) -> None:
        raw = "a" * 65
        with pytest.raises(ValueError, match="exceeding the 64-character limit"):
            normalise_scene_id(raw)

    def test_long_name_normalised_beyond_64_raises(self) -> None:
        # After normalisation, this long string would exceed 64 chars.
        raw = (
            "a_very_long_scene_identifier_that_exceeds_the_maximum_allowed_length_of_64_characters"
        )
        with pytest.raises(ValueError, match="exceeding the 64-character limit"):
            normalise_scene_id(raw)

    # ---------------------------------------------------------------------------
    # Empty / degenerate inputs
    # ---------------------------------------------------------------------------

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="normalises to an empty string"):
            normalise_scene_id("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="normalises to an empty string"):
            normalise_scene_id("   ")

    def test_hyphens_only_raises(self) -> None:
        with pytest.raises(ValueError, match="normalises to an empty string"):
            normalise_scene_id("---")

    def test_separators_only_raises(self) -> None:
        with pytest.raises(ValueError, match="normalises to an empty string"):
            normalise_scene_id(" - - ")


# ---------------------------------------------------------------------------
# validate_scene_id
# ---------------------------------------------------------------------------


class TestValidateSceneId:
    def test_canonical_identifier_returns_true(self) -> None:
        assert validate_scene_id("guard_room_b") is True

    def test_simple_word_returns_true(self) -> None:
        assert validate_scene_id("dungeon") is True

    def test_digits_in_identifier_returns_true(self) -> None:
        assert validate_scene_id("room_17") is True

    def test_starts_with_digit_returns_true(self) -> None:
        # A digit is a valid leading character per the regex ^[a-z0-9]...
        assert validate_scene_id("1st_floor") is True

    def test_uppercase_returns_false(self) -> None:
        assert validate_scene_id("Guard_Room_B") is False

    def test_spaces_return_false(self) -> None:
        assert validate_scene_id("guard room b") is False

    def test_hyphens_return_false(self) -> None:
        assert validate_scene_id("guard-room-b") is False

    def test_empty_string_returns_false(self) -> None:
        assert validate_scene_id("") is False

    def test_leading_underscore_returns_false(self) -> None:
        assert validate_scene_id("_guard_room") is False

    def test_exactly_64_chars_returns_true(self) -> None:
        assert validate_scene_id("a" * 64) is True

    def test_65_chars_returns_false(self) -> None:
        assert validate_scene_id("a" * 65) is False

    def test_unicode_returns_false(self) -> None:
        assert validate_scene_id("große_halle") is False
