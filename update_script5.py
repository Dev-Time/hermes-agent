import re

with open("plugins/memory/byterover/__init__.py", "r") as f:
    content = f.read()

# Update usages in ByteRoverMemoryProvider
# 1. prefetch
content = content.replace("timeout=_QUERY_TIMEOUT", "timeout=self._query_timeout")

# 2. sync_turn
content = content.replace("timeout=_CURATE_TIMEOUT", "timeout=self._curate_timeout")

# The string replacement might replace _QUERY_TIMEOUT globally if it occurs in function definitions.
# Wait, let me replace it safely using replace_with_git_merge_diff or exact string replace.
