/**
 * Parse a stringified API error so the UI can render structured detail.
 *
 * The frontend wraps API failures in `new Error(<text>)`, where text is the
 * raw response body. For 422 responses the body looks like:
 *
 *     { "detail": { "errors": ["msg-1", "msg-2"], "field": "analysis_plan" } }
 *
 * Returns a parsed shape when at least one error is present, else null.
 * Callers that just need a quick summary can fall back to the raw string.
 */
export function parseApiError(raw: string | null): {
  summary: string
  tooltip: string
  errors: string[]
  field?: string
} | null {
  if (!raw) return null
  const match = raw.match(/\{[\s\S]*\}/)
  if (!match) return null
  try {
    const body = JSON.parse(match[0]) as {
      detail?: { errors?: string[]; field?: string }
    }
    const errors = body.detail?.errors
    if (!errors || errors.length === 0) return null
    const field = body.detail?.field
    const summary =
      errors.length === 1
        ? errors[0]
        : `${errors.length} ${field ?? ''} errors`.trim()
    return { summary, tooltip: errors.join('\n'), errors, field }
  } catch {
    return null
  }
}
