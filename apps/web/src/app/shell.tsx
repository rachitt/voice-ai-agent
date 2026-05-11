import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Rocket,
  BarChart3,
  Phone,
  PhoneCall,
  BookOpen,
  Wrench,
  Settings as SettingsIcon,
  LifeBuoy,
  Plus,
  ChevronDown,
} from 'lucide-react'
import { cn } from '@/lib/cn'

type NavItem = { to: string; icon: typeof Rocket; label: string }

const NAV: NavItem[] = [
  { to: '/', icon: Rocket, label: 'Launch Console' },
  { to: '/web-call', icon: PhoneCall, label: 'Web Call' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/numbers', icon: Phone, label: 'Numbers' },
  { to: '/knowledge', icon: BookOpen, label: 'Knowledge' },
  { to: '/tools', icon: Wrench, label: 'Tools' },
  { to: '/settings', icon: SettingsIcon, label: 'Settings' },
]

export function Shell() {
  const { pathname } = useLocation()
  const active = NAV.find((n) => (n.to === '/' ? pathname === '/' : pathname.startsWith(n.to)))

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg text-fg">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar title={active?.label ?? 'Launch Console'} />
        <main className="min-h-0 flex-1 overflow-auto px-6 py-5">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function Sidebar() {
  return (
    <aside className="flex w-[232px] shrink-0 flex-col border-r border-border bg-panel">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="grid h-8 w-8 place-items-center rounded-[8px] bg-accent text-bg">
          <Plus className="h-4 w-4" strokeWidth={2.5} />
        </div>
        <div className="text-sm font-medium tracking-tight">Voice 2.0</div>
        <LifeBuoy className="ml-auto h-4 w-4 text-muted" />
      </div>

      <div className="mx-3 mb-3 mt-1 rounded-[10px] border border-border bg-panel-2 p-2">
        <div className="flex items-center justify-between px-1">
          <span className="text-[11px] uppercase tracking-wider text-muted">Support Agent</span>
          <ChevronDown className="h-3.5 w-3.5 text-muted" />
        </div>
      </div>

      <nav className="flex-1 px-2">
        {NAV.map((n) => (
          <NavItemLink key={n.to} {...n} />
        ))}
      </nav>

      <div className="m-3 rounded-[10px] border border-border bg-panel-2 p-3">
        <div className="text-[11px] uppercase tracking-wider text-muted">Credits</div>
        <div className="mt-1 text-lg font-medium">$12.45</div>
        <button className="mt-2 text-xs text-accent hover:underline">Add credits</button>
      </div>

      <div className="flex items-center gap-2 border-t border-border px-3 py-3">
        <div className="grid h-7 w-7 place-items-center rounded-full bg-accent-dim text-[11px] font-medium text-bg">
          RP
        </div>
        <div className="min-w-0 text-xs">
          <div className="truncate">Rachit</div>
          <div className="truncate text-muted">Pro Plan</div>
        </div>
      </div>
    </aside>
  )
}

function NavItemLink({ to, icon: Icon, label }: NavItem) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      data-testid={`nav-${label.toLowerCase().replace(/\s+/g, '-')}`}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 rounded-[8px] px-3 py-2 text-sm transition-colors',
          isActive
            ? 'bg-accent-soft text-fg shadow-[inset_0_0_0_1px_var(--color-border-strong)]'
            : 'text-muted hover:bg-panel-2 hover:text-fg',
        )
      }
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="truncate">{label}</span>
    </NavLink>
  )
}

function Topbar({ title }: { title: string }) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-panel/60 px-6 backdrop-blur">
      <div className="flex items-center gap-3">
        <h1 className="text-base font-medium">{title}</h1>
        <span className="text-xs text-muted">Deploy your voice agent in minutes</span>
      </div>
      <div className="flex items-center gap-2">
        <HeaderButton label="Share" />
        <HeaderButton label="Logs" />
        <HeaderButton label="Docs" />
      </div>
    </header>
  )
}

function HeaderButton({ label }: { label: string }) {
  return (
    <button className="rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs text-muted transition-colors hover:bg-panel hover:text-fg">
      {label}
    </button>
  )
}
