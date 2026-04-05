import { useEffect } from 'react'
import type { CharacterState } from '../types'
import { SKILL_ABILITY_MAP, CONDITION_SUMMARIES } from '../constants'

interface Props {
  character: CharacterState
  onClose: () => void
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ABILITY_ABBREVS = ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'] as const

const ABILITY_FULL: Record<string, string> = {
  STR: 'Strength', DEX: 'Dexterity', CON: 'Constitution',
  INT: 'Intelligence', WIS: 'Wisdom', CHA: 'Charisma',
}

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

function abilityMod(score: number): number {
  return Math.floor((score - 10) / 2)
}

function calcProfBonus(level: number): number {
  return Math.floor((level - 1) / 4) + 2
}

function modStr(mod: number): string {
  return mod >= 0 ? `+${mod}` : `${mod}`
}

function hasProficiency(character: CharacterState, name: string): boolean {
  if (!character.proficiencies?.length) return false
  const lower = name.toLowerCase()
  return character.proficiencies.some((p) => p.toLowerCase() === lower)
}

// Saving throw proficiency accepts the abbreviation ("STR"), full name
// ("Strength"), or "Strength saving throw" — whichever the server sends.
function hasSaveProficiency(character: CharacterState, abbr: string): boolean {
  if (!character.proficiencies?.length) return false
  const full = ABILITY_FULL[abbr] ?? ''
  const lower = abbr.toLowerCase()
  return character.proficiencies.some((p) => {
    const pl = p.toLowerCase()
    return pl === lower || pl === full.toLowerCase() || pl.startsWith(full.toLowerCase() + ' saving')
  })
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Pips({ current, max }: { current: number; max: number }) {
  if (max > 9) return <span style={s.pipText}>{current} / {max}</span>
  return (
    <span>
      {Array.from({ length: max }).map((_, i) => (
        <span
          key={i}
          style={{ color: i < current ? 'var(--color-gold)' : 'var(--color-border)', fontSize: '0.8rem' }}
        >
          {i < current ? '●' : '○'}
        </span>
      ))}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CharacterSheetOverlay({ character, onClose }: Props) {
  const profBonus = character.proficiency_bonus ?? calcProfBonus(character.level)
  const scores = character.ability_scores

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const hpPct = Math.max(0, Math.min(100, (character.hp / character.max_hp) * 100))
  const hpColor =
    hpPct > 60 ? 'var(--color-success)' : hpPct > 30 ? 'var(--color-gold)' : 'var(--color-danger)'

  const subtitleParts = [character.species, character.class_name, `— Level ${character.level}`]
    .filter(Boolean)
  const subtitle = subtitleParts.join(' ')

  const initiativeMod =
    character.initiative_modifier ?? (scores ? abilityMod(scores['DEX'] ?? 10) : null)

  const hasSpellSlots = Object.keys(character.spell_slots).length > 0
  const hasSpells = (character.spells?.length ?? 0) > 0
  const hasFeatures = Object.keys(character.features ?? {}).length > 0
  const hasInventory = (character.inventory?.length ?? 0) > 0
  const hasConditions = (character.conditions?.length ?? 0) > 0

  return (
    <div style={s.backdrop} onClick={onClose}>
      <div
        style={s.panel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Character sheet: ${character.name}`}
      >
        <button style={s.closeBtn} onClick={onClose} title="Close">×</button>

        {/* ── Header ───────────────────────────────────────── */}
        <div style={s.header}>
          <h2 style={s.charName}>{character.name}</h2>
          <p style={s.subtitle}>{subtitle}</p>

          <div style={s.hpRow}>
            <span style={s.hpLabel}>HP {character.hp} / {character.max_hp}</span>
            <div style={s.hpTrack}>
              <div style={{ ...s.hpFill, width: `${hpPct}%`, background: hpColor }} />
            </div>
          </div>

          <div style={s.inlineStats}>
            <span>AC {character.ac}</span>
            {character.speed != null && <span>· Speed {character.speed} ft</span>}
            {initiativeMod != null && <span>· Initiative {modStr(initiativeMod)}</span>}
            <span>· Proficiency {modStr(profBonus)}</span>
          </div>
        </div>

        {/* ── Ability Scores ────────────────────────────────── */}
        {scores && (
          <section style={s.section}>
            <h3 style={s.sectionTitle}>Ability Scores</h3>
            <div style={s.abilityGrid}>
              {ABILITY_ABBREVS.map((abbr) => {
                const score = scores[abbr] ?? 10
                const mod = abilityMod(score)
                return (
                  <div key={abbr} style={s.abilityCell}>
                    <span style={s.abilityAbbr}>{abbr}</span>
                    <span style={s.abilityScore}>{score}</span>
                    <span style={s.abilityModifier}>{modStr(mod)}</span>
                  </div>
                )
              })}
            </div>
            {(() => {
              const wisMod = abilityMod(scores['WIS'] ?? 10)
              const percProf = hasProficiency(character, 'Perception')
              const pp = 10 + wisMod + (percProf ? profBonus : 0)
              return <p style={s.passivePerc}>Passive Perception: {pp}</p>
            })()}
          </section>
        )}

        {/* ── Saving Throws ─────────────────────────────────── */}
        {scores && (
          <section style={s.section}>
            <h3 style={s.sectionTitle}>Saving Throws</h3>
            <div style={s.twoColGrid}>
              {ABILITY_ABBREVS.map((abbr) => {
                const score = scores[abbr] ?? 10
                const mod = abilityMod(score)
                const prof = hasSaveProficiency(character, abbr)
                const total = mod + (prof ? profBonus : 0)
                return (
                  <div key={abbr} style={s.checkRow}>
                    <span style={{ ...s.profDot, color: prof ? 'var(--color-gold)' : 'var(--color-parchment-dim)' }}>
                      {prof ? '●' : '○'}
                    </span>
                    <span style={s.checkLabel}>{abbr}</span>
                    <span style={s.checkValue}>{modStr(total)}</span>
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {/* ── Skills ────────────────────────────────────────── */}
        {scores && (
          <section style={s.section}>
            <h3 style={s.sectionTitle}>Skills</h3>
            <div style={s.threeColGrid}>
              {Object.entries(SKILL_ABILITY_MAP).map(([skill, ability]) => {
                const score = scores[ability] ?? 10
                const mod = abilityMod(score)
                const prof = hasProficiency(character, skill)
                const total = mod + (prof ? profBonus : 0)
                return (
                  <div key={skill} style={s.checkRow}>
                    <span style={{ ...s.profDot, color: prof ? 'var(--color-gold)' : 'var(--color-parchment-dim)' }}>
                      {prof ? '●' : '○'}
                    </span>
                    <span style={s.checkLabel}>
                      {skill} <span style={s.abilityTag}>({ability})</span>
                    </span>
                    <span style={s.checkValue}>{modStr(total)}</span>
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {/* ── Spell Slots ───────────────────────────────────── */}
        {hasSpellSlots && (
          <section style={s.section}>
            <h3 style={s.sectionTitle}>Spell Slots</h3>
            <div style={s.slotGrid}>
              {Object.entries(character.spell_slots)
                .sort(([a], [b]) => Number(a) - Number(b))
                .map(([level, current]) => {
                  const max = character.spell_slots_max?.[level] ?? current
                  return (
                    <div key={level} style={s.slotRow}>
                      <span style={s.slotLabel}>Level {level}</span>
                      <Pips current={current} max={max} />
                    </div>
                  )
                })}
            </div>
          </section>
        )}

        {/* ── Spells Known / Prepared ───────────────────────── */}
        {hasSpells && (
          <section style={s.section}>
            <h3 style={s.sectionTitle}>Spells</h3>
            {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((lvl) => {
              const group = character.spells!.filter((sp) => sp.level === lvl)
              if (group.length === 0) return null
              return (
                <div key={lvl} style={s.spellGroup}>
                  <span style={s.spellGroupLabel}>
                    {lvl === 0 ? 'Cantrips' : `Level ${lvl}`}
                  </span>
                  {group.map((sp) => (
                    <div key={sp.name} style={s.spellRow}>
                      <span style={s.spellName}>{sp.name}</span>
                      {sp.school && <span style={s.spellMeta}>{sp.school}</span>}
                      {sp.damage && <span style={s.spellMeta}>{sp.damage}</span>}
                    </div>
                  ))}
                </div>
              )
            })}
          </section>
        )}

        {/* ── Class Features & Traits ───────────────────────── */}
        {hasFeatures && (
          <section style={s.section}>
            <h3 style={s.sectionTitle}>Class Features & Traits</h3>
            {Object.entries(character.features).map(([name, desc]) => (
              <div key={name} style={s.featureRow}>
                <span style={s.featureName}>{name}</span>
                {typeof desc === 'string' && desc && (
                  <span style={s.featureDesc}>{desc}</span>
                )}
              </div>
            ))}
          </section>
        )}

        {/* ── Equipment ─────────────────────────────────────── */}
        {hasInventory && (
          <section style={s.section}>
            <h3 style={s.sectionTitle}>Equipment</h3>
            {character.inventory!.map((item, i) => (
              <div key={item.id ?? i} style={s.itemRow}>
                <span style={s.itemName}>{item.name}</span>
                {item.damage && <span style={s.itemMeta}>{item.damage}</span>}
                {item.ac_bonus != null && <span style={s.itemMeta}>+{item.ac_bonus} AC</span>}
              </div>
            ))}
          </section>
        )}

        {/* ── Conditions ────────────────────────────────────── */}
        {hasConditions && (
          <section style={s.section}>
            <h3 style={s.sectionTitle}>Conditions</h3>
            {character.conditions!.map((cond) => (
              <div key={cond} style={s.conditionRow}>
                <span style={s.conditionName}>{cond}</span>
                {CONDITION_SUMMARIES[cond] && (
                  <span style={s.conditionDesc}>{CONDITION_SUMMARIES[cond]}</span>
                )}
              </div>
            ))}
          </section>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const s: Record<string, React.CSSProperties> = {
  backdrop: {
    position: 'fixed',
    inset: 0,
    zIndex: 100,
    background: 'rgba(0, 0, 0, 0.75)',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'flex-start',
    padding: '2rem 1rem',
    overflowY: 'auto',
  },
  panel: {
    position: 'relative',
    width: '100%',
    maxWidth: 'min(90vw, 38rem)',
    background: 'var(--color-bg-panel)',
    border: '1px solid var(--color-border)',
    borderRadius: '6px',
    padding: '1.75rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0',
  },
  closeBtn: {
    position: 'absolute',
    top: '0.75rem',
    right: '0.75rem',
    background: 'transparent',
    border: 'none',
    color: 'var(--color-parchment-dim)',
    fontSize: '1.4rem',
    lineHeight: 1,
    cursor: 'pointer',
    padding: '0.1rem 0.3rem',
  },

  // Header
  header: {
    marginBottom: '1.25rem',
    paddingBottom: '1rem',
    borderBottom: '1px solid var(--color-border)',
  },
  charName: {
    fontSize: '1.6rem',
    color: 'var(--color-gold)',
    fontFamily: 'var(--font-serif)',
    marginBottom: '0.15rem',
  },
  subtitle: {
    fontSize: '0.85rem',
    color: 'var(--color-parchment-dim)',
    marginBottom: '0.75rem',
    fontStyle: 'italic',
  },
  hpRow: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.2rem',
    marginBottom: '0.6rem',
  },
  hpLabel: {
    fontSize: '0.8rem',
    color: 'var(--color-parchment-dim)',
  },
  hpTrack: {
    height: '0.3rem',
    background: 'var(--color-border)',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  hpFill: {
    height: '100%',
    borderRadius: '3px',
    transition: 'width 0.3s',
  },
  inlineStats: {
    display: 'flex',
    gap: '0.6rem',
    flexWrap: 'wrap',
    fontSize: '0.8rem',
    color: 'var(--color-parchment)',
  },

  // Section
  section: {
    paddingTop: '1rem',
    paddingBottom: '0.75rem',
    borderBottom: '1px solid var(--color-border)',
  },
  sectionTitle: {
    fontSize: '0.65rem',
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    color: 'var(--color-gold-dim)',
    marginBottom: '0.65rem',
  },

  // Ability scores
  abilityGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(6, 1fr)',
    gap: '0.4rem',
    marginBottom: '0.5rem',
  },
  abilityCell: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    borderRadius: '4px',
    padding: '0.4rem 0.2rem',
    gap: '0.1rem',
  },
  abilityAbbr: {
    fontSize: '0.6rem',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: 'var(--color-gold-dim)',
  },
  abilityScore: {
    fontSize: '1rem',
    fontWeight: 700,
    color: 'var(--color-parchment)',
  },
  abilityModifier: {
    fontSize: '0.75rem',
    color: 'var(--color-parchment-dim)',
  },
  passivePerc: {
    fontSize: '0.78rem',
    color: 'var(--color-parchment-dim)',
    marginTop: '0.4rem',
  },

  // Saving throws / skills grid
  twoColGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: '0.25rem 1rem',
  },
  threeColGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gap: '0.25rem 0.5rem',
  },
  checkRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.3rem',
    minWidth: 0,
  },
  profDot: {
    fontSize: '0.6rem',
    flexShrink: 0,
  },
  checkLabel: {
    fontSize: '0.75rem',
    color: 'var(--color-parchment)',
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  checkValue: {
    fontSize: '0.75rem',
    color: 'var(--color-parchment-dim)',
    flexShrink: 0,
    minWidth: '2rem',
    textAlign: 'right',
  },
  abilityTag: {
    color: 'var(--color-parchment-dim)',
    fontSize: '0.65rem',
  },

  // Spell slots
  slotGrid: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.3rem',
  },
  slotRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    fontSize: '0.8rem',
  },
  slotLabel: {
    color: 'var(--color-parchment-dim)',
    width: '4rem',
    flexShrink: 0,
  },
  pipText: {
    color: 'var(--color-parchment)',
    fontSize: '0.8rem',
  },

  // Spells
  spellGroup: {
    marginBottom: '0.6rem',
  },
  spellGroupLabel: {
    display: 'block',
    fontSize: '0.7rem',
    color: 'var(--color-gold-dim)',
    letterSpacing: '0.06em',
    marginBottom: '0.2rem',
  },
  spellRow: {
    display: 'flex',
    gap: '0.6rem',
    alignItems: 'baseline',
    paddingLeft: '0.5rem',
  },
  spellName: {
    fontSize: '0.82rem',
    color: 'var(--color-parchment)',
  },
  spellMeta: {
    fontSize: '0.72rem',
    color: 'var(--color-parchment-dim)',
    fontStyle: 'italic',
  },

  // Features
  featureRow: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.1rem',
    marginBottom: '0.5rem',
  },
  featureName: {
    fontSize: '0.82rem',
    fontWeight: 700,
    color: 'var(--color-parchment)',
  },
  featureDesc: {
    fontSize: '0.78rem',
    color: 'var(--color-parchment-dim)',
    lineHeight: 1.55,
  },

  // Equipment
  itemRow: {
    display: 'flex',
    gap: '0.6rem',
    alignItems: 'baseline',
    marginBottom: '0.25rem',
  },
  itemName: {
    fontSize: '0.82rem',
    color: 'var(--color-parchment)',
  },
  itemMeta: {
    fontSize: '0.72rem',
    color: 'var(--color-parchment-dim)',
    fontStyle: 'italic',
  },

  // Conditions
  conditionRow: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.1rem',
    marginBottom: '0.5rem',
  },
  conditionName: {
    fontSize: '0.82rem',
    fontWeight: 700,
    color: 'var(--color-gold)',
  },
  conditionDesc: {
    fontSize: '0.78rem',
    color: 'var(--color-parchment-dim)',
    lineHeight: 1.5,
  },
}
