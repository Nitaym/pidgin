from __future__ import annotations

import sqlite3
from typing import Literal, Protocol

from pidgin.connectors.types import (
    ConnectorMetadata,
    HealthStatus,
    PrincipalContext,
    ReadResult,
    ResourceUri,
    WritePayload,
    WriteResult,
)

WriteMode = Literal["draft", "execute"]


class ConnectorProtocol(Protocol):
    connector_type: str
    installation_id: str | None

    def metadata(self) -> ConnectorMetadata: ...

    def read(
        self,
        conn: sqlite3.Connection,
        resource: ResourceUri,
        *,
        principal: PrincipalContext,
    ) -> ReadResult: ...

    def write(
        self,
        conn: sqlite3.Connection,
        resource: ResourceUri,
        payload: WritePayload,
        *,
        principal: PrincipalContext,
        mode: WriteMode,
    ) -> WriteResult: ...

    def health_check(self, conn: sqlite3.Connection) -> HealthStatus: ...
