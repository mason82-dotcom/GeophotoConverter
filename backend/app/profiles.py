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
                        "key": "mapping",
                        "title": "Mapping (RGB/WIDE)",
                        "description": (
                            "Orthofoto, Geländemodelle, Punktwolke und Mesh "
                            "aus RGB/WIDE-Luftbildern."
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
                                "purpose": "Schnelle Prüfung von Abdeckung und Bildzuordnung.",
                                "orthophoto_resolution_cm": 10,
                            },
                            "standard": {
                                "purpose": "Allgemeines Mapping und Geländerekonstruktion.",
                                "orthophoto_resolution_cm": 5,
                            },
                            "high": {
                                "purpose": "Hochwertigere Verarbeitung für Vermessungsaufgaben.",
                                "orthophoto_resolution_cm": 2,
                            },
                        },
                    },
                    {
                        "key": "multispectral",
                        "title": "M3M Multispektral",
                        "description": (
                            "Vollständige DJI-Mavic-3-Multispektral-Aufnahmegruppen "
                            "gemeinsam als kalibriertes Multiband-Orthofoto verarbeiten."
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
                            "reason": "ODM kennzeichnet camera+sun als experimentell.",
                        },
                        "outputs": [
                            "multiband_orthophoto",
                            "point_cloud_laz",
                            "report_pdf",
                        ],
                        "profiles": {
                            "preview": {
                                "purpose": "Grobe Multispektral-Prüfung.",
                                "orthophoto_resolution_cm": 10,
                            },
                            "standard": {
                                "purpose": "Kalibriertes Multispektral-Mapping.",
                                "orthophoto_resolution_cm": 5,
                            },
                            "high": {
                                "purpose": "Höher aufgelöstes Multispektral-Mapping.",
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
                        "key": "mapping",
                        "title": "Mapping (RGB/WIDE) mit MicMac",
                        "eligible_media_kinds": ["RGB", "WIDE"],
                        "minimum_images": 3,
                        "outputs": ["sparse_point_cloud", "dense_point_cloud"],
                        "profiles": {
                            "preview": {
                                "purpose": "Verknüpfungspunkte, Orientierung und dünne Punktwolke.",
                            },
                            "standard": {
                                "purpose": "Dünne Punktwolke plus dichte C3DC-QuickMac-Punktwolke.",
                            },
                            "high": {
                                "purpose": "Dünne Punktwolke plus dichte C3DC-BigMac-Punktwolke.",
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
                        "key": "reconstruction",
                        "title": "RGB-/Weitwinkel-3D-Gaussian-Splatting",
                        "eligible_media_kinds": ["RGB", "WIDE"],
                        "minimum_images": 3,
                        "outputs": ["gaussian_splat_ply", "checkpoint", "training_stats"],
                        "profiles": {
                            "preview": {
                                "purpose": "Schnelles Training mit reduzierter Auflösung.",
                                "max_steps": 3000,
                            },
                            "standard": {
                                "purpose": "Ausgewogene Rekonstruktion.",
                                "max_steps": 7000,
                            },
                            "high": {
                                "purpose": "Längeres Training mit höherem Detailgrad.",
                                "max_steps": 15000,
                            },
                        },
                    }
                ],
            },
            {
                "key": "thermal",
                "title": "DJI Radiometrische Thermografie",
                "automated": True,
                "requires_dji_tsdk": True,
                "platforms": ["M3T", "M4T"],
                "workflows": [
                    {
                        "key": "thermal",
                        "title": "WIDE + radiometrisches Thermalbild",
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
                                "note": "Optionale DIRP-Messwertvorgabe.",
                            },
                            "distance_m": {
                                "type": "number",
                                "minimum_exclusive": 0.0,
                                "default": None,
                                "note": "Optionale DIRP-Messwertvorgabe.",
                            },
                            "humidity_pct": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 100.0,
                                "default": None,
                                "note": "Optionale DIRP-Messwertvorgabe.",
                            },
                            "reflection_c": {
                                "type": "number",
                                "default": None,
                                "note": "Optionale Vorgabe der reflektierten Temperatur.",
                            },
                            "ambient_temp_c": {
                                "type": "number",
                                "default": None,
                                "note": "Optionale Vorgabe der Umgebungstemperatur.",
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
                                "purpose": "Verwendet die SDK-native Radiometrie.",
                            },
                            "standard": {
                                "purpose": "Verwendet die SDK-native Radiometrie.",
                            },
                            "high": {
                                "purpose": "Verwendet die SDK-native Radiometrie.",
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
                    "Manuelle/experimentelle Vergleichs-Engine; nicht Teil der "
                    "automatisierten Job-Warteschlange."
                ),
                "workflows": [],
            },
        ],
    }
