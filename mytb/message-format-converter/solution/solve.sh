#!/bin/bash
set -euo pipefail

cat > /app/convert.py << 'EOF'
import json


def convert(messages: list[dict], direction: str, **kwargs) -> dict:
    if direction == "openai_to_anthropic":
        return _oai_to_anthropic(messages, **kwargs)
    if direction == "anthropic_to_openai":
        return _anthropic_to_oai(messages, **kwargs)
    raise ValueError(f"Unknown direction: {direction!r}")


def _oai_to_anthropic(messages: list[dict], **kwargs) -> dict:
    system = None
    converted: list[dict] = []

    for msg in messages:
        role = msg["role"]

        if role == "system":
            system = msg["content"]

        elif role == "user":
            content = msg["content"]
            if isinstance(content, str):
                converted.append({"role": "user", "content": content})
            else:
                converted.append({"role": "user", "content": content})

        elif role == "assistant":
            blocks: list[dict] = []
            if msg.get("content"):
                blocks.append({"type": "text", "text": msg["content"]})
            for tc in msg.get("tool_calls") or []:
                blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "input": json.loads(tc["function"]["arguments"]),
                })
            converted.append({"role": "assistant", "content": blocks if blocks else msg.get("content", "")})

        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": msg["tool_call_id"],
                "content": msg["content"],
            }
            # Merge consecutive tool results into the same user message
            if converted and converted[-1]["role"] == "user" and isinstance(converted[-1]["content"], list):
                last_content = converted[-1]["content"]
                if any(b.get("type") == "tool_result" for b in last_content):
                    last_content.append(block)
                    continue
            converted.append({"role": "user", "content": [block]})

    result: dict = {}
    if system is not None:
        result["system"] = system
    result["messages"] = converted

    if "tools" in kwargs:
        result["tools"] = [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters", {}),
            }
            for t in kwargs.pop("tools")
        ]

    result.update(kwargs)
    return result


def _anthropic_to_oai(messages: list[dict], **kwargs) -> dict:
    oai: list[dict] = []

    system = kwargs.pop("system", None)
    if system:
        oai.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            if isinstance(content, str):
                oai.append({"role": "user", "content": content})
            else:
                tool_results = [b for b in content if b.get("type") == "tool_result"]
                text_blocks = [b for b in content if b.get("type") == "text"]
                for tr in tool_results:
                    c = tr["content"]
                    oai.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_use_id"],
                        "content": c if isinstance(c, str) else json.dumps(c),
                    })
                if text_blocks:
                    oai.append({"role": "user", "content": " ".join(b["text"] for b in text_blocks)})

        elif role == "assistant":
            if isinstance(content, str):
                oai.append({"role": "assistant", "content": content})
            else:
                text_blocks = [b for b in content if b.get("type") == "text"]
                tool_use_blocks = [b for b in content if b.get("type") == "tool_use"]
                text = "".join(b["text"] for b in text_blocks) or None
                tool_calls = [
                    {
                        "id": tu["id"],
                        "type": "function",
                        "function": {
                            "name": tu["name"],
                            "arguments": json.dumps(tu["input"]),
                        },
                    }
                    for tu in tool_use_blocks
                ]
                assistant_msg: dict = {"role": "assistant", "content": text}
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                oai.append(assistant_msg)

    result: dict = {"messages": oai}

    if "tools" in kwargs:
        result["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            }
            for t in kwargs.pop("tools")
        ]

    result.update(kwargs)
    return result
EOF

echo "convert.py written"
