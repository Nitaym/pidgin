from __future__ import annotations

import os

from pidgin.voice.providers.base import STTProvider, TTSProvider


def get_stt(backend: str | None = None) -> STTProvider:
    name = (backend or os.getenv("PIDGIN_STT_BACKEND", "openai")).lower()
    if name == "openai":
        from pidgin.voice.providers.openai_stt import OpenAISTTProvider
        return OpenAISTTProvider()
    if name == "openai_realtime":
        from pidgin.voice.providers.openai_realtime_stt import OpenAIRealtimeSTTProvider
        return OpenAIRealtimeSTTProvider()
    if name == "elevenlabs":
        from pidgin.voice.providers.elevenlabs_stt import ElevenLabsSTTProvider
        return ElevenLabsSTTProvider()
    raise ValueError(f"Unknown STT backend: {name!r}")


def get_tts(backend: str | None = None, voice: str | None = None) -> TTSProvider:
    from pidgin.voice.catalog import resolve_voice

    name = (backend or os.getenv("PIDGIN_TTS_BACKEND", "elevenlabs")).lower()
    resolved = resolve_voice(voice, name)
    if name == "elevenlabs":
        from pidgin.voice.providers.elevenlabs_tts import ElevenLabsTTSProvider
        return ElevenLabsTTSProvider(voice_id=resolved)
    if name == "openai":
        from pidgin.voice.providers.openai_tts import OpenAITTSProvider
        return OpenAITTSProvider(voice=resolved or "alloy")
    raise ValueError(f"Unknown TTS backend: {name!r}")
