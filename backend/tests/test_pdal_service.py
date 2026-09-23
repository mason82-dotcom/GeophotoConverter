from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_service():
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "workers" / "pdal" / "service.py"
    spec = importlib.util.spec_from_file_location("geophoto_pdal_service_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pdal_service_resolves_only_inside_data_root(monkeypatch, tmp_path):
    service = _load_service()
    monkeypatch.setattr(service, "DATA_ROOT", tmp_path.resolve())

    target = tmp_path / "jobs" / "a" / "cloud.laz"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fixture")

    relative, resolved = service._resolve_relative_path("jobs/a/cloud.laz")
    assert relative == "jobs/a/cloud.laz"
    assert resolved == target.resolve()

    for unsafe in ("../outside.laz", "/etc/passwd"):
        try:
            service._resolve_relative_path(unsafe)
        except service.ServiceError as exc:
            assert exc.status == 403
            assert exc.code == "invalid_relative_path"
        else:
            raise AssertionError(f"Unsafe path was accepted: {unsafe}")


def test_pdal_service_qa_requests_only_available_dimensions(
    monkeypatch,
    tmp_path,
):
    service = _load_service()
    monkeypatch.setattr(service, "DATA_ROOT", tmp_path.resolve())

    target = tmp_path / "jobs" / "a" / "dense.ply"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fixture")

    commands = []

    def fake_run(arguments):
        commands.append(arguments)
        if "--summary" in arguments:
            return {
                "summary": {
                    "num_points": 4,
                    "dimensions": "x, y, z, red, green, blue",
                }
            }
        return {
            "stats": {
                "statistic": [
                    {"name": "X", "minimum": 0, "maximum": 1},
                    {"name": "Y", "minimum": 0, "maximum": 1},
                    {"name": "Z", "minimum": 0, "maximum": 1},
                ]
            }
        }

    monkeypatch.setattr(service, "_run_pdal_json", fake_run)

    result = service._qa("jobs/a/dense.ply")

    assert result["relative_path"] == "jobs/a/dense.ply"
    assert commands[0][0:2] == ["info", "--summary"]
    assert "--dimensions=x,y,z" in commands[1]
    assert not any(
        item == "--enumerate=Classification"
        for item in commands[1]
    )


def test_pdal_service_includes_classification_when_present(
    monkeypatch,
    tmp_path,
):
    service = _load_service()
    monkeypatch.setattr(service, "DATA_ROOT", tmp_path.resolve())

    target = tmp_path / "jobs" / "a" / "cloud.laz"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fixture")

    commands = []

    def fake_run(arguments):
        commands.append(arguments)
        if "--summary" in arguments:
            return {
                "summary": {
                    "num_points": 10,
                    "dimensions": "X, Y, Z, Classification",
                }
            }
        return {"stats": {"statistic": []}}

    monkeypatch.setattr(service, "_run_pdal_json", fake_run)
    service._qa("jobs/a/cloud.laz")

    assert "--dimensions=X,Y,Z,Classification" in commands[1]
    assert "--enumerate=Classification" in commands[1]
