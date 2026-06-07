from __future__ import annotations

import asyncio
import base64
import os

import openai


# ~1 second of PCM16 at 24 kHz per append event
_CHUNK_BYTES = 48000


class OpenAIRealtimeSTTProvider:
    """Streaming STT via OpenAI Realtime API.

    Requires PCM16 audio at 24 kHz mono from the browser.
    The frontend must use AudioContext/ScriptProcessor recording (not MediaRecorder)
    and send mime_type="audio/pcm;rate=24000".
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key or os.environ["OPENAI_API_KEY"]
        )

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        if not mime_type.startswith("audio/pcm"):
            raise ValueError(
                f"OpenAI Realtime STT requires PCM16/24 kHz audio, got {mime_type!r}. "
                "Switch to 'OpenAI Whisper' in settings, or enable PCM recording mode."
            )

        transcript = ""

        async with self._client.beta.realtime.connect(
            model="gpt-4o-realtime-preview",
        ) as conn:
            # Transcription-only: text modality, no audio output, no server VAD
            await conn.session.update(session={  # type: ignore[arg-type]
                "modalities": ["text"],
                "input_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": None,
            })

            # Stream audio in ~1s chunks to avoid oversized frames
            for start in range(0, len(audio), _CHUNK_BYTES):
                chunk_b64 = base64.b64encode(audio[start : start + _CHUNK_BYTES]).decode()
                await conn.input_audio_buffer.append(audio=chunk_b64)  # type: ignore[arg-type]

            await conn.input_audio_buffer.commit()  # type: ignore[attr-defined]
            await conn.response.create()  # type: ignore[attr-defined]

            async with asyncio.timeout(20):
                async for event in conn:
                    t = event.type
                    if t == "conversation.item.input_audio_transcription.completed":
                        transcript = getattr(event, "transcript", "")
                        break
                    if t in ("response.done", "error"):
                        break

        return transcript.strip()
