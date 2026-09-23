# Changelog

Alle wesentlichen Änderungen an GeoPhotoConverter werden in dieser Datei dokumentiert.

## 1.0.1 – 2026-09-23

V1.0.1 ist ein Stabilitäts- und Release-Hygiene-Update ohne neue Engine- oder Workflow-Familien.

### Stabilität

- Worker-Fehlerbehandlung vereinheitlicht: technische Tracebacks bleiben im Job-Log, während die UI eine stabile Fehlermeldung erhält.
- Thermal-Artefaktsammlung mit einem isolierten Regressionstest abgesichert.
- verbliebene sichtbare Misch-/Englischtexte im deutschen Kernworkflow bereinigt.

### Reproduzierbarkeit

- direkte Frontend-Abhängigkeiten auf konkrete Versionen festgelegt.
- `frontend/package-lock.json` eingeführt.
- CI, Frontend-Docker-Build und VS-Code-Installtask auf `npm ci` umgestellt.
- Frontend und Backend auf Version `1.0.1` abgeglichen.

### Dokumentation

- API-Vertrag an die tatsächlich ausgelieferte V1.0.1-API angepasst.
- Preview-Vertrag als WebP mit 1024 px Standardgröße dokumentiert.
- ODM-Multispektral, DNG-Normalisierung und M3T/M4T-Thermal/DIRP dokumentiert.
- Thermal-Grenzen ausdrücklich festgehalten: Temperaturwerte bleiben im Sensor-Pixelraum; keine behauptete WIDE↔THERMAL-Koregistrierung und kein georeferenziertes Temperatur-Raster.
- Offline-Karten- und Entwicklungsdokumentation vollständig deutsch und an den realen Installer/Compose-Profile angeglichen.

### Bewusst nicht Bestandteil von 1.0.1

Folgende Punkte bleiben für nachgelagerte Stabilitäts-/Härtungsarbeit:

- Pinning externer Runtime-Container auf Release-Tags/Digests.
- weitergehende LAN/Auth/TLS-Härtung.
- FastAPI-Lifespan-Migration.
- zuverlässige Redis-Queue mit ACK/Crash-Recovery.
- Worker/SQLite-Entkopplung und formale Schema-Migrationen.
- erweiterte DJI-Metadaten-Normalisierung aus dem FH2-Metadatenvertrag.

## 1.0.0 – 2026-09-21

Erster stabiler Hauptrelease mit lokalem Bildimport, EXIF/XMP/DJI-Metadaten, Dataset-QA, Vorschauen, Offline-Karte, Processing-Katalog, ODM, MicMac, gsplat, DJI-Thermal-Workflow, Jobmonitor, Artefakten, optionaler DroneDB-Publikation und optionalem Open WebUI.
