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
http://<host-ip>:8080 -> nginx -> /api/v1 -> api:8000
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
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
```

In a second terminal, install and start the frontend:

```powershell
Set-Location frontend
npm install
$env:GEOPHOTO_DEV_API_TARGET = "http://127.0.0.1:8088"
npm run dev
```

Vite listens on all host interfaces and serves the UI on port `5173`; from another LAN device use `http://<host-ip>:5173`. It proxies `/api/*` to the backend on the development host. Application code continues to use only relative `/api/v1` calls.

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


## Home-network access

Docker-published application ports use `GEOPHOTO_BIND_ADDRESS=0.0.0.0` by default. This makes the following endpoints reachable from other devices on the same LAN when their profiles are running:

- `8080/tcp` - main GeoPhotoConverter UI through nginx
- `8088/tcp` - direct FastAPI endpoint for diagnostics/development
- `5000/tcp` - DroneDB when the `dronedb` profile is enabled
- `3001/tcp` - Open WebUI when the `ai` profile is enabled
- `5173/tcp` - Vite development server when run locally

Redis is intentionally kept on the private Compose network and is not published to the LAN. Processing workers do not require inbound LAN ports.

On Windows, determine the host IPv4 address with:

```powershell
ipconfig
```

If Windows Defender Firewall blocks access, allow inbound TCP only on the ports you actually use and only for the **Private** network profile. Do not create router/NAT port forwards for these services unless a separate authentication and TLS design is added.
