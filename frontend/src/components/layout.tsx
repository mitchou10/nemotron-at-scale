import { Activity, AudioLines, LayoutDashboard, LogOut, Mic, Moon, Server, Sun } from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useRange } from '@/hooks/use-range'
import { type Theme, useTheme } from '@/hooks/use-theme'
import { getToken } from '@/lib/api'
import { RANGES } from '@/lib/range'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: "Vue d'ensemble", icon: LayoutDashboard, end: true },
  { to: '/workers', label: 'Workers', icon: Server },
  { to: '/stt', label: 'Transcription', icon: Mic },
  { to: '/tts', label: 'Synthèse vocale', icon: AudioLines },
]

const TITLES: Record<string, string> = {
  '/': "Vue d'ensemble",
  '/workers': 'Workers',
  '/stt': 'Transcription (STT)',
  '/tts': 'Synthèse vocale (TTS)',
}

const NEXT_THEME: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' }

export function Layout({ onLogout }: { onLogout: () => void }) {
  const { pathname, search } = useLocation()
  const [range, setRange] = useRange()
  const { theme, setTheme } = useTheme()
  const showRange = pathname !== '/workers'

  return (
    <div className="bg-background text-foreground flex min-h-screen">
      <aside className="bg-sidebar border-sidebar-border sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r p-4 md:flex">
        <div className="mb-6 flex items-center gap-2 px-2">
          <span className="bg-primary text-primary-foreground flex size-8 items-center justify-center rounded-lg">
            <Activity className="size-4" />
          </span>
          <div className="leading-tight">
            <p className="font-semibold">Nemotron</p>
            <p className="text-muted-foreground text-xs">Administration</p>
          </div>
        </div>
        <nav className="flex flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={{ pathname: to, search }}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
                    : 'text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground',
                )
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <p className="text-muted-foreground mt-auto px-2 text-xs">Données rafraîchies toutes les 10 s</p>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="bg-background/80 sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b px-4 py-3 backdrop-blur md:px-6">
          <h1 className="mr-auto text-lg font-semibold">{TITLES[pathname] ?? 'Nemotron'}</h1>
          {showRange && (
            <div className="bg-muted flex rounded-lg p-0.5" role="group" aria-label="Période">
              {RANGES.map((r) => (
                <Button
                  key={r.id}
                  size="sm"
                  variant={r.id === range.id ? 'default' : 'ghost'}
                  onClick={() => setRange(r.id)}
                >
                  {r.label}
                </Button>
              ))}
            </div>
          )}
          <Button
            size="icon"
            variant="ghost"
            aria-label={`Thème : ${theme}`}
            onClick={() => setTheme(NEXT_THEME[theme])}
          >
            {theme === 'dark' ? <Moon className="size-4" /> : <Sun className="size-4" />}
          </Button>
          {getToken() && (
            <Button size="icon" variant="ghost" aria-label="Se déconnecter" onClick={onLogout}>
              <LogOut className="size-4" />
            </Button>
          )}
        </header>

        <nav className="flex gap-1 overflow-x-auto border-b px-4 py-2 md:hidden">
          {NAV.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={{ pathname: to, search }}
              end={end}
              className={({ isActive }) =>
                cn(
                  'rounded-md px-3 py-1 text-sm whitespace-nowrap',
                  isActive ? 'bg-muted font-medium' : 'text-muted-foreground',
                )
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>

        <main className="flex-1 space-y-6 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
