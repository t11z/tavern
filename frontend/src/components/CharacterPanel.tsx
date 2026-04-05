import { useState } from 'react'
import type { CharacterState } from '../types'

interface Props {
  character: CharacterState
  isActive: boolean
  onClick: () => void
}

export function CharacterPanel({ character, isActive, onClick }: Props) {
  const [hovered, setHovered] = useState(false)

  const hpPct = Math.max(0, Math.min(100, (character.hp / character.max_hp) * 100))
  const hpColor =
    hpPct > 60 ? 'var(--color-success)' : hpPct > 30 ? 'var(--color-gold)' : 'var(--color-danger)'

  const spellLevels = Object.entries(character.spell_slots).filter(([, v]) => v > 0)

  return (
    <div
      style={{
        ...styles.card,
        ...(isActive ? styles.active : {}),
        ...(!isActive && hovered ? { borderColor: 'var(--color-gold-dim)' } : {}),
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
    >
      <div style={styles.nameRow}>
        <span style={styles.name}>{character.name}</span>
        <span style={styles.classLevel}>
          {character.class_name} {character.level}
        </span>
      </div>

      {/* HP bar */}
      <div style={styles.hpRow}>
        <span style={styles.hpLabel}>
          HP {character.hp}/{character.max_hp}
        </span>
        <div style={styles.hpTrack}>
          <div style={{ ...styles.hpFill, width: `${hpPct}%`, background: hpColor }} />
        </div>
      </div>

      <div style={styles.statsRow}>
        <span style={styles.stat}>AC {character.ac}</span>
        {spellLevels.length > 0 && (
          <span style={styles.stat}>
            Slots:{' '}
            {spellLevels.map(([lvl, count]) => `L${lvl}×${count}`).join(' ')}
          </span>
        )}
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    padding: '0.75rem',
    borderRadius: '4px',
    border: '1px solid var(--color-border)',
    background: 'var(--color-bg-panel)',
    cursor: 'pointer',
    transition: 'border-color 0.15s',
    userSelect: 'none',
  },
  active: {
    borderColor: 'var(--color-gold)',
  },
  nameRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    marginBottom: '0.4rem',
  },
  name: {
    fontWeight: 600,
    color: 'var(--color-gold)',
    fontSize: '0.95rem',
  },
  classLevel: {
    fontSize: '0.75rem',
    color: 'var(--color-parchment-dim)',
  },
  hpRow: {
    marginBottom: '0.35rem',
  },
  hpLabel: {
    fontSize: '0.75rem',
    color: 'var(--color-parchment-dim)',
    display: 'block',
    marginBottom: '0.2rem',
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
  statsRow: {
    display: 'flex',
    gap: '0.75rem',
    marginTop: '0.3rem',
  },
  stat: {
    fontSize: '0.75rem',
    color: 'var(--color-parchment-dim)',
  },
}
