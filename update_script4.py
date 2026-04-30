import re

with open("plugins/memory/byterover/__init__.py", "r") as f:
    content = f.read()

# Add save_config after get_config_schema
save_config = """
    def save_config(self, values, hermes_home):
        \"\"\"Write config to config.yaml under plugins.byterover.\"\"\"
        from pathlib import Path
        config_path = Path(hermes_home) / "config.yaml"
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
"""

content = content.replace("        ]\n\n    def initialize", "        ]" + save_config + "\n    def initialize")

with open("plugins/memory/byterover/__init__.py", "w") as f:
    f.write(content)
