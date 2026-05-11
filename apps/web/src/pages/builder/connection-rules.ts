// Connection protocol for the voice flow builder.
//
// Mirrored in apps/api/app/schemas/flow_graph_validators.py — keep in sync.

import type { StepEdge, StepKind, StepNode } from './types'

export interface KindRule {
  /** May this kind receive inbound edges? */
  inAllowed: boolean
  /** Maximum outbound edges allowed from this kind. */
  outMax: number
  /** If true, outbound edges from this kind must carry a label (e.g. condition). */
  outNeedsLabel: boolean
  /** Allowed labels (when outNeedsLabel). */
  allowedLabels?: string[]
  /** True if this kind is a graph terminator. */
  terminal: boolean
  /** True if this kind is a graph root (must have exactly one per graph). */
  root: boolean
}

export const RULES: Record<StepKind, KindRule> = {
  greeting: { inAllowed: false, outMax: 1, outNeedsLabel: false, terminal: false, root: true },
  collect: { inAllowed: true, outMax: 1, outNeedsLabel: false, terminal: false, root: false },
  api: { inAllowed: true, outMax: 1, outNeedsLabel: false, terminal: false, root: false },
  condition: {
    inAllowed: true,
    outMax: 2,
    outNeedsLabel: true,
    allowedLabels: ['yes', 'no'],
    terminal: false,
    root: false,
  },
  transfer: { inAllowed: true, outMax: 1, outNeedsLabel: false, terminal: false, root: false },
  voicemail: { inAllowed: true, outMax: 0, outNeedsLabel: false, terminal: true, root: false },
  end: { inAllowed: true, outMax: 0, outNeedsLabel: false, terminal: true, root: false },
}

export const TERMINAL_KINDS: ReadonlySet<StepKind> = new Set(
  (Object.keys(RULES) as StepKind[]).filter((k) => RULES[k].terminal),
)

export interface ConnectCheck {
  ok: boolean
  reason?: string
  /** When true, frontend should open the branch-label dialog before committing. */
  needsLabel?: boolean
}

/**
 * Check whether a proposed edge `source → target` is allowed given the
 * current graph state. Stateless: caller passes nodes+edges.
 */
export function canConnect(
  source: string | null | undefined,
  target: string | null | undefined,
  nodes: StepNode[],
  edges: StepEdge[],
): ConnectCheck {
  if (!source || !target) return { ok: false, reason: 'missing source or target' }
  if (source === target) return { ok: false, reason: 'self-loop not allowed' }

  const src = nodes.find((n) => n.id === source)
  const tgt = nodes.find((n) => n.id === target)
  if (!src || !tgt) return { ok: false, reason: 'node not found' }

  const srcRule = RULES[src.data.kind]
  const tgtRule = RULES[tgt.data.kind]

  if (srcRule.terminal || srcRule.outMax === 0) {
    return { ok: false, reason: `${src.data.kind} is terminal — no outbound edges` }
  }
  if (!tgtRule.inAllowed) {
    return { ok: false, reason: `${tgt.data.kind} cannot receive inbound edges` }
  }

  // Duplicate edge?
  if (edges.some((e) => e.source === source && e.target === target)) {
    return { ok: false, reason: 'edge already exists' }
  }

  const outbound = edges.filter((e) => e.source === source).length
  if (outbound >= srcRule.outMax) {
    return {
      ok: false,
      reason: `${src.data.kind} already has ${outbound}/${srcRule.outMax} outbound edge(s)`,
    }
  }

  return { ok: true, needsLabel: srcRule.outNeedsLabel }
}

/**
 * Which labels remain available for new outbound edges from a node?
 * For non-label-required sources, returns [].
 */
export function remainingLabels(sourceId: string, nodes: StepNode[], edges: StepEdge[]): string[] {
  const src = nodes.find((n) => n.id === sourceId)
  if (!src) return []
  const rule = RULES[src.data.kind]
  if (!rule.outNeedsLabel || !rule.allowedLabels) return []
  const used = new Set(
    edges
      .filter((e) => e.source === sourceId && typeof e.label === 'string')
      .map((e) => String(e.label).toLowerCase()),
  )
  return rule.allowedLabels.filter((l) => !used.has(l))
}

export interface GraphValidation {
  errors: string[]
  warnings: string[]
}

/**
 * Whole-graph validation. Used both client-side (UI warnings) and mirrored
 * server-side at publish time.
 */
export function validateGraph(nodes: StepNode[], edges: StepEdge[]): GraphValidation {
  const errors: string[] = []
  const warnings: string[] = []

  // Exactly one greeting (root)
  const roots = nodes.filter((n) => RULES[n.data.kind].root)
  if (roots.length === 0) errors.push('graph must contain a greeting node')
  if (roots.length > 1) errors.push(`graph must have exactly one greeting (found ${roots.length})`)

  // Per-node outbound limits + label requirements
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const outBySource = new Map<string, StepEdge[]>()
  for (const e of edges) {
    if (!byId.has(e.source) || !byId.has(e.target)) {
      errors.push(`edge ${e.id} references unknown node`)
      continue
    }
    if (e.source === e.target) errors.push(`edge ${e.id} is a self-loop`)
    const arr = outBySource.get(e.source) ?? []
    arr.push(e)
    outBySource.set(e.source, arr)
  }
  for (const [sourceId, outs] of outBySource) {
    const src = byId.get(sourceId)
    if (!src) continue
    const rule = RULES[src.data.kind]
    if (outs.length > rule.outMax) {
      errors.push(`${src.id} (${src.data.kind}) has ${outs.length} outbound edges (max ${rule.outMax})`)
    }
    if (rule.outNeedsLabel) {
      const labels = outs.map((o) => (typeof o.label === 'string' ? o.label.toLowerCase() : ''))
      if (labels.some((l) => !l)) errors.push(`${src.id} (condition) has unlabeled outbound edges`)
      const dupes = labels.filter((l, i) => labels.indexOf(l) !== i)
      if (dupes.length) errors.push(`${src.id} (condition) has duplicate branch labels: ${dupes.join(',')}`)
    }
  }

  // Inbound to root forbidden
  for (const e of edges) {
    const tgt = byId.get(e.target)
    if (tgt && !RULES[tgt.data.kind].inAllowed) {
      errors.push(`edge ${e.id} targets ${tgt.data.kind} which forbids inbound`)
    }
  }

  // Cycle detection (DFS), starting from each root.
  if (roots.length > 0) {
    const adj = new Map<string, string[]>()
    for (const e of edges) {
      const a = adj.get(e.source) ?? []
      a.push(e.target)
      adj.set(e.source, a)
    }
    const WHITE = 0
    const GREY = 1
    const BLACK = 2
    const color = new Map<string, number>()
    nodes.forEach((n) => color.set(n.id, WHITE))
    let cycle = false
    const stack: { id: string; iter: number }[] = []
    for (const root of roots) {
      if (color.get(root.id) !== WHITE) continue
      stack.push({ id: root.id, iter: 0 })
      color.set(root.id, GREY)
      while (stack.length) {
        const top = stack[stack.length - 1]
        const children = adj.get(top.id) ?? []
        if (top.iter >= children.length) {
          color.set(top.id, BLACK)
          stack.pop()
          continue
        }
        const next = children[top.iter++]
        const c = color.get(next) ?? WHITE
        if (c === GREY) {
          cycle = true
          break
        }
        if (c === WHITE) {
          color.set(next, GREY)
          stack.push({ id: next, iter: 0 })
        }
      }
      if (cycle) break
    }
    if (cycle) errors.push('graph contains a cycle')
  }

  // Reachability: every non-root node should be reachable from a root.
  if (roots.length === 1) {
    const seen = new Set<string>()
    const queue = [roots[0].id]
    const adj = new Map<string, string[]>()
    for (const e of edges) {
      const a = adj.get(e.source) ?? []
      a.push(e.target)
      adj.set(e.source, a)
    }
    while (queue.length) {
      const id = queue.shift() as string
      if (seen.has(id)) continue
      seen.add(id)
      for (const c of adj.get(id) ?? []) queue.push(c)
    }
    for (const n of nodes) {
      if (!seen.has(n.id)) warnings.push(`${n.id} (${n.data.kind}) is unreachable from greeting`)
    }
  }

  // Every non-terminal reachable node should have at least one outbound edge.
  for (const n of nodes) {
    const rule = RULES[n.data.kind]
    if (rule.terminal) continue
    const outs = outBySource.get(n.id) ?? []
    if (outs.length === 0) warnings.push(`${n.id} (${n.data.kind}) has no outbound edge`)
  }

  return { errors, warnings }
}
