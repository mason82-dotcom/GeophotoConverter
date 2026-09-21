import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock3,
  Download,
  FileOutput,
  LoaderCircle,
  RefreshCw,
  ScrollText,
  Square,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { cancelJob, getJob, getJobLogs, listJobs } from '../api/client'
import type { Job, JobLogs } from '../api/types'

interface JobMonitorProps {
  focusJobId?: string
}

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

function formatElapsed(job: Job, now: number) {
  const start = Date.parse(job.created_at)
  const end = TERMINAL.has(job.status) ? Date.parse(job.updated_at) : now
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '—'
  const seconds = Math.max(0, Math.floor((end - start) / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  if (hours) return `${hours}h ${String(minutes).padStart(2, '0')}m ${String(remainder).padStart(2, '0')}s`
  return `${minutes}m ${String(remainder).padStart(2, '0')}s`
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

function statusClass(status: string) {
  if (status === 'completed') return 'status-chip--uploaded'
  if (status === 'failed') return 'status-chip--error'
  if (status === 'cancelled' || status === 'cancel_requested') return 'status-chip--cancelled'
  if (status === 'running') return 'status-chip--uploading'
  return 'status-chip--neutral'
}

export function JobMonitor({ focusJobId }: JobMonitorProps) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [selectedId, setSelectedId] = useState<string>()
  const [selectedJob, setSelectedJob] = useState<Job>()
  const [logs, setLogs] = useState<JobLogs>()
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState<string>()
  const [now, setNow] = useState(Date.now())

  const loadSelected = useCallback(async (jobId: string, quiet = false) => {
    if (!quiet) setRefreshing(true)
    try {
      const [job, logResult] = await Promise.all([
        getJob(jobId),
        getJobLogs(jobId, 250),
      ])
      setSelectedJob(job)
      setLogs(logResult)
      setJobs((current) => current.map((item) => (item.id === job.id ? job : item)))
      setError(undefined)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Job state could not be loaded.')
    } finally {
      if (!quiet) setRefreshing(false)
    }
  }, [])

  const loadJobs = useCallback(async (preferredId?: string) => {
    setLoading(true)
    try {
      const next = await listJobs()
      setJobs(next)
      const target =
        (preferredId && next.some((job) => job.id === preferredId) ? preferredId : undefined) ??
        (selectedId && next.some((job) => job.id === selectedId) ? selectedId : undefined) ??
        next[0]?.id
      setSelectedId(target)
      if (target) await loadSelected(target)
      else {
        setSelectedJob(undefined)
        setLogs(undefined)
      }
      setError(undefined)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Jobs could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [loadSelected, selectedId])

  useEffect(() => {
    void loadJobs(focusJobId)
  }, [focusJobId, loadJobs])

  useEffect(() => {
    const autoRefresh = window.localStorage.getItem('geophoto.ui.autoRefresh') !== 'false'
    if (!autoRefresh || !selectedId || !selectedJob || TERMINAL.has(selectedJob.status)) return
    const timer = window.setInterval(() => {
      void loadSelected(selectedId, true)
    }, 2500)
    return () => window.clearInterval(timer)
  }, [loadSelected, selectedId, selectedJob])

  useEffect(() => {
    if (!selectedJob || TERMINAL.has(selectedJob.status)) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [selectedJob])

  const progress = useMemo(
    () => Math.max(0, Math.min(100, Number(selectedJob?.progress ?? 0))),
    [selectedJob?.progress],
  )

  async function selectJob(id: string) {
    setSelectedId(id)
    await loadSelected(id)
  }

  async function cancel() {
    if (!selectedJob) return
    setCancelling(true)
    setError(undefined)
    try {
      const next = await cancelJob(selectedJob.id)
      setSelectedJob(next)
      setJobs((current) => current.map((job) => (job.id === next.id ? next : job)))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Cancellation failed.')
    } finally {
      setCancelling(false)
    }
  }

  return (
    <section className="panel jobs-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Job monitoring</p>
          <h2>Processing activity</h2>
          <p>Backend status, phase, progress, worker logs and generated artifacts.</p>
        </div>
        <button className="button" type="button" onClick={() => void loadJobs()} disabled={loading}>
          <RefreshCw className={refreshing ? 'spin' : ''} size={16} />
          Refresh jobs
        </button>
      </div>

      {loading && !jobs.length ? (
        <div className="compact-empty"><LoaderCircle className="spin" size={22} /> Loading jobs…</div>
      ) : !jobs.length ? (
        <div className="compact-empty"><Clock3 size={22} /> No processing jobs yet.</div>
      ) : (
        <div className="job-monitor-grid">
          <div className="job-list" role="list" aria-label="Processing jobs">
            {jobs.map((job) => (
              <button
                key={job.id}
                type="button"
                role="listitem"
                className={`job-list-item ${job.id === selectedId ? 'job-list-item--active' : ''}`}
                onClick={() => void selectJob(job.id)}
              >
                <div>
                  <strong>{job.engine.toUpperCase()} · {job.workflow ?? 'rgb'} · {job.profile}</strong>
                  <span>{job.id.slice(0, 8)} · {job.phase || job.status}</span>
                </div>
                <span className={`status-chip ${statusClass(job.status)}`}>{job.status}</span>
              </button>
            ))}
          </div>

          {selectedJob && (
            <div className="job-detail">
              <div className="job-detail-heading">
                <div>
                  <p className="eyebrow">Job {selectedJob.id.slice(0, 8)}</p>
                  <h3>{selectedJob.engine.toUpperCase()} / {selectedJob.workflow ?? 'rgb'} / {selectedJob.profile}</h3>
                </div>
                <span className={`status-chip ${statusClass(selectedJob.status)}`}>{selectedJob.status}</span>
              </div>

              <div className="job-metrics">
                <div><span>Phase</span><strong>{selectedJob.phase || '—'}</strong></div>
                <div><span>Progress</span><strong>{progress.toFixed(0)}%</strong></div>
                <div><span>Runtime</span><strong>{formatElapsed(selectedJob, now)}</strong></div>
                <div><span>Artifacts</span><strong>{selectedJob.artifacts?.length ?? 0}</strong></div>
              </div>

              <div className="job-progress-block">
                <div className="progress-track progress-track--large" role="progressbar" aria-label="Job progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
                <span>{selectedJob.message || 'Waiting for backend status…'}</span>
              </div>

              {selectedJob.status === 'failed' && (
                <div className="inline-message inline-message--error" role="alert">
                  <AlertTriangle size={17} />
                  <span>{selectedJob.message || 'Processing failed without an error message.'}</span>
                </div>
              )}

              <div className="job-actions">
                <button
                  className="button"
                  type="button"
                  disabled={TERMINAL.has(selectedJob.status) || selectedJob.status === 'cancel_requested' || cancelling}
                  onClick={() => void cancel()}
                >
                  {cancelling ? <LoaderCircle className="spin" size={16} /> : <Square size={15} />}
                  {selectedJob.status === 'cancel_requested' ? 'Cancellation requested' : 'Cancel job'}
                </button>
              </div>

              <div className="job-subgrid">
                <section className="job-subpanel">
                  <div className="job-subpanel-title">
                    <span><ScrollText size={16} /> Log tail</span>
                    <span>{logs?.available ? `${logs.lines.length} lines` : 'Not available'}</span>
                  </div>
                  <pre className="log-tail" tabIndex={0}>
                    {logs?.available && logs.lines.length
                      ? logs.lines.join('\n')
                      : 'Worker log has not been created yet.'}
                  </pre>
                </section>

                <section className="job-subpanel">
                  <div className="job-subpanel-title">
                    <span><FileOutput size={16} /> Artifacts</span>
                    <span>{selectedJob.artifacts?.length ?? 0}</span>
                  </div>
                  <div className="artifact-list">
                    {selectedJob.artifacts?.length ? (
                      selectedJob.artifacts.map((artifact, index) => (
                        <div className="artifact-row" key={`${artifact.name}-${index}`}>
                          <div>
                            <strong>{artifact.name}</strong>
                            <span>{artifact.type} · {formatBytes(artifact.size_bytes)}</span>
                          </div>
                          {artifact.download_url ? (
                            <a className="mini-button" href={artifact.download_url} download title={`Download ${artifact.name}`}>
                              <Download size={15} />
                              <span className="visually-hidden">Download {artifact.name}</span>
                            </a>
                          ) : (
                            <Ban size={15} aria-label="Download unavailable" />
                          )}
                        </div>
                      ))
                    ) : (
                      <div className="artifact-empty">
                        <FileOutput size={20} />
                        <span>No artifacts reported yet.</span>
                      </div>
                    )}
                  </div>
                </section>
              </div>
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="inline-message inline-message--error job-monitor-error" role="alert">
          <AlertTriangle size={17} />
          <span>{error}</span>
        </div>
      )}
    </section>
  )
}
