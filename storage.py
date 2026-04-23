from __future__ import annotations

import secrets
import sqlite3
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .billing import UsageSnapshot, daily_window_start, hourly_window_start, to_iso8601, utc_now


KEY_ALPHABET = string.ascii_lowercase + string.digits


@dataclass(slots=True)
class ServiceKeyRecord:
    service_key: str
    name: str
    note: str
    enabled: bool
    created_at: str


@dataclass(slots=True)
class ReferenceRecord:
    refer_hash: str
    file_name: str
    file_path: str
    prompt_text: str
    prompt_language: str
    mime_type: str
    created_at: str


class CloudStorage:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS service_keys (
                    service_key TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    github_id TEXT NOT NULL DEFAULT '',
                    github_login TEXT NOT NULL DEFAULT '',
                    github_email TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_key TEXT NOT NULL,
                    category TEXT NOT NULL,
                    point_units INTEGER NOT NULL,
                    request_units REAL NOT NULL DEFAULT 0,
                    request_id TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(service_key) REFERENCES service_keys(service_key)
                );
                CREATE INDEX IF NOT EXISTS idx_usage_events_key_created_at ON usage_events(service_key, created_at);
                CREATE TABLE IF NOT EXISTS references_cache (
                    refer_hash TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    prompt_language TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'audio/wav',
                    created_at TEXT NOT NULL
                );
                """
            )
            # Ensure github columns exist for compatibility with older DBs
            self._ensure_service_key_columns(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_service_key_columns(self, conn: sqlite3.Connection) -> None:
        # Ensure compatibility with older DBs by adding github columns if missing
        rows = conn.execute("PRAGMA table_info(service_keys)").fetchall()
        existing = {r[1] for r in rows}
        to_add = []
        if "github_id" not in existing:
            to_add.append("ALTER TABLE service_keys ADD COLUMN github_id TEXT NOT NULL DEFAULT ''")
        if "github_login" not in existing:
            to_add.append("ALTER TABLE service_keys ADD COLUMN github_login TEXT NOT NULL DEFAULT ''")
        if "github_email" not in existing:
            to_add.append("ALTER TABLE service_keys ADD COLUMN github_email TEXT NOT NULL DEFAULT ''")
        for stmt in to_add:
            conn.execute(stmt)

    def create_service_key(self, name: str = "", note: str = "") -> ServiceKeyRecord:
        while True:
            candidate = "FSK-" + "".join(secrets.choice(KEY_ALPHABET) for _ in range(23))
            try:
                with self._connect() as conn:
                    created_at = to_iso8601(utc_now())
                    conn.execute(
                        "INSERT INTO service_keys(service_key, name, note, enabled, created_at) VALUES (?, ?, ?, 1, ?)",
                        (candidate, str(name or ""), str(note or ""), created_at),
                    )
                return ServiceKeyRecord(candidate, str(name or ""), str(note or ""), True, created_at)
            except sqlite3.IntegrityError:
                continue

    def get_service_key_by_github_id(self, github_id: str) -> ServiceKeyRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT service_key, name, note, enabled, created_at FROM service_keys WHERE github_id = ?",
                (str(github_id or ""),),
            ).fetchone()
        return self._service_key_from_row(row) if row else None

    def link_service_key_to_github(self, service_key: str, github_id: str, github_login: str = "", github_email: str = "") -> bool:
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE service_keys SET github_id = ?, github_login = ?, github_email = ? WHERE service_key = ?",
                (str(github_id or ""), str(github_login or ""), str(github_email or ""), str(service_key or "")),
            )
        return result.rowcount > 0

    def create_or_get_service_key_for_github(self, github_id: str, github_login: str = "", github_email: str = "") -> ServiceKeyRecord:
        # Return existing service key bound to this github_id or create a new permanent key and bind it.
        existing = self.get_service_key_by_github_id(github_id)
        if existing:
            return existing
        # create new key and associate
        record = self.create_service_key(name=f"github:{github_login}", note=f"github:{github_id}")
        # link github info
        linked = False
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE service_keys SET github_id = ?, github_login = ?, github_email = ? WHERE service_key = ?",
                    (str(github_id or ""), str(github_login or ""), str(github_email or ""), str(record.service_key)),
                )
            linked = True
        except Exception:
            linked = False
        if not linked:
            # best-effort: return the created key even if linking failed
            return record
        return self.get_service_key(record.service_key)

    def list_service_keys(self) -> list[ServiceKeyRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT service_key, name, note, enabled, created_at FROM service_keys ORDER BY created_at DESC"
            ).fetchall()
        return [self._service_key_from_row(row) for row in rows]

    def get_service_key(self, service_key: str) -> ServiceKeyRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT service_key, name, note, enabled, created_at FROM service_keys WHERE service_key = ?",
                (str(service_key or ""),),
            ).fetchone()
        return self._service_key_from_row(row) if row else None

    def set_service_key_enabled(self, service_key: str, enabled: bool) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE service_keys SET enabled = ? WHERE service_key = ?",
                (1 if enabled else 0, str(service_key or "")),
            )
        return result.rowcount > 0

    def reset_usage(self, service_key: str) -> int:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM usage_events WHERE service_key = ?", (str(service_key or ""),))
        return int(result.rowcount or 0)

    def record_usage(
        self,
        service_key: str,
        category: str,
        point_units: int,
        request_units: float,
        request_id: str,
        metadata_json: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_events(service_key, category, point_units, request_units, request_id, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(service_key or ""),
                    str(category or ""),
                    int(point_units or 0),
                    float(request_units or 0.0),
                    str(request_id or ""),
                    str(metadata_json or "{}"),
                    to_iso8601(utc_now()),
                ),
            )

    def get_usage_snapshot(
        self,
        service_key: str,
        *,
        hourly_limit_units: int,
        daily_limit_units: int,
    ) -> UsageSnapshot:
        with self._connect() as conn:
            hourly_units = int(
                conn.execute(
                    "SELECT COALESCE(SUM(point_units), 0) FROM usage_events WHERE service_key = ? AND created_at >= ?",
                    (str(service_key or ""), to_iso8601(hourly_window_start())),
                ).fetchone()[0]
                or 0
            )
            daily_units = int(
                conn.execute(
                    "SELECT COALESCE(SUM(point_units), 0) FROM usage_events WHERE service_key = ? AND created_at >= ?",
                    (str(service_key or ""), to_iso8601(daily_window_start())),
                ).fetchone()[0]
                or 0
            )
        return UsageSnapshot(hourly_units, daily_units, hourly_limit_units, daily_limit_units)

    def upsert_reference(
        self,
        refer_hash: str,
        file_name: str,
        file_path: str,
        prompt_text: str,
        prompt_language: str,
        mime_type: str,
    ) -> ReferenceRecord:
        created_at = to_iso8601(utc_now())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO references_cache(refer_hash, file_name, file_path, prompt_text, prompt_language, mime_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(refer_hash) DO UPDATE SET
                    file_name = excluded.file_name,
                    file_path = excluded.file_path,
                    prompt_text = excluded.prompt_text,
                    prompt_language = excluded.prompt_language,
                    mime_type = excluded.mime_type
                """,
                (
                    str(refer_hash or ""),
                    str(file_name or ""),
                    str(file_path or ""),
                    str(prompt_text or ""),
                    str(prompt_language or "zh"),
                    str(mime_type or "audio/wav"),
                    created_at,
                ),
            )
        record = self.get_reference(refer_hash)
        if record is None:
            raise RuntimeError("reference upsert failed")
        return record

    def get_reference(self, refer_hash: str) -> ReferenceRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT refer_hash, file_name, file_path, prompt_text, prompt_language, mime_type, created_at FROM references_cache WHERE refer_hash = ?",
                (str(refer_hash or ""),),
            ).fetchone()
        return self._reference_from_row(row) if row else None

    def _service_key_from_row(self, row: sqlite3.Row) -> ServiceKeyRecord:
        return ServiceKeyRecord(
            service_key=str(row["service_key"]),
            name=str(row["name"] or ""),
            note=str(row["note"] or ""),
            enabled=bool(row["enabled"]),
            created_at=str(row["created_at"]),
        )

    def _reference_from_row(self, row: sqlite3.Row) -> ReferenceRecord:
        return ReferenceRecord(
            refer_hash=str(row["refer_hash"]),
            file_name=str(row["file_name"]),
            file_path=str(row["file_path"]),
            prompt_text=str(row["prompt_text"] or ""),
            prompt_language=str(row["prompt_language"] or "zh"),
            mime_type=str(row["mime_type"] or "audio/wav"),
            created_at=str(row["created_at"]),
        )