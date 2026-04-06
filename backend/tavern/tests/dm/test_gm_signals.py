"""Tests for dm/gm_signals.py — parse_gm_signals() and GMSignals dataclass.

Covers the suggested_actions field introduced in ADR-0015 and the diagnostic
tuple return added for ADR-0018 observability.
"""

from __future__ import annotations

import json

from tavern.dm.gm_signals import (
    GM_SIGNALS_DELIMITER,
    GMSignals,
    parse_gm_signals,
    safe_default,
)

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
        result, _diag = parse_gm_signals(raw)
        assert result.suggested_actions == suggestions

    def test_one_valid_entry_parsed(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": ["Search the room for hidden passages"],
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.suggested_actions == ["Search the room for hidden passages"]

    def test_empty_list_parsed(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
            }
        )
        result, _diag = parse_gm_signals(raw)
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
        result, _diag = parse_gm_signals(raw)
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
        result, _diag = parse_gm_signals(raw)
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
        result, _diag = parse_gm_signals(raw)
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
        result, _diag = parse_gm_signals(raw)
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
        result, _diag = parse_gm_signals(raw)
        assert result.suggested_actions == []

    def test_field_is_string_defaults_to_empty_list(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": "not a list",
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.suggested_actions == []

    def test_field_is_dict_defaults_to_empty_list(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": {"action": "something"},
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.suggested_actions == []

    def test_field_is_integer_defaults_to_empty_list(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": 42,
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.suggested_actions == []

    def test_field_is_null_defaults_to_empty_list(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": None,
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.suggested_actions == []

    def test_non_string_items_skipped(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [42, "Valid suggestion text here", None],
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.suggested_actions == ["Valid suggestion text here"]

    def test_empty_string_items_skipped(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": ["", "Valid suggestion", "   "],
            }
        )
        result, _diag = parse_gm_signals(raw)
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


# ---------------------------------------------------------------------------
# Diagnostic dict — happy path (no fallback)
# ---------------------------------------------------------------------------


class TestDiagnosticSuccess:
    def test_success_has_fallback_used_false(self):
        raw = _make_raw({"scene_transition": {"type": "none"}, "npc_updates": []})
        _signals, diag = parse_gm_signals(raw)
        assert diag["fallback_used"] is False

    def test_success_has_no_parse_error(self):
        raw = _make_raw({"scene_transition": {"type": "none"}, "npc_updates": []})
        _signals, diag = parse_gm_signals(raw)
        assert diag["parse_error"] is None

    def test_success_has_raw_input_truncated(self):
        raw = _make_raw({"scene_transition": {"type": "none"}, "npc_updates": []})
        _signals, diag = parse_gm_signals(raw)
        assert isinstance(diag["raw_input_truncated"], str)
        assert len(diag["raw_input_truncated"]) <= 500

    def test_raw_input_truncated_to_500_chars(self):
        """raw_input_truncated must never exceed 500 characters."""
        long_raw = "x" * 2000
        _signals, diag = parse_gm_signals(long_raw)
        assert len(diag["raw_input_truncated"]) <= 500


# ---------------------------------------------------------------------------
# Diagnostic dict — fallback cases
# ---------------------------------------------------------------------------


class TestDiagnosticFallback:
    def test_missing_delimiter_sets_fallback_used(self):
        _signals, diag = parse_gm_signals("No delimiter here.")
        assert diag["fallback_used"] is True

    def test_missing_delimiter_sets_parse_error(self):
        _signals, diag = parse_gm_signals("No delimiter here.")
        assert isinstance(diag["parse_error"], str)
        assert len(diag["parse_error"]) > 0

    def test_invalid_json_sets_fallback_used(self):
        raw = f"Narrative.\n{GM_SIGNALS_DELIMITER}\n{{not valid json}}"
        _signals, diag = parse_gm_signals(raw)
        assert diag["fallback_used"] is True

    def test_invalid_json_sets_parse_error(self):
        raw = f"Narrative.\n{GM_SIGNALS_DELIMITER}\n{{not valid json}}"
        _signals, diag = parse_gm_signals(raw)
        assert diag["parse_error"] is not None

    def test_fallback_returns_safe_default_signals(self):
        _signals, diag = parse_gm_signals("No delimiter here.")
        assert diag["fallback_used"] is True
        assert _signals == safe_default()


# ---------------------------------------------------------------------------
# LocationChange — happy path
# ---------------------------------------------------------------------------


class TestLocationChangeValid:
    def test_valid_snake_case_identifier_parsed(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "location_change": {"new_location": "harborside_supply", "reason": "Entered shop"},
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.location_change is not None
        assert result.location_change.new_location == "harborside_supply"
        assert result.location_change.reason == "Entered shop"

    def test_location_requiring_normalisation_preserved_raw(self):
        """Parser stores the raw value; normalisation is the pipeline's responsibility."""
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "location_change": {"new_location": "Harborside Supply"},
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.location_change is not None
        assert result.location_change.new_location == "Harborside Supply"

    def test_location_change_reason_defaults_to_empty(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "location_change": {"new_location": "dungeon_level_2"},
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.location_change is not None
        assert result.location_change.reason == ""

    def test_null_location_change_parses_to_none(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "location_change": None,
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.location_change is None

    def test_missing_location_change_parses_to_none(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.location_change is None


# ---------------------------------------------------------------------------
# LocationChange — malformed
# ---------------------------------------------------------------------------


class TestLocationChangeMalformed:
    def test_string_instead_of_dict_ignored(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "location_change": "harborside_supply",
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.location_change is None

    def test_missing_new_location_key_ignored(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "location_change": {"reason": "went somewhere"},
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.location_change is None

    def test_integer_new_location_ignored(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "location_change": {"new_location": 42},
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.location_change is None

    def test_malformed_location_change_does_not_affect_other_fields(self):
        """Other GMSignals fields must parse correctly even if location_change is malformed."""
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": ["Do something"],
                "location_change": "not-a-dict",
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.location_change is None
        assert result.suggested_actions == ["Do something"]
        assert _diag["fallback_used"] is False


# ---------------------------------------------------------------------------
# TimeProgression — happy path
# ---------------------------------------------------------------------------


class TestTimeProgressionValid:
    def test_all_eight_valid_values_parse(self):
        valid_values = [
            "dawn",
            "morning",
            "midday",
            "afternoon",
            "dusk",
            "evening",
            "night",
            "late_night",
        ]
        for value in valid_values:
            raw = _make_raw(
                {
                    "scene_transition": {"type": "none"},
                    "npc_updates": [],
                    "suggested_actions": [],
                    "time_progression": {"new_time_of_day": value},
                }
            )
            result, _diag = parse_gm_signals(raw)
            assert result.time_progression is not None, f"Failed for value: {value}"
            assert result.time_progression.new_time_of_day == value

    def test_time_progression_with_reason(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "time_progression": {"new_time_of_day": "evening", "reason": "Hours of travel"},
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.time_progression is not None
        assert result.time_progression.new_time_of_day == "evening"
        assert result.time_progression.reason == "Hours of travel"

    def test_null_time_progression_parses_to_none(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "time_progression": None,
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.time_progression is None

    def test_missing_time_progression_parses_to_none(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.time_progression is None


# ---------------------------------------------------------------------------
# TimeProgression — malformed
# ---------------------------------------------------------------------------


class TestTimeProgressionMalformed:
    def test_invalid_time_value_ignored(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "time_progression": {"new_time_of_day": "noon"},
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.time_progression is None

    def test_string_instead_of_dict_ignored(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "time_progression": "morning",
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.time_progression is None

    def test_missing_new_time_of_day_key_ignored(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": [],
                "time_progression": {"reason": "time passed"},
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.time_progression is None

    def test_malformed_time_progression_does_not_affect_other_fields(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [],
                "suggested_actions": ["Do something"],
                "time_progression": {"new_time_of_day": "high_noon"},
            }
        )
        result, _diag = parse_gm_signals(raw)
        assert result.time_progression is None
        assert result.suggested_actions == ["Do something"]
        assert _diag["fallback_used"] is False


# ---------------------------------------------------------------------------
# Combined — all five fields populated
# ---------------------------------------------------------------------------


class TestAllFieldsCombined:
    def test_all_five_fields_populated(self):
        raw = _make_raw(
            {
                "scene_transition": {"type": "none"},
                "npc_updates": [
                    {
                        "event": "spawn",
                        "npc_name": "Vara",
                        "species": "Human",
                        "appearance": "A woman with sun-darkened skin.",
                        "role": "Shopkeeper",
                        "motivation": "To make a living",
                        "disposition": "neutral",
                    }
                ],
                "location_change": {"new_location": "harborside_supply", "reason": "Entered shop"},
                "time_progression": {"new_time_of_day": "midday"},
                "suggested_actions": ["Ask about the diving equipment"],
            }
        )
        result, diag = parse_gm_signals(raw)
        assert diag["fallback_used"] is False
        assert result.scene_transition.type == "none"
        assert len(result.npc_updates) == 1
        assert result.npc_updates[0].npc_name == "Vara"
        assert result.location_change is not None
        assert result.location_change.new_location == "harborside_supply"
        assert result.time_progression is not None
        assert result.time_progression.new_time_of_day == "midday"
        assert result.suggested_actions == ["Ask about the diving equipment"]


# ---------------------------------------------------------------------------
# safe_default — new fields
# ---------------------------------------------------------------------------


class TestSafeDefaultNewFields:
    def test_safe_default_location_change_is_none(self):
        result = safe_default()
        assert result.location_change is None

    def test_safe_default_time_progression_is_none(self):
        result = safe_default()
        assert result.time_progression is None
