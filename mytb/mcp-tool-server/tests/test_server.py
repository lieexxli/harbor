import asyncio

from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

SERVER = StdioServerParameters(command="python", args=["/app/server.py"])


async def _list_tools():
    async with stdio_client(SERVER) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return await s.list_tools()


async def _call(name, args):
    async with stdio_client(SERVER) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return await s.call_tool(name, args)


def _contains_mcp_error(exc: BaseException) -> bool:
    if isinstance(exc, McpError):
        return True
    if isinstance(exc, ExceptionGroup):
        return any(_contains_mcp_error(child) for child in exc.exceptions)
    return False


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


def test_exactly_three_tools():
    result = asyncio.run(_list_tools())
    names = {t.name for t in result.tools}
    assert names == {"add", "reverse", "count_words"}, (
        f"server must expose exactly {{add, reverse, count_words}}, got {names}"
    )


def test_tools_have_input_schema():
    result = asyncio.run(_list_tools())
    for tool in result.tools:
        assert tool.inputSchema is not None, f"'{tool.name}' missing inputSchema"


def test_tool_schemas_describe_parameters():
    result = asyncio.run(_list_tools())
    schemas = {t.name: t.inputSchema for t in result.tools}

    add_props = schemas["add"].get("properties", {})
    assert "a" in add_props, "add inputSchema must describe parameter 'a'"
    assert "b" in add_props, "add inputSchema must describe parameter 'b'"

    reverse_props = schemas["reverse"].get("properties", {})
    assert "text" in reverse_props, "reverse inputSchema must describe parameter 'text'"

    cw_props = schemas["count_words"].get("properties", {})
    assert "text" in cw_props, "count_words inputSchema must describe parameter 'text'"


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def test_add_integers():
    result = asyncio.run(_call("add", {"a": 3, "b": 4}))
    assert not result.isError
    assert float(result.content[0].text) == 7.0


def test_add_floats():
    result = asyncio.run(_call("add", {"a": 1.5, "b": 2.5}))
    assert not result.isError
    assert float(result.content[0].text) == 4.0


def test_add_negative():
    result = asyncio.run(_call("add", {"a": -3, "b": 1}))
    assert not result.isError
    assert float(result.content[0].text) == -2.0


# ---------------------------------------------------------------------------
# reverse
# ---------------------------------------------------------------------------


def test_reverse_word():
    result = asyncio.run(_call("reverse", {"text": "hello"}))
    assert not result.isError
    assert result.content[0].text == "olleh"


def test_reverse_sentence():
    result = asyncio.run(_call("reverse", {"text": "abc def"}))
    assert not result.isError
    assert result.content[0].text == "fed cba"


def test_reverse_empty_string():
    result = asyncio.run(_call("reverse", {"text": ""}))
    assert not result.isError
    assert result.content[0].text == ""


# ---------------------------------------------------------------------------
# count_words
# ---------------------------------------------------------------------------


def test_count_words_multiple():
    result = asyncio.run(_call("count_words", {"text": "hello world foo"}))
    assert not result.isError
    assert int(result.content[0].text) == 3


def test_count_words_single():
    result = asyncio.run(_call("count_words", {"text": "hello"}))
    assert not result.isError
    assert int(result.content[0].text) == 1


def test_count_words_empty():
    result = asyncio.run(_call("count_words", {"text": ""}))
    assert not result.isError
    assert int(result.content[0].text) == 0


# ---------------------------------------------------------------------------
# Error handling: unknown tool must return isError:true (MCP tool-call error),
# not a JSON-RPC protocol error
# ---------------------------------------------------------------------------


def test_unknown_tool_returns_error():
    """Server must not crash on an unknown tool; only MCP errors are acceptable."""
    try:
        result = asyncio.run(_call("nonexistent_tool", {}))
        assert result.isError is True, (
            "calling an unknown tool must set isError=true in the MCP result"
        )
    except Exception as exc:
        # McpError, or an ExceptionGroup wrapping one from anyio TaskGroup, is acceptable.
        if not _contains_mcp_error(exc):
            raise
