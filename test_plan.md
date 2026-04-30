1. **Import `cfg_get`** from `hermes_cli.config` in `plugins/memory/byterover/__init__.py`. Oh wait, user said "without importing the hermes cli". I can just re-implement a small version of it or directly navigate the yaml config in `_load_plugin_config`. Since it's simple enough: `all_config.get("plugins", {}).get("byterover", {})`.
2. **Add a `_load_plugin_config()` function** to read the plugin config from `config.yaml` without importing from hermes_cli.
3. **Modify `ByteRoverMemoryProvider.__init__`** to load the config via `_load_plugin_config()`. Also extract `query_timeout` and `curate_timeout` from config, with defaults of `_QUERY_TIMEOUT` (10) and `_CURATE_TIMEOUT` (120) respectively. Store them as instance variables `self._query_timeout` and `self._curate_timeout`.
4. **Update `get_config_schema`** to include `query_timeout` and `curate_timeout` so they are configurable via `hermes memory setup` and `config.yaml`.
5. **Add `save_config` method** to `ByteRoverMemoryProvider` to save these non-secret settings to `config.yaml` under `plugins.byterover` (similar to holographic).
6. **Update timeout usages:** When calling `_run_brv()`, pass the timeout instance variables (`self._query_timeout` and `self._curate_timeout`) instead of the globals.
7. **Ensure testing, verification, review, and reflection** (pre-commit steps) are done.
8. **Submit the changes**.
