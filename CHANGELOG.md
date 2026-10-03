# Changelog

Alle wesentlichen Änderungen an GeoPhotoConverter werden hier dokumentiert.

## Unreleased

### Photogrammetrie / Multispektral

- DroneDash_x64-erprobten Rasteransatz als nativen GeoPhotoConverter-Kern übernommen
- eindeutige Red/Green/NIR/Red-Edge-Bandzuordnung über Raster-Beschreibungen
- expliziter, opt-in M3M-Vierband-Fallback statt stiller Bandannahmen
- gekachelte NDVI-, NDRE- und GNDVI-Berechnung mit optionalem CuPy/CUDA und CPU-Fallback
- GeoTIFF-Ausgaben übernehmen CRS und GeoTransform der ODM-Quelle und werden atomisch veröffentlicht
- NDVI-Scouting-Zonen mit fünf Klassen; Klasse 0 bleibt NoData
- read-only API-Inspektion für ODM-`multiband_orthophoto`-Artefakte ergänzt
- Tests für Bandzuordnung, Indizes, CUDA-Strictness, Georeferenzierung und Zonen ergänzt

## 1.0.1 — 2026-09-23

Patch-Release zur Stabilisierung von V1.0. Keine neuen Verarbeitungs-Engines oder Hauptworkflows.

### Behoben

- letzte sichtbare englische/Mischtexte im deutschen Kernworkflow korrigiert
- Worker-Fehlerbehandlung gehärtet: technische Exceptions landen im Job-Log statt roh im UI
- Thermal-Worker sammelt erzeugte Artefakte wieder zuverlässig
- Regressionstest für Thermal-Artefaktsammlung ergänzt

### Reproduzierbarkeit

- direkte Frontend-Abhängigkeiten exakt versioniert
- `frontend/package-lock.json` eingeführt
- CI auf `npm ci` umgestellt
- Frontend-Docker-Build auf `npm ci` umgestellt
- VS-Code-Installtask und Entwicklungsdoku an den Lockfile-Workflow angepasst

### Dokumentation

- API-Vertrag an den tatsächlichen V1.0.1-Code angeglichen
- Processing-Dokumentation für ODM, M3M, MicMac, gsplat und Thermal aktualisiert
- implementierte DNG-Normalisierung dokumentiert
- Thermal-Grenzen dokumentiert: Sensor-Pixelraum, keine behauptete WIDE↔THERMAL-Coregistrierung
- Offline-Karten-Dokumentation auf Deutsch und auf den aktuellen MBTiles-Workflow gebracht
- README und Entwicklungsdoku um Thermal- und Offline-Kartenbetrieb ergänzt

### Nicht Bestandteil von 1.0.1

Bewusst auf spätere Releases verschoben:

- Digest-/Versions-Pinning externer Container-Images
- zusätzliche Authentifizierungs-/TLS-Härtung für Betrieb außerhalb eines vertrauenswürdigen LAN
- FastAPI-Lifespan-Migration
- Entkopplung der Worker von direktem SQLite-Zugriff
- zuverlässige Redis-Queue mit ACK/Crash-Recovery
- formale, versionierte Datenbankmigrationen
- additive DJI-Metadaten-Normalisierung aus dem FH2-Metadatenvertrag
