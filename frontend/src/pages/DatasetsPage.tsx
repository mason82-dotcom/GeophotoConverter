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
import { statusText } from '../i18n'

interface DatasetsPageProps {
  mapFocused?: boolean
}

function summarizeCounts(values: Record<string, number> | undefined) {
  if (!values) return 'Nicht angegeben'
  const entries = Object.entries(values)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1])
  return entries.length ? entries.map(([name, count]) => `${name} (${count})`).join(', ') : 'Nicht angegeben'
}

function readinessLabel(dataset: DatasetDetail) {
  const readiness = dataset.qa?.readiness
  if (!readiness) return 'Nicht angegeben'
  return [
    `ODM ${readiness.odm.ready ? 'ready' : 'blocked'}`,
    `MicMac ${readiness.micmac.ready ? 'ready' : 'blocked'}`,
    `gsplat ${readiness.gsplat.ready ? 'ready' : 'blocked'}`,
  ].join(' · ')
}

function formatCoordinate(value?: number | null) {
  return typeof value === 'number' ? value.toFixed(7) : '—'
}

function PreviewImage({ file }: { file: UploadedFileRecord }) {
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setFailed(false)
  }, [file.preview_url])

  if (!file.preview_url) {
    return (
      <div className="inspector-preview inspector-preview--empty">
        <ImageOff size={26} />
        <span>Keine Bildvorschau verfügbar.</span>
      </div>
    )
  }

  if (failed) {
    return (
      <div className="inspector-preview inspector-preview--empty">
        <AlertTriangle size={24} />
        <span>Vorschau konnte nicht geladen werden.</span>
      </div>
    )
  }

  return (
    <div className="inspector-preview">
      <img
        src={file.preview_url}
        alt={`Vorschau von ${file.relative_path}`}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    </div>
  )
}

function MetadataInspector({ file }: { file?: UploadedFileRecord }) {
  if (!file) {
    return (
      <div className="inspector-empty">
        <ImageOff size={26} />
        <span>Einen Aufnahmepunkt oder ein Segment der Fluglinie auswählen.</span>
      </div>
    )
  }

  const metadata = file.metadata
  const rows = [
    ['Pfad', file.relative_path],
    ['Aufnahmezeit', metadata?.capture_time ?? '—'],
    ['Kamera', [metadata?.camera?.make, metadata?.camera?.model].filter(Boolean).join(' ') || '—'],
    ['Plattform', file.classification?.platform ?? '—'],
    ['Medientyp', file.classification?.media_kind ?? '—'],
    ['Objektiv', metadata?.camera?.lens ?? '—'],
    ['Breitengrad', formatCoordinate(metadata?.gps?.latitude)],
    ['Längengrad', formatCoordinate(metadata?.gps?.longitude)],
    ['Höhe', typeof metadata?.gps?.altitude === 'number' ? `${metadata.gps.altitude.toFixed(1)} m` : '—'],
    ['RTK-Status', metadata?.dji?.rtk_flag == null ? '—' : String(metadata.dji.rtk_flag)],
    ['Gimbal-Neigung', typeof metadata?.dji?.gimbal_pitch === 'number' ? `${metadata.dji.gimbal_pitch.toFixed(1)}°` : '—'],
    ['Flug-Gierwinkel', typeof metadata?.dji?.flight_yaw === 'number' ? `${metadata.dji.flight_yaw.toFixed(1)}°` : '—'],
  ]

  return (
    <div className="metadata-inspector">
      <PreviewImage file={file} />
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
      setError(requestError instanceof Error ? requestError.message : 'Datensatz konnte nicht geladen werden.')
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
      setError(requestError instanceof Error ? requestError.message : 'Datensätze konnten nicht geladen werden.')
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
        <span>Datensätze werden geladen …</span>
      </div>
    )
  }

  if (error && !datasets.length) {
    return (
      <div className="panel error-state">
        <AlertTriangle size={26} />
        <h2>Datensatz-API nicht verfügbar</h2>
        <p>{error}</p>
        <button className="button" type="button" onClick={() => void loadAll()}>
          <RefreshCw size={16} /> Erneut versuchen
        </button>
      </div>
    )
  }

  if (!datasets.length) {
    return (
      <div className="panel empty-state">
        <p className="eyebrow">Datensätze</p>
        <h2>Noch keine Datensätze</h2>
        <p>Vor der Qualitätssicherung zuerst Luftbilddaten importieren und scannen.</p>
      </div>
    )
  }

  return (
    <div className="dataset-layout">
      <aside className="dataset-browser panel" aria-label="Datensatzliste">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Bibliothek</p>
            <h3>Datensätze</h3>
          </div>
          <button className="mini-button" type="button" onClick={() => void loadAll()} title="Datensätze aktualisieren">
            <RefreshCw size={15} />
            <span className="visually-hidden">Datensätze aktualisieren</span>
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
                <span>{dataset.image_count ?? 0} Bilder · {dataset.geotagged_percent ?? 0}% GPS</span>
              </div>
              <ChevronRight size={16} />
            </button>
          ))}
        </div>
      </aside>

      <div className="dataset-workspace">
        {detailLoading && !detail ? (
          <div className="panel loading-state"><LoaderCircle className="spin" size={22} /> Datensatz wird geladen …</div>
        ) : detail ? (
          <>
            <section className="panel dataset-header">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">{mapFocused ? 'Karten-Arbeitsbereich' : 'Datensatzqualität'}</p>
                  <h2>{detail.name}</h2>
                  <p>{detail.description || 'Keine Datensatzbeschreibung.'}</p>
                </div>
                <span className={`status-chip ${detail.scan_status === 'completed' ? 'status-chip--uploaded' : 'status-chip--neutral'}`}>
                  {statusText(detail.scan_status)}
                </span>
              </div>

              <div className="quality-grid">
                <article>
                  <ImagesIcon />
                  <span>Bilder</span>
                  <strong>{detail.image_count ?? detail.files.length}</strong>
                </article>
                <article>
                  <MapPinned size={18} />
                  <span>Georeferenziert</span>
                  <strong>{qa?.geotagged_percent ?? detail.geotagged_percent ?? 0}%</strong>
                </article>
                <article>
                  <Camera size={18} />
                  <span>Kamera</span>
                  <strong>{summarizeCounts(qa?.camera_models)}</strong>
                </article>
                <article>
                  <Satellite size={18} />
                  <span>Plattform</span>
                  <strong>{summarizeCounts(qa?.platforms)}</strong>
                </article>
                <article>
                  <Mountain size={18} />
                  <span>Höhenbereich</span>
                  <strong>
                    {qa?.altitude.gps_m.min != null && qa.altitude.gps_m.max != null
                      ? `${qa.altitude.gps_m.min.toFixed(0)}–${qa.altitude.gps_m.max.toFixed(0)} m`
                      : '—'}
                  </strong>
                </article>
                <article>
                  <AlertTriangle size={18} />
                  <span>QA-Warnungen</span>
                  <strong>{warnings}</strong>
                </article>
                <article>
                  <CheckCircle2 size={18} />
                  <span>Bereitschaft</span>
                  <strong>{readinessLabel(detail)}</strong>
                </article>
                <article>
                  <AlertTriangle size={18} />
                  <span>Fehlerhafte Scans</span>
                  <strong>{failedScans}</strong>
                </article>
              </div>

              {qa && (
                <div className="qa-engine-row" aria-label="Verarbeitungsbereitschaft nach Engine">
                  {(['odm', 'micmac', 'gsplat'] as const).map((engine) => {
                    const state = qa.readiness[engine]
                    return (
                      <div className={`qa-engine-card ${state.ready ? 'qa-engine-card--ready' : 'qa-engine-card--blocked'}`} key={engine}>
                        <strong>{engine.toUpperCase()}</strong>
                        <span>{state.ready ? 'Bereit' : state.reason ?? 'Blockiert'}</span>
                        <small>{state.eligible_images} geeignete RGB/WIDE-Bilder</small>
                      </div>
                    )
                  })}
                  <div className={`qa-engine-card ${qa.readiness.odm_multispectral.ready ? 'qa-engine-card--ready' : 'qa-engine-card--blocked'}`}>
                    <strong>ODM M3M</strong>
                    <span>{qa.readiness.odm_multispectral.ready ? 'Bereit' : qa.readiness.odm_multispectral.reason ?? 'Blockiert'}</span>
                    <small>{qa.readiness.odm_multispectral.complete_groups ?? 0} vollständige Aufnahmegruppen</small>
                  </div>
                  <div className={`qa-engine-card ${qa.readiness.thermal.ready ? 'qa-engine-card--ready' : 'qa-engine-card--blocked'}`}>
                    <strong>Thermal</strong>
                    <span>{qa.readiness.thermal.ready ? 'Bereit' : qa.readiness.thermal.reason ?? 'Blockiert'}</span>
                    <small>{qa.readiness.thermal.complete_groups ?? 0} vollständige WIDE+THERMAL-Gruppen · {qa.readiness.thermal.platform ?? 'Plattform unbekannt'}</small>
                  </div>
                  <div className="qa-engine-card">
                    <strong>Eingaben</strong>
                    <span>RGB/WIDE {qa.engine_inputs.rgb_wide} · Thermal {qa.engine_inputs.thermal}</span>
                    <small>Multispectral {qa.engine_inputs.multispectral} · complete groups {qa.engine_inputs.complete_multispectral_groups} · thermal groups {qa.engine_inputs.complete_thermal_groups}</small>
                  </div>
                </div>
              )}
            </section>

            <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Qualitätsstreifen der Fluglinie</p>
                  <h3>Qualität der Aufnahmesequenz</h3>
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
                    <p className="eyebrow">Aufnahmegeometrie</p>
                    <h3>Bildpositionen</h3>
                  </div>
                  <label className="compact-select">
                    <span>Offline-Karte</span>
                    <select
                      value={mapPackId ?? ''}
                      onChange={(event) => setMapPackId(event.target.value || undefined)}
                    >
                      <option value="">Keine Basiskarte</option>
                      {mapPacks.map((pack) => (
                        <option key={pack.id} value={pack.id} disabled={!pack.installed}>
                          {pack.name}{pack.installed ? '' : ' · nicht installiert'}
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
                    <p className="eyebrow">Aufnahme-Inspektor</p>
                    <h3>Bild & Metadaten</h3>
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
