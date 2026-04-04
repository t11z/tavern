"""Spell resolution orchestrator for the SRD 5.2.1 Rules Engine.

Single public function: ``resolve_spell()`` — fetches the spell document,
validates the slot level, derives caster stats, routes by resolution type
(attack roll / saving throw / auto-hit), rolls damage or healing, and returns
a ``SpellResult`` describing every mechanical outcome.

Resolution routing (mutually exclusive, first match wins):
  - ``attack_type`` present in spell doc → spell attack roll via combat.resolve_attack
  - ``dc`` present in spell doc          → saving throw per target
  - neither                              → auto-hit (Magic Missile, Cure Wounds…)

Cantrip scaling:
  ``damage_at_character_level`` keys are sparse thresholds (e.g. "1", "5", "11",
  "17"); the highest threshold ≤ character level selects the damage dice.

Upcasting:
  ``damage_at_slot_level`` and ``heal_at_slot_level`` are keyed by slot level
  string ("1"–"9").  ``heal_at_slot_level`` values contain a ``MOD`` placeholder
  that is replaced with the caster's spellcasting ability modifier at runtime.

Per-projectile spells (Magic Missile):
  When all ``damage_at_slot_level`` values are identical, the spell fires multiple
  projectiles.  Projectile count is parsed from the ``desc`` field ("You create N
  …") and scaled by slot level above the spell's base level.

M1 scope notes:
  - Concentration is flagged but not tracked (M2).
  - AoE geometry is not enforced; caller provides the target list.
  - V/S/M component validation is not performed (M2).
  - Spell slot availability is not checked; caller owns that state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tavern.core import srd_data
from tavern.core.characters import ability_modifier
from tavern.core.combat import AttackResult, resolve_attack
from tavern.core.conditions import ConditionName
from tavern.core.dice import D20Result, roll, roll_d20

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DamageApplication:
    """Damage outcome for one target from this spell cast."""

    target_index: int
    damage_total: int
    """Final damage after resistance/vulnerability/immunity."""

    raw_damage: int
    """Damage before resistance/vulnerability — after dice and any modifiers."""

    damage_type: str
    was_resisted: bool
    was_vulnerable: bool
    was_immune: bool
    saved: bool | None
    """None if no saving throw applied; True if the target succeeded the save."""

    save_roll: D20Result | None


@dataclass
class HealingApplication:
    """Healing outcome for one target."""

    target_index: int
    healing_amount: int


@dataclass
class ConditionApplication:
    """Condition application outcome for one target."""

    target_index: int
    condition_name: str
    applied: bool
    """True when the condition was applied (target failed the save or no save required)."""

    save_roll: D20Result | None


@dataclass
class SpellResult:
    """Complete result of resolving one spell cast.

    ``attack_result`` is set for single-target spell attacks (e.g. Fire Bolt).
    Multi-target attack spells in M2 will require a revised field.
    ``healing`` is None for non-healing spells; empty list is not used.
    ``damage`` is always a list (empty when the spell deals no damage).
    """

    spell_name: str
    slot_consumed: int | None
    """None for cantrips; the slot level used for levelled spells."""

    attack_result: AttackResult | None
    damage: list[DamageApplication]
    healing: list[HealingApplication] | None
    conditions_applied: list[ConditionApplication]
    concentration_required: bool
    description: str
    """Human-readable summary for the Context Builder's rules_result field."""


# ---------------------------------------------------------------------------
# Condition map — spells that apply conditions (5e-database lacks structured field)
# ---------------------------------------------------------------------------

_CONDITION_MAP: dict[str, str] = {
    "hold-person": ConditionName.PARALYZED,
    "hold-monster": ConditionName.PARALYZED,
    "entangle": ConditionName.RESTRAINED,
    "web": ConditionName.RESTRAINED,
    "blindness-deafness": ConditionName.BLINDED,
    "fear": ConditionName.FRIGHTENED,
    "hideous-laughter": ConditionName.INCAPACITATED,
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _normalize_dice(notation: str) -> str:
    """Strip internal spaces so dice.roll() can parse the notation."""
    return notation.replace(" ", "")


def _sub_mod(notation: str, modifier: int) -> str:
    """Replace the 'MOD' placeholder in heal_at_slot_level values.

    5e-database heal_at_slot_level values use ``MOD`` as a stand-in for the
    caster's spellcasting ability modifier (e.g. ``"1d8 + MOD"``).
    """
    if "MOD" not in notation:
        return _normalize_dice(notation)
    if modifier >= 0:
        substituted = notation.replace("MOD", str(modifier))
    else:
        # Replace "+ MOD" with "- abs(modifier)" to avoid double-sign ("+-1")
        substituted = re.sub(r"\+\s*MOD", f"-{abs(modifier)}", notation)
    return _normalize_dice(substituted)


def _cantrip_dice(damage_at_char_level: dict[str, str], char_level: int) -> str:
    """Select cantrip damage dice for *char_level* using threshold logic.

    ``damage_at_char_level`` has sparse keys like ``"1"``, ``"5"``, ``"11"``,
    ``"17"``.  Returns the dice notation for the highest threshold ≤ char_level.
    """
    thresholds = sorted(int(k) for k in damage_at_char_level)
    best = max((t for t in thresholds if t <= char_level), default=thresholds[0])
    return _normalize_dice(damage_at_char_level[str(best)])


def _is_per_projectile(spell: dict) -> bool:
    """Return True when all damage_at_slot_level values are identical.

    When every slot level has the same dice string, the spell fires multiple
    independent projectiles (e.g. Magic Missile) rather than scaling dice.
    """
    dasl = spell.get("damage", {}).get("damage_at_slot_level", {})
    if len(dasl) < 2:
        return False
    return len(set(dasl.values())) == 1


def _projectile_count(spell: dict, slot_level: int) -> int:
    """Parse the base projectile count from the spell's desc and scale by slot.

    Looks for "you create N [darts/missiles/…]" in the description.
    Scales as: base + (slot_level - spell_level).
    Falls back to 1 if the count cannot be parsed.
    """
    desc = " ".join(spell.get("desc", []))
    m = re.search(r"you create (\w+)", desc, re.IGNORECASE)
    if m:
        word = m.group(1).lower()
        base: int | None = _NUMBER_WORDS.get(word)
        if base is None and word.isdigit():
            base = int(word)
        if base is not None:
            return base + (slot_level - spell["level"])
    return 1


def _target_save_mod(target: dict, ability: str) -> int:
    """Return the target's saving throw modifier for *ability*.

    Prefers an explicit ``saving_throw_modifiers`` dict; falls back to
    deriving from ``ability_scores``.
    """
    st = target.get("saving_throw_modifiers", {})
    if ability.upper() in st:
        return st[ability.upper()]
    score = target.get("ability_scores", {}).get(ability.upper(), 10)
    return ability_modifier(score)


def _seed_at(seed: int | None, offset: int) -> int | None:
    return (seed + offset) if seed is not None else None


def _apply_rv(
    raw: int,
    damage_type: str,
    resistances: frozenset[str],
    vulnerabilities: frozenset[str],
    immunities: frozenset[str],
) -> tuple[int, bool, bool, bool]:
    """Apply resistance / vulnerability / immunity in SRD order.

    Returns (total, was_resisted, was_vulnerable, was_immune).
    Mirrors the logic in combat._apply_resistance_vulnerability.
    """
    was_immune = damage_type in immunities
    was_resisted = damage_type in resistances and not was_immune
    was_vulnerable = damage_type in vulnerabilities and not was_immune

    if was_immune:
        return 0, False, False, True

    total = raw
    if was_resisted:
        total = total // 2
    if was_vulnerable:
        total = total * 2

    return total, was_resisted, was_vulnerable, False


def _build_description(
    spell_name: str,
    has_attack: bool,
    damages: list[DamageApplication],
    healings: list[HealingApplication] | None,
    conditions: list[ConditionApplication],
    attack_result: AttackResult | None,
) -> str:
    parts = [f"{spell_name}:"]

    if has_attack and attack_result is not None:
        outcome = "hit" if attack_result.hit else "missed"
        parts.append(f"spell attack {outcome} (roll {attack_result.attack_roll.total})")

    if damages:
        total_dmg = sum(d.damage_total for d in damages)
        dtype = damages[0].damage_type
        parts.append(f"{total_dmg} {dtype} damage")
        saved_count = sum(1 for d in damages if d.saved)
        if any(d.saved is not None for d in damages):
            parts.append(f"({saved_count}/{len(damages)} target(s) saved)")

    if healings:
        total_heal = sum(h.healing_amount for h in healings)
        parts.append(f"healed {total_heal} HP")

    if conditions:
        applied = [c for c in conditions if c.applied]
        if applied:
            cond_name = applied[0].condition_name
            parts.append(f"{cond_name} applied to {len(applied)}/{len(conditions)} target(s)")
        else:
            parts.append("all targets saved against condition")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_spell(
    spell_index: str,
    caster: dict,
    targets: list[dict],
    slot_level: int | None = None,
    campaign_id: str | None = None,
    seed: int | None = None,
) -> SpellResult:
    """Resolve a spell cast and return all mechanical outcomes.

    Args:
        spell_index:  Lowercase slug matching the 5e-database ``index`` field
                      (e.g. ``"fireball"``, ``"fire-bolt"``).
        caster:       Character state snapshot.  Expected keys:
                      ``level`` (int), ``ability_scores`` (dict[str, int]),
                      ``spellcasting_ability`` (str, e.g. ``"INT"``).
        targets:      List of target state snapshots.  Each target dict may
                      contain ``ac`` (int), ``ability_scores`` (dict[str, int]),
                      ``saving_throw_modifiers`` (dict[str, int]),
                      ``resistances`` / ``vulnerabilities`` / ``immunities``
                      (list[str] of damage type names).
        slot_level:   None for cantrips; the slot expended for levelled spells.
                      Must be ≥ the spell's level; availability is the caller's
                      responsibility.
        campaign_id:  Passed through to the three-tier SRD lookup.
        seed:         Integer seed for reproducible dice rolls.

    Returns:
        A ``SpellResult`` with all mechanical outcomes filled in.

    Raises:
        ValueError: If the spell is not found, the slot level is too low, or
                    a cantrip is cast with a slot (slot_level not None).
    """
    # ------------------------------------------------------------------
    # 1. Fetch spell document
    # ------------------------------------------------------------------
    spell = await srd_data.get_spell(spell_index, campaign_id)
    if spell is None:
        raise ValueError(f"Unknown spell: {spell_index!r}")

    spell_name: str = spell["name"]
    spell_level: int = int(spell["level"])
    is_cantrip = spell_level == 0
    concentration_required = bool(spell.get("concentration", False))

    # ------------------------------------------------------------------
    # 2. Validate slot level
    # ------------------------------------------------------------------
    if is_cantrip:
        slot_consumed: int | None = None
    else:
        if slot_level is None:
            raise ValueError(f"{spell_name!r} requires a spell slot (minimum level {spell_level})")
        if slot_level < spell_level:
            raise ValueError(
                f"Slot level {slot_level} is too low for {spell_name!r} "
                f"(minimum slot level {spell_level})"
            )
        slot_consumed = slot_level

    effective_slot = slot_level if slot_level is not None else 0

    # ------------------------------------------------------------------
    # 3. Derive caster stats
    # ------------------------------------------------------------------
    caster_level: int = int(caster.get("level", 1))
    prof_bonus = await srd_data.get_proficiency_bonus(caster_level)
    sc_ability: str = caster.get("spellcasting_ability", "INT")
    sc_score: int = caster.get("ability_scores", {}).get(sc_ability, 10)
    sc_mod = ability_modifier(sc_score)
    spell_save_dc = 8 + prof_bonus + sc_mod
    spell_attack_mod = prof_bonus + sc_mod

    # ------------------------------------------------------------------
    # 4. Route by resolution type
    # ------------------------------------------------------------------
    has_attack = "attack_type" in spell
    has_save = "dc" in spell

    damages: list[DamageApplication] = []
    healings: list[HealingApplication] | None = None
    conditions: list[ConditionApplication] = []
    first_attack_result: AttackResult | None = None

    spell_damage: dict = spell.get("damage", {})
    damage_type_name: str = spell_damage.get("damage_type", {}).get("name", "")

    # ------------------------------------------------------------------
    # 4a. Spell attack roll
    # ------------------------------------------------------------------
    if has_attack:
        if is_cantrip:
            dasl = spell_damage.get("damage_at_character_level", {})
            damage_dice = _cantrip_dice(dasl, caster_level)
        else:
            dasl = spell_damage.get("damage_at_slot_level", {})
            damage_dice = _normalize_dice(dasl.get(str(effective_slot), dasl.get("1", "1d6")))

        for i, target in enumerate(targets):
            target_seed = _seed_at(seed, i * 10)
            ar = resolve_attack(
                attack_modifier=spell_attack_mod,
                target_ac=int(target.get("ac", 10)),
                damage_dice=damage_dice,
                damage_modifier=0,
                damage_type=damage_type_name,
                target_resistances=frozenset(target.get("resistances", [])),
                target_vulnerabilities=frozenset(target.get("vulnerabilities", [])),
                target_immunities=frozenset(target.get("immunities", [])),
                seed=target_seed,
            )
            if i == 0:
                first_attack_result = ar
            if ar.hit and ar.damage is not None:
                d = ar.damage
                damages.append(
                    DamageApplication(
                        target_index=i,
                        damage_total=d.total,
                        raw_damage=d.raw_total,
                        damage_type=d.damage_type,
                        was_resisted=d.was_resisted,
                        was_vulnerable=d.was_vulnerable,
                        was_immune=d.was_immune,
                        saved=None,
                        save_roll=None,
                    )
                )

    # ------------------------------------------------------------------
    # 4b. Saving throw
    # ------------------------------------------------------------------
    elif has_save:
        dc_info: dict = spell["dc"]
        save_ability: str = dc_info["dc_type"]["name"].upper()
        dc_success: str = dc_info.get("dc_success", "none")  # "half" or "none"

        raw_damage_dice: str | None = None
        if spell_damage:
            dasl = spell_damage.get("damage_at_slot_level", {})
            raw = dasl.get(str(effective_slot), dasl.get("1", ""))
            raw_damage_dice = _normalize_dice(raw) if raw else None

        cond_name: str | None = _CONDITION_MAP.get(spell["index"])

        for i, target in enumerate(targets):
            save_seed = _seed_at(seed, i * 10)
            dmg_seed = _seed_at(seed, 100 + i * 10)

            save_mod = _target_save_mod(target, save_ability)
            save_roll = roll_d20(modifier=save_mod, seed=save_seed)
            saved = save_roll.total >= spell_save_dc

            if raw_damage_dice:
                dice_result = roll(raw_damage_dice, seed=dmg_seed)
                raw_dmg = max(0, dice_result.total)

                if saved and dc_success == "none":
                    final_dmg = 0
                elif saved and dc_success == "half":
                    final_dmg = raw_dmg // 2
                else:
                    final_dmg = raw_dmg

                resistances = frozenset(target.get("resistances", []))
                vulnerabilities = frozenset(target.get("vulnerabilities", []))
                immunities = frozenset(target.get("immunities", []))
                total, was_resisted, was_vulnerable, was_immune = _apply_rv(
                    final_dmg, damage_type_name, resistances, vulnerabilities, immunities
                )

                damages.append(
                    DamageApplication(
                        target_index=i,
                        damage_total=total,
                        raw_damage=raw_dmg,
                        damage_type=damage_type_name,
                        was_resisted=was_resisted,
                        was_vulnerable=was_vulnerable,
                        was_immune=was_immune,
                        saved=saved,
                        save_roll=save_roll,
                    )
                )

            if cond_name is not None:
                conditions.append(
                    ConditionApplication(
                        target_index=i,
                        condition_name=cond_name,
                        applied=not saved,
                        save_roll=save_roll,
                    )
                )

    # ------------------------------------------------------------------
    # 4c. Auto-hit (Magic Missile, Cure Wounds, etc.)
    # ------------------------------------------------------------------
    else:
        heal_at_slot: dict = spell.get("heal_at_slot_level", {})

        if heal_at_slot:
            # Healing spell
            healings = []
            heal_dice_str: str = heal_at_slot.get(
                str(effective_slot), heal_at_slot.get("1", "1d8")
            )
            heal_dice = _sub_mod(heal_dice_str, sc_mod)

            for i, target in enumerate(targets):
                heal_seed = _seed_at(seed, i * 10)
                heal_result = roll(heal_dice, seed=heal_seed)
                amount = max(1, heal_result.total)
                healings.append(HealingApplication(target_index=i, healing_amount=amount))

        elif spell_damage:
            # Auto-hit damage (Magic Missile and similar)
            dasl = spell_damage.get("damage_at_slot_level", {})
            per_proj_dice = _normalize_dice(dasl.get(str(effective_slot), dasl.get("1", "1d4")))

            dart_count = (
                _projectile_count(spell, effective_slot) if _is_per_projectile(spell) else 1
            )

            for i, target in enumerate(targets):
                resistances = frozenset(target.get("resistances", []))
                vulnerabilities = frozenset(target.get("vulnerabilities", []))
                immunities = frozenset(target.get("immunities", []))

                total_raw = 0
                for dart in range(dart_count):
                    dart_seed = _seed_at(seed, i * 100 + dart)
                    d_result = roll(per_proj_dice, seed=dart_seed)
                    total_raw += d_result.total

                total_raw = max(0, total_raw)
                total, was_resisted, was_vulnerable, was_immune = _apply_rv(
                    total_raw, damage_type_name, resistances, vulnerabilities, immunities
                )

                damages.append(
                    DamageApplication(
                        target_index=i,
                        damage_total=total,
                        raw_damage=total_raw,
                        damage_type=damage_type_name,
                        was_resisted=was_resisted,
                        was_vulnerable=was_vulnerable,
                        was_immune=was_immune,
                        saved=None,
                        save_roll=None,
                    )
                )

    # ------------------------------------------------------------------
    # 5. Build description and return
    # ------------------------------------------------------------------
    description = _build_description(
        spell_name, has_attack, damages, healings, conditions, first_attack_result
    )

    return SpellResult(
        spell_name=spell_name,
        slot_consumed=slot_consumed,
        attack_result=first_attack_result,
        damage=damages,
        healing=healings,
        conditions_applied=conditions,
        concentration_required=concentration_required,
        description=description,
    )
