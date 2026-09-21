# GeoPhotoConverter

GeoPhotoConverter is a local-first workstation for importing geotagged aerial imagery, validating metadata, reviewing map coverage, and dispatching photogrammetry jobs.

## Architecture

The default Docker stack is intentionally simple:

```text
Browser
  |
  v
web (nginx + React/Vite build) :8080
  |
  +-- /api/v1/* --> api (FastAPI) :8000
                         |
                         +--> redis
                         +--> shared ./data
                         +--> optional processing workers
```

The browser only uses relative `/api/v1` URLs. In production nginx proxies those requests to the API container. During local frontend development Vite proxies the same paths to the local/direct API port.

## Quick start

Create a local environment file:

```powershell
Copy-Item .env.example .env
```

Start the core stack:

```powershell
docker compose up -d --build web api redis
```

Open on the host itself:

- UI: `http://localhost:8080`
- direct API/diagnostics: `http://localhost:8088/api/v1/health`

All published application ports bind to `0.0.0.0` by default. From another device in the same trusted home network, replace `localhost` with the IPv4 address of the GeoPhotoConverter host, for example:

- UI: `http://192.168.178.45:8080`
- API: `http://192.168.178.45:8088/api/v1/health`
- DroneDB profile: `http://192.168.178.45:5000`
- Open WebUI profile: `http://192.168.178.45:3001`

The exact host address can be found on Windows with `ipconfig`. Do not forward these ports from the router to the public Internet; the current stack is designed for a trusted LAN and does not add an authentication layer in front of every service.

Stop the stack with:

```powershell
docker compose down
```

## Optional services

Processing and auxiliary services are Compose profiles:

```powershell
docker compose --profile odm up -d
docker compose --profile micmac up -d
docker compose --profile dronedb up -d
docker compose --profile ai up -d
```

ODM and MicMac consume jobs from Redis and share the same data directory as the API. DroneDB and Open WebUI remain optional.

## VS Code

Open the repository root in VS Code and install the recommended extensions when prompted.

Useful tasks are available through **Terminal > Run Task**:

- `Docker: Core up`
- `Docker: Core down`
- `Docker: Redis only`
- `Frontend: Install`
- `Frontend: Dev`
- `Frontend: Build`
- `Backend: Install`
- `Backend: Dev`
- `Check: Full stack`

For Python debugging, select a Python interpreter containing `backend/requirements.txt` and use **Run and Debug > Backend: FastAPI (debug)**.

See `docs/DEVELOPMENT.md` for the recommended local development workflow.
