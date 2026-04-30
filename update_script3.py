import re

with open("plugins/memory/byterover/__init__.py", "r") as f:
    content = f.read()

# Update get_config_schema
old_schema = """    def get_config_schema(self):
        return [
            {
                "key": "api_key",
                "description": "ByteRover API key (optional, for cloud sync)",
                "secret": True,
                "env_var": "BRV_API_KEY",
                "url": "https://app.byterover.dev",
            },
        ]"""

new_schema = """    def get_config_schema(self):
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
                "default": str(_QUERY_TIMEOUT),
            },
            {
                "key": "curate_timeout",
                "description": "Timeout for brv curate (seconds)",
                "default": str(_CURATE_TIMEOUT),
            },
        ]"""

content = content.replace(old_schema, new_schema)

with open("plugins/memory/byterover/__init__.py", "w") as f:
    f.write(content)
