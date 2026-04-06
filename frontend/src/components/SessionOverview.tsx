import type { SessionTelemetry, TurnEventLog } from '../types'

// ---------------------------------------------------------------------------
// Sparkline
// ---------------------------------------------------------------------------

function Sparkline({ data }: { data: number[] }) {
  if (data.length < 2) return null
  const W = 200
  const H = 32
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const pts = data
    .map(
      (v, i) =>
        `${(i / (data.length - 1)) * W},${H - ((v - min) / range) * H}`,
    )
    .join(' ')
  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      <polyline
        points={pts}
        fill="none"
        stroke="var(--color-gold-dim)"
        strokeWidth={1.5}
      />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  telemetry: SessionTelemetry | null
  sparklineData: number[]
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pct(n: number): string {
  return (n * 100).toFixed(1) + '%'
}

function fmt(n: number): string {
  return n.toLocaleString()
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SessionOverview({ telemetry, sparklineData }: Props) {
  if (!telemetry) {
    return (
      <div style={s.empty}>
        <p style={s.emptyText}>Collecting telemetry…</p>
        <p style={s.emptyHint}>(sent after every 10 turns, or on connect)</p>
      </div>
    )
  }

  const modelEntries = Object.entries(telemetry.model_tier_distribution)

  return (
    <div style={s.root}>
      {/* Cost — most prominent */}
      <div style={s.costBlock}>
        <span style={s.costIcon}>💰</span>
        <span style={s.costLabel}>Session cost</span>
        <span style={s.costValue}>${telemetry.total_cost_usd.toFixed(4)}</span>
      </div>

      {/* Metrics grid */}
      <div style={s.grid}>
        <MetricRow label="Turns processed" value={String(telemetry.turns_processed)} />
        <MetricRow label="Avg narration" value={`${fmt(telemetry.avg_narration_latency_ms)}ms`} />
        <MetricRow label="Avg pipeline" value={`${fmt(telemetry.avg_pipeline_duration_ms)}ms`} />
        <MetricRow label="Cache hit rate" value={pct(telemetry.cache_hit_rate)} />
        <MetricRow
          label="Total tokens"
          value={`${fmt(telemetry.total_input_tokens)} in / ${fmt(telemetry.total_output_tokens)} out`}
        />
        <MetricRow label="GMSignals failures" value={String(telemetry.gm_signals_parse_failures)} />
      </div>

      {/* Model split */}
      {modelEntries.length > 0 && (
        <div style={s.section}>
          <span style={s.sectionLabel}>Model tier split</span>
          <div style={s.grid}>
            {modelEntries.map(([tier, count]) => (
              <MetricRow key={tier} label={tier} value={String(count)} />
            ))}
          </div>
        </div>
      )}

      {/* Classifier stats */}
      {telemetry.classifier_invocations > 0 && (
        <div style={s.section}>
          <span style={s.sectionLabel}>Classifier</span>
          <div style={s.grid}>
            <MetricRow label="Invocations" value={String(telemetry.classifier_invocations)} />
            <MetricRow
              label="Low confidence"
              value={String(telemetry.classifier_low_confidence_count)}
            />
          </div>
        </div>
      )}

      {/* Narration latency sparkline */}
      {sparklineData.length > 0 && (
        <div style={s.section}>
          <span style={s.sectionLabel}>Narration latency (recent turns)</span>
          <div style={{ marginTop: '0.4rem' }}>
            <Sparkline data={sparklineData} />
            {sparklineData.length >= 2 && (
              <span style={s.sparkHint}>
                {fmt(Math.min(...sparklineData))}ms – {fmt(Math.max(...sparklineData))}ms
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-component
// ---------------------------------------------------------------------------

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <span style={s.metricLabel}>{label}</span>
      <span style={s.metricValue}>{value}</span>
    </>
  )
}

// ---------------------------------------------------------------------------
// Inline styles
// ---------------------------------------------------------------------------

const s: Record<string, React.CSSProperties> = {
  root: {
    padding: '0.75rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
    overflowY: 'auto',
    flex: 1,
  },
  empty: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.35rem',
    padding: '1rem',
  },
  emptyText: {
    color: 'var(--color-parchment-dim)',
    fontStyle: 'italic',
    fontSize: '0.82rem',
  },
  emptyHint: {
    color: 'var(--color-parchment-dim)',
    fontSize: '0.72rem',
    opacity: 0.7,
  },
  costBlock: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    padding: '0.5rem 0.75rem',
    background: 'rgba(212,162,78,0.08)',
    border: '1px solid var(--color-gold-dim)',
    borderRadius: '4px',
  },
  costIcon: {
    fontSize: '1rem',
  },
  costLabel: {
    color: 'var(--color-parchment-dim)',
    fontSize: '0.78rem',
    flex: 1,
  },
  costValue: {
    color: 'var(--color-gold)',
    fontSize: '1rem',
    fontWeight: 700,
    fontFamily: 'var(--font-mono)',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr auto',
    gap: '0.2rem 0.75rem',
    alignItems: 'baseline',
  },
  metricLabel: {
    color: 'var(--color-parchment-dim)',
    fontSize: '0.72rem',
  },
  metricValue: {
    color: 'var(--color-parchment)',
    fontSize: '0.72rem',
    fontFamily: 'var(--font-mono)',
    textAlign: 'right' as const,
    whiteSpace: 'nowrap' as const,
  },
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.3rem',
    paddingTop: '0.5rem',
    borderTop: '1px solid var(--color-border)',
  },
  sectionLabel: {
    fontSize: '0.65rem',
    letterSpacing: '0.1em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-gold-dim)',
  },
  sparkHint: {
    fontSize: '0.65rem',
    color: 'var(--color-parchment-dim)',
    fontFamily: 'var(--font-mono)',
    marginTop: '0.2rem',
    display: 'block',
  },
}
