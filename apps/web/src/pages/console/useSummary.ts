import { useEffect, useState } from 'react'
import { api, ApiError, type ConsoleSummary } from '@/lib/api'

/** Fetch /v1/console/summary on mount; null on 401/loading so fixtures stay. */
export function useConsoleSummary() {
  const [data, setData] = useState<ConsoleSummary | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .consoleSummary()
      .then((s) => {
        if (!cancelled) setData(s)
      })
      .catch((e) => {
        if (cancelled) return
        // 401 just means no session yet — Shell will bounce to /signin.
        if (e instanceof ApiError && e.status === 401) return
        setErr(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { data, err }
}
