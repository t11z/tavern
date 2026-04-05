"""Tests for dm/gm_signals.py — parse_gm_signals() and GMSignals dataclass.

Covers the suggested_actions field introduced in ADR-0015.
"""

from __future__ import annotations

import json

from tavern.dm.gm_signals import GM_SIGNALS_DELIMITER, GMSignals, parse_gm_signals, safe_default

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raw(payload: dict) -> str:
    """Wrap a payload dict in a minimal narrator output with the GM_SIGNALS delimiter."""
    return f"Narrative prose here.\n{GM_SIGNALS_DELIMITER}\n{json.dumps(payload)}"


# ---------------------------------------------------------------------------
# suggested_actions — happy path
# ---------------------------------------------------------------------------


class TestSuggestedActionsValid:
    def test_three_valid_entries_parsed(self):
        suggestions = [
            "Slip through the gap before the guards arrive",
            "Demand the harbormaster explain herself",
            "Throw your cloak over the lantern and run",
        ]
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": suggestions,
            }
        )
        result = parse_gm_signals(raw)
        assert result.suggested_actions == suggestions

    def test_one_valid_entry_parsed(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": ["Search the room for hidden passages"],
            }
        )
        result = parse_gm_signals(raw)
        assert result.suggested_actions == ["Search the room for hidden passages"]

    def test_empty_list_parsed(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
            }
        )
        result = parse_gm_signals(raw)
        assert result.suggested_actions == []


# ---------------------------------------------------------------------------
# suggested_actions — truncation
# ---------------------------------------------------------------------------


class TestSuggestedActionsTruncation:
    def test_five_entries_truncated_to_three(self):
        suggestions = [
            "Slip through the gap before the guards arrive",
            "Demand the harbormaster explain herself",
            "Throw your cloak over the lantern and run",
            "This fourth suggestion should be dropped",
            "This fifth suggestion should also be dropped",
        ]
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": suggestions,
            }
        )
        result = parse_gm_signals(raw)
        assert len(result.suggested_actions) == 3
        assert result.suggested_actions == suggestions[:3]

    def test_entry_exceeding_80_chars_truncated(self):
        long_entry = "A" * 100  # 100 chars — exceeds 80-char limit
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [long_entry],
            }
        )
        result = parse_gm_signals(raw)
        assert len(result.suggested_actions) == 1
        assert result.suggested_actions[0] == long_entry[:80]

    def test_entry_at_exactly_80_chars_not_truncated(self):
        exact_entry = "B" * 80
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [exact_entry],
            }
        )
        result = parse_gm_signals(raw)
        assert result.suggested_actions == [exact_entry]

    def test_four_entries_with_long_one_truncates_both(self):
        suggestions = [
            "Slip through the gap before the guards arrive",
            "Demand the harbormaster explain herself",
            "Throw your cloak over the lantern and run",
            "C" * 90,  # Fourth entry — dropped entirely by count limit
        ]
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": suggestions,
            }
        )
        result = parse_gm_signals(raw)
        assert len(result.suggested_actions) == 3
        assert result.suggested_actions == suggestions[:3]


# ---------------------------------------------------------------------------
# suggested_actions — missing / malformed field
# ---------------------------------------------------------------------------


class TestSuggestedActionsMissing:
    def test_field_missing_defaults_to_empty_list(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                # No suggested_actions key
            }
        )
        result = parse_gm_signals(raw)
        assert result.suggested_actions == []

    def test_field_is_string_defaults_to_empty_list(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": "not a list",
            }
        )
        result = parse_gm_signals(raw)
        assert result.suggested_actions == []

    def test_field_is_dict_defaults_to_empty_list(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": {"action": "something"},
            }
        )
        result = parse_gm_signals(raw)
        assert result.suggested_actions == []

    def test_field_is_integer_defaults_to_empty_list(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": 42,
            }
        )
        result = parse_gm_signals(raw)
        assert result.suggested_actions == []

    def test_field_is_null_defaults_to_empty_list(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": None,
            }
        )
        result = parse_gm_signals(raw)
        assert result.suggested_actions == []

    def test_non_string_items_skipped(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [42, "Valid suggestion text here", None],
            }
        )
        result = parse_gm_signals(raw)
        assert result.suggested_actions == ["Valid suggestion text here"]

    def test_empty_string_items_skipped(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": ["", "Valid suggestion", "   "],
            }
        )
        result = parse_gm_signals(raw)
        assert result.suggested_actions == ["Valid suggestion"]


# ---------------------------------------------------------------------------
# safe_default
# ---------------------------------------------------------------------------


class TestSafeDefault:
    def test_safe_default_has_empty_suggested_actions(self):
        result = safe_default()
        assert isinstance(result, GMSignals)
        assert result.suggested_actions == []

    def test_safe_default_suggested_actions_is_list(self):
        result = safe_default()
        assert isinstance(result.suggested_actions, list)
