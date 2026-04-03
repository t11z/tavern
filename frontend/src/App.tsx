import { useCallback, useEffect, useState } from 'react'
import './index.css'
import type { CharacterState, SessionState, TurnEntry, WsEvent } from './types'
import { useWebSocket } from './hooks/useWebSocket'
import { CampaignHeader } from './components/CampaignHeader'
import { CharacterPanel } from './components/CharacterPanel'
import { ChatLog } from './components/ChatLog'
import { ChatInput } from './components/ChatInput'

export default function App() {
  const [session, setSession] = useState<SessionState | null>(null)
  const [turns, setTurns] = useState<TurnEntry[]>([])
  const [activeCharId, setActiveCharId] = useState<string | null>(null)
  const [streaming, setStreaming] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Use the first campaign for now — production flow will add campaign selection
  const [campaignId, setCampaignId] = useState<string | null>(null)

  // Load campaigns on mount and pick the first active one
  useEffect(() => {
    fetch('/api/campaigns')
      .then((r) => r.json())
      .then((data: { campaigns: Array<{ id: string; status: string }> }) => {
        const active = data.campaigns.find((c) => c.status === 'active')
        if (active) setCampaignId(active.id)
      })
      .catch(() => setError('Failed to load campaigns'))
  }, [])

  const handleWsMessage = useCallback((event: WsEvent) => {
    switch (event.event) {
      case 'session.state': {
        const s = event.payload
        setSession(s)
        setTurns(
          s.recent_turns.map((t) => ({
            ...t,
            narrative: t.narrative ?? null,
          })),
        )
        if (s.characters.length > 0 && !activeCharId) {
          setActiveCharId(s.characters[0].id)
        }
        break
      }
      case 'turn.narrative_start':
        setStreaming('')
        break
      case 'turn.narrative_chunk':
        setStreaming((prev) => (prev ?? '') + event.payload.chunk)
        break
      case 'turn.narrative_end': {
        const narrative = event.payload.narrative
        setStreaming(null)
        setTurns((prev) => {
          // Update the pending turn (last entry with null narrative)
          const idx = [...prev].reverse().findIndex((t) => t.narrative === null)
          if (idx === -1) return prev
          const realIdx = prev.length - 1 - idx
          const updated = [...prev]
          updated[realIdx] = { ...updated[realIdx], narrative }
          return updated
        })
        break
      }
      case 'system.error':
        setError(event.payload.message)
        break
    }
  }, [activeCharId])

  const { status: wsStatus } = useWebSocket(campaignId, { onMessage: handleWsMessage })

  const handleSubmit = async (action: string) => {
    if (!campaignId || !activeCharId || streaming !== null) return

    // Optimistically add the turn entry
    const pendingTurn: TurnEntry = {
      turn_id: crypto.randomUUID(),
      sequence_number: (session?.campaign.turn_count ?? 0) + 1,
      character_id: activeCharId,
      player_action: action,
      narrative: null,
    }
    setTurns((prev) => [...prev, pendingTurn])

    try {
      const res = await fetch(`/api/campaigns/${campaignId}/turns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character_id: activeCharId, action }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError((body as { message?: string }).message ?? 'Turn submission failed')
        // Remove the optimistic entry
        setTurns((prev) => prev.filter((t) => t.turn_id !== pendingTurn.turn_id))
      } else {
        // Update session turn count
        const { sequence_number } = await res.json()
        setSession((s) =>
          s ? { ...s, campaign: { ...s.campaign, turn_count: sequence_number } } : s,
        )
        // Swap the optimistic turn_id with the real one from the response
        // (narrative arrives via WS)
      }
    } catch {
      setError('Network error — turn not submitted')
      setTurns((prev) => prev.filter((t) => t.turn_id !== pendingTurn.turn_id))
    }
  }

  if (error) {
    return (
      <div style={styles.center}>
        <p style={{ color: 'var(--color-danger)', fontStyle: 'italic' }}>{error}</p>
        <button style={styles.retryBtn} onClick={() => setError(null)}>
          Dismiss
        </button>
      </div>
    )
  }

  if (!campaignId || !session) {
    return (
      <div style={styles.center}>
        <h1 style={styles.splash}>Tavern</h1>
        <p style={{ color: 'var(--color-parchment-dim)' }}>
          {!campaignId ? 'No active campaign found.' : 'Loading campaign…'}
        </p>
      </div>
    )
  }

  const activeChar: CharacterState | undefined = session.characters.find(
    (c) => c.id === activeCharId,
  )

  return (
    <div style={styles.layout}>
      {/* Sidebar */}
      <aside style={styles.sidebar}>
        <div style={styles.sidebarTitle}>Characters</div>
        {session.characters.map((c) => (
          <CharacterPanel
            key={c.id}
            character={c}
            isActive={c.id === activeCharId}
            onClick={() => setActiveCharId(c.id)}
          />
        ))}
        {activeChar && (
          <div style={styles.sceneMeta}>
            {session.scene.location && (
              <p style={styles.sceneItem}>
                <strong>Location:</strong> {session.scene.location}
              </p>
            )}
            {session.scene.time_of_day && (
              <p style={styles.sceneItem}>
                <strong>Time:</strong> {session.scene.time_of_day}
              </p>
            )}
          </div>
        )}
      </aside>

      {/* Main column */}
      <div style={styles.main}>
        <CampaignHeader campaign={session.campaign} wsStatus={wsStatus} />
        <ChatLog turns={turns} streamingNarrative={streaming} />
        <ChatInput
          disabled={streaming !== null || wsStatus !== 'open'}
          onSubmit={handleSubmit}
        />
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  layout: {
    display: 'flex',
    height: '100vh',
    overflow: 'hidden',
  },
  sidebar: {
    width: '260px',
    flexShrink: 0,
    background: 'var(--color-bg-panel)',
    borderRight: '1px solid var(--color-border)',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
    padding: '0.75rem',
  },
  sidebarTitle: {
    fontSize: '0.7rem',
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
    color: 'var(--color-gold-dim)',
    paddingBottom: '0.4rem',
    borderBottom: '1px solid var(--color-border)',
    marginBottom: '0.25rem',
  },
  sceneMeta: {
    marginTop: 'auto',
    paddingTop: '1rem',
    borderTop: '1px solid var(--color-border)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.3rem',
  },
  sceneItem: {
    fontSize: '0.75rem',
    color: 'var(--color-parchment-dim)',
  },
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
    overflow: 'hidden',
  },
  center: {
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '1rem',
  },
  splash: {
    fontSize: '4rem',
    color: 'var(--color-gold)',
    letterSpacing: '0.2em',
    textTransform: 'uppercase',
  },
  retryBtn: {
    background: 'transparent',
    border: '1px solid var(--color-gold-dim)',
    color: 'var(--color-gold)',
    padding: '0.4rem 1rem',
    borderRadius: '4px',
    fontSize: '0.85rem',
  },
}
