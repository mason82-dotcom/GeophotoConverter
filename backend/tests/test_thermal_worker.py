from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_thermal_worker(repo_root: Path):
    workers_root = repo_root / "workers"
    thermal_root = workers_root / "thermal"

    sys.path.insert(0, str(workers_root))
    try:
        thermal_core = types.ModuleType("thermal_core")
        thermal_core.__path__ = []
        sys.modules["thermal_core"] = thermal_core

        dji_sdk = types.ModuleType("thermal_core.dji_sdk")
        dji_sdk.DjiThermalSdk = object
        sys.modules["thermal_core.dji_sdk"] = dji_sdk

        processor = types.ModuleType("thermal_core.processor")
        processor.process_handoff = lambda *_args, **_kwargs: None
        sys.modules["thermal_core.processor"] = processor

        spec = importlib.util.spec_from_file_location(
            "geophoto_thermal_worker_test_module",
            thermal_root / "worker.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_collect_thermal_artifacts(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    module = _load_thermal_worker(repo_root)

    data_root = tmp_path / "data"
    result_dir = data_root / "jobs" / "job-1" / "thermal" / "results"
    result_dir.mkdir(parents=True)

    (result_dir / "temperature.tif").write_bytes(b"temp")
    (result_dir / "preview.png").write_bytes(b"preview")
    (result_dir / "thermal-summary.json").write_text("{}", encoding="utf-8")

    module.DATA_ROOT = data_root
    artifacts = module._collect_artifacts(result_dir)

    assert [item["type"] for item in artifacts] == [
        "thermal_preview",
        "thermal_summary",
        "thermal_temperature_tiff",
    ]
    assert all(item["relative_path"].startswith("jobs/job-1/") for item in artifacts)
