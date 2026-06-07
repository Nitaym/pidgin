from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx


class ElevenLabsTTSProvider:
    """Text-to-speech via ElevenLabs streaming API."""

    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(
        self,
        voice_id: str | None = None,
        model_id: str = "eleven_turbo_v2_5",
        api_key: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ["ELEVENLABS_API_KEY"]
        self._voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
        self._model_id = model_id

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        url = f"{self.BASE_URL}/text-to-speech/{self._voice_id}/stream"
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": self._model_id,
            "output_format": "mp3_44100_128",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=4096):
                    yield chunk

    # Make the class directly usable as an async generator via __call__
    async def __call__(self, text: str) -> AsyncIterator[bytes]:
        return self.synthesize(text)
