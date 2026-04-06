import { useEffect, useRef } from 'react'
import type { TurnEntry } from '../types'

interface Props {
  turns: TurnEntry[]
  streamingNarrative: string | null
  onSelectTurn?: (turnId: string) => void
}

export function ChatLog({ turns, streamingNarrative, onSelectTurn }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, streamingNarrative])

  return (
    <div style={styles.log}>
      {turns.length === 0 && streamingNarrative === null && (
        <p style={styles.empty}>The adventure awaits. What will you do?</p>
      )}

      {turns.map((t) => (
        <div
          key={t.turn_id}
          style={{
            ...styles.entry,
            ...(onSelectTurn ? styles.entryClickable : {}),
          }}
          onClick={onSelectTurn ? () => onSelectTurn(t.turn_id) : undefined}
          title={onSelectTurn ? 'Click to inspect this turn' : undefined}
        >
          <p style={styles.action}>&gt; {t.player_action}</p>
          {t.rules_result && (
            <p style={styles.rulesResult}>{t.rules_result}</p>
          )}
          {t.narrative && <p style={styles.narrative}>{t.narrative}</p>}
        </div>
      ))}

      {streamingNarrative !== null && (
        <div style={styles.entry}>
          <p style={styles.narrative}>
            {streamingNarrative}
            <span style={styles.cursor}>▌</span>
          </p>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  log: {
    flex: 1,
    overflowY: 'auto',
    padding: '1.25rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '1.5rem',
  },
  empty: {
    color: 'var(--color-parchment-dim)',
    fontStyle: 'italic',
    textAlign: 'center',
    marginTop: '3rem',
  },
  entry: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  entryClickable: {
    cursor: 'pointer',
    borderRadius: '4px',
    padding: '0.25rem',
    margin: '-0.25rem',
    transition: 'background 0.15s',
  },
  action: {
    color: 'var(--color-gold-dim)',
    fontStyle: 'italic',
    fontSize: '0.9rem',
  },
  rulesResult: {
    color: 'var(--color-parchment-dim)',
    fontSize: '0.82rem',
    fontFamily: 'var(--font-mono)',
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid var(--color-border)',
    borderRadius: '3px',
    padding: '0.3rem 0.6rem',
  },
  narrative: {
    color: 'var(--color-parchment)',
    lineHeight: 1.8,
    fontSize: '1rem',
  },
  cursor: {
    display: 'inline-block',
    animation: 'blink 1s step-end infinite',
    color: 'var(--color-gold)',
  },
}
