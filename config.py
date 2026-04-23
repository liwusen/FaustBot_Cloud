from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parent
DATA_ROOT = PACKAGE_ROOT / "data"
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "cloud.config.json"


@dataclass(slots=True)
class CloudConfig:
    host: str = "127.0.0.1"
    port: int = 18980
    database_path: str = str(DATA_ROOT / "cloud_inference.sqlite3")
    reference_dir: str = str(DATA_ROOT / "references")
    gpt_sovits_base_url: str = "http://127.0.0.1:5000"
    funasr_base_url: str = "http://127.0.0.1:1000"
    request_timeout_seconds: int = 120
    hourly_limit_points: int = 1500
    daily_limit_points: int = 5000
    root_key: str = ""
    cors_allow_origins: list[str] = field(default_factory=lambda: ["*"])
    # GitHub OAuth
    github_oauth_enabled: bool = False
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    github_oauth_callback_url: str = ""
    github_oauth_scopes: list[str] = field(default_factory=lambda: ["read:user"])
    github_api_base: str = "https://api.github.com"

    @property
    def database_file(self) -> Path:
        return Path(self.database_path).expanduser().resolve()

    @property
    def reference_root(self) -> Path:
        return Path(self.reference_dir).expanduser().resolve()


def _normalize_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if "cors_allow_origins" in normalized and not isinstance(normalized["cors_allow_origins"], list):
        raw = str(normalized["cors_allow_origins"] or "").strip()
        normalized["cors_allow_origins"] = [item.strip() for item in raw.split(",") if item.strip()] or ["*"]
    return normalized


def ensure_config_exists(config_path: Path | None = None) -> Path:
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    save_config(CloudConfig(), path)
    return path


def load_config(config_path: Path | None = None) -> CloudConfig:
    path = ensure_config_exists(config_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return CloudConfig(**_normalize_config_payload(data))


def save_config(config: CloudConfig, config_path: Path | None = None) -> Path:
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def update_config(updates: dict[str, Any], config_path: Path | None = None) -> CloudConfig:
    current = load_config(config_path)
    payload = asdict(current)
    payload.update(_normalize_config_payload(updates))
    updated = CloudConfig(**payload)
    save_config(updated, config_path)
    return updated