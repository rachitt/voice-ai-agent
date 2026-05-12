export type BuilderEdge = {
  id: string
  source: string
  target: string
  label?: string
}

export type BuilderState = {
  onConnect: (c: { source: string; target: string }) => void
  connectionError: string | null
  edges: BuilderEdge[]
  onEdgesChange: (changes: { id: string; type: string }[]) => void
  addNode: (kind: string, position: { x: number; y: number }) => string
}

export type BuilderHandle = { getState: () => BuilderState }
