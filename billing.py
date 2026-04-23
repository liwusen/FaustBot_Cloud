from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


POINT_SCALE = 100
NON_CJK_UNITS = 15
CHINESE_UNITS = 100
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso8601(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def count_tts_point_units(text: str) -> int:
    total_units = 0
    for char in str(text or ""):
        if char.isspace():
            continue
        total_units += CHINESE_UNITS if _CJK_RE.match(char) else NON_CJK_UNITS
    return total_units


def count_asr_point_units(duration_seconds: float) -> int:
    seconds = max(0, math.ceil(float(duration_seconds or 0.0)))
    return seconds * POINT_SCALE


def format_points(point_units: int) -> float:
    return round(float(point_units or 0) / POINT_SCALE, 2)


@dataclass(slots=True)
class UsageSnapshot:
    hourly_units: int
    daily_units: int
    hourly_limit_units: int
    daily_limit_units: int

    def to_dict(self) -> dict[str, float]:
        return {
            "hourly_points": format_points(self.hourly_units),
            "daily_points": format_points(self.daily_units),
            "hourly_limit_points": format_points(self.hourly_limit_units),
            "daily_limit_points": format_points(self.daily_limit_units),
            "hourly_remaining_points": format_points(max(0, self.hourly_limit_units - self.hourly_units)),
            "daily_remaining_points": format_points(max(0, self.daily_limit_units - self.daily_units)),
        }


def hourly_window_start(now: datetime | None = None) -> datetime:
    current = now or utc_now()
    return current - timedelta(hours=1)


def daily_window_start(now: datetime | None = None) -> datetime:
    current = (now or utc_now()).astimezone(timezone.utc)
    return current.replace(hour=0, minute=0, second=0, microsecond=0)