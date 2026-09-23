from __future__ import annotations

import os
from pathlib import Path


DATA_ROOT = Path(os.getenv("GEOPHOTO_DATA_ROOT", "/data")).resolve()
DATASETS_ROOT = DATA_ROOT / "datasets"
MAPS_ROOT = DATA_ROOT / "maps"
CACHE_ROOT = DATA_ROOT / "cache"
POINTCLOUD_CACHE_ROOT = CACHE_ROOT / "pointcloud"
DB_PATH = DATA_ROOT / "geophoto.db"
REDIS_URL = os.getenv("GEOPHOTO_REDIS_URL", "redis://redis:6379/0")
DRONEDB_BASE_URL = os.getenv("DRONEDB_BASE_URL", "http://dronedb:5000")
DRONEDB_USERNAME = os.getenv("DRONEDB_USERNAME", "admin")
DRONEDB_PASSWORD = os.getenv("DRONEDB_PASSWORD", "password123")
DRONEDB_ORG = os.getenv("DRONEDB_ORG", "geophoto")
DRONEDB_PUBLIC_URL = os.getenv("DRONEDB_PUBLIC_URL", "").strip()
DRONEDB_PUBLIC_PORT = int(os.getenv("DRONEDB_PUBLIC_PORT", "5000"))
OPENWEBUI_INTERNAL_URL = os.getenv(
    "OPENWEBUI_INTERNAL_URL",
    "http://open-webui:8080",
).rstrip("/")
OPENWEBUI_PUBLIC_URL = os.getenv("OPENWEBUI_PUBLIC_URL", "").strip()
OPENWEBUI_PUBLIC_PORT = int(os.getenv("OPENWEBUI_PUBLIC_PORT", "3001"))
PDAL_SERVICE_URL = os.getenv(
    "GEOPHOTO_PDAL_URL",
    "http://pdal-service:8090",
).rstrip("/")
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
