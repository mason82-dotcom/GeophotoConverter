import {
  CheckCircle2,
  Database,
  Gauge,
  HardDrive,
  LoaderCircle,
  MapPinned,
  RefreshCw,
  Server,
  Settings2,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getHealth, getServices, listMapPacks, type HealthResponse } from '../api/client'
import type { MapCatalog, ServicesResponse } from '../api/types'

type Density = 'comfortable' | 'compact'

function readDensity(): Density {
  const value = window.localStorage.getItem('geophoto.ui.density')
  return value === 'compact' ? 'compact' : 'comfortable'
}

function readAutoRefresh() {
  return window.localStorage.getItem('geophoto.ui.autoRefresh') !== 'false'
}

function formatBytes(bytes?: number | null) {
  if (!bytes) return 'Not installed'
  const gib = bytes / 1024 / 1024 / 1024
  if (gib >= 1) return `${gib.toFixed(2)} GiB`
  return `${(bytes / 1024 / 1024).toFixed(0)} MiB`
}

export function SettingsPage() {
  const [health, setHealth] = useState<HealthResponse>()
  const [services, setServices] = useState<ServicesResponse>()
  const [maps, setMaps] = useState<MapCatalog>()
  const [density, setDensity] = useState<Density>(readDensity)
  const [autoRefresh, setAutoRefresh] = useState(readAutoRefresh)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()

  const load = useCallback(async () => {
    setLoading(true)
    setError(undefined)
    try {
      const [healthState, serviceState, mapState] = await Promise.all([
        getHealth(),
        getServices(),
        listMapPacks(),
      ])
      setHealth(healthState)
      setServices(serviceState)
      setMaps(mapState)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Settings state could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    window.localStorage.setItem('geophoto.ui.density', density)
    document.documentElement.dataset.density = density
  }, [density])

  useEffect(() => {
    window.localStorage.setItem('geophoto.ui.autoRefresh', String(autoRefresh))
  }, [autoRefresh])

  const serviceEntries = useMemo(() => Object.entries(services ?? {}), [services])
  const installedMaps = maps?.packs.filter((pack) => pack.installed) ?? []

  if (loading) {
    return (
      <div className="panel loading-state" role="status">
        <LoaderCircle className="spin" size={24} />
        <span>Loading workstation settings…</span>
      </div>
    )
  }

  return (
    <div className="settings-layout">
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">System</p>
            <h2>Runtime status</h2>
            <p>Read-only status from the relative GeoPhoto API.</p>
          </div>
          <button className="button" type="button" onClick={() => void load()}>
            <RefreshCw size={16} />
            Refresh
          </button>
        </div>

        <div className="settings-status-grid">
          <article>
            <Server size={19} />
            <span>API</span>
            <strong>{health?.status ?? 'Unknown'}</strong>
          </article>
          <article>
            <Database size={19} />
            <span>Redis</span>
            <strong>{health?.redis ?? 'Unknown'}</strong>
          </article>
          <article>
            <Gauge size={19} />
            <span>API version</span>
            <strong>{health?.version ?? '—'}</strong>
          </article>
          <article>
            <MapPinned size={19} />
            <span>Offline maps</span>
            <strong>{installedMaps.length}/{maps?.packs.length ?? 0}</strong>
          </article>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Frontend preferences</p>
            <h3>Operator interface</h3>
          </div>
        </div>

        <div className="settings-form">
          <fieldset>
            <legend>Interface density</legend>
            <label className="radio-setting">
              <input
                type="radio"
                name="density"
                value="comfortable"
                checked={density === 'comfortable'}
                onChange={() => setDensity('comfortable')}
              />
              <span><strong>Comfortable</strong><small>Standard spacing and touch targets.</small></span>
            </label>
            <label className="radio-setting">
              <input
                type="radio"
                name="density"
                value="compact"
                checked={density === 'compact'}
                onChange={() => setDensity('compact')}
              />
              <span><strong>Compact</strong><small>Higher information density for desktop workstations.</small></span>
            </label>
          </fieldset>

          <label className="toggle-setting">
            <span>
              <strong>Automatic job refresh preference</strong>
              <small>Stored locally for frontend polling behavior. No backend setting is changed.</small>
            </span>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(event) => setAutoRefresh(event.target.checked)}
            />
          </label>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Connected services</p>
            <h3>Backend capabilities</h3>
          </div>
        </div>
        <div className="service-table" role="list">
          {serviceEntries.map(([name, state]) => (
            <div className="service-row" role="listitem" key={name}>
              <div className="service-row-icon">
                {name === 'dronedb' ? <HardDrive size={17} /> : <Settings2 size={17} />}
              </div>
              <div>
                <strong>{name.replaceAll('_', ' ')}</strong>
                <span>{state.note ?? state.profile ?? 'Backend service'}</span>
              </div>
              <span className={`status-chip ${state.status === 'unavailable' ? 'status-chip--error' : 'status-chip--neutral'}`}>
                {state.status}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Offline basemaps</p>
            <h3>Regional map packs</h3>
          </div>
        </div>
        <div className="map-pack-list">
          {maps?.packs.map((pack) => (
            <article key={pack.id}>
              <div>
                <strong>{pack.name}</strong>
                <span>{pack.id} · {formatBytes(pack.size_bytes)}</span>
              </div>
              <span className={`status-chip ${pack.installed ? 'status-chip--uploaded' : 'status-chip--neutral'}`}>
                {pack.installed && <CheckCircle2 size={13} />}
                {pack.installed ? 'Installed' : 'Not installed'}
              </span>
            </article>
          ))}
        </div>
        {maps?.attribution && <p className="settings-attribution">{maps.attribution}</p>}
      </section>

      {error && (
        <div className="inline-message inline-message--error" role="alert">
          <TriangleAlert size={17} />
          <span>{error}</span>
        </div>
      )}
    </div>
  )
}
