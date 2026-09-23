# GeoPhotoConverter API-Vertrag v1.0

Basis-URL: `/api/v1`

Das Browser-Frontend verwendet ausschließlich relative `/api/v1`-Aufrufe. Im Produktionsbetrieb stellt nginx denselben Origin bereit; im Entwicklungsbetrieb übernimmt der Vite-Proxy die Weiterleitung.

## Systemstatus

### GET /health

Liefert den Dienststatus:

```json
{
  "status": "ok",
  "redis": "ok",
  "version": "1.0.0"
}
```

`redis` kann `unavailable` sein, wenn die Warteschlange nicht erreichbar ist.

## Verarbeitungskatalog

### GET /processing/profiles

Liefert den vom Backend definierten Verarbeitungskatalog. Das Frontend verwendet diesen Katalog für Engines, Workflows, Profile, Ausgaben und typisierte Job-Optionen.

Globale Profile:

- `preview`
- `standard`
- `high`

Automatisierte Engines/Workflows:

- `odm/rgb`
- `odm/multispectral`
- `micmac/rgb`
- `gsplat/rgb`
- `thermal/thermal`

`telesculptor` wird als experimentelle, nicht automatisierte Vergleichs-Engine gemeldet.

Der Thermal-Katalog kennzeichnet zusätzlich unter anderem:

- `requires_dji_tsdk=true`
- Plattformen `M3T` und `M4T`
- `temperature_space="sensor_pixel"`
- `wide_thermal_coregistered=false`
- `georeferenced_temperature_raster=false`

Diese Felder sind fachliche Grenzen und dürfen vom Frontend nicht in eine behauptete WIDE↔THERMAL-Koregistrierung oder ein georeferenziertes Temperatur-Orthomosaik umgedeutet werden.

## Datensätze

### GET /datasets

Listet importierte Datensätze auf.

### POST /datasets

Erstellt einen Datensatz.

Body:

```json
{
  "name": "Befliegung 2026-09-21",
  "description": "optional"
}
```

### GET /datasets/{dataset_id}

Liefert Datensatzdetails, Dateien, Georeferenzierungsabdeckung und das vollständige `qa`-Objekt. Jede Datei enthält nach dem Scan die gespeicherten Metadaten, ihre Klassifikation und eine relative `preview_url`.

### POST /datasets/{dataset_id}/files

Multipart-Upload. Feldname: `files`.

Optionales Formularfeld: `relative_paths` als JSON-Array zur Beibehaltung der vom Browser gelieferten Ordnerpfade.

Uploads werden in eine temporäre Datei gestreamt und erst nach erfolgreicher Validierung atomar an die Zielposition verschoben. Das Backend:

- akzeptiert nur konfigurierte Bildendungen,
- berechnet SHA-256,
- lehnt doppelte Inhalte innerhalb desselben Datensatzes ab,
- erzwingt Größenlimits pro Datei und Datensatz,
- schützt den Datensatzpfad gegen Traversal.

Antwort:

```json
{
  "accepted": [],
  "rejected": []
}
```

### POST /datasets/{dataset_id}/scan

Analysiert hochgeladene Bilddaten mit ExifTool und speichert EXIF-/XMP-/GPS-/DJI-Metadaten.

Antwortfelder:

- `dataset`
- `scanned`
- `failed`

### GET /datasets/{dataset_id}/qa

Liefert die Datensatz-QA einschließlich Georeferenzierungsabdeckung, Plattform-/Medienklassifikation, Kameramodellen, Höhenbereichen, Aufnahmezeitraum, Warnungen und Bereitschaft je Verarbeitungsweg.

Relevante Readiness-Schlüssel:

- `odm`
- `odm_multispectral`
- `micmac`
- `gsplat`
- `thermal`

### GET /datasets/{dataset_id}/geojson

Liefert georeferenzierte Bildpositionen als GeoJSON-`FeatureCollection` für MapLibre.

### GET /datasets/{dataset_id}/files/{file_id}/preview?size=1024

Liefert eine gecachte **WebP**-Vorschau mit angewendeter EXIF-Ausrichtung.

- Standardgröße: `1024`
- zulässige maximale Kantenlänge: `128` bis `2048` px
- MIME-Type: `image/webp`
- Cache-Key: Datei-SHA-256 beziehungsweise Datei-ID plus angeforderter Größe
- `Cache-Control: private, max-age=86400, immutable`
- ETag basiert auf Cache-Key und Größe
- DNG wird für die Vorschau über LibRaw/`dcraw_emu` dekodiert

Nicht dekodierbare Bildformate liefern HTTP 415; andere Fehler bei der Vorschauerzeugung HTTP 422. Dateisystempfade werden nicht offengelegt.

## Aufträge

### GET /jobs

Listet Verarbeitungsaufträge auf.

### POST /jobs

Erstellt einen Verarbeitungsauftrag.

Allgemeines Schema:

```json
{
  "dataset_id": "...",
  "engine": "odm",
  "profile": "standard",
  "workflow": "rgb",
  "options": {}
}
```

Defaults:

- `profile="standard"`
- `workflow="rgb"`
- `options={}`

Erlaubte Engines:

- `odm`
- `micmac`
- `gsplat`
- `thermal`
- `telesculptor`

`telesculptor` ist zwar Teil des Katalogs, wird beim automatisierten Job-Erstellen mit HTTP 409 abgelehnt.

Erlaubte Profile:

- `preview`
- `standard`
- `high`

Erlaubte Workflows:

- `rgb`
- `multispectral`
- `thermal`

Workflow-Bindungen:

- `multispectral` ist derzeit nur mit `odm` erlaubt.
- `thermal` ist nur mit der Engine `thermal` erlaubt.
- Die Engine `thermal` erfordert `workflow="thermal"`.

Vor dem Enqueue prüft das Backend die Dataset-Readiness. Nicht geeignete Datensätze liefern HTTP 409 mit strukturierten Detailfeldern wie `message`, `engine`, `workflow`, `eligible_images` und `engine_inputs`.

### Thermal-Job-Optionen

Nur `thermal/thermal` akzeptiert derzeit Job-Optionen:

| Feld | Typ | Regel / Default |
| --- | --- | --- |
| `emissivity` | number | optional, > 0 und ≤ 1 |
| `distance_m` | number | optional, > 0 |
| `humidity_pct` | number | optional, 0 bis 100 |
| `reflection_c` | number | optional |
| `ambient_temp_c` | number | optional |
| `hotspot_delta_c` | number | > 0, Default 10.0 |
| `hotspot_min_pixels` | integer | ≥ 1, Default 4 |

Unbekannte Thermal-Optionen werden abgelehnt. Für alle anderen Engine-/Workflow-Kombinationen muss `options` leer bleiben.

### GET /jobs/{job_id}

Liefert Status, Fortschritt, Phase, Nachricht, Workflow/Optionen, Publikationsstatus und eine Artefakt-Zusammenfassung. Jedes Artefakt erhält eine relative `download_url`.

### GET /jobs/{job_id}/logs?tail=200

Liefert die letzten Worker-Protokollzeilen.

- Default: 200
- Bereich: 1 bis 5000
- solange kein Protokoll existiert: `available=false`

### GET /jobs/{job_id}/artifacts/{artifact_index}

Überträgt ein Auftragsartefakt. Clients sollen die vom Auftrag gelieferte `download_url` verwenden und keine Dateipfade selbst zusammensetzen.

### POST /jobs/{job_id}/cancel

Fordert den Abbruch eines Auftrags an. Bereits abgeschlossene, fehlgeschlagene oder abgebrochene Aufträge werden unverändert zurückgegeben.

### POST /jobs/{job_id}/publish/dronedb

Veröffentlicht die Artefakte eines **abgeschlossenen** Auftrags beim optionalen DroneDB-Dienst.

Optionaler Body:

```json
{
  "name": "Anzeigename"
}
```

Die Publikation erzeugt zusätzlich ein `geophoto-job.json`-Manifest und fordert anschließend den DroneDB-Build an. Nicht abgeschlossene Aufträge oder Aufträge ohne publizierbare Artefakte werden mit HTTP 409 abgelehnt.

## Dienste

### GET /services

Liefert Laufzeitstatus für:

- Redis
- ODM
- MicMac
- gsplat
- Thermal
- TeleSculptor
- DroneDB
- Open WebUI

Die vier automatisierten Worker melden unter anderem `status`, `queue_depth` und ihr Compose-`profile`. gsplat kennzeichnet `gpu=true`.

Thermal meldet zusätzlich:

- `requires_dji_tsdk=true`
- `platforms=["M3T","M4T"]`
- `wide_thermal_coregistered=false`
- `georeferenced_temperature_raster=false`

TeleSculptor meldet `status="experimental"`.

DroneDB und Open WebUI werden aktiv über ihre internen HTTP-Endpunkte geprüft. Ihre Zustände enthalten je nach Erreichbarkeit unter anderem `status`, `reachable`, `health_status_code`, `public_port` und `launch_url`.

## Frontend-Vertrag

Das Frontend enthält keine eigene Verarbeitungslogik. Es:

- verwendet relative `/api/v1`-Aufrufe,
- liest Engine-/Workflow-Fähigkeiten aus `/processing/profiles`,
- liest Dienstzustände aus `/services`,
- erstellt Backend-Aufträge,
- zeigt den vom Backend gelieferten Zustand und Artefakte an.

Erforderliche UI-Zustände umfassen Laden, Leerzustand, Fehler, Uploadfortschritt, Verarbeitung, Abschluss und Abbruch.

## Offline-Karten

### GET /maps

Listet konfigurierte regionale Offline-Kartenpakete auf und meldet, ob die jeweilige MBTiles-Datei installiert ist.

### GET /maps/{region_id}/tilejson.json

Liefert MapLibre-kompatibles TileJSON für ein installiertes regionales Kartenpaket.

### GET /maps/{region_id}/tiles/{z}/{x}/{y}.pbf

Liefert eine Offline-Shortbread-Vektorkachel aus der lokalen MBTiles-Datenbank.

Initial konfigurierte Regionen:

- `baden-wuerttemberg` (Standard)
- `bayern`
- `hessen`
- `rheinland-pfalz`
- `saarland`

Die Kartenanzeige im Frontend muss die OpenStreetMap-Attribution sichtbar lassen.
