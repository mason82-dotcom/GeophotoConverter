# GeoPhotoConverter

GeoPhotoConverter ist eine lokal betriebene Arbeitsstation zum Importieren georeferenzierter Luftbilder, Prüfen von Metadaten, Kontrollieren der Kartenabdeckung und Starten photogrammetrischer Verarbeitungsaufträge.

## Architektur

Der Standard-Docker-Stack ist bewusst einfach aufgebaut:

```text
Browser
  |
  v
web (nginx + React/Vite-Build) :8080
  |
  +-- /api/v1/* --> api (FastAPI) :8000
                         |
                         +--> redis
                         +--> gemeinsames ./data
                         +--> optionale Verarbeitungs-Worker
```

Der Browser verwendet ausschließlich relative `/api/v1`-URLs. Im Produktivbetrieb leitet nginx diese Anfragen an den API-Container weiter. Bei lokaler Frontend-Entwicklung leitet Vite dieselben Pfade an den lokalen bzw. direkt erreichbaren API-Port weiter.

## Schnellstart

Lokale Umgebungsdatei anlegen:

```powershell
Copy-Item .env.example .env
```

Kern-Stack starten:

```powershell
docker compose up -d --build web api redis
```

Direkt auf dem Host erreichbar:

- UI: `http://localhost:8080`
- direkte API/Diagnose: `http://localhost:8088/api/v1/health`

Alle veröffentlichten Anwendungsports binden standardmäßig an `0.0.0.0`. Von einem anderen Gerät im vertrauenswürdigen Heimnetz `localhost` durch die IPv4-Adresse des GeoPhotoConverter-Hosts ersetzen, zum Beispiel:

- UI: `http://192.168.178.45:8080`
- API: `http://192.168.178.45:8088/api/v1/health`
- DroneDB-Profil: `http://192.168.178.45:5000`
- Open-WebUI-Profil: `http://192.168.178.45:3001`

Die genaue Host-Adresse lässt sich unter Windows mit `ipconfig` ermitteln. Diese Ports nicht per Router-Portweiterleitung ins öffentliche Internet freigeben; der aktuelle Stack ist für ein vertrauenswürdiges LAN ausgelegt und setzt nicht vor jeden Dienst eine eigene Authentifizierungsschicht.

Stack stoppen:

```powershell
docker compose down
```

## Optionale Dienste

Verarbeitungs- und Zusatzdienste werden über Compose-Profile aktiviert:

```powershell
docker compose --profile odm up -d
docker compose --profile odm-gpu up -d
docker compose --profile micmac up -d
docker compose --profile gsplat up -d
docker compose --profile thermal up -d
docker compose --profile dronedb up -d
docker compose --profile ai up -d
```

ODM, MicMac, gsplat und Thermal beziehen Aufträge aus Redis und verwenden dasselbe Datenverzeichnis wie die API. Der Thermal-Worker benötigt ein lokal bereitgestelltes DJI Thermal SDK unter dem in `.env` konfigurierten `DJI_TSDK_HOST_PATH`; das proprietäre SDK wird nicht mit dem Repository ausgeliefert. DroneDB und Open WebUI bleiben optional.

### NVIDIA CUDA

Für NVIDIA-GPUs gibt es zwei GPU-Pfade:

- `odm-gpu`: OpenDroneMap 3.6.2 GPU-Image (CUDA 12.9.1) mit CUDA-beschleunigter SIFT-Merkmalsextraktion.
- `gsplat`: CUDA 12.8.1 / PyTorch-CUDA für Gaussian Splatting sowie COLMAP 4.2.0 mit CUDA-SIFT für Feature Extraction und Matching.

Voraussetzung ist ein funktionierender NVIDIA-Treiber plus NVIDIA Container Toolkit.

```powershell
docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi
```

Für ODM genau eine Variante starten:

```powershell
# CPU
docker compose --profile odm up -d --build

# NVIDIA CUDA
docker compose --profile odm-gpu up -d --build
```

`odm` und `odm-gpu` konsumieren denselben Redis-Stream für ODM-Aufträge und dürfen deshalb nicht gleichzeitig als regulärer Betriebsmodus laufen.

Beim `gsplat`-Profil ist COLMAP-CUDA standardmäßig aktiviert. `GEOPHOTO_CUDA_DEVICE` wählt den NVIDIA-GPU-Index; Standard ist `0`.

## VS Code

Das Repository-Stammverzeichnis in VS Code öffnen und die empfohlenen Erweiterungen installieren.

Nützliche Aufgaben stehen unter **Terminal > Aufgabe ausführen** bereit:

- `Docker: Kern starten`
- `Docker: Kern stoppen`
- `Docker: Nur Redis`
- `Frontend: Installieren`
- `Frontend: Entwicklung`
- `Frontend: Bauen`
- `Backend: Installieren`
- `Backend: Entwicklung`
- `Prüfen: Gesamtsystem`

Für Python-Debugging einen Python-Interpreter mit den Abhängigkeiten aus `backend/requirements.txt` auswählen und **Ausführen und Debuggen > Backend: FastAPI (Debug)** verwenden.

Der empfohlene lokale Entwicklungsablauf ist in `docs/DEVELOPMENT.md` beschrieben.


## Offline-Karten

Für eine vollständig lokale Basiskarte kann zunächst Baden-Württemberg installiert werden:

```powershell
python scripts/maps/download_map_pack.py baden-wuerttemberg
```

Das komplette vorkonfigurierte Süddeutschland-Set:

```powershell
python scripts/maps/download_map_pack.py south-germany
```

Die MBTiles-Dateien werden unter `data/maps/` gespeichert und nicht in Git eingecheckt. Details stehen in `docs/OFFLINE_MAPS.md`.

## Reproduzierbarer Frontend-Build

Die direkten Frontend-Abhängigkeiten sind fest versioniert und `frontend/package-lock.json` ist Teil des Repositories.

Lokale Installation:

```powershell
Set-Location frontend
npm ci
```

CI und Frontend-Docker-Build verwenden ebenfalls `npm ci`.
