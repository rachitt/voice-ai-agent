import { useEffect, useState } from 'react'
import { api, type ConsoleSummary, getApiKey } from '@/lib/api'

/** Fetch /v1/console/summary on mount; null while loading or unauthorised. */
export function useConsoleSummary() {
  const [data, setData] = useState<ConsoleSummary | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!getApiKey()) {
      // No API key → keep fixtures until OAuth path lands a session for SDK key
      return
    }
    let cancelled = false
    api
      .consoleSummary()
      .then((s) => {
        if (!cancelled) setData(s)
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { data, err }
}
