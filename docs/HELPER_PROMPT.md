# Helper task — GeoPhotoConverter frontend

You are the frontend implementation agent for `mason82-dotcom/GeophotoConverter`.

Work only on branch:
`agent/frontend-ui`

Do not modify backend, workers, Docker processing engines, or database code. Your ownership is:
- `frontend/**`
- `docs/DESIGN.md`
- frontend-specific documentation only

The other agent owns:
- `backend/**`
- `workers/**`
- `infra/**`
- `compose.yaml`
- processing engine integration
- metadata extraction
- dataset persistence
- DroneDB/Open WebUI integration

## Product

Build a modern professional operator UI called **GeoPhoto Converter** for local aerial imagery processing.

Primary input:
- locally selected geotagged drone images
- browser file picker and folder picker
- preserve relative paths when possible

Primary workflow:
1. Import
2. Validate metadata / GPS / camera data
3. Review dataset
4. Choose processing engine
5. Run job
6. Inspect results
7. Publish/export to DroneDB

Processing engines shown in the UI:
- OpenDroneMap (ODM) — primary mapping pipeline
- MicMac — alternative photogrammetry
- gsplat — Gaussian Splatting, GPU-oriented
- TeleSculptor — experimental/legacy comparison engine

Optional service:
- Open WebUI as AI assistant, never as the primary application UI

## Design direction

Create an application UI, not a marketing website.

Visual direction:
- professional geospatial / survey workstation
- dark slate/navy base
- restrained accent usage
- high information density without looking cluttered
- crisp panels, maps, status indicators and data tables
- WCAG 2.2 AA
- responsive desktop-first layout

Suggested navigation:
- Overview
- Import
- Datasets
- Map
- Processing
- Results
- DroneDB
- Assistant
- Settings

Signature UI idea:
Use a horizontal “flightline quality strip” showing image sequence, geotag coverage, warnings and processing readiness.

## Import UX requirements

Implement:
- drag and drop
- explicit “Select files” button
- explicit “Select folder” button using webkitdirectory where supported
- fallback to multi-file picker
- accepted formats displayed before selection
- queue table with file name, relative path, size, type, status
- per-file error state
- retry/cancel controls
- overall upload progress
- no browser alert()/confirm()

Supported imagery should include at least:
- JPG/JPEG
- TIFF/TIF
- DNG
- R-JPEG where browser file handling permits

## Screens

### Overview
Show service health, recent datasets/jobs, storage summary and quick import action.

### Import
Dataset name + folder/file upload + queue + progress.

### Dataset detail
Summary metrics:
- image count
- geotagged %
- camera model(s)
- altitude range
- duplicate/warning count
- detected platform if available
- processing readiness

Include map placeholder/component interface for image positions.

### Processing
Engine cards for ODM, MicMac, gsplat, TeleSculptor.
Each card must explain capability and hardware implications briefly.
Profiles: Preview / Standard / High.

### Job detail
Progress bar, current phase, logs tail, elapsed time, cancel action and resulting artifacts.

### Results
Artifact browser for orthophoto, DSM/DTM, point cloud, mesh, Gaussian splat PLY/checkpoint and downloadable outputs.

### DroneDB
Publish/export panel with connection status.

### Assistant
Optional Open WebUI launch/integration surface.

## API

Use relative base path:
`/api/v1`

Assume endpoints:
- GET /health
- GET /datasets
- POST /datasets
- GET /datasets/{id}
- POST /datasets/{id}/files
- POST /datasets/{id}/scan
- GET /jobs
- POST /jobs
- GET /jobs/{id}
- POST /jobs/{id}/cancel
- GET /services

If backend responses are not yet available, build a typed API client and an explicit mock adapter. Keep mocks isolated so they can be removed without changing components.

## Technical direction

Use:
- React
- TypeScript
- Vite
- MapLibre GL JS for map surface
- Lucide icons if adding an icon library

Create:
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`
- `frontend/src/**`
- `docs/DESIGN.md`

Avoid heavyweight UI frameworks unless clearly justified. Prefer reusable local components.

## Branch discipline

Commit in small logical commits. Suggested sequence:
1. chore: scaffold frontend
2. feat: add application shell and navigation
3. feat: add import workflow
4. feat: add datasets and processing screens
5. feat: add results and service views
6. docs: document frontend design system

Do not merge branches. Stop after the frontend branch is complete and report:
- commit SHAs
- files changed
- build/test result
- unresolved integration points
