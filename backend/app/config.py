from __future__ import annotations

import os
from pathlib import Path


def _default_data_root() -> Path:
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA")
        if base:
            return Path(base) / "GeoPhotoConverter" / "data"
        return Path.home() / "AppData" / "Local" / "GeoPhotoConverter" / "data"
    return Path("/data")


def _service_default(container_url: str, windows_url: str) -> str:
    return windows_url if os.name == "nt" else container_url


DATA_ROOT = Path(
    os.getenv("GEOPHOTO_DATA_ROOT") or _default_data_root()
).expanduser().resolve()
DATASETS_ROOT = DATA_ROOT / "datasets"
MAPS_ROOT = DATA_ROOT / "maps"
CACHE_ROOT = DATA_ROOT / "cache"
POINTCLOUD_CACHE_ROOT = CACHE_ROOT / "pointcloud"
DB_PATH = DATA_ROOT / "geophoto.db"
REDIS_URL = os.getenv(
    "GEOPHOTO_REDIS_URL",
    _service_default("redis://redis:6379/0", "redis://127.0.0.1:6379/0"),
)
DRONEDB_BASE_URL = os.getenv(
    "DRONEDB_BASE_URL",
    _service_default("http://dronedb:5000", "http://127.0.0.1:5000"),
)
DRONEDB_USERNAME = os.getenv("DRONEDB_USERNAME", "admin")
DRONEDB_PASSWORD = os.getenv("DRONEDB_PASSWORD", "password123")
DRONEDB_ORG = os.getenv("DRONEDB_ORG", "geophoto")
DRONEDB_PUBLIC_URL = os.getenv("DRONEDB_PUBLIC_URL", "").strip()
DRONEDB_PUBLIC_PORT = int(os.getenv("DRONEDB_PUBLIC_PORT", "5000"))
OPENWEBUI_INTERNAL_URL = os.getenv(
    "OPENWEBUI_INTERNAL_URL",
    _service_default("http://open-webui:8080", "http://127.0.0.1:3001"),
).rstrip("/")
OPENWEBUI_PUBLIC_URL = os.getenv("OPENWEBUI_PUBLIC_URL", "").strip()
OPENWEBUI_PUBLIC_PORT = int(os.getenv("OPENWEBUI_PUBLIC_PORT", "3001"))
PDAL_SERVICE_URL = os.getenv(
    "GEOPHOTO_PDAL_URL",
    _service_default("http://pdal-service:8090", "http://127.0.0.1:8090"),
).rstrip("/")
EXIFTOOL_BIN = os.getenv(
    "GEOPHOTO_EXIFTOOL_BIN",
    "exiftool.exe" if os.name == "nt" else "exiftool",
)
DCRAW_BIN = os.getenv(
    "GEOPHOTO_DCRAW_BIN",
    "dcraw_emu.exe" if os.name == "nt" else "dcraw_emu",
)
PDAL_TIMEOUT_SECONDS = max(
    5,
    int(os.getenv("GEOPHOTO_PDAL_TIMEOUT_SECONDS", "120")),
)
MAX_FILE_BYTES = int(os.getenv("GEOPHOTO_MAX_FILE_MB", "500")) * 1024 * 1024
MAX_DATASET_BYTES = int(os.getenv("GEOPHOTO_MAX_DATASET_GB", "50")) * 1024 * 1024 * 1024

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".dng",
    ".rjpeg",
}

ENGINE_NAMES = {"odm", "micmac", "gsplat", "thermal", "telesculptor"}
PROFILE_NAMES = {"preview", "standard", "high"}
WORKFLOW_NAMES = {"mapping", "reconstruction", "rgb", "multispectral", "thermal"}


def ensure_directories() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DATASETS_ROOT.mkdir(parents=True, exist_ok=True)
    MAPS_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    POINTCLOUD_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
