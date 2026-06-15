import json
import sys

import httpx
import pytest

sys.path.insert(0, "/app")

from convert import convert

# ---------------------------------------------------------------------------
# OpenAI → Anthropic
# ---------------------------------------------------------------------------

OAI_PLAIN = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is 2+2?"},
    {"role": "assistant", "content": "4"},
]

OAI_TOOL_FLOW = [
    {"role": "user", "content": "What's the weather in Paris?"},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_001",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"city": "Paris"}',
                },
            }
        ],
    },
    {"role": "tool", "tool_call_id": "call_001", "content": "15°C, cloudy"},
    {"role": "assistant", "content": "The weather in Paris is 15°C and cloudy."},
]

OAI_TOOLS_DEF = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]

ANTHROPIC_PLAIN = [
    {"role": "user", "content": "What is 2+2?"},
    {"role": "assistant", "content": "4"},
]

ANTHROPIC_TOOL_FLOW = [
    {"role": "user", "content": "What's the weather in Paris?"},
    {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_001",
                "name": "get_weather",
                "input": {"city": "Paris"},
            }
        ],
    },
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_001",
                "content": "15°C, cloudy",
            }
        ],
    },
    {"role": "assistant", "content": "The weather in Paris is 15°C and cloudy."},
]

ANTHROPIC_TOOLS_DEF = [
    {
        "name": "get_weather",
        "description": "Get current weather",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    }
]


# ---------------------------------------------------------------------------
# Tests: OpenAI → Anthropic
# ---------------------------------------------------------------------------


def test_oai_to_anthropic_system_extracted():
    result = convert(OAI_PLAIN, "openai_to_anthropic")
    assert result.get("system") == "You are a helpful assistant.", (
        "system message must be lifted to top-level 'system' field"
    )


def test_oai_to_anthropic_system_not_in_messages():
    result = convert(OAI_PLAIN, "openai_to_anthropic")
    roles = [m["role"] for m in result["messages"]]
    assert "system" not in roles, "system role must not appear inside 'messages'"


def test_oai_to_anthropic_plain_message_count():
    result = convert(OAI_PLAIN, "openai_to_anthropic")
    assert len(result["messages"]) == 2, "system removed → 2 messages remain"


def test_oai_to_anthropic_tool_call_becomes_tool_use_block():
    result = convert(OAI_TOOL_FLOW, "openai_to_anthropic")
    assistant_msgs = [m for m in result["messages"] if m["role"] == "assistant"]
    first_assistant = assistant_msgs[0]
    content = first_assistant["content"]
    assert isinstance(content, list), "tool-calling assistant content must be a list"
    types = [b["type"] for b in content]
    assert "tool_use" in types, "must contain a tool_use block"


def test_oai_to_anthropic_tool_use_id_and_name():
    result = convert(OAI_TOOL_FLOW, "openai_to_anthropic")
    all_blocks = [
        b
        for m in result["messages"]
        for b in (m["content"] if isinstance(m["content"], list) else [])
    ]
    tool_use = next((b for b in all_blocks if b.get("type") == "tool_use"), None)
    assert tool_use is not None
    assert tool_use["name"] == "get_weather"
    assert tool_use["input"] == {"city": "Paris"}, (
        "arguments JSON string must be parsed into a dict"
    )


def test_oai_to_anthropic_tool_result_becomes_user_message():
    result = convert(OAI_TOOL_FLOW, "openai_to_anthropic")
    # tool result must appear as a user-role message with tool_result block
    user_msgs = [m for m in result["messages"] if m["role"] == "user"]
    tool_result_blocks = [
        b
        for m in user_msgs
        for b in (m["content"] if isinstance(m["content"], list) else [])
        if isinstance(b, dict) and b.get("type") == "tool_result"
    ]
    assert len(tool_result_blocks) == 1
    assert tool_result_blocks[0]["content"] == "15°C, cloudy"


def test_oai_to_anthropic_no_tool_role_messages():
    result = convert(OAI_TOOL_FLOW, "openai_to_anthropic")
    roles = [m["role"] for m in result["messages"]]
    assert "tool" not in roles, "Anthropic has no 'tool' role — must be converted"


def test_oai_to_anthropic_tools_definition():
    result = convert([], "openai_to_anthropic", tools=OAI_TOOLS_DEF)
    assert "tools" in result
    tool = result["tools"][0]
    assert "input_schema" in tool, "OpenAI 'parameters' must become 'input_schema'"
    assert "parameters" not in tool
    assert tool["name"] == "get_weather"


# ---------------------------------------------------------------------------
# Tests: Anthropic → OpenAI
# ---------------------------------------------------------------------------


def test_anthropic_to_oai_system_becomes_message():
    result = convert(
        ANTHROPIC_PLAIN,
        "anthropic_to_openai",
        system="You are a helpful assistant.",
    )
    messages = result["messages"]
    assert messages[0]["role"] == "system", "system kwarg must become first message"
    assert messages[0]["content"] == "You are a helpful assistant."


def test_anthropic_to_oai_plain_message_count():
    result = convert(
        ANTHROPIC_PLAIN,
        "anthropic_to_openai",
        system="You are a helpful assistant.",
    )
    assert len(result["messages"]) == 3  # system + user + assistant


def test_anthropic_to_oai_tool_use_becomes_tool_calls():
    result = convert(ANTHROPIC_TOOL_FLOW, "anthropic_to_openai")
    assistant_msgs = [m for m in result["messages"] if m["role"] == "assistant"]
    first = assistant_msgs[0]
    assert "tool_calls" in first, "tool_use block must become tool_calls"
    tc = first["tool_calls"][0]
    assert tc["function"]["name"] == "get_weather"
    args = json.loads(tc["function"]["arguments"])
    assert args == {"city": "Paris"}, "input dict must be serialised to JSON string"


def test_anthropic_to_oai_tool_result_becomes_tool_role():
    result = convert(ANTHROPIC_TOOL_FLOW, "anthropic_to_openai")
    roles = [m["role"] for m in result["messages"]]
    assert "tool" in roles, "tool_result block must become a role:tool message"


def test_anthropic_to_oai_tool_result_id():
    result = convert(ANTHROPIC_TOOL_FLOW, "anthropic_to_openai")
    tool_msgs = [m for m in result["messages"] if m["role"] == "tool"]
    assert tool_msgs[0]["tool_call_id"] == "toolu_001"
    assert tool_msgs[0]["content"] == "15°C, cloudy"


def test_anthropic_to_oai_no_user_tool_result_blocks():
    result = convert(ANTHROPIC_TOOL_FLOW, "anthropic_to_openai")
    for m in result["messages"]:
        if m["role"] == "user":
            content = m.get("content", "")
            if isinstance(content, list):
                for b in content:
                    assert b.get("type") != "tool_result", (
                        "tool_result blocks must be converted to role:tool messages"
                    )


def test_anthropic_to_oai_tools_definition():
    result = convert([], "anthropic_to_openai", tools=ANTHROPIC_TOOLS_DEF)
    assert "tools" in result
    tool = result["tools"][0]
    assert tool["type"] == "function"
    func = tool["function"]
    assert "parameters" in func, "Anthropic 'input_schema' must become 'parameters'"
    assert "input_schema" not in func
    assert func["name"] == "get_weather"


def test_extra_kwargs_passed_through_oai_to_anthropic():
    result = convert([], "openai_to_anthropic", model="claude-opus-4-8", max_tokens=1024)
    assert result.get("model") == "claude-opus-4-8", "extra kwargs must appear in output"
    assert result.get("max_tokens") == 1024


def test_extra_kwargs_passed_through_anthropic_to_oai():
    result = convert([], "anthropic_to_openai", model="gpt-4o", temperature=0.7)
    assert result.get("model") == "gpt-4o", "extra kwargs must appear in output"
    assert result.get("temperature") == 0.7


# ---------------------------------------------------------------------------
# Tests: SDK validation via mock transport
# ---------------------------------------------------------------------------


def test_sdk_validates_oai_to_anthropic():
    """Pass converted payload through the Anthropic SDK (mock transport) to verify the SDK accepts it."""
    import anthropic

    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "msg_01",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "model": "claude-opus-4-8",
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = anthropic.Anthropic(
        api_key="test",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    # OAI_PLAIN has a system message → verify it is lifted to top-level 'system'
    result = convert(OAI_PLAIN, "openai_to_anthropic", model="claude-opus-4-8")
    client.messages.create(max_tokens=100, **result)

    body = captured["body"]
    assert "messages" in body, "SDK serialised payload must have 'messages'"
    assert body.get("system") is not None, "system must be at top level in Anthropic payload"
    roles = [m["role"] for m in body["messages"]]
    assert "system" not in roles, "system role must not appear inside messages array"


def test_sdk_validates_anthropic_to_oai():
    """Pass converted payload through the OpenAI SDK (mock transport) to verify the SDK accepts it."""
    import openai

    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-01",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "gpt-4o",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok", "refusal": None},
                        "logprobs": None,
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    client = openai.OpenAI(
        api_key="sk-test",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = convert(
        ANTHROPIC_TOOL_FLOW,
        "anthropic_to_openai",
        model="gpt-4o",
        system="You are helpful.",
    )
    client.chat.completions.create(**result)

    body = captured["body"]
    assert "messages" in body, "SDK serialised payload must have 'messages'"
    assert body["messages"][0]["role"] == "system", "system must be the first message"
    roles = [m["role"] for m in body["messages"]]
    assert "tool" in roles, "tool_result must become role:tool message"
