import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { LogIn } from 'lucide-react'

import { ApiError, auth, setApiBase } from '@/lib/api'

/**
 * Sign-in page (route: `/signin`).
 *
 * Two paths to the same httpOnly session cookie:
 *   1. Google OAuth — anchor to /v1/auth/login/google; backend 302s back to
 *      `${web_app_base_url}` (configured server-side) with the cookie set.
 *   2. API-key exchange — POST the org's `sk_live_…` key to
 *      /v1/auth/session/api-key. The backend mints a session cookie and
 *      discards the key reference on the client. The key itself never lives
 *      in localStorage anymore, eliminating the XSS-extracts-credential risk.
 *
 * After login, lands on `?next=…` or `/`.
 */
export function SignInPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [apiKey, setApiKey] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // If already signed in, skip the form.
  useEffect(() => {
    let cancelled = false
    auth.me().then((me) => {
      if (!cancelled && me) navigate(params.get('next') || '/', { replace: true })
    })
    return () => {
      cancelled = true
    }
  }, [navigate, params])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setSubmitting(true)
    // Force same-origin so the SameSite=Lax session cookie actually rides on
    // every subsequent fetch (vite dev proxies /v1/* to the API in dev).
    setApiBase('')
    try {
      await auth.loginWithApiKey(apiKey.trim())
      navigate(params.get('next') || '/', { replace: true })
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 401 ? 'Invalid API key.' : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      data-testid="signin-root"
      className="grid min-h-screen place-items-center bg-bg p-6 text-fg"
    >
      <div className="w-full max-w-md rounded-[12px] border border-border bg-panel p-6 shadow-2xl">
        <div className="mb-1 text-sm font-medium">Welcome to Voice 2.0</div>
        <div className="mb-5 text-xs text-muted">Sign in to continue</div>

        <a
          data-testid="signin-google"
          href={auth.loginGoogleUrl()}
          className="mb-4 flex items-center justify-center gap-2 rounded-[10px] border border-border bg-panel-2 px-4 py-2.5 text-sm hover:bg-panel"
        >
          <GoogleG />
          Continue with Google
        </a>

        <div className="my-4 flex items-center gap-3 text-[10px] uppercase text-muted">
          <div className="h-px flex-1 bg-border" />
          or API key
          <div className="h-px flex-1 bg-border" />
        </div>

        <form onSubmit={submit} className="space-y-3">
          <label className="block text-xs">
            <span className="mb-1 block text-muted">API key</span>
            <input
              type="password"
              data-testid="signin-api-key"
              autoComplete="off"
              className="w-full rounded-[8px] border border-border bg-panel-2 px-2 py-1.5"
              placeholder="sk_live_..."
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </label>
          {err && (
            <div
              data-testid="signin-error"
              className="rounded-[8px] border border-red-500/40 bg-red-500/10 px-2.5 py-1.5 text-xs text-red-300"
            >
              {err}
            </div>
          )}
          <button
            type="submit"
            data-testid="signin-submit"
            disabled={!apiKey || submitting}
            className="flex w-full items-center justify-center gap-2 rounded-[10px] bg-accent px-4 py-2.5 text-sm font-medium text-bg hover:opacity-90 disabled:opacity-50"
          >
            <LogIn className="h-4 w-4" />
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}

function GoogleG() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M21.35 11.1H12v2.99h5.35c-.23 1.4-1.62 4.13-5.35 4.13-3.22 0-5.84-2.66-5.84-5.95s2.62-5.95 5.84-5.95c1.83 0 3.06.78 3.76 1.45l2.56-2.48C16.6 3.6 14.5 2.6 12 2.6c-5.18 0-9.4 4.2-9.4 9.4 0 5.18 4.22 9.4 9.4 9.4 5.42 0 9-3.8 9-9.16 0-.61-.07-1.07-.15-1.54z"
        fill="currentColor"
      />
    </svg>
  )
}
