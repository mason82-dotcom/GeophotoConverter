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
Dataset details including image count, geotag coverage and processing readiness.

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

## Jobs

### GET /jobs
List processing jobs.

### POST /jobs
Create a processing job.
```json
{
  "dataset_id":"...",
  "engine":"odm",
  "profile":"preview",
  "workflow":"rgb",
  "options": {}
}
```
Allowed engines: `odm`, `micmac`, `gsplat`, `telesculptor`.
Allowed profiles: `preview`, `standard`, `high`.

Allowed workflows:
- `rgb` — normal RGB/WIDE photogrammetry
- `multispectral` — ODM-only M3M processing with complete RGB + G + R + RE + NIR capture groups

Example M3M job:
```json
{
  "dataset_id":"...",
  "engine":"odm",
  "profile":"standard",
  "workflow":"multispectral"
}
```

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


## Processing catalog

### GET /processing/profiles
Returns the backend-owned engine/workflow/profile catalog. The frontend should use this endpoint instead of hardcoding engine capabilities.

It describes:
- ODM RGB and M3M multispectral workflows
- MicMac RGB reconstruction
- gsplat GPU requirements and training-step profiles
- DJI M3T/M4T thermal requirements and output semantics
- TeleSculptor experimental/manual status

Thermal results explicitly report that temperature rasters remain in sensor-pixel space and that WIDE/THERMAL images are not yet coregistered.

### Thermal job example
```json
{
  "dataset_id": "...",
  "engine": "thermal",
  "profile": "standard",
  "workflow": "thermal",
  "options": {
    "emissivity": 0.95,
    "distance_m": 10.0,
    "humidity_pct": 65.0,
    "reflection_c": 20.0,
    "ambient_temp_c": 20.0,
    "hotspot_delta_c": 10.0,
    "hotspot_min_pixels": 4
  }
}
```

The optional thermal worker requires a locally supplied DJI Thermal SDK. No DJI SDK binaries are included in this repository.


### Job options

Job options are validated and stored with the job for reproducibility. Arbitrary engine CLI arguments are never accepted.

For the current thermal workflow the supported options are:
- `emissivity`: optional, > 0 and <= 1
- `distance_m`: optional, > 0
- `humidity_pct`: optional, 0–100
- `reflection_c`: optional finite Celsius value
- `ambient_temp_c`: optional finite Celsius value
- `hotspot_delta_c`: positive Celsius delta, default 10
- `hotspot_min_pixels`: integer >= 1, default 4

Measurement overrides are additionally validated against the ranges reported by DJI DIRP for the specific R-JPEG. If DIRP cannot read/set explicitly requested overrides, thermal processing fails closed instead of claiming the override was applied.

Non-thermal engines currently reject non-empty `options` objects until their own typed option schemas are added.
