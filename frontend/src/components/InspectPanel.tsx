import type { SessionTelemetry, TurnEventLog } from '../types'
import { TurnDetail } from './TurnDetail'
import { SessionOverview } from './SessionOverview'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  campaignId: string
  tab: 'turn' | 'session'
  onTabChange: (tab: 'turn' | 'session') => void
  eventLogCache: Map<string, TurnEventLog>
  sessionTelemetry: SessionTelemetry | null
  selectedTurnLog: TurnEventLog | null
  onSelectTurnLog: (log: TurnEventLog | null) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function InspectPanel({
  campaignId,
  tab,
  onTabChange,
  eventLogCache,
  sessionTelemetry,
  selectedTurnLog,
  onSelectTurnLog,
}: Props) {
  // Build sparkline data from eventLogCache: extract narration step duration_ms
  const sparklineData: number[] = []
  for (const log of eventLogCache.values()) {
    const narrationStep = log.steps.find((s) => s.step === 'narration')
    if (narrationStep !== undefined) {
      const dur = (narrationStep.output_summary as Record<string, unknown>)['stream_duration_ms']
      if (typeof dur === 'number') {
        sparklineData.push(dur)
      } else {
        sparklineData.push(narrationStep.duration_ms)
      }
    }
  }

  return (
    // TODO: gate on campaign ownership — ADR-0006
    <div style={s.root}>
      {/* Panel header */}
      <div style={s.panelHeader}>
        <span style={s.panelTitle}>🔍 Inspect</span>
      </div>

      {/* Tab bar */}
      <div style={s.tabBar}>
        <button
          style={{ ...s.tab, ...(tab === 'session' ? s.tabActive : {}) }}
          onClick={() => onTabChange('session')}
        >
          Session
        </button>
        <button
          style={{ ...s.tab, ...(tab === 'turn' ? s.tabActive : {}) }}
          onClick={() => onTabChange('turn')}
        >
          Turn Detail
        </button>
      </div>

      {/* Content */}
      <div style={s.content}>
        {tab === 'session' && (
          <SessionOverview telemetry={sessionTelemetry} sparklineData={sparklineData} />
        )}
        {tab === 'turn' && (
          <TurnDetail
            campaignId={campaignId}
            log={selectedTurnLog}
            onClearSelection={() => onSelectTurnLog(null)}
          />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inline styles
// ---------------------------------------------------------------------------

const s: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
  },
  panelHeader: {
    padding: '0.4rem 0.75rem',
    borderBottom: '1px solid var(--color-border)',
    flexShrink: 0,
  },
  panelTitle: {
    fontSize: '0.65rem',
    letterSpacing: '0.12em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-gold-dim)',
  },
  tabBar: {
    display: 'flex',
    flexShrink: 0,
    borderBottom: '1px solid var(--color-border)',
  },
  tab: {
    flex: 1,
    background: 'transparent',
    border: 'none',
    borderBottom: '2px solid transparent',
    color: 'var(--color-parchment-dim)',
    fontFamily: 'var(--font-serif)',
    fontSize: '0.75rem',
    padding: '0.35rem 0.5rem',
    cursor: 'pointer',
    transition: 'color 0.15s, border-color 0.15s',
  },
  tabActive: {
    color: 'var(--color-gold)',
    borderBottomColor: 'var(--color-gold)',
  },
  content: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
}
