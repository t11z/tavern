"""Tests for srd_data.py constants and collection name definitions (ADR-0010)."""

from tavern.core.srd_data import _XP_THRESHOLDS


class TestXpThresholdsConstant:
    def test_has_exactly_20_entries(self) -> None:
        assert len(_XP_THRESHOLDS) == 20

    def test_starts_at_zero(self) -> None:
        assert _XP_THRESHOLDS[0] == 0

    def test_level_2_threshold(self) -> None:
        assert _XP_THRESHOLDS[1] == 300

    def test_level_20_threshold(self) -> None:
        assert _XP_THRESHOLDS[19] == 355000

    def test_strictly_increasing(self) -> None:
        for i in range(1, len(_XP_THRESHOLDS)):
            assert _XP_THRESHOLDS[i] > _XP_THRESHOLDS[i - 1], (
                f"_XP_THRESHOLDS[{i}] ({_XP_THRESHOLDS[i]}) should be > "
                f"_XP_THRESHOLDS[{i - 1}] ({_XP_THRESHOLDS[i - 1]})"
            )
