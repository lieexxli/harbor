#!/bin/bash
set -euo pipefail

pip install tiktoken --quiet

python3 - <<'EOF'
import json
from pathlib import Path

import tiktoken

enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(messages):
    total = 3  # reply-priming overhead
    for m in messages:
        total += 3  # per-message overhead
        total += len(enc.encode(m["role"]))
        total += len(enc.encode(m["content"]))
    return total


messages = json.loads(Path("/app/messages.json").read_text())
budget = json.loads(Path("/app/budget.json").read_text())["max_tokens"]

original_tokens = count_tokens(messages)

system_msgs = [m for m in messages if m["role"] == "system"]
non_system = [m for m in messages if m["role"] != "system"]

# Drop oldest non-system messages until we fit
while non_system and count_tokens(system_msgs + non_system) > budget:
    non_system.pop(0)

trimmed = system_msgs + non_system
trimmed_tokens = count_tokens(trimmed)
messages_removed = len(messages) - len(trimmed)

Path("/app/trimmed.json").write_text(json.dumps(trimmed, ensure_ascii=False, indent=2))
Path("/app/stats.json").write_text(json.dumps({
    "original_tokens": original_tokens,
    "trimmed_tokens": trimmed_tokens,
    "messages_removed": messages_removed,
}, indent=2))

print(f"original_tokens={original_tokens}, trimmed_tokens={trimmed_tokens}, messages_removed={messages_removed}")
EOF
