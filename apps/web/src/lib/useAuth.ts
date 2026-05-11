import { useEffect, useState } from 'react'
import { auth, type MeResponse } from './api'

export function useAuth() {
  const [me, setMe] = useState<MeResponse | null | undefined>(undefined)
  useEffect(() => {
    let cancelled = false
    auth
      .me()
      .then((m) => {
        if (!cancelled) setMe(m)
      })
      .catch(() => {
        if (!cancelled) setMe(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return {
    me,
    loading: me === undefined,
    signedIn: Boolean(me),
    logout: async () => {
      await auth.logout()
      setMe(null)
    },
  }
}
