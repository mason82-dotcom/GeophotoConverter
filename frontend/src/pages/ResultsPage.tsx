import {
  Box,
  Download,
  File,
  FileArchive,
  FileImage,
  FileText,
  Flame,
  Layers3,
  LoaderCircle,
  MapPinned,
  Mountain,
  RefreshCw,
  ScanLine,
  ScrollText,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getJob, getJobLogs, listDatasets, listJobs } from '../api/client'
import type { Artifact, Dataset, Job, JobLogs } from '../api/types'
import { profileText, workflowText } from '../i18n'

interface ResultJob {
  job: Job
  logs?: JobLogs
}

function formatBytes(bytes?: number) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KiB', 'MiB', 'GiB', 'TiB']
  let value = bytes / 1024
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[index]}`
}

function artifactLabel(artifact: Artifact) {
  const type = artifact.type.toLowerCase()
  const name = artifact.name.toLowerCase()
  if (type === 'thermal_temperature_tiff') return { label: 'Temperatur-TIFF', icon: Flame }
  if (type === 'thermal_preview') return { label: 'Thermal-Vorschau', icon: FileImage }
  if (type === 'thermal_hotspot_mask') return { label: 'Hotspot-Maske', icon: Flame }
  if (type === 'thermal_hotspots') return { label: 'Hotspots', icon: Flame }
  if (type === 'thermal_capture_points') return { label: 'Thermal-Aufnahmepunkte', icon: MapPinned }
  if (type === 'thermal_summary') return { label: 'Thermal-Zusammenfassung', icon: FileText }
  if (type === 'thermal_registration_audit') return { label: 'Registrierungsprüfung', icon: ScanLine }
  if (type.includes('multiband_orthophoto')) return { label: 'Multiband-Orthophoto', icon: FileImage }
  if (type.includes('orthophoto')) return { label: 'Orthophoto', icon: FileImage }
  if (type === 'dsm') return { label: 'DSM', icon: Mountain }
  if (type === 'dtm') return { label: 'DTM', icon: Mountain }
  if (type.includes('point_cloud') || name.endsWith('.las') || name.endsWith('.laz')) return { label: 'Punktwolke', icon: ScanLine }
  if (name.endsWith('.ply') || type.includes('ply')) return { label: type.includes('gsplat') ? 'gsplat PLY' : 'PLY', icon: Sparkles }
  if (name.endsWith('.obj') || type.includes('mesh')) return { label: 'Mesh / OBJ', icon: Box }
  if (name.endsWith('.tif') || name.endsWith('.tiff') || type.includes('geotiff')) return { label: 'GeoTIFF', icon: Layers3 }
  if (type.includes('checkpoint') || /\.(ckpt|pt|pth)$/.test(name)) return { label: 'gsplat-Prüfpunkt', icon: FileArchive }
  if (name.endsWith('.log') || type.includes('log')) return { label: 'Log', icon: ScrollText }
  if (name.endsWith('.pdf')) return { label: 'Bericht', icon: FileText }
  return { label: artifact.type || 'Artefakt', icon: File }
}

export function ResultsPage() {
  const [items, setItems] = useState<ResultJob[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [filter, setFilter] = useState('all')

  const load = useCallback(async () => {
    setLoading(true)
    setError(undefined)
    try {
      const [jobs, datasetList] = await Promise.all([listJobs(), listDatasets()])
      const completed = jobs.filter((job) => job.status === 'completed')
      const detailResults = await Promise.allSettled(
        completed.map(async (job) => {
          const [detail, logs] = await Promise.all([getJob(job.id), getJobLogs(job.id, 60)])
          return { job: detail, logs }
        }),
      )
      setItems(
        detailResults
          .filter((result): result is PromiseFulfilledResult<ResultJob> => result.status === 'fulfilled')
          .map((result) => result.value),
      )
      setDatasets(datasetList)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Ergebnisse konnten nicht geladen werden.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const categories = useMemo(() => {
    const values = new Set<string>()
    items.forEach(({ job }) => job.artifacts?.forEach((artifact) => values.add(artifactLabel(artifact).label)))
    if (items.some((item) => item.logs?.available)) values.add('Protokolle')
    return Array.from(values).sort()
  }, [items])

  const datasetById = useMemo(() => new Map(datasets.map((dataset) => [dataset.id, dataset.name])), [datasets])

  if (loading) {
    return <div className="panel loading-state"><LoaderCircle className="spin" size={24} /> Ergebnisse werden geladen …</div>
  }

  if (error && !items.length) {
    return (
      <div className="panel error-state">
        <TriangleAlert size={26} />
        <h2>Ergebnisse nicht verfügbar</h2>
        <p>{error}</p>
        <button className="button" type="button" onClick={() => void load()}><RefreshCw size={16} /> Retry</button>
      </div>
    )
  }

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Verarbeitungsausgaben</p>
            <h2>Ergebnisartefakte</h2>
            <p>Abgeschlossene Backend-Aufträge und deren herunterladbare, vom Backend gemeldete Ausgaben.</p>
          </div>
          <button className="button" type="button" onClick={() => void load()}><RefreshCw size={16} /> Refresh</button>
        </div>
        <div className="result-filters" aria-label="Ergebnistyp-Filter">
          <button className={`filter-chip ${filter === 'all' ? 'filter-chip--active' : ''}`} type="button" onClick={() => setFilter('all')}>Alle</button>
          {categories.map((category) => (
            <button key={category} className={`filter-chip ${filter === category ? 'filter-chip--active' : ''}`} type="button" onClick={() => setFilter(category)}>
              {category}
            </button>
          ))}
        </div>
      </section>

      {!items.length ? (
        <section className="panel empty-state">
          <p className="eyebrow">Ergebnisse</p>
          <h2>Noch keine abgeschlossenen Ergebnisse</h2>
          <p>Abgeschlossene Verarbeitungsaufträge erscheinen hier mit den vom Backend bereitgestellten Artefakten.</p>
        </section>
      ) : (
        <div className="result-job-list">
          {items.map(({ job, logs }) => {
            const artifacts = (job.artifacts ?? []).filter((artifact) => filter === 'all' || artifactLabel(artifact).label === filter)
            const showLogs = logs?.available && (filter === 'all' || filter === 'Protokolle')
            if (!artifacts.length && !showLogs) return null
            return (
              <section className="panel result-job" key={job.id}>
                <div className="result-job-heading">
                  <div>
                    <p className="eyebrow">{job.engine.toUpperCase()} · {workflowText(job.workflow ?? 'rgb')} · {profileText(job.profile)}</p>
                    <h3>{datasetById.get(job.dataset_id) ?? job.dataset_id.slice(0, 8)}</h3>
                  </div>
                  <span className="mono-badge">{job.id.slice(0, 8)}</span>
                </div>

                <div className="artifact-grid">
                  {artifacts.map((artifact, index) => {
                    const meta = artifactLabel(artifact)
                    const Icon = meta.icon
                    return (
                      <article className="artifact-card" key={`${artifact.name}-${index}`}>
                        <div className="artifact-card-icon"><Icon size={20} /></div>
                        <div className="artifact-card-body">
                          <span className="artifact-kind">{meta.label}</span>
                          <strong>{artifact.name}</strong>
                          <small>{formatBytes(artifact.size_bytes)}</small>
                        </div>
                        {artifact.download_url ? (
                          <a className="button artifact-download" href={artifact.download_url} download>
                            <Download size={15} />
                            Download
                          </a>
                        ) : (
                          <span className="status-chip status-chip--neutral">Keine URL</span>
                        )}
                      </article>
                    )
                  })}

                  {showLogs && (
                    <article className="artifact-card artifact-card--log">
                      <div className="artifact-card-icon"><ScrollText size={20} /></div>
                      <div className="artifact-card-body">
                        <span className="artifact-kind">Protokolle</span>
                        <strong>Letzte Worker-Protokollzeilen</strong>
                        <small>{logs?.lines.length ?? 0} lines loaded</small>
                      </div>
                      <details className="result-log-details">
                        <summary>Anzeigen</summary>
                        <pre>{logs?.lines.join('\n') || 'Keine Protokollzeilen.'}</pre>
                      </details>
                    </article>
                  )}
                </div>
              </section>
            )
          })}
        </div>
      )}

      {error && items.length > 0 && (
        <div className="inline-message inline-message--error"><TriangleAlert size={17} /> {error}</div>
      )}
    </div>
  )
}
