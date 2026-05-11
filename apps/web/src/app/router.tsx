import { Navigate, Route, Routes } from 'react-router-dom'
import { Shell } from './shell'
import { ConsolePage } from '@/pages/console'
import { BuilderPage } from '@/pages/builder'

export function AppRouter() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<ConsolePage />} />
        <Route path="analytics" element={<Placeholder title="Analytics" />} />
        <Route path="numbers" element={<Placeholder title="Numbers" />} />
        <Route path="knowledge" element={<Placeholder title="Knowledge" />} />
        <Route path="tools" element={<Placeholder title="Tools" />} />
        <Route path="settings" element={<Placeholder title="Settings" />} />
      </Route>
      <Route path="builder/:agentId" element={<BuilderPage />} />
      <Route path="builder" element={<Navigate to="/builder/demo" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function Placeholder({ title }: { title: string }) {
  return (
    <div className="flex h-full items-center justify-center text-muted">
      <div className="text-center">
        <h1 className="text-2xl text-fg">{title}</h1>
        <p className="mt-2 text-sm">Coming soon.</p>
      </div>
    </div>
  )
}
