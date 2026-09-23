# Offline-Karten

GeoPhotoConverter kann lokale Vektorkarten aus MBTiles-Dateien an MapLibre ausliefern. Nach der Installation der Kartenpakete benötigt die Kartenanzeige dafür keine Internetverbindung.

## Standardpaket Baden-Württemberg

Vom Repository-Stammverzeichnis aus installieren:

```powershell
python scripts/maps/download_map_pack.py baden-wuerttemberg
```

Bereits vorhandene Dateien werden validiert und ohne `--force` nicht erneut heruntergeladen.

## Süddeutschland komplett

Alle im Kartenkatalog der Gruppe `south-germany` zugeordneten Pakete installieren:

```powershell
python scripts/maps/download_map_pack.py south-germany
```

Der aktuelle API-Katalog enthält:

- `baden-wuerttemberg` (Standard)
- `bayern`
- `hessen`
- `rheinland-pfalz`
- `saarland`

## Speicherort

Standard:

```text
data/maps/
```

Ein anderes GeoPhoto-Datenverzeichnis kann beim Installer explizit angegeben werden:

```powershell
python scripts/maps/download_map_pack.py baden-wuerttemberg --data-dir D:\GeoPhotoData
```

Mit `--force` wird ein vorhandenes Paket erneut heruntergeladen.

Der Downloader schreibt zunächst eine `.part`-Datei, prüft anschließend die SQLite-/MBTiles-Struktur und ersetzt erst danach atomar die Zieldatei. Große MBTiles-Dateien werden bewusst nicht in die normale Git-Historie aufgenommen.

## API

Nach dem Start der API:

- `GET /api/v1/maps` – Kartenkatalog und Installationsstatus
- `GET /api/v1/maps/{region}/tilejson.json` – MapLibre-kompatibles TileJSON
- `GET /api/v1/maps/{region}/tiles/{z}/{x}/{y}.pbf` – Vektorkacheln aus MBTiles

Die API konvertiert die von MapLibre verwendeten XYZ-Kachelkoordinaten auf die in MBTiles verwendete TMS-Zeile.

## Quelle und Attribution

Die konfigurierten Pakete verwenden Geofabrik-Shortbread-MBTiles auf Basis von OpenStreetMap-Daten.

Die sichtbare OpenStreetMap-Attribution in der Benutzeroberfläche muss erhalten bleiben. Vor einer Weitergabe der Kartendaten außerhalb der eigenen Installation sind die jeweils geltenden OpenStreetMap-/Geofabrik-Lizenz- und Nutzungsbedingungen zu prüfen.
