from __future__ import annotations

import io
import os

import openai


class OpenAISTTProvider:
    """Batch STT via OpenAI Whisper."""

    def __init__(self, model: str = "whisper-1", api_key: str | None = None) -> None:
        self._model = model
        self._client = openai.AsyncOpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        buf = io.BytesIO(audio)
        buf.name = f"audio.{_ext_for_mime(mime_type)}"
        response = await self._client.audio.transcriptions.create(
            model=self._model, file=buf
        )
        return response.text


def _ext_for_mime(mime_type: str) -> str:
    mapping = {
        "audio/webm": "webm",
        "audio/ogg": "ogg",
        "audio/mp4": "mp4",
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/flac": "flac",
    }
    return mapping.get(mime_type.split(";")[0].strip(), "webm")
