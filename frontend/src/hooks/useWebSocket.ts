import { useCallback, useEffect, useRef, useState } from 'react'
import type { WsEvent } from '../types'

/** 'fatal' — server sent a 4xxx close code; retrying is pointless. */
type Status = 'connecting' | 'open' | 'closed' | 'error' | 'fatal'

interface UseWebSocketOptions {
  onMessage: (event: WsEvent) => void
  /** Base reconnect delay in ms (default 3000). Set to 0 to disable reconnect. */
  reconnectDelay?: number
}

/** Maximum number of reconnect attempts before giving up. */
const MAX_RETRIES = 5
/** Reconnect delay ceiling in ms (exponential backoff is capped here). */
const MAX_DELAY_MS = 30_000

export function useWebSocket(campaignId: string | null, opts: UseWebSocketOptions) {
  const { onMessage, reconnectDelay = 3000 } = opts
  const [status, setStatus] = useState<Status>('closed')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const retryCountRef = useRef(0)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  const connect = useCallback(() => {
    if (!campaignId) return

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/api/campaigns/${campaignId}/ws`

    setStatus('connecting')
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      retryCountRef.current = 0
      setStatus('open')
    }

    ws.onmessage = (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data as string) as WsEvent
        onMessageRef.current(event)
      } catch {
        // malformed frame — ignore
      }
    }

    ws.onerror = () => setStatus('error')

    ws.onclose = (event: CloseEvent) => {
      setStatus('closed')

      // 4xxx codes are permanent server-side rejections (e.g. 4004 = Campaign not
      // found). Retrying will never succeed; mark as fatal and stop.
      if (event.code >= 4000 && event.code < 5000) {
        setStatus('fatal')
        return
      }

      if (reconnectDelay > 0 && retryCountRef.current < MAX_RETRIES) {
        const delay = Math.min(
          reconnectDelay * 2 ** retryCountRef.current,
          MAX_DELAY_MS,
        )
        retryCountRef.current += 1
        reconnectTimerRef.current = setTimeout(connect, delay)
      }
    }
  }, [campaignId, reconnectDelay])

  useEffect(() => {
    retryCountRef.current = 0
    connect()
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { status }
}
