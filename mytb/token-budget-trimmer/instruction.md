A conversation history is stored at `/app/messages.json` as a JSON array of `{"role", "content"}` objects. A budget file at `/app/budget.json` contains `{"max_tokens": N}`.

Trim the conversation so the total token count fits within `max_tokens`, then write the result to `/app/trimmed.json`.

Rules:
- Count tokens the way the GPT-4 API counts them for chat completions.
- The `system` message (if present) must always be kept.
- Remove messages starting from the oldest non-system message until the total fits.
- If the conversation already fits, write it unchanged.

Output `/app/trimmed.json`: a JSON array in the same format as the input, containing only the kept messages.
Output `/app/stats.json`: `{"original_tokens": M, "trimmed_tokens": K, "messages_removed": R}`.
