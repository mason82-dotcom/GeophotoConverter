import {
  CheckCircle2,
  Database,
  ExternalLink,
  LoaderCircle,
  PackageCheck,
  RefreshCw,
  ServerOff,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getServices, listDatasets, listJobs } from '../api/client'
import type { Dataset, Job, ServicesResponse } from '../api/types'
import { profileText, statusText } from '../i18n'

export function DroneDBPage() {
  const [services, setServices] = useState<ServicesResponse>()
  const [jobs, setJobs] = useState<Job[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [selectedJobId, setSelectedJobId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()

  const load = useCallback(async () => {
    setLoading(true)
    setError(undefined)
    try {
      const [serviceState, allJobs, datasetList] = await Promise.all([
        getServices(),
        listJobs(),
        listDatasets(),
      ])
      const completed = allJobs.filter((job) => job.status === 'completed' && (job.artifacts?.length ?? 0) > 0)
      setServices(serviceState)
      setJobs(completed)
      setDatasets(datasetList)
      setSelectedJobId((current) =>
        current && completed.some((job) => job.id === current) ? current : completed[0]?.id ?? '',
      )
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'DroneDB-Status konnte nicht geladen werden.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const selectedJob = jobs.find((job) => job.id === selectedJobId)
  const datasetName = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedJob?.dataset_id)?.name,
    [datasets, selectedJob],
  )
  const dronedb = services?.dronedb

  if (loading) {
    return <div className="panel loading-state"><LoaderCircle className="spin" size={24} /> DroneDB-Status wird geladen …</div>
  }

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Ergebnisveröffentlichung</p>
            <h2>DroneDB</h2>
            <p>Verarbeitete Datensätze und ausgewählte Ergebnisartefakte im optionalen DroneDB-Dienst veröffentlichen.</p>
          </div>
          <button className="button" type="button" onClick={() => void load()}><RefreshCw size={16} /> Aktualisieren</button>
        </div>

        <div className="service-overview-card">
          <div className={`service-large-icon ${dronedb ? '' : 'service-large-icon--offline'}`}>
            {dronedb ? <Database size={27} /> : <ServerOff size={27} />}
          </div>
          <div>
            <span className="eyebrow">Dienststatus</span>
            <strong>{dronedb ? statusText(dronedb.status) : 'Nicht verfügbar'}</strong>
            <p>{dronedb?.profile ? `Docker-Profil: ${dronedb.profile}` : 'Es wurde kein DroneDB-Dienststatus zurückgegeben.'}</p>
          </div>
          <span className={`status-chip ${dronedb ? 'status-chip--uploaded' : 'status-chip--error'}`}>
            {dronedb ? <CheckCircle2 size={13} /> : <TriangleAlert size={13} />}
            {dronedb ? 'Konfiguriert' : 'Nicht angegeben'}
          </span>
        </div>
      </section>

      <section className="panel publish-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">In DroneDB veröffentlichen</p>
            <h3>Abgeschlossenes Ergebnis auswählen</h3>
          </div>
        </div>

        <label className="field">
          <span>Abgeschlossener Verarbeitungsauftrag</span>
          <select value={selectedJobId} onChange={(event) => setSelectedJobId(event.target.value)}>
            {!jobs.length && <option value="">Keine abgeschlossenen Aufträge mit Artefakten</option>}
            {jobs.map((job) => {
              const name = datasets.find((dataset) => dataset.id === job.dataset_id)?.name ?? job.dataset_id.slice(0, 8)
              return <option key={job.id} value={job.id}>{name} · {job.engine} · {profileText(job.profile)}</option>
            })}
          </select>
        </label>

        {selectedJob && (
          <div className="publish-summary">
            <article>
              <span>Datensatz</span>
              <strong>{datasetName ?? selectedJob.dataset_id.slice(0, 8)}</strong>
            </article>
            <article>
              <span>Engine</span>
              <strong>{selectedJob.engine.toUpperCase()}</strong>
            </article>
            <article>
              <span>Profil</span>
              <strong>{profileText(selectedJob.profile)}</strong>
            </article>
            <article>
              <span>Artefakte</span>
              <strong>{selectedJob.artifacts?.length ?? 0}</strong>
            </article>
          </div>
        )}

        <div className="publish-action">
          <div>
            <PackageCheck size={20} />
            <div>
              <strong>Veröffentlichungs-Endpunkt steht noch aus</strong>
              <span>Das Frontend simuliert keine Veröffentlichung und erzeugt keine interne DroneDB-URL.</span>
            </div>
          </div>
          <button className="button button--primary" type="button" disabled title="Backend-API für die Veröffentlichung ist noch nicht verfügbar">
            <ExternalLink size={16} />
            In DroneDB veröffentlichen
          </button>
        </div>
      </section>

      {error && (
        <div className="inline-message inline-message--error" role="alert">
          <TriangleAlert size={17} /> {error}
        </div>
      )}
    </div>
  )
}
