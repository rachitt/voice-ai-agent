import { describe, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach } from 'vitest'
import { SaveStatusPill } from './SaveStatusPill'

afterEach(cleanup)

const TWO_ERRORS_RAW =
  'Error: 422 Unprocessable Entity — ' +
  '{"detail":{"field":"analysis_plan","errors":["bad summary","bad schema"]}}'

describe('SaveStatusPill', () => {
  it('renders nothing for idle status', () => {
    const { container } = render(<SaveStatusPill status="idle" error={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders saving label', () => {
    render(<SaveStatusPill status="saving" error={null} />)
    expect(screen.getByTestId('save-status')).toHaveTextContent('Saving')
  })

  it('renders saved label as a non-button span', () => {
    render(<SaveStatusPill status="saved" error={null} />)
    const pill = screen.getByTestId('save-status')
    expect(pill.tagName).toBe('SPAN')
    expect(pill).toHaveAttribute('data-status', 'saved')
    expect(pill).toHaveTextContent('Saved')
  })

  it('renders a plain span for error without parsable detail', () => {
    render(<SaveStatusPill status="error" error="connection refused" />)
    const pill = screen.getByTestId('save-status')
    expect(pill.tagName).toBe('SPAN')
    expect(pill).toHaveTextContent('connection refused')
    expect(screen.queryByTestId('save-error-list')).toBeNull()
  })

  it('renders dropdown trigger for parsable multi-error', () => {
    render(<SaveStatusPill status="error" error={TWO_ERRORS_RAW} />)
    const pill = screen.getByTestId('save-status')
    expect(pill.tagName).toBe('BUTTON')
    expect(pill).toHaveTextContent('2 analysis_plan errors')
    // Closed initially
    expect(screen.queryByTestId('save-error-list')).toBeNull()
    expect(pill).toHaveAttribute('aria-expanded', 'false')
  })

  it('opens the dropdown on click and shows each error', () => {
    render(<SaveStatusPill status="error" error={TWO_ERRORS_RAW} />)
    fireEvent.click(screen.getByTestId('save-status'))
    const list = screen.getByTestId('save-error-list')
    expect(list).toBeInTheDocument()
    const items = screen.getAllByTestId('save-error-item')
    expect(items.map((n) => n.textContent)).toEqual(['bad summary', 'bad schema'])
    expect(screen.getByTestId('save-status')).toHaveAttribute('aria-expanded', 'true')
  })

  it('closes the dropdown on second click', () => {
    render(<SaveStatusPill status="error" error={TWO_ERRORS_RAW} />)
    const pill = screen.getByTestId('save-status')
    fireEvent.click(pill)
    expect(screen.getByTestId('save-error-list')).toBeInTheDocument()
    fireEvent.click(pill)
    expect(screen.queryByTestId('save-error-list')).toBeNull()
  })

  it('closes on outside mousedown', () => {
    render(
      <div>
        <span data-testid="outside">outside</span>
        <SaveStatusPill status="error" error={TWO_ERRORS_RAW} />
      </div>,
    )
    fireEvent.click(screen.getByTestId('save-status'))
    expect(screen.getByTestId('save-error-list')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByTestId('outside'))
    expect(screen.queryByTestId('save-error-list')).toBeNull()
  })

  it('auto-closes the dropdown when status transitions away from error', () => {
    const { rerender } = render(
      <SaveStatusPill status="error" error={TWO_ERRORS_RAW} />,
    )
    fireEvent.click(screen.getByTestId('save-status'))
    expect(screen.getByTestId('save-error-list')).toBeInTheDocument()
    rerender(<SaveStatusPill status="saved" error={null} />)
    expect(screen.queryByTestId('save-error-list')).toBeNull()
  })
})
