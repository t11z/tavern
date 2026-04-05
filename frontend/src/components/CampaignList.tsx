import { useEffect, useState } from 'react'
import type { Campaign } from '../types'
import { TONE_PRESETS } from '../constants'
import { useBreakpoint } from '../hooks/useBreakpoint'

interface Props {
  onSelect: (campaignId: string) => void
}

type Mode = 'list' | 'create'

export function CampaignList({ onSelect }: Props) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>('list')
  const { isDesktop } = useBreakpoint()

  // Create form state
  const [name, setName] = useState('')
  const [tone, setTone] = useState('classic_fantasy')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/campaigns')
      .then((r) => r.json())
      .then((data: Campaign[]) => {
        setCampaigns(data)
        setLoading(false)
      })
      .catch(() => {
        setError('Failed to load campaigns.')
        setLoading(false)
      })
  }, [])

  const handleCreate = async () => {
    if (!name.trim()) return
    setCreating(true)
    setCreateError(null)
    try {
      const res = await fetch('/api/campaigns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), tone }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { message?: string }
        setCreateError(body.message ?? 'Campaign creation failed.')
        setCreating(false)
        return
      }
      const campaign = await res.json() as Campaign
      onSelect(campaign.id)
    } catch {
      setCreateError('Network error.')
      setCreating(false)
    }
  }

  if (loading) {
    return (
      <div style={s.center}>
        <p style={s.muted}>Loading campaigns…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div style={s.center}>
        <p style={{ color: 'var(--color-danger)' }}>{error}</p>
      </div>
    )
  }

  if (mode === 'create') {
    return (
      <div style={s.center}>
        <div style={s.card}>
          <h2 style={s.cardTitle}>New Campaign</h2>
          {createError && <p style={s.errMsg}>{createError}</p>}

          <label style={s.label}>Campaign name</label>
          <input
            style={s.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="The Sunken City"
            maxLength={200}
            onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
            autoFocus
          />

          <label style={s.label}>Tone</label>
          <select style={s.input} value={tone} onChange={(e) => setTone(e.target.value)}>
            {TONE_PRESETS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>

          <div style={s.btnRow}>
            <button
              style={{ ...s.btn, ...s.btnSecondary }}
              onClick={() => {
                setMode('list')
                setCreateError(null)
              }}
              disabled={creating}
            >
              Cancel
            </button>
            <button
              style={{ ...s.btn, ...s.btnPrimary, opacity: creating || !name.trim() ? 0.5 : 1 }}
              onClick={handleCreate}
              disabled={creating || !name.trim()}
            >
              {creating ? 'Creating…' : 'Create Campaign'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  const bodyStyle: React.CSSProperties = {
    ...s.body,
    maxWidth: isDesktop ? 'min(90vw, 52rem)' : 'min(92vw, 32rem)',
  }
  const listStyle: React.CSSProperties = isDesktop
    ? { display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.5rem' }
    : s.list

  return (
    <div style={s.page}>
      <header style={s.header}>
        <h1 style={s.splash}>Tavern</h1>
        <p style={s.tagline}>A solo D&amp;D adventure awaits.</p>
      </header>

      <div style={bodyStyle}>
        <div style={s.sectionHeader}>
          <span style={s.sectionTitle}>Your Campaigns</span>
          <button style={{ ...s.btn, ...s.btnPrimary }} onClick={() => setMode('create')}>
            + New Campaign
          </button>
        </div>

        {campaigns.length === 0 ? (
          <p style={s.muted}>No campaigns yet. Create one to begin your adventure.</p>
        ) : (
          <div style={listStyle}>
            {campaigns.map((c) => (
              <button key={c.id} style={s.campaignRow} onClick={() => onSelect(c.id)}>
                <div style={s.campaignName}>{c.name}</div>
                <span style={{ ...s.badge, ...statusBadge(c.status) }}>{c.status}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function statusBadge(status: string): React.CSSProperties {
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
    padding: '3rem 1rem',
  },
  header: {
    textAlign: 'center',
    marginBottom: '3rem',
  },
  splash: {
    fontSize: 'clamp(2rem, 5vw, 3.5rem)',
    color: 'var(--color-gold)',
    letterSpacing: '0.25em',
    textTransform: 'uppercase',
    fontFamily: 'var(--font-serif)',
  },
  tagline: {
    color: 'var(--color-parchment-dim)',
    fontStyle: 'italic',
    marginTop: '0.5rem',
    fontSize: '0.95rem',
  },
  body: {
    width: '100%',
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: '1rem',
  },
  sectionTitle: {
    fontSize: '0.7rem',
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
    color: 'var(--color-gold-dim)',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  campaignRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0.9rem 1rem',
    background: 'var(--color-bg-panel)',
    border: '1px solid var(--color-border)',
    borderRadius: '4px',
    cursor: 'pointer',
    textAlign: 'left',
    color: 'var(--color-parchment)',
    fontSize: '1rem',
    transition: 'border-color 0.15s',
  },
  campaignName: {
    fontWeight: 600,
    color: 'var(--color-parchment)',
  },
  badge: {
    fontSize: '0.75rem',
    textTransform: 'capitalize',
    letterSpacing: '0.05em',
  },
  muted: {
    color: 'var(--color-parchment-dim)',
    fontStyle: 'italic',
    fontSize: '0.9rem',
  },
  center: {
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '1rem',
  },
  card: {
    width: '100%',
    maxWidth: 'min(92vw, 24rem)',
    background: 'var(--color-bg-panel)',
    border: '1px solid var(--color-border)',
    borderRadius: '6px',
    padding: '2rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
  },
  cardTitle: {
    fontSize: '1.2rem',
    color: 'var(--color-gold)',
    marginBottom: '0.5rem',
  },
  label: {
    fontSize: '0.75rem',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: 'var(--color-parchment-dim)',
    marginTop: '0.25rem',
  },
  input: {
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    borderRadius: '4px',
    color: 'var(--color-parchment)',
    padding: '0.55rem 0.75rem',
    fontSize: '0.95rem',
    width: '100%',
  },
  btnRow: {
    display: 'flex',
    gap: '0.75rem',
    justifyContent: 'flex-end',
    marginTop: '0.5rem',
  },
  btn: {
    padding: '0.55rem 1.25rem',
    borderRadius: '4px',
    fontSize: '0.9rem',
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
  errMsg: {
    color: 'var(--color-danger)',
    fontSize: '0.85rem',
    fontStyle: 'italic',
  },
}
