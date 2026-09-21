# GeoPhotoConverter API Contract v0.1

Base URL: `/api/v1`

## Health

### GET /health
Returns service status.

## Datasets

### GET /datasets
List imported datasets.

### POST /datasets
Create a dataset.
Body:
```json
{"name":"Survey 2026-09-21","description":"optional"}
```

### GET /datasets/{dataset_id}
Dataset details including image count, geotag coverage and processing readiness. The response also exposes backend-authoritative `platform`, `duplicate_count`, and `processing_readiness` summary fields alongside the full `qa` object.

### POST /datasets/{dataset_id}/files
Multipart upload. Field name: `files`.
Optional form field: `relative_paths` as JSON array preserving browser folder paths.

Uploads are streamed to a temporary file and atomically moved into place after validation. The backend calculates SHA-256 for each image, rejects duplicate content within the same dataset, and enforces configurable per-file and per-dataset size limits.

### POST /datasets/{dataset_id}/scan
Analyze uploaded imagery and extract EXIF/XMP/GPS metadata.

### GET /datasets/{dataset_id}/qa
Returns dataset QA including geotag coverage, platform/media classification, camera models, altitude ranges, capture period, warnings and per-engine readiness.

### GET /datasets/{dataset_id}/geojson
Returns geotagged image capture positions as a GeoJSON FeatureCollection for MapLibre.

### GET /datasets/{dataset_id}/files/{file_id}/preview?size=960
Returns a browser-displayable JPEG preview with EXIF orientation applied. `size` is the maximum preview dimension (128–2048 px). Formats unsupported by Pillow return HTTP 415 instead of exposing filesystem paths.

## Jobs

### GET /jobs
List processing jobs.

### POST /jobs
Create a processing job.
```json
{
  "dataset_id":"...",
  "engine":"odm",
  "profile":"preview"
}
```
Allowed engines: `odm`, `micmac`, `gsplat`, `telesculptor`.
Allowed profiles: `preview`, `standard`, `high`.

### GET /jobs/{job_id}
Returns status, progress, phase and artifact summary. Each artifact includes a relative `download_url`.

### GET /jobs/{job_id}/logs?tail=200
Returns the last 1–5000 worker log lines. If processing has not produced a log yet, `available` is false.

### GET /jobs/{job_id}/artifacts/{artifact_index}
Streams one job artifact. Clients should use the `download_url` supplied by the job response instead of constructing paths themselves.

### POST /jobs/{job_id}/cancel
Request cancellation.

## Services

### GET /services
Returns availability/status for ODM, MicMac, gsplat, DroneDB and Open WebUI.

## Frontend contract

The frontend must not hardcode backend hostnames. Use relative `/api/v1` calls.

Required UI states:
- loading
- empty
- error
- uploading with per-file progress
- processing
- completed
- cancelled

The frontend owns no processing logic. It submits jobs and renders backend state.


## Offline maps

### GET /maps
Lists configured regional offline map packs and reports whether each MBTiles file is installed.

### GET /maps/{region_id}/tilejson.json
MapLibre-compatible TileJSON for an installed regional map pack.

### GET /maps/{region_id}/tiles/{z}/{x}/{y}.pbf
Returns an offline Shortbread vector tile from the local MBTiles database.

Configured initial regions:
- `baden-wuerttemberg` (default)
- `bayern`
- `hessen`
- `rheinland-pfalz`
- `saarland`

Frontend map rendering must retain OpenStreetMap attribution.
