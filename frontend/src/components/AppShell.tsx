import {
  Bot,
  Boxes,
  Database,
  Gauge,
  Images,
  Map,
  Menu,
  Orbit,
  PlaySquare,
  Settings,
  UploadCloud,
  X,
} from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'

export type NavKey =
  | 'overview'
  | 'import'
  | 'datasets'
  | 'map'
  | 'processing'
  | 'results'
  | 'dronedb'
  | 'assistant'
  | 'settings'

interface NavItem {
  id: NavKey
  label: string
  icon: typeof Gauge
}

const navItems: NavItem[] = [
  { id: 'overview', label: 'Übersicht', icon: Gauge },
  { id: 'import', label: 'Import', icon: UploadCloud },
  { id: 'datasets', label: 'Datensätze', icon: Images },
  { id: 'map', label: 'Karte', icon: Map },
  { id: 'processing', label: 'Verarbeitung', icon: PlaySquare },
  { id: 'results', label: 'Ergebnisse', icon: Boxes },
  { id: 'dronedb', label: 'DroneDB', icon: Database },
  { id: 'assistant', label: 'Assistent', icon: Bot },
  { id: 'settings', label: 'Einstellungen', icon: Settings },
]

interface AppShellProps {
  active: NavKey
  onNavigate: (next: NavKey) => void
  children: ReactNode
}

export function AppShell({ active, onNavigate, children }: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const activeItem = useMemo(() => navItems.find((item) => item.id === active), [active])

  function navigate(next: NavKey) {
    onNavigate(next)
    setSidebarOpen(false)
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Zum Inhalt springen
      </a>

      <aside className={`sidebar ${sidebarOpen ? 'sidebar--open' : ''}`} aria-label="Hauptnavigation">
        <div className="brand-row">
          <div className="brand-mark" aria-hidden="true">
            <Orbit size={23} strokeWidth={1.8} />
          </div>
          <div>
            <div className="brand-title">GeoPhoto</div>
            <div className="brand-subtitle">Converter</div>
          </div>
          <button
            className="icon-button sidebar-close"
            type="button"
            onClick={() => setSidebarOpen(false)}
            aria-label="Navigation schließen"
          >
            <X size={20} />
          </button>
        </div>

        <nav className="nav-list">
          {navItems.map((item) => {
            const Icon = item.icon
            const selected = item.id === active
            return (
              <button
                key={item.id}
                type="button"
                className={`nav-item ${selected ? 'nav-item--active' : ''}`}
                aria-current={selected ? 'page' : undefined}
                onClick={() => navigate(item.id)}
              >
                <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            )
          })}
        </nav>

        <div className="sidebar-footer">
          <span className="status-dot status-dot--neutral" aria-hidden="true" />
          <span>Lokale Arbeitsstation</span>
        </div>
      </aside>

      {sidebarOpen && (
        <button
          className="sidebar-scrim"
          type="button"
          onClick={() => setSidebarOpen(false)}
          aria-label="Navigation schließen"
        />
      )}

      <div className="workspace">
        <header className="topbar">
          <button
            className="icon-button menu-button"
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-label="Navigation öffnen"
          >
            <Menu size={20} />
          </button>
          <div>
            <div className="eyebrow">GeoPhoto Converter</div>
            <h1 className="page-title">{activeItem?.label ?? 'Übersicht'}</h1>
          </div>
          <div className="topbar-status" aria-label="Anwendungsmodus">
            <span className="status-dot status-dot--ok" aria-hidden="true" />
            <span>Bedienoberfläche</span>
          </div>
        </header>

        <main id="main-content" className="content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  )
}
