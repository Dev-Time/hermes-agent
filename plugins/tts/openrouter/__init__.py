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
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.tts_provider import TTSProvider

logger = logging.getLogger(__name__)

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Defaults mirror the OpenRouter docs and the wizard preset. As of Aug 2026
# the OpenAI TTS models (gpt-4o-mini-tts-*) have been REMOVED from OpenRouter
# and the OpenAI-style voice names are invalid for the remaining Gemini model,
# so the default is Gemini with a Gemini voice.
DEFAULT_MODEL = "google/gemini-3.1-flash-tts-preview"
DEFAULT_VOICE = "Kore"

# OpenRouter/TTS response formats we actually request. The speech endpoint is
# MP3/PCM-native; anything else is coerced to mp3 (valid across the models that
# accept mp3). Gemini is the exception: it ONLY accepts response_format="pcm".
_SUPPORTED_RESPONSE_FORMATS = frozenset({"mp3", "wav"})

# Gemini TTS only accepts response_format="pcm", which returns raw 24 kHz
# 16-bit mono little-endian PCM samples with NO container. We wrap those bytes
# in a minimal WAV RIFF header so the result is playable and re-encodable by
# the downstream ffmpeg (voice-bubble) pipeline.
GEMINI_RESPONSE_FORMAT = "pcm"
GEMINI_SAMPLE_RATE = 24000
GEMINI_CHANNELS = 1
GEMINI_SAMPLE_WIDTH = 2  # 16-bit PCM (L16)
# Gemini uses proper names (not OpenAI-style alloy/coral/...). Passing one of
# the OpenAI names (or unset) to a Gemini model 404s at the provider.
_GEMINI_VOICES = frozenset({
    "Kore", "Puck", "Charon", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr",
})
DEFAULT_GEMINI_VOICE = "Kore"


class OpenRouterTTSProvider(TTSProvider):
    """Text-to-speech via OpenRouter's OpenAI-compatible /audio/speech."""

    name = "openrouter"

    @property
    def display_name(self) -> str:
        return "OpenRouter"

    @property
    def voice_compatible(self) -> bool:
        """Gemini output is wrapped as WAV, so it's safe for voice-bubble
        delivery — the gateway's pipeline converts it to Opus via ffmpeg."""
        return True

    def _api_key(self) -> str:
        import os

        return (os.environ.get("OPENROUTER_API_KEY") or "").strip()

    def is_available(self) -> bool:
        # The openai Python package is a hard dependency already (used by the
        # built-in openai TTS provider), so we only gate on the key.
        return bool(self._api_key())

    def list_models(self) -> List[Dict[str, Any]]:
        # Valid OpenRouter "Speech" models as of Aug 2026. The OpenAI TTS
        # models (gpt-4o-mini-tts-*) were removed from the catalog.
        return [
            {
                "id": "google/gemini-3.1-flash-tts-preview",
                "display": "Gemini 3.1 Flash TTS",
                "languages": ["70+"],
                "max_text_length": 4096,
            },
            {
                "id": "x-ai/grok-voice-tts-1.0",
                "display": "Grok Voice TTS 1.0",
                "languages": ["20+"],
                "max_text_length": 15000,
            },
            {
                "id": "qwen/qwen-audio-3.0-tts-flash",
                "display": "Qwen-Audio-3.0-TTS Flash",
                "max_text_length": 4096,
            },
            {
                "id": "mistralai/voxtral-mini-tts-2603",
                "display": "Voxtral Mini TTS",
                "languages": ["multilingual"],
                "max_text_length": 4096,
            },
            {
                "id": "qwen/qwen-audio-3.0-tts-plus",
                "display": "Qwen-Audio-3.0-TTS Plus",
                "max_text_length": 4096,
            },
        ]

    def list_voices(self) -> List[Dict[str, Any]]:
        # Voices differ by model family. The default model is Gemini (proper
        # names); lead with Gemini's voices, then the OpenRouter cross-model
        # set for models that still accept them.
        return [
            {"id": "Kore", "display": "Kore — Gemini (balanced)"},
            {"id": "Puck", "display": "Puck — Gemini (upbeat)"},
            {"id": "Charon", "display": "Charon — Gemini (calm)"},
            {"id": "Fenrir", "display": "Fenrir — Gemini (deep)"},
            {"id": "Aoede", "display": "Aoede — Gemini (lyrical)"},
            {"id": "alloy", "display": "Alloy — balanced (mp3 models)"},
            {"id": "coral", "display": "Coral — warm (mp3 models)"},
            {"id": "nova", "display": "Nova — bright (mp3 models)"},
            {"id": "echo", "display": "Echo — deep (mp3 models)"},
            {"id": "shimmer", "display": "Shimmer — soft (mp3 models)"},
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

    def default_model(self) -> Optional[str]:
        """Return the default model id (gemini-3.1-flash-tts-preview)."""
        return DEFAULT_MODEL

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
        is_gemini = "gemini" in model_id.lower()

        if is_gemini:
            # Gemini TTS ONLY accepts response_format="pcm" and uses proper
            # voice names — an OpenAI-style voice (e.g. "alloy") 404s.
            response_format = GEMINI_RESPONSE_FORMAT
            if voice in _GEMINI_VOICES:
                voice_id = voice
            else:
                voice_id = DEFAULT_GEMINI_VOICE
        else:
            response_format = str(format).lower() if format else "mp3"
            # OpenRouter's /audio/speech is MP3/PCM-native. Coerce opus/ogg etc.
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

        if is_gemini:
            # Raw PCM came back (no container). Wrap as WAV so the file is
            # playable and the downstream ffmpeg pipeline can transcode it.
            raw = Path(output_path).read_bytes()
            wav = _wrap_pcm_as_wav(raw)
            if output_path.lower().endswith(".wav"):
                wav_path = output_path
            else:
                wav_path = os.path.splitext(output_path)[0] + ".wav"
            Path(wav_path).write_bytes(wav)
            return wav_path

        return output_path


def _wrap_pcm_as_wav(
    pcm_bytes: bytes,
    sample_rate: int = GEMINI_SAMPLE_RATE,
    channels: int = GEMINI_CHANNELS,
    sample_width: int = GEMINI_SAMPLE_WIDTH,
) -> bytes:
    """Wrap raw signed little-endian PCM with a standard WAV RIFF header.

    OpenRouter/Gemini TTS returns ``audio/L16;codec=pcm;rate=24000`` — raw PCM
    samples with no container. Add a minimal WAV header so the file is playable
    and ffmpeg can re-encode it to MP3/Opus downstream.
    """
    import struct

    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    data_size = len(pcm_bytes)
    fmt_chunk = struct.pack(
        "<4sIHHIIHH",
        b"fmt ",
        16,             # fmt chunk size (PCM)
        1,              # audio format (PCM)
        channels,
        sample_rate,
        byte_rate,
        block_align,
        sample_width * 8,
    )
    data_chunk_header = struct.pack("<4sI", b"data", data_size)
    riff_size = 4 + len(fmt_chunk) + len(data_chunk_header) + data_size
    riff_header = struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE")
    return riff_header + fmt_chunk + data_chunk_header + pcm_bytes


def register(ctx: Any) -> None:
    """Wire the OpenRouter TTS provider into the TTS provider registry."""
    ctx.register_tts_provider(OpenRouterTTSProvider())
