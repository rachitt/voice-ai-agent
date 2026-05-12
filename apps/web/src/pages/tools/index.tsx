import { useCallback, useEffect, useState } from 'react'
import { Check, Pencil, Plus, RefreshCw, Trash2, Wrench, X } from 'lucide-react'
import { tools, type ToolRow } from '@/lib/api'

interface FormState {
  name: string
  description: string
  server_url: string
  method: string
  timeout_ms: number
  headers_text: string
  params_text: string
}

const blankForm: FormState = {
  name: '',
  description: '',
  server_url: '',
  method: 'POST',
  timeout_ms: 10000,
  headers_text: '{}',
  params_text: '{\n  "type": "object",\n  "properties": {}\n}',
}

export function ToolsPage() {
  const [rows, setRows] = useState<ToolRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [form, setForm] = useState<FormState>(blankForm)

  const load = useCallback(async () => {
    setErr(null)
    try {
      setRows(await tools.list())
    } catch (e) {
      setErr(String(e))
      setRows([])
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial tools fetch on mount
    void load()
  }, [load])

  async function onCreate() {
    if (!form.name.trim() || !form.server_url.trim()) {
      setErr('name and server_url are required')
      return
    }
    let headers: Record<string, string>
    let params_schema: Record<string, unknown>
    try {
      headers = JSON.parse(form.headers_text || '{}')
    } catch (e) {
      setErr(`headers JSON invalid: ${String(e)}`)
      return
    }
    try {
      params_schema = JSON.parse(form.params_text || '{}')
    } catch (e) {
      setErr(`params_schema JSON invalid: ${String(e)}`)
      return
    }
    setBusy(true)
    setErr(null)
    try {
      await tools.create({
        name: form.name.trim(),
        description: form.description || null,
        server_url: form.server_url.trim(),
        method: form.method,
        timeout_ms: form.timeout_ms,
        headers,
        params_schema,
      })
      setShowNew(false)
      setForm(blankForm)
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<{
    name: string
    server_url: string
    method: string
    timeout_ms: number
  } | null>(null)

  function startEdit(r: ToolRow) {
    setEditingId(r.id)
    setEditForm({
      name: r.name,
      server_url: r.server_url,
      method: r.method,
      timeout_ms: r.timeout_ms,
    })
  }

  async function saveEdit(id: string) {
    if (!editForm) return
    if (!editForm.name.trim() || !editForm.server_url.trim()) {
      setErr('name and server_url are required')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      await tools.update(id, {
        name: editForm.name.trim(),
        server_url: editForm.server_url.trim(),
        method: editForm.method,
        timeout_ms: editForm.timeout_ms,
      })
      setEditingId(null)
      setEditForm(null)
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function onDelete(id: string, name: string) {
    if (!confirm(`Delete tool "${name}"? Agents using it will break.`)) return
    setBusy(true)
    setErr(null)
    try {
      await tools.remove(id)
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-6" data-testid="tools-root">
      <section className="panel">
        <header className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <Wrench className="h-4 w-4 text-muted" />
            <h2 className="text-sm font-medium">Tools</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              className="grid h-7 w-7 place-items-center rounded-[6px] border border-border bg-panel-2 text-muted hover:text-fg"
              title="Refresh"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
            <button
              data-testid="new-tool"
              onClick={() => setShowNew((v) => !v)}
              className="flex items-center gap-1.5 rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs hover:bg-bg"
            >
              <Plus className="h-3.5 w-3.5" /> New tool
            </button>
          </div>
        </header>

        {err && (
          <div className="border-b border-border bg-danger/10 px-5 py-2 text-xs text-danger">
            {err}
          </div>
        )}

        {showNew && (
          <div className="grid gap-3 border-b border-border bg-panel-2 px-5 py-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Name">
                <input
                  autoFocus
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="lookup_customer"
                  className="w-full rounded-[6px] border border-border bg-bg px-2 py-1.5 text-xs outline-none focus:border-accent"
                />
              </Field>
              <Field label="Method">
                <select
                  value={form.method}
                  onChange={(e) => setForm({ ...form, method: e.target.value })}
                  className="w-full rounded-[6px] border border-border bg-bg px-2 py-1.5 text-xs outline-none focus:border-accent"
                >
                  {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="Server URL">
              <input
                value={form.server_url}
                onChange={(e) => setForm({ ...form, server_url: e.target.value })}
                placeholder="https://example.com/api/lookup"
                className="w-full rounded-[6px] border border-border bg-bg px-2 py-1.5 text-xs font-mono outline-none focus:border-accent"
              />
            </Field>
            <Field label="Description">
              <input
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="What this tool does (shown to the LLM)"
                className="w-full rounded-[6px] border border-border bg-bg px-2 py-1.5 text-xs outline-none focus:border-accent"
              />
            </Field>
            <Field label="Timeout (ms)">
              <input
                type="number"
                value={form.timeout_ms}
                onChange={(e) =>
                  setForm({ ...form, timeout_ms: Number(e.target.value) || 0 })
                }
                className="w-32 rounded-[6px] border border-border bg-bg px-2 py-1.5 text-xs outline-none focus:border-accent"
              />
            </Field>
            <Field label="Headers (JSON)">
              <textarea
                value={form.headers_text}
                onChange={(e) => setForm({ ...form, headers_text: e.target.value })}
                rows={3}
                className="w-full rounded-[6px] border border-border bg-bg px-2 py-1.5 font-mono text-xs outline-none focus:border-accent"
              />
            </Field>
            <Field label="params_schema (JSON Schema)">
              <textarea
                value={form.params_text}
                onChange={(e) => setForm({ ...form, params_text: e.target.value })}
                rows={6}
                className="w-full rounded-[6px] border border-border bg-bg px-2 py-1.5 font-mono text-xs outline-none focus:border-accent"
              />
            </Field>
            <div className="flex items-center gap-2">
              <button
                data-testid="confirm-new-tool"
                disabled={busy}
                onClick={onCreate}
                className="rounded-[6px] bg-accent px-3 py-1.5 text-xs text-bg disabled:opacity-40"
              >
                Create
              </button>
              <button
                onClick={() => {
                  setShowNew(false)
                  setForm(blankForm)
                }}
                className="rounded-[6px] border border-border bg-bg px-3 py-1.5 text-xs text-muted hover:text-fg"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {rows === null ? (
          <div className="px-5 py-8 text-sm text-muted">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="px-5 py-8 text-sm text-muted">
            No tools yet. Tools let agents call your APIs mid-conversation.
          </div>
        ) : (
          <ul className="divide-y divide-border" data-testid="tools-list">
            {rows.map((r) =>
              editingId === r.id && editForm ? (
                <li
                  key={r.id}
                  className="flex flex-wrap items-center gap-2 bg-panel-2 px-5 py-3 text-sm"
                >
                  <input
                    data-testid={`edit-name-${r.id}`}
                    value={editForm.name}
                    onChange={(e) =>
                      setEditForm({ ...editForm, name: e.target.value })
                    }
                    placeholder="name"
                    className="w-40 rounded-[6px] border border-border bg-bg px-2 py-1 text-xs outline-none focus:border-accent"
                  />
                  <select
                    value={editForm.method}
                    onChange={(e) =>
                      setEditForm({ ...editForm, method: e.target.value })
                    }
                    className="rounded-[6px] border border-border bg-bg px-2 py-1 text-xs outline-none focus:border-accent"
                  >
                    {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                  <input
                    data-testid={`edit-url-${r.id}`}
                    value={editForm.server_url}
                    onChange={(e) =>
                      setEditForm({ ...editForm, server_url: e.target.value })
                    }
                    placeholder="https://…"
                    className="min-w-[200px] flex-1 rounded-[6px] border border-border bg-bg px-2 py-1 text-xs font-mono outline-none focus:border-accent"
                  />
                  <input
                    type="number"
                    value={editForm.timeout_ms}
                    onChange={(e) =>
                      setEditForm({
                        ...editForm,
                        timeout_ms: Number(e.target.value) || 0,
                      })
                    }
                    className="w-24 rounded-[6px] border border-border bg-bg px-2 py-1 text-xs outline-none focus:border-accent"
                  />
                  <button
                    data-testid={`save-${r.id}`}
                    disabled={busy}
                    onClick={() => saveEdit(r.id)}
                    className="grid h-7 w-7 place-items-center rounded-[6px] bg-accent text-bg disabled:opacity-40"
                    title="Save"
                  >
                    <Check className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => {
                      setEditingId(null)
                      setEditForm(null)
                    }}
                    className="grid h-7 w-7 place-items-center rounded-[6px] border border-border text-muted hover:text-fg"
                    title="Cancel"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </li>
              ) : (
                <li
                  key={r.id}
                  className="flex items-center justify-between gap-3 px-5 py-3 text-sm"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium">{r.name}</span>
                      <span className="chip text-muted">{r.method}</span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-3 text-[11px] text-muted">
                      <code className="truncate font-mono">{r.server_url}</code>
                      <span>{r.timeout_ms}ms</span>
                    </div>
                    {r.description && (
                      <div className="mt-1 text-[11px] text-muted">{r.description}</div>
                    )}
                  </div>
                  <button
                    data-testid={`edit-${r.id}`}
                    disabled={busy}
                    onClick={() => startEdit(r)}
                    className="grid h-7 w-7 place-items-center rounded-[6px] text-muted hover:text-fg"
                    title="Edit"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    data-testid={`delete-${r.id}`}
                    disabled={busy}
                    onClick={() => onDelete(r.id, r.name)}
                    className="grid h-7 w-7 place-items-center rounded-[6px] text-muted hover:text-danger"
                    title="Delete"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ),
            )}
          </ul>
        )}
      </section>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wide text-muted">{label}</span>
      {children}
    </label>
  )
}
