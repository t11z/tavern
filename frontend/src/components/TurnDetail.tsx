import { useState } from 'react'
import type { TurnEventLog, PipelineStep, LLMCallRecord } from '../types'

// ---------------------------------------------------------------------------
// Step categorisation
// ---------------------------------------------------------------------------

const CORE_STEPS = new Set([
  'action_analysis',
  'attack_resolution',
  'spell_resolution',
  'condition_evaluation',
  'srd_lookup',
  'character_state_mutation',
  'rest_resolution',
  'death_save',
])

const DM_STEPS = new Set([
  'snapshot_build',
  'model_routing',
  'narration',
  'gm_signals_parse',
  'npc_update_apply',
  'scene_transition_apply',
  'summary_compression',
  'suggested_actions_emit',
  'combat_classification',
])

function stepBorderColor(stepName: string): string {
  if (CORE_STEPS.has(stepName)) return 'var(--color-gold-dim)'
  if (DM_STEPS.has(stepName)) return 'var(--color-success)'
  return 'var(--color-border)'
}

function formatStepName(name: string): string {
  return name
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

// ---------------------------------------------------------------------------
// Step row
// ---------------------------------------------------------------------------

interface StepRowProps {
  step: PipelineStep
}

function StepRow({ step }: StepRowProps) {
  const [expanded, setExpanded] = useState(false)
  const borderColor = stepBorderColor(step.step)

  return (
    <div style={{ ...s.stepRow, borderLeftColor: borderColor }}>
      <button style={s.stepHeader} onClick={() => setExpanded((v) => !v)}>
        <span style={s.stepArrow}>{expanded ? '▾' : '▸'}</span>
        <span style={s.stepName}>{formatStepName(step.step)}</span>
        <span style={s.stepDuration}>{step.duration_ms}ms</span>
      </button>
      {step.decision && <div style={s.stepDecision}>{step.decision}</div>}
      {expanded && (
        <div style={s.stepDetail}>
          <div style={s.stepDetailSection}>
            <span style={s.stepDetailLabel}>Input</span>
            <pre style={s.stepDetailPre}>{JSON.stringify(step.input_summary, null, 2)}</pre>
          </div>
          <div style={s.stepDetailSection}>
            <span style={s.stepDetailLabel}>Output</span>
            <pre style={s.stepDetailPre}>{JSON.stringify(step.output_summary, null, 2)}</pre>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// LLM call row
// ---------------------------------------------------------------------------

interface LLMCallRowProps {
  call: LLMCallRecord
}

function LLMCallRow({ call }: LLMCallRowProps) {
  const [expanded, setExpanded] = useState(false)
  const totalIn = call.input_tokens + call.cache_read_tokens + call.cache_creation_tokens
  const cachePct = totalIn > 0 ? Math.round((call.cache_read_tokens / totalIn) * 100) : 0

  return (
    <div style={s.llmRow}>
      <button style={s.stepHeader} onClick={() => setExpanded((v) => !v)}>
        <span style={s.stepArrow}>{expanded ? '▾' : '▸'}</span>
        <span style={s.llmCallType}>{call.call_type}</span>
        <span style={s.llmTier}>{call.model_tier}</span>
        {!call.success && <span style={s.llmError}>FAIL</span>}
      </button>
      <div style={s.llmSummary}>
        <span style={s.llmMetric}>{call.model_id}</span>
      </div>
      <div style={s.llmSummary}>
        <span style={s.llmMetric}>{call.input_tokens.toLocaleString()} in / {call.output_tokens.toLocaleString()} out</span>
        <span style={s.llmMetricSep}>·</span>
        <span style={s.llmMetric}>cache: {cachePct}%</span>
      </div>
      <div style={s.llmSummary}>
        <span style={s.llmCost}>${call.estimated_cost_usd.toFixed(4)}</span>
        <span style={s.llmMetricSep}>·</span>
        <span style={s.llmMetric}>{call.latency_ms}ms</span>
        {call.stream_first_token_ms !== null && (
          <>
            <span style={s.llmMetricSep}>·</span>
            <span style={s.llmMetric}>ttft: {call.stream_first_token_ms}ms</span>
          </>
        )}
      </div>
      {expanded && call.error && (
        <div style={s.llmErrorDetail}>{call.error}</div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  campaignId: string
  log: TurnEventLog | null
  onClearSelection: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TurnDetail({ log, onClearSelection }: Props) {
  if (!log) {
    return (
      <div style={s.empty}>
        <p style={s.emptyText}>Select a turn to inspect</p>
        <p style={s.emptyHint}>
          Click any narrative entry in the story panel to load its pipeline trace.
        </p>
      </div>
    )
  }

  const totalCost = log.llm_calls.reduce((acc, c) => acc + c.estimated_cost_usd, 0)

  // Compute pipeline duration from ISO timestamps
  let pipelineDurationMs: number | null = null
  try {
    const start = new Date(log.pipeline_started_at).getTime()
    const end = new Date(log.pipeline_finished_at).getTime()
    pipelineDurationMs = end - start
  } catch {
    // timestamps may be absent in older logs
  }

  return (
    <div style={s.root}>
      {/* Header */}
      <div style={s.header}>
        <div style={s.headerRow}>
          <span style={s.turnId}>Turn {log.turn_id.slice(0, 8)}</span>
          {pipelineDurationMs !== null && (
            <span style={s.headerMeta}>{pipelineDurationMs}ms</span>
          )}
          <span style={s.headerCost}>${totalCost.toFixed(4)}</span>
          <button style={s.clearBtn} onClick={onClearSelection} title="Deselect">×</button>
        </div>
      </div>

      <div style={s.scrollArea}>
        {/* Warnings */}
        {log.warnings.length > 0 && (
          <div style={s.alertBlock}>
            <span style={s.alertTitle}>Warnings</span>
            {log.warnings.map((w, i) => (
              <p key={i} style={{ ...s.alertItem, color: 'var(--color-gold)' }}>{w}</p>
            ))}
          </div>
        )}

        {/* Errors */}
        {log.errors.length > 0 && (
          <div style={{ ...s.alertBlock, borderColor: 'var(--color-danger)' }}>
            <span style={{ ...s.alertTitle, color: 'var(--color-danger)' }}>Errors</span>
            {log.errors.map((e, i) => (
              <p key={i} style={{ ...s.alertItem, color: 'var(--color-danger)' }}>{e}</p>
            ))}
          </div>
        )}

        {/* Pipeline steps */}
        {log.steps.length > 0 && (
          <section style={s.section}>
            <span style={s.sectionLabel}>Pipeline steps</span>
            <div style={s.stepList}>
              {log.steps.map((step, i) => (
                <StepRow key={`${step.step}-${i}`} step={step} />
              ))}
            </div>
          </section>
        )}

        {/* LLM calls */}
        {log.llm_calls.length > 0 && (
          <section style={s.section}>
            <span style={s.sectionLabel}>LLM calls ({log.llm_calls.length})</span>
            <div style={s.stepList}>
              {log.llm_calls.map((call, i) => (
                <LLMCallRow key={`${call.call_type}-${i}`} call={call} />
              ))}
            </div>
          </section>
        )}

        {log.steps.length === 0 && log.llm_calls.length === 0 && (
          <p style={s.emptyHint}>No pipeline trace recorded for this turn.</p>
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
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  empty: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.5rem',
    padding: '1.5rem',
  },
  emptyText: {
    color: 'var(--color-parchment-dim)',
    fontStyle: 'italic',
    fontSize: '0.85rem',
  },
  emptyHint: {
    color: 'var(--color-parchment-dim)',
    fontSize: '0.72rem',
    textAlign: 'center' as const,
    opacity: 0.7,
  },
  header: {
    padding: '0.5rem 0.75rem',
    borderBottom: '1px solid var(--color-border)',
    flexShrink: 0,
  },
  headerRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
  },
  turnId: {
    fontFamily: 'var(--font-mono)',
    fontSize: '0.75rem',
    color: 'var(--color-parchment)',
    flex: 1,
  },
  headerMeta: {
    fontFamily: 'var(--font-mono)',
    fontSize: '0.7rem',
    color: 'var(--color-parchment-dim)',
  },
  headerCost: {
    fontFamily: 'var(--font-mono)',
    fontSize: '0.75rem',
    color: 'var(--color-gold)',
    fontWeight: 600,
  },
  clearBtn: {
    background: 'transparent',
    border: 'none',
    color: 'var(--color-parchment-dim)',
    fontSize: '1rem',
    cursor: 'pointer',
    padding: '0 0.2rem',
    lineHeight: 1,
  },
  scrollArea: {
    flex: 1,
    overflowY: 'auto',
    padding: '0.5rem 0.75rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
  },
  alertBlock: {
    padding: '0.4rem 0.6rem',
    border: '1px solid var(--color-gold-dim)',
    borderRadius: '3px',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.2rem',
  },
  alertTitle: {
    fontSize: '0.65rem',
    letterSpacing: '0.1em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-gold)',
  },
  alertItem: {
    fontSize: '0.72rem',
    fontFamily: 'var(--font-mono)',
    lineHeight: 1.4,
  },
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.3rem',
  },
  sectionLabel: {
    fontSize: '0.65rem',
    letterSpacing: '0.1em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-gold-dim)',
  },
  stepList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.2rem',
  },
  stepRow: {
    borderLeft: '2px solid var(--color-border)',
    paddingLeft: '0.5rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.1rem',
  },
  stepHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.3rem',
    background: 'transparent',
    border: 'none',
    color: 'var(--color-parchment)',
    fontFamily: 'var(--font-serif)',
    fontSize: '0.75rem',
    cursor: 'pointer',
    padding: '0.15rem 0',
    textAlign: 'left' as const,
    width: '100%',
  },
  stepArrow: {
    color: 'var(--color-gold-dim)',
    flexShrink: 0,
    fontSize: '0.7rem',
  },
  stepName: {
    flex: 1,
  },
  stepDuration: {
    fontFamily: 'var(--font-mono)',
    fontSize: '0.68rem',
    color: 'var(--color-parchment-dim)',
    flexShrink: 0,
  },
  stepDecision: {
    fontSize: '0.68rem',
    color: 'var(--color-parchment-dim)',
    paddingLeft: '1rem',
    fontStyle: 'italic',
  },
  stepDetail: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.3rem',
    paddingLeft: '1rem',
    paddingTop: '0.2rem',
  },
  stepDetailSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.1rem',
  },
  stepDetailLabel: {
    fontSize: '0.62rem',
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-gold-dim)',
  },
  stepDetailPre: {
    fontSize: '0.62rem',
    fontFamily: 'var(--font-mono)',
    color: 'var(--color-parchment-dim)',
    background: 'rgba(0,0,0,0.2)',
    padding: '0.3rem',
    borderRadius: '2px',
    overflowX: 'auto',
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-all' as const,
    maxHeight: '8rem',
    overflowY: 'auto',
  },
  llmRow: {
    borderLeft: '2px solid var(--color-border)',
    paddingLeft: '0.5rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.1rem',
  },
  llmCallType: {
    flex: 1,
    fontSize: '0.75rem',
  },
  llmTier: {
    fontSize: '0.65rem',
    color: 'var(--color-parchment-dim)',
    fontFamily: 'var(--font-mono)',
    background: 'rgba(255,255,255,0.05)',
    padding: '0 0.3rem',
    borderRadius: '2px',
    flexShrink: 0,
  },
  llmError: {
    fontSize: '0.65rem',
    color: 'var(--color-danger)',
    fontWeight: 700,
    flexShrink: 0,
  },
  llmSummary: {
    display: 'flex',
    alignItems: 'baseline',
    gap: '0.3rem',
    paddingLeft: '1rem',
  },
  llmMetric: {
    fontSize: '0.68rem',
    fontFamily: 'var(--font-mono)',
    color: 'var(--color-parchment-dim)',
  },
  llmMetricSep: {
    fontSize: '0.65rem',
    color: 'var(--color-border)',
  },
  llmCost: {
    fontSize: '0.68rem',
    fontFamily: 'var(--font-mono)',
    color: 'var(--color-gold)',
  },
  llmErrorDetail: {
    fontSize: '0.65rem',
    fontFamily: 'var(--font-mono)',
    color: 'var(--color-danger)',
    paddingLeft: '1rem',
    fontStyle: 'italic',
  },
}
