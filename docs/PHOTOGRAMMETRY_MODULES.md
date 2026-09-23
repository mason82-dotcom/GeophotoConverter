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

Erster Vertrag:

- GeoTIFF-/Raster-Inspektion ohne Engine-Abhängigkeit
- CRS muss vorhanden sein; fehlendes CRS blockiert
- nicht projizierte oder nicht metrische CRS werden als Warning ausgewiesen
- GeoTransform, Bounds, Pixelauflösung, Bandzahl, Datentyp und NoData werden erfasst
- Rotation/Shear wird explizit diagnostiziert
- Rastersets (z. B. Orthofoto/DSM/DTM) werden auf gemeinsamen CRS geprüft
- disjunkte Bounds innerhalb eines Produktsets blockieren die QA
- unterschiedliche Pixelgrößen werden nicht pauschal als Fehler behandelt, weil Orthofoto und DEM absichtlich verschiedene Auflösungen haben dürfen
- später: COG/Overviews, Statistik/NoData-Anteile und direkte ODM-Artefaktintegration

Der Python-Pfad nutzt die Rasterio-Wheels; ein separater systemweiter GDAL-Source-Build
im API-Container ist für diesen Modulblock nicht erforderlich.

## PGM-POINTCLOUD — Punktwolken-QA

Issue: #53  
Status: **in Entwicklung**

Upstream-Vertrag: PDAL `2.10.2`.

Erste Phase:

- standardisierte `pdal info --summary`-Abfrage
- standardisierte `pdal info --stats`-Abfrage für X/Y/Z/Classification
- Parser für:
  - Punktzahl
  - Bounds
  - SRS
  - Dimensionen
  - XY-Flächendichte
  - Z-Bereich
  - Klassifikationszählungen
- fehlendes CRS wird zunächst als Warning ausgewiesen
- leere oder geometrisch degenerierte Clouds blockieren die QA
- der API-Container erhält **keine** native libPDAL-Abhängigkeit

Folgephase:

- eigener PDAL-Worker auf dem offiziellen Release-Image `pdal/pdal:2.10.2`
- LAS/LAZ/COPC Read/Write
- Reprojection
- Ground/HAG
- Outlier-/Density-QA
- ODM-/MicMac-/OpenMVS-Artefaktintegration

## PGM-GEOMETRY — GSD, Footprint, Overlap

Issue: #54; bestehende PGM-3-Arbeit: #50.

#54 ersetzt #50 nicht, sondern bildet das langfristige Modul. Bereits in #50
implementierte oder spezifizierte Kamera-/Footprint-/Overlap-Logik wird
übernommen und nicht parallel neu geschrieben.

## PGM-GCP — Ground Control und Checkpoints

Issue: #55

Kontrollpunkte und unabhängige Prüfpunkte werden getrennt behandelt.
Genauigkeit wird über Residuen und RMSE ausgewiesen.

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
