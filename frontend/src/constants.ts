export const SRD_CLASSES = [
  'Barbarian',
  'Bard',
  'Cleric',
  'Druid',
  'Fighter',
  'Monk',
  'Paladin',
  'Ranger',
  'Rogue',
  'Sorcerer',
  'Warlock',
  'Wizard',
]

export const SRD_SPECIES = [
  'Human',
  'Elf',
  'Dwarf',
  'Halfling',
  'Gnome',
  'Half-Elf',
  'Half-Orc',
  'Tiefling',
  'Dragonborn',
]

export interface BackgroundDef {
  name: string
  /** Three abilities eligible for the +2/+1 bonus. */
  eligible: [string, string, string]
}

// SRD 5.2.1 backgrounds only (p.83-86). Non-SRD backgrounds removed per ADR-0010.
export const BACKGROUNDS: BackgroundDef[] = [
  { name: 'Acolyte', eligible: ['INT', 'WIS', 'CHA'] },
  { name: 'Criminal', eligible: ['DEX', 'INT', 'CHA'] },
  { name: 'Sage', eligible: ['CON', 'INT', 'WIS'] },
  { name: 'Soldier', eligible: ['STR', 'DEX', 'CON'] },
]

export const ABILITIES = ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'] as const

export const STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]

export const TONE_PRESETS = [
  { value: 'classic_fantasy', label: 'Classic Fantasy' },
  { value: 'dark_gritty', label: 'Dark & Gritty' },
  { value: 'lighthearted', label: 'Lighthearted' },
  { value: 'epic_high_fantasy', label: 'Epic High Fantasy' },
  { value: 'mystery_intrigue', label: 'Mystery & Intrigue' },
]

export const ABILITY_EMOJIS: Record<string, string> = {
  STR: '💪', DEX: '🏹', CON: '❤️', INT: '📚', WIS: '🦉', CHA: '✨',
}

export const SKILL_ABILITY_MAP: Record<string, string> = {
  'Acrobatics': 'DEX', 'Animal Handling': 'WIS', 'Arcana': 'INT',
  'Athletics': 'STR', 'Deception': 'CHA', 'History': 'INT',
  'Insight': 'WIS', 'Intimidation': 'CHA', 'Investigation': 'INT',
  'Medicine': 'WIS', 'Nature': 'INT', 'Perception': 'WIS',
  'Performance': 'CHA', 'Persuasion': 'CHA', 'Religion': 'INT',
  'Sleight of Hand': 'DEX', 'Stealth': 'DEX', 'Survival': 'WIS',
}

export const CONDITION_SUMMARIES: Record<string, string> = {
  'Blinded': 'Auto-fail sight checks; attacks against you have advantage.',
  'Charmed': 'Cannot attack the charmer; charmer has advantage on social checks.',
  'Deafened': 'Auto-fail hearing checks.',
  'Exhaustion': 'Cumulative penalties; at level 6: death.',
  'Frightened': 'Disadvantage on checks/attacks while source is in sight; cannot move closer.',
  'Grappled': 'Speed becomes 0.',
  'Incapacitated': 'Cannot take actions or reactions.',
  'Invisible': 'Attacks against you have disadvantage; your attacks have advantage.',
  'Paralyzed': 'Incapacitated; auto-fail STR/DEX saves; attacks have advantage; hits within 5 ft crit.',
  'Petrified': 'Transformed to stone; incapacitated; resistant to all damage.',
  'Poisoned': 'Disadvantage on attack rolls and ability checks.',
  'Prone': 'Disadvantage on attack rolls; melee attacks against you have advantage.',
  'Restrained': 'Speed 0; disadvantage on attacks and DEX saves; attacks against you have advantage.',
  'Stunned': 'Incapacitated; auto-fail STR/DEX saves; attacks against you have advantage.',
  'Unconscious': 'Incapacitated, prone; auto-fail STR/DEX saves; attacks have advantage; hits within 5 ft crit.',
}
