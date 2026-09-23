# GeoPhotoConverter API-Vertrag v0.1

Basis-URL: `/api/v1`

## Systemstatus

### GET /health
Liefert den Dienststatus.

## Datensätze

### GET /datasets
Listet importierte Datensätze auf.

### POST /datasets
Erstellt einen Datensatz.

Body:
```json
{"name":"Befliegung 2026-09-21","description":"optional"}
```

### GET /datasets/{dataset_id}
Liefert Datensatzdetails einschließlich Bildanzahl, Georeferenzierungsabdeckung und Verarbeitungsbereitschaft. Zusätzlich werden die vom Backend berechneten Zusammenfassungsfelder `platform`, `duplicate_count` und `processing_readiness` sowie das vollständige `qa`-Objekt ausgegeben.

### POST /datasets/{dataset_id}/files
Multipart-Upload. Feldname: `files`.

Optionales Formularfeld: `relative_paths` als JSON-Array zur Beibehaltung der vom Browser gelieferten Ordnerpfade.

Uploads werden zunächst in eine temporäre Datei gestreamt und nach erfolgreicher Validierung atomar an die Zielposition verschoben. Das Backend berechnet für jedes Bild SHA-256, lehnt doppelte Inhalte innerhalb desselben Datensatzes ab und erzwingt konfigurierbare Größenlimits pro Datei und Datensatz.

### POST /datasets/{dataset_id}/scan
Analysiert hochgeladene Bilddaten und extrahiert EXIF-/XMP-/GPS-Metadaten.

### GET /datasets/{dataset_id}/qa
Liefert die Datensatz-QA einschließlich Georeferenzierungsabdeckung, Plattform-/Medienklassifikation, Kameramodellen, Höhenbereichen, Aufnahmezeitraum, Warnungen und Bereitschaft je Verarbeitungs-Engine.

### GET /datasets/{dataset_id}/geojson
Liefert die georeferenzierten Bildpositionen als GeoJSON-`FeatureCollection` für MapLibre.

### GET /datasets/{dataset_id}/files/{file_id}/preview?size=960
Liefert eine im Browser darstellbare JPEG-Vorschau mit angewendeter EXIF-Ausrichtung. `size` ist die maximale Kantenlänge der Vorschau (128–2048 px). Von Pillow nicht unterstützte Formate liefern HTTP 415; Dateisystempfade werden nicht offengelegt.

## Aufträge

### GET /jobs
Listet Verarbeitungsaufträge auf.

### POST /jobs
Erstellt einen Verarbeitungsauftrag.

```json
{
  "dataset_id":"...",
  "engine":"odm",
  "profile":"preview",
  "workflow":"mapping"
}
```

Erlaubte Engines: `odm`, `micmac`, `gsplat`, `telesculptor`.

Erlaubte Profile: `preview`, `standard`, `high`.

Kanonische Workflows: `mapping` (ODM/MicMac), `reconstruction` (gsplat), `multispectral` (ODM) und `thermal` (Thermal-Engine). Der ältere Bezeichner `rgb` bleibt während der Migration als Legacy-Eingabe zulässig und wird engine-spezifisch auf `mapping` bzw. `reconstruction` normalisiert.

### GET /jobs/{job_id}
Liefert Status, Fortschritt, Phase und eine Artefakt-Zusammenfassung. Jedes Artefakt enthält eine relative `download_url`.

### GET /jobs/{job_id}/logs?tail=200
Liefert die letzten 1–5000 Worker-Protokollzeilen. Falls die Verarbeitung noch kein Protokoll erzeugt hat, ist `available` gleich `false`.

### GET /jobs/{job_id}/artifacts/{artifact_index}
Überträgt ein Auftragsartefakt. Clients sollen die vom Auftrag gelieferte `download_url` verwenden und keine Dateipfade selbst zusammensetzen.

### POST /jobs/{job_id}/cancel
Fordert den Abbruch eines Auftrags an.

## Dienste

### GET /services
Liefert Verfügbarkeit und Status von ODM, MicMac, gsplat, DroneDB und Open WebUI.

## Frontend-Vertrag

Das Frontend darf keine Backend-Hostnamen fest eintragen. Es verwendet relative `/api/v1`-Aufrufe.

Erforderliche UI-Zustände:

- Laden
- Leerzustand
- Fehler
- Upload mit Fortschritt je Datei
- Verarbeitung
- Abgeschlossen
- Abgebrochen

Das Frontend enthält keine eigene Verarbeitungslogik. Es erstellt Aufträge und stellt den vom Backend gelieferten Zustand dar.

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
