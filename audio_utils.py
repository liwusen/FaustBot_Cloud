from __future__ import annotations

import hashlib
import io
import os
import wave
from pathlib import Path


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def guess_extension(filename: str, default: str = ".wav") -> str:
    suffix = Path(str(filename or "").strip()).suffix.lower()
    if suffix:
        return suffix
    return default


def measure_wav_duration_seconds(audio_bytes: bytes) -> float:
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        frame_count = wav_file.getnframes()
        frame_rate = wav_file.getframerate()
        if frame_rate <= 0:
            raise ValueError("无效的 WAV 采样率")
        return frame_count / float(frame_rate)


def persist_reference_file(reference_dir: Path, refer_hash: str, original_name: str, audio_bytes: bytes) -> Path:
    reference_dir.mkdir(parents=True, exist_ok=True)
    target = reference_dir / f"{refer_hash}{guess_extension(original_name)}"
    if not target.exists():
        target.write_bytes(audio_bytes)
    return target.resolve()


def safe_file_name(name: str) -> str:
    base = os.path.basename(str(name or "").strip())
    return base or "audio.wav"