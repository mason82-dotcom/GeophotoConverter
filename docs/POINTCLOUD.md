# Punktwolkenmodul

## Zweck

Das Punktwolkenmodul stellt klassische 3D-Punktwolken aus GeoPhotoConverter-Verarbeitungsaufträgen interaktiv dar.

Quellen:
- ODM: georeferenzierte LAZ-Punktwolke
- MicMac: sparse/dense PLY-Punktwolken

Gaussian-Splat-PLY aus gsplat wird bewusst nicht als klassische Punktwolke behandelt.

## Architektur

### Backend

Unterstützte Formate:
- LAS
- LAZ
- PLY ASCII
- PLY binary little endian
- PLY binary big endian

LAS/LAZ:
- Reader: `laspy`
- LAZ-Dekompression: `lazrs`
- CRS-Auswertung: `pyproj` über die LAS/LAZ-VLRs
- Verarbeitung in Chunks, damit große LAZ-Dateien nicht vollständig in den RAM geladen werden müssen
- Metadaten enthalten zusätzlich LAS-Version, Punktformat, Scale/Offset und – falls vorhanden – Koordinatenreferenzsystem/EPSG

PLY:
- eigener Header-/Vertex-Reader
- keine zusätzliche GPL-Paketabhängigkeit
- Standard-Vertex-Eigenschaften `x/y/z` erforderlich
- PLY-Header ist auf 1 MiB begrenzt
- verkürzte Vertex-Zeilen sowie NaN/Inf-Koordinaten werden als ungültig abgelehnt
- RGB wird über `red/green/blue` oder `r/g/b` erkannt

### Sampling

Der Browser lädt nicht die Originalpunktwolke.

Die API bildet eine gleichmäßig verteilte Stichprobe mit 1.000–500.000 Punkten. Standard sind 100.000 Punkte.

Die Vorschau wird mit der Quellsignatur aus Pfad, Dateigröße und Änderungszeit gecacht. Ändert sich das Artefakt, entsteht automatisch ein neuer Cache-Key.

Cache-Schreibvorgänge verwenden eindeutige temporäre Dateien und atomisches Umbenennen, damit parallele Preview-Anfragen nicht auf denselben `.part`-Pfad schreiben.

### Binärformat

Ein Punkt belegt 16 Byte:

```text
float32 x
float32 y
float32 z
uint8   r
uint8   g
uint8   b
uint8   a
```

XYZ sind relativ zum Mittelpunkt der Bounding Box. Dadurch bleiben große georeferenzierte Koordinaten im WebGL-Float32-Raum numerisch stabil.

## Frontend

Der Viewer verwendet WebGL2 direkt.

Funktionen:
- Orbit-Drehung per Ziehen
- Zoom per Mausrad
- Ansicht zurücksetzen
- Punktgröße 1–8
- RGB-Färbung, sofern vorhanden
- Höhenfärbung als Fallback oder alternative Darstellung
- Auswahl 50k / 100k / 200k / 500k Vorschaupunkte
- Punktzahl, Format, Dateigröße, Bounds und Dimensionen

Der GPU-Buffer wird pro geladener Vorschau nur einmal erzeugt. Kamerabewegungen ändern ausschließlich die View-/Projection-Matrix.

## Integration

Navigation:
- `Punktwolken`

Ergebnisse:
- klassische Punktwolken erhalten die Aktion `Im Viewer öffnen`
- Originalartefakt bleibt separat herunterladbar

## Grenzen der ersten Version

Noch nicht enthalten:
- COPC
- EPT
- Potree-Octrees
- 3D Tiles
- Punktselektion/Messwerkzeuge
- Klassifikationsfilter
- Boden-/Vegetationssegmentierung
- progressive LOD-Nachladung

Für lokale ODM-/MicMac-Projekte ist die gecachte Stichprobe der bewusst einfache V1-Pfad.
