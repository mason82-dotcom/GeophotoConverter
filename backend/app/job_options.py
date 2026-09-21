from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ThermalJobOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emissivity: float | None = Field(default=None, gt=0.0, le=1.0, allow_inf_nan=False)
    distance_m: float | None = Field(default=None, gt=0.0, allow_inf_nan=False)
    humidity_pct: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        allow_inf_nan=False,
    )
    reflection_c: float | None = Field(default=None, allow_inf_nan=False)
    ambient_temp_c: float | None = Field(default=None, allow_inf_nan=False)
    hotspot_delta_c: float = Field(default=10.0, gt=0.0, allow_inf_nan=False)
    hotspot_min_pixels: int = Field(default=4, ge=1)


def normalize_job_options(
    engine: str,
    workflow: str,
    raw: dict[str, Any] | None,
) -> dict[str, Any]:
    options = raw or {}

    if engine == "thermal" and workflow == "thermal":
        parsed = ThermalJobOptions.model_validate(options)
        return parsed.model_dump(exclude_none=True)

    if options:
        raise ValueError(
            f"Engine/workflow {engine}/{workflow} does not accept job options yet."
        )
    return {}
