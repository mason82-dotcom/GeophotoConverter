# PGM-GCP — Ground Control Points und Checkpoints

Issue: #55  
Basis: PGM-GEO (#51)

## Ziel

PGM-GCP stellt einen engine-neutralen Vertrag für vermessene Bodenpunkte,
Bildbeobachtungen, unabhängige Checkpoints sowie Residuen/RMSE bereit.

## Punktvertrag

Ein Punkt enthält:

- eindeutige `id`
- `role`: `control` oder `checkpoint`
- metrische Projektkoordinaten `x_m`, `y_m`, `z_m`
- optional `sigma_x_m`, `sigma_y_m`, `sigma_z_m`
- mindestens zwei Bildbeobachtungen
- pro Beobachtung:
  - `image_name`
  - `pixel_x`
  - `pixel_y`

Alle Punkte eines Projekts verwenden genau ein explizites projiziertes CRS mit
Meterachsen. PGM-GCP transformiert Koordinaten nicht still; Umprojektion erfolgt
vorher explizit über PGM-GEO.

## Qualitätsregeln

Blocked:

- ungültiges/nicht metrisches Projekt-CRS
- fehlende oder doppelte Punkt-ID
- unbekannte Rolle
- nicht-finite XYZ-Koordinaten
- ungültige/negative Pixelkoordinaten
- doppelte Beobachtung desselben Punkts im selben Bild
- weniger als zwei Bildbeobachtungen pro Punkt
- weniger als drei Control Points

Warning:

- weniger als drei Bildbeobachtungen pro Punkt
- weniger als fünf Control Points

Fünf gut verteilte Kontrollpunkte mit je mindestens drei Bildbeobachtungen sind
für robuste ODM-Mappingprojekte empfohlen.

## Control vs. Checkpoint

Die Rollen werden strikt getrennt:

- `control`: darf in die Bundle-/Georeferenzierungsanpassung eingehen
- `checkpoint`: unabhängige Qualitätskontrolle

Adapter exportieren standardmäßig **nur Control Points**. Checkpoints werden
niemals still als Kontrollpunkte verwendet.

## ODM-Adapter

Erzeugt `gcp_list.txt`:

```text
EPSG:<code>
geo_x geo_y geo_z im_x im_y image_name gcp_name
...
```

Standardmäßig werden nur Control Points exportiert.

## MicMac-Adapter

Erzeugt:

- `ground_points.txt` im Format `N X Y Z`
- `SetOfMesureAppuisFlottants`-XML mit Bildmessungen
- Kommando-Metadaten für:
  `mm3d GCPConvert "#F=N_X_Y_Z" ground_points.txt Out=ground_points.xml`

Auch hier werden Checkpoints standardmäßig nicht in die Anpassung gespeist.

## COLMAP

Der Standard-`model_aligner` von COLMAP richtet Rekonstruktionen über
Referenzpositionen von **Kamerazentren** aus. Er wird deshalb nicht als direkter
Adapter für beliebige vermessene Bodenpunkte dargestellt.

PGM-GCP meldet für diesen direkten Pfad explizit
`no_direct_ground_point_constraint_adapter`.

Ein späterer COLMAP-GCP-Pfad muss zuerst einen fachlich belastbaren
Punkt-/Constraint-Workflow definieren und testen.

## Residuen und RMSE

`residual_report()` vergleicht geschätzte/rekonstruierte XYZ-Koordinaten mit
den Referenzpunkten und liefert getrennt für Control Points und Checkpoints:

- RMSE X
- RMSE Y
- RMSE Z
- horizontalen RMSE
- 3D-RMSE
- Einzelresiduen
- fehlende Schätzungen

Checkpoint-RMSE ist die primäre unabhängige Qualitätskennzahl; Control-RMSE
darf nicht als unabhängige Genauigkeitsprüfung interpretiert werden.

## Phase 2

Nach stabilem Domainvertrag:

- Persistenz pro Dataset
- Import-/Export-API
- Frontend-Punkteditor
- ODM-Worker-Verkabelung über `--gcp`
- MicMac-Worker-Verkabelung
- Checkpoint-Report als Job-Artefakt
- reale Integrationstests mit vermessenem Mapping-Dataset
