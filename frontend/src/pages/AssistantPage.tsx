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
import { statusText } from '../i18n'

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
      setError(requestError instanceof Error ? requestError.message : 'Assistenten-Status konnte nicht geladen werden.')
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
        <span>KI-Assistenten-Dienst wird geprüft …</span>
      </div>
    )
  }

  return (
    <div className="page-stack">
      <section className="panel assistant-hero">
        <div className="assistant-hero-icon"><BrainCircuit size={31} /></div>
        <div>
          <p className="eyebrow">Optionaler Dienst</p>
          <h2>KI-Assistent</h2>
          <p>
            Open WebUI ist eine ergänzende Analyseoberfläche. GeoPhoto Converter bleibt die primäre Bedienoberfläche für Datensätze, Karten, Verarbeitung und Ergebnisse.
          </p>
        </div>
        <button className="button" type="button" onClick={() => void load()}>
          <RefreshCw size={16} />
          Status aktualisieren
        </button>
      </section>

      <section className="assistant-grid">
        <article className="panel assistant-status-card">
          <div className="assistant-card-heading">
            <div className="assistant-service-icon"><Bot size={23} /></div>
            <div>
              <p className="eyebrow">Open WebUI</p>
              <h3>Dienststatus</h3>
            </div>
          </div>
          <span className={`status-chip ${statusClass(service)}`}>
            {service ? <CheckCircle2 size={13} /> : <ServerOff size={13} />}
            {service ? statusText(service.status) : 'Nicht angegeben'}
          </span>
          <dl className="service-details">
            <div><dt>Docker-Profil</dt><dd>{service?.profile ?? '—'}</dd></div>
            <div><dt>Rolle</dt><dd>Optionaler KI-Assistent</dd></div>
            <div><dt>Hauptoberfläche</dt><dd>Nein — GeoPhoto Converter bleibt primär</dd></div>
          </dl>
        </article>

        <article className="panel assistant-policy-card">
          <ShieldCheck size={25} />
          <div>
            <p className="eyebrow">Integrationsgrenze</p>
            <h3>Frontend erfindet keine Start-URL</h3>
            <p>
              Die aktuelle API meldet den Open-WebUI-Dienststatus, stellt aber keine Browser-Start-URL bereit. Daher werden weder Hostname noch Port oder iframe-Ziel fest codiert.
            </p>
          </div>
          <button className="button button--primary" type="button" disabled title="Für V1.0 bewusst deaktiviert">
            Assistent öffnen
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
