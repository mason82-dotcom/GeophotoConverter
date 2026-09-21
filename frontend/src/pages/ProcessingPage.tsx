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
  Thermometer,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  createJob,
  getDatasetQa,
  getProcessingCatalog,
  getServices,
  listDatasets,
} from '../api/client'
import {
  ApiError,
  type Dataset,
  type DatasetQa,
  type EngineReadiness,
  type Job,
  type ProcessingCatalog,
  type ProcessingEngine,
  type ProcessingOptionDefinition,
  type ProcessingProfile,
  type ProcessingWorkflow,
  type ServicesResponse,
} from '../api/types'
import { JobMonitor } from '../components/JobMonitor'

const ENGINE_UI: Record<ProcessingEngine, { eyebrow: string; icon: typeof Map }> = {
  odm: { eyebrow: 'Photogrammetry / mapping', icon: Map },
  micmac: { eyebrow: 'Alternative photogrammetry', icon: ScanLine },
  gsplat: { eyebrow: 'Gaussian Splatting / 3DGS', icon: Sparkles },
  thermal: { eyebrow: 'Radiometric thermal', icon: Thermometer },
  telesculptor: { eyebrow: 'Experimental / legacy comparison', icon: FlaskConical },
}

const PROFILE_ICONS = {
  preview: Gauge,
  standard: Layers3,
  high: Box,
} satisfies Record<ProcessingProfile, typeof Gauge>

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

function optionLabel(value: string) {
  const labels: Record<string, string> = {
    emissivity: 'Emissivity',
    distance_m: 'Distance (m)',
    humidity_pct: 'Humidity (%)',
    reflection_c: 'Reflected temperature (°C)',
    ambient_temp_c: 'Ambient temperature (°C)',
    hotspot_delta_c: 'Hotspot delta (°C)',
    hotspot_min_pixels: 'Hotspot minimum pixels',
  }
  return labels[value] ?? value.replaceAll('_', ' ')
}

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

function readinessFor(
  qa: DatasetQa | undefined,
  engine: ProcessingEngine,
  workflow: ProcessingWorkflow,
): EngineReadiness | undefined {
  if (!qa || engine === 'telesculptor') return undefined
  if (engine === 'thermal') return qa.readiness.thermal
  if (engine === 'odm' && workflow === 'multispectral') return qa.readiness.odm_multispectral
  if (engine === 'odm') return qa.readiness.odm
  if (engine === 'micmac') return qa.readiness.micmac
  if (engine === 'gsplat') return qa.readiness.gsplat
  return undefined
}

function workflowRequirement(
  engine: ProcessingEngine,
  workflow: ProcessingWorkflow,
  qa: DatasetQa | undefined,
) {
  const readiness = readinessFor(qa, engine, workflow)
  if (!readiness) return 'Readiness not reported'
  if (workflow === 'multispectral') {
    return `${readiness.complete_groups ?? 0} complete groups · ${readiness.eligible_images} images`
  }
  if (workflow === 'thermal') {
    return `${readiness.complete_groups ?? 0} complete WIDE+THERMAL groups · ${readiness.platform ?? 'platform unconfirmed'}`
  }
  return `${readiness.eligible_images} eligible RGB/WIDE images`
}

function optionError(raw: string | undefined, definition: ProcessingOptionDefinition) {
  if (raw == null || raw.trim() === '') return undefined
  const value = Number(raw)
  if (!Number.isFinite(value)) return 'Enter a finite number.'
  if (definition.type === 'integer' && !Number.isInteger(value)) return 'Enter a whole number.'
  if (definition.minimum != null && value < definition.minimum) return `Minimum is ${definition.minimum}.`
  if (definition.minimum_exclusive != null && value <= definition.minimum_exclusive) {
    return `Must be greater than ${definition.minimum_exclusive}.`
  }
  if (definition.maximum != null && value > definition.maximum) return `Maximum is ${definition.maximum}.`
  return undefined
}

export function ProcessingPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [services, setServices] = useState<ServicesResponse>()
  const [catalog, setCatalog] = useState<ProcessingCatalog>()
  const [datasetId, setDatasetId] = useState('')
  const [qa, setQa] = useState<DatasetQa>()
  const [qaLoading, setQaLoading] = useState(false)
  const [engine, setEngine] = useState<ProcessingEngine>('odm')
  const [profile, setProfile] = useState<ProcessingProfile>('standard')
  const [workflow, setWorkflow] = useState<ProcessingWorkflow>('rgb')
  const [optionValues, setOptionValues] = useState<Record<string, string>>({})
  const [createdJob, setCreatedJob] = useState<Job>()
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string>()

  const load = useCallback(async () => {
    setLoading(true)
    setError(undefined)
    try {
      const [datasetList, serviceState, processingCatalog] = await Promise.all([
        listDatasets(),
        getServices(),
        getProcessingCatalog(),
      ])
      setDatasets(datasetList)
      setServices(serviceState)
      setCatalog(processingCatalog)
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
    if (!catalog) return
    const currentEngine = catalog.engines.find((item) => item.key === engine)
    if (!currentEngine) {
      setEngine(catalog.engines[0]?.key ?? 'odm')
      return
    }
    if (!currentEngine.workflows.some((item) => item.key === workflow)) {
      setWorkflow(currentEngine.workflows[0]?.key ?? 'rgb')
    }
    if (!catalog.profiles.includes(profile)) {
      setProfile(catalog.profiles[0] ?? 'standard')
    }
  }, [catalog, engine, profile, workflow])

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
  const selectedEngine = useMemo(
    () => catalog?.engines.find((item) => item.key === engine),
    [catalog, engine],
  )
  const selectedWorkflow = useMemo(
    () => selectedEngine?.workflows.find((item) => item.key === workflow),
    [selectedEngine, workflow],
  )

  useEffect(() => {
    const defaults: Record<string, string> = {}
    Object.entries(selectedWorkflow?.options ?? {}).forEach(([key, definition]) => {
      if (definition.default != null) defaults[key] = String(definition.default)
    })
    setOptionValues(defaults)
  }, [engine, selectedWorkflow?.key])

  const engineReadiness = readinessFor(qa, engine, workflow)
  const optionErrors = useMemo(() => {
    const entries = Object.entries(selectedWorkflow?.options ?? {})
      .map(([key, definition]) => [key, optionError(optionValues[key], definition)] as const)
      .filter((entry): entry is readonly [string, string] => Boolean(entry[1]))
    return Object.fromEntries(entries)
  }, [optionValues, selectedWorkflow])
  const jobOptions = useMemo(() => {
    const result: Record<string, number> = {}
    Object.keys(selectedWorkflow?.options ?? {}).forEach((key) => {
      const raw = optionValues[key]
      if (raw != null && raw.trim() !== '' && !optionErrors[key]) {
        result[key] = Number(raw)
      }
    })
    return result
  }, [optionErrors, optionValues, selectedWorkflow])
  const canSubmit =
    Boolean(datasetId) &&
    selectedEngine?.automated === true &&
    Boolean(selectedWorkflow) &&
    engineReadiness?.ready === true &&
    Object.keys(optionErrors).length === 0 &&
    !qaLoading &&
    !submitting

  async function submit() {
    if (!canSubmit) return
    setSubmitting(true)
    setCreatedJob(undefined)
    setError(undefined)
    try {
      setCreatedJob(await createJob(datasetId, engine, profile, workflow, jobOptions))
    } catch (requestError) {
      setError(apiMessage(requestError))
    } finally {
      setSubmitting(false)
    }
  }

  function selectEngine(next: ProcessingEngine) {
    setEngine(next)
    const definition = catalog?.engines.find((item) => item.key === next)
    setWorkflow(definition?.workflows[0]?.key ?? 'rgb')
  }

  if (loading) {
    return (
      <div className="panel loading-state" role="status">
        <LoaderCircle className="spin" size={24} />
        <span>Loading processing catalog and services…</span>
      </div>
    )
  }

  if (!catalog) {
    return (
      <div className="panel error-state">
        <TriangleAlert size={26} />
        <h2>Processing catalog unavailable</h2>
        <p>{error ?? 'The backend did not return the processing capability catalog.'}</p>
        <button className="button" type="button" onClick={() => void load()}>
          <RefreshCw size={16} /> Retry
        </button>
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
            <p>Engine capabilities, workflows, profiles and typed options are loaded from the backend catalog.</p>
          </div>
          <button className="button" type="button" onClick={() => void load()}>
            <RefreshCw size={16} />
            Refresh catalog
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
              {selectedEngine?.title ?? engine} readiness
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
          {catalog.engines.map((item) => {
            const ui = ENGINE_UI[item.key]
            const Icon = ui.icon
            const selected = item.key === engine
            const outputs = Array.from(new Set(item.workflows.flatMap((entry) => entry.outputs ?? [])))
            return (
              <button
                key={item.key}
                type="button"
                className={`engine-card ${selected ? 'engine-card--selected' : ''}`}
                aria-pressed={selected}
                onClick={() => selectEngine(item.key)}
              >
                <div className="engine-card-top">
                  <span className="engine-icon"><Icon size={21} /></span>
                  <span className={`service-badge ${item.experimental ? 'service-badge--warning' : ''}`}>
                    {serviceLabel(services, item.key)}
                  </span>
                </div>
                <p className="eyebrow">{ui.eyebrow}</p>
                <h3>{item.title}</h3>
                <p>{item.description ?? item.workflows[0]?.description ?? item.workflows[0]?.title ?? 'Backend processing engine.'}</p>
                <div className="engine-output">
                  {outputs.length ? outputs.slice(0, 5).join(' · ') : 'No automated outputs declared'}
                </div>
                <div className="engine-capabilities">
                  {item.requires_gpu && <span>GPU required</span>}
                  {item.requires_dji_tsdk && <span>DJI Thermal SDK required</span>}
                  {item.experimental && <span>Experimental</span>}
                  {!item.automated && <span>Manual only</span>}
                </div>
              </button>
            )
          })}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Processing workflow</p>
            <h3>Dataset interpretation</h3>
          </div>
        </div>
        {selectedEngine?.workflows.length ? (
          <div className="workflow-card-grid">
            {selectedEngine.workflows.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`workflow-card ${workflow === item.key ? 'workflow-card--selected' : ''}`}
                aria-pressed={workflow === item.key}
                onClick={() => setWorkflow(item.key)}
              >
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.description ?? 'Backend-defined processing workflow.'}</span>
                </div>
                <small>{workflowRequirement(engine, item.key, qa)}</small>
              </button>
            ))}
          </div>
        ) : (
          <div className="compact-empty">
            <FlaskConical size={22} />
            <span>This engine is not exposed as an automated backend workflow.</span>
          </div>
        )}
      </section>

      {engine === 'thermal' && selectedWorkflow && (
        <section className="panel thermal-boundary-panel">
          <div>
            <p className="eyebrow">Thermal output semantics</p>
            <h3>M3T / M4T radiometric processing</h3>
          </div>
          <div className="thermal-boundary-grid">
            <span><strong>SDK</strong>{selectedEngine?.requires_dji_tsdk ? 'Local DJI Thermal SDK required' : 'Not required'}</span>
            <span><strong>Temperature space</strong>{selectedWorkflow.temperature_space ?? 'Not reported'}</span>
            <span><strong>WIDE ↔ THERMAL</strong>{selectedWorkflow.wide_thermal_coregistered ? 'Coregistered' : 'Not coregistered'}</span>
            <span><strong>Georeferenced temperature raster</strong>{selectedWorkflow.georeferenced_temperature_raster ? 'Available' : 'Not available'}</span>
          </div>
          <p className="warning-copy">
            <TriangleAlert size={16} />
            Temperature rasters remain in sensor-pixel space. Do not present them as a georeferenced thermal orthomosaic.
          </p>
        </section>
      )}

      {Object.keys(selectedWorkflow?.options ?? {}).length > 0 && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Typed job options</p>
              <h3>Radiometric and hotspot parameters</h3>
            </div>
          </div>
          <div className="job-options-grid">
            {Object.entries(selectedWorkflow?.options ?? {}).map(([key, definition]) => (
              <label className="field job-option-field" key={key}>
                <span>{optionLabel(key)}</span>
                <input
                  type="number"
                  step={definition.type === 'integer' ? 1 : 'any'}
                  value={optionValues[key] ?? ''}
                  onChange={(event) =>
                    setOptionValues((current) => ({ ...current, [key]: event.target.value }))
                  }
                  aria-invalid={Boolean(optionErrors[key])}
                />
                <small className={optionErrors[key] ? 'field-error' : ''}>
                  {optionErrors[key] ?? definition.note ?? (definition.default != null ? `Backend default: ${definition.default}` : 'Optional override')}
                </small>
              </label>
            ))}
          </div>
          <p className="helper-text">
            Only options declared by the backend catalog are sent. Explicit measurement overrides are validated again by the backend and DJI DIRP.
          </p>
        </section>
      )}

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Processing profile</p>
            <h3>Backend-defined quality / resource preset</h3>
          </div>
        </div>
        <div className="profile-grid">
          {catalog.profiles.map((item) => {
            const Icon = PROFILE_ICONS[item]
            const selected = item === profile
            const definition = selectedWorkflow?.profiles[item]
            return (
              <button
                key={item}
                type="button"
                className={`profile-card ${selected ? 'profile-card--selected' : ''}`}
                aria-pressed={selected}
                onClick={() => setProfile(item)}
                disabled={!definition}
              >
                <Icon size={18} />
                <div>
                  <strong>{titleCase(item)}</strong>
                  <span>{definition?.purpose ?? 'Not available for the selected workflow.'}</span>
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
          <h3>{selectedEngine?.title ?? engine} · {selectedWorkflow?.title ?? 'Manual'} · {titleCase(profile)}</h3>
          {!selectedEngine?.automated ? (
            <p className="warning-copy">
              <TriangleAlert size={16} />
              {selectedEngine?.description ?? 'This engine is not available through the automated job queue.'}
            </p>
          ) : engineReadiness && !engineReadiness.ready ? (
            <p className="warning-copy">
              <TriangleAlert size={16} />
              {engineReadiness.reason ?? 'This dataset is not ready for the selected workflow.'}
            </p>
          ) : (
            <p className="muted-copy">
              <ServerCog size={16} />
              POST /api/v1/jobs creates the backend job. No processing runs in the browser.
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
            <span>{createdJob.id} · {createdJob.engine} · {createdJob.workflow ?? workflow} · {createdJob.profile} · {createdJob.status}</span>
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
