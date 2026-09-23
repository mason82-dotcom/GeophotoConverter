# Offline-Karten

GeoPhotoConverter kann lokale Vektorkarten für MapLibre bereitstellen und benötigt nach Installation eines Kartenpakets für die Basiskarte keine Internetverbindung.

## Kartenpakete

Standardpaket:

- Baden-Württemberg

Zusätzlich vorkonfiguriert:

- Bayern
- Hessen
- Rheinland-Pfalz
- Saarland

Die Pakete verwenden Geofabrik-Shortbread-MBTiles auf Basis von OpenStreetMap-Daten.

## Installation

Vom Repository-Stammverzeichnis aus Baden-Württemberg installieren:

```bash
python scripts/maps/download_map_pack.py baden-wuerttemberg
```

Das vollständige konfigurierte Süddeutschland-Set installieren:

```bash
python scripts/maps/download_map_pack.py south-germany
```

Ein bereits vorhandenes Paket wird validiert und ohne `--force` nicht erneut geladen.

## Speicherort

Karten werden unter

```text
data/maps/
```

gespeichert.

`*.mbtiles` und unvollständige `*.mbtiles.part`-Dateien sind von Git ausgeschlossen. Die großen Kartendaten gehören bewusst nicht in die normale Repository-Historie.

## API

Nach Start der API:

- `GET /api/v1/maps`
- `GET /api/v1/maps/{region}/tilejson.json`
- `GET /api/v1/maps/{region}/tiles/{z}/{x}/{y}.pbf`

### Kartenkatalog

`GET /api/v1/maps` meldet pro Paket unter anderem:

- ID und Name
- Quelldatei/URL aus dem Katalog
- installiert / nicht installiert
- lokale Dateigröße
- Bounds
- Min-/Max-Zoom, soweit in MBTiles vorhanden

### TileJSON

MapLibre erhält lokale Tile-URLs über den TileJSON-Endpunkt.

### Koordinatenschema

MapLibre fordert Kacheln im XYZ-Schema an. MBTiles speichert die Zeile nach TMS. Die API rechnet die Y-Koordinate beim Lesen entsprechend um.

## Betrieb

Das Frontend soll bevorzugt die lokale Basemap verwenden, sobald ein passendes Paket installiert ist. Externe Online-Basemaps dürfen keine Voraussetzung für die Kernfunktion sein.

## Quelle und Lizenz

Die vorkonfigurierten Pakete stammen von Geofabrik und basieren auf OpenStreetMap-Daten.

Die OpenStreetMap-Attribution muss in der Kartenansicht sichtbar bleiben. Vor einer Weiterverteilung der Kartendaten außerhalb der lokalen Installation sind die aktuellen Lizenz- und Nutzungsbedingungen von OpenStreetMap/ODbL sowie Geofabrik zu beachten.
