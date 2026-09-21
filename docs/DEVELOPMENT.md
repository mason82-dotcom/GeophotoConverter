# Entwicklungsablauf

## Empfohlene Betriebsarten

Es werden zwei Entwicklungsarten unterstützt.

### 1. Vollständiger Docker-Stack

Diese Variante eignet sich für Integration, Uploads, Netzwerk, Kartenkacheln und Worker-Orchestrierung:

```powershell
docker compose up -d --build web api redis
```

Der vollständige Browser-/API-Pfad lautet dann:

```text
http://<host-ip>:8080 -> nginx -> /api/v1 -> api:8000
```

Das entspricht der späteren Bereitstellungstopologie am besten.

### 2. Lokales Frontend/Backend mit Redis in Docker

Für schnelle UI- und API-Entwicklung.

Redis starten:

```powershell
docker compose up -d redis
```

Virtuelle Python-Umgebung im Repository-Stammverzeichnis anlegen und aktivieren:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

Backend starten:

```powershell
Set-Location backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
```

In einem zweiten Terminal das Frontend installieren und starten:

```powershell
Set-Location frontend
npm install
$env:GEOPHOTO_DEV_API_TARGET = "http://127.0.0.1:8088"
npm run dev
```

Vite lauscht auf allen Host-Schnittstellen und stellt die UI auf Port `5173` bereit. Von einem anderen LAN-Gerät wird `http://<host-ip>:5173` verwendet. Vite leitet `/api/*` an das Backend auf dem Entwicklungsrechner weiter. Der Anwendungscode verwendet weiterhin ausschließlich relative `/api/v1`-Aufrufe.

## VS-Code-Konfiguration

Die Repository-Einstellungen schließen erzeugte und stark veränderliche Verzeichnisse wie `data`, `node_modules`, `dist` und Python-Caches von Suche und Dateiüberwachung aus. Dadurch beeinträchtigen große Bilddatensätze die Editor-Leistung nicht unnötig.

Empfohlene Erweiterungen:

- Python/Pylance/debugpy
- Docker/Compose
- GitHub Actions

Nach `npm install` verwendet das Frontend die TypeScript-Installation aus `frontend/node_modules`.

## Prüfung

Die VS-Code-Aufgabe `Prüfen: Gesamtsystem` ausführen oder die entsprechenden Befehle verwenden:

```powershell
python -m compileall backend/app workers
Set-Location frontend
npm run build
Set-Location ..
docker compose config --quiet
```

## Dienstprofile

Der Kern-Entwicklungsstack besteht aus `web + api + redis`.

Optionale Compose-Profile:

- `odm` – OpenDroneMap-Worker
- `micmac` – MicMac-Worker
- `gsplat` – GPU-Worker für Gaussian Splatting
- `dronedb` – DroneDB Registry
- `ai` – Open WebUI

Nur die für die aktuelle Aufgabe benötigten Profile aktivieren, damit der lokale Ressourcenverbrauch kontrollierbar bleibt.

## Zugriff im Heimnetz

Von Docker veröffentlichte Anwendungsports verwenden standardmäßig `GEOPHOTO_BIND_ADDRESS=0.0.0.0`. Dadurch sind bei laufenden Profilen folgende Endpunkte von anderen Geräten im selben LAN erreichbar:

- `8080/tcp` – Hauptoberfläche von GeoPhotoConverter über nginx
- `8088/tcp` – direkte FastAPI-Schnittstelle für Diagnose/Entwicklung
- `5000/tcp` – DroneDB bei aktiviertem Profil `dronedb`
- `3001/tcp` – Open WebUI bei aktiviertem Profil `ai`
- `5173/tcp` – lokaler Vite-Entwicklungsserver

Redis bleibt bewusst im privaten Compose-Netz und wird nicht ins LAN veröffentlicht. Verarbeitungs-Worker benötigen keine eingehenden LAN-Ports.

Unter Windows lässt sich die IPv4-Adresse des Hosts mit folgendem Befehl ermitteln:

```powershell
ipconfig
```

Falls die Windows Defender Firewall den Zugriff blockiert, eingehendes TCP nur für tatsächlich benötigte Ports und ausschließlich für das **private** Netzwerkprofil freigeben. Keine Router-/NAT-Portweiterleitungen einrichten, solange keine separate Authentifizierungs- und TLS-Lösung ergänzt wurde.
