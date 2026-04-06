"""Tests for dm/summary.py — build_turn_summary_input and trim_summary."""

from __future__ import annotations

from tavern.dm.summary import (
    _BUDGET_SUMMARY_TOKENS,
    _MAX_ACTION_WORDS,
    build_turn_summary_input,
    trim_summary,
)

# ---------------------------------------------------------------------------
# build_turn_summary_input
# ---------------------------------------------------------------------------


class TestBuildTurnSummaryInput:
    def test_includes_sequence_number(self) -> None:
        line = build_turn_summary_input(
            character_name="Kael",
            player_action="I attack the goblin",
            rules_result=None,
            narrative_excerpt="",
            sequence_number=5,
        )
        assert "Turn 5" in line

    def test_includes_character_name(self) -> None:
        line = build_turn_summary_input(
            character_name="Mira",
            player_action="I cast fireball",
            rules_result=None,
            narrative_excerpt="",
            sequence_number=1,
        )
        assert "Mira" in line

    def test_includes_player_action(self) -> None:
        line = build_turn_summary_input(
            character_name="Kael",
            player_action="I strike the troll with my longsword",
            rules_result=None,
            narrative_excerpt="",
            sequence_number=3,
        )
        assert "longsword" in line

    def test_includes_rules_result_when_present(self) -> None:
        line = build_turn_summary_input(
            character_name="Kael",
            player_action="I attack",
            rules_result="Attack roll 18 — hit! Deals 14 Slashing damage",
            narrative_excerpt="",
            sequence_number=2,
        )
        assert "hit" in line
        assert "14 Slashing" in line

    def test_omits_rules_result_when_none(self) -> None:
        line = build_turn_summary_input(
            character_name="Kael",
            player_action="I look around the room",
            rules_result=None,
            narrative_excerpt="",
            sequence_number=1,
        )
        # Should not have an empty separator artefact
        assert "None" not in line
        assert "  " not in line.replace("  ", " ")

    def test_includes_narrative_excerpt(self) -> None:
        narrative = (
            "Goblin A fell to the ground with a sickening thud. "
            "The party pressed forward into the darkened corridor. "
            "More sounds echoed from the depths below."
        )
        line = build_turn_summary_input(
            character_name="Kael",
            player_action="I attack Goblin A",
            rules_result="Hit for 12 damage",
            narrative_excerpt=narrative,
            sequence_number=7,
        )
        # First sentence should be present; third should be excluded
        assert "thud" in line
        assert "depths" not in line

    def test_narrative_excerpt_capped_at_two_sentences(self) -> None:
        narrative = "Sentence one. Sentence two. Sentence three. Sentence four."
        line = build_turn_summary_input(
            character_name="X",
            player_action="action",
            rules_result=None,
            narrative_excerpt=narrative,
            sequence_number=1,
        )
        assert "Sentence one" in line
        assert "Sentence two" in line
        assert "Sentence three" not in line

    def test_empty_narrative_excerpt_omitted(self) -> None:
        line = build_turn_summary_input(
            character_name="Kael",
            player_action="I move north",
            rules_result=None,
            narrative_excerpt="",
            sequence_number=4,
        )
        assert line.strip()  # Still produces output
        assert "None" not in line

    def test_long_action_is_truncated(self) -> None:
        long_action = " ".join(f"word{i}" for i in range(_MAX_ACTION_WORDS + 20))
        line = build_turn_summary_input(
            character_name="Kael",
            player_action=long_action,
            rules_result=None,
            narrative_excerpt="",
            sequence_number=1,
        )
        # The ellipsis marker should be present after truncation
        assert "…" in line

    def test_short_action_not_truncated(self) -> None:
        short_action = "I attack the goblin"
        line = build_turn_summary_input(
            character_name="Kael",
            player_action=short_action,
            rules_result=None,
            narrative_excerpt="",
            sequence_number=1,
        )
        assert short_action in line
        assert "…" not in line

    def test_returns_a_string(self) -> None:
        line = build_turn_summary_input(
            character_name="Kael",
            player_action="I look around",
            rules_result=None,
            narrative_excerpt="",
            sequence_number=1,
        )
        assert isinstance(line, str)
        assert len(line) > 0

    def test_line_ends_with_period(self) -> None:
        line = build_turn_summary_input(
            character_name="Kael",
            player_action="I hide behind the pillar",
            rules_result=None,
            narrative_excerpt="Something happened.",
            sequence_number=9,
        )
        assert line.endswith(".")

    def test_full_turn_combines_all_components(self) -> None:
        line = build_turn_summary_input(
            character_name="Kael",
            player_action="attacked Goblin A with longsword",
            rules_result="Attack roll 18 — hit! Deals 14 Slashing damage",
            narrative_excerpt="Goblin A fell. The party cheered.",
            sequence_number=5,
        )
        assert "Turn 5" in line
        assert "Kael" in line
        assert "longsword" in line
        assert "14 Slashing" in line
        assert "Goblin A fell" in line


# ---------------------------------------------------------------------------
# trim_summary
# ---------------------------------------------------------------------------


class TestTrimSummary:
    def test_returns_unchanged_when_within_budget(self) -> None:
        short = "Turn 1: Kael attacked the goblin. Turn 2: Mira cast fireball."
        result, _diag = trim_summary(short)
        assert result == short

    def test_returns_empty_string_unchanged(self) -> None:
        result, _diag = trim_summary("")
        assert result == ""

    def test_result_within_token_budget(self) -> None:
        # Build a summary that exceeds the budget, then trim it.
        long_summary = "\n".join(
            f"Turn {i}: Character attacked enemy — hit for {i * 3} damage. "
            f"The enemy recoiled. Battle continued."
            for i in range(1, 40)
        )
        trimmed, _diag = trim_summary(long_summary)
        tokens = len(trimmed) // 4
        assert tokens <= _BUDGET_SUMMARY_TOKENS

    def test_drops_oldest_lines_first(self) -> None:
        # Build 20 turns, check that trim keeps recent and drops old.
        lines = [f"Turn {i}: entry {i}" for i in range(1, 21)]
        long_summary = "\n".join(lines)
        trimmed, _diag = trim_summary(long_summary)
        # Most-recent entry must survive; very old entries may be gone.
        assert "Turn 20" in trimmed

    def test_twenty_turns_do_not_exceed_budget(self) -> None:
        lines = [
            build_turn_summary_input(
                character_name="Kael",
                player_action="I attack the goblin with my longsword",
                rules_result="Attack roll 17 — hit! Deals 12 Slashing damage",
                narrative_excerpt="The goblin staggered. Steel rang against the dungeon walls.",
                sequence_number=i,
            )
            for i in range(1, 21)
        ]
        summary = "\n".join(lines)
        trimmed, _diag = trim_summary(summary)
        tokens = len(trimmed) // 4
        assert tokens <= _BUDGET_SUMMARY_TOKENS

    def test_trims_prose_block_by_sentences(self) -> None:
        # Simulate LLM-compressed prose (no newlines).
        prose = (
            "The party entered the dungeon. "
            "Kael attacked a goblin and hit for 12 damage. "
            "The goblin fell. "
            "Mira cast fireball at the troll. "
            "The troll was bloodied. "
            "Everyone moved to the next room. "
        ) * 30  # repeat to force budget overflow
        trimmed, _diag = trim_summary(prose)
        assert len(trimmed) // 4 <= _BUDGET_SUMMARY_TOKENS

    def test_preserves_at_least_one_entry(self) -> None:
        # Even a summary that can't be fully trimmed should keep something.
        single_long_line = "word " * 3000
        trimmed, _diag = trim_summary(single_long_line)
        assert len(trimmed) > 0

    def test_custom_max_tokens(self) -> None:
        # Build a multi-sentence prose block that exceeds a tight budget.
        sentences = " ".join(f"Sentence {i} happened here and was noted." for i in range(50))
        trimmed, _diag = trim_summary(sentences, max_tokens=50)
        assert len(trimmed) // 4 <= 50

    def test_idempotent_when_already_trimmed(self) -> None:
        short = "Turn 19: Kael attacked. Turn 20: Mira healed."
        result1, _diag1 = trim_summary(short)
        result2, _diag2 = trim_summary(result1)
        result3, _diag3 = trim_summary(short)
        assert result2 == result3

    def test_diagnostic_before_tokens_on_unchanged(self) -> None:
        short = "Turn 1: quick note."
        _result, diag = trim_summary(short)
        assert diag["before_tokens"] == len(short) // 4
        assert diag["after_tokens"] == diag["before_tokens"]

    def test_diagnostic_after_tokens_less_than_before_on_trim(self) -> None:
        long_summary = "\n".join(
            f"Turn {i}: Character attacked enemy — hit for {i * 3} damage." for i in range(1, 40)
        )
        _result, diag = trim_summary(long_summary)
        assert diag["before_tokens"] > diag["after_tokens"]

    def test_diagnostic_empty_string_both_zero(self) -> None:
        _result, diag = trim_summary("")
        assert diag["before_tokens"] == 0
        assert diag["after_tokens"] == 0
