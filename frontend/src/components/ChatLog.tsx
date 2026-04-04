import { useEffect, useRef } from 'react'
import type { TurnEntry } from '../types'

interface Props {
  turns: TurnEntry[]
  streamingNarrative: string | null
}

export function ChatLog({ turns, streamingNarrative }: Props) {
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
        <div key={t.turn_id} style={styles.entry}>
          <p style={styles.action}>&gt; {t.player_action}</p>
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
    gap: '0.6rem',
  },
  action: {
    color: 'var(--color-gold-dim)',
    fontStyle: 'italic',
    fontSize: '0.9rem',
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
