from __future__ import annotations

import os
from collections.abc import AsyncIterator

import openai


class OpenAITTSProvider:
    """Text-to-speech via OpenAI tts-1 with streaming."""

    def __init__(
        self,
        model: str = "tts-1",
        voice: str = "alloy",
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._voice = voice
        self._client = openai.AsyncOpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        async with self._client.audio.speech.with_streaming_response.create(
            model=self._model,
            voice=self._voice,  # type: ignore[arg-type]
            input=text,
            response_format="mp3",
        ) as response:
            async for chunk in response.iter_bytes(chunk_size=4096):
                yield chunk
