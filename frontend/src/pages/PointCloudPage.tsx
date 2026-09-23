import { Download, LoaderCircle, RefreshCw, ScanLine, TriangleAlert } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  getPointCloudMetadata,
  getPointCloudPreview,
  listDatasets,
  listJobPointClouds,
  listJobs,
} from '../api/client'
import type {
  Dataset,
  PointCloudMetadata,
  PointCloudPreview,
  PointCloudSource,
} from '../api/types'
import { PointCloudViewer } from '../components/PointCloudViewer'

export interface PointCloudSelection {
  jobId: string
  artifactIndex: number
}

interface Props {
  initialSelection?: PointCloudSelection
}

interface SourceWithJob extends PointCloudSource {
  job_id: string
  dataset_id: string
  engine: string
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('de-DE').format(value)
}

function formatBytes(bytes: number) {
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

function coordinate(values: number[]) {
  return values.map((value) => value.toFixed(3)).join(' / ')
}

export function PointCloudPage({ initialSelection }: Props) {
  const [sources, setSources] = useState<SourceWithJob[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [selection, setSelection] = useState<PointCloudSelection | undefined>(initialSelection)
  const [metadata, setMetadata] = useState<PointCloudMetadata>()
  const [preview, setPreview] = useState<PointCloudPreview>()
  const [maxPoints, setMaxPoints] = useState(100_000)
  const [loadingSources, setLoadingSources] = useState(true)
  const [loadingCloud, setLoadingCloud] = useState(false)
  const [error, setError] = useState<string>()

  const loadSources = useCallback(async () => {
    setLoadingSources(true)
    setError(undefined)
    try {
      const [jobs, datasetList] = await Promise.all([listJobs(), listDatasets()])
      const completed = jobs.filter((job) => job.status === 'completed')
      const results = await Promise.allSettled(
        completed.map(async (job) => {
          const response = await listJobPointClouds(job.id)
          return response.pointclouds.map((source) => ({
            ...source,
            job_id: job.id,
            dataset_id: job.dataset_id,
            engine: job.engine,
          }))
        }),
      )
      const next = results.flatMap((result) => result.status === 'fulfilled' ? result.value : [])
      setSources(next)
      setDatasets(datasetList)
      setSelection((current) => {
        if (initialSelection && next.some(
          (item) => item.job_id === initialSelection.jobId && item.artifact_index === initialSelection.artifactIndex,
        )) {
          return initialSelection
        }
        if (current && next.some(
          (item) => item.job_id === current.jobId && item.artifact_index === current.artifactIndex,
        )) {
          return current
        }
        const first = next[0]
        return first ? { jobId: first.job_id, artifactIndex: first.artifact_index } : undefined
      })
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Punktwolken konnten nicht geladen werden.')
    } finally {
      setLoadingSources(false)
    }
  }, [initialSelection])

  useEffect(() => {
    void loadSources()
  }, [loadSources])

  useEffect(() => {
    if (!selection) {
      setMetadata(undefined)
      setPreview(undefined)
      return
    }
    let active = true
    setLoadingCloud(true)
    setError(undefined)
    Promise.all([
      getPointCloudMetadata(selection.jobId, selection.artifactIndex),
      getPointCloudPreview(selection.jobId, selection.artifactIndex, maxPoints),
    ])
      .then(([nextMetadata, nextPreview]) => {
        if (!active) return
        setMetadata(nextMetadata)
        setPreview(nextPreview)
      })
      .catch((requestError) => {
        if (!active) return
        setMetadata(undefined)
        setPreview(undefined)
        setError(requestError instanceof Error ? requestError.message : 'Punktwolke konnte nicht geladen werden.')
      })
      .finally(() => {
        if (active) setLoadingCloud(false)
      })
    return () => { active = false }
  }, [maxPoints, selection])

  const datasetById = useMemo(
    () => new Map(datasets.map((dataset) => [dataset.id, dataset.name])),
    [datasets],
  )
  const selectedSource = sources.find(
    (source) => source.job_id === selection?.jobId && source.artifact_index === selection.artifactIndex,
  )

  if (loadingSources) {
    return <div className="panel loading-state"><LoaderCircle className="spin" size={24} /> Punktwolken werden gesucht …</div>
  }

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">3D-Auswertung</p>
            <h2>Punktwolken</h2>
            <p>LAS/LAZ- und klassische PLY-Artefakte aus abgeschlossenen Verarbeitungsaufträgen interaktiv prüfen.</p>
          </div>
          <button className="button" type="button" onClick={() => void loadSources()}>
            <RefreshCw size={16} /> Aktualisieren
          </button>
        </div>

        {sources.length > 0 && (
          <div className="pointcloud-source-controls">
            <label>
              Punktwolke
              <select
                value={selection ? `${selection.jobId}:${selection.artifactIndex}` : ''}
                onChange={(event) => {
                  const [jobId, index] = event.target.value.split(':')
                  setSelection({ jobId, artifactIndex: Number(index) })
                }}
              >
                {sources.map((source) => (
                  <option
                    key={`${source.job_id}:${source.artifact_index}`}
                    value={`${source.job_id}:${source.artifact_index}`}
                  >
                    {datasetById.get(source.dataset_id) ?? source.dataset_id.slice(0, 8)}
                    {' · '}{source.engine.toUpperCase()} · {source.name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Vorschaupunkte
              <select value={maxPoints} onChange={(event) => setMaxPoints(Number(event.target.value))}>
                <option value={50_000}>50.000</option>
                <option value={100_000}>100.000</option>
                <option value={200_000}>200.000</option>
                <option value={500_000}>500.000</option>
              </select>
            </label>

            {selectedSource?.download_url && (
              <a className="button" href={selectedSource.download_url} download>
                <Download size={16} /> Original herunterladen
              </a>
            )}
          </div>
        )}
      </section>

      {!sources.length ? (
        <section className="panel empty-state">
          <ScanLine size={30} />
          <h2>Noch keine Punktwolken vorhanden</h2>
          <p>ODM-LAZ oder MicMac-Punktwolken erscheinen hier nach einem abgeschlossenen Verarbeitungsauftrag.</p>
        </section>
      ) : loadingCloud ? (
        <section className="panel loading-state"><LoaderCircle className="spin" size={24} /> Punktwolke wird aufbereitet …</section>
      ) : metadata && preview ? (
        <>
          <section className="pointcloud-metric-grid">
            <article className="metric-card">
              <div><span className="metric-label">Punkte gesamt</span><strong>{formatNumber(metadata.point_count)}</strong></div>
            </article>
            <article className="metric-card">
              <div><span className="metric-label">Vorschau</span><strong>{formatNumber(preview.pointCount)}</strong></div>
            </article>
            <article className="metric-card">
              <div><span className="metric-label">Format</span><strong>{metadata.format.toUpperCase()}</strong></div>
            </article>
            <article className="metric-card">
              <div><span className="metric-label">Dateigröße</span><strong>{formatBytes(metadata.source_size_bytes)}</strong></div>
            </article>
          </section>

          <section className="panel pointcloud-panel">
            <PointCloudViewer metadata={metadata} preview={preview} />
          </section>

          <section className="panel">
            <div className="section-heading">
              <div><p className="eyebrow">Punktwolken-Metadaten</p><h3>{metadata.name}</h3></div>
              <span className={`status-chip ${metadata.has_rgb ? 'status-chip--ok' : 'status-chip--neutral'}`}>
                {metadata.has_rgb ? 'RGB vorhanden' : 'Keine RGB-Farben'}
              </span>
            </div>
            <div className="pointcloud-detail-grid">
              <div><span>Minimum XYZ</span><strong>{coordinate(metadata.bounds.min)}</strong></div>
              <div><span>Maximum XYZ</span><strong>{coordinate(metadata.bounds.max)}</strong></div>
              <div><span>Ausdehnung XYZ</span><strong>{coordinate(metadata.bounds.extent)}</strong></div>
              <div><span>Ursprung der Vorschau</span><strong>{coordinate(preview.origin)}</strong></div>
              {metadata.crs && (
                <div>
                  <span>Koordinatenreferenzsystem</span>
                  <strong>
                    {metadata.crs.epsg ? `EPSG:${metadata.crs.epsg} · ` : ''}
                    {metadata.crs.name}
                  </strong>
                </div>
              )}
              {metadata.las_version && (
                <div>
                  <span>LAS-Version / Punktformat</span>
                  <strong>
                    {metadata.las_version}
                    {metadata.point_format !== undefined ? ` / ${metadata.point_format}` : ''}
                  </strong>
                </div>
              )}
              {metadata.scales && (
                <div><span>LAS Scale XYZ</span><strong>{coordinate(metadata.scales)}</strong></div>
              )}
              {metadata.offsets && (
                <div><span>LAS Offset XYZ</span><strong>{coordinate(metadata.offsets)}</strong></div>
              )}
            </div>
            <div className="pointcloud-dimensions">
              {metadata.dimensions.map((dimension) => <span className="mono-badge" key={dimension}>{dimension}</span>)}
            </div>
          </section>
        </>
      ) : null}

      {error && (
        <div className="inline-message inline-message--error">
          <TriangleAlert size={17} /> {error}
        </div>
      )}
    </div>
  )
}
