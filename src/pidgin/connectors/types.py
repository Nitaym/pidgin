from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pidgin.types import TrustLabel

ConnectorType = Literal[
    "pidgin_chat",
    "slack",
    "gmail",
    "google_drive",
    "google_meet",
    "zoom",
]

AuthMode = Literal["oauth2", "manual", "none"]


@dataclass(frozen=True)
class ResourceUri:
    prefix: str
    kind: str
    resource_id: str
    query: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        base = f"{self.prefix}:{self.kind}/{self.resource_id}"
        if not self.query:
            return base
        q = "&".join(f"{k}={v}" for k, v in sorted(self.query.items()))
        return f"{base}?{q}"


@dataclass(frozen=True)
class PrincipalContext:
    principal_id: str
    display_name: str
    trust_label: TrustLabel


@dataclass(frozen=True)
class ConnectorMetadata:
    connector_type: str
    display_name: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class ReadResult:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WritePayload:
    text: str | None = None
    subject: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WriteResult:
    handle: str
    external_ref: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    message: str
