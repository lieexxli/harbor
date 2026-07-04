Implement `/app/trim.py`.

A conversation history is stored at `/app/messages.json` as a JSON array of `{"role", "content"}` objects. A budget file at `/app/budget.json` contains `{"max_tokens": N}`.

Trim the conversation so the total token count fits within `max_tokens`, then write the result to `/app/trimmed.json`.

Default invocation:

```bash
python /app/trim.py
```

Also support explicit paths:

```bash
python /app/trim.py --messages /path/messages.json --budget /path/budget.json --output /path/trimmed.json --stats /path/stats.json
```

Rules:
- Count tokens with `tiktoken.get_encoding("cl100k_base")`.
- Use this ChatML token formula: start with `3` reply-priming tokens; for each message add `3` per-message overhead, plus the encoded token count of `role`, plus the encoded token count of `content`.
- The `system` message (if present) must always be kept.
- Remove messages starting from the oldest non-system message until the total fits.
- If the conversation already fits, write it unchanged.

Output `/app/trimmed.json`: a JSON array in the same format as the input, containing only the kept messages.
Output `/app/stats.json`: `{"original_tokens": M, "trimmed_tokens": K, "messages_removed": R}`.
