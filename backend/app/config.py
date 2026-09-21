from __future__ import annotations

import os
from pathlib import Path


DATA_ROOT = Path(os.getenv("GEOPHOTO_DATA_ROOT", "/data")).resolve()
DATASETS_ROOT = DATA_ROOT / "datasets"
MAPS_ROOT = DATA_ROOT / "maps"
DB_PATH = DATA_ROOT / "geophoto.db"
REDIS_URL = os.getenv("GEOPHOTO_REDIS_URL", "redis://redis:6379/0")
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

ENGINE_NAMES = {"odm", "micmac", "gsplat", "telesculptor"}
PROFILE_NAMES = {"preview", "standard", "high"}
WORKFLOW_NAMES = {"rgb", "multispectral"}


def ensure_directories() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DATASETS_ROOT.mkdir(parents=True, exist_ok=True)
    MAPS_ROOT.mkdir(parents=True, exist_ok=True)
