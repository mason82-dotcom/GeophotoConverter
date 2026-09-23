from __future__ import annotations

from pathlib import Path
from typing import Any


def odm_geo_arguments(
    project_dir: Path,
    workflow: str,
    input_manifest: dict[str, Any],
) -> list[str]:
    georeferencing = input_manifest.get("georeferencing")
    if not isinstance(georeferencing, dict):
        return []
    if (
        workflow != "mapping"
        or georeferencing.get("mode") != "geo_override"
        or not georeferencing.get("path")
    ):
        return []
    return [
        "--geo",
        str(project_dir / str(georeferencing["path"])),
    ]
