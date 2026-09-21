import { useState } from 'react'
import { Activity, ArrowRight, Database, Images, ServerCog } from 'lucide-react'
import { AppShell, type NavKey } from './components/AppShell'
import { DatasetsPage } from './pages/DatasetsPage'
import { ImportPage } from './pages/ImportPage'
import { ProcessingPage } from './pages/ProcessingPage'
import { ResultsPage } from './pages/ResultsPage'
import { DroneDBPage } from './pages/DroneDBPage'
import { AssistantPage } from './pages/AssistantPage'
import { SettingsPage } from './pages/SettingsPage'

function Overview({ onNavigate }: { onNavigate: (next: NavKey) => void }) {
  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Aerial survey workstation</p>
          <h2>Import, validate, process, and publish geotagged imagery.</h2>
          <p className="hero-copy">
            GeoPhoto Converter keeps imagery QA, map context, processing jobs, and artifacts in one focused operator UI.
          </p>
        </div>
        <button className="button button--primary" type="button" onClick={() => onNavigate('import')}>
          Start import
          <ArrowRight size={17} />
        </button>
      </section>

      <section className="metric-grid" aria-label="Workspace summary">
        <article className="metric-card">
          <div className="metric-icon"><ServerCog size={19} /></div>
          <div><span className="metric-label">Backend</span><strong>Not checked</strong></div>
        </article>
        <article className="metric-card">
          <div className="metric-icon"><Images size={19} /></div>
          <div><span className="metric-label">Datasets</span><strong>—</strong></div>
        </article>
        <article className="metric-card">
          <div className="metric-icon"><Activity size={19} /></div>
          <div><span className="metric-label">Processing jobs</span><strong>—</strong></div>
        </article>
        <article className="metric-card">
          <div className="metric-icon"><Database size={19} /></div>
          <div><span className="metric-label">DroneDB</span><strong>Optional</strong></div>
        </article>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Workflow</p><h3>Survey pipeline</h3></div>
        </div>
        <ol className="workflow-list">
          {['Import imagery', 'Validate metadata & GPS', 'Review dataset', 'Choose processing engine', 'Monitor job', 'Inspect results', 'Publish/export'].map((item, index) => (
            <li key={item}>
              <span className="workflow-index">{String(index + 1).padStart(2, '0')}</span>
              <span>{item}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}

export default function App() {
  const [active, setActive] = useState<NavKey>('overview')

  return (
    <AppShell active={active} onNavigate={setActive}>
      {active === 'overview' && <Overview onNavigate={setActive} />}
      {active === 'import' && <ImportPage />}
      {active === 'datasets' && <DatasetsPage />}
      {active === 'map' && <DatasetsPage mapFocused />}
      {active === 'processing' && <ProcessingPage />}
      {active === 'results' && <ResultsPage />}
      {active === 'dronedb' && <DroneDBPage />}
      {active === 'assistant' && <AssistantPage />}
      {active === 'settings' && <SettingsPage />}
    </AppShell>
  )
}
