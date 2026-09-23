# PGM-EPOCH — Multi-temporale Change Detection

Issue: #59  
Abhängigkeiten: PGM-GEO, PGM-GCP, PGM-RASTER, PGM-POINTCLOUD, PGM-3D-QA

## Ziel

Vergleich wiederholter Befliegungen auf explizit gemeinsamer räumlicher Basis.

Phase 1 liefert einen engine-neutralen Vertrag für:

- Epoch-Paarvalidierung
- signierte Raster-Differenzen
- Change Mask
- Cut/Fill/Netto-Volumen aus DSM-/Rasterzellen
- signierte Punktwolken-Differenzen
- Provenienz des Referenz-/Vergleichsartefakts

## Epoch-Vertrag

Jede Epoche benötigt:

- eindeutige ID
- UTC-Zeit `captured_at`
- explizite CRS-ID
- projiziertes CRS
- metrische Achsen

Die Vergleichsepoche muss zeitlich nach der Referenz liegen.

## CRS-Regel

Beide Epochen müssen in Phase 1 dieselbe explizite metrische CRS-ID besitzen.

Keine stille Reprojektion und keine automatische Transformation im
Change-Detection-Modul.

Wenn Reprojektion notwendig ist, muss sie vorgelagert und dokumentiert über
PGM-GEO/Raster/Pointcloud erfolgen.

## Raster-Change

Eingabe:

- signierte Höhen-/Wertdifferenz pro gültiger Zelle
- Zellfläche in m²
- symmetrische Change-Schwelle in m

Maske:

- `-1`: negativer Change
- `0`: innerhalb der Schwelle stabil
- `1`: positiver Change
- `null`: ungültig/NoData

Ausgabe:

- Changed/Stable Cell Count
- Changed Area
- Fill Volume
- Cut Volume
- Netto-Volumen
- getrennte positive/negative Statistik

Volumen wird nur bei explizit bekannter Zellfläche berechnet.

## Pointcloud-Change

Signierte Cloud-Distanzen werden analog nach positiv/negativ/stabil
klassifiziert und statistisch ausgewertet.

Es wird **kein Volumen aus bloßen Punktdistanzen erfunden**.

Volumenänderungen aus Punktwolken benötigen einen eigenen
Oberflächen-/Rasterintegrationsschritt.

## Provenienz

Der Report kann Referenz- und Vergleichsartefakte, Job-IDs, Engine-Versionen,
GCP-/Checkpoint-Reports und Transformationsnachweise aufnehmen.

Diese Provenienz ist Teil des maschinenlesbaren Ergebnisvertrags.

## Genauigkeitsgrenze

Change Detection ist nur so belastbar wie:

- gemeinsame CRS-Basis
- GCP-/Checkpoint-Qualität
- Registrierung
- Raster-/Cloud-QA
- räumliche Auflösung
- gewählte Change-Schwelle

Ein numerischer Unterschied allein wird nicht automatisch als reale
Geländeveränderung interpretiert.

## Phase 2

- Rasterio-basierter DSM/DTM-Differenzworker
- PDAL/Open3D-basierter Cloud-Differenzworker
- COG/GeoTIFF Change Mask
- Volumen-Polygone
- GCP-/Checkpoint-Gate
- Frontend Multi-Epoch-Auswahl und Kartenvisualisierung
- reale Wiederholungsbefliegungs-Fixtures
