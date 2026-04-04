import { useState } from 'react'
import {
  ABILITIES,
  BACKGROUNDS,
  SRD_CLASSES,
  SRD_SPECIES,
  STANDARD_ARRAY,
  type BackgroundDef,
} from '../constants'

interface Props {
  campaignId: string
  onDone: () => void
  onCancel: () => void
}

type Step = 'basics' | 'scores' | 'review'

interface FormState {
  name: string
  class_name: string
  species: string
  background: string
  /** +2 ability bonus from background */
  bonus2: string
  /** +1 ability bonus from background */
  bonus1: string
  /** Raw standard array assignments: ability → value (0 = unassigned) */
  scores: Record<string, number>
}

const EMPTY_SCORES: Record<string, number> = Object.fromEntries(ABILITIES.map((a) => [a, 0]))

function bgDef(name: string): BackgroundDef | undefined {
  return BACKGROUNDS.find((b) => b.name === name)
}

export function CharacterCreation({ campaignId, onDone, onCancel }: Props) {
  const [step, setStep] = useState<Step>('basics')
  const [form, setForm] = useState<FormState>({
    name: '',
    class_name: SRD_CLASSES[0],
    species: SRD_SPECIES[0],
    background: BACKGROUNDS[0].name,
    bonus2: BACKGROUNDS[0].eligible[0],
    bonus1: BACKGROUNDS[0].eligible[1],
    scores: { ...EMPTY_SCORES },
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ---- Derived ----
  const bg = bgDef(form.background)!
  const usedValues = Object.values(form.scores).filter((v) => v > 0)
  const available = STANDARD_ARRAY.filter((v) => !usedValues.includes(v))
  const allAssigned = STANDARD_ARRAY.every((v) => usedValues.includes(v))

  // Final scores with background bonuses applied
  const finalScores: Record<string, number> = Object.fromEntries(
    ABILITIES.map((a) => {
      const base = form.scores[a] || 0
      const bonus = (a === form.bonus2 ? 2 : 0) + (a === form.bonus1 ? 1 : 0)
      return [a, base + bonus]
    }),
  )

  // ---- Handlers ----
  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const handleBackgroundChange = (bg: string) => {
    const def = bgDef(bg)
    if (!def) return
    setForm((f) => ({
      ...f,
      background: bg,
      bonus2: def.eligible[0],
      bonus1: def.eligible[1],
    }))
  }

  const handleScoreChange = (ability: string, value: number) => {
    setForm((f) => {
      // If another ability already has this value, clear it
      const cleared = Object.fromEntries(
        Object.entries(f.scores).map(([a, v]) => [a, v === value && a !== ability ? 0 : v]),
      )
      return { ...f, scores: { ...cleared, [ability]: value } }
    })
  }

  const basicsValid =
    form.name.trim().length > 0 &&
    form.class_name &&
    form.species &&
    form.background &&
    form.bonus2 !== form.bonus1

  const handleSubmit = async () => {
    if (!allAssigned || !basicsValid) return
    setSubmitting(true)
    setError(null)

    const payload = {
      name: form.name.trim(),
      class_name: form.class_name,
      species: form.species,
      background: form.background,
      ability_scores: { ...form.scores },
      ability_score_method: 'standard_array',
      background_bonuses: {
        [form.bonus2]: 2,
        [form.bonus1]: 1,
      },
      equipment_choices: 'package_a',
      languages: ['Common'],
    }

    try {
      const res = await fetch(`/api/campaigns/${campaignId}/characters`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { message?: string }
        setError(body.message ?? 'Character creation failed.')
        setSubmitting(false)
        return
      }
      onDone()
    } catch {
      setError('Network error.')
      setSubmitting(false)
    }
  }

  // ---- Step: Basics ----
  if (step === 'basics') {
    return (
      <div style={s.center}>
        <div style={s.card}>
          <h2 style={s.cardTitle}>Create Character</h2>
          <p style={s.stepHint}>Step 1 of 2 — Class, species & background</p>

          <label style={s.label}>Character name</label>
          <input
            style={s.input}
            value={form.name}
            onChange={(e) => setField('name', e.target.value)}
            placeholder="Aldric Stonebrow"
            maxLength={100}
            autoFocus
          />

          <div style={s.row}>
            <div style={s.col}>
              <label style={s.label}>Class</label>
              <select
                style={s.input}
                value={form.class_name}
                onChange={(e) => setField('class_name', e.target.value)}
              >
                {SRD_CLASSES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <div style={s.col}>
              <label style={s.label}>Species</label>
              <select
                style={s.input}
                value={form.species}
                onChange={(e) => setField('species', e.target.value)}
              >
                {SRD_SPECIES.map((sp) => (
                  <option key={sp} value={sp}>{sp}</option>
                ))}
              </select>
            </div>
          </div>

          <label style={s.label}>Background</label>
          <select
            style={s.input}
            value={form.background}
            onChange={(e) => handleBackgroundChange(e.target.value)}
          >
            {BACKGROUNDS.map((b) => (
              <option key={b.name} value={b.name}>{b.name}</option>
            ))}
          </select>

          {/* Background bonus selectors */}
          <div style={s.bonusBox}>
            <p style={s.bonusLabel}>
              {form.background} grants +2 and +1 to abilities from:{' '}
              <strong style={{ color: 'var(--color-gold)' }}>
                {bg.eligible.join(', ')}
              </strong>
            </p>
            <div style={s.row}>
              <div style={s.col}>
                <label style={s.label}>+2 to</label>
                <select
                  style={s.input}
                  value={form.bonus2}
                  onChange={(e) => setField('bonus2', e.target.value)}
                >
                  {bg.eligible.map((a) => (
                    <option key={a} value={a} disabled={a === form.bonus1}>{a}</option>
                  ))}
                </select>
              </div>
              <div style={s.col}>
                <label style={s.label}>+1 to</label>
                <select
                  style={s.input}
                  value={form.bonus1}
                  onChange={(e) => setField('bonus1', e.target.value)}
                >
                  {bg.eligible.map((a) => (
                    <option key={a} value={a} disabled={a === form.bonus2}>{a}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          <div style={s.btnRow}>
            <button style={{ ...s.btn, ...s.btnSecondary }} onClick={onCancel}>
              Cancel
            </button>
            <button
              style={{ ...s.btn, ...s.btnPrimary, opacity: basicsValid ? 1 : 0.45 }}
              onClick={() => basicsValid && setStep('scores')}
              disabled={!basicsValid}
            >
              Next →
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ---- Step: Ability Scores ----
  if (step === 'scores') {
    return (
      <div style={s.center}>
        <div style={{ ...s.card, maxWidth: '520px' }}>
          <h2 style={s.cardTitle}>Ability Scores</h2>
          <p style={s.stepHint}>
            Step 2 of 2 — Assign the Standard Array: {STANDARD_ARRAY.join(', ')}
          </p>
          <p style={s.muted}>
            Remaining:{' '}
            {available.length > 0
              ? available.join(', ')
              : <span style={{ color: 'var(--color-success)' }}>all assigned</span>}
          </p>

          <div style={s.scoresGrid}>
            {ABILITIES.map((ability) => {
              const bonus = (ability === form.bonus2 ? 2 : 0) + (ability === form.bonus1 ? 1 : 0)
              const base = form.scores[ability]
              const final = base ? base + bonus : null
              return (
                <div key={ability} style={s.scoreRow}>
                  <span style={s.abilityLabel}>{ability}</span>
                  <select
                    style={{ ...s.input, ...s.scoreSelect }}
                    value={base || ''}
                    onChange={(e) => handleScoreChange(ability, Number(e.target.value))}
                  >
                    <option value="">—</option>
                    {STANDARD_ARRAY.map((v) => (
                      <option
                        key={v}
                        value={v}
                        disabled={usedValues.includes(v) && base !== v}
                      >
                        {v}
                      </option>
                    ))}
                  </select>
                  {bonus > 0 && (
                    <span style={s.bonusPill}>+{bonus}</span>
                  )}
                  {final !== null && (
                    <span style={s.finalScore}>{final}</span>
                  )}
                </div>
              )
            })}
          </div>

          {error && <p style={s.errMsg}>{error}</p>}

          <div style={s.btnRow}>
            <button
              style={{ ...s.btn, ...s.btnSecondary }}
              onClick={() => { setStep('basics'); setError(null) }}
              disabled={submitting}
            >
              ← Back
            </button>
            <button
              style={{ ...s.btn, ...s.btnPrimary, opacity: allAssigned && !submitting ? 1 : 0.45 }}
              onClick={handleSubmit}
              disabled={!allAssigned || submitting}
            >
              {submitting ? 'Creating…' : 'Create Character'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return null
}

const s: Record<string, React.CSSProperties> = {
  center: {
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '2rem 1rem',
  },
  card: {
    width: '100%',
    maxWidth: '460px',
    background: 'var(--color-bg-panel)',
    border: '1px solid var(--color-border)',
    borderRadius: '6px',
    padding: '2rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
  },
  cardTitle: {
    fontSize: '1.3rem',
    color: 'var(--color-gold)',
    marginBottom: '0',
  },
  stepHint: {
    fontSize: '0.78rem',
    color: 'var(--color-parchment-dim)',
    marginBottom: '0.25rem',
  },
  label: {
    fontSize: '0.72rem',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: 'var(--color-parchment-dim)',
    marginTop: '0.1rem',
  },
  input: {
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    borderRadius: '4px',
    color: 'var(--color-parchment)',
    padding: '0.5rem 0.7rem',
    fontSize: '0.92rem',
    width: '100%',
  },
  row: {
    display: 'flex',
    gap: '0.75rem',
  },
  col: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: '0.35rem',
  },
  bonusBox: {
    background: 'var(--color-bg)',
    border: '1px solid var(--color-border)',
    borderRadius: '4px',
    padding: '0.75rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.6rem',
  },
  bonusLabel: {
    fontSize: '0.82rem',
    color: 'var(--color-parchment-dim)',
    lineHeight: 1.5,
  },
  scoresGrid: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.4rem',
    margin: '0.25rem 0',
  },
  scoreRow: {
    display: 'grid',
    gridTemplateColumns: '3.5rem 1fr auto auto',
    alignItems: 'center',
    gap: '0.6rem',
  },
  abilityLabel: {
    fontSize: '0.8rem',
    fontWeight: 700,
    letterSpacing: '0.06em',
    color: 'var(--color-parchment)',
    textAlign: 'right' as const,
  },
  scoreSelect: {
    padding: '0.4rem 0.6rem',
    fontSize: '0.9rem',
  },
  bonusPill: {
    fontSize: '0.72rem',
    color: 'var(--color-gold)',
    background: 'rgba(212,162,78,0.12)',
    borderRadius: '3px',
    padding: '0.1rem 0.35rem',
    whiteSpace: 'nowrap' as const,
  },
  finalScore: {
    fontSize: '1rem',
    fontWeight: 700,
    color: 'var(--color-gold)',
    minWidth: '2rem',
    textAlign: 'center' as const,
  },
  muted: {
    color: 'var(--color-parchment-dim)',
    fontSize: '0.82rem',
    fontStyle: 'italic',
  },
  errMsg: {
    color: 'var(--color-danger)',
    fontSize: '0.85rem',
    fontStyle: 'italic',
  },
  btnRow: {
    display: 'flex',
    gap: '0.75rem',
    justifyContent: 'flex-end',
    marginTop: '0.5rem',
  },
  btn: {
    padding: '0.55rem 1.2rem',
    borderRadius: '4px',
    fontSize: '0.88rem',
    fontWeight: 600,
    border: 'none',
    cursor: 'pointer',
    letterSpacing: '0.04em',
  },
  btnPrimary: {
    background: 'var(--color-gold)',
    color: 'var(--color-bg)',
  },
  btnSecondary: {
    background: 'transparent',
    border: '1px solid var(--color-gold-dim)',
    color: 'var(--color-gold)',
  },
}
