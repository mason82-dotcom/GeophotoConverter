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
import { createJob, getDatasetQa, getServices, listDatasets } from '../api/client'
import { ApiError, type Dataset, type DatasetQa, type Job, type ProcessingEngine, type ProcessingProfile, type ServicesResponse } from '../api/types'
import { JobMonitor } from '../components/JobMonitor'

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
    eyebrow: 'Primary photogrammetry',
    description: 'Survey mapping pipeline for georeferenced aerial imagery.',
    output: 'Orthophoto · DSM/DTM · point cloud · mesh',
    note: 'Recommended default for conventional mapping products.',
    icon: Map,
  },
  {
    id: 'micmac',
    name: 'MicMac',
    eyebrow: 'Alternative photogrammetry',
    description: 'Alternative SfM and reconstruction engine for comparison workflows.',
    output: 'SfM · reconstruction · photogrammetry outputs',
    note: 'Useful as an independent processing path.',
    icon: ScanLine,
  },
  {
    id: 'gsplat',
    name: 'gsplat',
    eyebrow: 'Gaussian Splatting / 3DGS',
    description: 'GPU-oriented scene reconstruction using Gaussian splatting.',
    output: '3DGS PLY · checkpoints · scene assets',
    note: 'Designed for CUDA-capable GPU processing.',
    icon: Sparkles,
  },
  {
    id: 'telesculptor',
    name: 'TeleSculptor',
    eyebrow: 'Experimental / legacy comparison',
    description: 'Comparison engine retained for experimental reconstruction workflows.',
    output: 'Experimental comparison outputs',
    note: 'Manual comparison surface; backend does not accept automated jobs yet.',
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
  { id: 'preview', name: 'Preview', description: 'Fast validation pass with reduced processing cost.', icon: Gauge },
  { id: 'standard', name: 'Standard', description: 'Balanced default for routine survey processing.', icon: Layers3 },
  { id: 'high', name: 'High', description: 'Maximum-detail profile with higher runtime and resource use.', icon: Box },
]

function apiMessage(error: unknown) {
  if (error instanceof ApiError && error.detail && typeof error.detail === 'object') {
    const detail = (error.detail as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object') {
      const message = (detail as { message?: unknown }).message
      if (typeof message === 'string') return message
    }
  }
  return error instanceof Error ? error.message : 'Request failed.'
}

function serviceLabel(services: ServicesResponse | undefined, engine: ProcessingEngine) {
  const state = services?.[engine]
  if (!state) return 'Status unknown'
  if (state.status === 'experimental') return 'Experimental'
  if (state.status === 'optional') return 'Optional service'
  return state.status
}

export function ProcessingPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [services, setServices] = useState<ServicesResponse>()
  const [datasetId, setDatasetId] = useState('')
  const [qa, setQa] = useState<DatasetQa>()
  const [qaLoading, setQaLoading] = useState(false)
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

  useEffect(() => {
    if (!datasetId) {
      setQa(undefined)
      return
    }
    let active = true
    setQaLoading(true)
    void getDatasetQa(datasetId)
      .then((nextQa) => {
        if (active) setQa(nextQa)
      })
      .catch((requestError) => {
        if (active) setError(apiMessage(requestError))
      })
      .finally(() => {
        if (active) setQaLoading(false)
      })
    return () => {
      active = false
    }
  }, [datasetId])

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === datasetId),
    [datasets, datasetId],
  )
  const selectedEngine = ENGINES.find((item) => item.id === engine)!
  const engineReadiness = engine === 'telesculptor' ? undefined : qa?.readiness[engine]
  const canSubmit =
    Boolean(datasetId) &&
    engine !== 'telesculptor' &&
    engineReadiness?.ready === true &&
    !qaLoading &&
    !submitting

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
        <span>Loading processing services…</span>
      </div>
    )
  }

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Processing target</p>
            <h2>Select dataset and engine</h2>
            <p>The frontend only submits jobs. All processing remains in backend workers.</p>
          </div>
          <button className="button" type="button" onClick={() => void load()}>
            <RefreshCw size={16} />
            Refresh services
          </button>
        </div>

        <label className="field processing-dataset-select">
          <span>Dataset</span>
          <select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
            {!datasets.length && <option value="">No datasets available</option>}
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name} · {dataset.image_count ?? 0} images · {dataset.geotagged_percent ?? 0}% GPS
              </option>
            ))}
          </select>
        </label>

        {selectedDataset && (
          <div className="processing-dataset-summary">
            <span><strong>{selectedDataset.image_count ?? 0}</strong> images</span>
            <span><strong>{selectedDataset.geotagged_percent ?? 0}%</strong> geotagged</span>
            <span><strong>{selectedDataset.scan_status}</strong> scan</span>
            <span>
              <strong>{qaLoading ? 'Checking…' : engineReadiness?.ready ? 'Ready' : 'Blocked'}</strong>
              {engine.toUpperCase()} readiness
            </span>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Processing engine</p>
            <h3>Backend execution path</h3>
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
                {item.id !== 'telesculptor' && qa?.readiness[item.id] && (
                  <div className={`engine-readiness ${qa.readiness[item.id].ready ? 'engine-readiness--ready' : 'engine-readiness--blocked'}`}>
                    {qa.readiness[item.id].ready ? 'Ready' : 'Blocked'} · {qa.readiness[item.id].eligible_images} eligible
                  </div>
                )}
              </button>
            )
          })}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Processing profile</p>
            <h3>Quality / resource preset</h3>
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
          <p className="eyebrow">Job request</p>
          <h3>{selectedEngine.name} · {PROFILES.find((item) => item.id === profile)?.name}</h3>
          {engine === 'telesculptor' ? (
            <p className="warning-copy">
              <TriangleAlert size={16} />
              TeleSculptor is exposed for experimental comparison only. The backend currently rejects automated TeleSculptor jobs.
            </p>
          ) : engineReadiness && !engineReadiness.ready ? (
            <p className="warning-copy">
              <TriangleAlert size={16} />
              {engineReadiness.reason ?? 'This dataset is not ready for the selected engine.'}
            </p>
          ) : (
            <p className="muted-copy">
              <ServerCog size={16} />
              POST /api/v1/jobs will create the backend job. No processing runs in the browser.
            </p>
          )}
        </div>
        <button className="button button--primary" type="button" disabled={!canSubmit} onClick={() => void submit()}>
          {submitting ? <LoaderCircle className="spin" size={17} /> : <Play size={17} />}
          {submitting ? 'Creating job…' : 'Create processing job'}
        </button>
      </section>

      {createdJob && (
        <div className="inline-message inline-message--success" role="status">
          <CheckCircle2 size={18} />
          <div>
            <strong>Job created</strong>
            <span>{createdJob.id} · {createdJob.engine} · {createdJob.profile} · {createdJob.status}</span>
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
          <span>No dataset is available. Import imagery before creating a processing job.</span>
        </div>
      )}

      <JobMonitor focusJobId={createdJob?.id} />
    </div>
  )
}
