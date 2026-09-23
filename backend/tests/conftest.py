from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_ROOT = Path(tempfile.gettempdir()) / "geophoto-converter-tests"
os.environ["GEOPHOTO_DATA_ROOT"] = str(TEST_ROOT)
os.environ["GEOPHOTO_REDIS_URL"] = "redis://127.0.0.1:6399/15"
os.environ["GEOPHOTO_MAX_FILE_MB"] = "2"
os.environ["GEOPHOTO_MAX_DATASET_GB"] = "1"

from app.config import DATA_ROOT, DATASETS_ROOT, MAPS_ROOT
from app.main import app
from app.storage import store


@pytest.fixture(autouse=True)
def clean_state():
    with store.connect() as conn:
        conn.execute("DELETE FROM artifact_jobs")
        conn.execute("DELETE FROM jobs")
        conn.execute("DELETE FROM files")
        conn.execute("DELETE FROM datasets")

    shutil.rmtree(DATASETS_ROOT, ignore_errors=True)
    shutil.rmtree(DATA_ROOT / "jobs", ignore_errors=True)
    shutil.rmtree(MAPS_ROOT, ignore_errors=True)
    DATASETS_ROOT.mkdir(parents=True, exist_ok=True)
    MAPS_ROOT.mkdir(parents=True, exist_ok=True)

    yield


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)
