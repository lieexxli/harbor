Implement `/app/convert.py` exposing:

    def convert(messages: list[dict], direction: str, **kwargs) -> dict

`direction` is `"openai_to_anthropic"` or `"anthropic_to_openai"`.

- When `"openai_to_anthropic"`: convert OpenAI Chat Completions text messages, system messages, tool calls, tool results, and tool definitions into the corresponding Anthropic Messages API structure.
- When `"anthropic_to_openai"`: convert Anthropic Messages API text messages, top-level system prompts, tool use blocks, tool result blocks, and tool definitions into the corresponding OpenAI Chat Completions structure.

Pass extra fields (`model`, `tools`, etc.) via `**kwargs`; include them in the output where the target API expects them.
