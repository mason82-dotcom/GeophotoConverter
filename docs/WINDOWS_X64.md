# Windows x64

GeoPhotoConverter unterstützt Windows x64 in zwei klar getrennten Betriebsarten.

## Unterstützte Architektur

### Produktiv / vollständiger Funktionsumfang

Der Windows-Host läuft nativ auf AMD64/x64. Docker Desktop verwendet das WSL2-/Linux-Container-Backend. API, Weboberfläche und alle Photogrammetrie-Worker werden dabei als explizite linux/amd64-Container ausgeführt.

Das ist für folgende Toolchains bewusst so vorgesehen:

- OpenDroneMap
- MicMac
- PDAL
- gsplat/CUDA
- DJI Thermal SDK
- Raster-Processing mit optionalem CuPy/CUDA

Diese Komponenten werden nicht als native Windows-Binaries nachgebaut. Ihre Linux-Laufzeit bleibt reproduzierbar und wird auf Windows durch Docker Desktop bereitgestellt.

### Native Windows-Entwicklung

FastAPI und React/Vite können direkt unter Windows x64 laufen. Redis und optionale Linux-Sidecars bleiben in Docker Desktop. Dadurch ist der Edit/Test-Zyklus schnell, während die Produktions-Toolchains unverändert bleiben.

## Voraussetzungen

Für den vollständigen Docker-Betrieb:

- Windows 10/11 x64
- aktivierte Hardware-Virtualisierung
- Docker Desktop mit WSL2-Backend und Linux-Containern
- ausreichend freier Speicher im Docker-/WSL-Datenträger

Zusätzlich für native Entwicklung:

- Python 3.12 x64 über py -3.12
- Node.js 24 x64 mit npm
- optional exiftool.exe im PATH für native Metadaten-Scans
- optional dcraw_emu.exe im PATH für native DNG-Vorschauen

Für NVIDIA-Profile zusätzlich:

- aktueller NVIDIA-Windows-Treiber mit WSL2-CUDA-Unterstützung
- funktionierender GPU-Passthrough in Docker Desktop

## Installation

PowerShell im Repository-Stamm öffnen:

    Set-ExecutionPolicy -Scope Process Bypass
    .\scripts\windows\GeoPhotoConverter.ps1 -Action Install

Der Installer:

1. prüft Windows x64,
2. prüft Docker Desktop,
3. legt .env und data\ an,
4. erstellt .venv mit Python 3.12 x64,
5. installiert Backend- und Testabhängigkeiten,
6. führt npm ci aus,
7. validiert den Windows-Compose-Override,
8. prüft optionale native ExifTool-/LibRaw-Binaries.

Alternativ kann der Root-Launcher verwendet werden:

    GeoPhotoConverter.cmd -Action Install

## Vollständiger Docker-Betrieb

Kernsystem:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Start

Mit ODM:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Start -Profiles odm

M3M/Multispektral auf CPU:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Start -Profiles odm,raster-processing

M3M/Multispektral auf NVIDIA CUDA:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Start -Profiles odm,raster-processing-gpu

Punktwolken-QA und Derived-PDAL:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Start -Profiles pdal,pdal-processing

Gaussian Splatting:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Start -Profiles gsplat

Thermal:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Start -Profiles thermal

Vor Thermal muss DJI_TSDK_HOST_PATH in .env auf das lokal vorhandene Linux-x86-64-DJI-TSDK zeigen.

raster-processing und raster-processing-gpu dürfen nicht gleichzeitig gestartet werden, weil beide denselben Redis-Stream konsumieren. Das Windows-Verwaltungsskript blockiert diese Kombination.

## Native Windows-Entwicklung

Zuerst installieren:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Install

Dann:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Dev

Dadurch werden gestartet:

- Redis in Docker auf 127.0.0.1:6379
- FastAPI nativ auf 0.0.0.0:8088
- Vite nativ auf 0.0.0.0:5173

Optional mit PDAL-Sidecar:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Dev -Profiles pdal

Stoppen:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action StopDev

## Status und Prüfung

Docker-Status:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Status

Kompletter Windows-Porttest:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Verify

Der Verify-Lauf prüft:

- Python-x64-Architektur
- Python-Compile
- FastAPI-Import
- Backend-Pytest
- Frontend npm ci
- TypeScript-Typecheck
- Frontend-Build
- Docker-Desktop-Erreichbarkeit
- kombinierte compose.yaml + compose.windows.yaml-Konfiguration

Zusätzlich läuft dieselbe native Kernplattform in GitHub Actions auf windows-latest.

## Datenpfade

Im Docker-Betrieb bleibt die kanonische Container-Sicht /data; auf Windows wird standardmäßig .\data dorthin eingebunden.

Im nativen Backend ohne gesetztes GEOPHOTO_DATA_ROOT lautet der Windows-Standard:

    %LOCALAPPDATA%\GeoPhotoConverter\data

Der mitgelieferte Dev-Launcher setzt GEOPHOTO_DATA_ROOT absichtlich auf .\data, damit native API und Container-Worker dieselben Daten sehen.

## Native externe Werkzeuge

Für Docker müssen ExifTool und LibRaw nicht auf Windows installiert sein; sie sind Bestandteil des API-Containers.

Für den nativen Dev-Modus können die Pfade explizit gesetzt werden:

    $env:GEOPHOTO_EXIFTOOL_BIN = "C:\Tools\ExifTool\exiftool.exe"
    $env:GEOPHOTO_DCRAW_BIN = "C:\Tools\LibRaw\dcraw_emu.exe"

Ohne exiftool.exe sind native Metadaten-Scans nicht vollständig. Ohne dcraw_emu.exe sind native DNG-Vorschauen nicht verfügbar. JPEG/TIFF-Vorschauen und die übrige API bleiben davon getrennt.

## Windows-spezifische Service-Endpunkte

Der Windows-Compose-Override veröffentlicht nur die für den Hybridbetrieb notwendigen internen Dienste:

- Redis: 127.0.0.1:6379
- PDAL-Sidecar: 127.0.0.1:8090

Sie werden nicht an das LAN gebunden.

Die Anwendungsports bleiben:

- UI Docker: 8080
- API: 8088
- Vite Dev: 5173
- DroneDB optional: 5000
- Open WebUI optional: 3001

## Beenden

Docker-Stack:

    .\scripts\windows\GeoPhotoConverter.ps1 -Action Stop

Ein Neustart ist mit -Action Restart möglich.
