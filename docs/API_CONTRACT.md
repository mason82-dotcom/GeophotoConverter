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

### POST /datasets/{dataset_id}/scan
Analyze uploaded imagery and extract EXIF/XMP/GPS metadata.

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
Returns status, progress, phase, logs tail and artifact summary.

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
