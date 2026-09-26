from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_accelerator_state_reports_nvidia_gpu(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    workers_root = repo_root / "workers"
    sys.path.insert(0, str(workers_root))
    try:
        runtime = _load_module(
            "geophoto_cuda_runtime_test_module",
            workers_root / "common" / "runtime.py",
        )
    finally:
        sys.path.pop(0)

    monkeypatch.setattr(runtime, "ACCELERATOR", "nvidia-cuda")
    monkeypatch.setattr(runtime, "CUDA_REQUIRED", True)
    monkeypatch.setattr(runtime, "CUDA_PROBE", True)
    monkeypatch.setattr(runtime, "CUDA_VERSION", "12.9.1")
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="NVIDIA RTX Test, 580.01, 12288\n",
            stderr="",
        ),
    )

    state = runtime._accelerator_state()

    assert state["accelerator"] == "nvidia-cuda"
    assert state["cuda_required"] is True
    assert state["cuda_probe"] == "ok"
    assert state["cuda_version"] == "12.9.1"
    assert state["cuda_device"] == "NVIDIA RTX Test"
    assert state["cuda_driver"] == "580.01"
    assert state["cuda_memory_mb"] == 12288
    assert state["cuda_device_count"] == 1


def test_accelerator_state_degrades_without_nvidia_smi(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    workers_root = repo_root / "workers"
    sys.path.insert(0, str(workers_root))
    try:
        runtime = _load_module(
            "geophoto_cuda_runtime_unavailable_test_module",
            workers_root / "common" / "runtime.py",
        )
    finally:
        sys.path.pop(0)

    monkeypatch.setattr(runtime, "ACCELERATOR", "nvidia-cuda")
    monkeypatch.setattr(runtime, "CUDA_REQUIRED", True)
    monkeypatch.setattr(runtime, "CUDA_PROBE", True)
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    state = runtime._accelerator_state()

    assert state["accelerator"] == "nvidia-cuda"
    assert state["cuda_probe"] == "unavailable"


def _load_odm_worker():
    repo_root = Path(__file__).resolve().parents[2]
    workers_root = repo_root / "workers"
    sys.path.insert(0, str(workers_root))
    try:
        return _load_module(
            "geophoto_odm_cuda_test_module",
            workers_root / "odm" / "worker.py",
        )
    finally:
        sys.path.pop(0)


def test_odm_cuda_adds_sift_without_mutating_mapping_profile(monkeypatch):
    worker = _load_odm_worker()
    original = list(worker.PROFILES["standard"])

    monkeypatch.setattr(worker, "CUDA_ENABLED", True)
    gpu_options = worker._profile_options("mapping", "standard")
    assert gpu_options is not None
    assert gpu_options[-2:] == ["--feature-type", "sift"]

    monkeypatch.setattr(worker, "CUDA_ENABLED", False)
    cpu_options = worker._profile_options("mapping", "standard")
    assert cpu_options == original
    assert worker.PROFILES["standard"] == original


def test_odm_cuda_preserves_multispectral_options(monkeypatch):
    worker = _load_odm_worker()

    monkeypatch.setattr(worker, "CUDA_ENABLED", True)
    options = worker._profile_options("multispectral", "standard")

    assert options is not None
    assert "--radiometric-calibration" in options
    assert options[-2:] == ["--feature-type", "sift"]
