from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from ulid import ULID


def new_ulid() -> str:
    return str(ULID())


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
