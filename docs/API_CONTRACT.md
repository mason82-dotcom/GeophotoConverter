# GeoPhotoConverter API-Vertrag v1.0.1

Basis-URL: `/api/v1`

Der Browser verwendet ausschließlich relative API-URLs. Interne Docker-Hostnamen werden nicht im Frontend fest codiert.

## System und Fähigkeiten

### GET /health

Liefert API-, Redis- und Versionsstatus.

Beispiel:

```json
{
  "status": "ok",
  "redis": "ok",
  "version": "1.0.1"
}
```

### GET /processing/profiles

Autoritative Quelle für Verarbeitungs-Engines, Workflows, Profile, Eingabeanforderungen, optionale Parameter und erwartete Artefakttypen.

Das Frontend darf Engine-Fähigkeiten nicht unabhängig davon hart codieren.

Aktuell modelliert:

- ODM
  - `mapping`
  - `multispectral`
- MicMac
  - `mapping`
- gsplat
  - `reconstruction`
- Thermal
  - `thermal`
- TeleSculptor
  - experimentell/manuell, nicht automatisiert

Profile: `preview`, `standard`, `high`.

### GET /services

Liefert Laufzeitstatus der Queue, Worker und optionalen Dienste.

Worker-Felder können unter anderem enthalten:

- `status`
- `queue_depth`
- `profile`
- `gpu`
- `requires_dji_tsdk`
- `platforms`

Für Thermal gelten zusätzlich:

- `wide_thermal_coregistered = false`
- `georeferenced_temperature_raster = false`

DroneDB und Open WebUI enthalten zusätzlich:

- `status`: `online`, `reachable`, `degraded` oder `offline`
- `reachable`
- `health_status_code`
- `public_port`
- `launch_url`

DroneDB meldet außerdem den Publish-Endpunkt. Open WebUI ist nur ein optionaler Assistent und nicht die primäre GeoPhotoConverter-Oberfläche.

## Datensätze

### GET /datasets

Listet Datensätze mit Bildanzahl und Georeferenzierungsabdeckung.

### POST /datasets

Erstellt einen Datensatz.

```json
{
  "name": "Befliegung 2026-09-21",
  "description": "optional"
}
```

### GET /datasets/{dataset_id}

Liefert Datensatzdetails einschließlich:

- Dateien
- extrahierte Metadaten
- Medien-/Plattformklassifikation
- `preview_url` pro Datei
- Georeferenzierungsabdeckung
- vollständiges `qa`-Objekt mit Engine-Readiness

### POST /datasets/{dataset_id}/files

Multipart-Upload. Feldname: `files`.

Optionales Formularfeld: `relative_paths` als JSON-Array für vom Browser gelieferte Ordnerpfade.

Eigenschaften:

- unterstützte Endungen werden serverseitig validiert
- Pfad-Traversal wird verhindert
- Upload wird gestreamt
- temporäre Datei wird erst nach Validierung atomar verschoben
- SHA-256 wird berechnet
- doppelte Dateiinhalte im selben Datensatz werden abgelehnt
- konfigurierbares Datei- und Datensatz-Größenlimit

### POST /datasets/{dataset_id}/scan

Extrahiert EXIF-/XMP-/DJI-Metadaten über ExifTool und aktualisiert den Scanstatus.

### GET /datasets/{dataset_id}/qa

Liefert unter anderem:

- Bildanzahl
- Anzahl/Anteil georeferenzierter Bilder
- Plattformen und Kameramodelle
- Medienarten
- Höhenbereiche
- Aufnahmezeitraum
- Warnungen
- Engine-Eingabezahlen
- Readiness für ODM, MicMac, gsplat, Thermal und ODM-Multispektral
- zusätzliches `mapping`-Objekt mit `ready|warning|blocked`, Mapping-GPS-Abdeckung, RTK-Metadaten- und RTK-Fix-Anzahl sowie DJI-Lage-Metadatenabdeckung

### GET /datasets/{dataset_id}/geojson

Liefert georeferenzierte Aufnahmezentren als GeoJSON-`FeatureCollection`.

Die Punkte repräsentieren Bild-Capture-Positionen. Bei Thermal sind sie keine Georeferenzierung einzelner Temperaturpixel.

### GET /datasets/{dataset_id}/files/{file_id}/preview?size=1024

Liefert eine gecachte WebP-Vorschau.

- `size`: längste Kante, 128–2048 px
- Standard: 1024 px
- EXIF-Ausrichtung wird angewendet
- DNG wird für die Vorschau über LibRaw dekodiert
- Ausgabe: `image/webp`
- Cache-Key basiert auf SHA-256 bzw. Datei-ID
- Response enthält `Cache-Control` und `ETag`

Clients sollen die vom Datensatz gelieferte `preview_url` verwenden.

## Aufträge

### GET /jobs

Listet Verarbeitungsaufträge.

### POST /jobs

Erstellt einen Auftrag.

Allgemeines Beispiel:

```json
{
  "dataset_id": "...",
  "engine": "odm",
  "profile": "standard",
  "workflow": "mapping",
  "options": {}
}
```

Automatisierte Engines:

- `odm`
- `micmac`
- `gsplat`
- `thermal`

`telesculptor` ist im Katalog sichtbar, aber nicht über die automatisierte Queue startbar.

Workflows:

- `mapping` — ODM/MicMac
- `reconstruction` — gsplat
- `multispectral` — nur ODM
- `thermal` — nur Thermal-Engine
- `rgb` — Legacy-Eingabe; wird engine-spezifisch auf `mapping` oder `reconstruction` normalisiert

Ältere Clients, die `workflow` weglassen, bleiben kompatibel: Der historische Default `rgb` wird erst nach Auswahl der Engine kanonisiert.

Das Backend validiert vor dem Enqueue die jeweilige Datensatz-Readiness.

### ODM Multispektral

Beispiel:

```json
{
  "dataset_id": "...",
  "engine": "odm",
  "profile": "standard",
  "workflow": "multispectral",
  "options": {}
}
```

Erfordert mindestens zwei vollständige M3M-Aufnahmegruppen mit:

- RGB
- Green
- Red
- Red Edge
- NIR

### Thermal

Beispiel:

```json
{
  "dataset_id": "...",
  "engine": "thermal",
  "profile": "standard",
  "workflow": "thermal",
  "options": {
    "emissivity": 0.95,
    "distance_m": 30,
    "humidity_pct": 50,
    "hotspot_delta_c": 10,
    "hotspot_min_pixels": 4
  }
}
```

Optionale Thermal-Parameter:

- `emissivity`: > 0 bis 1
- `distance_m`: > 0
- `humidity_pct`: 0 bis 100
- `reflection_c`
- `ambient_temp_c`
- `hotspot_delta_c`: > 0, Standard 10
- `hotspot_min_pixels`: >= 1, Standard 4

Unbekannte Optionen werden abgelehnt.

Thermal erfordert vollständige WIDE+THERMAL-Gruppen von genau einer bestätigten Plattform `M3T` oder `M4T`.

### GET /jobs/{job_id}

Liefert Status, Fortschritt, Phase, Meldung, Optionen, Artefakte und gegebenenfalls Publikationsstatus.

Jedes Artefakt erhält eine relative `download_url`.

### GET /jobs/{job_id}/logs?tail=200

Liefert die letzten 1–5000 Worker-Protokollzeilen.

Falls noch kein Protokoll existiert:

```json
{
  "available": false,
  "lines": []
}
```

### GET /jobs/{job_id}/artifacts/{artifact_index}

Überträgt ein Artefakt. Clients sollen die im Job gelieferte `download_url` verwenden.

### POST /jobs/{job_id}/cancel

Fordert den Abbruch eines laufenden/queued Jobs an.

## DroneDB

### POST /jobs/{job_id}/publish/dronedb

Optionaler Export eines **abgeschlossenen** Jobs mit Artefakten in die konfigurierte DroneDB Registry.

Optionaler Body:

```json
{
  "name": "Befliegung Ergebnis"
}
```

Nach erfolgreicher Veröffentlichung wird der Publikationsstatus am Job persistiert. Wiederholte Aufrufe nach erfolgreicher Publikation sind idempotent.

DroneDB ist kein V1.0.1-Kernworkflow und bleibt ein optionales Compose-Profil.

## Offline-Karten

### GET /maps

Liefert den regionalen Kartenkatalog sowie Installationsstatus und lokale MBTiles-Metadaten.

### GET /maps/{region_id}/tilejson.json

MapLibre-kompatibles TileJSON für ein installiertes Paket.

### GET /maps/{region_id}/tiles/{z}/{x}/{y}.pbf

Liefert lokale Shortbread-Vektorkacheln aus MBTiles. Die API rechnet MapLibre-XYZ-Koordinaten in die MBTiles-TMS-Zeilennummer um.

Konfigurierte Regionen:

- `baden-wuerttemberg`
- `bayern`
- `hessen`
- `rheinland-pfalz`
- `saarland`

OpenStreetMap-Attribution muss im Frontend sichtbar bleiben.

## Frontend-Vertrag

Das Frontend:

- verwendet relative `/api/v1`-Aufrufe
- konsumiert `/processing/profiles` als Fähigkeitenkatalog
- verwendet `preview_url` statt Dateisystempfade
- konstruiert Artefaktpfade nicht selbst
- zeigt API-/Jobstatus an, implementiert aber keine eigene Processing-Logik
- muss Lade-, Leer-, Fehler-, Upload-, Verarbeitungs-, Erfolgs- und Abbruchzustände darstellen
