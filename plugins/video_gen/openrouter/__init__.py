"""OpenRouter video generation backend.

Uses OpenRouter's dedicated async video endpoint::

    POST /api/v1/videos        -> {id, polling_url, status}
    GET  {polling_url}         -> {status: pending|in_progress|completed|failed, ...}
    (download)                 -> unsigned_urls[0]  OR /api/v1/videos/{id}/content?index=0

The model catalog is discovered live from ``GET /api/v1/videos/models``, so
new video models appear (and retired ones disappear) without a patch. Each
catalog entry advertises its own supported durations / resolutions / aspect
ratios / audio / frame-image support, which map onto the provider's
``capabilities()`` and per-model picker rows.

Credentials reuse the agent's OpenRouter auth (``OPENROUTER_API_KEY`` env or
the credential pool) via the shared runtime resolver — the same key the user
already uses for chat. No extra account or billing setup.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from agent.video_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_RESOLUTION,
    VideoGenProvider,
    error_response,
    save_url_video,
    success_response,
)

logger = logging.getLogger(__name__)

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Cheap, fast, text+image capable default for the picker.
DEFAULT_MODEL = "google/veo-3.1-lite"

# Cubit: how long to wait between poll attempts, and the hard cap on wall
# time before we fail out (video jobs commonly run 30s-few minutes).
_POLL_INTERVAL_S = 10.0
_POLL_DEADLINE_S = 600.0

_TERMINAL_STATUSES = {"completed", "failed", "error", "cancelled", "canceled"}


def _openrouter_base_url() -> str:
    import os

    return (os.environ.get("OPENROUTER_VIDEO_BASE_URL") or DEFAULT_OPENROUTER_BASE_URL).rstrip("/")


def _resolve_credentials() -> Optional[Dict[str, str]]:
    """Return ``{api_key, base_url}`` from the shared OpenRouter auth chain.

    Mirrors how the image_gen/openrouter plugin resolves credentials so both
    surfaces share the same key pool and env precedence. Returns None when no
    key is available.
    """
    try:
        from hermes_cli.runtime_provider import resolve_runtime_provider

        runtime = resolve_runtime_provider(requested="openrouter")
    except Exception as exc:  # noqa: BLE001 - never break availability
        logger.debug("OpenRouter runtime resolution failed: %s", exc)
        runtime = {}
    api_key = str(runtime.get("api_key") or "").strip() if runtime else ""
    if not api_key:
        import os

        api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    base_url = str(runtime.get("base_url") or "").strip() if runtime else ""
    if not base_url:
        base_url = _openrouter_base_url()
    if not api_key:
        return None
    return {"api_key": api_key, "base_url": base_url.rstrip("/")}


def _http_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Live model catalog
# ---------------------------------------------------------------------------


def _fetch_video_models() -> List[Dict[str, Any]]:
    """Fetch ``GET /api/v1/videos/models`` (public — no auth required)."""
    import requests

    try:
        resp = requests.get(f"{_openrouter_base_url()}/videos/models", timeout=30)
        resp.raise_for_status()
        return list((resp.json() or {}).get("data") or [])
    except Exception as exc:  # noqa: BLE001 - catalog is best-effort
        logger.debug("Could not fetch OpenRouter video models: %s", exc)
        return []


def _model_card(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Map one catalog entry onto a picker row + capability hints.

    OpenRouter advertises per-model ``supported_durations``,
    ``supported_resolutions``, ``supported_aspect_ratios``,
    ``supported_frame_images``, ``generate_audio`` and ``pricing_skus``.
    """
    mid = entry.get("id") or ""
    pricing = entry.get("pricing_skus") or {}
    price_txt = _format_price(pricing)
    modalities: List[str] = ["text"]
    if entry.get("supported_frame_images"):
        modalities.append("image")
    durations = entry.get("supported_durations")
    if durations and isinstance(durations, list):
        max_duration = max(int(d) for d in durations if isinstance(d, (int, float)))
    else:
        max_duration = 15
    return {
        "id": mid,
        "display": entry.get("name") or mid.split("/")[-1],
        "speed": "~30s-several min",
        "strengths": (entry.get("description") or "")[:140] or "OpenRouter video model",
        "price": price_txt,
        "modalities": modalities,
        "max_duration": max_duration,
    }


def _format_price(pricing: Dict[str, Any]) -> str:
    """Best-effort human price from a model's pricing_skus dict."""
    if not pricing:
        return ""
    # Common shapes: {"duration_seconds": "0.13"} or {"cents_per_second_output": "28"}.
    for key in (
        "duration_seconds",
        "cents_per_second_output",
        "text_to_video_duration_seconds_720p",
        "video_tokens",
    ):
        if key not in pricing:
            continue
        try:
            numeric = float(pricing[key])
        except (TypeError, ValueError):
            continue
        if numeric <= 0:
            continue
        if "cents_per_second" in key:
            return f"${numeric / 100:.3f}/s"
        if "tokens" in key:
            return f"${numeric * 1000:.2f}/1k tokens"
        return f"${numeric:.3f}/s"
    return ""


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class OpenRouterVideoGenProvider(VideoGenProvider):
    """Text/image-to-video via OpenRouter's async /api/v1/videos endpoint."""

    name = "openrouter"

    @property
    def display_name(self) -> str:
        return "OpenRouter"

    def is_available(self) -> bool:
        return _resolve_credentials() is not None

    def list_models(self) -> List[Dict[str, Any]]:
        models = _fetch_video_models()
        out: List[Dict[str, Any]] = []
        for entry in models:
            card = _model_card(entry)
            if card["id"]:
                out.append(card)
        if not out:
            # Fallback so the picker always shows something even when the
            # catalog is unreachable.
            out.append({
                "id": DEFAULT_MODEL,
                "display": "Veo 3.1 Lite",
                "modalities": ["text", "image"],
                "max_duration": 15,
            })
        return out

    def default_model(self) -> Optional[str]:
        return DEFAULT_MODEL

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "OpenRouter",
            "badge": "paid",
            "tag": "Veo 3.1, Kling v3, Hailuo 3, Seedance 2.0, Wan 2.7, Sora 2 Pro — text & image-to-video via OPENROUTER_API_KEY",
            "env_vars": [
                {
                    "key": "OPENROUTER_API_KEY",
                    "prompt": "OpenRouter API key",
                    "url": "https://openrouter.ai/keys",
                },
            ],
        }

    def capabilities(self) -> Dict[str, Any]:
        return {
            "modalities": ["text", "image"],
            "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9"],
            "resolutions": ["480p", "540p", "720p", "1080p"],
            "max_duration": 15,
            "min_duration": 1,
            "supports_audio": True,
            "supports_negative_prompt": True,
            "max_reference_images": 3,
        }

    # -- request plumbing ------------------------------------------------

    def _submit(self, api_key: str, base_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST a video job; returns the submission dict {id, polling_url, status}."""
        import requests

        resp = requests.post(
            f"{base_url}/videos",
            headers=_http_headers(api_key),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def _poll(
        self, api_key: str, polling_url: str
    ) -> Optional[Dict[str, Any]]:
        """Poll until terminal. Returns the terminal status dict or None on timeout."""
        deadline = time.monotonic() + _POLL_DEADLINE_S
        import requests

        while True:
            resp = requests.get(polling_url, headers=_http_headers(api_key), timeout=60)
            resp.raise_for_status()
            body = resp.json()
            status = (body or {}).get("status") or ""
            if status in _TERMINAL_STATUSES:
                return body
            if time.monotonic() >= deadline:
                logger.warning(
                    "OpenRouter video job did not finish within %ss (last=%s)",
                    int(_POLL_DEADLINE_S), status,
                )
                return None
            time.sleep(_POLL_INTERVAL_S)

    def _download(self, api_key: str, base_url: str, terminal: Dict[str, Any], prefix: str) -> str:
        """Resolve the final video URL and materialise it locally."""
        unsigned = (terminal or {}).get("unsigned_urls") or []
        url = unsigned[0] if unsigned else None

        if not url:
            # Fall back to the content endpoint: /api/v1/videos/{id}/content?index=0
            job_id = (terminal or {}).get("id") or ""
            if job_id:
                url = f"{base_url}/videos/{job_id}/content?index=0"
        if not url:
            raise ValueError("OpenRouter returned no video URL in the terminal response")

        try:
            return str(save_url_video(url, prefix=prefix))
        except Exception as exc:  # noqa: BLE001 - best-effort: return raw URL
            logger.debug("Could not cache OpenRouter video locally (%s); returning URL", exc)
            return url

    # -- main entry ------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        duration: Optional[int] = None,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        resolution: str = DEFAULT_RESOLUTION,
        negative_prompt: Optional[str] = None,
        audio: Optional[bool] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        creds = _resolve_credentials()
        if not creds:
            return error_response(
                error=(
                    "No OpenRouter credentials found. Set OPENROUTER_API_KEY "
                    "(run `hermes tools` → Video Generation → OpenRouter), or "
                    "add OpenRouter to your credential pool."
                ),
                error_type="missing_credentials",
                provider=self.name,
                prompt=prompt or "",
            )

        prompt = (prompt or "").strip()
        if not prompt:
            return error_response(
                error="prompt is required.",
                error_type="missing_prompt",
                provider=self.name,
                prompt="",
            )

        model_id = model or self.default_model() or ""

        # Build the OpenRouter video payload. Field names follow the documented
        # /api/v1/videos schema (see module docstring).
        payload: Dict[str, Any] = {"model": model_id, "prompt": prompt}
        if duration and duration > 0:
            payload["duration"] = int(duration)
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if resolution:
            payload["resolution"] = resolution
        if seed is not None:
            payload["seed"] = int(seed)
        if audio is not None:
            payload["generate_audio"] = bool(audio)

        # Image-to-video: a single source image becomes the first frame.
        if image_url:
            images = [{
                "type": "image_url",
                "image_url": {"url": image_url},
                "frame_type": "first_frame",
            }]
            for ref in (reference_image_urls or []):
                if len(images) >= 2:
                    break
                images.append({
                    "type": "image_url",
                    "image_url": {"url": ref},
                    "frame_type": "last_frame",
                })
            payload["frame_images"] = images
            modality_used = "image"
        else:
            if reference_image_urls:
                payload["input_references"] = [
                    {"type": "image_url", "image_url": {"url": r}}
                    for r in reference_image_urls
                ]
            modality_used = "text"

        # Provider passthrough for negative_prompt (only some models accept it
        # — run it through provider.options keyed as the model's provider slug).
        if negative_prompt:
            # Try a best-effort mapping of model id -> provider slug.
            slug = model_id.split("/")[0] if "/" in model_id else model_id
            payload.setdefault("provider", {}).setdefault("options", {}).setdefault(
                slug, {}
            ).setdefault("parameters", {})["negativePrompt"] = negative_prompt

        try:
            submission = self._submit(creds["api_key"], creds["base_url"], payload)
        except Exception as exc:  # noqa: BLE001
            return error_response(
                error=f"OpenRouter video submission failed: {exc}",
                error_type="api_error",
                provider=self.name,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
            )

        job_id = (submission or {}).get("id") or ""
        polling_url = (submission or {}).get("polling_url") or ""
        if not polling_url or not job_id:
            return error_response(
                error="OpenRouter video submission returned no polling_url",
                error_type="empty_response",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        try:
            terminal = self._poll(creds["api_key"], polling_url)
        except Exception as exc:  # noqa: BLE001
            return error_response(
                error=f"OpenRouter video polling failed: {exc}",
                error_type="api_error",
                provider=self.name,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
            )
        if terminal is None:
            return error_response(
                error=(
                    f"OpenRouter video job {job_id} did not reach a terminal "
                    f"state within {int(_POLL_DEADLINE_S)}s"
                ),
                error_type="timeout",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        status = (terminal or {}).get("status") or ""
        if status != "completed":
            job_error = (terminal or {}).get("error") or ""
            return error_response(
                error=f"OpenRouter video job ended with status={status!r}: {job_error}",
                error_type="job_failed",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        try:
            video_ref = self._download(
                creds["api_key"], creds["base_url"], terminal, prefix=self.name
            )
        except Exception as exc:  # noqa: BLE001
            return error_response(
                error=f"OpenRouter video job succeeded but output could not be retrieved: {exc}",
                error_type="empty_response",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        return success_response(
            video=video_ref,
            model=model_id,
            prompt=prompt,
            modality=modality_used,
            aspect_ratio=aspect_ratio,
            duration=duration or 0,
            provider=self.name,
            extra={"job_id": job_id},
        )


def register(ctx) -> None:
    """Plugin entry point — wire ``OpenRouterVideoGenProvider`` into the registry."""
    ctx.register_video_gen_provider(OpenRouterVideoGenProvider())
