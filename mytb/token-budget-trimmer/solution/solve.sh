#!/bin/bash
set -euo pipefail

pip install tiktoken --quiet

cat > /app/trim.py <<'PY'
import argparse
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


def trim(messages, max_tokens):
    system_msgs = [m for m in messages if m["role"] == "system"]
    non_system = [m for m in messages if m["role"] != "system"]

    while non_system and count_tokens(system_msgs + non_system) > max_tokens:
        non_system.pop(0)

    return system_msgs + non_system


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--messages", default="/app/messages.json")
    parser.add_argument("--budget", default="/app/budget.json")
    parser.add_argument("--output", default="/app/trimmed.json")
    parser.add_argument("--stats", default="/app/stats.json")
    args = parser.parse_args()

    messages = json.loads(Path(args.messages).read_text(encoding="utf-8"))
    budget = json.loads(Path(args.budget).read_text(encoding="utf-8"))["max_tokens"]

    original_tokens = count_tokens(messages)
    trimmed = trim(messages, budget)
    trimmed_tokens = count_tokens(trimmed)
    messages_removed = len(messages) - len(trimmed)

    Path(args.output).write_text(
        json.dumps(trimmed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    Path(args.stats).write_text(
        json.dumps(
            {
                "original_tokens": original_tokens,
                "trimmed_tokens": trimmed_tokens,
                "messages_removed": messages_removed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"original_tokens={original_tokens}, "
        f"trimmed_tokens={trimmed_tokens}, "
        f"messages_removed={messages_removed}"
    )


if __name__ == "__main__":
    main()
PY

python3 /app/trim.py
