# Offline map packs

GeoPhotoConverter can serve local vector maps to MapLibre without an internet connection.

## Default pack

Baden-Württemberg is the recommended default offline pack.

Install it from the repository root:

```bash
python scripts/maps/download_map_pack.py baden-wuerttemberg
```

Install the complete configured South Germany set:

```bash
python scripts/maps/download_map_pack.py south-germany
```

The downloader stores MBTiles under `data/maps/`. The large map databases are intentionally not committed to normal Git history.

## API

After the API container is running:

- `GET /api/v1/maps`
- `GET /api/v1/maps/{region}/tilejson.json`
- `GET /api/v1/maps/{region}/tiles/{z}/{x}/{y}.pbf`

The server converts MapLibre XYZ tile coordinates to the TMS row convention used by MBTiles.

## Source and licensing

Configured map packs use Geofabrik's Shortbread MBTiles downloads generated from OpenStreetMap data.

The UI must retain OpenStreetMap attribution. Review the upstream OpenStreetMap/Geofabrik licensing terms before redistributing map data outside this installation.
