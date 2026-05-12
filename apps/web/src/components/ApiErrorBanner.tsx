import { parseApiError } from '@/lib/parseApiError'
import { cn } from '@/lib/cn'

type Variant = 'banner' | 'stripe'

const VARIANT_CLS: Record<Variant, string> = {
  banner: 'mb-3 rounded border border-red-500 bg-red-500/10 p-2 text-xs text-red-300',
  stripe: 'border-b border-border bg-danger/10 px-5 py-2 text-xs text-danger',
}

/**
 * Inline error renderer that prefers a parsed `detail.errors[]` list over the
 * raw error string. Two variants:
 *   - `banner`: free-floating rounded box (default).
 *   - `stripe`: full-width strip under a panel header.
 */
export function ApiErrorBanner({
  err,
  variant = 'banner',
  testId,
  className,
}: {
  err: string | null
  variant?: Variant
  testId?: string
  className?: string
}) {
  if (!err) return null
  const parsed = parseApiError(err)
  return (
    <div role="alert" data-testid={testId} className={cn(VARIANT_CLS[variant], className)}>
      {parsed ? (
        <>
          {parsed.field && (
            <div className="mb-1 text-[10px] uppercase tracking-wider opacity-70">
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
