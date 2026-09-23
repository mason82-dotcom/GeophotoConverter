# GeoPhotoConverter V1.0.1

V1.0.1 ist ein reines Stabilitäts- und Qualitätsrelease auf Basis von V1.0.

## Schwerpunkt

Der Hauptworkflow bleibt unverändert:

```text
Import → Metadaten/QA → Karte/Vorschau → Processing → Jobmonitor → Ergebnisse
```

Es wurden keine neuen Engines oder Workflows eingeführt.

## Wichtigste Änderungen

### Stabilerer Thermal-Workflow

Ein Laufzeitfehler beim Einsammeln erzeugter Thermal-Artefakte wurde behoben. Ein Regressionstest deckt diesen Pfad jetzt ab.

Die fachliche Grenze bleibt unverändert:

- Temperaturwerte bleiben im Sensor-Pixelraum.
- Capture-GPS beschreibt den Aufnahmeort.
- Einzelne Temperaturpixel werden nicht als georeferenziert ausgegeben.
- Eine validierte WIDE↔THERMAL-Coregistrierung wird nicht behauptet.

### Reproduzierbares Frontend

Das Frontend verwendet jetzt exakt gepinnte direkte Abhängigkeiten und ein committed `package-lock.json`.

CI, Docker und lokale Installation verwenden `npm ci`.

Dadurch kann ein später veröffentlichtes npm-Paket nicht mehr ohne Repository-Änderung die Dependency-Auflösung des V1.0.1-Builds verändern.

### Deutsche V1-Oberfläche

Verbliebene englische oder gemischte Texte im Kernworkflow wurden bereinigt. Technische IDs, API-Feldnamen und Engine-Schlüssel bleiben bewusst stabil.

### Fehlerdarstellung

Worker-Exceptions werden vollständig in den technischen Job-Logs erhalten. Die UI erhält stattdessen eine stabile Benutzerfehlermeldung.

### Dokumentation

API-, Processing-, Offline-Karten- und Entwicklungsdokumentation wurden gegen den tatsächlich implementierten Code neu abgeglichen.

## Release-Gate

Vor Merge nach `main` müssen erfolgreich sein:

- Backend pytest
- Python compileall
- Frontend `npm ci`
- Typecheck
- Production Build
- Compose Validation
- Docker Build
- Core Stack Start
- Same-Origin `/api/v1/health` Smoke-Test

## Bekannte technische Nacharbeiten

Nicht release-blockierend für V1.0.1:

- externe Container-Images weiter pinnen
- FastAPI `on_event` auf Lifespan migrieren
- Sicherheitsmodell für Betrieb außerhalb vertrauenswürdiger LANs erweitern
- Worker/SQLite-Kopplung vor höherer Parallelität neu bewerten
