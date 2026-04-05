import { useCallback, useState } from 'react'
import type { CharacterState, SessionState, TurnEntry, WsEvent } from '../types'

// ---------------------------------------------------------------------------
// Normalise a raw CharacterState from the server.
// The server puts species, languages, background, ability_modifiers, and
// proficiency_bonus inside features{} as a grab-bag. Extract known keys into
// dedicated top-level fields; everything left over becomes class_features.
// ---------------------------------------------------------------------------

const KNOWN_FEATURE_KEYS = new Set([
  'species', 'languages', 'background', 'ability_modifiers', 'proficiency_bonus',
])

function normalizeCharacter(raw: CharacterState): CharacterState {
  const f = raw.features ?? {}

  const species = (f['species'] as string | undefined) ?? raw.species
  const languages = (f['languages'] as string[] | undefined) ?? raw.languages
  const background = (f['background'] as string | undefined) ?? raw.background
  const ability_modifiers =
    (f['ability_modifiers'] as Record<string, number> | undefined) ?? raw.ability_modifiers
  const proficiency_bonus =
    (f['proficiency_bonus'] as number | undefined) ?? raw.proficiency_bonus

  const class_features: Record<string, string> = {}
  for (const [k, v] of Object.entries(f)) {
    if (!KNOWN_FEATURE_KEYS.has(k)) {
      class_features[k] = typeof v === 'string' ? v : JSON.stringify(v)
    }
  }

  return {
    ...raw,
    species,
    languages,
    background,
    ability_modifiers,
    proficiency_bonus,
    class_features: Object.keys(class_features).length > 0 ? class_features : undefined,
  }
}
import { useWebSocket } from '../hooks/useWebSocket'
import { useBreakpoint } from '../hooks/useBreakpoint'
import { CampaignHeader } from './CampaignHeader'
import { CharacterPanel } from './CharacterPanel'
import { CharacterSheetOverlay } from './CharacterSheetOverlay'
import { ChatLog } from './ChatLog'
import { ChatInput } from './ChatInput'

interface Props {
  campaignId: string
  onEndSession: () => void
}

export function GameSession({ campaignId, onEndSession }: Props) {
  const [session, setSession] = useState<SessionState | null>(null)
  const [turns, setTurns] = useState<TurnEntry[]>([])
  const [activeCharId, setActiveCharId] = useState<string | null>(null)
  const [streaming, setStreaming] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ending, setEnding] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [characterSheetOpen, setCharacterSheetOpen] = useState(false)
  const [sheetCharacterId, setSheetCharacterId] = useState<string | null>(null)
  const { isMobile } = useBreakpoint()

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 4000)
  }

  const handleWsMessage = useCallback(
    (event: WsEvent) => {
      switch (event.event) {
        case 'session.state': {
          const s = event.payload
          setSession({
            ...s,
            characters: s.characters.map(normalizeCharacter),
          })
          setTurns(
            s.recent_turns.map((t) => ({
              ...t,
              rules_result: t.rules_result ?? null,
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
            const idx = [...prev].reverse().findIndex((t) => t.narrative === null)
            if (idx === -1) return prev
            const realIdx = prev.length - 1 - idx
            const updated = [...prev]
            updated[realIdx] = { ...updated[realIdx], narrative }
            return updated
          })
          break
        }
        case 'character.updated': {
          const { character_id, hp, spell_slots } = event.payload
          setSession((s) => {
            if (!s) return s
            return {
              ...s,
              characters: s.characters.map((c) => {
                if (c.id !== character_id) return c
                // Merge only the fields the server sent; preserve ability_scores
                // and other data already on the character from session.state.
                return normalizeCharacter({ ...c, hp, spell_slots })
              }),
            }
          })
          break
        }
        case 'system.error':
          showToast(event.payload.message)
          break
      }
    },
    [activeCharId],
  )

  const { status: wsStatus } = useWebSocket(campaignId, { onMessage: handleWsMessage })

  const handleSubmit = async (action: string) => {
    if (!activeCharId || streaming !== null) return

    const pendingTurn: TurnEntry = {
      turn_id: crypto.randomUUID(),
      sequence_number: (session?.campaign.turn_count ?? 0) + 1,
      character_id: activeCharId,
      player_action: action,
      rules_result: null,
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
        const body = await res.json().catch(() => ({})) as { message?: string }
        showToast(body.message ?? 'Turn submission failed.')
        setTurns((prev) => prev.filter((t) => t.turn_id !== pendingTurn.turn_id))
      } else {
        const data = await res.json() as { sequence_number: number }
        setSession((s) =>
          s ? { ...s, campaign: { ...s.campaign, turn_count: data.sequence_number } } : s,
        )
      }
    } catch {
      showToast('Network error — turn not submitted.')
      setTurns((prev) => prev.filter((t) => t.turn_id !== pendingTurn.turn_id))
    }
  }

  const handleEndSession = async () => {
    if (ending) return
    setEnding(true)
    try {
      const res = await fetch(`/api/campaigns/${campaignId}/sessions/end`, { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { message?: string }
        showToast(body.message ?? 'Failed to end session.')
        setEnding(false)
        return
      }
      onEndSession()
    } catch {
      showToast('Network error.')
      setEnding(false)
    }
  }

  if (error) {
    return (
      <div style={s.center}>
        <p style={{ color: 'var(--color-danger)' }}>{error}</p>
        <button style={{ ...s.btn, ...s.btnSecondary }} onClick={() => setError(null)}>
          Dismiss
        </button>
      </div>
    )
  }

  if (!session) {
    return (
      <div style={s.center}>
        <p style={s.muted}>Connecting to session…</p>
      </div>
    )
  }

  const activeChar: CharacterState | undefined = session.characters.find(
    (c) => c.id === activeCharId,
  )
  const sheetCharacter: CharacterState | undefined = session.characters.find(
    (c) => c.id === sheetCharacterId,
  )

  const sidebarStyle: React.CSSProperties = isMobile
    ? {
        ...s.sidebar,
        position: 'fixed',
        top: 0, left: 0, bottom: 0,
        zIndex: 50,
        width: '16rem',
        transform: sidebarOpen ? 'translateX(0)' : 'translateX(-100%)',
        transition: 'transform 0.2s ease',
      }
    : { ...s.sidebar, width: 'clamp(12rem, 18vw, 16rem)' }

  return (
    <div style={s.layout}>
      {toast && (
        <div style={s.toast}>
          {toast}
          <button style={s.toastClose} onClick={() => setToast(null)}>×</button>
        </div>
      )}

      {/* Mobile overlay */}
      {isMobile && sidebarOpen && (
        <div
          style={s.overlay}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside style={sidebarStyle}>
        <div style={s.sidebarTop}>
          <span style={s.sidebarTitle}>Characters</span>
          <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
            {isMobile && (
              <button style={s.closeBtn} onClick={() => setSidebarOpen(false)} title="Close">×</button>
            )}
            <button
              style={{ ...s.btn, ...s.btnDanger, opacity: ending ? 0.5 : 1 }}
              onClick={handleEndSession}
              disabled={ending}
              title="End Session"
            >
              {ending ? '…' : 'End'}
            </button>
          </div>
        </div>

        {session.characters.map((c) => (
          <CharacterPanel
            key={c.id}
            character={c}
            isActive={c.id === activeCharId}
            onClick={() => {
              setActiveCharId(c.id)
              setSheetCharacterId(c.id)
              setCharacterSheetOpen(true)
            }}
          />
        ))}

        {/* Scene metadata */}
        {(session.scene.location || session.scene.time_of_day || session.scene.description) && (
          <div style={s.sceneMeta}>
            {session.scene.location && (
              <p style={s.sceneItem}>
                <strong>Location</strong> {session.scene.location}
              </p>
            )}
            {session.scene.time_of_day && (
              <p style={s.sceneItem}>
                <strong>Time</strong> {session.scene.time_of_day}
              </p>
            )}
            {session.scene.description && (
              <p style={{ ...s.sceneItem, fontStyle: 'italic', marginTop: '0.35rem' }}>
                {session.scene.description}
              </p>
            )}
          </div>
        )}

        {/* Active character info */}
        {activeChar && (
          <div style={s.activeCharInfo}>
            <p style={s.sceneItem}>
              Playing as <strong style={{ color: 'var(--color-gold)' }}>{activeChar.name}</strong>
            </p>
          </div>
        )}
      </aside>

      {/* Main column */}
      <div style={s.main}>
        {isMobile && (
          <button style={s.menuBtn} onClick={() => setSidebarOpen(true)} title="Characters">☰</button>
        )}
        <CampaignHeader campaign={session.campaign} wsStatus={wsStatus} />
        <ChatLog turns={turns} streamingNarrative={streaming} />
        <ChatInput
          disabled={streaming !== null || wsStatus !== 'open'}
          onSubmit={handleSubmit}
        />
      </div>

      {/* Character sheet overlay */}
      {characterSheetOpen && sheetCharacter && (
        <CharacterSheetOverlay
          character={sheetCharacter}
          onClose={() => setCharacterSheetOpen(false)}
        />
      )}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  layout: {
    display: 'flex',
    height: '100vh',
    overflow: 'hidden',
  },
  sidebar: {
    flexShrink: 0,
    background: 'var(--color-bg-panel)',
    borderRight: '1px solid var(--color-border)',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
    padding: '0.75rem',
  },
  overlay: {
    position: 'fixed',
    inset: 0,
    zIndex: 49,
    background: 'rgba(0,0,0,0.55)',
  },
  menuBtn: {
    position: 'absolute',
    top: '0.5rem',
    left: '0.5rem',
    zIndex: 10,
    background: 'transparent',
    border: '1px solid var(--color-border)',
    color: 'var(--color-gold-dim)',
    borderRadius: '4px',
    fontSize: '1.1rem',
    padding: '0.2rem 0.5rem',
    cursor: 'pointer',
    lineHeight: 1,
  },
  closeBtn: {
    background: 'transparent',
    border: 'none',
    color: 'var(--color-parchment-dim)',
    fontSize: '1.2rem',
    cursor: 'pointer',
    padding: '0 0.2rem',
    lineHeight: 1,
  },
  sidebarTop: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingBottom: '0.4rem',
    borderBottom: '1px solid var(--color-border)',
    marginBottom: '0.25rem',
  },
  sidebarTitle: {
    fontSize: '0.7rem',
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
    color: 'var(--color-gold-dim)',
  },
  sceneMeta: {
    marginTop: '0.5rem',
    paddingTop: '0.75rem',
    borderTop: '1px solid var(--color-border)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.3rem',
  },
  sceneItem: {
    fontSize: '0.75rem',
    color: 'var(--color-parchment-dim)',
    lineHeight: 1.5,
  },
  activeCharInfo: {
    marginTop: 'auto',
    paddingTop: '0.75rem',
    borderTop: '1px solid var(--color-border)',
  },
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
    overflow: 'hidden',
    position: 'relative',
  },
  center: {
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '1rem',
  },
  muted: {
    color: 'var(--color-parchment-dim)',
    fontStyle: 'italic',
  },
  toast: {
    position: 'fixed',
    top: '1rem',
    right: '1rem',
    zIndex: 100,
    background: 'var(--color-bg-panel)',
    border: '1px solid var(--color-danger)',
    color: 'var(--color-danger)',
    borderRadius: '4px',
    padding: '0.6rem 1rem',
    fontSize: '0.85rem',
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    maxWidth: '360px',
  },
  toastClose: {
    background: 'transparent',
    border: 'none',
    color: 'var(--color-danger)',
    fontSize: '1.1rem',
    cursor: 'pointer',
    padding: 0,
    lineHeight: 1,
  },
  btn: {
    padding: '0.3rem 0.75rem',
    borderRadius: '4px',
    fontSize: '0.78rem',
    fontWeight: 600,
    border: 'none',
    cursor: 'pointer',
    letterSpacing: '0.04em',
  },
  btnSecondary: {
    background: 'transparent',
    border: '1px solid var(--color-gold-dim)',
    color: 'var(--color-gold)',
  },
  btnDanger: {
    background: 'transparent',
    border: '1px solid #5a1a1a',
    color: '#c0392b',
    fontSize: '0.72rem',
  },
}
