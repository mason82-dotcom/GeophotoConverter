from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.job_options import normalize_job_options
from app.storage import store


def test_thermal_options_are_normalized_with_defaults():
    options = normalize_job_options(
        "thermal",
        "thermal",
        {
            "emissivity": 0.95,
            "distance_m": 10,
            "humidity_pct": 65,
        },
    )
    assert options["emissivity"] == 0.95
    assert options["distance_m"] == 10.0
    assert options["humidity_pct"] == 65.0
    assert options["hotspot_delta_c"] == 10.0
    assert options["hotspot_min_pixels"] == 4
    assert "ambient_temp_c" not in options


@pytest.mark.parametrize(
    ("options", "field"),
    [
        ({"emissivity": 0}, "emissivity"),
        ({"emissivity": 1.1}, "emissivity"),
        ({"distance_m": 0}, "distance_m"),
        ({"humidity_pct": -1}, "humidity_pct"),
        ({"humidity_pct": 101}, "humidity_pct"),
        ({"hotspot_delta_c": 0}, "hotspot_delta_c"),
        ({"hotspot_min_pixels": 0}, "hotspot_min_pixels"),
        ({"unknown": 1}, "unknown"),
    ],
)
def test_invalid_thermal_options_are_rejected(options, field):
    with pytest.raises(ValidationError) as exc:
        normalize_job_options("thermal", "thermal", options)
    assert field in str(exc.value)


def test_nonthermal_options_are_rejected():
    with pytest.raises(ValueError, match="does not accept job options"):
        normalize_job_options(
            "odm",
            "rgb",
            {"orthophoto_resolution": 1},
        )


def test_job_options_round_trip_in_store():
    dataset = store.create_dataset("Options", None)
    job = store.create_job(
        dataset["id"],
        "thermal",
        "standard",
        "thermal",
        {
            "emissivity": 0.95,
            "hotspot_delta_c": 8.0,
            "hotspot_min_pixels": 6,
        },
    )
    assert job["options"] == {
        "emissivity": 0.95,
        "hotspot_delta_c": 8.0,
        "hotspot_min_pixels": 6,
    }
