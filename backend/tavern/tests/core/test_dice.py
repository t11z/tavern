import pytest

from tavern.core.dice import (
    roll,
    roll_ability_scores,
    roll_d20,
)


class TestRollBasicRange:
    def test_1d20_stays_in_range(self) -> None:
        for seed in range(20):
            result = roll("1d20", seed=seed)
            assert 1 <= result.total <= 20

    def test_2d6_stays_in_range(self) -> None:
        for seed in range(20):
            result = roll("2d6", seed=seed)
            assert 2 <= result.total <= 12

    def test_8d6_stays_in_range(self) -> None:
        for seed in range(20):
            result = roll("8d6", seed=seed)
            assert 8 <= result.total <= 48

    def test_rolls_field_length_matches_num_dice(self) -> None:
        assert len(roll("3d6", seed=0).rolls) == 3
        assert len(roll("1d20", seed=0).rolls) == 1

    def test_rolls_field_each_die_in_range(self) -> None:
        result = roll("4d6", seed=0)
        for r in result.rolls:
            assert 1 <= r <= 6

    def test_notation_preserved(self) -> None:
        assert roll("2d8+3", seed=0).notation == "2d8+3"


class TestModifiers:
    def test_positive_modifier_adds_to_total(self) -> None:
        # With seed we know the base roll; modifier must shift total
        base = roll("1d20", seed=99)
        modified = roll("1d20+5", seed=99)
        assert modified.total == base.total + 5

    def test_negative_modifier_subtracts_from_total(self) -> None:
        base = roll("1d20", seed=99)
        modified = roll("1d20-3", seed=99)
        assert modified.total == base.total - 3

    def test_negative_total_is_possible(self) -> None:
        # 1d1-3 always gives -2
        result = roll("1d1-3", seed=0)
        assert result.total == -2

    def test_zero_modifier_unchanged(self) -> None:
        base = roll("2d6", seed=5)
        with_zero = roll("2d6+0", seed=5)
        assert base.total == with_zero.total


class TestDeterministicSeeding:
    def test_same_seed_same_result(self) -> None:
        a = roll("2d6", seed=42)
        b = roll("2d6", seed=42)
        assert a.total == b.total
        assert a.rolls == b.rolls

    def test_different_seeds_differ(self) -> None:
        results = {roll("1d20", seed=s).total for s in range(50)}
        # With 50 seeds and a d20, we expect more than 1 distinct value
        assert len(results) > 1

    def test_no_seed_still_valid_range(self) -> None:
        result = roll("1d20")
        assert 1 <= result.total <= 20

    def test_seeded_roll_independent_of_global_state(self) -> None:
        import random

        random.seed(0)
        a = roll("2d6", seed=7)
        random.seed(999)
        b = roll("2d6", seed=7)
        assert a.rolls == b.rolls


class TestKeepHighest:
    def test_4d6kh3_keeps_three_dice(self) -> None:
        result = roll("4d6kh3", seed=0)
        assert len(result.rolls) == 4
        assert len(result.dropped) == 1

    def test_4d6kh3_drops_lowest(self) -> None:
        result = roll("4d6kh3", seed=0)
        assert result.dropped[0] == min(result.rolls)

    def test_4d6kh3_total_is_sum_of_kept(self) -> None:
        result = roll("4d6kh3", seed=0)
        expected = sum(result.rolls) - sum(result.dropped)
        assert result.total == expected

    def test_kh_with_modifier(self) -> None:
        base = roll("4d6kh3", seed=0)
        with_mod = roll("4d6kh3+2", seed=0)
        assert with_mod.total == base.total + 2

    def test_keep_all_drops_nothing(self) -> None:
        result = roll("3d6kh3", seed=0)
        assert result.dropped == []
        assert result.total == sum(result.rolls)


class TestKeepLowest:
    def test_2d20kl1_keeps_one_die(self) -> None:
        result = roll("2d20kl1", seed=0)
        assert len(result.rolls) == 2
        assert len(result.dropped) == 1

    def test_2d20kl1_drops_highest(self) -> None:
        result = roll("2d20kl1", seed=0)
        assert result.dropped[0] == max(result.rolls)

    def test_2d20kl1_total_is_lower_of_two(self) -> None:
        result = roll("2d20kl1", seed=0)
        assert result.total == min(result.rolls)

    def test_kl_total_is_sum_of_kept(self) -> None:
        result = roll("4d6kl2", seed=0)
        expected = sum(result.rolls) - sum(result.dropped)
        assert result.total == expected


class TestD20Roll:
    def test_natural_in_range(self) -> None:
        for seed in range(30):
            r = roll_d20(seed=seed)
            assert 1 <= r.natural <= 20

    def test_modifier_applied_to_total(self) -> None:
        r = roll_d20(modifier=5, seed=0)
        assert r.total == r.natural + 5

    def test_negative_modifier(self) -> None:
        r = roll_d20(modifier=-3, seed=0)
        assert r.total == r.natural - 3

    def test_natural_20_is_critical_hit(self) -> None:
        # Find a seed that produces a natural 20
        for seed in range(200):
            r = roll_d20(seed=seed)
            if r.natural == 20:
                assert r.is_critical_hit is True
                assert r.is_critical_miss is False
                return
        pytest.fail("Could not produce a natural 20 in 200 seeds")

    def test_natural_1_is_critical_miss(self) -> None:
        for seed in range(200):
            r = roll_d20(seed=seed)
            if r.natural == 1:
                assert r.is_critical_miss is True
                assert r.is_critical_hit is False
                return
        pytest.fail("Could not produce a natural 1 in 200 seeds")

    def test_critical_hit_regardless_of_modifier(self) -> None:
        for seed in range(200):
            r = roll_d20(modifier=-10, seed=seed)
            if r.natural == 20:
                assert r.is_critical_hit is True
                return
        pytest.fail("Could not produce a natural 20 in 200 seeds")

    def test_critical_miss_regardless_of_modifier(self) -> None:
        for seed in range(200):
            r = roll_d20(modifier=+10, seed=seed)
            if r.natural == 1:
                assert r.is_critical_miss is True
                return
        pytest.fail("Could not produce a natural 1 in 200 seeds")

    def test_advantage_takes_higher(self) -> None:
        for seed in range(50):
            r = roll_d20(advantage=True, seed=seed)
            assert r.natural == max(r.all_rolls)
            assert len(r.all_rolls) == 2

    def test_disadvantage_takes_lower(self) -> None:
        for seed in range(50):
            r = roll_d20(disadvantage=True, seed=seed)
            assert r.natural == min(r.all_rolls)
            assert len(r.all_rolls) == 2

    def test_advantage_disadvantage_cancel_out(self) -> None:
        for seed in range(50):
            normal = roll_d20(seed=seed)
            cancelled = roll_d20(advantage=True, disadvantage=True, seed=seed)
            assert cancelled.natural == normal.natural
            assert len(cancelled.all_rolls) == 1

    def test_advantage_sets_flag(self) -> None:
        r = roll_d20(advantage=True, seed=0)
        assert r.had_advantage is True
        assert r.had_disadvantage is False

    def test_disadvantage_sets_flag(self) -> None:
        r = roll_d20(disadvantage=True, seed=0)
        assert r.had_disadvantage is True
        assert r.had_advantage is False

    def test_normal_roll_single_result(self) -> None:
        r = roll_d20(seed=0)
        assert len(r.all_rolls) == 1

    def test_deterministic_advantage(self) -> None:
        a = roll_d20(advantage=True, seed=42)
        b = roll_d20(advantage=True, seed=42)
        assert a.all_rolls == b.all_rolls
        assert a.natural == b.natural

    def test_deterministic_disadvantage(self) -> None:
        a = roll_d20(disadvantage=True, seed=42)
        b = roll_d20(disadvantage=True, seed=42)
        assert a.all_rolls == b.all_rolls


class TestAbilityScores:
    def test_standard_array_exact_values(self) -> None:
        scores = roll_ability_scores("standard_array")
        assert scores == [15, 14, 13, 12, 10, 8]

    def test_standard_array_unaffected_by_seed(self) -> None:
        assert roll_ability_scores("standard_array", seed=0) == [15, 14, 13, 12, 10, 8]
        assert roll_ability_scores("standard_array", seed=999) == [15, 14, 13, 12, 10, 8]

    def test_standard_array_returns_copy(self) -> None:
        a = roll_ability_scores("standard_array")
        a[0] = 99
        assert roll_ability_scores("standard_array")[0] == 15

    def test_point_buy_raises(self) -> None:
        with pytest.raises(ValueError, match="interactive"):
            roll_ability_scores("point_buy")

    def test_unknown_method_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown"):
            roll_ability_scores("rolled")

    def test_random_returns_six_scores(self) -> None:
        scores = roll_ability_scores("random", seed=0)
        assert len(scores) == 6

    def test_random_each_score_in_range(self) -> None:
        scores = roll_ability_scores("random", seed=0)
        for score in scores:
            assert 3 <= score <= 18, f"Score {score} out of 3–18 range"

    def test_random_with_seed_reproducible(self) -> None:
        a = roll_ability_scores("random", seed=7)
        b = roll_ability_scores("random", seed=7)
        assert a == b

    def test_random_different_seeds_differ(self) -> None:
        results = [tuple(roll_ability_scores("random", seed=s)) for s in range(20)]
        assert len(set(results)) > 1


class TestEdgeCases:
    def test_1d1_always_returns_1(self) -> None:
        for seed in range(10):
            assert roll("1d1", seed=seed).total == 1

    def test_0d6_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot roll 0 dice"):
            roll("0d6")

    def test_100d6_works(self) -> None:
        result = roll("100d6", seed=0)
        assert 100 <= result.total <= 600
        assert len(result.rolls) == 100

    def test_invalid_notation_raises(self) -> None:
        for bad in ["d20", "2x6", "abc", "", "1d", "1d20kh"]:
            with pytest.raises(ValueError):
                roll(bad)

    def test_keep_count_exceeds_dice_raises(self) -> None:
        with pytest.raises(ValueError):
            roll("2d6kh5")

    def test_whitespace_stripped_from_notation(self) -> None:
        result = roll(" 1d20 ", seed=0)
        assert 1 <= result.total <= 20

    def test_uppercase_notation_accepted(self) -> None:
        result = roll("4D6KH3", seed=0)
        assert len(result.dropped) == 1

    def test_dropped_empty_when_no_keep(self) -> None:
        result = roll("3d6", seed=0)
        assert result.dropped == []
