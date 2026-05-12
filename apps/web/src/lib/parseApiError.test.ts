import { describe, expect, it } from 'vitest'
import { parseApiError } from './parseApiError'

describe('parseApiError', () => {
  it('returns null for null/empty input', () => {
    expect(parseApiError(null)).toBeNull()
    expect(parseApiError('')).toBeNull()
  })

  it('returns null when no JSON object is embedded', () => {
    expect(parseApiError('Error: connection refused')).toBeNull()
  })

  it('returns null when JSON parse fails', () => {
    expect(parseApiError('Error: { invalid: json')).toBeNull()
  })

  it('returns null when detail.errors missing or empty', () => {
    expect(parseApiError('Error: {"detail": {}}')).toBeNull()
    expect(parseApiError('Error: {"detail": {"errors": []}}')).toBeNull()
    expect(parseApiError('Error: {"unrelated": 1}')).toBeNull()
  })

  it('returns single-error summary verbatim', () => {
    const out = parseApiError('Error: {"detail":{"errors":["bad shape"]}}')
    expect(out).not.toBeNull()
    expect(out!.summary).toBe('bad shape')
    expect(out!.errors).toEqual(['bad shape'])
    expect(out!.tooltip).toBe('bad shape')
    expect(out!.field).toBeUndefined()
  })

  it('summary counts multi-error w/ field label', () => {
    const raw =
      'Error: {"detail":{"field":"analysis_plan","errors":["a is bad","b is bad"]}}'
    const out = parseApiError(raw)!
    expect(out.summary).toBe('2 analysis_plan errors')
    expect(out.field).toBe('analysis_plan')
    expect(out.errors).toEqual(['a is bad', 'b is bad'])
    expect(out.tooltip).toBe('a is bad\nb is bad')
  })

  it('summary counts multi-error without field label', () => {
    const out = parseApiError('Error: {"detail":{"errors":["x","y","z"]}}')!
    expect(out.summary).toBe('3 errors')
  })

  it('extracts nested object out of wrapping prose', () => {
    const raw =
      'Failed: 422 Unprocessable Entity — {"detail":{"errors":["msg"]}} trailing junk'
    const out = parseApiError(raw)!
    expect(out.errors).toEqual(['msg'])
  })
})
