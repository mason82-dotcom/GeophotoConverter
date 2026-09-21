import {
  Bot,
  BrainCircuit,
  CheckCircle2,
  LoaderCircle,
  RefreshCw,
  ServerOff,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { getServices } from '../api/client'
import type { ServiceState } from '../api/types'

function statusClass(service?: ServiceState) {
  if (!service) return 'status-chip--error'
  if (service.status === 'ok' || service.status === 'available') return 'status-chip--uploaded'
  if (service.status === 'unavailable') return 'status-chip--error'
  return 'status-chip--neutral'
}

export function AssistantPage() {
  const [service, setService] = useState<ServiceState>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()

  const load = useCallback(async () => {
    setLoading(true)
    setError(undefined)
    try {
      const services = await getServices()
      setService(services.open_webui)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Assistant service state could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (loading) {
    return (
      <div className="panel loading-state" role="status">
        <LoaderCircle className="spin" size={24} />
        <span>Checking AI assistant service…</span>
      </div>
    )
  }

  return (
    <div className="page-stack">
      <section className="panel assistant-hero">
        <div className="assistant-hero-icon"><BrainCircuit size={31} /></div>
        <div>
          <p className="eyebrow">Optional service</p>
          <h2>AI Assistant</h2>
          <p>
            Open WebUI is an auxiliary analysis surface. GeoPhoto Converter remains the primary operator interface for datasets,
            maps, processing and results.
          </p>
        </div>
        <button className="button" type="button" onClick={() => void load()}>
          <RefreshCw size={16} />
          Refresh status
        </button>
      </section>

      <section className="assistant-grid">
        <article className="panel assistant-status-card">
          <div className="assistant-card-heading">
            <div className="assistant-service-icon"><Bot size={23} /></div>
            <div>
              <p className="eyebrow">Open WebUI</p>
              <h3>Service status</h3>
            </div>
          </div>
          <span className={`status-chip ${statusClass(service)}`}>
            {service ? <CheckCircle2 size={13} /> : <ServerOff size={13} />}
            {service?.status ?? 'Not reported'}
          </span>
          <dl className="service-details">
            <div><dt>Docker profile</dt><dd>{service?.profile ?? '—'}</dd></div>
            <div><dt>Role</dt><dd>Optional AI assistant</dd></div>
            <div><dt>Main UI</dt><dd>No — GeoPhoto Converter remains primary</dd></div>
          </dl>
        </article>

        <article className="panel assistant-policy-card">
          <ShieldCheck size={25} />
          <div>
            <p className="eyebrow">Integration boundary</p>
            <h3>Frontend does not invent a launch URL</h3>
            <p>
              The current API reports Open WebUI service state but does not expose a browser launch URL. This page therefore
              does not hardcode a hostname, port or iframe target.
            </p>
          </div>
          <button className="button button--primary" type="button" disabled title="Backend launch URL is not part of the API contract">
            Open Assistant
          </button>
        </article>
      </section>

      {service?.note && (
        <div className="inline-message">
          <Bot size={17} />
          <span>{service.note}</span>
        </div>
      )}

      {error && (
        <div className="inline-message inline-message--error" role="alert">
          <TriangleAlert size={17} />
          <span>{error}</span>
        </div>
      )}
    </div>
  )
}
