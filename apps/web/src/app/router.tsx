import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Shell } from './shell'
import { AuthGate } from './AuthGate'
import { ConsolePage } from '@/pages/console'
import { WebCallPage } from '@/pages/web-call'
import { SignInPage } from '@/pages/signin'
import { SettingsPage } from '@/pages/settings'
import { CallsPage } from '@/pages/calls'
import { NumbersPage } from '@/pages/numbers'
import { ToolsPage } from '@/pages/tools'
import { KnowledgePage } from '@/pages/knowledge'
import { AnalyticsPage } from '@/pages/analytics'

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
        <Route path="calls" element={<CallsPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="numbers" element={<NumbersPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="tools" element={<ToolsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route
        path="builder/:agentId"
        element={
          <AuthGate>
            <Suspense fallback={<BuilderFallback />}>
              <BuilderPage />
            </Suspense>
          </AuthGate>
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

