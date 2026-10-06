from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.common import georeferencing as odm_evidence
from workers.common import images as worker_images


def _record(
    root: Path,
    name: str,
    metadata: dict,
    *,
    fh2_media: dict | None = None,
) -> dict:
    source = root / "source" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(name.encode())
    return {
        "relative_path": f"M3E/{name}",
        "stored_path": str(source),
        "size_bytes": source.stat().st_size,
        "sha256": f"sha-{name}",
        "metadata_json": json.dumps(metadata),
        "fh2_media_json": json.dumps(fh2_media) if fh2_media else None,
    }


def _file_metadata(
    latitude: float | None,
    longitude: float | None,
    *,
    absolute_altitude: float | None = 210.0,
    relative_altitude: float | None = 80.0,
    rtk_flag: int | None = 50,
) -> dict:
    gps = {}
    if latitude is not None:
        gps["latitude"] = latitude
    if longitude is not None:
        gps["longitude"] = longitude

    dji: dict[str, object] = {}
    if absolute_altitude is not None:
        dji["absolute_altitude"] = absolute_altitude
    if relative_altitude is not None:
        dji["relative_altitude"] = relative_altitude
    if rtk_flag is not None:
        dji["rtk_flag"] = rtk_flag
        dji["rtk_fixed"] = rtk_flag == 50
    return {"gps": gps, "dji": dji}


def _fh2(
    latitude: float,
    longitude: float,
    *,
    ellipsoid_height: float | None = 220.0,
    relative_height: float = 80.0,
    rtk_fixed: bool = True,
) -> dict:
    capture: dict[str, object] = {
        "latitudeDeg": latitude,
        "longitudeDeg": longitude,
        "relativeHeightM": relative_height,
        "rtkFixed": rtk_fixed,
    }
    if ellipsoid_height is not None:
        capture["ellipsoidHeightM"] = ellipsoid_height
    return {"asset": {"capture": capture}}


def test_odm_staging_writes_fh2_prioritized_geo_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        _record(
            tmp_path,
            "DJI_0001_D.JPG",
            _file_metadata(49.0, 8.0, absolute_altitude=210.0),
            fh2_media=_fh2(49.1001, 8.5001, ellipsoid_height=220.1),
        ),
        _record(
            tmp_path,
            "DJI_0002_D.JPG",
            _file_metadata(49.0001, 8.0001, absolute_altitude=211.0),
            fh2_media=_fh2(49.1002, 8.5002, ellipsoid_height=220.2),
        ),
    ]
    monkeypatch.setattr(worker_images, "_dataset_files", lambda _: records)

    target = tmp_path / "project" / "images"
    manifest = worker_images.prepare_photogrammetry_images(
        "dataset-1",
        target,
        create_geo_override=True,
    )

    georef = manifest["georeferencing"]
    assert georef["mode"] == "geo_override"
    assert georef["projection"] == "EPSG:4326"
    assert georef["height_mode"] == "ellipsoid"
    assert georef["canonical_position_images"] == 2
    assert georef["ellipsoid_height_images"] == 2
    assert georef["position_sources"] == {"fh2_media": 2}
    assert georef["rtk_fixed_images"] == 2

    assert [item["prepared_name"] for item in georef["files"]] == [
        "IMG_000001.JPG",
        "IMG_000002.JPG",
    ]
    assert all(item["position_source"] == "fh2_media" for item in georef["files"])
    assert all(item["has_ellipsoid_height"] for item in georef["files"])
    assert any(
        conflict.get("field") == "position.latitude_deg"
        for conflict in georef["files"][0]["fusion_conflicts"]
    )

    lines = (tmp_path / "project" / "geo.txt").read_text().splitlines()
    assert lines == [
        "EPSG:4326",
        "IMG_000001.JPG 8.5001000000 49.1001000000 220.100",
        "IMG_000002.JPG 8.5002000000 49.1002000000 220.200",
    ]


def test_geo_override_never_promotes_generic_or_relative_height_to_z(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        _record(
            tmp_path,
            "DJI_0101_D.JPG",
            {
                "gps": {
                    "latitude": 49.1,
                    "longitude": 8.5,
                    "altitude": 150.0,
                },
                "dji": {"relative_altitude": 80.0},
            },
        ),
        _record(
            tmp_path,
            "DJI_0102_D.JPG",
            {
                "gps": {
                    "latitude": 49.2,
                    "longitude": 8.6,
                    "altitude": 151.0,
                },
                "dji": {"relative_altitude": 81.0},
            },
        ),
    ]
    monkeypatch.setattr(worker_images, "_dataset_files", lambda _: records)

    target = tmp_path / "project" / "images"
    manifest = worker_images.prepare_photogrammetry_images(
        "dataset-2",
        target,
        create_geo_override=True,
    )

    assert manifest["georeferencing"]["mode"] == "geo_override"
    assert manifest["georeferencing"]["height_mode"] == "xy_only"
    assert manifest["georeferencing"]["ellipsoid_height_images"] == 0

    lines = (tmp_path / "project" / "geo.txt").read_text().splitlines()
    assert len(lines[1].split()) == 3
    assert len(lines[2].split()) == 3


def test_geo_override_falls_back_when_position_coverage_is_incomplete(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        _record(tmp_path, "DJI_0201_D.JPG", _file_metadata(49.1, 8.5)),
        _record(tmp_path, "DJI_0202_D.JPG", _file_metadata(None, None)),
    ]
    monkeypatch.setattr(worker_images, "_dataset_files", lambda _: records)

    target = tmp_path / "project" / "images"
    manifest = worker_images.prepare_photogrammetry_images(
        "dataset-3",
        target,
        create_geo_override=True,
    )

    georef = manifest["georeferencing"]
    assert georef["mode"] == "embedded_metadata_fallback"
    assert georef["reason"] == "incomplete_canonical_position"
    assert georef["canonical_position_images"] == 1
    assert not (tmp_path / "project" / "geo.txt").exists()


def test_geo_override_rejects_non_finite_coordinates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        _record(
            tmp_path,
            "DJI_0301_D.JPG",
            {"gps": {"latitude": 49.1, "longitude": 8.5}},
        ),
        _record(
            tmp_path,
            "DJI_0302_D.JPG",
            {"gps": {"latitude": float("nan"), "longitude": 8.6}},
        ),
    ]
    monkeypatch.setattr(worker_images, "_dataset_files", lambda _: records)

    manifest = worker_images.prepare_photogrammetry_images(
        "dataset-4",
        tmp_path / "project" / "images",
        create_geo_override=True,
    )

    assert manifest["georeferencing"]["mode"] == "embedded_metadata_fallback"
    assert not (tmp_path / "project" / "geo.txt").exists()


def test_dng_normalization_keeps_exiftool_metadata_copy_step(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "image.DNG"
    source.write_bytes(b"dng")
    target = tmp_path / "image.TIF"
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        if command[0] == "dcraw_emu":
            target.write_bytes(b"tiff")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(worker_images.subprocess, "run", fake_run)
    worker_images._normalize_dng(source, target)

    assert commands[0][0] == "dcraw_emu"
    assert commands[1][0] == "exiftool"
    assert "-TagsFromFile" in commands[1]
    assert str(source) in commands[1]
    assert "-all:all" in commands[1]
    assert "-unsafe" in commands[1]


def test_result_evidence_verifies_inspected_georeferencing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    for relative in (
        "odm_orthophoto/odm_orthophoto.tif",
        "odm_dem/dsm.tif",
        "odm_dem/dtm.tif",
        "odm_georeferencing/odm_georeferenced_model.laz",
    ):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"artifact")

    def fake_run(command, **kwargs):
        if command[0] == "gdalinfo":
            payload = {
                "size": [1024, 768],
                "coordinateSystem": {
                    "wkt": 'PROJCRS["WGS 84 / UTM zone 32N"]'
                },
                "geoTransform": [
                    500000.0,
                    0.05,
                    0.0,
                    5430000.0,
                    0.0,
                    -0.05,
                ],
                "stac": {"proj:epsg": 32632},
            }
        elif command[0] == "pdal":
            payload = {
                "metadata": {
                    "srs": {
                        "compoundwkt": 'PROJCRS["WGS 84 / UTM zone 32N"]'
                    }
                }
            }
        else:
            raise AssertionError(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(odm_evidence.subprocess, "run", fake_run)

    evidence_path, evidence = odm_evidence.build_odm_result_evidence(
        project,
        {"georeferencing": {"mode": "geo_override", "projection": "EPSG:4326"}},
    )

    assert evidence["summary"] == {
        "existing_outputs": 4,
        "raster_outputs_with_verified_georeferencing": 3,
        "point_cloud_outputs_with_reported_crs": 1,
    }
    assert evidence["outputs"]["orthophoto"]["georeferencing_verified"] is True
    assert evidence["outputs"]["orthophoto"]["epsg"] == 32632
    assert evidence["outputs"]["point_cloud_laz"]["crs_reported"] is True

    written = json.loads(evidence_path.read_text())
    assert written["schema"] == "geophoto.odm.georeferencing-evidence.v1"


def test_degenerate_geotransform_is_not_verified(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "orthophoto.tif"
    path.write_bytes(b"artifact")

    monkeypatch.setattr(
        odm_evidence.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "coordinateSystem": {"wkt": 'PROJCRS["test"]'},
                    "geoTransform": [0, 0, 0, 0, 0, 0],
                }
            ),
            stderr="",
        ),
    )

    evidence = odm_evidence.inspect_geotiff(path)
    assert evidence["has_crs"] is True
    assert evidence["has_geotransform"] is False
    assert evidence["georeferencing_verified"] is False


def test_missing_inspection_tool_never_claims_georeferencing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "orthophoto.tif"
    path.write_bytes(b"artifact")

    def missing_tool(command, **kwargs):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(odm_evidence.subprocess, "run", missing_tool)
    evidence = odm_evidence.inspect_geotiff(path)

    assert evidence["inspection_status"] == "unavailable"
    assert evidence["georeferencing_verified"] is False


def test_odm_geo_arguments_only_enable_mapping_override(tmp_path: Path) -> None:
    manifest = {
        "georeferencing": {
            "mode": "geo_override",
            "path": "geo.txt",
        }
    }

    assert odm_evidence.odm_geo_arguments(
        tmp_path,
        "mapping",
        manifest,
    ) == ["--geo", str(tmp_path / "geo.txt")]
    assert odm_evidence.odm_geo_arguments(
        tmp_path,
        "multispectral",
        manifest,
    ) == []
    assert odm_evidence.odm_geo_arguments(
        tmp_path,
        "mapping",
        {
            "georeferencing": {
                "mode": "embedded_metadata_fallback",
                "path": None,
            }
        },
    ) == []
