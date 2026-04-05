import { useEffect, useRef, useState } from 'react'
import type { MechanicalResultEntry, TurnMechanicalGroup } from '../types'

// ---------------------------------------------------------------------------
// Colour class helpers
// ---------------------------------------------------------------------------

function colourClass(entry: MechanicalResultEntry): string {
  switch (entry.type) {
    case 'attack_roll':
      return entry.outcome === 'hit' ? 'mech-success' : 'mech-fail'
    case 'saving_throw':
      return entry.outcome === 'pass' || entry.outcome === 'success' ? 'mech-success' : 'mech-fail'
    case 'ability_check':
      return entry.outcome === 'pass' || entry.outcome === 'success' ? 'mech-success' : 'mech-fail'
    case 'damage': {
      const hpAfter = entry.hp_after as number | undefined
      return typeof hpAfter === 'number' && hpAfter <= 0 ? 'mech-fail' : 'mech-warning'
    }
    case 'healing':
      return 'mech-success'
    case 'condition_applied':
      return 'mech-warning'
    case 'condition_removed':
      return 'mech-neutral'
    case 'spell_cast':
      return 'mech-neutral'
    case 'combat_started':
    case 'combat_ended':
      return 'mech-neutral'
    case 'rest_result':
      return 'mech-success'
    default:
      return 'mech-neutral'
  }
}

// ---------------------------------------------------------------------------
// Entry renderers
// ---------------------------------------------------------------------------

function renderAttackRoll(e: MechanicalResultEntry): React.ReactNode {
  const actor = e.actor as string | undefined
  const target = e.target as string | undefined
  const total = e.total as number | undefined
  const roll = e.roll as number | undefined
  const modifier = e.modifier as number | undefined
  const ac = e.target_ac as number | undefined
  const outcome = (e.outcome as string | undefined)?.toUpperCase() ?? ''

  return (
    <>
      <span style={s.entryMain}>
        {actor} → {target}
        <span style={s.outcomeLabel}>{outcome}</span>
      </span>
      <span style={s.entryDetail}>
        Attack: {total}{roll !== undefined && modifier !== undefined ? ` (${roll}+${modifier})` : ''}
        {ac !== undefined ? ` vs AC ${ac}` : ''}
      </span>
    </>
  )
}

function renderDamage(e: MechanicalResultEntry): React.ReactNode {
  const target = e.target as string | undefined
  const amount = e.amount as number | undefined
  const damageType = e.damage_type as string | undefined
  const hpBefore = e.hp_before as number | undefined
  const hpAfter = e.hp_after as number | undefined

  return (
    <>
      <span style={s.entryMain}>
        {target}: {amount} {damageType}
      </span>
      {hpBefore !== undefined && hpAfter !== undefined && (
        <span style={s.entryDetail}>
          {hpBefore} HP → {hpAfter} HP
          {hpAfter <= 0 ? ' · Defeated' : ''}
        </span>
      )}
    </>
  )
}

function renderHealing(e: MechanicalResultEntry): React.ReactNode {
  const target = e.target as string | undefined
  const amount = e.amount as number | undefined
  const hpBefore = e.hp_before as number | undefined
  const hpAfter = e.hp_after as number | undefined

  return (
    <>
      <span style={s.entryMain}>
        {target}: +{amount} HP
      </span>
      {hpBefore !== undefined && hpAfter !== undefined && (
        <span style={s.entryDetail}>
          {hpBefore} HP → {hpAfter} HP
        </span>
      )}
    </>
  )
}

function renderSavingThrow(e: MechanicalResultEntry): React.ReactNode {
  const target = e.target as string | undefined
  const ability = e.ability as string | undefined
  const roll = e.roll as number | undefined
  const dc = e.dc as number | undefined
  const outcome = e.outcome as string | undefined
  const outcomeLabel = outcome === 'pass' || outcome === 'success' ? 'Pass' : 'Fail'

  return (
    <span style={s.entryMain}>
      {target}: {ability} save {roll} vs DC {dc} — {outcomeLabel}
    </span>
  )
}

function renderSpellCast(e: MechanicalResultEntry): React.ReactNode {
  const caster = e.caster as string | undefined
  const spellName = e.spell_name as string | undefined
  const slotLevel = e.slot_level as string | number | undefined
  const targets = e.targets as string[] | undefined

  return (
    <>
      <span style={s.entryMain}>
        {caster} — {spellName}
        {slotLevel !== undefined ? ` (${slotLevel}-level slot)` : ''}
        <span style={s.outcomeLabel}>CAST</span>
      </span>
      {targets && targets.length > 0 && (
        <span style={s.entryDetail}>Targets: {targets.join(', ')}</span>
      )}
    </>
  )
}

function renderConditionApplied(e: MechanicalResultEntry): React.ReactNode {
  const target = e.target as string | undefined
  const condition = e.condition as string | undefined
  const source = e.source as string | undefined

  return (
    <span style={s.entryMain}>
      {target}: {condition} applied{source ? ` (from ${source})` : ''}
    </span>
  )
}

function renderConditionRemoved(e: MechanicalResultEntry): React.ReactNode {
  const target = e.target as string | undefined
  const condition = e.condition as string | undefined

  return (
    <span style={s.entryMain}>
      {target}: {condition} removed
    </span>
  )
}

function renderCombatStarted(e: MechanicalResultEntry): React.ReactNode {
  const participants = e.participants as string[] | undefined

  return (
    <span style={s.entryMain}>
      ⚔️ Combat — Initiative order: {participants ? participants.join(', ') : '(see initiative panel)'}
    </span>
  )
}

function renderCombatEnded(_e: MechanicalResultEntry): React.ReactNode {
  return <span style={s.entryMain}>Combat ended.</span>
}

function renderRestResult(e: MechanicalResultEntry): React.ReactNode {
  const type = e.rest_type as string | undefined
  const hpBefore = e.hp_before as number | undefined
  const hpAfter = e.hp_after as number | undefined
  const maxHp = e.max_hp as number | undefined

  return (
    <span style={s.entryMain}>
      {type ?? 'Rest'} Rest — HP: {hpBefore} → {hpAfter} / {maxHp}
    </span>
  )
}

function renderGeneric(e: MechanicalResultEntry): React.ReactNode {
  return (
    <span style={s.entryMain}>
      {e.type}: {JSON.stringify(e, null, 0)}
    </span>
  )
}

function renderEntry(e: MechanicalResultEntry): React.ReactNode {
  switch (e.type) {
    case 'attack_roll':
      return renderAttackRoll(e)
    case 'damage':
      return renderDamage(e)
    case 'healing':
      return renderHealing(e)
    case 'saving_throw':
      return renderSavingThrow(e)
    case 'spell_cast':
      return renderSpellCast(e)
    case 'condition_applied':
      return renderConditionApplied(e)
    case 'condition_removed':
      return renderConditionRemoved(e)
    case 'combat_started':
      return renderCombatStarted(e)
    case 'combat_ended':
      return renderCombatEnded(e)
    case 'rest_result':
      return renderRestResult(e)
    default:
      return renderGeneric(e)
  }
}

// ---------------------------------------------------------------------------
// Turn group
// ---------------------------------------------------------------------------

interface TurnGroupProps {
  group: TurnMechanicalGroup
  expanded: boolean
  onToggle: () => void
  hasMechanicalResults: boolean
}

function TurnGroup({ group, expanded, onToggle, hasMechanicalResults }: TurnGroupProps) {
  return (
    <div className="mech-turn-group">
      <button className="mech-group-header" onClick={onToggle}>
        <span className="mech-group-arrow">{expanded ? '▾' : '▸'}</span>
        <span className="mech-group-title">
          Turn {group.sequence_number} · {group.character_name}
        </span>
      </button>
      {expanded && (
        <div className="mech-group-body">
          {!hasMechanicalResults ? (
            <p className="mech-empty">
              {group.entries.length === 0 && group.entries !== undefined
                ? 'No mechanical results recorded.'
                : 'No mechanical results recorded.'}
            </p>
          ) : (
            group.entries.map((entry, i) => (
              <div key={i} className={`mech-entry ${colourClass(entry)}`}>
                {renderEntry(entry)}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export interface MechanicalLogProps {
  turnGroups: TurnMechanicalGroup[]
  /** Set to true when session.state was received but had no mechanical_results key at all (pre-migration) */
  preMigration?: boolean
}

export function MechanicalLog({ turnGroups, preMigration }: MechanicalLogProps) {
  const logEndRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  // Determine which groups start expanded: last 5 turns
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => {
    const initial = new Set<string>()
    const last5 = turnGroups.slice(-5)
    for (const g of last5) initial.add(g.turn_id)
    return initial
  })

  // When new turn groups are added, auto-expand the newest one
  useEffect(() => {
    if (turnGroups.length === 0) return
    const newest = turnGroups[turnGroups.length - 1]
    setExpandedIds((prev) => {
      if (prev.has(newest.turn_id)) return prev
      const next = new Set(prev)
      next.add(newest.turn_id)
      return next
    })
  }, [turnGroups])

  useEffect(() => {
    if (autoScroll) {
      logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [turnGroups, autoScroll])

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setAutoScroll(distFromBottom < 50)
  }

  const toggleGroup = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  return (
    <div
      className="mech-log-container"
      ref={containerRef}
      onScroll={handleScroll}
    >
      {preMigration && turnGroups.length === 0 && (
        <p className="mech-premigration">
          Mechanical results are recorded from new turns onward.
        </p>
      )}
      {turnGroups.map((group) => (
        <TurnGroup
          key={group.turn_id}
          group={group}
          expanded={expandedIds.has(group.turn_id)}
          onToggle={() => toggleGroup(group.turn_id)}
          hasMechanicalResults={group.entries.length > 0}
        />
      ))}
      <div ref={logEndRef} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inline styles for entry sub-elements (layout only; colour via CSS classes)
// ---------------------------------------------------------------------------

const s: Record<string, React.CSSProperties> = {
  entryMain: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: '0.5rem',
    whiteSpace: 'pre-wrap' as const,
  },
  entryDetail: {
    display: 'block',
    paddingLeft: '1rem',
    opacity: 0.8,
  },
  outcomeLabel: {
    marginLeft: 'auto',
    fontWeight: 700,
    letterSpacing: '0.06em',
    flexShrink: 0,
  },
}
