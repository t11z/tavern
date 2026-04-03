import { useEffect, useState } from 'react'

type HealthStatus = 'loading' | 'ok' | 'error'

export default function App() {
  const [status, setStatus] = useState<HealthStatus>('loading')

  useEffect(() => {
    fetch('/health')
      .then((res) => res.json())
      .then((data: { status: string }) => {
        setStatus(data.status === 'ok' ? 'ok' : 'error')
      })
      .catch(() => setStatus('error'))
  }, [])

  const statusLabel: Record<HealthStatus, string> = {
    loading: 'Connecting…',
    ok: 'Online',
    error: 'Unreachable',
  }

  return (
    <div style={styles.root}>
      <h1 style={styles.title}>Tavern</h1>
      <p style={styles.status}>
        Server:{' '}
        <span style={{ color: status === 'ok' ? '#d4a24e' : status === 'error' ? '#c0392b' : '#888' }}>
          {statusLabel[status]}
        </span>
      </p>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    minHeight: '100vh',
    backgroundColor: '#090502',
    color: '#d4a24e',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: 'Georgia, serif',
  },
  title: {
    fontSize: '3rem',
    margin: 0,
    letterSpacing: '0.15em',
    textTransform: 'uppercase',
  },
  status: {
    fontSize: '1rem',
    marginTop: '1rem',
    color: '#888',
  },
}
