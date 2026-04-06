import { useCallback, useState } from 'react'
import type {
  CharacterState,
  CombatState,
  MechanicalResultEntry,
  SessionState,
  SessionTelemetry,
  TurnEntry,
  TurnEventLog,
  TurnMechanicalGroup,
  WsEvent,
  WsSessionTelemetryEvent,
  WsTurnEventLogEvent,
} from '../types'

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
import { MechanicalLog } from './MechanicalLog'
import { InspectPanel } from './InspectPanel'

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
  const [combat, setCombat] = useState<CombatState | null>(null)
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [characterSheetOpen, setCharacterSheetOpen] = useState(false)
  const [sheetCharacterId, setSheetCharacterId] = useState<string | null>(null)
  const [mechLog, setMechLog] = useState<TurnMechanicalGroup[]>([])
  const [preMigration, setPreMigration] = useState(false)
  const [logTab, setLogTab] = useState<'story' | 'log'>('story')
  const [eventLogCache, setEventLogCache] = useState<Map<string, TurnEventLog>>(new Map())
  const [sessionTelemetry, setSessionTelemetry] = useState<SessionTelemetry | null>(null)
  const [inspectOpen, setInspectOpen] = useState(false)
  const [inspectTab, setInspectTab] = useState<'turn' | 'session'>('session')
  const [selectedTurnLog, setSelectedTurnLog] = useState<TurnEventLog | null>(null)
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
          setCombat(s.combat
            ? {
                initiativeOrder: s.combat.initiative_order,
                surprised: s.combat.surprised,
                currentRound: 1,
                currentTurnIndex: 0,
              }
            : null,
          )
          if (s.characters.length > 0 && !activeCharId) {
            setActiveCharId(s.characters[0].id)
          }
          // Build mechanical log from recent_turns.
          // If none of the turns have a mechanical_results key at all,
          // treat this as a pre-migration payload.
          const anyHasMechKey = s.recent_turns.some(
            (t) => 'mechanical_results' in t,
          )
          setPreMigration(!anyHasMechKey)
          if (anyHasMechKey) {
            const charById: Record<string, string> = {}
            for (const c of s.characters) charById[c.id] = c.name
            setMechLog(
              s.recent_turns.map((t) => ({
                turn_id: t.turn_id,
                sequence_number: t.sequence_number,
                character_name:
                  t.character_name ??
                  charById[t.character_id] ??
                  t.character_id,
                entries: (t.mechanical_results ?? []) as MechanicalResultEntry[],
                created_at: t.created_at ?? '',
              })),
            )
          }
          break
        }
        case 'turn.narrative_start':
          setStreaming('')
          setSuggestions([])
          break
        case 'turn.narrative_chunk':
          setStreaming((prev) => (prev ?? '') + event.payload.chunk)
          break
        case 'turn.narrative_end': {
          const { narrative, mechanical_results, turn_id, sequence_number, character_name, created_at } =
            event.payload
          setStreaming(null)
          setTurns((prev) => {
            const idx = [...prev].reverse().findIndex((t) => t.narrative === null)
            if (idx === -1) return prev
            const realIdx = prev.length - 1 - idx
            const updated = [...prev]
            updated[realIdx] = { ...updated[realIdx], narrative }
            return updated
          })
          // Append new turn group to mechanical log
          if (mechanical_results !== null && mechanical_results !== undefined) {
            setMechLog((prev) => {
              // Avoid duplicates (e.g. reconnect delivering session.state followed by stale event)
              if (prev.some((g) => g.turn_id === turn_id)) return prev
              // Resolve character name: prefer payload field, then look up from session
              const resolvedName = character_name ?? turn_id
              return [
                ...prev,
                {
                  turn_id,
                  sequence_number: sequence_number ?? (prev.length > 0 ? prev[prev.length - 1].sequence_number + 1 : 1),
                  character_name: resolvedName,
                  entries: mechanical_results,
                  created_at: created_at ?? new Date().toISOString(),
                },
              ]
            })
          }
          // Advance combat turn index after every turn.narrative_end
          setCombat((prev) => {
            if (!prev) return prev
            const nextIndex = prev.currentTurnIndex + 1
            if (nextIndex >= prev.initiativeOrder.length) {
              return { ...prev, currentTurnIndex: 0, currentRound: prev.currentRound + 1 }
            }
            return { ...prev, currentTurnIndex: nextIndex }
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
        // combat.started / combat.ended arrive as live events during a session.
        // The switch had no cases for them, so they were silently dropped —
        // combat UI only updated after reconnect (which delivers session.state).
        case 'combat.started':
          setCombat({
            initiativeOrder: event.payload.initiative_order,
            surprised: event.payload.surprised,
            currentRound: 1,
            currentTurnIndex: 0,
          })
          break
        case 'combat.ended':
          setCombat(null)
          break
        case 'turn.suggested_actions':
          setSuggestions(event.payload.suggestions)
          break
      }

      // ADR-0018 observability events use "type" key (not "event")
      const rawMsg = event as unknown as { type?: string; payload?: unknown }
      if (rawMsg.type === 'turn.event_log') {
        const payload = (rawMsg as WsTurnEventLogEvent).payload
        setEventLogCache((prev) => {
          const next = new Map(prev)
          next.set(payload.turn_id, payload as TurnEventLog)
          // Keep last 50 turns
          if (next.size > 50) {
            const firstKey = next.keys().next().value
            if (firstKey !== undefined) next.delete(firstKey)
          }
          return next
        })
      }
      if (rawMsg.type === 'session.telemetry') {
        const payload = (rawMsg as WsSessionTelemetryEvent).payload
        setSessionTelemetry(payload as SessionTelemetry)
      }
    },
    [activeCharId],
  )

  const { status: wsStatus } = useWebSocket(campaignId, { onMessage: handleWsMessage })

  const handleSelectTurn = useCallback(
    async (turnId: string) => {
      setInspectOpen(true)
      setInspectTab('turn')
      const cached = eventLogCache.get(turnId)
      if (cached) {
        setSelectedTurnLog(cached)
        return
      }
      // Not in cache — fetch from REST
      try {
        const res = await fetch(`/api/campaigns/${campaignId}/turns/${turnId}/event_log`)
        if (res.ok) {
          const data = await res.json() as { turn_id: string; event_log: TurnEventLog }
          const log = { ...data.event_log, turn_id: data.turn_id }
          setEventLogCache((prev) => {
            const next = new Map(prev)
            next.set(turnId, log)
            return next
          })
          setSelectedTurnLog(log)
        }
      } catch {
        // Silently fail — TurnDetail will show "no trace" message
      }
    },
    [campaignId, eventLogCache],
  )

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
            {!isMobile && (
              // TODO: gate on campaign ownership — ADR-0006
              <button
                style={{ ...s.btn, ...s.btnSecondary, padding: '0.3rem 0.5rem' }}
                onClick={() => setInspectOpen((v) => !v)}
                title={inspectOpen ? 'Close Inspect' : 'Inspect'}
              >
                🔍
              </button>
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

        {/* Combat panel */}
        {combat && (
          <div style={s.combatPanel}>
            <span style={s.combatBadge}>COMBAT · Round {combat.currentRound}</span>
            <div style={s.initiativeHeader}>
              <span style={s.initiativeRank}>#</span>
              <span style={{ ...s.initiativeName, color: 'var(--color-parchment-dim)', fontSize: '0.65rem', letterSpacing: '0.08em' }}>Name</span>
              <span style={{ ...s.initiativeRoll, color: 'var(--color-parchment-dim)', fontSize: '0.65rem', letterSpacing: '0.08em' }}>Init</span>
            </div>
            {combat.initiativeOrder.map((entry, i) => {
              const char = session.characters.find((c) => c.id === entry.character_id)
              const name = char?.name ?? entry.character_id
              const isSurprised = combat.currentRound === 1 && combat.surprised.includes(entry.character_id)
              const isActive = i === combat.currentTurnIndex
              return (
                <div key={entry.character_id} style={{
                  ...s.initiativeEntry,
                  ...(isActive ? { color: 'var(--color-parchment)', background: 'rgba(192,57,43,0.1)', borderRadius: '3px', paddingLeft: '0.25rem', marginLeft: '-0.25rem' } : {}),
                }}>
                  <span style={{ ...s.initiativeRank, ...(isActive ? { color: 'var(--color-danger)' } : {}) }}>{i + 1}.</span>
                  <span style={s.initiativeName}>
                    {name}
                    {isSurprised && <span style={s.surprisedMark}> !</span>}
                  </span>
                  <span style={s.initiativeRoll}>{entry.initiative_result}</span>
                </div>
              )
            })}
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

      {/* Main column: narrative + mechanical log */}
      <div style={s.main}>
        {isMobile && (
          <button style={s.menuBtn} onClick={() => setSidebarOpen(true)} title="Characters">☰</button>
        )}
        <CampaignHeader
          campaign={session.campaign}
          wsStatus={wsStatus}
          combatDisplay={combat ? {
            currentRound: combat.currentRound,
            currentTurnIndex: combat.currentTurnIndex,
            entries: combat.initiativeOrder.map((entry) => {
              const char = session.characters.find((c) => c.id === entry.character_id)
              return {
                id: entry.character_id,
                name: char?.name ?? entry.character_id,
                initiative: entry.initiative_result,
                surprised: combat.currentRound === 1 && combat.surprised.includes(entry.character_id),
              }
            }),
          } : null}
        />

        {/* Mobile tab bar */}
        <div className="log-tab-bar">
          <button
            className={logTab === 'story' ? 'active' : ''}
            onClick={() => setLogTab('story')}
          >
            📜 Story
          </button>
          <button
            className={logTab === 'log' ? 'active' : ''}
            onClick={() => setLogTab('log')}
          >
            ⚔️ Log
          </button>
        </div>

        {/* Content area: narrative left, log right (desktop); tab-switched (mobile) */}
        <div style={s.contentArea}>
          {/* Narrative pane */}
          <div
            style={{
              ...s.narrativePane,
              display: isMobile && logTab !== 'story' ? 'none' : 'flex',
            }}
          >
            <ChatLog
              turns={turns}
              streamingNarrative={streaming}
              onSelectTurn={!isMobile ? handleSelectTurn : undefined}
            />
            <ChatInput
              disabled={streaming !== null || wsStatus !== 'open'}
              onSubmit={handleSubmit}
              suggestions={suggestions}
              onSuggestionDismiss={() => setSuggestions([])}
            />
          </div>

          {/* Mechanical log pane */}
          <div
            style={{
              ...s.logPane,
              display: isMobile && logTab !== 'log' ? 'none' : 'flex',
            }}
          >
            <span className="mech-log-label">⚔️ Mechanical Log</span>
            <MechanicalLog turnGroups={mechLog} preMigration={preMigration} />
          </div>

          {/* Inspect panel — desktop only, host-only TODO ADR-0006 */}
          {!isMobile && inspectOpen && (
            <div style={s.inspectPane}>
              <InspectPanel
                campaignId={campaignId}
                tab={inspectTab}
                onTabChange={setInspectTab}
                eventLogCache={eventLogCache}
                sessionTelemetry={sessionTelemetry}
                selectedTurnLog={selectedTurnLog}
                onSelectTurnLog={setSelectedTurnLog}
              />
            </div>
          )}
        </div>
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
  combatPanel: {
    marginTop: '0.5rem',
    paddingTop: '0.75rem',
    borderTop: '1px solid var(--color-border)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.25rem',
  },
  combatBadge: {
    fontSize: '0.65rem',
    letterSpacing: '0.14em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-danger)',
    fontWeight: 700,
    marginBottom: '0.25rem',
  },
  initiativeHeader: {
    display: 'flex',
    alignItems: 'baseline',
    gap: '0.3rem',
    fontSize: '0.65rem',
    color: 'var(--color-parchment-dim)',
    opacity: 0.6,
    marginBottom: '0.1rem',
  },
  initiativeEntry: {
    display: 'flex',
    alignItems: 'baseline',
    gap: '0.3rem',
    fontSize: '0.75rem',
    color: 'var(--color-parchment-dim)',
  },
  initiativeRank: {
    color: 'var(--color-gold-dim)',
    minWidth: '1rem',
  },
  initiativeName: {
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  initiativeRoll: {
    color: 'var(--color-gold)',
    fontWeight: 600,
    minWidth: '1.5rem',
    textAlign: 'right' as const,
  },
  surprisedMark: {
    color: 'var(--color-danger)',
    fontWeight: 700,
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
  contentArea: {
    flex: 1,
    display: 'flex',
    flexDirection: 'row',
    overflow: 'hidden',
    minHeight: 0,
  },
  narrativePane: {
    flex: '3 1 0',
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
    overflow: 'hidden',
  },
  logPane: {
    flex: '2 1 0',
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
    overflow: 'hidden',
  },
  inspectPane: {
    width: '24rem',
    flexShrink: 0,
    borderLeft: '1px solid var(--color-border)',
    background: 'var(--color-bg-panel)',
    display: 'flex',
    flexDirection: 'column',
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
