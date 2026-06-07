from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class STTProvider(Protocol):
    async def transcribe(self, audio: bytes, mime_type: str) -> str: ...


class TTSProvider(Protocol):
    async def synthesize(self, text: str) -> AsyncIterator[bytes]: ...
