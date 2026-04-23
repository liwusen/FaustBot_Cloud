from pathlib import Path
import sys

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cloud_inference_server.app import create_app
from cloud_inference_server.config import CloudConfig
from cloud_inference_server.storage import CloudStorage


def _build_client(tmp_path):
    config = CloudConfig(
        database_path=str(tmp_path / "cloud.sqlite3"),
        reference_dir=str(tmp_path / "references"),
        root_key="FSK-ROOT-1234567890abcdef",
    )
    storage = CloudStorage(Path(config.database_path))
    app = create_app(config=config, storage=storage)
    return TestClient(app), config, storage


def test_admin_create_key_requires_root_key(tmp_path):
    client, _, _ = _build_client(tmp_path)
    response = client.post("/v1/admin/keys", data={"name": "demo"})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_root_key"


def test_admin_key_management_works_with_root_key(tmp_path):
    client, config, _ = _build_client(tmp_path)
    headers = {"Authorization": f"Bearer {config.root_key}"}

    create_response = client.post("/v1/admin/keys", headers=headers, data={"name": "demo", "note": "local"})
    assert create_response.status_code == 200
    service_key = create_response.json()["service_key"]

    list_response = client.get("/v1/admin/keys", headers=headers)
    assert list_response.status_code == 200
    assert any(item["service_key"] == service_key for item in list_response.json())

    disable_response = client.post(f"/v1/admin/keys/{service_key}/disable", headers=headers)
    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False

    enable_response = client.post(f"/v1/admin/keys/{service_key}/enable", headers=headers)
    assert enable_response.status_code == 200
    assert enable_response.json()["enabled"] is True

    reset_response = client.post(f"/v1/admin/keys/{service_key}/reset-usage", headers=headers)
    assert reset_response.status_code == 200
