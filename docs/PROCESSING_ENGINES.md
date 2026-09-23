# Verarbeitungs-Engines

## Workflow-Semantik

- `mapping`: georeferenzierte RGB/WIDE-Photogrammetrie mit ODM oder MicMac
- `reconstruction`: visuelle 3D-Rekonstruktion mit gsplat
- `multispectral`: kalibriertes M3M-Multispektral-Mapping mit ODM
- `thermal`: radiometrische M3T/M4T-Thermalverarbeitung
- `rgb`: Legacy-Identifier; wird von der API engine-spezifisch auf `mapping` oder `reconstruction` normalisiert

`preview`, `standard` und `high` bleiben davon getrennte Qualitäts-/Ressourcenprofile. Für `mapping` bewertet die Dataset-QA zusätzlich GPS-Abdeckung und vorhandene DJI RTK-/Flight-/Gimbal-Metadaten; RTK ist Diagnoseinformation und keine generelle Mapping-Pflicht.


## OpenDroneMap / ODM

Container-Basis: `opendronemap/odm:3.6.2`.

Profile:

- `preview`: schnelles Orthofoto, niedrigste Punktwolkenqualität
- `standard`: DSM/DTM, mittlere Punktwolkenqualität
- `high`: DSM/DTM, hohe Punktwolkenqualität

## MicMac

Festgelegte Upstream-Version: `micmacIGN/micmac v1.2.0`.

Das Linux-Release-Archiv wird beim Image-Build mit SHA-256 geprüft:

`84c1b48dd4f7b4e099a40d034d08afbebd4837ea61526ecae370304e8d5153c5`

Profile:

- `preview`: Tapioca + Tapas RadialBasic + AperiCloud
- `standard`: Tapioca + Tapas RadialStd + AperiCloud + C3DC QuickMac
- `high`: Tapioca + Tapas RadialStd + AperiCloud + C3DC BigMac

Der erste MicMac-Worker erzeugt dünne und dichte Punktwolken in lokalen Koordinaten. GPS-/RTK-basierte Georeferenzierung sowie Orthomosaik-/DEM-Export sind eine getrennte Integrationsphase, damit die Orientierung unabhängig geprüft werden kann.

Der MicMac-Worker akzeptiert derzeit JPEG-/TIFF-Bilddaten. DNG-/R-JPEG-Konvertierung wird in einer eigenen Normalisierungsstufe umgesetzt und nicht in den Rekonstruktionsbefehlen versteckt.

## gsplat

GPU-Worker auf folgenden Upstream-Commit festgelegt:

`nerfstudio-project/gsplat@512d366b67073d77ca099ede742683c165dfc23b`

Laufzeitbasis:

- NVIDIA CUDA 12.8.1 + cuDNN-Development-Image
- PyTorch 2.9.1 / torchvision 0.24.1 mit CUDA-12.8-Wheels
- COLMAP-CLI für Kameraposen und dünne Rekonstruktion
- gsplat-CUDA-Erweiterung wird bei der ersten GPU-Nutzung per JIT kompiliert und in einem persistenten Docker-Volume gespeichert

Profile:

- `preview`: sequenzielles COLMAP-Matching, maximale Bildgröße 1600, gsplat-Faktor 4, 3000 Trainingsschritte
- `standard`: vollständiges Matching, maximale Bildgröße 2400, gsplat-Faktor 2, 7000 Schritte
- `high`: vollständiges Matching, maximale Bildgröße 3200, gsplat-Faktor 2, 15000 Schritte

Alle Profile verwenden gepackte Rasterisierung zur Reduzierung des GPU-Speicherbedarfs. Der Worker benötigt NVIDIA Container Toolkit und eine CUDA-fähige NVIDIA-GPU. Die Bildnormalisierung akzeptiert derzeit JPEG/PNG/TIFF; DNG und R-JPEG werden später über eine eigene Vorverarbeitungsstufe ergänzt.

## TeleSculptor

Nur als experimentelle/manuelle Vergleichs-Engine vorgesehen. TeleSculptor ist nicht Bestandteil der standardmäßigen automatisierten Worker-Warteschlange.
