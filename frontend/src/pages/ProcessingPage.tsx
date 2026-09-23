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
import { profileText, statusText, workflowText } from '../i18n'

const ENGINE_UI: Record<ProcessingEngine, { eyebrow: string; icon: typeof Map }> = {
  odm: { eyebrow: 'Photogrammetrie / Kartierung', icon: Map },
  micmac: { eyebrow: 'Alternative Photogrammetrie', icon: ScanLine },
  gsplat: { eyebrow: 'Gaussian Splatting / 3DGS', icon: Sparkles },
  thermal: { eyebrow: 'Radiometrische Thermografie', icon: Thermometer },
  telesculptor: { eyebrow: 'Experimenteller / älterer Vergleich', icon: FlaskConical },
}

const PROFILE_ICONS = {
  preview: Gauge,
  standard: Layers3,
  high: Box,
} satisfies Record<ProcessingProfile, typeof Gauge>

function optionLabel(value: string) {
  const labels: Record<string, string> = {
    emissivity: 'Emissionsgrad',
    distance_m: 'Entfernung (m)',
    humidity_pct: 'Luftfeuchtigkeit (%)',
    reflection_c: 'Reflektierte Temperatur (°C)',
    ambient_temp_c: 'Umgebungstemperatur (°C)',
    hotspot_delta_c: 'Hotspot-Differenz (°C)',
    hotspot_min_pixels: 'Hotspot-Mindestpixel',
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
  return error instanceof Error ? error.message : 'Anfrage fehlgeschlagen.'
}

function serviceLabel(services: ServicesResponse | undefined, engine: ProcessingEngine) {
  const state = services?.[engine]
  if (!state) return 'Status unbekannt'
  if (state.status === 'experimental') return 'Experimentell'
  if (state.status === 'optional') return 'Optionaler Dienst'
  return statusText(state.status)
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
  if (!readiness) return 'Bereitschaft nicht gemeldet'
  if (workflow === 'multispectral') {
    return `${readiness.complete_groups ?? 0} vollständige Gruppen · ${readiness.eligible_images} Bilder`
  }
  if (workflow === 'thermal') {
    return `${readiness.complete_groups ?? 0} vollständige WIDE+THERMAL-Gruppen · ${readiness.platform ?? 'Plattform unbestätigt'}`
  }
  return `${readiness.eligible_images} geeignete RGB/WIDE-Bilder`
}

function optionError(raw: string | undefined, definition: ProcessingOptionDefinition) {
  if (raw == null || raw.trim() === '') return undefined
  const value = Number(raw)
  if (!Number.isFinite(value)) return 'Eine gültige Zahl eingeben.'
  if (definition.type === 'integer' && !Number.isInteger(value)) return 'Eine ganze Zahl eingeben.'
  if (definition.minimum != null && value < definition.minimum) return `Minimum ist ${definition.minimum}.`
  if (definition.minimum_exclusive != null && value <= definition.minimum_exclusive) {
    return `Muss größer als ${definition.minimum_exclusive} sein.`
  }
  if (definition.maximum != null && value > definition.maximum) return `Maximum ist ${definition.maximum}.`
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
  const [workflow, setWorkflow] = useState<ProcessingWorkflow>('mapping')
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
      setWorkflow(currentEngine.workflows[0]?.key ?? 'mapping')
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
    setWorkflow(definition?.workflows[0]?.key ?? 'mapping')
  }

  if (loading) {
    return (
      <div className="panel loading-state" role="status">
        <LoaderCircle className="spin" size={24} />
        <span>Verarbeitungskatalog und Dienste werden geladen …</span>
      </div>
    )
  }

  if (!catalog) {
    return (
      <div className="panel error-state">
        <TriangleAlert size={26} />
        <h2>Verarbeitungskatalog nicht verfügbar</h2>
        <p>{error ?? 'Das Backend hat keinen Verarbeitungskatalog geliefert.'}</p>
        <button className="button" type="button" onClick={() => void load()}>
          <RefreshCw size={16} /> Erneut versuchen
        </button>
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
            <p>Engine-Fähigkeiten, Arbeitsabläufe, Profile und Optionen werden aus dem Backend-Katalog geladen.</p>
          </div>
          <button className="button" type="button" onClick={() => void load()}>
            <RefreshCw size={16} />
            Katalog aktualisieren
          </button>
        </div>

        <label className="field processing-dataset-select">
          <span>Datensatz</span>
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
            <span><strong>{statusText(selectedDataset.scan_status)}</strong> Metadatenstatus</span>
            <span>
              <strong>{qaLoading ? 'Wird geprüft …' : engineReadiness?.ready ? 'Bereit' : 'Blockiert'}</strong>
              {selectedEngine?.title ?? engine} Bereitschaft
            </span>
          </div>
        )}
      </section>

      {workflow === 'mapping' && qa?.mapping && (
        <section className="panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Mapping-Readiness</p>
              <h3>
                {qa.mapping.status === 'ready'
                  ? 'Bereit'
                  : qa.mapping.status === 'warning'
                    ? 'Bereit mit Warnung'
                    : 'Blockiert'}
              </h3>
              <p>
                {qa.mapping.reason ??
                  'GPS- und Mapping-Metadaten sind für die Verarbeitung ausreichend.'}
              </p>
            </div>
          </div>
          <div className="processing-dataset-summary">
            <span><strong>{qa.mapping.eligible_images}</strong> RGB/WIDE</span>
            <span><strong>{qa.mapping.geotagged_percent}%</strong> Mapping-GPS</span>
            <span>
              <strong>{qa.mapping.rtk_fixed_images}</strong> RTK-Fix · {qa.mapping.rtk_metadata_images} mit RTK-Metadatum
            </span>
            <span>
              <strong>{qa.mapping.orientation_metadata_images}</strong> mit vollständiger DJI-Lage
            </span>
            <span>
              <strong>
                {Object.values(qa.mapping.checks).filter((check) => check.status === 'warning').length}
              </strong>{' '}
              fachliche QA-Warnungen
            </span>
            <span>
              <strong>
                {Object.values(qa.mapping.checks).filter((check) => check.status === 'unknown').length}
              </strong>{' '}
              Checks nicht bestimmbar
            </span>
          </div>
          {qa.mapping.reasons.map((reason) => (
            <p className="warning-copy" key={reason.code}>
              <TriangleAlert size={16} />
              {reason.message}
            </p>
          ))}
        </section>
      )}

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Verarbeitungs-Engine</p>
            <h3>Backend-Ausführungspfad</h3>
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
                <p>{item.description ?? item.workflows[0]?.description ?? item.workflows[0]?.title ?? 'Backend-Verarbeitungs-Engine.'}</p>
                <div className="engine-output">
                  {outputs.length ? outputs.slice(0, 5).join(' · ') : 'Keine automatisierten Ausgaben angegeben'}
                </div>
                <div className="engine-capabilities">
                  {item.requires_gpu && <span>GPU erforderlich</span>}
                  {item.requires_dji_tsdk && <span>DJI Thermal SDK erforderlich</span>}
                  {item.experimental && <span>Experimentell</span>}
                  {!item.automated && <span>Nur manuell</span>}
                </div>
              </button>
            )
          })}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Verarbeitungsablauf</p>
            <h3>Datensatzinterpretation</h3>
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
                  <span>{item.description ?? 'Vom Backend definierter Verarbeitungsablauf.'}</span>
                </div>
                <small>{workflowRequirement(engine, item.key, qa)}</small>
              </button>
            ))}
          </div>
        ) : (
          <div className="compact-empty">
            <FlaskConical size={22} />
            <span>Diese Engine steht nicht als automatisierter Backend-Ablauf zur Verfügung.</span>
          </div>
        )}
      </section>

      {engine === 'thermal' && selectedWorkflow && (
        <section className="panel thermal-boundary-panel">
          <div>
            <p className="eyebrow">Semantik der Thermal-Ausgaben</p>
            <h3>Radiometrische Verarbeitung M3T / M4T</h3>
          </div>
          <div className="thermal-boundary-grid">
            <span><strong>SDK</strong>{selectedEngine?.requires_dji_tsdk ? 'Lokales DJI Thermal SDK erforderlich' : 'Nicht erforderlich'}</span>
            <span><strong>Temperaturraum</strong>{selectedWorkflow.temperature_space ?? 'Nicht gemeldet'}</span>
            <span><strong>WIDE ↔ THERMAL</strong>{selectedWorkflow.wide_thermal_coregistered ? 'Koregistriert' : 'Nicht koregistriert'}</span>
            <span><strong>Georeferenziertes Temperaturraster</strong>{selectedWorkflow.georeferenced_temperature_raster ? 'Verfügbar' : 'Nicht verfügbar'}</span>
          </div>
          <p className="warning-copy">
            <TriangleAlert size={16} />
            Temperaturraster bleiben im Sensor-Pixelraum. Sie dürfen nicht als georeferenziertes Thermal-Orthomosaik dargestellt werden.
          </p>
        </section>
      )}

      {Object.keys(selectedWorkflow?.options ?? {}).length > 0 && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Typisierte Auftragsoptionen</p>
              <h3>Radiometrie- und Hotspot-Parameter</h3>
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
                  {optionErrors[key] ?? definition.note ?? (definition.default != null ? `Backend-Standard: ${definition.default}` : 'Optionale Vorgabe')}
                </small>
              </label>
            ))}
          </div>
          <p className="helper-text">
            Es werden nur vom Backend-Katalog deklarierte Optionen gesendet. Messwertvorgaben werden erneut vom Backend und DJI DIRP validiert.
          </p>
        </section>
      )}

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Verarbeitungsprofil</p>
            <h3>Vom Backend definiertes Qualitäts-/Ressourcenprofil</h3>
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
                  <strong>{profileText(item)}</strong>
                  <span>{definition?.purpose ?? 'Für den gewählten Workflow nicht verfügbar.'}</span>
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
          <h3>{selectedEngine?.title ?? engine} · {selectedWorkflow?.title ?? 'Manuell'} · {profileText(profile)}</h3>
          {!selectedEngine?.automated ? (
            <p className="warning-copy">
              <TriangleAlert size={16} />
              {selectedEngine?.description ?? 'Diese Engine ist nicht über die automatisierte Auftragswarteschlange verfügbar.'}
            </p>
          ) : engineReadiness && !engineReadiness.ready ? (
            <p className="warning-copy">
              <TriangleAlert size={16} />
              {engineReadiness.reason ?? 'Dieser Datensatz ist für den gewählten Ablauf nicht bereit.'}
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
            <span>{createdJob.id} · {createdJob.engine} · {workflowText(createdJob.workflow ?? workflow)} · {profileText(createdJob.profile)} · {statusText(createdJob.status)}</span>
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
          <span>Kein Datensatz verfügbar. Vor dem Erstellen eines Auftrags zuerst Bilddaten importieren.</span>
        </div>
      )}

      <JobMonitor focusJobId={createdJob?.id} />
    </div>
  )
}
