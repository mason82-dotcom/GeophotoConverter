[CmdletBinding()]
param(
    [ValidateSet("Install", "Start", "Stop", "Restart", "Status", "Verify", "Dev", "StopDev")]
    [string]$Action = "Status",

    [string[]]$Profiles = @(),

    [switch]$NoBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeBase = Join-Path $RepoRoot "compose.yaml"
$ComposeWindows = Join-Path $RepoRoot "compose.windows.yaml"
$EnvFile = Join-Path $RepoRoot ".env"
$EnvExample = Join-Path $RepoRoot ".env.example"
$DataRoot = Join-Path $RepoRoot "data"
$RuntimeRoot = Join-Path $RepoRoot ".runtime\windows"
$BackendPidFile = Join-Path $RuntimeRoot "backend.pid"
$FrontendPidFile = Join-Path $RuntimeRoot "frontend.pid"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

$Profiles = @(
    $Profiles |
        ForEach-Object { $_ -split "," } |
        ForEach-Object { $_.Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object -Unique
)

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-WindowsX64 {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw "Dieses Skript ist ausschließlich für Windows x64 vorgesehen."
    }

    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "GeoPhotoConverter benötigt ein 64-Bit-Windows."
    }

    $nativeArch = $env:PROCESSOR_ARCHITECTURE
    $wowArch = $env:PROCESSOR_ARCHITEW6432
    if ($nativeArch -ne "AMD64" -and $wowArch -ne "AMD64") {
        throw "Dieses Portierungsprofil unterstützt Windows x64/AMD64. Erkannt: $nativeArch."
    }
}

function Assert-Command([string]$Name, [string]$Hint) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "$Name wurde nicht gefunden. $Hint"
    }
    return $command
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @(),

        [Parameter(Mandatory = $false)]
        [string]$WorkingDirectory = $RepoRoot
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath ist mit Exitcode $LASTEXITCODE fehlgeschlagen."
        }
    }
    finally {
        Pop-Location
    }
}

function Compose-Arguments {
    param(
        [string[]]$SelectedProfiles = @(),
        [string[]]$Tail = @()
    )

    $args = @(
        "compose",
        "-f", $ComposeBase,
        "-f", $ComposeWindows
    )
    foreach ($profile in $SelectedProfiles) {
        if ([string]::IsNullOrWhiteSpace($profile)) {
            continue
        }
        $args += @("--profile", $profile)
    }
    $args += $Tail
    return $args
}

function Invoke-Compose {
    param(
        [string[]]$SelectedProfiles = @(),
        [string[]]$Tail = @()
    )

    $args = Compose-Arguments -SelectedProfiles $SelectedProfiles -Tail $Tail
    Invoke-Checked -FilePath "docker" -Arguments $args
}

function Assert-DockerDesktop {
    Assert-Command "docker" "Docker Desktop für Windows installieren und den WSL2/Linux-Container-Modus aktivieren." | Out-Null

    $dockerPlatform = (& docker info --format "{{.OSType}}/{{.Architecture}}" 2>$null | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($dockerPlatform)) {
        throw "Docker Desktop ist nicht erreichbar. Docker Desktop starten und erneut versuchen."
    }

    $dockerPlatform = $dockerPlatform.Trim().ToLowerInvariant()
    if ($dockerPlatform -ne "linux/amd64" -and $dockerPlatform -ne "linux/x86_64") {
        throw "Docker Desktop muss Linux/amd64-Container verwenden. Erkannt: $dockerPlatform."
    }
}

function Ensure-LocalLayout {
    New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

    if (-not (Test-Path $EnvFile)) {
        Copy-Item $EnvExample $EnvFile
        Write-Host ".env wurde aus .env.example angelegt."
    }
}

function Install-NativeCore {
    Write-Step "Windows-x64-Voraussetzungen prüfen"
    Assert-WindowsX64
    Assert-Command "py" "Python 3.12 x64 von python.org installieren." | Out-Null
    Assert-Command "node" "Node.js x64 installieren." | Out-Null
    Assert-Command "npm.cmd" "Node.js/npm x64 installieren." | Out-Null
    Assert-DockerDesktop
    Ensure-LocalLayout

    Write-Step "Python 3.12 x64 virtuelle Umgebung erstellen"
    Invoke-Checked -FilePath "py" -Arguments @("-3.12", "-m", "venv", ".venv")
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "-r", "backend\requirements.txt", "-r", "backend\requirements-dev.txt")

    Write-Step "Frontend-Abhängigkeiten installieren"
    Invoke-Checked -FilePath "npm.cmd" -Arguments @("ci", "--no-audit", "--no-fund") -WorkingDirectory (Join-Path $RepoRoot "frontend")

    Write-Step "Windows-Compose-Konfiguration prüfen"
    Invoke-Compose -Tail @("config", "--quiet")

    Write-Step "Native Zusatzwerkzeuge prüfen"
    $exiftool = Get-Command "exiftool.exe" -ErrorAction SilentlyContinue
    $dcraw = Get-Command "dcraw_emu.exe" -ErrorAction SilentlyContinue
    if ($exiftool) {
        Write-Host "ExifTool: $($exiftool.Source)" -ForegroundColor Green
    }
    else {
        Write-Warning "exiftool.exe fehlt im PATH. Docker-Betrieb ist vollständig; im nativen Dev-Modus sind Metadaten-Scans bis zur Installation eingeschränkt."
    }

    if ($dcraw) {
        Write-Host "LibRaw/dcraw_emu: $($dcraw.Source)" -ForegroundColor Green
    }
    else {
        Write-Warning "dcraw_emu.exe fehlt im PATH. Docker-Betrieb ist vollständig; DNG-Vorschauen im nativen Dev-Modus benötigen LibRaw."
    }

    Write-Host ""
    Write-Host "Windows-x64-Installation abgeschlossen." -ForegroundColor Green
    Write-Host "Start: .\scripts\windows\GeoPhotoConverter.ps1 -Action Start"
}

function Validate-Profiles {
    param([string[]]$SelectedProfiles)

    $cpuRaster = $SelectedProfiles -contains "raster-processing"
    $gpuRaster = $SelectedProfiles -contains "raster-processing-gpu"
    if ($cpuRaster -and $gpuRaster) {
        throw "raster-processing und raster-processing-gpu dürfen nicht gleichzeitig laufen; beide konsumieren denselben Redis-Stream."
    }
}

function Start-DockerStack {
    Assert-WindowsX64
    Assert-DockerDesktop
    Ensure-LocalLayout
    Validate-Profiles -SelectedProfiles $Profiles

    Write-Step "GeoPhotoConverter unter Docker Desktop starten"
    $tail = @("up", "-d")
    if (-not $NoBuild) {
        $tail += "--build"
    }
    Invoke-Compose -SelectedProfiles $Profiles -Tail $tail

    Write-Host ""
    Write-Host "UI:  http://127.0.0.1:8080" -ForegroundColor Green
    Write-Host "API: http://127.0.0.1:8088/api/v1/health" -ForegroundColor Green
    if ($Profiles.Count -gt 0) {
        Write-Host "Aktive Profile: $($Profiles -join ', ')"
    }
}

function Stop-DockerStack {
    Assert-WindowsX64
    if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
        return
    }
    Write-Step "Docker-Stack stoppen"
    Invoke-Compose -SelectedProfiles $Profiles -Tail @("down")
}

function Show-Status {
    Assert-WindowsX64
    Assert-DockerDesktop
    Write-Step "Docker-Status"
    Invoke-Compose -SelectedProfiles $Profiles -Tail @("ps")
}

function Set-NativeToolEnvironment {
    $exiftool = Get-Command "exiftool.exe" -ErrorAction SilentlyContinue
    if ($exiftool) {
        $env:GEOPHOTO_EXIFTOOL_BIN = $exiftool.Source
    }

    $dcraw = Get-Command "dcraw_emu.exe" -ErrorAction SilentlyContinue
    if ($dcraw) {
        $env:GEOPHOTO_DCRAW_BIN = $dcraw.Source
    }
}

function Start-DevMode {
    Assert-WindowsX64
    Assert-DockerDesktop
    Ensure-LocalLayout

    if (-not (Test-Path $VenvPython)) {
        throw ".venv fehlt. Zuerst -Action Install ausführen."
    }
    Assert-Command "npm.cmd" "Node.js/npm x64 installieren." | Out-Null

    foreach ($pidFile in @($BackendPidFile, $FrontendPidFile)) {
        if (Test-Path $pidFile) {
            $existingPid = [int](Get-Content $pidFile -Raw)
            if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
                throw "Ein nativer Dev-Prozess läuft bereits (PID $existingPid). Zuerst -Action StopDev ausführen."
            }
            Remove-Item $pidFile -Force
        }
    }

    Write-Step "Redis für nativen Windows-Core starten"
    Invoke-Compose -Tail @("up", "-d", "redis")

    if ($Profiles -contains "pdal") {
        Write-Step "PDAL-Sidecar für nativen Windows-Core starten"
        Invoke-Compose -SelectedProfiles @("pdal") -Tail @("up", "-d", "--build", "pdal-service")
    }

    $env:GEOPHOTO_DATA_ROOT = $DataRoot
    $env:GEOPHOTO_REDIS_URL = "redis://127.0.0.1:6379/0"
    $env:GEOPHOTO_PDAL_URL = "http://127.0.0.1:8090"
    $env:DRONEDB_BASE_URL = "http://127.0.0.1:5000"
    $env:OPENWEBUI_INTERNAL_URL = "http://127.0.0.1:3001"
    $env:GEOPHOTO_DEV_API_TARGET = "http://127.0.0.1:8088"
    Set-NativeToolEnvironment

    Write-Step "FastAPI nativ unter Windows x64 starten"
    $backend = Start-Process -FilePath $VenvPython -ArgumentList @("-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8088") -WorkingDirectory (Join-Path $RepoRoot "backend") -PassThru
    Set-Content -Path $BackendPidFile -Value $backend.Id -Encoding Ascii

    Write-Step "Vite nativ unter Windows x64 starten"
    $frontend = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev") -WorkingDirectory (Join-Path $RepoRoot "frontend") -PassThru
    Set-Content -Path $FrontendPidFile -Value $frontend.Id -Encoding Ascii

    Write-Host ""
    Write-Host "Native Windows-Entwicklung läuft." -ForegroundColor Green
    Write-Host "UI:  http://127.0.0.1:5173"
    Write-Host "API: http://127.0.0.1:8088/api/v1/health"
}

function Stop-DevMode {
    Assert-WindowsX64
    Write-Step "Native Windows-Dev-Prozesse stoppen"

    foreach ($pidFile in @($BackendPidFile, $FrontendPidFile)) {
        if (-not (Test-Path $pidFile)) {
            continue
        }

        $processId = [int](Get-Content $pidFile -Raw)
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $processId -Force
        }
        Remove-Item $pidFile -Force
    }

    if (Get-Command "docker" -ErrorAction SilentlyContinue) {
        try {
            Invoke-Compose -Tail @("stop", "redis")
        }
        catch {
            Write-Warning $_.Exception.Message
        }
    }
}

function Verify-WindowsPort {
    Assert-WindowsX64
    Ensure-LocalLayout

    if (-not (Test-Path $VenvPython)) {
        throw ".venv fehlt. Zuerst -Action Install ausführen."
    }

    Write-Step "Python-Architektur und Backend prüfen"
    Invoke-Checked -FilePath $VenvPython -Arguments @("-c", "import platform,sys; assert sys.maxsize > 2**32; assert platform.machine().lower() in ('amd64','x86_64'); print(platform.platform())")
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "compileall", "backend\app", "workers")

    $oldPythonPath = $env:PYTHONPATH
    $oldDataRoot = $env:GEOPHOTO_DATA_ROOT
    try {
        $env:PYTHONPATH = (Join-Path $RepoRoot "backend")
        $env:GEOPHOTO_DATA_ROOT = $DataRoot
        Invoke-Checked -FilePath $VenvPython -Arguments @("-c", "from app.main import app; from app.config import DATA_ROOT; assert app.version; print(DATA_ROOT)")
        Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pytest", "backend\tests", "-q")
    }
    finally {
        $env:PYTHONPATH = $oldPythonPath
        $env:GEOPHOTO_DATA_ROOT = $oldDataRoot
    }

    Write-Step "Frontend unter Windows x64 prüfen"
    Invoke-Checked -FilePath "npm.cmd" -Arguments @("ci", "--no-audit", "--no-fund") -WorkingDirectory (Join-Path $RepoRoot "frontend")
    Invoke-Checked -FilePath "npm.cmd" -Arguments @("run", "typecheck") -WorkingDirectory (Join-Path $RepoRoot "frontend")
    Invoke-Checked -FilePath "npm.cmd" -Arguments @("run", "build") -WorkingDirectory (Join-Path $RepoRoot "frontend")

    Write-Step "Windows-Docker-Topologie prüfen"
    Assert-DockerDesktop
    Invoke-Compose -Tail @("config", "--quiet")

    Write-Host ""
    Write-Host "Windows-x64-Portprüfung erfolgreich." -ForegroundColor Green
}

Assert-WindowsX64

switch ($Action) {
    "Install" { Install-NativeCore }
    "Start" { Start-DockerStack }
    "Stop" { Stop-DockerStack }
    "Restart" {
        Stop-DockerStack
        Start-DockerStack
    }
    "Status" { Show-Status }
    "Verify" { Verify-WindowsPort }
    "Dev" { Start-DevMode }
    "StopDev" { Stop-DevMode }
}
