"""Dice rolling system for the SRD 5e Rules Engine.

All functions accept an optional ``seed`` parameter. When provided, results are
fully reproducible — the same seed always produces the same rolls. Each call
creates its own ``random.Random`` instance so global random state is never
touched.
"""

import random
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Regex: NdX, NdX+M, NdX-M, NdXkhY, NdXklY, NdXkhY+M, NdXklY-M …
# Groups: (num_dice)(die_sides)(keep_mode?)(keep_count?)(sign?)(modifier?)
# ---------------------------------------------------------------------------
_NOTATION_RE = re.compile(
    r"^(\d+)d(\d+)"
    r"(?:k([hl])(\d+))?"
    r"(?:([+-])(\d+))?$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DiceResult:
    """Result of a dice roll expression."""

    total: int
    """Final result after applying keep-highest/lowest and modifiers."""

    rolls: list[int]
    """All individual die results (including dropped dice)."""

    notation: str
    """The original notation string that produced this result."""

    dropped: list[int] = field(default_factory=list)
    """Dice that were excluded from the total (e.g. lowest die in 4d6kh3)."""


@dataclass
class D20Result:
    """Result of a d20 roll, including advantage/disadvantage handling."""

    total: int
    """Final result (natural roll + modifier)."""

    natural: int
    """The raw d20 value before the modifier is applied."""

    is_critical_hit: bool
    """True when the natural roll is 20, regardless of modifier."""

    is_critical_miss: bool
    """True when the natural roll is 1, regardless of modifier."""

    had_advantage: bool
    """Whether advantage was requested."""

    had_disadvantage: bool
    """Whether disadvantage was requested."""

    all_rolls: list[int]
    """Both d20 rolls when rolling with advantage/disadvantage, else [natural]."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def roll(notation: str, seed: int | None = None) -> DiceResult:
    """Parse and evaluate standard dice notation.

    Supported forms::

        1d20          Roll one twenty-sided die
        2d6+3         Roll 2d6 and add 3
        4d6kh3        Roll 4d6, keep the highest 3 (ability score generation)
        2d20kl1       Roll 2d20, keep the lowest (disadvantage)

    Args:
        notation: A dice notation string.
        seed: Optional integer seed for reproducibility.

    Returns:
        A :class:`DiceResult` with the total, all rolls, and dropped dice.

    Raises:
        ValueError: If the notation is invalid or ``num_dice`` is zero.
    """
    m = _NOTATION_RE.match(notation.strip())
    if m is None:
        raise ValueError(f"Invalid dice notation: {notation!r}")

    num_dice = int(m.group(1))
    die_sides = int(m.group(2))
    keep_mode: str | None = m.group(3)
    keep_count: int | None = int(m.group(4)) if m.group(4) is not None else None
    modifier_sign: str | None = m.group(5)
    modifier_value: int = int(m.group(6)) if m.group(6) is not None else 0

    if num_dice == 0:
        raise ValueError(f"Cannot roll 0 dice: {notation!r}")
    if die_sides < 1:
        raise ValueError(f"Die must have at least 1 side: {notation!r}")
    if keep_count is not None and keep_count > num_dice:
        raise ValueError(f"Cannot keep {keep_count} dice from a pool of {num_dice}: {notation!r}")
    if keep_count is not None and keep_count == 0:
        raise ValueError(f"keep count must be at least 1: {notation!r}")

    rng = random.Random(seed)
    rolls = [rng.randint(1, die_sides) for _ in range(num_dice)]

    dropped: list[int] = []
    if keep_mode is not None and keep_count is not None and keep_count < num_dice:
        sorted_rolls = sorted(rolls)
        if keep_mode.lower() == "h":
            # Keep highest Y — drop the (num_dice - keep_count) lowest values
            dropped = sorted_rolls[: num_dice - keep_count]
        else:
            # Keep lowest Y — drop the (num_dice - keep_count) highest values
            dropped = sorted_rolls[keep_count:]

    modifier = modifier_value if modifier_sign != "-" else -modifier_value
    total = sum(rolls) - sum(dropped) + modifier

    return DiceResult(total=total, rolls=rolls, notation=notation, dropped=dropped)


def roll_d20(
    modifier: int = 0,
    advantage: bool = False,
    disadvantage: bool = False,
    seed: int | None = None,
) -> D20Result:
    """Roll a d20 with optional modifier and advantage/disadvantage.

    Advantage and disadvantage cancel each other out — if both are True the die
    is rolled once normally, matching the SRD rule.

    Args:
        modifier: Integer bonus or penalty added to the natural roll.
        advantage: Roll twice and take the higher result.
        disadvantage: Roll twice and take the lower result.
        seed: Optional integer seed for reproducibility.

    Returns:
        A :class:`D20Result` with the total, natural roll, and crit flags.
    """
    # Advantage and disadvantage cancel out per SRD
    net_advantage = advantage and not disadvantage
    net_disadvantage = disadvantage and not advantage

    rng = random.Random(seed)

    if net_advantage or net_disadvantage:
        r1 = rng.randint(1, 20)
        r2 = rng.randint(1, 20)
        all_rolls = [r1, r2]
        natural = max(r1, r2) if net_advantage else min(r1, r2)
    else:
        natural = rng.randint(1, 20)
        all_rolls = [natural]

    return D20Result(
        total=natural + modifier,
        natural=natural,
        is_critical_hit=natural == 20,
        is_critical_miss=natural == 1,
        had_advantage=advantage,
        had_disadvantage=disadvantage,
        all_rolls=all_rolls,
    )


_STANDARD_ARRAY: list[int] = [15, 14, 13, 12, 10, 8]


def roll_ability_scores(
    method: str = "standard_array",
    seed: int | None = None,
) -> list[int]:
    """Generate six ability scores using the specified method.

    Args:
        method: One of ``"standard_array"``, ``"random"``, or ``"point_buy"``.
            ``"point_buy"`` is interactive and always raises.
        seed: Optional integer seed for reproducibility (``"random"`` only).

    Returns:
        A list of six integers representing ability scores.

    Raises:
        ValueError: For ``"point_buy"`` or an unrecognised method name.
    """
    if method == "standard_array":
        return list(_STANDARD_ARRAY)

    if method == "point_buy":
        raise ValueError(
            "Point buy is an interactive method and cannot be rolled; "
            "present the point buy table to the player instead."
        )

    if method == "random":
        rng = random.Random(seed)
        scores: list[int] = []
        for _ in range(6):
            # 4d6, drop the lowest die
            four_rolls = sorted(rng.randint(1, 6) for _ in range(4))
            scores.append(sum(four_rolls[1:]))  # sum of highest 3
        return scores

    raise ValueError(
        f"Unknown ability score method: {method!r}. "
        "Expected 'standard_array', 'random', or 'point_buy'."
    )
