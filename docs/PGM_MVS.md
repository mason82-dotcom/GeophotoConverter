# PGM-MVS — OpenMVS Dense-/Mesh-Backend

Issue: #57  
Abhängigkeit: PGM-SFM-QA (#56)

## Ziel

Optionaler COLMAP→OpenMVS-Pfad für:

1. COLMAP-Import
2. Dense Point Cloud
3. Mesh
4. optional Mesh Refinement
5. optional Texturierung

PGM-MVS ist **kein Ersatz für ODM-Mapping**. Georeferenzierte Orthofotos/DEM und
der etablierte Mapping-Kern bleiben Aufgabe von ODM.

## Upstream-Vertrag

OpenMVS: **v2.4.0**

OpenMVS 2.4.0 ist der aktuelle stabile Release-Vertrag für dieses Modul.

## Eingabe

Der Pipeline-Planer erwartet:

- vorbereitetes COLMAP-Workspace
- explizites Image-Verzeichnis
- separates OpenMVS-Ausgabeverzeichnis
- ausschließlich absolute Pfade

Absolute Pfade sind bewusst verpflichtend. Bei OpenMVS 2.4.0 existieren
bekannte Fallstricke bei relativ aufgelösten COLMAP-Image-Pfaden.

## Profile

### preview

- InterfaceCOLMAP
- DensifyPointCloud
- ReconstructMesh

Ziel: schneller Dense-/Mesh-Nachweis ohne Refine/Textur.

### standard

- InterfaceCOLMAP
- DensifyPointCloud
- ReconstructMesh
- TextureMesh

### high

- InterfaceCOLMAP
- DensifyPointCloud
- ReconstructMesh
- RefineMesh
- TextureMesh

Die Profile unterscheiden sich in Phase 1 nur über tatsächlich ausgeführte
OpenMVS-Stages. Es werden keine ungetesteten Qualitätsparameter erfunden.

## SFM-QA-Gate

PGM-MVS kann das Ergebnis von PGM-SFM-QA konsumieren.

- SFM `blocked` → MVS blockiert
- weniger als zwei registrierte Bilder → blockiert
- keine Sparse Points → blockiert
- SFM `warning` → MVS bleibt verfügbar, Warning wird erhalten

## Artefakte

Der Plan beschreibt:

- `scene.mvs`
- `scene_dense.mvs`
- Dense-Punktwolken-Sidecars
- Mesh
- optional refined scene
- optional textured scene
- optionale OBJ/MTL/Textur-Sidecars

Der spätere Worker validiert die tatsächlich erzeugten Dateien.

## Lizenz

OpenMVS: AGPL-3.0.

Das Modul bleibt optional und getrennt vom ODM-Kernpfad.

## Phase 2

- eigener OpenMVS-2.4.0-Worker
- reproduzierbares CPU-Image
- optionales CUDA-Profil separat
- COLMAP-Workspace-Staging
- Ausführung des Pipeline-Plans
- standardisierte Job-Artefakte
- SFM-QA als vorgeschaltetes Quality Gate
- reale Fixture mit Sparse COLMAP-Modell
