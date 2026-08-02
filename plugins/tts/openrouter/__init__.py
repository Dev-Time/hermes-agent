"""OpenRouter TTS backend.

OpenRouter exposes text-to-speech at ``POST /api/v1/audio/speech`` using the
same schema as OpenAI's ``audio.speech.create``, so the synthesis call reuses
the OpenAI client pointed at OpenRouter's base URL. This keeps the plugin
tiny: resolve credentials, build the client, stream audio bytes to disk.

The supported models (GPT-4o Mini TTS, Voxtral Mini, Gemini TTS, …) and
voices are those OpenRouter advertises for the ``/audio/speech`` endpoint,
not the chat ``/models`` catalog — so we don't query a live model list here
and instead expose the most common defaults, honoring per-call overrides.

OpenRouter's speech endpoint accepts MP3 (and PCM); it does not accept
Opus. We map ``ogg``/``opus`` requests to ``mp3`` and let the voice-bubble
delivery pipeline (which converts to Opus via ffmpeg when ``voice_compatible``
is set) handle Telegram-style delivery.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agent.tts_provider import TTSProvider

logger = logging.getLogger(__name__)

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Defaults mirror the OpenRouter docs and the wizard preset.
DEFAULT_MODEL = "openai/gpt-4o-mini-tts-2025-12-15"
DEFAULT_VOICE = "alloy"

# OpenRouter/TTS response formats we actually request. The speech endpoint is
# MP3/PCM-native; anything else is coerced to mp3 (valid across all models).
_SUPPORTED_RESPONSE_FORMATS = frozenset({"mp3", "wav"})


class OpenRouterTTSProvider(TTSProvider):
    """Text-to-speech via OpenRouter's OpenAI-compatible /audio/speech."""

    name = "openrouter"

    @property
    def display_name(self) -> str:
        return "OpenRouter"

    def _api_key(self) -> str:
        import os

        return (os.environ.get("OPENROUTER_API_KEY") or "").strip()

    def is_available(self) -> bool:
        # The openai Python package is a hard dependency already (used by the
        # built-in openai TTS provider), so we only gate on the key.
        return bool(self._api_key())

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": "openai/gpt-4o-mini-tts-2025-12-15",
                "display": "GPT-4o Mini TTS",
                "languages": ["en", "es", "fr", "de", "ja"],
                "max_text_length": 4096,
            },
            {
                "id": "google/gemini-3.1-flash-tts-preview",
                "display": "Gemini 3.1 Flash TTS",
                "max_text_length": 4096,
            },
            {
                "id": "mistralai/voxtral-mini-tts",
                "display": "Voxtral Mini TTS",
                "max_text_length": 4096,
            },
        ]

    def list_voices(self) -> List[Dict[str, Any]]:
        # Voices vary by model; alloy is the safe cross-model default. Expose
        # a small known set for the picker.
        return [
            {"id": "alloy", "display": "Alloy — balanced"},
            {"id": "coral", "display": "Coral — warm"},
            {"id": "stellar", "display": "Stellar — expressive"},
            {"id": "nova", "display": "Nova — bright"},
            {"id": "echo", "display": "Echo — deep"},
            {"id": "shimmer", "display": "Shimmer — soft"},
        ]

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "OpenRouter",
            "badge": "paid",
            "tag": "GPT-4o Mini TTS, Voxtral, Gemini TTS via OPENROUTER_API_KEY",
            "env_vars": [
                {
                    "key": "OPENROUTER_API_KEY",
                    "prompt": "OpenRouter API key",
                    "url": "https://openrouter.ai/keys",
                },
            ],
        }

    def synthesize(
        self,
        text: str,
        output_path: str,
        *,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        speed: Optional[float] = None,
        format: str = "mp3",  # noqa: A002 - ABC uses `format`
        **extra: Any,
    ) -> str:
        api_key = self._api_key()
        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY not set. Run `hermes setup` or set the "
                "env var directly, then select OpenRouter in `hermes tools` → "
                "Text-to-Speech."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - openai is a core dep
            raise ImportError(
                "OpenRouter TTS uses the 'openai' SDK but it isn't installed."
            ) from exc

        voice_id = voice or DEFAULT_VOICE
        model_id = model or DEFAULT_MODEL
        response_format = str(format).lower() if format else "mp3"
        # OpenRouter's /audio/speech is MP3/PCM-native. Coerce opus/ogg/etc.
        if response_format not in _SUPPORTED_RESPONSE_FORMATS:
            response_format = "mp3"

        client = OpenAI(api_key=api_key, base_url=DEFAULT_OPENROUTER_BASE_URL)
        try:
            create_kwargs: Dict[str, Any] = {
                "model": model_id,
                "voice": voice_id,
                "input": text,
                "response_format": response_format,
            }
            if speed is not None:
                create_kwargs["speed"] = max(0.25, min(4.0, float(speed)))
            response = client.audio.speech.create(**create_kwargs)
            response.stream_to_file(output_path)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

        return output_path


def register(ctx: Any) -> None:
    """Wire the OpenRouter TTS provider into the TTS provider registry."""
    ctx.register_tts_provider(OpenRouterTTSProvider())
