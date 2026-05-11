import { auth } from '@/lib/api'

export function SignInPage() {
  return (
    <div className="grid min-h-screen place-items-center bg-bg text-fg">
      <div className="w-[360px] rounded-[12px] border border-border bg-panel p-6 shadow-2xl">
        <div className="mb-1 text-sm font-medium">Welcome to Voice 2.0</div>
        <div className="mb-5 text-xs text-muted">Sign in to continue</div>
        <a
          data-testid="signin-google"
          href={auth.loginGoogleUrl()}
          className="flex items-center justify-center gap-2 rounded-[10px] border border-border bg-panel-2 px-4 py-2.5 text-sm hover:bg-panel"
        >
          <GoogleG />
          Continue with Google
        </a>
        <div className="mt-4 text-center text-[11px] text-muted">
          Or keep using an API key on the Web Call page.
        </div>
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
