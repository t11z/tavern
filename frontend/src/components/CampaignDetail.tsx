import { useEffect, useState } from 'react'
import type { CampaignDetail, CharacterSummary } from '../types'

interface Props {
  campaignId: string
  onCreateChar: () => void
  onStartSession: () => void
  onBack: () => void
}

export function CampaignDetailView({ campaignId, onCreateChar, onStartSession, onBack }: Props) {
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null)
  const [characters, setCharacters] = useState<CharacterSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  const reload = () => {
    setLoading(true)
    Promise.all([
      fetch(`/api/campaigns/${campaignId}`).then((r) => r.json()) as Promise<CampaignDetail>,
      fetch(`/api/campaigns/${campaignId}/characters`).then((r) => r.json()) as Promise<CharacterSummary[]>,
    ])
      .then(([camp, chars]) => {
        setCampaign(camp)
        setCharacters(chars)
        setLoading(false)
      })
      .catch(() => {
        setError('Failed to load campaign.')
        setLoading(false)
      })
  }

  useEffect(reload, [campaignId])

  const handleStartSession = async () => {
    if (!campaign || starting) return
    setStarting(true)
    try {
      const res = await fetch(`/api/campaigns/${campaignId}/sessions`, { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { message?: string }
        setError(body.message ?? 'Failed to start session.')
        setStarting(false)
        return
      }
      onStartSession()
    } catch {
      setError('Network error.')
      setStarting(false)
    }
  }

  if (loading) {
    return (
      <div style={s.center}>
        <p style={s.muted}>Loading…</p>
      </div>
    )
  }

  if (error || !campaign) {
    return (
      <div style={s.center}>
        <p style={{ color: 'var(--color-danger)' }}>{error ?? 'Campaign not found.'}</p>
        <button style={{ ...s.btn, ...s.btnSecondary }} onClick={onBack}>
          ← Back
        </button>
      </div>
    )
  }

  const canStart = campaign.status === 'paused' && characters.length > 0
  const isActive = campaign.status === 'active'

  return (
    <div style={s.page}>
      <div style={s.topBar}>
        <button style={s.backBtn} onClick={onBack}>
          ← Campaigns
        </button>
        {isActive && (
          <button style={{ ...s.btn, ...s.btnPrimary }} onClick={onStartSession}>
            Rejoin Session →
          </button>
        )}
        {!isActive && (
          <button
            style={{ ...s.btn, ...s.btnPrimary, opacity: canStart ? 1 : 0.45 }}
            onClick={handleStartSession}
            disabled={!canStart || starting}
            title={!characters.length ? 'Create a character first' : undefined}
          >
            {starting ? 'Starting…' : 'Start Session'}
          </button>
        )}
      </div>

      <div style={s.body}>
        {/* Campaign header */}
        <div style={s.campHeader}>
          <h1 style={s.campName}>{campaign.name}</h1>
          <span style={{ ...s.badge, ...statusStyle(campaign.status) }}>{campaign.status}</span>
        </div>

        {campaign.world_seed && (
          <p style={s.worldSeed}>{campaign.world_seed}</p>
        )}

        {campaign.state?.scene_context && (
          <div style={s.sceneBox}>
            <span style={s.sceneLabel}>Opening Scene</span>
            <p style={s.sceneText}>{campaign.state.scene_context}</p>
          </div>
        )}

        {/* Characters */}
        <div style={s.sectionHeader}>
          <span style={s.sectionTitle}>Characters</span>
          <button style={{ ...s.btn, ...s.btnSecondary }} onClick={onCreateChar}>
            + Create Character
          </button>
        </div>

        {characters.length === 0 ? (
          <p style={s.muted}>No characters yet. Create one to begin.</p>
        ) : (
          <div style={s.charList}>
            {characters.map((c) => (
              <CharacterCard key={c.id} character={c} />
            ))}
          </div>
        )}

        {!canStart && !isActive && characters.length === 0 && (
          <p style={{ ...s.muted, marginTop: '1rem' }}>
            Create at least one character to start the session.
          </p>
        )}
      </div>
    </div>
  )
}

function CharacterCard({ character }: { character: CharacterSummary }) {
  const hpPct = Math.max(0, Math.min(100, (character.hp / character.max_hp) * 100))
  const hpColor =
    hpPct > 60 ? 'var(--color-success)' : hpPct > 30 ? 'var(--color-gold)' : 'var(--color-danger)'
  const slots = Object.entries(character.spell_slots).filter(([, v]) => v > 0)

  return (
    <div style={s.charCard}>
      <div style={s.charNameRow}>
        <span style={s.charName}>{character.name}</span>
        <span style={s.charClass}>
          {character.class_name} {character.level}
        </span>
      </div>
      <div style={s.hpRow}>
        <span style={s.statLabel}>HP {character.hp}/{character.max_hp}</span>
        <div style={s.hpTrack}>
          <div style={{ ...s.hpFill, width: `${hpPct}%`, background: hpColor }} />
        </div>
      </div>
      <div style={s.statsRow}>
        <span style={s.statLabel}>AC {character.ac}</span>
        {slots.length > 0 && (
          <span style={s.statLabel}>
            Slots: {slots.map(([l, c]) => `L${l}×${c}`).join(' ')}
          </span>
        )}
      </div>
    </div>
  )
}

function statusStyle(status: string): React.CSSProperties {
  if (status === 'active') return { color: 'var(--color-success)' }
  if (status === 'paused') return { color: 'var(--color-gold-dim)' }
  return { color: 'var(--color-parchment-dim)' }
}

const s: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '1.5rem 1rem 3rem',
  },
  center: {
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '1rem',
  },
  topBar: {
    width: '100%',
    maxWidth: 'min(90vw, 38rem)',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '2rem',
  },
  backBtn: {
    background: 'transparent',
    border: 'none',
    color: 'var(--color-gold-dim)',
    fontSize: '0.9rem',
    cursor: 'pointer',
    padding: '0.3rem 0',
    letterSpacing: '0.04em',
  },
  body: {
    width: '100%',
    maxWidth: 'min(90vw, 38rem)',
    display: 'flex',
    flexDirection: 'column',
    gap: '1.25rem',
  },
  campHeader: {
    display: 'flex',
    alignItems: 'baseline',
    gap: '1rem',
  },
  campName: {
    fontSize: '1.8rem',
    color: 'var(--color-gold)',
    fontFamily: 'var(--font-serif)',
  },
  badge: {
    fontSize: '0.75rem',
    textTransform: 'capitalize',
    letterSpacing: '0.06em',
  },
  worldSeed: {
    color: 'var(--color-parchment-dim)',
    fontStyle: 'italic',
    fontSize: '0.95rem',
    lineHeight: 1.7,
  },
  sceneBox: {
    background: 'var(--color-bg-panel)',
    border: '1px solid var(--color-border)',
    borderRadius: '4px',
    padding: '1rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  sceneLabel: {
    fontSize: '0.65rem',
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    color: 'var(--color-gold-dim)',
  },
  sceneText: {
    color: 'var(--color-parchment)',
    fontSize: '0.95rem',
    lineHeight: 1.7,
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: '0.5rem',
  },
  sectionTitle: {
    fontSize: '0.7rem',
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
    color: 'var(--color-gold-dim)',
  },
  charList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  charCard: {
    background: 'var(--color-bg-panel)',
    border: '1px solid var(--color-border)',
    borderRadius: '4px',
    padding: '0.85rem 1rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.4rem',
  },
  charNameRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
  },
  charName: {
    fontWeight: 600,
    color: 'var(--color-gold)',
    fontSize: '1rem',
  },
  charClass: {
    fontSize: '0.8rem',
    color: 'var(--color-parchment-dim)',
  },
  hpRow: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.2rem',
  },
  hpTrack: {
    height: '0.25rem',
    background: 'var(--color-border)',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  hpFill: {
    height: '100%',
    borderRadius: '3px',
  },
  statsRow: {
    display: 'flex',
    gap: '1rem',
  },
  statLabel: {
    fontSize: '0.75rem',
    color: 'var(--color-parchment-dim)',
  },
  muted: {
    color: 'var(--color-parchment-dim)',
    fontStyle: 'italic',
    fontSize: '0.9rem',
  },
  btn: {
    padding: '0.5rem 1.1rem',
    borderRadius: '4px',
    fontSize: '0.85rem',
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
