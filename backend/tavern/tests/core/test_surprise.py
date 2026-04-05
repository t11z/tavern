"""Tests for surprise mechanics — SRD 5.2.1 p.13 (ADR-0014).

All test cases cite the SRD 5.2.1 section or ADR-0014 decision they validate.
Deterministic seeds guarantee reproducibility.

Surprise rules implemented (ADR-0014):
- Surprise = Disadvantage on initiative roll ONLY.  No action restriction.
- A target is surprised if ALL concealers beat its passive Perception.
- One concealer failing ruins the ambush for all targets.
- Alert feat grants immunity to Surprise (pre-filter, not in determine_surprise).
"""

from __future__ import annotations

import logging

import pytest

from tavern.core.combat import (
    CombatParticipant,
    CombatSnapshot,
    CombatSnapshotCharacter,
    _has_surprise_immunity,
    determine_surprise,
    roll_initiative_order,
)
from tavern.core.dice import roll_d20

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(*chars: tuple[str, int, bool, int, list[str]]) -> CombatSnapshot:
    """Build a CombatSnapshot from (id, wis_mod, perc_proficient, prof_bonus, feats) tuples."""
    return CombatSnapshot(
        characters={
            cid: CombatSnapshotCharacter(
                wis_modifier=wis_mod,
                perception_proficient=perc_prof,
                proficiency_bonus=prof_bonus,
                feats=feats,
            )
            for cid, wis_mod, perc_prof, prof_bonus, feats in chars
        }
    )


def _participant(
    character_id: str,
    participant_type: str = "pc",
    surprised: bool = False,
) -> CombatParticipant:
    """Build a minimal CombatParticipant for testing (initiative fields zeroed)."""
    return CombatParticipant(
        character_id=character_id,
        participant_type=participant_type,  # type: ignore[arg-type]
        initiative_roll=0,
        initiative_result=0,
        surprised=surprised,
    )


# ===========================================================================
# CombatParticipant dataclass
# ===========================================================================


class TestCombatParticipant:
    def test_instantiation_with_all_fields(self) -> None:
        """CombatParticipant can be instantiated with all required fields."""
        p = CombatParticipant(
            character_id="pc-001",
            participant_type="pc",
            initiative_roll=14,
            initiative_result=16,
            surprised=True,
            acted_this_round=False,
        )
        assert p.character_id == "pc-001"
        assert p.participant_type == "pc"
        assert p.initiative_roll == 14
        assert p.initiative_result == 16
        assert p.surprised is True
        assert p.acted_this_round is False

    def test_acted_this_round_defaults_false(self) -> None:
        """acted_this_round defaults to False (not yet acted at combat start)."""
        p = CombatParticipant(
            character_id="npc-001",
            participant_type="npc",
            initiative_roll=8,
            initiative_result=8,
            surprised=False,
        )
        assert p.acted_this_round is False

    def test_npc_participant_type(self) -> None:
        """participant_type can be 'npc'."""
        p = CombatParticipant(
            character_id="goblin-1",
            participant_type="npc",
            initiative_roll=5,
            initiative_result=4,
            surprised=False,
        )
        assert p.participant_type == "npc"


# ===========================================================================
# determine_surprise — ADR-0014 §2
# ===========================================================================


class TestDetermineSurprise:
    def test_all_concealers_beat_passive_perception_surprised(self) -> None:
        """ADR-0014 §2: All concealers beat target's passive Perception → surprised=True.

        SRD 5.2.1 p.13: passive Perception = 10 + WIS modifier.
        Target WIS modifier = +1 → passive Perception = 11.
        Concealers: goblin-A stealth=15, goblin-B stealth=14.
        Both 15 > 11 and 14 > 11 → target IS surprised.
        """
        snapshot = _snapshot(("pc-001", 1, False, 0, []))
        stealth_results = {"goblin-A": 15, "goblin-B": 14}
        result = determine_surprise(["pc-001"], stealth_results, snapshot)
        assert result == {"pc-001": True}

    def test_one_concealer_fails_not_surprised(self) -> None:
        """ADR-0014 §2: One concealer fails to beat passive Perception → target NOT surprised.

        'All concealers must beat' rule: a single detected member ruins the
        ambush.  goblin-B's stealth of 6 does not beat passive Perception 11.
        """
        snapshot = _snapshot(("pc-001", 1, False, 0, []))
        # goblin-A succeeds (15 > 11) but goblin-B fails (6 ≤ 11)
        stealth_results = {"goblin-A": 15, "goblin-B": 6}
        result = determine_surprise(["pc-001"], stealth_results, snapshot)
        assert result == {"pc-001": False}

    def test_concealer_exactly_equal_to_passive_perception_not_surprised(self) -> None:
        """ADR-0014: Stealth must STRICTLY beat passive Perception (not equal).

        Target passive Perception = 11 (WIS +1).  Concealer stealth = 11.
        11 is not strictly greater than 11 → NOT surprised.
        """
        snapshot = _snapshot(("pc-001", 1, False, 0, []))
        stealth_results = {"goblin-A": 11}
        result = determine_surprise(["pc-001"], stealth_results, snapshot)
        assert result == {"pc-001": False}

    def test_empty_potential_surprised_returns_empty(self) -> None:
        """ADR-0014 §3 Path C: No potential targets → empty result immediately."""
        snapshot = _snapshot(("pc-001", 1, False, 0, []))
        stealth_results = {"goblin-A": 15}
        result = determine_surprise([], stealth_results, snapshot)
        assert result == {}

    def test_empty_stealth_results_all_false(self) -> None:
        """ADR-0014: No concealers → no one can be surprised."""
        snapshot = _snapshot(("pc-001", 1, False, 0, []), ("pc-002", 0, False, 0, []))
        result = determine_surprise(["pc-001", "pc-002"], {}, snapshot)
        assert result == {"pc-001": False, "pc-002": False}

    def test_per_character_determination(self) -> None:
        """ADR-0014 §2: Surprise is determined per character, not globally.

        pc-001 has passive Perception 11 (WIS +1).
        pc-002 has passive Perception 15 (WIS +3 + proficiency 2 = 10+3+2=15).
        Concealer stealth = 14.
        14 > 11 → pc-001 IS surprised.
        14 < 15 (not strictly greater) → pc-002 is NOT surprised.
        """
        snapshot = _snapshot(
            ("pc-001", 1, False, 0, []),
            ("pc-002", 3, True, 2, []),
        )
        stealth_results = {"npc-rogue": 14}
        result = determine_surprise(["pc-001", "pc-002"], stealth_results, snapshot)
        assert result["pc-001"] is True
        assert result["pc-002"] is False

    def test_perception_proficiency_increases_passive_perception(self) -> None:
        """SRD 5.2.1: Passive Perception includes proficiency bonus if proficient.

        WIS modifier = 0, proficiency bonus = 3 → passive Perception = 13.
        Concealer stealth = 12.  12 ≤ 13 → NOT surprised.
        """
        snapshot = _snapshot(("pc-001", 0, True, 3, []))
        stealth_results = {"rogue": 12}
        result = determine_surprise(["pc-001"], stealth_results, snapshot)
        assert result == {"pc-001": False}

    def test_unknown_character_not_surprised(self) -> None:
        """Unknown character_id (not in snapshot) → not surprised (safe default)."""
        snapshot = CombatSnapshot(characters={})
        stealth_results = {"attacker": 20}
        result = determine_surprise(["unknown-char"], stealth_results, snapshot)
        assert result == {"unknown-char": False}

    def test_multiple_targets_mixed_results(self) -> None:
        """Multiple targets with different passive Perceptions yield mixed results.

        ADR-0014 §2: Each target evaluated independently.
        Target A: passive Perception 8 (WIS -1) — both concealers beat 8 → surprised.
        Target B: passive Perception 14 (WIS +2 + prof 2) — concealer-B fails → not surprised.
        """
        snapshot = _snapshot(
            ("target-a", -1, False, 0, []),
            ("target-b", 2, True, 2, []),
        )
        stealth_results = {"concealer-A": 12, "concealer-B": 10}
        result = determine_surprise(["target-a", "target-b"], stealth_results, snapshot)
        # target-a: passive=9, both 12>9 and 10>9 → surprised
        assert result["target-a"] is True
        # target-b: passive=14, concealer-B 10 ≤ 14 → not surprised
        assert result["target-b"] is False


# ===========================================================================
# _has_surprise_immunity — ADR-0014 §6
# ===========================================================================


class TestHasSurpriseImmunity:
    def test_alert_feat_returns_true(self) -> None:
        """ADR-0014 §6: Alert feat grants immunity to Surprise."""
        snapshot = _snapshot(("pc-001", 1, False, 0, ["Alert"]))
        assert _has_surprise_immunity("pc-001", snapshot) is True

    def test_no_feats_returns_false(self) -> None:
        """Character with no feats is not immune to Surprise."""
        snapshot = _snapshot(("pc-001", 1, False, 0, []))
        assert _has_surprise_immunity("pc-001", snapshot) is False

    def test_other_feats_no_immunity(self) -> None:
        """Feats other than Alert do not grant Surprise immunity."""
        snapshot = _snapshot(("pc-001", 1, False, 0, ["Lucky", "Tough"]))
        assert _has_surprise_immunity("pc-001", snapshot) is False

    def test_unknown_character_no_immunity(self) -> None:
        """Unknown character_id → not immune (safe default, no KeyError)."""
        snapshot = CombatSnapshot(characters={})
        assert _has_surprise_immunity("ghost-char", snapshot) is False

    def test_alert_immunity_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Alert feat immunity is logged at INFO level."""
        snapshot = _snapshot(("pc-alert", 2, False, 0, ["Alert"]))
        with caplog.at_level(logging.INFO, logger="tavern.core.combat"):
            result = _has_surprise_immunity("pc-alert", snapshot)
        assert result is True
        assert "Alert feat" in caplog.text
        assert "pc-alert" in caplog.text

    def test_alert_prefilter_removes_from_surprised(self) -> None:
        """ADR-0014 §6: After pre-filtering Alert character, they appear in no surprised results.

        This validates the caller-side pre-filter workflow:
        1. Build potential_surprised list
        2. Remove Alert characters via _has_surprise_immunity
        3. Call determine_surprise with filtered list
        4. Alert character is not in the result dict at all.
        """
        snapshot = _snapshot(
            ("pc-alert", 0, False, 0, ["Alert"]),
            ("pc-normal", 0, False, 0, []),
        )
        potential = ["pc-alert", "pc-normal"]
        # Pre-filter
        filtered = [cid for cid in potential if not _has_surprise_immunity(cid, snapshot)]
        assert "pc-alert" not in filtered
        assert "pc-normal" in filtered

        # With high stealth, normal PC is surprised; Alert PC is not even in result
        stealth_results = {"goblin": 20}
        result = determine_surprise(filtered, stealth_results, snapshot)
        assert "pc-alert" not in result
        assert result.get("pc-normal") is True


# ===========================================================================
# roll_initiative_order — ADR-0014 §4
# ===========================================================================


class TestRollInitiativeOrder:
    def test_surprised_participant_rolls_disadvantage(self) -> None:
        """ADR-0014 §4: Surprised participant rolls two d20s and takes the lower.

        Uses deterministic seed to verify the lower of two d20 values is used.
        """
        # Compute expected result using roll_d20 directly with same seed
        expected = roll_d20(modifier=0, disadvantage=True, seed=42)
        assert expected.natural == min(expected.all_rolls)

        participant = _participant("pc-001", surprised=True)
        result = roll_initiative_order(
            [participant],
            surprised_map={"pc-001": True},
            dex_modifiers={"pc-001": 0},
            seeds={"pc-001": 42},
        )
        assert len(result) == 1
        p = result[0]
        assert p.initiative_roll == expected.natural
        assert p.initiative_roll == min(expected.all_rolls)

    def test_surprised_participant_uses_lower_roll(self) -> None:
        """Disadvantage: initiative_roll equals min of the two d20 values rolled."""
        # Verify using a seed that produces two distinct rolls
        participant = _participant("pc-001", surprised=True)
        results = roll_initiative_order(
            [participant],
            surprised_map={"pc-001": True},
            dex_modifiers={"pc-001": 0},
            seeds={"pc-001": 7},
        )
        p = results[0]
        expected_d20 = roll_d20(modifier=0, disadvantage=True, seed=7)
        assert p.initiative_roll == expected_d20.natural
        assert p.initiative_roll == min(expected_d20.all_rolls)

    def test_non_surprised_participant_rolls_normally(self) -> None:
        """Non-surprised participant rolls one d20 (no Disadvantage)."""
        expected = roll_d20(modifier=2, seed=42)
        participant = _participant("pc-001", surprised=False)
        results = roll_initiative_order(
            [participant],
            dex_modifiers={"pc-001": 2},
            seeds={"pc-001": 42},
        )
        assert len(results) == 1
        p = results[0]
        assert p.initiative_roll == expected.natural
        assert p.initiative_result == expected.total

    def test_initiative_result_includes_dex_modifier(self) -> None:
        """initiative_result = initiative_roll + DEX modifier."""
        participant = _participant("pc-001", surprised=False)
        results = roll_initiative_order(
            [participant],
            dex_modifiers={"pc-001": 3},
            seeds={"pc-001": 5},
        )
        p = results[0]
        assert p.initiative_result == p.initiative_roll + 3

    def test_sorted_highest_first(self) -> None:
        """roll_initiative_order returns participants sorted by initiative_result descending."""
        participants = [
            _participant("pc-low", surprised=False),
            _participant("pc-high", surprised=False),
            _participant("pc-mid", surprised=False),
        ]
        # Use seeds that produce known orderings
        results = roll_initiative_order(
            participants,
            dex_modifiers={"pc-low": -2, "pc-high": 4, "pc-mid": 1},
            seeds={"pc-low": 1, "pc-high": 2, "pc-mid": 3},
        )
        for i in range(len(results) - 1):
            assert results[i].initiative_result >= results[i + 1].initiative_result

    def test_surprised_flag_preserved_on_result(self) -> None:
        """Surprised flag is propagated to the returned CombatParticipant."""
        participant = _participant("pc-001", surprised=True)
        results = roll_initiative_order(
            [participant],
            surprised_map={"pc-001": True},
            seeds={"pc-001": 42},
        )
        assert results[0].surprised is True

    def test_non_surprised_flag_preserved(self) -> None:
        """Non-surprised flag is preserved on the returned CombatParticipant."""
        participant = _participant("pc-001", surprised=False)
        results = roll_initiative_order([participant], seeds={"pc-001": 42})
        assert results[0].surprised is False

    def test_disadvantage_logged_for_surprised(self, caplog: pytest.LogCaptureFixture) -> None:
        """Both d20 values are logged when Disadvantage applies (ADR-0014 §4)."""
        participant = _participant("pc-001", surprised=True)
        with caplog.at_level(logging.DEBUG, logger="tavern.core.combat"):
            roll_initiative_order(
                [participant],
                surprised_map={"pc-001": True},
                seeds={"pc-001": 42},
            )
        # Log message should mention the character and the list of rolls
        assert "pc-001" in caplog.text
        # The disadvantage log message includes the all_rolls list
        assert "Disadvantage" in caplog.text or "Surprised" in caplog.text

    def test_empty_participants_returns_empty(self) -> None:
        """Empty participant list returns empty list."""
        result = roll_initiative_order([])
        assert result == []

    def test_surprised_map_overrides_participant_surprised_flag(self) -> None:
        """surprised_map takes precedence over participant.surprised."""
        # Participant says not surprised, but surprised_map says surprised
        participant = _participant("pc-001", surprised=False)
        results = roll_initiative_order(
            [participant],
            surprised_map={"pc-001": True},
            seeds={"pc-001": 42},
        )
        assert results[0].surprised is True

    def test_multiple_participants_mixed_surprise(self) -> None:
        """Mixed surprised/not-surprised participants all get correct Disadvantage handling."""
        surprised_p = _participant("pc-surprised", surprised=True)
        normal_p = _participant("pc-normal", surprised=False)

        results = roll_initiative_order(
            [surprised_p, normal_p],
            surprised_map={"pc-surprised": True, "pc-normal": False},
            seeds={"pc-surprised": 10, "pc-normal": 11},
        )
        by_id = {p.character_id: p for p in results}

        # Surprised participant had disadvantage applied
        assert by_id["pc-surprised"].surprised is True
        # Verify it used the lower of two d20 values
        expected_surprised = roll_d20(disadvantage=True, seed=10)
        assert by_id["pc-surprised"].initiative_roll == expected_surprised.natural

        # Non-surprised rolled normally
        assert by_id["pc-normal"].surprised is False
        expected_normal = roll_d20(seed=11)
        assert by_id["pc-normal"].initiative_roll == expected_normal.natural
