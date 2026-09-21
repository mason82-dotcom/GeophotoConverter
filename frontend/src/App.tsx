import { useState } from 'react'
import { Activity, ArrowRight, Database, Images, ServerCog } from 'lucide-react'
import { AppShell, type NavKey } from './components/AppShell'
import { AssistantPage } from './pages/AssistantPage'
import { DatasetsPage } from './pages/DatasetsPage'
import { DroneDBPage } from './pages/DroneDBPage'
import { ImportPage } from './pages/ImportPage'
import { ProcessingPage } from './pages/ProcessingPage'
import { ResultsPage } from './pages/ResultsPage'
import { SettingsPage } from './pages/SettingsPage'

function Overview({ onNavigate }: { onNavigate: (next: NavKey) => void }) {
  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Luftbild-Auswertestation</p>
          <h2>Georeferenzierte Luftbilder importieren, prüfen, verarbeiten und auswerten.</h2>
          <p className="hero-copy">
            GeoPhoto Converter bündelt Qualitätssicherung, Kartenkontext, Verarbeitungsaufträge und Ergebnisse in einer technischen Bedienoberfläche.
          </p>
        </div>
        <button className="button button--primary" type="button" onClick={() => onNavigate('import')}>
          Import starten
          <ArrowRight size={17} />
        </button>
      </section>

      <section className="metric-grid" aria-label="Arbeitsbereich-Übersicht">
        <article className="metric-card">
          <div className="metric-icon"><ServerCog size={19} /></div>
          <div><span className="metric-label">Backend</span><strong>Nicht geprüft</strong></div>
        </article>
        <article className="metric-card">
          <div className="metric-icon"><Images size={19} /></div>
          <div><span className="metric-label">Datensätze</span><strong>—</strong></div>
        </article>
        <article className="metric-card">
          <div className="metric-icon"><Activity size={19} /></div>
          <div><span className="metric-label">Verarbeitungsaufträge</span><strong>—</strong></div>
        </article>
        <article className="metric-card">
          <div className="metric-icon"><Database size={19} /></div>
          <div><span className="metric-label">DroneDB</span><strong>Optional</strong></div>
        </article>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Arbeitsablauf</p><h3>Vermessungs-Workflow</h3></div>
        </div>
        <ol className="workflow-list">
          {['Bilddaten importieren', 'Metadaten & GPS prüfen', 'Datensatz prüfen', 'Verarbeitungs-Engine wählen', 'Auftrag überwachen', 'Ergebnisse prüfen', 'Veröffentlichen / exportieren'].map((item, index) => (
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
