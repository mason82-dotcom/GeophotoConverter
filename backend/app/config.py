from __future__ import annotations

import os
from pathlib import Path


DATA_ROOT = Path(os.getenv("GEOPHOTO_DATA_ROOT", "/data")).resolve()
DATASETS_ROOT = DATA_ROOT / "datasets"
DB_PATH = DATA_ROOT / "geophoto.db"
REDIS_URL = os.getenv("GEOPHOTO_REDIS_URL", "redis://redis:6379/0")

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


def ensure_directories() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DATASETS_ROOT.mkdir(parents=True, exist_ok=True)
