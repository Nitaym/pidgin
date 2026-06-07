from __future__ import annotations


class ElevenLabsSTTProvider:
    """ElevenLabs STT — not yet available (no API key or public endpoint)."""

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        raise NotImplementedError(
            "ElevenLabs STT is not yet supported. "
            "Select 'OpenAI Whisper' or 'OpenAI Realtime' in voice settings."
        )
