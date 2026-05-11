import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Shell } from './shell'
import { ConsolePage } from '@/pages/console'
import { WebCallPage } from '@/pages/web-call'
import { SignInPage } from '@/pages/signin'
import { SettingsPage } from '@/pages/settings'

const BuilderPage = lazy(() =>
  import('@/pages/builder').then((m) => ({ default: m.BuilderPage })),
)

export function AppRouter() {
  return (
    <Routes>
      <Route path="signin" element={<SignInPage />} />
      <Route element={<Shell />}>
        <Route index element={<ConsolePage />} />
        <Route path="web-call" element={<WebCallPage />} />
        <Route path="analytics" element={<Placeholder title="Analytics" />} />
        <Route path="numbers" element={<Placeholder title="Numbers" />} />
        <Route path="knowledge" element={<Placeholder title="Knowledge" />} />
        <Route path="tools" element={<Placeholder title="Tools" />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route
        path="builder/:agentId"
        element={
          <Suspense fallback={<BuilderFallback />}>
            <BuilderPage />
          </Suspense>
        }
      />
      <Route path="builder" element={<Navigate to="/builder/demo" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function BuilderFallback() {
  return (
    <div className="flex h-screen w-screen items-center justify-center bg-bg text-sm text-muted">
      Loading builder…
    </div>
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
