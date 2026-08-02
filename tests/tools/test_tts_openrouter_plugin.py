"""Tests for the bundled OpenRouter TTS plugin (plugins/tts/openrouter).

Covers the provider contract on the ABC and the plugin's registration hook:

- is_available() gates on OPENROUTER_API_KEY
- synthesize() builds an OpenAI client pointed at OpenRouter's
  /audio/speech base URL and streams audio to disk (mocked client)
- format coercion: OpenRouter's speech endpoint is MP3/PCM-native, so
  ogg/opus requests are coerced to mp3 rather than sent unsupported
- per-call voice/model/speed overrides win over plugin defaults
- register() wires the provider into the TTS registry via the ctx hook
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from plugins.tts.openrouter import (
    DEFAULT_MODEL,
    DEFAULT_OPENROUTER_BASE_URL,
    DEFAULT_VOICE,
    OpenRouterTTSProvider,
)


@pytest.fixture
def provider() -> OpenRouterTTSProvider:
    return OpenRouterTTSProvider()


class TestAvailability:
    def test_unavailable_without_key(self, provider, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        assert provider.is_available() is False

    def test_available_with_key(self, provider, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        assert provider.is_available() is True


class TestSynthesize:
    def _fake_openai(self, monkeypatch):
        """Inject a fake openai module so synthesize() can import it w/o dep."""
        import sys
        import types

        fake_speech = MagicMock()
        fake_speech.create.return_value.stream_to_file = MagicMock()

        captured = {}

        class _FakeAudio:
            speech = fake_speech

        class _FakeClient:
            def __init__(self, *a, **kw):
                captured.update(kw)
                self.audio = _FakeAudio()
                self.closed = False

            def close(self):
                self.closed = True

        openai_mod = types.ModuleType("openai")
        openai_mod.OpenAI = _FakeClient
        monkeypatch.setitem(sys.modules, "openai", openai_mod)
        return fake_speech, captured

    def test_synthesize_happy_path(self, provider, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        fake_speech, captured = self._fake_openai(monkeypatch)

        out = tmp_path / "out.mp3"
        result = provider.synthesize("hello", str(out))

        assert result == str(out)
        # Client was pointed at OpenRouter (not api.openai.com).
        assert captured["base_url"] == DEFAULT_OPENROUTER_BASE_URL
        assert captured["api_key"] == "sk-or-test"
        # Defaults applied.
        kwargs = fake_speech.create.call_args.kwargs
        assert kwargs["model"] == DEFAULT_MODEL
        assert kwargs["voice"] == DEFAULT_VOICE
        assert kwargs["input"] == "hello"
        assert kwargs["response_format"] == "mp3"
        fake_speech.create.return_value.stream_to_file.assert_called_once_with(str(out))

    def test_synthesize_uses_overrides(self, provider, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        fake_speech, _ = self._fake_openai(monkeypatch)

        out = tmp_path / "x.mp3"
        provider.synthesize(
            "hi", str(out),
            voice="nova", model="google/gemini-3.1-flash-tts-preview", speed=1.5,
        )
        kwargs = fake_speech.create.call_args.kwargs
        assert kwargs["voice"] == "nova"
        assert kwargs["model"] == "google/gemini-3.1-flash-tts-preview"
        assert kwargs["speed"] == 1.5

    @pytest.mark.parametrize(
        ["requested", "coerced"],
        [("ogg", "mp3"), ("opus", "mp3"), ("flac", "mp3"), ("wav", "wav"), ("mp3", "mp3")],
    )
    def test_format_coercion(self, provider, monkeypatch, tmp_path, requested, coerced):
        """OpenRouter speech is MP3/PCM-native; opus/ogg/etc. coerce to mp3."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        fake_speech, _ = self._fake_openai(monkeypatch)

        out = tmp_path / f"out.{requested}"
        provider.synthesize("hi", str(out), format=requested)
        kwargs = fake_speech.create.call_args.kwargs
        assert kwargs["response_format"] == coerced

    def test_raises_without_key(self, provider, monkeypatch, tmp_path):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY not set"):
            provider.synthesize("hi", str(tmp_path / "out.mp3"))


class TestRegisterHook:
    def test_register_wires_provider_into_registry(self, monkeypatch):
        from agent import tts_registry
        from agent.tts_provider import TTSProvider

        tts_registry._reset_for_tests()
        try:
            class _Ctx:
                def __init__(self):
                    self.registered = None

                def register_tts_provider(self, provider):
                    self.registered = provider

            ctx = _Ctx()
            from plugins.tts.openrouter import register

            register(ctx)

            assert isinstance(ctx.registered, TTSProvider)
            assert ctx.registered.name == "openrouter"
        finally:
            tts_registry._reset_for_tests()

    def test_name_not_a_builtin(self):
        """openrouter must not collide with a built-in TTS provider name."""
        from agent import tts_registry

        assert "openrouter" not in tts_registry._BUILTIN_NAMES
        assert "openrouter" not in (
            "edge", "openai", "elevenlabs", "minimax", "xai",
            "mistral", "gemini", "neutts", "kittentts", "piper", "deepinfra",
        )


class TestSchema:
    def test_setup_schema_prompts_for_openrouter_key(self, provider):
        schema = provider.get_setup_schema()
        assert schema["name"] == "OpenRouter"
        env_keys = [v["key"] for v in schema["env_vars"]]
        assert "OPENROUTER_API_KEY" in env_keys

    def test_default_model(self, provider):
        assert provider.default_model() == DEFAULT_MODEL
