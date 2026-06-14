from __future__ import annotations

"""
Voice preset catalog
====================

Stable, provider-agnostic preset keys that the frontend stores per agent
(in hire customization) and sends on the voice WebSocket as ?voice=<key>.
Each preset maps to a concrete voice for every supported TTS backend:

  - openai:     built-in voice name (alloy, echo, onyx, nova, shimmer, …)
  - elevenlabs: premade voice id

Unknown keys are passed through raw, so a provider-specific voice name/id
can be used directly as an escape hatch.
"""

VOICE_PRESETS: dict[str, dict[str, str]] = {
    "female_warm": {
        "label": "Warm (female)",
        "gender": "female",
        "openai": "nova",
        "elevenlabs": "21m00Tcm4TlvDq8ikWAM",  # Rachel
    },
    "female_bright": {
        "label": "Bright (female)",
        "gender": "female",
        "openai": "shimmer",
        "elevenlabs": "EXAVITQu4vr4xnSDxMaL",  # Sarah
    },
    "male_deep": {
        "label": "Deep (male)",
        "gender": "male",
        "openai": "onyx",
        "elevenlabs": "JBFqnCBsd6RMkjVDRZzb",  # George
    },
    "male_casual": {
        "label": "Casual (male)",
        "gender": "male",
        "openai": "echo",
        "elevenlabs": "pNInz6obpgDQGcFmaJgB",  # Adam
    },
    "neutral": {
        "label": "Neutral",
        "gender": "",
        "openai": "alloy",
        "elevenlabs": "Xb7hH8MSUJpSbSDYk0k2",  # Alice
    },
}


def resolve_voice(voice: str | None, backend: str) -> str | None:
    """Map a preset key to the backend-specific voice.

    Returns None when no voice was requested (provider uses its default).
    Unknown keys are returned as-is so raw provider voices keep working.
    """
    if not voice:
        return None
    preset = VOICE_PRESETS.get(voice)
    if preset is None:
        return voice
    return preset.get(backend) or None
