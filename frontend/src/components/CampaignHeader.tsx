import type { Campaign } from '../types'

interface Props {
  campaign: Campaign
  wsStatus: 'connecting' | 'open' | 'closed' | 'error'
}

const statusDot: Record<Props['wsStatus'], { color: string; label: string }> = {
  open: { color: 'var(--color-success)', label: 'Connected' },
  connecting: { color: 'var(--color-gold-dim)', label: 'Connecting…' },
  closed: { color: 'var(--color-parchment-dim)', label: 'Disconnected' },
  error: { color: 'var(--color-danger)', label: 'Error' },
}

export function CampaignHeader({ campaign, wsStatus }: Props) {
  const dot = statusDot[wsStatus]
  return (
    <header style={styles.header}>
      <h1 style={styles.title}>{campaign.name}</h1>
      <div style={styles.meta}>
        <span style={styles.turns}>Turn {campaign.turn_count}</span>
        <span style={{ ...styles.dot, color: dot.color }}>{dot.label}</span>
      </div>
    </header>
  )
}

const styles: Record<string, React.CSSProperties> = {
  header: {
    display: 'flex',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    padding: '0.75rem 1.25rem',
    borderBottom: '1px solid var(--color-border)',
    background: 'var(--color-bg-panel)',
    flexShrink: 0,
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
  turns: {
    color: 'var(--color-parchment-dim)',
  },
  dot: {
    fontSize: '0.75rem',
  },
}
