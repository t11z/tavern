interface CampaignInfo {
  name: string
  turn_count: number
}

interface CombatDisplayEntry {
  id: string
  name: string
  initiative: number
  surprised: boolean
}

interface CombatDisplay {
  currentRound: number
  currentTurnIndex: number
  entries: CombatDisplayEntry[]
}

interface Props {
  campaign: CampaignInfo
  wsStatus: 'connecting' | 'open' | 'closed' | 'error' | 'fatal'
  combatDisplay: CombatDisplay | null
}

const statusDot: Record<Props['wsStatus'], { color: string; label: string }> = {
  open: { color: 'var(--color-success)', label: 'Connected' },
  connecting: { color: 'var(--color-gold-dim)', label: 'Connecting…' },
  closed: { color: 'var(--color-parchment-dim)', label: 'Disconnected' },
  error: { color: 'var(--color-danger)', label: 'Error' },
  fatal: { color: 'var(--color-danger)', label: 'Campaign not found' },
}

export function CampaignHeader({ campaign, wsStatus, combatDisplay }: Props) {
  const dot = statusDot[wsStatus]
  const activeName = combatDisplay?.entries[combatDisplay.currentTurnIndex]?.name

  return (
    <div style={styles.wrapper}>
      <header style={styles.header}>
        <h1 style={styles.title}>{campaign.name}</h1>
        <div style={styles.meta}>
          {combatDisplay && (
            <span style={styles.roundLabel}>
              Round {combatDisplay.currentRound}
              {activeName ? ` — ${activeName}'s Turn` : ''}
            </span>
          )}
          <span style={{ ...styles.dot, color: dot.color }}>{dot.label}</span>
        </div>
      </header>

      {combatDisplay && (
        <div style={styles.initiativeStrip}>
          {combatDisplay.entries.map((entry, i) => {
            const isActive = i === combatDisplay.currentTurnIndex
            return (
              <div
                key={entry.id}
                style={{
                  ...styles.pip,
                  ...(isActive ? styles.pipActive : {}),
                }}
              >
                <span style={styles.pipName}>{entry.name}</span>
                {entry.surprised && <span style={styles.surprisedDot} title="Surprised">!</span>}
                <span style={styles.pipInit}>{entry.initiative}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    flexShrink: 0,
    borderBottom: '1px solid var(--color-border)',
    background: 'var(--color-bg-panel)',
  },
  header: {
    display: 'flex',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    padding: '0.75rem 1.25rem',
  },
  title: {
    fontFamily: 'var(--font-serif)',
    fontSize: '1.2rem',
    fontWeight: 600,
    color: 'var(--color-gold)',
    letterSpacing: '0.05em',
  },
  meta: {
    display: 'flex',
    gap: '1.25rem',
    alignItems: 'baseline',
    fontSize: '0.8rem',
  },
  roundLabel: {
    color: 'var(--color-danger)',
    fontWeight: 700,
    fontSize: '0.78rem',
    letterSpacing: '0.04em',
  },
  dot: {
    fontSize: '0.75rem',
  },
  initiativeStrip: {
    display: 'flex',
    gap: '0.35rem',
    overflowX: 'auto',
    padding: '0.35rem 1.25rem 0.45rem',
    borderTop: '1px solid rgba(192,57,43,0.2)',
    background: 'rgba(192,57,43,0.04)',
    scrollbarWidth: 'none' as const,
  },
  pip: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.3rem',
    flexShrink: 0,
    padding: '0.15rem 0.55rem',
    borderRadius: '3px',
    border: '1px solid var(--color-border)',
    background: 'var(--color-bg-panel)',
    fontSize: '0.7rem',
    color: 'var(--color-parchment-dim)',
    maxWidth: '9rem',
    overflow: 'hidden',
  },
  pipActive: {
    background: 'rgba(192,57,43,0.15)',
    border: '1px solid var(--color-danger)',
    color: 'var(--color-parchment)',
    fontWeight: 600,
  },
  pipName: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    flex: 1,
  },
  surprisedDot: {
    color: 'var(--color-danger)',
    fontWeight: 700,
    flexShrink: 0,
  },
  pipInit: {
    color: 'var(--color-gold-dim)',
    flexShrink: 0,
    fontSize: '0.65rem',
  },
}
