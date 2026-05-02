"""ByteRover memory plugin — MemoryProvider interface.

Persistent memory via the ByteRover CLI (``brv``). Organizes knowledge into
a hierarchical context tree with tiered retrieval (fuzzy text → LLM-driven
search). Local-first with optional cloud sync.

Original PR #3499 by hieuntg81, adapted to MemoryProvider ABC.

Requires: ``brv`` CLI installed (npm install -g byterover-cli or
curl -fsSL https://byterover.dev/install.sh | sh).

Config via environment variables (profile-scoped via each profile's .env):
  BRV_API_KEY   — ByteRover API key (for cloud features, optional for local)

Working directory: $HERMES_HOME/byterover/ (profile-scoped context tree)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider
from agent.retry_utils import jittered_backoff
from hermes_cli.config import cfg_get
from tools.registry import tool_error

logger = logging.getLogger(__name__)

# Timeouts
_QUERY_TIMEOUT = 10   # brv query — should be fast
_CURATE_TIMEOUT = 120  # brv curate — may involve LLM processing

# Minimum lengths to filter noise
_MIN_QUERY_LEN = 10
_MIN_OUTPUT_LEN = 20


# ---------------------------------------------------------------------------
# brv binary resolution (cached, thread-safe)
# ---------------------------------------------------------------------------

_brv_path_lock = threading.Lock()
_cached_brv_path: Optional[str] = None


def _resolve_brv_path() -> Optional[str]:
    """Find the brv binary on PATH or well-known install locations."""
    global _cached_brv_path
    with _brv_path_lock:
        if _cached_brv_path is not None:
            return _cached_brv_path if _cached_brv_path != "" else None

    found = shutil.which("brv")
    if not found:
        home = Path.home()
        candidates = [
            home / ".brv-cli" / "bin" / "brv",
            Path("/usr/local/bin/brv"),
            home / ".npm-global" / "bin" / "brv",
        ]
        for c in candidates:
            if c.exists():
                found = str(c)
                break

    with _brv_path_lock:
        if _cached_brv_path is not None:
            return _cached_brv_path if _cached_brv_path != "" else None
        _cached_brv_path = found or ""
    return found


def _run_brv(args: List[str], timeout: int = _QUERY_TIMEOUT,
             cwd: str = None) -> dict:
    """Run a brv CLI command with retry logic. Returns {success, output, error}."""
    brv_path = _resolve_brv_path()
    if not brv_path:
        return {"success": False, "error": "brv CLI not found. Install: npm install -g byterover-cli"}

    cmd = [brv_path] + args
    effective_cwd = cwd or str(_get_brv_cwd())
    Path(effective_cwd).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    brv_bin_dir = str(Path(brv_path).parent)
    env["PATH"] = brv_bin_dir + os.pathsep + env.get("PATH", "")

    max_retries = 4
    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, cwd=effective_cwd, env=env,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode == 0:
                return {"success": True, "output": stdout}

            error_msg = stderr or stdout or f"brv exited {result.returncode}"

            # Don't retry on user errors
            if "not found" in error_msg.lower() or "invalid" in error_msg.lower():
                 return {"success": False, "error": f"Provider returned error: {error_msg}"}

            if attempt < max_retries - 1:
                delay = jittered_backoff(attempt + 1, base_delay=1.0, max_delay=8.0)
                logger.debug(f"ByteRover provider returned error, retrying in {delay:.2f}s (attempt {attempt+1}/{max_retries}): {error_msg}")
                time.sleep(delay)
                continue

            return {"success": False, "error": f"Provider returned error after {max_retries} attempts: {error_msg}"}

        except subprocess.TimeoutExpired:
            if attempt < max_retries - 1:
                delay = jittered_backoff(attempt + 1, base_delay=1.0, max_delay=8.0)
                logger.debug(f"ByteRover provider network issue (timeout), retrying in {delay:.2f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(delay)
                continue
            return {"success": False, "error": f"Network issue: brv timed out after {timeout}s"}
        except FileNotFoundError:
            global _cached_brv_path
            with _brv_path_lock:
                _cached_brv_path = None
            return {"success": False, "error": "brv CLI not found"}
        except Exception as e:
            if attempt < max_retries - 1:
                delay = jittered_backoff(attempt + 1, base_delay=1.0, max_delay=8.0)
                logger.debug(f"ByteRover provider error, retrying in {delay:.2f}s (attempt {attempt+1}/{max_retries}): {e}")
                time.sleep(delay)
                continue
            return {"success": False, "error": f"Provider returned error: {str(e)}"}

    return {"success": False, "error": "All retry attempts exhausted"}


def _get_brv_cwd() -> Path:
    """Profile-scoped working directory for the brv context tree."""
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "byterover"



# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_plugin_config() -> dict:
    from hermes_constants import get_hermes_home
    config_path = get_hermes_home() / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
        with open(config_path) as f:
            all_config = yaml.safe_load(f) or {}
        return cfg_get(all_config, "plugins", "byterover", default={}) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

QUERY_SCHEMA = {
    "name": "brv_query",
    "description": (
        "Search ByteRover's persistent knowledge tree for relevant context. "
        "Returns memories, project knowledge, architectural decisions, and "
        "patterns from previous sessions. Use for any question where past "
        "context would help."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
        },
        "required": ["query"],
    },
}

CURATE_SCHEMA = {
    "name": "brv_curate",
    "description": (
        "Store important information in ByteRover's persistent knowledge tree. "
        "Use for architectural decisions, bug fixes, user preferences, project "
        "patterns — anything worth remembering across sessions. ByteRover's LLM "
        "automatically categorizes and organizes the memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The information to remember."},
        },
        "required": ["content"],
    },
}

STATUS_SCHEMA = {
    "name": "brv_status",
    "description": "Check ByteRover status — CLI version, context tree stats, cloud sync state.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}


# ---------------------------------------------------------------------------
# MemoryProvider implementation
# ---------------------------------------------------------------------------

class ByteRoverMemoryProvider(MemoryProvider):
    """ByteRover persistent memory via the brv CLI."""

    def __init__(self):
        self._config = _load_plugin_config()
        self._cwd = ""
        self._session_id = ""
        self._turn_count = 0
        self._sync_thread: Optional[threading.Thread] = None
        self._query_timeout = int(self._config.get("query_timeout", _QUERY_TIMEOUT))
        self._curate_timeout = int(self._config.get("curate_timeout", _CURATE_TIMEOUT))

    @property
    def name(self) -> str:
        return "byterover"

    def is_available(self) -> bool:
        """Check if brv CLI is installed. No network calls."""
        return _resolve_brv_path() is not None

    def get_config_schema(self):
        return [
            {
                "key": "api_key",
                "description": "ByteRover API key (optional, for cloud sync)",
                "secret": True,
                "env_var": "BRV_API_KEY",
                "url": "https://app.byterover.dev",
            },
            {
                "key": "query_timeout",
                "description": "Timeout for brv query (seconds)",
                "default": _QUERY_TIMEOUT,
            },
            {
                "key": "curate_timeout",
                "description": "Timeout for brv curate (seconds)",
                "default": _CURATE_TIMEOUT,
            },
        ]
    def save_config(self, values, hermes_home):
        """Write config to config.yaml under plugins.byterover."""
        from pathlib import Path
        config_path = Path(hermes_home) / "config.yaml"

        # Cast timeouts to ints if present
        if "query_timeout" in values:
            try:
                values["query_timeout"] = int(values["query_timeout"])
            except ValueError:
                pass
        if "curate_timeout" in values:
            try:
                values["curate_timeout"] = int(values["curate_timeout"])
            except ValueError:
                pass

        try:
            import yaml
            existing = {}
            if config_path.exists():
                with open(config_path) as f:
                    existing = yaml.safe_load(f) or {}
            existing.setdefault("plugins", {})
            existing["plugins"]["byterover"] = values
            with open(config_path, "w") as f:
                yaml.dump(existing, f, default_flow_style=False)
        except Exception:
            pass

    def initialize(self, session_id: str, **kwargs) -> None:
        self._cwd = str(_get_brv_cwd())
        self._session_id = session_id
        self._turn_count = 0
        Path(self._cwd).mkdir(parents=True, exist_ok=True)

    def system_prompt_block(self) -> str:
        if not _resolve_brv_path():
            return ""
        return (
            "# ByteRover Memory\n"
            "Active. Persistent knowledge tree with hierarchical context.\n"
            "Use brv_query to search past knowledge, brv_curate to store "
            "important facts, brv_status to check state."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Run brv query synchronously before the agent's first LLM call.

        Blocks until the query completes (up to _QUERY_TIMEOUT seconds), ensuring
        the result is available as context before the model is called.
        """
        if not query or len(query.strip()) < _MIN_QUERY_LEN:
            return ""
        result = _run_brv(
            ["query", "--", query.strip()[:5000]],
            timeout=self._query_timeout, cwd=self._cwd,
        )
        if result["success"] and result.get("output"):
            output = result["output"].strip()
            if len(output) > _MIN_OUTPUT_LEN:
                return f"## ByteRover Context\n{output}"
        return ""

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """No-op: prefetch() now runs synchronously at turn start."""
        pass

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Curate the conversation turn in background (non-blocking)."""
        self._turn_count += 1

        # Only curate substantive turns
        if len(user_content.strip()) < _MIN_QUERY_LEN:
            return

        def _sync():
            if getattr(self, "_circuit_breaker_open", False) and time.time() < getattr(self, "_circuit_breaker_expiry", 0):
                return
            try:
                combined = f"User: {user_content[:2000]}\nAssistant: {assistant_content[:2000]}"
                result = _run_brv(
                    ["curate", "--", combined],
                    timeout=self._curate_timeout, cwd=self._cwd,
                )
                if not result["success"]:
                     self._record_failure()
                     logger.debug(f"ByteRover sync failed: {result.get('error')}")
                else:
                     self._record_success()
            except Exception as e:
                self._record_failure()
                logger.debug("ByteRover sync failed: %s", e)

        # Wait for previous sync
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)

        self._sync_thread = threading.Thread(
            target=_sync, daemon=True, name="brv-sync"
        )
        self._sync_thread.start()

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        """Mirror built-in memory writes to ByteRover."""
        if action not in ("add", "replace") or not content:
            return

        def _write():
            if getattr(self, "_circuit_breaker_open", False) and time.time() < getattr(self, "_circuit_breaker_expiry", 0):
                return
            try:
                label = "User profile" if target == "user" else "Agent memory"
                result = _run_brv(
                    ["curate", "--", f"[{label}] {content}"],
                    timeout=self._curate_timeout, cwd=self._cwd,
                )
                if not result["success"]:
                     self._record_failure()
                     logger.debug(f"ByteRover memory mirror failed: {result.get('error')}")
                else:
                     self._record_success()
            except Exception as e:
                self._record_failure()
                logger.debug("ByteRover memory mirror failed: %s", e)

        t = threading.Thread(target=_write, daemon=True, name="brv-memwrite")
        t.start()

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """Extract insights before context compression discards turns."""
        if not messages:
            return ""

        # Build a summary of messages about to be compressed
        parts = []
        for msg in messages[-10:]:  # last 10 messages
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip() and role in ("user", "assistant"):
                parts.append(f"{role}: {content[:500]}")

        if not parts:
            return ""

        combined = "\n".join(parts)

        def _flush():
            if getattr(self, "_circuit_breaker_open", False) and time.time() < getattr(self, "_circuit_breaker_expiry", 0):
                return
            try:
                result = _run_brv(
                    ["curate", "--", f"[Pre-compression context]\n{combined}"],
                    timeout=self._curate_timeout, cwd=self._cwd,
                )
                if not result["success"]:
                     self._record_failure()
                     logger.debug(f"ByteRover pre-compression flush failed: {result.get('error')}")
                else:
                     self._record_success()
                     logger.info("ByteRover pre-compression flush: %d messages", len(parts))
            except Exception as e:
                self._record_failure()
                logger.debug("ByteRover pre-compression flush failed: %s", e)

        t = threading.Thread(target=_flush, daemon=True, name="brv-flush")
        t.start()
        return ""

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [QUERY_SCHEMA, CURATE_SCHEMA, STATUS_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        if tool_name == "brv_query":
            return self._tool_query(args)
        elif tool_name == "brv_curate":
            return self._tool_curate(args)
        elif tool_name == "brv_status":
            return self._tool_status()
        return tool_error(f"Unknown tool: {tool_name}")

    def shutdown(self) -> None:
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=10.0)

    # -- Tool implementations ------------------------------------------------

    def _tool_query(self, args: dict) -> str:
        query = args.get("query", "")
        if not query:
            return tool_error("query is required")

        if getattr(self, "_circuit_breaker_open", False) and time.time() < getattr(self, "_circuit_breaker_expiry", 0):
            return json.dumps({"result": "ByteRover provider is temporarily unavailable. Using local memory only."})

        result = _run_brv(
            ["query", "--", query.strip()[:5000]],
            timeout=self._query_timeout, cwd=self._cwd,
        )

        if not result["success"]:
            self._record_failure()
            logger.warning(f"ByteRover query failed: {result.get('error')}")
            return json.dumps({"result": "ByteRover provider temporarily unavailable, proceeding with local context."})

        self._record_success()
        output = result.get("output", "").strip()
        if not output or len(output) < _MIN_OUTPUT_LEN:
            return json.dumps({"result": "No relevant memories found."})

        # Truncate very long results
        if len(output) > 8000:
            output = output[:8000] + "\n\n[... truncated]"

        return json.dumps({"result": output})

    def _tool_curate(self, args: dict) -> str:
        content = args.get("content", "")
        if not content:
            return tool_error("content is required")

        if getattr(self, "_circuit_breaker_open", False) and time.time() < getattr(self, "_circuit_breaker_expiry", 0):
            return json.dumps({"result": "ByteRover provider is temporarily unavailable. Memory sync skipped, local memory still active."})

        def _bg_curate():
            result = _run_brv(
                ["curate", "--", content],
                timeout=self._curate_timeout, cwd=self._cwd,
            )
            if not result["success"]:
                self._record_failure()
                logger.warning(f"ByteRover background curate failed: {result.get('error')}")
            else:
                self._record_success()

        # Run in background to avoid blocking session
        t = threading.Thread(target=_bg_curate, daemon=True, name="brv-tool-curate")
        t.start()

        return json.dumps({"result": "Memory curate initiated in background."})

    def _tool_status(self) -> str:
        if getattr(self, "_circuit_breaker_open", False) and time.time() < getattr(self, "_circuit_breaker_expiry", 0):
             return json.dumps({"status": "ByteRover provider is temporarily offline due to repeated failures."})

        result = _run_brv(["status"], timeout=15, cwd=self._cwd)
        if not result["success"]:
            self._record_failure()
            return json.dumps({"status": f"Status check failed: {result.get('error')}"})

        self._record_success()
        return json.dumps({"status": result.get("output", "")})

    def _record_failure(self):
        """Record a provider failure to implement circuit breaking."""
        self._consecutive_failures = getattr(self, "_consecutive_failures", 0) + 1
        if self._consecutive_failures >= 3:
            self._circuit_breaker_open = True
            # Open circuit for 5 minutes
            self._circuit_breaker_expiry = time.time() + 300
            logger.error("ByteRover circuit breaker opened due to repeated failures.")

    def _record_success(self):
        """Record a provider success, closing the circuit breaker if open."""
        self._consecutive_failures = 0
        if getattr(self, "_circuit_breaker_open", False):
            self._circuit_breaker_open = False
            logger.info("ByteRover circuit breaker closed (provider recovered).")


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register ByteRover as a memory provider plugin."""
    ctx.register_memory_provider(ByteRoverMemoryProvider())
