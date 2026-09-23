# PGM-3D-QA — Open3D Vergleich und Registrierung

Issue: #58  
Abhängigkeiten: PGM-POINTCLOUD, PGM-SFM-QA, optional PGM-MVS

## Ziel

Engine-neutrale 3D-Qualitätsbewertung und Referenzvergleich zwischen
Punktwolken/Modellen.

Open3D-Vertrag: **0.20.0**.

## Phase-1-Vertrag

Der Backend-Kern importiert Open3D nicht direkt. Er beschreibt den
Ausführungsplan und normalisiert die resultierenden Metriken.

Ein späterer Worker führt denselben Vertrag mit Open3D 0.20.0 aus.

## Pipeline

Konfigurierbar:

- Voxel Downsampling
- Statistical Outlier Removal
- optional Normalenschätzung
- initiale Registration Evaluation
- ICP
  - point-to-point
  - point-to-plane
- Source→Target-Distanzen
- Target→Source-Distanzen

Point-to-plane ICP erfordert Normalen und fügt daher explizit eine
Normalenschätzung in den Plan ein.

## Registration-Metriken

Open3D liefert:

- Fitness
- Inlier RMSE
- Transformation
- Correspondence Count, soweit verfügbar

Fitness misst den Überlappungsanteil; Inlier RMSE die Anpassung der gültigen
Korrespondenzen.

## Cloud-to-cloud-Distanzen

Beide Richtungen werden getrennt berechnet.

Je Richtung:

- Count
- Mean
- Median
- RMSE
- p95
- Maximum

Zusätzlich wird als konservative symmetrische Kennzahl das Maximum der beiden
p95-Distanzen ausgewiesen.

## Outlier

Phase 1 normalisiert das Verhältnis entfernter Punkte aus einer vorgelagerten
Statistical-Outlier-Removal-Stufe.

## Standard-Warnschwellen

- Fitness < 0.50
- Inlier RMSE > 0.10 m
- symmetrische p95-Distanz > 0.20 m
- Outlier-Anteil > 10 %

Diese Werte sind **keine universelle Vermessungsgenauigkeit**. Sie sind
konfigurierbare Warnschwellen und müssen zum Projektmaßstab passen.

Blocked wird nur bei strukturell ungültigen Eingaben wie leerer Source- oder
Target-Cloud erzeugt.

## Koordinatenvertrag

PGM-3D-QA erwartet räumlich vergleichbare Punktwolken in einer bekannten,
metrisch interpretierbaren Referenz.

Ohne gemeinsame CRS-/GCP-/Registrierungsbasis darf ein niedriger ICP-RMSE nicht
als absolute geodätische Genauigkeit interpretiert werden.

## Phase 2

- dedizierter Open3D-0.20.0-Worker
- reale LAS/LAZ/PLY-Fixtures
- PDAL→Open3D-Staging
- GCP-/Checkpoint-basierte Referenzbewertung
- 3D-QA-JSON als Job-Artefakt
- Visualisierung von Distanzverteilungen und Transformationen
