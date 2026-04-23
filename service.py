from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

from .audio_utils import measure_wav_duration_seconds, persist_reference_file, safe_file_name, sha256_hex
from .billing import POINT_SCALE, count_asr_point_units, count_tts_point_units, format_points
from .config import CloudConfig
from .storage import CloudStorage, ReferenceRecord, ServiceKeyRecord


class CloudServiceError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int = 400, code: str = "bad_request") -> None:
        super().__init__(detail)
        self.detail = str(detail)
        self.status_code = int(status_code)
        self.code = str(code)


@dataclass(slots=True)
class TtsRequest:
    text: str
    text_language: str = "zh"
    refer_hash: str = ""
    prompt_text: str = ""
    prompt_language: str = ""


class CloudInferenceService:
    def __init__(self, config: CloudConfig, storage: CloudStorage) -> None:
        self.config = config
        self.storage = storage

    def authenticate(self, service_key: str) -> ServiceKeyRecord:
        candidate = str(service_key or "").strip()
        if not candidate:
            raise CloudServiceError("缺少 Service Key", status_code=401, code="missing_service_key")
        record = self.storage.get_service_key(candidate)
        if record is None:
            raise CloudServiceError("无效的 Service Key", status_code=401, code="invalid_service_key")
        if not record.enabled:
            raise CloudServiceError("Service Key 已禁用", status_code=403, code="service_key_disabled")
        return record

    def upload_reference(self, service_key: str, file_name: str, audio_bytes: bytes, prompt_text: str, prompt_language: str, mime_type: str) -> dict[str, Any]:
        self.authenticate(service_key)
        if not audio_bytes:
            raise CloudServiceError("参考音频不能为空", status_code=400, code="empty_reference_audio")
        prompt = str(prompt_text or "").strip()
        if not prompt:
            raise CloudServiceError("prompt_text 不能为空", status_code=400, code="empty_prompt_text")
        language = str(prompt_language or "zh").strip() or "zh"
        refer_hash = sha256_hex(audio_bytes)
        saved_path = persist_reference_file(self.config.reference_root, refer_hash, file_name, audio_bytes)
        record = self.storage.upsert_reference(
            refer_hash=refer_hash,
            file_name=safe_file_name(file_name),
            file_path=str(saved_path),
            prompt_text=prompt,
            prompt_language=language,
            mime_type=str(mime_type or "audio/wav"),
        )
        return {
            "refer_hash": record.refer_hash,
            "file_name": record.file_name,
            "prompt_text": record.prompt_text,
            "prompt_language": record.prompt_language,
            "created_at": record.created_at,
        }

    def get_reference(self, service_key: str, refer_hash: str) -> dict[str, Any]:
        self.authenticate(service_key)
        candidate = str(refer_hash or "").strip()
        if not candidate:
            raise CloudServiceError("refer_hash 不能为空", status_code=400, code="missing_refer_hash")
        reference = self.storage.get_reference(candidate)
        if reference is None:
            raise CloudServiceError("未找到对应的参考音频", status_code=404, code="reference_not_found")
        return {
            "refer_hash": reference.refer_hash,
            "file_name": reference.file_name,
            "file_path": reference.file_path,
            "prompt_text": reference.prompt_text,
            "prompt_language": reference.prompt_language,
            "mime_type": reference.mime_type,
            "created_at": reference.created_at,
            "exists": Path(reference.file_path).exists(),
        }

    def find_reference_by_signature(self, service_key: str, signature: str) -> dict[str, Any] | None:
        self.authenticate(service_key)
        candidate = str(signature or "").strip()
        if not candidate:
            raise CloudServiceError("signature 不能为空", status_code=400, code="missing_signature")
        record = self.storage.get_reference(candidate)
        if record is None:
            return None
        return {
            "refer_hash": record.refer_hash,
            "file_name": record.file_name,
            "prompt_text": record.prompt_text,
            "prompt_language": record.prompt_language,
            "mime_type": record.mime_type,
            "created_at": record.created_at,
            "exists": Path(record.file_path).exists(),
        }

    def synthesize_tts(self, service_key: str, request: TtsRequest) -> tuple[bytes, str, dict[str, float]]:
        service_key_record = self.authenticate(service_key)
        text = str(request.text or "").strip()
        if not text:
            raise CloudServiceError("TTS 文本不能为空", status_code=400, code="empty_tts_text")
        point_units = count_tts_point_units(text)
        if point_units <= 0:
            raise CloudServiceError("TTS 文本没有可计费字符", status_code=400, code="empty_billable_text")

        reference = self._resolve_reference(request.refer_hash)
        usage_before = self._ensure_usage_available(service_key_record.service_key, point_units)
        payload = {
            "refer_wav_path": reference.file_path,
            "prompt_text": str(request.prompt_text or reference.prompt_text),
            "prompt_language": str(request.prompt_language or reference.prompt_language),
            "text": text,
            "text_language": str(request.text_language or "zh"),
        }
        audio_bytes, content_type = self._forward_tts_request(payload)
        self.storage.record_usage(
            service_key=service_key_record.service_key,
            category="tts",
            point_units=point_units,
            request_units=len(text),
            request_id=reference.refer_hash,
            metadata_json=json.dumps({"refer_hash": reference.refer_hash, "text_language": payload["text_language"]}, ensure_ascii=False),
        )
        usage_after = self.storage.get_usage_snapshot(
            service_key_record.service_key,
            hourly_limit_units=self.config.hourly_limit_points * POINT_SCALE,
            daily_limit_units=self.config.daily_limit_points * POINT_SCALE,
        )
        return audio_bytes, content_type, usage_after.to_dict()

    def transcribe_asr(self, service_key: str, file_name: str, audio_bytes: bytes, mime_type: str) -> dict[str, Any]:
        service_key_record = self.authenticate(service_key)
        if not audio_bytes:
            raise CloudServiceError("ASR 音频不能为空", status_code=400, code="empty_asr_audio")
        try:
            duration_seconds = measure_wav_duration_seconds(audio_bytes)
        except Exception as exc:
            raise CloudServiceError(f"无法解析 WAV 时长: {exc}", status_code=400, code="invalid_wav_audio") from exc
        point_units = count_asr_point_units(duration_seconds)
        self._ensure_usage_available(service_key_record.service_key, point_units)
        payload = self._forward_asr_request(file_name, audio_bytes, mime_type)
        self.storage.record_usage(
            service_key=service_key_record.service_key,
            category="asr",
            point_units=point_units,
            request_units=duration_seconds,
            request_id=safe_file_name(file_name),
            metadata_json=json.dumps({"duration_seconds": round(duration_seconds, 3)}, ensure_ascii=False),
        )
        usage_after = self.storage.get_usage_snapshot(
            service_key_record.service_key,
            hourly_limit_units=self.config.hourly_limit_points * POINT_SCALE,
            daily_limit_units=self.config.daily_limit_points * POINT_SCALE,
        )
        payload["billing"] = {
            "charged_points": format_points(point_units),
            "duration_seconds": round(duration_seconds, 3),
            "usage": usage_after.to_dict(),
        }
        return payload

    def _resolve_reference(self, refer_hash: str) -> ReferenceRecord:
        candidate = str(refer_hash or "").strip()
        if not candidate:
            raise CloudServiceError("refer_hash 不能为空", status_code=400, code="missing_refer_hash")
        reference = self.storage.get_reference(candidate)
        if reference is None:
            raise CloudServiceError("未找到对应的参考音频", status_code=404, code="reference_not_found")
        if not Path(reference.file_path).exists():
            raise CloudServiceError("参考音频文件不存在", status_code=404, code="reference_file_missing")
        return reference

    def _ensure_usage_available(self, service_key: str, request_units: int):
        usage = self.storage.get_usage_snapshot(
            service_key,
            hourly_limit_units=self.config.hourly_limit_points * POINT_SCALE,
            daily_limit_units=self.config.daily_limit_points * POINT_SCALE,
        )
        if usage.hourly_units + request_units > usage.hourly_limit_units:
            raise CloudServiceError("超过每小时额度限制", status_code=429, code="hourly_limit_exceeded")
        if usage.daily_units + request_units > usage.daily_limit_units:
            raise CloudServiceError("超过每日额度限制", status_code=429, code="daily_limit_exceeded")
        return usage

    def _forward_tts_request(self, payload: dict[str, Any]) -> tuple[bytes, str]:
        endpoint = self.config.gpt_sovits_base_url.rstrip("/") + "/"
        response = requests.post(endpoint, json=payload, timeout=self.config.request_timeout_seconds)
        if not response.ok:
            raise CloudServiceError(
                f"GPT-SoVITS 上游错误: {response.status_code} {response.text}",
                status_code=502,
                code="tts_upstream_error",
            )
        return response.content, response.headers.get("content-type") or "audio/wav"

    def _forward_asr_request(self, file_name: str, audio_bytes: bytes, mime_type: str) -> dict[str, Any]:
        endpoint = self.config.funasr_base_url.rstrip("/") + "/v1/upload_audio"
        response = requests.post(
            endpoint,
            files={"file": (safe_file_name(file_name), audio_bytes, str(mime_type or "audio/wav"))},
            timeout=self.config.request_timeout_seconds,
        )
        if not response.ok:
            raise CloudServiceError(
                f"FunASR 上游错误: {response.status_code} {response.text}",
                status_code=502,
                code="asr_upstream_error",
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise CloudServiceError(f"FunASR 返回非 JSON: {response.text}", status_code=502, code="asr_upstream_invalid_json") from exc
        if isinstance(payload, dict) and payload.get("status") == "error":
            raise CloudServiceError(str(payload.get("message") or "FunASR 识别失败"), status_code=502, code="asr_upstream_failed")
        if not isinstance(payload, dict):
            raise CloudServiceError("FunASR 返回格式错误", status_code=502, code="asr_upstream_invalid_body")
        return payload