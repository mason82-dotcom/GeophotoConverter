from __future__ import annotations


def _dataset(client) -> dict:
    response = client.post("/api/v1/datasets", json={"name": "GCP Survey"})
    assert response.status_code == 201
    return response.json()


def _upload_mapping_images(client, dataset_id: str) -> list[str]:
    paths = [
        "flight/DJI_0001.JPG",
        "flight/DJI_0002.JPG",
        "flight/DJI_0003.JPG",
    ]
    for index, path in enumerate(paths):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/files",
            files=[
                (
                    "files",
                    (
                        path.split("/")[-1],
                        f"gcp-image-{index}".encode(),
                        "image/jpeg",
                    ),
                )
            ],
            data={"relative_paths": f'["{path}"]'},
        )
        assert response.status_code == 200
    return paths


def _project(paths: list[str]) -> dict:
    points = []
    for point_index in range(5):
        points.append(
            {
                "id": f"GCP-{point_index + 1:02d}",
                "role": "control",
                "x_m": 500000.0 + point_index * 10.0,
                "y_m": 5430000.0 + point_index * 10.0,
                "z_m": 120.0,
                "observations": [
                    {
                        "image_name": path,
                        "pixel_x": 1000.0 + point_index * 10.0 + image_index,
                        "pixel_y": 800.0 + point_index * 5.0 + image_index,
                    }
                    for image_index, path in enumerate(paths)
                ],
            }
        )
    points.append(
        {
            "id": "CHK-01",
            "role": "checkpoint",
            "x_m": 500100.0,
            "y_m": 5430100.0,
            "z_m": 120.0,
            "observations": [
                {
                    "image_name": path,
                    "pixel_x": 1200.0 + image_index,
                    "pixel_y": 900.0 + image_index,
                }
                for image_index, path in enumerate(paths)
            ],
        }
    )
    return {
        "project_crs": "EPSG:32632",
        "points": points,
    }


def test_gcp_project_can_be_saved_loaded_and_deleted(client):
    dataset = _dataset(client)
    paths = _upload_mapping_images(client, dataset["id"])

    saved = client.put(
        f"/api/v1/datasets/{dataset['id']}/gcp",
        json=_project(paths),
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["configured"] is True
    assert body["validation"]["status"] == "ready"
    assert body["validation"]["summary"]["control_points"] == 5
    assert body["validation"]["summary"]["checkpoints"] == 1
    assert body["validation"]["dataset_mapping_image_count"] == 3

    loaded = client.get(f"/api/v1/datasets/{dataset['id']}/gcp")
    assert loaded.status_code == 200
    assert loaded.json()["project_crs"] == "EPSG:32632"
    assert len(loaded.json()["points"]) == 6

    deleted = client.delete(f"/api/v1/datasets/{dataset['id']}/gcp")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    empty = client.get(f"/api/v1/datasets/{dataset['id']}/gcp")
    assert empty.status_code == 200
    assert empty.json()["configured"] is False


def test_gcp_project_draft_persists_when_observation_file_is_unknown(client):
    dataset = _dataset(client)
    paths = _upload_mapping_images(client, dataset["id"])
    project = _project(paths)
    project["points"][0]["observations"][0]["image_name"] = "missing.JPG"

    response = client.put(
        f"/api/v1/datasets/{dataset['id']}/gcp",
        json=project,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["validation"]["status"] == "blocked"
    assert any(
        issue["code"] == "observation_image_not_in_dataset"
        for issue in body["validation"]["issues"]
    )


def test_gcp_endpoint_requires_existing_dataset(client):
    response = client.get("/api/v1/datasets/missing/gcp")
    assert response.status_code == 404
