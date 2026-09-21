# Development workflow

## Recommended modes

There are two supported development modes.

### 1. Full Docker stack

Use this when working on integration, uploads, networking, map tiles, or worker orchestration:

```powershell
docker compose up -d --build web api redis
```

The complete browser/API path is then:

```text
http://localhost:8080 -> nginx -> /api/v1 -> api:8000
```

This is the closest representation of the deployment topology.

### 2. Local frontend/backend with Redis in Docker

Use this for fast UI and API iteration.

Start Redis:

```powershell
docker compose up -d redis
```

Create and activate a Python virtual environment from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

Start the backend:

```powershell
Set-Location backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8088
```

In a second terminal, install and start the frontend:

```powershell
Set-Location frontend
npm install
$env:GEOPHOTO_DEV_API_TARGET = "http://127.0.0.1:8088"
npm run dev
```

Vite serves the UI on `http://127.0.0.1:5173` and proxies `/api/*` to the backend. Application code continues to use only relative `/api/v1` calls.

## VS Code layout

Repository settings exclude generated and high-churn directories such as `data`, `node_modules`, `dist`, and Python caches from search/watch operations. This prevents large imagery datasets from degrading editor performance.

The recommended extension set covers:

- Python/Pylance/debugpy
- Docker/Compose
- GitHub Actions

The frontend uses the workspace TypeScript installation under `frontend/node_modules` after `npm install`.

## Validation

Run the VS Code task `Check: Full stack` or execute the equivalent commands:

```powershell
python -m compileall backend/app workers
Set-Location frontend
npm run build
Set-Location ..
docker compose config --quiet
```

## Service profiles

The core development stack is `web + api + redis`.

Optional Compose profiles:

- `odm` - OpenDroneMap worker
- `micmac` - MicMac worker
- `dronedb` - DroneDB Registry
- `ai` - Open WebUI

Only enable the profiles needed for the current task to keep local resource usage predictable.
