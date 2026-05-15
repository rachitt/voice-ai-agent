import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '@/lib/useAuth'

/**
 * Wraps children that require a session cookie. While the cookie probe is
 * in-flight, renders a thin neutral loader (no layout shift). On 401, bounces
 * to /signin?next=<original path> so the user lands back where they wanted.
 *
 * Shell already does its own gate for the dashboard tabs; AuthGate is meant
 * for routes that don't sit under Shell, like /builder/:id.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { signedIn, loading } = useAuth()
  const { pathname, search } = useLocation()
  if (loading) {
    return (
      <div
        data-testid="auth-gate-loading"
        className="grid h-screen w-screen place-items-center bg-bg text-xs text-muted"
      >
        Checking session…
      </div>
    )
  }
  if (!signedIn) {
    const next = encodeURIComponent(pathname + search)
    return <Navigate to={`/signin?next=${next}`} replace />
  }
  return <>{children}</>
}
