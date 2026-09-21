import {
  Box,
  CheckCircle2,
  Cpu,
  FlaskConical,
  Gauge,
  Layers3,
  LoaderCircle,
  Map,
  Play,
  RefreshCw,
  ScanLine,
  ServerCog,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { createJob, getServices, listDatasets } from '../api/client'
import { ApiError, type Dataset, type Job, type ProcessingEngine, type ProcessingProfile, type ServicesResponse } from '../api/types'
import { JobMonitor } from '../components/JobMonitor'
import { profileText, readinessText, statusText } from '../i18n'

interface EngineDefinition {
  id: ProcessingEngine
  name: string
  eyebrow: string
  description: string
  output: string
  note: string
  icon: typeof Map
  experimental?: boolean
}

const ENGINES: EngineDefinition[] = [
  {
    id: 'odm',
    name: 'OpenDroneMap',
    eyebrow: 'Primäre Photogrammetrie',
    description: 'Vermessungs-Pipeline für georeferenzierte Luftbilder.',
    output: 'Orthophoto · DSM/DTM · Punktwolke · mesh',
    note: 'Empfohlener Standard für klassische Vermessungsprodukte.',
    icon: Map,
  },
  {
    id: 'micmac',
    name: 'MicMac',
    eyebrow: 'Alternative Photogrammetrie',
    description: 'Alternative SfM- und Rekonstruktions-Engine für Vergleichsabläufe.',
    output: 'SfM · reconstruction · Photogrammetrie-Ausgaben',
    note: 'Nützlich als unabhängiger Verarbeitungsweg.',
    icon: ScanLine,
  },
  {
    id: 'gsplat',
    name: 'gsplat',
    eyebrow: 'Gaussian Splatting / 3DGS',
    description: 'GPU-orientierte Szenenrekonstruktion mit Gaussian Splatting.',
    output: '3DGS PLY · checkpoints · Szenen-Daten',
    note: 'Für die Verarbeitung auf CUDA-fähigen GPUs ausgelegt.',
    icon: Sparkles,
  },
  {
    id: 'telesculptor',
    name: 'TeleSculptor',
    eyebrow: 'Experimenteller / älterer Vergleich',
    description: 'Vergleichs-Engine für experimentelle Rekonstruktionsabläufe.',
    output: 'Experimentelle Vergleichsausgaben',
    note: 'Manueller Vergleich; das Backend nimmt dafür noch keine automatisierten Aufträge an.',
    icon: FlaskConical,
    experimental: true,
  },
]

const PROFILES: Array<{
  id: ProcessingProfile
  name: string
  description: string
  icon: typeof Gauge
}> = [
  { id: 'preview', name: 'Vorschau', description: 'Schneller Prüflauf mit reduziertem Rechenaufwand.', icon: Gauge },
  { id: 'standard', name: 'Standard', description: 'Ausgewogener Standard für reguläre Vermessungsverarbeitung.', icon: Layers3 },
  { id: 'high', name: 'Hoch', description: 'Profil mit maximalem Detailgrad, höherer Laufzeit und Ressourcenbedarf.', icon: Box },
]

function apiMessage(error: unknown) {
  if (error instanceof ApiError && error.detail && typeof error.detail === 'object') {
    const detail = (error.detail as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return error instanceof Error ? error.message : 'Anfrage fehlgeschlagen.'
}

function serviceLabel(services: ServicesResponse | undefined, engine: ProcessingEngine) {
  const state = services?.[engine]
  if (!state) return 'Status unbekannt'
  if (state.status === 'experimental') return 'Experimentell'
  if (state.status === 'optional') return 'Optionaler Dienst'
  return statusText(state.status)
}

export function ProcessingPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [services, setServices] = useState<ServicesResponse>()
  const [datasetId, setDatasetId] = useState('')
  const [engine, setEngine] = useState<ProcessingEngine>('odm')
  const [profile, setProfile] = useState<ProcessingProfile>('standard')
  const [createdJob, setCreatedJob] = useState<Job>()
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string>()

  const load = useCallback(async () => {
    setLoading(true)
    setError(undefined)
    try {
      const [datasetList, serviceState] = await Promise.all([listDatasets(), getServices()])
      setDatasets(datasetList)
      setServices(serviceState)
      setDatasetId((current) =>
        current && datasetList.some((dataset) => dataset.id === current)
          ? current
          : datasetList[0]?.id ?? '',
      )
    } catch (requestError) {
      setError(apiMessage(requestError))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === datasetId),
    [datasets, datasetId],
  )
  const selectedEngine = ENGINES.find((item) => item.id === engine)!
  const canSubmit = Boolean(datasetId) && engine !== 'telesculptor' && !submitting

  async function submit() {
    if (!canSubmit) return
    setSubmitting(true)
    setCreatedJob(undefined)
    setError(undefined)
    try {
      setCreatedJob(await createJob(datasetId, engine, profile))
    } catch (requestError) {
      setError(apiMessage(requestError))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="panel loading-state" role="status">
        <LoaderCircle className="spin" size={24} />
        <span>Verarbeitungsdienste werden geladen …</span>
      </div>
    )
  }

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Verarbeitungsziel</p>
            <h2>Datensatz und Engine auswählen</h2>
            <p>Das Frontend erstellt nur Aufträge. Die gesamte Verarbeitung erfolgt in Backend-Workern.</p>
          </div>
          <button className="button" type="button" onClick={() => void load()}>
            <RefreshCw size={16} />
            Dienste aktualisieren
          </button>
        </div>

        <label className="field processing-dataset-select">
          <span>Dataset</span>
          <select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
            {!datasets.length && <option value="">Keine Datensätze verfügbar</option>}
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name} · {dataset.image_count ?? 0} Bilder · {dataset.geotagged_percent ?? 0}% GPS
              </option>
            ))}
          </select>
        </label>

        {selectedDataset && (
          <div className="processing-dataset-summary">
            <span><strong>{selectedDataset.image_count ?? 0}</strong> Bilder</span>
            <span><strong>{selectedDataset.geotagged_percent ?? 0}%</strong> georeferenziert</span>
            <span><strong>{statusText(selectedDataset.scan_status)}</strong> Scan</span>
            <span>
              <strong>
                {selectedDataset.processing_Bereitschaft == null
                  ? 'Nicht angegeben'
                  : String(selectedDataset.processing_Bereitschaft)}
              </strong>
              Bereitschaft
            </span>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Verarbeitungs-Engine</p>
            <h3>Backend-Ausführungspfad</h3>
          </div>
        </div>
        <div className="engine-grid">
          {ENGINES.map((item) => {
            const Icon = item.icon
            const selected = item.id === engine
            return (
              <button
                key={item.id}
                type="button"
                className={`engine-card ${selected ? 'engine-card--selected' : ''}`}
                aria-pressed={selected}
                onClick={() => setEngine(item.id)}
              >
                <div className="engine-card-top">
                  <span className="engine-icon"><Icon size={21} /></span>
                  <span className={`service-badge ${item.experimental ? 'service-badge--warning' : ''}`}>
                    {serviceLabel(services, item.id)}
                  </span>
                </div>
                <p className="eyebrow">{item.eyebrow}</p>
                <h3>{item.name}</h3>
                <p>{item.description}</p>
                <div className="engine-output">{item.output}</div>
                <small>{item.note}</small>
              </button>
            )
          })}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Verarbeitungsprofil</p>
            <h3>Qualitäts-/Ressourcenprofil</h3>
          </div>
        </div>
        <div className="profile-grid">
          {PROFILES.map((item) => {
            const Icon = item.icon
            const selected = item.id === profile
            return (
              <button
                key={item.id}
                type="button"
                className={`profile-card ${selected ? 'profile-card--selected' : ''}`}
                aria-pressed={selected}
                onClick={() => setProfile(item.id)}
              >
                <Icon size={18} />
                <div>
                  <strong>{item.name}</strong>
                  <span>{item.description}</span>
                </div>
                {selected && <CheckCircle2 size={17} className="profile-check" />}
              </button>
            )
          })}
        </div>
      </section>

      <section className="panel job-submit-panel">
        <div>
          <p className="eyebrow">Auftragsanforderung</p>
          <h3>{selectedEngine.name} · {PROFILES.find((item) => item.id === profile)?.name}</h3>
          {engine === 'telesculptor' ? (
            <p className="warning-copy">
              <TriangleAlert size={16} />
              TeleSculptor dient derzeit nur dem experimentellen Vergleich. Das Backend lehnt automatisierte TeleSculptor-Aufträge aktuell ab.
            </p>
          ) : (
            <p className="muted-copy">
              <ServerCog size={16} />
              POST /api/v1/jobs erstellt den Backend-Auftrag. Im Browser findet keine Verarbeitung statt.
            </p>
          )}
        </div>
        <button className="button button--primary" type="button" disabled={!canSubmit} onClick={() => void submit()}>
          {submitting ? <LoaderCircle className="spin" size={17} /> : <Play size={17} />}
          {submitting ? 'Auftrag wird erstellt …' : 'Verarbeitungsauftrag erstellen'}
        </button>
      </section>

      {createdJob && (
        <div className="inline-message inline-message--success" role="status">
          <CheckCircle2 size={18} />
          <div>
            <strong>Auftrag erstellt</strong>
            <span>{createdJob.id} · {createdJob.engine} · {profileText(createdJob.profile)} · {statusText(createdJob.status)}</span>
          </div>
        </div>
      )}

      {error && (
        <div className="inline-message inline-message--error" role="alert">
          <TriangleAlert size={18} />
          <span>{error}</span>
        </div>
      )}

      {!datasets.length && !error && (
        <div className="inline-message">
          <Cpu size={18} />
          <span>Kein Datensatz verfügbar. Vor dem Erstellen eines Verarbeitungsauftrags zuerst Bilddaten importieren.</span>
        </div>
      )}

      <JobMonitor focusJobId={createdJob?.id} />
    </div>
  )
}
