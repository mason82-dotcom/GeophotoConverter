# Verarbeitungs-Engines

Diese Datei beschreibt den tatsächlich implementierten Stand für GeoPhotoConverter V1.0.1.

## Workflow-Semantik

- `mapping`: RGB/WIDE-Photogrammetrie mit ODM oder MicMac
- `reconstruction`: visuelle 3D-Rekonstruktion mit gsplat
- `multispectral`: kalibriertes M3M-Multispektral-Mapping mit ODM
- `thermal`: radiometrische M3T/M4T-Thermalverarbeitung
- `rgb`: Legacy-Identifier; die API normalisiert ihn engine-spezifisch auf `mapping` oder `reconstruction`

`preview`, `standard` und `high` sind davon getrennte Qualitäts-/Ressourcenprofile.
Die allgemeine Mapping-Readiness beginnt bei zwei RGB/WIDE-Bildern entsprechend
dem ODM-Minimum. MicMac verlangt weiterhin mindestens drei Bilder. Fehlendes RTK
allein blockiert normales Mapping nicht.

Die fachliche Mapping-QA bewertet zusätzlich:
- fehlende und ungültige GPS-Koordinaten getrennt;
- eindeutige/duplizierte Capture-Positionen und räumliche GPS-Ausdehnung;
- Kamera-, Bildgrößen- und Brennweitenkonsistenz;
- Konsistenz von absoluter und relativer DJI-Höhe über den Takeoff-Offset;
- nichtpositive relative Höhen;
- Gimbal-Nadir-Plausibilität und vollständige Aircraft-/Gimbal-Lage;
- Aufnahmezeit-Abdeckung und doppelte Zeitstempel;
- RTK-Metadaten-/RTK-Fix-Abdeckung;
- Scan-/Metadatenfehler.

Diese Qualitätsbefunde ändern in PGM-2 nicht stillschweigend die bestehende
Engine-Jobfreigabe. `mapping.ready` bleibt kompatibel zur Mindestbildzahl;
`mapping.status` und `mapping.issues[]` transportieren die fachliche Qualität.
Overlap/GSD werden erst mit belastbarer Kamerageometrie in einem separaten Block
berechnet.


## Gemeinsame Eingabeaufbereitung

ODM, MicMac und gsplat verwenden eine gemeinsame joblokale Eingabeaufbereitung.

### RGB/WIDE

Für normale Photogrammetrie sind `RGB` und `WIDE` zugelassen.

- JPEG/TIFF/PNG werden ohne Re-Encode verlinkt oder kopiert.
- DNG wird mit LibRaw/`dcraw_emu` zu 16-Bit-TIFF normalisiert.
- Verwendete LibRaw-Optionen: Kamera-Weißabgleich, 16 Bit, TIFF, AHD-Demosaicing.
- ExifTool kopiert EXIF/XMP/DJI-Metadaten vom DNG in die normalisierte TIFF-Datei.
- ZOOM, Thermal und Multispektral werden nicht in normale RGB-Jobs gemischt.
- Jede vorbereitete Eingabemenge enthält `geophoto-input-manifest.json`.

Damit ist DNG-Normalisierung bereits implementiert und keine spätere Planung mehr.

## OpenDroneMap / ODM

Container-Basis:

`opendronemap/odm:3.6.2`

### Workflow `mapping`

Mindestanforderung: zwei geeignete RGB/WIDE-Bilder.

Profile:

- `preview`
  - Fast Orthophoto
  - 10 cm Orthofoto-Auflösung
  - niedrigste Punktwolkenqualität
  - 3D-Modell übersprungen
- `standard`
  - DSM + DTM
  - 5 cm Orthofoto-Auflösung
  - mittlere Punktwolkenqualität
- `high`
  - DSM + DTM
  - 2 cm Orthofoto-Auflösung
  - hohe Punktwolkenqualität

Mögliche Artefakte:

- Orthofoto
- DSM
- DTM
- LAZ-Punktwolke
- OBJ-Mesh
- PDF-Bericht

### Workflow `multispectral` — DJI M3M

Mindestens zwei vollständige Capture-Gruppen.

Jede Gruppe muss enthalten:

- RGB
- Green
- Red
- Red Edge
- NIR

Eigenschaften:

- Originale M3M-Dateinamen/Bandnamen bleiben für ODM erhalten.
- Alle Bänder einer vollständigen Capture-Gruppe werden gemeinsam verarbeitet.
- Der Worker staged ausschließlich vollständige und physisch stagebare Capture-Gruppen.
  Unvollständige Gruppen werden als `incomplete_m3m_capture_group`, Gruppen mit
  fehlenden/nicht stagebaren Quelldateien als `unstageable_m3m_capture_group`
  im Input-Manifest ausgewiesen.
- `CaptureUUID` ist der bevorzugte Gruppenschlüssel, Dateinamen sind der Fallback.
- Widerspricht ein authoritative DJI-`BandName` der Dateinamenklassifikation
  in einer vollständigen Capture-Gruppe, blockiert dieser Konflikt den
  ODM-Multispektralworkflow.
- Konflikte in unvollständigen, ohnehin verworfenen Gruppen bleiben diagnostisch
  im Input-Manifest sichtbar, blockieren zwei saubere vollständige Gruppen aber
  nicht zusätzlich.
- Der Worker prüft mindestens zwei vollständige, physisch stagebare Capture-Gruppen
  und verwendet nicht mehr nur die rohe Zahl vorbereiteter Dateien als Gate.
- `--radiometric-calibration camera` ist aktiviert.
- `camera+sun` ist bewusst nicht Standard, da dieser Modus in ODM als experimentell behandelt wird.
- 3D-Modell wird in den aktuellen Multispektralprofilen übersprungen.
- Das Orthofoto wird als `multiband_orthophoto` gemeldet.

Auflösungen:

- `preview`: 10 cm
- `standard`: 5 cm
- `high`: 2 cm

## MicMac

Workflow: `mapping`

Festgelegte Upstream-Version:

`micmacIGN/micmac v1.2.0`

Das Release-Archiv wird beim Image-Build mit SHA-256 geprüft:

`84c1b48dd4f7b4e099a40d034d08afbebd4837ea61526ecae370304e8d5153c5`

Mindestanforderung: drei geeignete RGB/WIDE-Bilder.

Profile:

- `preview`
  - Tapioca
  - Tapas RadialBasic
  - AperiCloud
- `standard`
  - Tapioca
  - Tapas RadialStd
  - AperiCloud
  - C3DC QuickMac
- `high`
  - Tapioca
  - Tapas RadialStd
  - AperiCloud
  - C3DC BigMac

Aktuelle Artefakte:

- dünne Punktwolke
- dichte Punktwolke

Die aktuelle MicMac-Pipeline erzeugt Punktwolken in lokalen Rekonstruktionskoordinaten; sie ist nicht als Ersatz für die georeferenzierten ODM-Orthofoto-/DEM-Produkte zu interpretieren.

## gsplat

Workflow: `reconstruction`

Festgelegter Upstream-Commit:

`nerfstudio-project/gsplat@512d366b67073d77ca099ede742683c165dfc23b`

Laufzeitbasis:

- NVIDIA CUDA 12.8.1 + cuDNN Development
- PyTorch 2.9.1 / torchvision 0.24.1 mit CUDA-12.8-Wheels
- COLMAP für Kamera-Posen und sparse Rekonstruktion
- NVIDIA Container Toolkit erforderlich
- gsplat-CUDA-Erweiterung wird bei erster GPU-Nutzung JIT-kompiliert und im persistenten Docker-Volume gecacht

Mindestanforderung: drei geeignete RGB/WIDE-Bilder.

Profile:

- `preview`
  - COLMAP sequential matcher
  - maximale Bildgröße 1600
  - Datenfaktor 4
  - 3000 Trainingsschritte
- `standard`
  - exhaustive matcher
  - maximale Bildgröße 2400
  - Datenfaktor 2
  - 7000 Schritte
- `high`
  - exhaustive matcher
  - maximale Bildgröße 3200
  - Datenfaktor 2
  - 15000 Schritte

Die Profile nutzen packed rasterization zur Reduzierung des VRAM-Bedarfs.

Artefakte:

- Gaussian-Splat-PLY
- Checkpoints
- Trainingsstatistiken

## DJI Radiometrische Thermografie

Engine: `thermal`  
Workflow: `thermal`  
Unterstützte Plattformen: `M3T`, `M4T`

### Voraussetzung

- optionales DJI Thermal SDK / DIRP muss lokal vorhanden sein
- SDK wird **nicht** im Repository ausgeliefert
- Host-Pfad wird read-only nach `/opt/dji-tsdk` gemountet
- mindestens eine vollständige WIDE+THERMAL-Aufnahmegruppe
- alle Gruppen eines Jobs müssen genau einer bestätigten M3T- oder M4T-Plattform zugeordnet sein

Compose-Profil:

```text
thermal
```

Relevante Variablen:

- `DJI_TSDK_HOST_PATH`
- `DJI_TSDK_VERSION`

### Radiometrie

Optionale DIRP-Messwertvorgaben:

- Emissivität
- Entfernung
- Luftfeuchte
- reflektierte Temperatur
- Umgebungstemperatur

Hotspot-Parameter:

- Temperaturdifferenz-Schwelle
- Mindestanzahl zusammenhängender Pixel

### Geometrische Grenze

Die Temperaturmatrix bleibt im **Sensor-Pixelraum**.

Aktuell gilt ausdrücklich:

- `wide_thermal_coregistered = false`
- `georeferenced_temperature_raster = false`
- GPS/EXIF-Positionen beschreiben das Capture-Center
- `capture-points.geojson` georeferenziert die Aufnahmezentren, nicht einzelne Temperaturpixel
- es wird keine validierte WIDE↔THERMAL-Coregistrierung behauptet
- Hotspots sind generische thermische Kandidaten, keine automatische Defektklassifikation

### Artefakte

Der Worker kann unter anderem erzeugen:

- `temperature.tif`
- `preview.png`
- `hotspot-mask.png`
- `hotspots.json`
- `capture-points.geojson`
- `registration-audit.json`
- `thermal-summary.json`
- `thermal-summary.csv`
- `result-manifest.json`
- `thermal.json`

Die Profile `preview`, `standard` und `high` verwenden derzeit dieselbe SDK-native radiometrische Verarbeitung; Unterschiede werden nicht erfunden, solange der Worker sie nicht implementiert.

## TeleSculptor

TeleSculptor bleibt eine experimentelle/manuelle Vergleichs-Engine.

- im Processing Catalog sichtbar
- nicht Teil der automatisierten Redis-Jobqueue
- nicht V1.0.1-Kernworkflow

## Optionale Zusatzdienste

### DroneDB

Kann abgeschlossene Job-Artefakte in eine konfigurierte DroneDB Registry publizieren. Compose-Profil: `dronedb`.

### Open WebUI

Optionaler AI-Assistent. Compose-Profil: `ai`. Open WebUI ersetzt nicht die GeoPhotoConverter-Hauptoberfläche.
