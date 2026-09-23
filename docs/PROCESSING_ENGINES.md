# Verarbeitungs-Engines

Der Backend-Katalog unter `GET /api/v1/processing/profiles` ist die maßgebliche Laufzeitquelle für verfügbare Engines, Workflows, Profile, Optionen und erwartete Ausgaben.

## Gemeinsame Bildnormalisierung

Die Photogrammetrie-Worker verwenden `workers/common/images.py`.

Direkt verwendete Rasterformate:

- JPEG
- PNG
- TIFF

DNG wird vor der Verarbeitung mit LibRaw/`dcraw_emu` in TIFF normalisiert. Anschließend kopiert ExifTool die Metadaten aus der Quelldatei in das normalisierte TIFF.

R-JPEG wird **nicht** als allgemeiner Photogrammetrie-Input behandelt. Radiometrische Thermalmedien gehören in den separaten Thermal-Workflow.

## OpenDroneMap / ODM

Container-Basis: `opendronemap/odm:3.6.2`.

### RGB-/WIDE-Workflow

- Workflow: `odm/rgb`
- geeignete Medien: `RGB`, `WIDE`
- Mindestanzahl: 2 Bilder

Ausgaben laut Backend-Katalog:

- `orthophoto`
- `dsm`
- `dtm`
- `point_cloud_laz`
- `mesh_obj`
- `report_pdf`

Profile:

- `preview`: ca. 10 cm Orthofoto-Auflösung, schnelle Prüfung
- `standard`: ca. 5 cm, allgemeines Mapping
- `high`: ca. 2 cm, höher aufgelöste Verarbeitung

### M3M-Multispektral-Workflow

- Workflow: `odm/multispectral`
- Plattform: `M3M`
- benötigte Medien pro vollständiger Gruppe:
  - `RGB`
  - `MS_GREEN`
  - `MS_RED`
  - `MS_RED_EDGE`
  - `MS_NIR`
- mindestens 2 vollständige Aufnahmegruppen
- radiometrische Kalibrierung: `camera`

`camera+sun` ist im GeoPhotoConverter-Katalog bewusst deaktiviert, weil dieser ODM-Pfad als experimentell behandelt wird.

Ausgaben:

- `multiband_orthophoto`
- `point_cloud_laz`
- `report_pdf`

Die M3M-Eingaben werden über den gemeinsamen Vorbereitungsweg in ein flaches Projektverzeichnis überführt. DNG wird dabei wie oben beschrieben nach TIFF normalisiert. Dateinamen müssen beim Flattening eindeutig bleiben.

## MicMac

Festgelegte Upstream-Version: `micmacIGN/micmac v1.2.0`.

Das Linux-Release-Archiv wird beim Image-Build mit SHA-256 geprüft:

`84c1b48dd4f7b4e099a40d034d08afbebd4837ea61526ecae370304e8d5153c5`

Workflow:

- `micmac/rgb`
- geeignete Medien: `RGB`, `WIDE`
- Mindestanzahl: 3 Bilder

Profile:

- `preview`: Tapioca + Tapas RadialBasic + AperiCloud
- `standard`: Tapioca + Tapas RadialStd + AperiCloud + C3DC QuickMac
- `high`: Tapioca + Tapas RadialStd + AperiCloud + C3DC BigMac

Ausgaben:

- `sparse_point_cloud`
- `dense_point_cloud`

Der Worker erzeugt dünne und dichte Punktwolken in lokalen Koordinaten. GPS-/RTK-basierte Georeferenzierung sowie Orthomosaik-/DEM-Export sind nicht Teil dieses MicMac-Vertrags.

JPEG/PNG/TIFF werden direkt vorbereitet; **DNG-Normalisierung ist bereits implementiert** und erfolgt vor den MicMac-Kommandos über den gemeinsamen LibRaw-/ExifTool-Pfad. R-JPEG ist kein MicMac-Photogrammetrie-Input.

## gsplat

GPU-Worker auf folgenden Upstream-Commit festgelegt:

`nerfstudio-project/gsplat@512d366b67073d77ca099ede742683c165dfc23b`

Laufzeitbasis:

- NVIDIA CUDA 12.8.1 + cuDNN-Development-Image
- PyTorch 2.9.1 / torchvision 0.24.1 mit CUDA-12.8-Wheels
- COLMAP-CLI für Kameraposen und dünne Rekonstruktion
- gsplat-CUDA-Erweiterung wird bei der ersten GPU-Nutzung per JIT kompiliert und in einem persistenten Docker-Volume gespeichert

Workflow:

- `gsplat/rgb`
- geeignete Medien: `RGB`, `WIDE`
- Mindestanzahl: 3 Bilder
- NVIDIA-GPU erforderlich

Profile:

- `preview`: sequenzielles COLMAP-Matching, maximale Bildgröße 1600, gsplat-Faktor 4, 3000 Trainingsschritte
- `standard`: vollständiges Matching, maximale Bildgröße 2400, gsplat-Faktor 2, 7000 Schritte
- `high`: vollständiges Matching, maximale Bildgröße 3200, gsplat-Faktor 2, 15000 Schritte

Ausgaben:

- `gaussian_splat_ply`
- `checkpoint`
- `training_stats`

Alle Profile verwenden gepackte Rasterisierung zur Reduzierung des GPU-Speicherbedarfs.

Wie bei MicMac wird **DNG bereits vor COLMAP/gsplat nach TIFF normalisiert**. JPEG/PNG/TIFF werden direkt verwendet. R-JPEG gehört nicht in diesen Rekonstruktionspfad.

## DJI Radiometrische Thermografie

Workflow:

- `thermal/thermal`
- Plattformen: `M3T`, `M4T`
- mindestens eine vollständige WIDE+THERMAL-Aufnahmegruppe
- lokales DJI Thermal SDK / DIRP erforderlich

Fachliche Grenzen des ausgelieferten Vertrags:

- Temperaturwerte bleiben im `sensor_pixel`-Raum.
- WIDE und THERMAL werden nicht als pixelgenau koregistriert behauptet.
- Es wird kein georeferenziertes Temperatur-Raster behauptet.
- Capture-Punkte verwenden vorhandene Aufnahme-GPS-Positionen; sie machen aus dem Temperaturbild kein Thermal-Orthomosaik.

Optionale radiometrische Vorgaben:

- `emissivity`
- `distance_m`
- `humidity_pct`
- `reflection_c`
- `ambient_temp_c`

Hotspot-Parameter:

- `hotspot_delta_c`, Default 10.0
- `hotspot_min_pixels`, Default 4

Ausgaben laut Katalog:

- `thermal_temperature_tiff`
- `thermal_preview`
- `thermal_hotspot_mask`
- `thermal_hotspots`
- `thermal_capture_points`
- `thermal_summary`
- `thermal_registration_audit`

Der Worker erzeugt zusätzlich weitere technische Dateien wie Ergebnismanifest und Capture-Metadaten. Hotspot-Kandidaten sind keine automatische Geräte- oder PV-Defektklassifikation.

## TeleSculptor

TeleSculptor ist ausschließlich als experimentelle/manuelle Vergleichs-Engine vorgesehen.

- `automated=false`
- keine automatisierten Workflows im Backend-Katalog
- `POST /api/v1/jobs` lehnt TeleSculptor als automatische Job-Engine mit HTTP 409 ab

TeleSculptor ist damit nicht Bestandteil der standardmäßigen Worker-Warteschlange.
