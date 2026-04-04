import { useCallback, useEffect, useRef, useState } from 'react'
import type { WsEvent } from '../types'

type Status = 'connecting' | 'open' | 'closed' | 'error'

interface UseWebSocketOptions {
  onMessage: (event: WsEvent) => void
  /** Reconnect delay in ms (default 3000). Set to 0 to disable reconnect. */
  reconnectDelay?: number
}

export function useWebSocket(campaignId: string | null, opts: UseWebSocketOptions) {
  const { onMessage, reconnectDelay = 3000 } = opts
  const [status, setStatus] = useState<Status>('closed')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  const connect = useCallback(() => {
    if (!campaignId) return

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/api/campaigns/${campaignId}/ws`

    setStatus('connecting')
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setStatus('open')

    ws.onmessage = (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data as string) as WsEvent
        onMessageRef.current(event)
      } catch {
        // malformed frame — ignore
      }
    }

    ws.onerror = () => setStatus('error')

    ws.onclose = () => {
      setStatus('closed')
      if (reconnectDelay > 0) {
        reconnectTimerRef.current = setTimeout(connect, reconnectDelay)
      }
    }
  }, [campaignId, reconnectDelay])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { status }
}
