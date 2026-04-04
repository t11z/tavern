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
