import re

with open("plugins/memory/byterover/__init__.py", "r") as f:
    content = f.read()

# Add import
import_stmt = "from hermes_cli.config import cfg_get\n"
content = content.replace("from agent.memory_provider import MemoryProvider\n",
                          "from agent.memory_provider import MemoryProvider\n" + import_stmt)

# Add _load_plugin_config
load_fn = """
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
"""
content = content.replace("# ---------------------------------------------------------------------------\n# Tool schemas", load_fn + "\n\n# ---------------------------------------------------------------------------\n# Tool schemas")

with open("plugins/memory/byterover/__init__.py", "w") as f:
    f.write(content)
