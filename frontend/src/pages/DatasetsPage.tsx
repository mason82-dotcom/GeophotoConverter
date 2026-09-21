import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  ChevronRight,
  ImageOff,
  LoaderCircle,
  MapPinned,
  Mountain,
  RefreshCw,
  Satellite,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getDataset, listDatasets, listMapPacks } from '../api/client'
import type { Dataset, DatasetDetail, MapPack, UploadedFileRecord } from '../api/types'
import { CaptureMap } from '../components/CaptureMap'
import { FlightlineQualityStrip } from '../components/FlightlineQualityStrip'

interface DatasetsPageProps {
  mapFocused?: boolean
}

function summarizeCounts(values: Record<string, number> | undefined) {
  if (!values) return 'Not reported'
  const entries = Object.entries(values)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1])
  return entries.length ? entries.map(([name, count]) => `${name} (${count})`).join(', ') : 'Not reported'
}

function readinessLabel(dataset: DatasetDetail) {
  const readiness = dataset.qa?.readiness
  if (!readiness) return 'Not reported'
  return [
    `ODM ${readiness.odm.ready ? 'ready' : 'blocked'}`,
    `MicMac ${readiness.micmac.ready ? 'ready' : 'blocked'}`,
    `gsplat ${readiness.gsplat.ready ? 'ready' : 'blocked'}`,
  ].join(' · ')
}

function formatCoordinate(value?: number | null) {
  return typeof value === 'number' ? value.toFixed(7) : '—'
}

function MetadataInspector({ file }: { file?: UploadedFileRecord }) {
  if (!file) {
    return (
      <div className="inspector-empty">
        <ImageOff size={26} />
        <span>Select a capture point or flightline segment.</span>
      </div>
    )
  }

  const metadata = file.metadata
  const rows = [
    ['Path', file.relative_path],
    ['Capture time', metadata?.capture_time ?? '—'],
    ['Camera', [metadata?.camera?.make, metadata?.camera?.model].filter(Boolean).join(' ') || '—'],
    ['Platform', file.classification?.platform ?? '—'],
    ['Media kind', file.classification?.media_kind ?? '—'],
    ['Lens', metadata?.camera?.lens ?? '—'],
    ['Latitude', formatCoordinate(metadata?.gps?.latitude)],
    ['Longitude', formatCoordinate(metadata?.gps?.longitude)],
    ['Altitude', typeof metadata?.gps?.altitude === 'number' ? `${metadata.gps.altitude.toFixed(1)} m` : '—'],
    ['RTK flag', metadata?.dji?.rtk_flag == null ? '—' : String(metadata.dji.rtk_flag)],
    ['Gimbal pitch', typeof metadata?.dji?.gimbal_pitch === 'number' ? `${metadata.dji.gimbal_pitch.toFixed(1)}°` : '—'],
    ['Flight yaw', typeof metadata?.dji?.flight_yaw === 'number' ? `${metadata.dji.flight_yaw.toFixed(1)}°` : '—'],
  ]

  return (
    <div className="metadata-inspector">
      <div className="inspector-preview">
        <Camera size={30} strokeWidth={1.5} />
        <span>Image preview API not available</span>
      </div>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {file.scan_error && (
        <div className="inline-message inline-message--error">
          <AlertTriangle size={16} />
          <span>{file.scan_error}</span>
        </div>
      )}
    </div>
  )
}

export function DatasetsPage({ mapFocused = false }: DatasetsPageProps) {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [detail, setDetail] = useState<DatasetDetail>()
  const [selectedId, setSelectedId] = useState<string>()
  const [selectedFileId, setSelectedFileId] = useState<string>()
  const [mapPacks, setMapPacks] = useState<MapPack[]>([])
  const [mapPackId, setMapPackId] = useState<string>()
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string>()

  const loadDetail = useCallback(async (id: string) => {
    setDetailLoading(true)
    setError(undefined)
    try {
      const next = await getDataset(id)
      setDetail(next)
      setSelectedFileId((current) =>
        next.files.some((file) => file.id === current)
          ? current
          : next.files.find((file) => file.metadata?.gps?.latitude != null)?.id ?? next.files[0]?.id,
      )
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Dataset could not be loaded.')
      setDetail(undefined)
    } finally {
      setDetailLoading(false)
    }
  }, [])

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(undefined)
    try {
      const [datasetList, maps] = await Promise.all([listDatasets(), listMapPacks()])
      setDatasets(datasetList)
      setMapPacks(maps.packs)
      const preferredPack =
        maps.packs.find((pack) => pack.installed && pack.default) ??
        maps.packs.find((pack) => pack.installed)
      setMapPackId((current) => current ?? preferredPack?.id)

      const target = selectedId && datasetList.some((item) => item.id === selectedId)
        ? selectedId
        : datasetList[0]?.id
      setSelectedId(target)
      if (target) await loadDetail(target)
      else setDetail(undefined)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Datasets could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [loadDetail, selectedId])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  const selectedFile = detail?.files.find((file) => file.id === selectedFileId)
  const qa = detail?.qa
  const warnings = useMemo(
    () => qa?.warnings.reduce((sum, warning) => sum + warning.count, 0) ?? 0,
    [qa],
  )
  const failedScans = useMemo(
    () => detail?.files.filter((file) => Boolean(file.scan_error)).length ?? 0,
    [detail],
  )

  async function selectDataset(id: string) {
    setSelectedId(id)
    setSelectedFileId(undefined)
    await loadDetail(id)
  }

  if (loading) {
    return (
      <div className="panel loading-state" role="status">
        <LoaderCircle className="spin" size={24} />
        <span>Loading datasets…</span>
      </div>
    )
  }

  if (error && !datasets.length) {
    return (
      <div className="panel error-state">
        <AlertTriangle size={26} />
        <h2>Dataset API unavailable</h2>
        <p>{error}</p>
        <button className="button" type="button" onClick={() => void loadAll()}>
          <RefreshCw size={16} /> Retry
        </button>
      </div>
    )
  }

  if (!datasets.length) {
    return (
      <div className="panel empty-state">
        <p className="eyebrow">Datasets</p>
        <h2>No datasets yet</h2>
        <p>Import and scan aerial imagery before opening the QA workspace.</p>
      </div>
    )
  }

  return (
    <div className="dataset-layout">
      <aside className="dataset-browser panel" aria-label="Dataset browser">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Library</p>
            <h3>Datasets</h3>
          </div>
          <button className="mini-button" type="button" onClick={() => void loadAll()} title="Refresh datasets">
            <RefreshCw size={15} />
            <span className="visually-hidden">Refresh datasets</span>
          </button>
        </div>
        <div className="dataset-list">
          {datasets.map((dataset) => (
            <button
              key={dataset.id}
              type="button"
              className={`dataset-list-item ${dataset.id === selectedId ? 'dataset-list-item--active' : ''}`}
              onClick={() => void selectDataset(dataset.id)}
            >
              <div>
                <strong>{dataset.name}</strong>
                <span>{dataset.image_count ?? 0} images · {dataset.geotagged_percent ?? 0}% GPS</span>
              </div>
              <ChevronRight size={16} />
            </button>
          ))}
        </div>
      </aside>

      <div className="dataset-workspace">
        {detailLoading && !detail ? (
          <div className="panel loading-state"><LoaderCircle className="spin" size={22} /> Loading dataset…</div>
        ) : detail ? (
          <>
            <section className="panel dataset-header">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">{mapFocused ? 'Map workspace' : 'Dataset quality'}</p>
                  <h2>{detail.name}</h2>
                  <p>{detail.description || 'No dataset description.'}</p>
                </div>
                <span className={`status-chip ${detail.scan_status === 'completed' ? 'status-chip--uploaded' : 'status-chip--neutral'}`}>
                  {detail.scan_status}
                </span>
              </div>

              <div className="quality-grid">
                <article>
                  <ImagesIcon />
                  <span>Images</span>
                  <strong>{detail.image_count ?? detail.files.length}</strong>
                </article>
                <article>
                  <MapPinned size={18} />
                  <span>Geotagged</span>
                  <strong>{qa?.geotagged_percent ?? detail.geotagged_percent ?? 0}%</strong>
                </article>
                <article>
                  <Camera size={18} />
                  <span>Camera</span>
                  <strong>{summarizeCounts(qa?.camera_models)}</strong>
                </article>
                <article>
                  <Satellite size={18} />
                  <span>Platform</span>
                  <strong>{summarizeCounts(qa?.platforms)}</strong>
                </article>
                <article>
                  <Mountain size={18} />
                  <span>Altitude</span>
                  <strong>
                    {qa?.altitude.gps_m.min != null && qa.altitude.gps_m.max != null
                      ? `${qa.altitude.gps_m.min.toFixed(0)}–${qa.altitude.gps_m.max.toFixed(0)} m`
                      : '—'}
                  </strong>
                </article>
                <article>
                  <AlertTriangle size={18} />
                  <span>QA warnings</span>
                  <strong>{warnings}</strong>
                </article>
                <article>
                  <CheckCircle2 size={18} />
                  <span>Readiness</span>
                  <strong>{readinessLabel(detail)}</strong>
                </article>
                <article>
                  <AlertTriangle size={18} />
                  <span>Failed scans</span>
                  <strong>{failedScans}</strong>
                </article>
              </div>

              {qa && (
                <div className="qa-engine-row" aria-label="Processing readiness by engine">
                  {(['odm', 'micmac', 'gsplat'] as const).map((engine) => {
                    const state = qa.readiness[engine]
                    return (
                      <div className={`qa-engine-card ${state.ready ? 'qa-engine-card--ready' : 'qa-engine-card--blocked'}`} key={engine}>
                        <strong>{engine.toUpperCase()}</strong>
                        <span>{state.ready ? 'Ready' : state.reason ?? 'Blocked'}</span>
                        <small>{state.eligible_images} eligible RGB/WIDE images</small>
                      </div>
                    )
                  })}
                  <div className={`qa-engine-card ${qa.readiness.odm_multispectral.ready ? 'qa-engine-card--ready' : 'qa-engine-card--blocked'}`}>
                    <strong>ODM M3M</strong>
                    <span>{qa.readiness.odm_multispectral.ready ? 'Ready' : qa.readiness.odm_multispectral.reason ?? 'Blocked'}</span>
                    <small>{qa.readiness.odm_multispectral.complete_groups ?? 0} complete capture groups</small>
                  </div>
                  <div className={`qa-engine-card ${qa.readiness.thermal.ready ? 'qa-engine-card--ready' : 'qa-engine-card--blocked'}`}>
                    <strong>Thermal</strong>
                    <span>{qa.readiness.thermal.ready ? 'Ready' : qa.readiness.thermal.reason ?? 'Blocked'}</span>
                    <small>{qa.readiness.thermal.complete_groups ?? 0} complete WIDE+THERMAL groups · {qa.readiness.thermal.platform ?? 'platform unknown'}</small>
                  </div>
                  <div className="qa-engine-card">
                    <strong>Inputs</strong>
                    <span>RGB/WIDE {qa.engine_inputs.rgb_wide} · Thermal {qa.engine_inputs.thermal}</span>
                    <small>Multispectral {qa.engine_inputs.multispectral} · complete groups {qa.engine_inputs.complete_multispectral_groups} · thermal groups {qa.engine_inputs.complete_thermal_groups}</small>
                  </div>
                </div>
              )}
            </section>

            <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Flightline quality strip</p>
                  <h3>Capture sequence QA</h3>
                </div>
              </div>
              <FlightlineQualityStrip
                files={detail.files}
                selectedId={selectedFileId}
                onSelect={setSelectedFileId}
              />
            </section>

            <section className={`map-inspector-grid ${mapFocused ? 'map-inspector-grid--focused' : ''}`}>
              <div className="panel map-panel">
                <div className="map-toolbar">
                  <div>
                    <p className="eyebrow">Capture geometry</p>
                    <h3>Image positions</h3>
                  </div>
                  <label className="compact-select">
                    <span>Offline map</span>
                    <select
                      value={mapPackId ?? ''}
                      onChange={(event) => setMapPackId(event.target.value || undefined)}
                    >
                      <option value="">No basemap</option>
                      {mapPacks.map((pack) => (
                        <option key={pack.id} value={pack.id} disabled={!pack.installed}>
                          {pack.name}{pack.installed ? '' : ' · not installed'}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <CaptureMap
                  files={detail.files}
                  selectedId={selectedFileId}
                  mapPackId={mapPackId}
                  onSelect={setSelectedFileId}
                />
              </div>

              <aside className="panel inspector-panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Capture inspector</p>
                    <h3>Image & metadata</h3>
                  </div>
                </div>
                <MetadataInspector file={selectedFile} />
              </aside>
            </section>

            {error && (
              <div className="inline-message inline-message--error" role="alert">
                <AlertTriangle size={16} /> {error}
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  )
}

function ImagesIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="2" />
      <path d="m3 15 5-5 4 4 2-2 7 7" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <circle cx="16.5" cy="9.5" r="1.5" fill="currentColor" />
    </svg>
  )
}
