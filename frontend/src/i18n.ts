export function statusText(status?: string | null) {
  if (!status) return '—'
  return ({
    queued: 'Wartend',
    pending: 'Ausstehend',
    running: 'Läuft',
    uploading: 'Wird hochgeladen',
    uploaded: 'Hochgeladen',
    completed: 'Abgeschlossen',
    completed_with_errors: 'Abgeschlossen mit Fehlern',
    failed: 'Fehlgeschlagen',
    cancelled: 'Abgebrochen',
    cancel_requested: 'Abbruch angefordert',
    scanning: 'Wird gescannt',
    experimental: 'Experimentell',
    optional: 'Optional',
    unavailable: 'Nicht verfügbar',
    unknown: 'Unbekannt',
    ok: 'OK',
  } as Record<string, string>)[status] ?? status
}

export function profileText(profile?: string | null) {
  if (!profile) return '—'
  return ({ preview: 'Vorschau', standard: 'Standard', high: 'Hoch' } as Record<string, string>)[profile] ?? profile
}

export function readinessText(value?: string | boolean | null) {
  if (value == null) return 'Nicht angegeben'
  if (typeof value === 'boolean') return value ? 'Bereit' : 'Nicht bereit'
  return ({
    Ready: 'Bereit',
    'Partially ready': 'Teilweise bereit',
    'Not ready': 'Nicht bereit',
  } as Record<string, string>)[value] ?? value
}
