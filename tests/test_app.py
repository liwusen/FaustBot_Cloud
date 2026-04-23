import io
import sys
import wave
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cloud_inference_server.app import create_app
from cloud_inference_server.config import CloudConfig
from cloud_inference_server.storage import CloudStorage


def _make_wav_bytes(duration_seconds: float = 1.2, sample_rate: int = 16000) -> bytes:
    frame_count = int(duration_seconds * sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)
    return buffer.getvalue()


def _build_client(tmp_path):
    config = CloudConfig(
        database_path=str(tmp_path / "cloud.sqlite3"),
        reference_dir=str(tmp_path / "references"),
        hourly_limit_points=10,
        daily_limit_points=20,
    )
    storage = CloudStorage(Path(config.database_path))
    app = create_app(config=config, storage=storage)
    service_key = storage.create_service_key(name="pytest").service_key
    return TestClient(app), service_key, app.state.cloud_service, storage


def test_reference_upload_and_tts_usage(tmp_path, monkeypatch):
    client, service_key, service, storage = _build_client(tmp_path)

    def fake_forward_tts(payload):
        assert payload["prompt_text"] == "一二三。"
        assert payload["text"] == "你好ab"
        return b"RIFF", "audio/wav"

    monkeypatch.setattr(service, "_forward_tts_request", fake_forward_tts)

    upload_response = client.post(
        "/v1/references",
        headers={"Authorization": f"Bearer {service_key}"},
        files={"file": ("demo.wav", _make_wav_bytes(0.5), "audio/wav")},
        data={"prompt_text": "一二三。", "prompt_language": "zh"},
    )
    assert upload_response.status_code == 200
    refer_hash = upload_response.json()["refer_hash"]

    tts_response = client.post(
        "/v1/tts",
        headers={"Authorization": f"Bearer {service_key}"},
        json={"refer_hash": refer_hash, "text": "你好ab", "text_language": "zh"},
    )
    assert tts_response.status_code == 200
    assert tts_response.headers["content-type"].startswith("audio/wav")

    usage = storage.get_usage_snapshot(service_key, hourly_limit_units=1000, daily_limit_units=2000)
    assert usage.hourly_units == 230
    assert usage.daily_units == 230


def test_asr_usage_rounds_total_seconds_up(tmp_path, monkeypatch):
    client, service_key, service, storage = _build_client(tmp_path)

    def fake_forward_asr(file_name, audio_bytes, mime_type):
        assert file_name == "chunk.wav"
        return {"status": "success", "text": "测试"}

    monkeypatch.setattr(service, "_forward_asr_request", fake_forward_asr)

    response = client.post(
        "/v1/asr",
        headers={"Authorization": f"Bearer {service_key}"},
        files={"file": ("chunk.wav", _make_wav_bytes(1.2), "audio/wav")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["billing"]["charged_points"] == 2.0

    usage = storage.get_usage_snapshot(service_key, hourly_limit_units=1000, daily_limit_units=2000)
    assert usage.hourly_units == 200


def test_service_key_is_required(tmp_path):
    client, _, _, _ = _build_client(tmp_path)
    response = client.get("/v1/tts", params={"refer_hash": "abc", "text": "你好", "text_language": "zh"})
    assert response.status_code == 401
    assert response.json()["code"] == "missing_service_key"


def test_reference_lookup_endpoint_returns_uploaded_item(tmp_path):
    client, service_key, _, _ = _build_client(tmp_path)
    payload = _make_wav_bytes(0.5)

    upload_response = client.post(
        "/v1/references",
        headers={"Authorization": f"Bearer {service_key}"},
        files={"file": ("demo.wav", payload, "audio/wav")},
        data={"prompt_text": "一二三。", "prompt_language": "zh"},
    )
    assert upload_response.status_code == 200
    refer_hash = upload_response.json()["refer_hash"]

    lookup_response = client.get(
        f"/v1/references/{refer_hash}",
        headers={"Authorization": f"Bearer {service_key}"},
    )
    assert lookup_response.status_code == 200
    data = lookup_response.json()
    assert data["refer_hash"] == refer_hash
    assert data["exists"] is True