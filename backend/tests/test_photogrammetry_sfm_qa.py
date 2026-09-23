from __future__ import annotations

import pytest

from app.photogrammetry_sfm_qa import inspect_reconstruction


class FakeTrackElement:
    def __init__(self, image_id: int):
        self.image_id = image_id


class FakeTrack:
    def __init__(self, image_ids: list[int]):
        self.elements = [FakeTrackElement(image_id) for image_id in image_ids]

    def length(self) -> int:
        return len(self.elements)


class FakePoint:
    def __init__(self, error: float, image_ids: list[int]):
        self.error = error
        self.track = FakeTrack(image_ids)


class FakeImage:
    def __init__(self, image_id: int, name: str, has_pose: bool = True):
        self.image_id = image_id
        self.name = name
        self.has_pose = has_pose


class FakeReconstruction:
    def __init__(
        self,
        images: list[FakeImage],
        points: list[FakePoint],
    ):
        self.images = {image.image_id: image for image in images}
        self.points3D = {
            index + 1: point
            for index, point in enumerate(points)
        }

    def update_point_3d_errors(self) -> None:
        return None

    def num_images(self) -> int:
        return len(self.images)

    def num_reg_images(self) -> int:
        return sum(1 for image in self.images.values() if image.has_pose)

    def num_points3D(self) -> int:
        return len(self.points3D)

    def compute_num_observations(self) -> int:
        return sum(point.track.length() for point in self.points3D.values())

    def compute_mean_track_length(self) -> float:
        if not self.points3D:
            return 0.0
        return (
            self.compute_num_observations()
            / len(self.points3D)
        )

    def compute_mean_observations_per_reg_image(self) -> float:
        registered = self.num_reg_images()
        return (
            self.compute_num_observations() / registered
            if registered
            else 0.0
        )

    def compute_mean_reprojection_error(self) -> float:
        if not self.points3D:
            return 0.0
        return sum(
            point.error
            for point in self.points3D.values()
        ) / len(self.points3D)


def test_ready_sparse_reconstruction() -> None:
    reconstruction = FakeReconstruction(
        images=[
            FakeImage(1, "IMG_0001.JPG"),
            FakeImage(2, "IMG_0002.JPG"),
            FakeImage(3, "IMG_0003.JPG"),
            FakeImage(4, "IMG_0004.JPG"),
        ],
        points=[
            FakePoint(0.5, [1, 2, 3]),
            FakePoint(0.8, [1, 2, 4]),
            FakePoint(1.0, [1, 3, 4]),
            FakePoint(1.2, [2, 3, 4]),
        ],
    )

    result = inspect_reconstruction(
        reconstruction,
        expected_image_names=[
            "IMG_0001.JPG",
            "IMG_0002.JPG",
            "IMG_0003.JPG",
            "IMG_0004.JPG",
        ],
    )

    assert result["status"] == "ready"
    assert result["images"]["registration_ratio"] == 1.0
    assert result["sparse_points"]["count"] == 4
    assert result["track_length"]["mean"] == pytest.approx(3.0)
    assert result["connectivity"]["component_count"] == 1
    assert result["connectivity"]["largest_component_ratio"] == 1.0
    assert result["connectivity"]["weak_image_candidates"] == []


def test_registration_and_reprojection_warnings() -> None:
    reconstruction = FakeReconstruction(
        images=[
            FakeImage(1, "IMG_0001.JPG"),
            FakeImage(2, "IMG_0002.JPG"),
            FakeImage(3, "IMG_0003.JPG", has_pose=False),
            FakeImage(4, "IMG_0004.JPG", has_pose=False),
        ],
        points=[
            FakePoint(5.0, [1, 2]),
            FakePoint(6.0, [1, 2]),
        ],
    )

    result = inspect_reconstruction(
        reconstruction,
        expected_image_names=[
            "IMG_0001.JPG",
            "IMG_0002.JPG",
            "IMG_0003.JPG",
            "IMG_0004.JPG",
        ],
    )

    codes = {item["code"] for item in result["issues"]}
    assert result["status"] == "warning"
    assert result["images"]["registration_ratio"] == pytest.approx(0.5)
    assert "SFM_LOW_REGISTRATION_RATIO" in codes
    assert "SFM_HIGH_MEAN_REPROJECTION_ERROR" in codes
    assert "SFM_HIGH_P95_REPROJECTION_ERROR" in codes
    assert "SFM_LOW_MEAN_TRACK_LENGTH" in codes


def test_fragmented_camera_network_is_reported() -> None:
    reconstruction = FakeReconstruction(
        images=[
            FakeImage(1, "A.JPG"),
            FakeImage(2, "B.JPG"),
            FakeImage(3, "C.JPG"),
            FakeImage(4, "D.JPG"),
        ],
        points=[
            FakePoint(0.4, [1, 2]),
            FakePoint(0.5, [1, 2]),
            FakePoint(0.4, [3, 4]),
            FakePoint(0.5, [3, 4]),
        ],
    )

    result = inspect_reconstruction(
        reconstruction,
        thresholds={
            "min_mean_track_length": 2.0,
            "min_connected_image_ratio": 0.8,
        },
    )

    codes = {item["code"] for item in result["issues"]}
    assert result["status"] == "warning"
    assert result["connectivity"]["component_count"] == 2
    assert result["connectivity"]["largest_component_ratio"] == pytest.approx(0.5)
    assert "SFM_FRAGMENTED_CAMERA_NETWORK" in codes
    assert "SFM_WEAK_CAMERA_CONNECTIVITY" in codes


def test_no_registered_images_or_points_blocks() -> None:
    reconstruction = FakeReconstruction(
        images=[
            FakeImage(1, "A.JPG", has_pose=False),
            FakeImage(2, "B.JPG", has_pose=False),
        ],
        points=[],
    )

    result = inspect_reconstruction(reconstruction)

    codes = {item["code"] for item in result["issues"]}
    assert result["status"] == "blocked"
    assert "SFM_NO_REGISTERED_IMAGES" in codes
    assert "SFM_NO_SPARSE_POINTS" in codes


def test_expected_image_names_control_registration_denominator() -> None:
    reconstruction = FakeReconstruction(
        images=[
            FakeImage(1, "A.JPG"),
            FakeImage(2, "B.JPG"),
            FakeImage(3, "EXTRA.JPG"),
        ],
        points=[
            FakePoint(0.5, [1, 2, 3]),
            FakePoint(0.6, [1, 2, 3]),
            FakePoint(0.7, [1, 2, 3]),
        ],
    )

    result = inspect_reconstruction(
        reconstruction,
        expected_image_names=["A.JPG", "B.JPG", "C.JPG", "D.JPG"],
    )

    assert result["images"]["expected"] == 4
    assert result["images"]["registered_expected"] == 2
    assert result["images"]["registration_ratio"] == pytest.approx(0.5)


def test_thresholds_are_explicitly_overridable() -> None:
    reconstruction = FakeReconstruction(
        images=[
            FakeImage(1, "A.JPG"),
            FakeImage(2, "B.JPG"),
        ],
        points=[
            FakePoint(2.5, [1, 2]),
            FakePoint(2.5, [1, 2]),
        ],
    )

    result = inspect_reconstruction(
        reconstruction,
        thresholds={
            "min_registration_ratio": 1.0,
            "max_mean_reprojection_error_px": 3.0,
            "max_p95_reprojection_error_px": 3.0,
            "min_mean_track_length": 2.0,
            "min_connected_image_ratio": 1.0,
        },
    )

    codes = {item["code"] for item in result["issues"]}
    assert "SFM_HIGH_MEAN_REPROJECTION_ERROR" not in codes
    assert "SFM_HIGH_P95_REPROJECTION_ERROR" not in codes
