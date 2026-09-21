from __future__ import annotations

from typing import Any


def processing_catalog() -> dict[str, Any]:
    return {
        "profiles": ["preview", "standard", "high"],
        "engines": [
            {
                "key": "odm",
                "title": "OpenDroneMap",
                "automated": True,
                "workflows": [
                    {
                        "key": "rgb",
                        "title": "RGB / Wide Mapping",
                        "description": (
                            "Orthophoto, terrain products, point cloud and mesh "
                            "from RGB/WIDE aerial imagery."
                        ),
                        "eligible_media_kinds": ["RGB", "WIDE"],
                        "minimum_images": 2,
                        "outputs": [
                            "orthophoto",
                            "dsm",
                            "dtm",
                            "point_cloud_laz",
                            "mesh_obj",
                            "report_pdf",
                        ],
                        "profiles": {
                            "preview": {
                                "purpose": "Fast coverage and matching check.",
                                "orthophoto_resolution_cm": 10,
                            },
                            "standard": {
                                "purpose": "General mapping and terrain reconstruction.",
                                "orthophoto_resolution_cm": 5,
                            },
                            "high": {
                                "purpose": "Higher-quality survey processing.",
                                "orthophoto_resolution_cm": 2,
                            },
                        },
                    },
                    {
                        "key": "multispectral",
                        "title": "M3M Multispectral",
                        "description": (
                            "Process complete DJI Mavic 3 Multispectral capture "
                            "groups together as a calibrated multiband orthophoto."
                        ),
                        "platforms": ["M3M"],
                        "eligible_media_kinds": [
                            "RGB",
                            "MS_GREEN",
                            "MS_RED",
                            "MS_RED_EDGE",
                            "MS_NIR",
                        ],
                        "minimum_complete_groups": 2,
                        "radiometric_calibration": "camera",
                        "camera_plus_sun": {
                            "enabled": False,
                            "reason": "ODM documents camera+sun as experimental.",
                        },
                        "outputs": [
                            "multiband_orthophoto",
                            "point_cloud_laz",
                            "report_pdf",
                        ],
                        "profiles": {
                            "preview": {
                                "purpose": "Coarse multispectral validation.",
                                "orthophoto_resolution_cm": 10,
                            },
                            "standard": {
                                "purpose": "Calibrated multispectral mapping.",
                                "orthophoto_resolution_cm": 5,
                            },
                            "high": {
                                "purpose": "Higher-resolution multispectral mapping.",
                                "orthophoto_resolution_cm": 2,
                            },
                        },
                    },
                ],
            },
            {
                "key": "micmac",
                "title": "MicMac",
                "automated": True,
                "workflows": [
                    {
                        "key": "rgb",
                        "title": "RGB / Wide Reconstruction",
                        "eligible_media_kinds": ["RGB", "WIDE"],
                        "minimum_images": 3,
                        "outputs": ["sparse_point_cloud", "dense_point_cloud"],
                        "profiles": {
                            "preview": {
                                "purpose": "Tie points, orientation and sparse cloud.",
                            },
                            "standard": {
                                "purpose": "Sparse + C3DC QuickMac dense cloud.",
                            },
                            "high": {
                                "purpose": "Sparse + C3DC BigMac dense cloud.",
                            },
                        },
                    }
                ],
            },
            {
                "key": "gsplat",
                "title": "Gaussian Splatting",
                "automated": True,
                "requires_gpu": True,
                "workflows": [
                    {
                        "key": "rgb",
                        "title": "RGB / Wide 3D Gaussian Splatting",
                        "eligible_media_kinds": ["RGB", "WIDE"],
                        "minimum_images": 3,
                        "outputs": ["gaussian_splat_ply", "checkpoint", "training_stats"],
                        "profiles": {
                            "preview": {
                                "purpose": "Fast reduced-resolution training.",
                                "max_steps": 3000,
                            },
                            "standard": {
                                "purpose": "Balanced reconstruction.",
                                "max_steps": 7000,
                            },
                            "high": {
                                "purpose": "Longer higher-detail training.",
                                "max_steps": 15000,
                            },
                        },
                    }
                ],
            },
            {
                "key": "thermal",
                "title": "DJI Radiometric Thermal",
                "automated": True,
                "requires_dji_tsdk": True,
                "platforms": ["M3T", "M4T"],
                "workflows": [
                    {
                        "key": "thermal",
                        "title": "WIDE + Radiometric Thermal",
                        "minimum_complete_groups": 1,
                        "required_pair": ["WIDE", "THERMAL"],
                        "temperature_space": "sensor_pixel",
                        "wide_thermal_coregistered": False,
                        "georeferenced_temperature_raster": False,
                        "options": {
                            "emissivity": {
                                "type": "number",
                                "minimum_exclusive": 0.0,
                                "maximum": 1.0,
                                "default": None,
                                "note": "Optional DIRP measurement override.",
                            },
                            "distance_m": {
                                "type": "number",
                                "minimum_exclusive": 0.0,
                                "default": None,
                                "note": "Optional DIRP measurement override.",
                            },
                            "humidity_pct": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 100.0,
                                "default": None,
                                "note": "Optional DIRP measurement override.",
                            },
                            "reflection_c": {
                                "type": "number",
                                "default": None,
                                "note": "Optional reflected temperature override.",
                            },
                            "ambient_temp_c": {
                                "type": "number",
                                "default": None,
                                "note": "Optional ambient temperature override.",
                            },
                            "hotspot_delta_c": {
                                "type": "number",
                                "minimum_exclusive": 0.0,
                                "default": 10.0,
                            },
                            "hotspot_min_pixels": {
                                "type": "integer",
                                "minimum": 1,
                                "default": 4,
                            },
                        },
                        "outputs": [
                            "thermal_temperature_tiff",
                            "thermal_preview",
                            "thermal_hotspot_mask",
                            "thermal_hotspots",
                            "thermal_capture_points",
                            "thermal_summary",
                            "thermal_registration_audit",
                        ],
                        "profiles": {
                            "preview": {
                                "purpose": "Uses SDK-native radiometry.",
                            },
                            "standard": {
                                "purpose": "Uses SDK-native radiometry.",
                            },
                            "high": {
                                "purpose": "Uses SDK-native radiometry.",
                            },
                        },
                    }
                ],
            },
            {
                "key": "telesculptor",
                "title": "TeleSculptor",
                "automated": False,
                "experimental": True,
                "description": (
                    "Manual/experimental comparison engine; not part of the "
                    "automated job queue."
                ),
                "workflows": [],
            },
        ],
    }
