from __future__ import annotations

"""
Voice WebSocket session protocol
=================================

Standard mode (stt=openai / default):
  Buffer audio chunks → end_of_utterance → Whisper → transcript.

Realtime mode (stt=openai_realtime):
  Backend opens a persistent WebSocket to OpenAI Realtime (gpt-realtime-whisper).
  PCM16/24kHz audio is streamed from the browser and forwarded directly.
  OpenAI server VAD detects utterance boundaries and returns transcript events.

Web Speech mode (stt=web_speech):
  STT is handled entirely in the browser. Backend is TTS-only.

Backend calls / meetings:
  Same providers, driven server-side via the STT registry.

Client → Server (JSON):
  {"type": "audio_chunk", "data": "<base64>", "mime_type": "..."}
  {"type": "end_of_utterance"}           — standard mode only
  {"type": "synthesize", "text": "..."}  — TTS → stream MP3 back
  {"type": "ping"}

Server → Client (JSON):
  {"type": "transcript", "text": "..."}
  {"type": "transcript_delta", "text": "..."}  — realtime mode only
  {"type": "audio_chunk", "data": "<base64 mp3>"}
  {"type": "audio_done"}
  {"type": "error", "message": "..."}
  {"type": "pong"}
"""

import asyncio
import base64
import json
import logging
import os

from fastapi import WebSocket, WebSocketDisconnect

from pidgin.voice.providers.base import TTSProvider
from pidgin.voice.registry import get_stt, get_tts

log = logging.getLogger(__name__)


async def handle_voice_session(ws: WebSocket, stt: str | None, tts: str | None) -> None:
    await ws.accept()

    stt_backend = (stt or os.getenv("PIDGIN_STT_BACKEND", "openai")).lower()

    # web_speech is handled entirely in the browser — treat as whisper on backend
    if stt_backend == "web_speech":
        stt_backend = "openai"

    # Resolve TTS provider up-front so config errors reach the client
    try:
        tts_provider = get_tts(tts)
    except (KeyError, ValueError) as exc:
        key = str(exc).strip("'")
        await ws.send_text(json.dumps({
            "type": "error",
            "message": f"TTS not configured: environment variable {key} is missing.",
        }))
        return

    if stt_backend == "openai_realtime":
        await _realtime_session(ws, tts_provider)
    else:
        await _standard_session(ws, stt_backend, tts_provider)


# ---------------------------------------------------------------------------
# Standard session — buffer audio → STT on end_of_utterance
# ---------------------------------------------------------------------------

async def _standard_session(ws: WebSocket, stt_backend: str, tts_provider: TTSProvider) -> None:
    try:
        stt_provider = get_stt(stt_backend)
    except (KeyError, ValueError) as exc:
        key = str(exc).strip("'")
        await ws.send_text(json.dumps({
            "type": "error",
            "message": f"STT not configured: environment variable {key} is missing.",
        }))
        return

    audio_buffer: list[bytes] = []
    mime_type = "audio/webm"

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            kind = msg.get("type")

            if kind == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

            elif kind == "audio_chunk":
                audio_buffer.append(base64.b64decode(msg["data"]))
                mime_type = msg.get("mime_type", mime_type)

            elif kind == "end_of_utterance":
                if not audio_buffer:
                    continue
                audio = b"".join(audio_buffer)
                audio_buffer.clear()
                try:
                    transcript = await stt_provider.transcribe(audio, mime_type)
                    if transcript:
                        await ws.send_text(json.dumps({"type": "transcript", "text": transcript}))
                except Exception as exc:
                    log.exception("STT error")
                    await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))

            elif kind == "synthesize":
                text = msg.get("text", "")
                if not text:
                    continue
                try:
                    async for chunk in tts_provider.synthesize(text):
                        encoded = base64.b64encode(chunk).decode()
                        await ws.send_text(json.dumps({"type": "audio_chunk", "data": encoded}))
                    await ws.send_text(json.dumps({"type": "audio_done"}))
                except Exception as exc:
                    log.exception("TTS error")
                    await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Standard voice session error")


# ---------------------------------------------------------------------------
# Realtime session — persistent WebSocket to OpenAI Realtime
# ---------------------------------------------------------------------------

_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-2"

_SESSION_CONFIG = {
    "type": "session.update",
    "session": {
        "type": "transcription",
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "transcription": {
                    "model": "gpt-realtime-whisper",
                    "language": "en",
                },
            }
        },
    },
}


async def _realtime_session(ws: WebSocket, tts_provider: TTSProvider) -> None:
    """Bridge browser ↔ OpenAI Realtime for streaming transcription."""
    import websockets

    api_key = os.environ["OPENAI_API_KEY"]
    stop = asyncio.Event()

    try:
        async with websockets.connect(
            _REALTIME_URL,
            additional_headers={"Authorization": f"Bearer {api_key}"},
        ) as oai:
            await oai.send(json.dumps(_SESSION_CONFIG))

            async def from_browser() -> None:
                try:
                    while not stop.is_set():
                        raw = await ws.receive_text()
                        msg = json.loads(raw)
                        kind = msg.get("type")

                        if kind == "audio_chunk":
                            await oai.send(json.dumps({
                                "type": "input_audio_buffer.append",
                                "audio": msg["data"],
                            }))
                        elif kind == "synthesize":
                            text = msg.get("text", "")
                            if text:
                                try:
                                    async for chunk in tts_provider.synthesize(text):
                                        enc = base64.b64encode(chunk).decode()
                                        await ws.send_text(json.dumps({"type": "audio_chunk", "data": enc}))
                                    await ws.send_text(json.dumps({"type": "audio_done"}))
                                except Exception as exc:
                                    log.exception("TTS error")
                                    await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
                        elif kind == "ping":
                            await ws.send_text(json.dumps({"type": "pong"}))
                except WebSocketDisconnect:
                    stop.set()
                except Exception:
                    log.exception("Browser→OAI relay error")
                    stop.set()

            async def from_oai() -> None:
                try:
                    async for raw in oai:
                        if stop.is_set():
                            break
                        event = json.loads(raw)
                        t = event.get("type", "")

                        if t == "conversation.item.input_audio_transcription.delta":
                            delta = event.get("delta", "")
                            if delta:
                                await ws.send_text(json.dumps({"type": "transcript_delta", "text": delta}))
                        elif t == "conversation.item.input_audio_transcription.completed":
                            transcript = event.get("transcript", "")
                            if transcript and transcript.strip():
                                await ws.send_text(json.dumps({"type": "transcript", "text": transcript.strip()}))
                        elif t == "error":
                            err = event.get("error", {})
                            log.error("OpenAI Realtime error: %s", err)
                            await ws.send_text(json.dumps({"type": "error", "message": str(err)}))
                            stop.set()
                except Exception:
                    log.exception("OAI→browser relay error")
                    stop.set()

            await asyncio.gather(from_browser(), from_oai())

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Realtime voice session error")
