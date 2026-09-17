import type { AgentEvent } from '../api/client'
import { wsEventsUrl } from '../api/client'
import { usePoStore } from '../store'
import { useEffect, useRef } from 'react'

export function useEventSocket(enabled: boolean) {
  const ingestEvent = usePoStore((s) => s.ingestEvent)
  const ref = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!enabled) return
    let closed = false
    let retry: number | undefined

    const connect = () => {
      const ws = new WebSocket(wsEventsUrl())
      ref.current = ws
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data as string) as AgentEvent & { type: string }
          if (data.type === 'connected') return
          ingestEvent(data)
        } catch {
          /* ignore */
        }
      }
      ws.onclose = () => {
        if (!closed) retry = window.setTimeout(connect, 1500)
      }
    }
    connect()
    return () => {
      closed = true
      if (retry) window.clearTimeout(retry)
      ref.current?.close()
    }
  }, [enabled, ingestEvent])
}
