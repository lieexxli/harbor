Implement `/app/convert.py` exposing:

    def convert(messages: list[dict], direction: str, **kwargs) -> dict

`direction` is `"openai_to_anthropic"` or `"anthropic_to_openai"`.

- When `"openai_to_anthropic"`: `messages` follows the OpenAI Chat Completions format; the returned dict must conform to the Anthropic Messages API.
- When `"anthropic_to_openai"`: `messages` follows the Anthropic Messages API format; the returned dict must conform to the OpenAI Chat Completions API.

Pass extra fields (`model`, `tools`, etc.) via `**kwargs`; include them in the output where the target API expects them.
