import { parseApiError } from '@/lib/parseApiError'

/**
 * Inline error banner that prefers a parsed `detail.errors[]` list over the
 * raw error string. Drop-in replacement for the
 * `{err && <div ...>{err}</div>}` pattern scattered across page modules.
 */
export function ApiErrorBanner({
  err,
  testId,
}: {
  err: string | null
  testId?: string
}) {
  if (!err) return null
  const parsed = parseApiError(err)
  return (
    <div
      role="alert"
      data-testid={testId}
      className="mb-3 rounded border border-red-500 bg-red-500/10 p-2 text-xs text-red-300"
    >
      {parsed ? (
        <>
          {parsed.field && (
            <div className="mb-1 text-[10px] uppercase tracking-wider text-red-300/70">
              {parsed.field}
            </div>
          )}
          <ul className="list-disc space-y-0.5 pl-4">
            {parsed.errors.map((msg, i) => (
              <li key={`${i}-${msg}`}>{msg}</li>
            ))}
          </ul>
        </>
      ) : (
        err
      )}
    </div>
  )
}
