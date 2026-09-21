import { useState } from 'react'
import { Activity, ArrowRight, Database, Images, ServerCog } from 'lucide-react'
import { AppShell, type NavKey } from './components/AppShell'

const pageCopy: Record<Exclude<NavKey, 'overview'>, { title: string; description: string }> = {
  import: {
    title: 'Import aerial imagery',
    description: 'Create a dataset from local files or a folder while preserving relative paths.',
  },
  datasets: {
    title: 'Datasets',
    description: 'Review imagery metadata, GPS coverage, warnings, and processing readiness.',
  },
  map: {
    title: 'Map',
    description: 'Inspect capture positions, flight coverage, and geospatial quality.',
  },
  processing: {
    title: 'Processing',
    description: 'Choose a backend processing engine and quality profile for a ready dataset.',
  },
  results: {
    title: 'Results',
    description: 'Inspect generated orthophotos, surfaces, point clouds, meshes, and logs.',
  },
  dronedb: {
    title: 'DroneDB',
    description: 'Publish completed datasets and artifacts to the configured DroneDB service.',
  },
  assistant: {
    title: 'Assistant',
    description: 'Open the optional AI assistant surface without leaving the operator workflow.',
  },
  settings: {
    title: 'Settings',
    description: 'Review frontend preferences and connected service state.',
  },
}

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
          <div>
            <span className="metric-label">Backend</span>
            <strong>Not checked</strong>
          </div>
        </article>
        <article className="metric-card">
          <div className="metric-icon"><Images size={19} /></div>
          <div>
            <span className="metric-label">Datasets</span>
            <strong>—</strong>
          </div>
        </article>
        <article className="metric-card">
          <div className="metric-icon"><Activity size={19} /></div>
          <div>
            <span className="metric-label">Processing jobs</span>
            <strong>—</strong>
          </div>
        </article>
        <article className="metric-card">
          <div className="metric-icon"><Database size={19} /></div>
          <div>
            <span className="metric-label">DroneDB</span>
            <strong>Optional</strong>
          </div>
        </article>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Workflow</p>
            <h3>Survey pipeline</h3>
          </div>
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

function PlaceholderPage({ active }: { active: Exclude<NavKey, 'overview'> }) {
  const copy = pageCopy[active]
  return (
    <section className="panel empty-state">
      <p className="eyebrow">Workspace module</p>
      <h2>{copy.title}</h2>
      <p>{copy.description}</p>
      <span className="status-chip status-chip--neutral">Implementation queued</span>
    </section>
  )
}

export default function App() {
  const [active, setActive] = useState<NavKey>('overview')

  return (
    <AppShell active={active} onNavigate={setActive}>
      {active === 'overview' ? <Overview onNavigate={setActive} /> : <PlaceholderPage active={active} />}
    </AppShell>
  )
}
