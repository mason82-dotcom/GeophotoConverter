import { AlertTriangle, MapPinOff } from 'lucide-react'
import type { UploadedFileRecord } from '../api/types'

interface FlightlineQualityStripProps {
  files: UploadedFileRecord[]
  selectedId?: string
  onSelect: (fileId: string) => void
}

function quality(file: UploadedFileRecord) {
  if (file.scan_error) return 'error'
  const gps = file.metadata?.gps
  if (gps?.latitude == null || gps?.longitude == null) return 'warning'
  return 'ok'
}

export function FlightlineQualityStrip({
  files,
  selectedId,
  onSelect,
}: FlightlineQualityStripProps) {
  if (!files.length) {
    return <div className="flightline-empty">Keine Bilddaten für die Fluglinien-Qualitätssicherung verfügbar.</div>
  }

  return (
    <div className="flightline-wrap">
      <div className="flightline-legend" aria-hidden="true">
        <span><i className="flight-dot flight-dot--ok" /> GPS vorhanden</span>
        <span><i className="flight-dot flight-dot--warning" /> GPS fehlt</span>
        <span><i className="flight-dot flight-dot--error" /> Metadatenfehler</span>
      </div>
      <div className="flightline-strip" role="list" aria-label="Bildqualitätssequenz der Fluglinie">
        {files.map((file, index) => {
          const state = quality(file)
          return (
            <button
              key={file.id}
              type="button"
              role="listitem"
              className={`flight-segment flight-segment--${state} ${selectedId === file.id ? 'flight-segment--selected' : ''}`}
              onClick={() => onSelect(file.id)}
              aria-label={`Bild ${index + 1}: ${file.relative_path}; ${state === 'ok' ? 'GPS vorhanden' : state === 'warning' ? 'GPS fehlt' : 'Metadatenfehler'}`}
              title={file.relative_path}
            >
              <span>{String(index + 1).padStart(3, '0')}</span>
              {state === 'warning' && <MapPinOff size={12} aria-hidden="true" />}
              {state === 'error' && <AlertTriangle size={12} aria-hidden="true" />}
            </button>
          )
        })}
      </div>
    </div>
  )
}
