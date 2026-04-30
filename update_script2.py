import re

with open("plugins/memory/byterover/__init__.py", "r") as f:
    content = f.read()

# Update init
old_init = """    def __init__(self):
        self._cwd = ""
        self._session_id = ""
        self._turn_count = 0
        self._sync_thread: Optional[threading.Thread] = None"""

new_init = """    def __init__(self):
        self._config = _load_plugin_config()
        self._cwd = ""
        self._session_id = ""
        self._turn_count = 0
        self._sync_thread: Optional[threading.Thread] = None
        self._query_timeout = int(self._config.get("query_timeout", _QUERY_TIMEOUT))
        self._curate_timeout = int(self._config.get("curate_timeout", _CURATE_TIMEOUT))"""

content = content.replace(old_init, new_init)

with open("plugins/memory/byterover/__init__.py", "w") as f:
    f.write(content)
