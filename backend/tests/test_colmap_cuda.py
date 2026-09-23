from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _load_worker():
    repo_root = Path(__file__).resolve().parents[2]
    workers_root = repo_root / "workers"
    sys.path.insert(0, str(workers_root))
    try:
        spec = importlib.util.spec_from_file_location(
            "geophoto_gsplat_colmap_cuda_test_module",
            workers_root / "gsplat" / "worker.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_colmap_commands_use_cuda(monkeypatch):
    worker = _load_worker()
    monkeypatch.setattr(worker, "COLMAP_CUDA", True)
    monkeypatch.setattr(worker, "COLMAP_GPU_INDEX", "0")

    feature = worker._colmap_feature_command(
        Path("/tmp/database.db"),
        Path("/tmp/images"),
        "2400",
    )
    matching = worker._colmap_match_command(
        Path("/tmp/database.db"),
        "exhaustive_matcher",
    )

    assert feature[feature.index("--FeatureExtraction.type") + 1] == "SIFT"
    assert feature[feature.index("--FeatureExtraction.use_gpu") + 1] == "1"
    assert feature[feature.index("--FeatureExtraction.gpu_index") + 1] == "0"
    assert feature[feature.index("--FeatureExtraction.max_image_size") + 1] == "2400"
    assert matching[matching.index("--FeatureMatching.use_gpu") + 1] == "1"
    assert matching[matching.index("--FeatureMatching.gpu_index") + 1] == "0"


def test_colmap_commands_support_cpu_fallback(monkeypatch):
    worker = _load_worker()
    monkeypatch.setattr(worker, "COLMAP_CUDA", False)

    feature = worker._colmap_feature_command(
        Path("/tmp/database.db"),
        Path("/tmp/images"),
        "1600",
    )
    matching = worker._colmap_match_command(
        Path("/tmp/database.db"),
        "sequential_matcher",
    )

    assert feature[feature.index("--FeatureExtraction.use_gpu") + 1] == "0"
    assert "--FeatureExtraction.gpu_index" not in feature
    assert matching[matching.index("--FeatureMatching.use_gpu") + 1] == "0"
    assert "--FeatureMatching.gpu_index" not in matching


def test_colmap_runtime_verifies_version_cuda_and_gpu(monkeypatch, tmp_path):
    worker = _load_worker()
    monkeypatch.setattr(worker, "COLMAP_CUDA", True)
    monkeypatch.setattr(worker, "COLMAP_GPU_INDEX", "0")
    monkeypatch.setattr(worker, "COLMAP_VERSION", "4.2.0")

    def fake_run(command, **kwargs):
        if command[:2] == ["colmap", "version"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "COLMAP 4.2.0 -- Structure-from-Motion and Multi-View Stereo\n"
                    "Commit test on 2026-09-23 with CUDA\n"
                ),
                stderr="",
            )
        if command[:2] == ["nvidia-smi", "-L"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="GPU 0: NVIDIA RTX Test (UUID: GPU-test)\n",
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    log_path = tmp_path / "worker.log"
    worker._verify_colmap_runtime(log_path)

    text = log_path.read_text(encoding="utf-8")
    assert "COLMAP Runtime: 4.2.0" in text
    assert "CUDA-SIFT aktiv" in text
    assert "NVIDIA RTX Test" in text


def test_colmap_runtime_rejects_cpu_build(monkeypatch, tmp_path):
    worker = _load_worker()
    monkeypatch.setattr(worker, "COLMAP_CUDA", True)
    monkeypatch.setattr(worker, "COLMAP_VERSION", "4.2.0")

    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "COLMAP 4.2.0 "
                "(Commit test on 2026-09-23 without GPU support)\n"
            ),
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="nicht mit CUDA-Unterstützung gebaut"):
        worker._verify_colmap_runtime(tmp_path / "worker.log")


def test_colmap_runtime_rejects_missing_gpu(monkeypatch, tmp_path):
    worker = _load_worker()
    monkeypatch.setattr(worker, "COLMAP_CUDA", True)
    monkeypatch.setattr(worker, "COLMAP_VERSION", "4.2.0")

    def fake_run(command, **kwargs):
        if command[:2] == ["colmap", "version"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="COLMAP 4.2.0\nCommit test with CUDA\n",
                stderr="",
            )
        if command[:2] == ["nvidia-smi", "-L"]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="no gpu")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="keine NVIDIA-GPU sichtbar"):
        worker._verify_colmap_runtime(tmp_path / "worker.log")
