import { useRef, useState } from 'react'

interface Props {
  disabled: boolean
  onSubmit: (action: string) => void
}

export function ChatInput({ disabled, onSubmit }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSubmit = () => {
    const action = value.trim()
    if (!action || disabled) return
    onSubmit(action)
    setValue('')
    textareaRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div style={styles.container}>
      <textarea
        ref={textareaRef}
        style={{ ...styles.textarea, opacity: disabled ? 0.5 : 1 }}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={disabled ? 'The narrator is speaking…' : 'What do you do?'}
        disabled={disabled}
        rows={2}
      />
      <button
        style={{ ...styles.button, opacity: disabled || !value.trim() ? 0.4 : 1 }}
        onClick={handleSubmit}
        disabled={disabled || !value.trim()}
      >
        Act
      </button>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    gap: '0.75rem',
    padding: '0.75rem 1.25rem',
    borderTop: '1px solid var(--color-border)',
    background: 'var(--color-bg-panel)',
    flexShrink: 0,
    alignItems: 'flex-end',
  },
  textarea: {
    flex: 1,
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    borderRadius: '4px',
    color: 'var(--color-parchment)',
    padding: '0.6rem 0.75rem',
    resize: 'none',
    fontSize: '0.95rem',
    lineHeight: 1.5,
    transition: 'opacity 0.2s',
  },
  button: {
    background: 'var(--color-gold)',
    color: 'var(--color-bg)',
    border: 'none',
    borderRadius: '4px',
    padding: '0.6rem 1.25rem',
    fontWeight: 600,
    fontSize: '0.9rem',
    letterSpacing: '0.05em',
    transition: 'opacity 0.2s',
    alignSelf: 'stretch',
  },
}
