from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket

from pidgin.voice.session import handle_voice_session

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.websocket("/ws")
async def voice_ws(
    ws: WebSocket,
    stt: str | None = Query(default=None),
    tts: str | None = Query(default=None),
) -> None:
    """WebSocket voice session. Query params: ?stt=openai&tts=elevenlabs

    stt=openai          — Whisper batch (WebM/Opus, client VAD)
    stt=openai_realtime — gpt-realtime-whisper relay (PCM16/24kHz, server VAD)
    tts=elevenlabs      — ElevenLabs streaming (default)
    tts=openai          — OpenAI TTS-1 streaming
    """
    await handle_voice_session(ws, stt=stt, tts=tts)
