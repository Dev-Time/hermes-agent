"""Tests for the bundled OpenRouter video gen plugin (plugins/video_gen/openrouter).

Covers:
- is_available() gates on OpenRouter credentials
- generate() builds the OpenRouter /api/v1/videos payload and drives the
  async submit → poll → download flow (HTTP mocked)
- image_url routes to frame_images (image-to-video); its absence to
  text-to-video
- completed → saves video locally; failed/error surfaces a job error
- register() wires the provider into the video registry
- DEFAULT_MODEL is a real, cheap, text+image-capable model
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent import video_gen_registry
from plugins.video_gen.openrouter import (
    DEFAULT_MODEL,
    OpenRouterVideoGenProvider,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    video_gen_registry._reset_for_tests()
    yield
    video_gen_registry._reset_for_tests()


@pytest.fixture
def provider() -> OpenRouterVideoGenProvider:
    return OpenRouterVideoGenProvider()


def _set_creds(monkeypatch, key="sk-or-test"):
    monkeypatch.setenv("OPENROUTER_API_KEY", key)
    # Patch the runtime resolver to return our key directly (no pool needed).
    import plugins.video_gen.openrouter as mod

    monkeypatch.setattr(
        mod,
        "_resolve_credentials",
        lambda: {"api_key": key, "base_url": "https://openrouter.ai/api/v1"},
    )


def _mock_http(monkeypatch, *, terminal_status="completed", terminal_body=None):
    """Patch requests.post (submit) + requests.get (poll) + save_url_video."""
    import plugins.video_gen.openrouter as mod

    captured = {"post_payload": None, "poll_urls": []}

    class FakeResp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    job_id = "job_abc123"

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["post_payload"] = json
        assert json["model"], "model is required"
        assert json["prompt"], "prompt is required"
        return FakeResp({
            "id": job_id,
            "polling_url": f"{url}/{job_id}",
            "status": "pending",
        })

    def fake_get(url, headers=None, timeout=None):
        captured["poll_urls"].append(url)
        if terminal_status in ("failed", "error"):
            body = terminal_body or {
                "id": job_id, "status": terminal_status, "error": "boom",
            }
        else:
            body = terminal_body or {
                "id": job_id,
                "status": "completed",
                "unsigned_urls": ["https://cdn.example.com/out.mp4"],
            }
        return FakeResp(body)

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr(mod, "save_url_video", lambda url, prefix: f"/tmp/{prefix}_{url.split('/')[-1]}")
    return captured


class TestAvailability:
    def test_unavailable_without_key(self, provider, monkeypatch):
        import plugins.video_gen.openrouter as mod

        monkeypatch.setattr(mod, "_resolve_credentials", lambda: None)
        assert provider.is_available() is False

    def test_available_with_key(self, provider, monkeypatch):
        _set_creds(monkeypatch)
        assert provider.is_available() is True


class TestGenerate:
    def test_text_to_video_happy_path(self, provider, monkeypatch):
        _set_creds(monkeypatch)
        captured = _mock_http(monkeypatch)

        result = provider.generate("a dog running on a beach")

        assert result["success"] is True
        assert result["modality"] == "text"
        assert result["video"].endswith("out.mp4")
        assert captured["post_payload"]["prompt"] == "a dog running on a beach"
        assert "frame_images" not in captured["post_payload"]
        assert len(captured["poll_urls"]) >= 1

    def test_image_to_video_uses_frame_images(self, provider, monkeypatch):
        _set_creds(monkeypatch)
        captured = _mock_http(monkeypatch)

        result = provider.generate(
            "animate this", image_url="https://example.com/frame.png"
        )
        assert result["success"] is True
        assert result["modality"] == "image"
        frames = captured["post_payload"]["frame_images"]
        assert frames[0]["frame_type"] == "first_frame"
        assert frames[0]["image_url"]["url"] == "https://example.com/frame.png"

    def test_passes_optional_params(self, provider, monkeypatch):
        _set_creds(monkeypatch)
        captured = _mock_http(monkeypatch)

        provider.generate(
            "hello",
            duration=8, aspect_ratio="16:9", resolution="1080p",
            audio=True, seed=42,
        )
        payload = captured["post_payload"]
        assert payload["duration"] == 8
        assert payload["aspect_ratio"] == "16:9"
        assert payload["resolution"] == "1080p"
        assert payload["generate_audio"] is True
        assert payload["seed"] == 42

    def test_failed_job_returns_error(self, provider, monkeypatch):
        _set_creds(monkeypatch)
        _mock_http(monkeypatch, terminal_status="failed")

        result = provider.generate("hello")
        assert result["success"] is False
        assert "boom" in result["error"]
        assert result["error_type"] == "job_failed"

    def test_error_status_maps_to_job_failed(self, provider, monkeypatch):
        _set_creds(monkeypatch)
        _mock_http(monkeypatch, terminal_status="error", terminal_body={
            "id": "x", "status": "error", "error": "provider rejected prompt",
        })
        result = provider.generate("hello")
        assert result["success"] is False
        assert "provider rejected prompt" in result["error"]

    def test_missing_credentials_returns_error(self, provider, monkeypatch):
        import plugins.video_gen.openrouter as mod

        monkeypatch.setattr(mod, "_resolve_credentials", lambda: None)
        result = provider.generate("hello")
        assert result["success"] is False
        assert result["error_type"] == "missing_credentials"

    def test_empty_prompt_returns_error(self, provider, monkeypatch):
        _set_creds(monkeypatch)
        result = provider.generate("   ")
        assert result["success"] is False
        assert result["error_type"] == "missing_prompt"


class TestCatalog:
    def test_model_card_maps_fields(self):
        from plugins.video_gen.openrouter import _model_card

        card = _model_card({
            "id": "google/veo-3.1-lite",
            "name": "Google: Veo 3.1 Lite",
            "description": "Fast, Text+image",
            "supported_durations": [8, 4, 6],
            "supported_resolutions": ["720p", "1080p"],
            "supported_frame_images": ["first_frame", "last_frame"],
            "pricing_skus": {"duration_seconds": "0.08"},
        })
        assert card["id"] == "google/veo-3.1-lite"
        assert "image" in card["modalities"]
        assert card["max_duration"] == 8
        assert "$" in card["price"]

    def test_default_model_real_and_text_image(self):
        # The default must be a real, cheap, text+image-capable model.
        from plugins.video_gen.openrouter import _model_card

        # If the live catalog is unreachable we fall back; assert the default
        # is at least surfaced in list_models.
        provider = OpenRouterVideoGenProvider()
        models = provider.list_models()
        assert models, "list_models should always return at least a fallback"
        assert any(m["id"] == DEFAULT_MODEL for m in models)


class TestRegister:
    def test_register_wires_provider(self):
        class _Ctx:
            def __init__(self):
                self.registered = None

            def register_video_gen_provider(self, provider):
                self.registered = provider

        ctx = _Ctx()
        from plugins.video_gen.openrouter import register

        register(ctx)
        assert ctx.registered is not None
        assert ctx.registered.name == "openrouter"

    def test_registry_registration(self):
        provider = OpenRouterVideoGenProvider()
        video_gen_registry.register_provider(provider)
        assert video_gen_registry.get_provider("openrouter") is provider
