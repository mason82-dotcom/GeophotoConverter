# Photogrammetrie-Module

Diese Datei ist die technische Modul-Roadmap für den Photogrammetrie-Teil von
GeoPhotoConverter. Die fachliche Koordination erfolgt über GitHub-Issue #11.

## Abhängigkeitskette

```text
kanonische Metadaten / Mapping-Readiness
        |
        v
PGM-GEO (#51)
        |
        +--> PGM-RASTER (#52)
        +--> PGM-POINTCLOUD (#53)
        +--> PGM-GEOMETRY (#54, baut auf #50 auf)
        |
        +--> PGM-GCP (#55)
        +--> PGM-SFM-QA (#56)
                 |
                 +--> PGM-MVS (#57)
                 +--> PGM-3D-QA (#58)
                            |
                            v
                     PGM-EPOCH (#59)
```

## PGM-GEO — CRS und Geodäsie

Status: **in Entwicklung**

Technischer Kern: PROJ über `pyproj==3.8.0`.

Vertrag:

- Eingangspositionen sind WGS84 Latitude/Longitude in Grad.
- Automatische Projektionswahl ist konservativ.
- Ein CRS wird nur vorgeschlagen, wenn genau ein WGS84-UTM-CRS den kompletten
  Datensatz enthält.
- Zonenüberschreitende und Antimeridian-Datensätze werden nicht still einem
  beliebigen UTM-CRS zugeordnet.
- metrische Folgealgorithmen akzeptieren nur projizierte CRS mit Meterachsen.
- horizontale Transformation und Höhenreferenz bleiben getrennte Verträge.
- `height.ellipsoid_m` ist der einzige derzeit akzeptierte absolute
  Z-Kandidat für Georeferenzierung.
- `height.gps_altitude_m` bleibt semantisch generisch.
- `height.relative_m` ist ausschließlich takeoff-relativ und für
  Aufnahmegeometrie/GSD gedacht, nicht als absolutes Z.

PGM-GEO ist die gemeinsame Grundlage für ODM-`geo.txt`, MicMac-
Georeferenzierung, GCP/Checkpoints, Footprints, Overlap und räumliche QA.

## PGM-RASTER — Raster-QA

Issue: #52

Status: **in Entwicklung**

Technischer Kern: `rasterio==1.5.1`.

Phase 1:

- engine-neutrale GeoTIFF-Inspektion
- Driver, Größe, Bandzahl, Datentypen und NoData
- CRS, GeoTransform, Bounds und Pixelauflösung
- fehlendes CRS blockiert
- geographisches oder nicht-metrisches CRS warnt
- Rotation/Shear wird explizit markiert
- Produktsets prüfen gemeinsames CRS und räumliche Überdeckung
- unterschiedliche Auflösungen allein gelten nicht als Fehler

Spätere Phasen:

- ODM-Artefakt-QA direkt im Worker
- quantitative NoData-/Histogramm-Prüfung
- optionale Reprojektion/Resampling
- COG und Overviews

## PGM-POINTCLOUD — Punktwolken-QA

Issue: #53

Status: **in Entwicklung**

Upstream-Vertrag: PDAL `2.10.2`.

Phase 1 ergänzt den bestehenden LAS/LAZ/PLY-Viewer um einen engine-neutralen
PDAL-QA-Vertrag:

- standardisierte `pdal info --summary`-Abfrage
- standardisierte `pdal info --stats`-Abfrage für X/Y/Z/Classification
- Punktzahl, Bounds, strukturierte SRS-Daten und Dimensionen
- XY-Dichte mit expliziter Einheit statt impliziter Quadratmeter-Annahme
- Z-Bereich und Klassifikationszählungen
- fehlendes CRS = Warning
- geographisches CRS = Warning
- leere oder geometrisch degenerierte Clouds = blocked
- keine native libPDAL-Abhängigkeit im FastAPI-Container

Der vorhandene Viewer bleibt für LAS/LAZ/PLY zuständig. PGM-POINTCLOUD ist die
fachliche QA-/Processing-Schicht und dupliziert Sampling oder WebGL-Darstellung
nicht.

Phase 2A (#79):

- optionales Compose-Profil `pdal`
- gekapselter Sidecar auf `condaforge/miniforge3:26.7.2-0` mit isolierter Conda-Umgebung `pdal` und exakt `pdal=2.10.2`
- Container-Dateisystem read-only; `/data` wird read-only eingebunden
- PROJ-Netzwerkzugriffe sind deaktiviert
- `GET /health`
- `POST /qa` akzeptiert ausschließlich relative Artefaktpfade unter `/data`
- dynamische Stats-Dimensionen: X/Y/Z und optional Classification
- API-Endpunkt `/api/v1/jobs/{job_id}/pointclouds/{artifact_index}/qa`
- Service-Zustand unter `/api/v1/services`
- eigenes Container-Smoke-Gate mit realer PLY-Punktwolke

Phase 2B:

- COPC Read/Write
- Reprojection
- Ground/SMRF
- HAG
- Outlier-/Density-QA
- ODM-/MicMac-/OpenMVS-Artefaktintegration

Schreibende Filter werden bewusst nicht mit der read-only Phase-2A-QA vermischt.

## PGM-GEOMETRY — GSD, Footprint, Overlap

Issue: #54; bestehende PGM-3-Arbeit: #50.

#54 ersetzt #50 nicht, sondern bildet das langfristige Modul. Bereits in #50
implementierte oder spezifizierte Kamera-/Footprint-/Overlap-Logik wird
übernommen und nicht parallel neu geschrieben.

## PGM-GCP — Ground Control und Checkpoints

Issue: #55

Status: **Phase 1 implementiert**

- engine-neutraler Punkt-/Beobachtungsvertrag
- Control/Checkpoint strikt getrennt
- ODM `gcp_list.txt`-Export
- MicMac 3D-/Bildmessungs-Export
- explizite COLMAP-Fähigkeitsgrenze
- getrennte Control-/Checkpoint-Residuen und RMSE

Details: `docs/PGM_GCP.md`

## PGM-SFM-QA

Issue: #56

COLMAP/pycolmap-Metriken vor Dense-/gsplat-Verarbeitung, unter anderem
registrierte Bilder, Reprojection Error, Track Length und Kameranetz-QA.

## PGM-MVS

Issue: #57

Optionaler COLMAP-zu-OpenMVS-Pfad für Dense Point Cloud, Mesh, Refinement und
Texturierung. Kein Ersatz für den georeferenzierten ODM-Mapping-Kernpfad.

## PGM-3D-QA

Issue: #58

Open3D-basierte Registrierung und Cloud-/Mesh-Vergleiche.

## PGM-EPOCH

Issue: #59

Multi-temporale Change Detection erst auf stabiler GEO-/GCP-/Raster-/
Punktwolkenbasis.
