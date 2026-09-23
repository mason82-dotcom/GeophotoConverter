from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from services.pdal_qa import server


def test_resolve_artifact_rejects_escape(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path.resolve())
    with pytest.raises(server.RequestError) as exc:
        server._resolve_artifact("../secret.laz")
    assert exc.value.status == 400


def test_qa_artifact_runs_pinned_commands(monkeypatch, tmp_path: Path):
    cloud = tmp_path / "jobs" / "job-1" / "project" / "cloud.laz"
    cloud.parent.mkdir(parents=True)
    cloud.write_bytes(b"fixture")
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path.resolve())

    commands: list[list[str]] = []

    def fake_run(args, **kwargs):
        commands.append(list(args))
        if args == ["pdal", "--version"]:
            return subprocess.CompletedProcess(args, 0, "pdal 2.10.2 (git-version: Release)\n", "")
        payload = {"summary": {"num_points": 1}} if "--summary" in args else {"stats": {"statistic": []}}
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    result = server.qa_artifact("jobs/job-1/project/cloud.laz")

    assert result["artifact_path"] == "jobs/job-1/project/cloud.laz"
    assert result["pdal_version"].startswith("pdal 2.10.2")
    assert commands[1][:3] == ["pdal", "info", "--summary"]
    assert "--dimensions=X,Y,Z,Classification" in commands[2]
    assert "--enumerate=Classification" in commands[2]
