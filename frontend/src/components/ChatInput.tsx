import { useRef, useState } from 'react'

interface Props {
  disabled: boolean
  onSubmit: (action: string) => void
  suggestions: string[]
  onSuggestionDismiss: () => void
}

export function ChatInput({ disabled, onSubmit, suggestions, onSuggestionDismiss }: Props) {
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

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const next = e.target.value
    setValue(next)
    if (suggestions.length > 0 && next.length > 0) {
      onSuggestionDismiss()
    }
  }

  return (
    <div style={styles.wrapper}>
      {suggestions.length > 0 && (
        <div className="suggestion-chips">
          {suggestions.map((s, i) => (
            <button
              key={i}
              className="suggestion-chip"
              onClick={() => {
                setValue(s)
                onSuggestionDismiss()
                textareaRef.current?.focus()
              }}
            >
              {s}
            </button>
          ))}
        </div>
      )}
      <div style={styles.container}>
        <textarea
          ref={textareaRef}
          style={{ ...styles.textarea, opacity: disabled ? 0.5 : 1 }}
          value={value}
          onChange={handleChange}
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
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    flexShrink: 0,
    background: 'var(--color-bg-panel)',
    borderTop: '1px solid var(--color-border)',
  },
  container: {
    display: 'flex',
    gap: '0.75rem',
    padding: '0.75rem 1.25rem',
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
