import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from harbor.analyze import backend_router
from harbor.analyze.backends.codex import (
    DEFAULT_CODEX_MODEL,
    _codex_config_overrides,
    _codex_model_name,
    _ensure_codex_auth,
    _strict_json_schema,
)
from harbor.analyze.backend import normalize_model_name, query_agent

RESULT_MSG_KWARGS: dict[str, Any] = dict(
    subtype="result",
    duration_ms=1000,
    duration_api_ms=800,
    is_error=False,
    num_turns=3,
    session_id="test-session",
    total_cost_usd=0.01,
)


async def _make_messages(*messages):
    """Async generator that yields the given messages."""
    for msg in messages:
        yield msg


# ---------------------------------------------------------------------------
# normalize_model_name
# ---------------------------------------------------------------------------


class TestNormalizeModelName:
    @pytest.mark.unit
    def test_strips_anthropic_prefix(self):
        assert (
            normalize_model_name("anthropic/claude-sonnet-4-6") == "claude-sonnet-4-6"
        )

    @pytest.mark.unit
    def test_strips_anthropic_prefix_opus(self):
        assert normalize_model_name("anthropic/claude-opus-4-6") == "claude-opus-4-6"

    @pytest.mark.unit
    def test_strips_anthropic_prefix_haiku(self):
        assert (
            normalize_model_name("anthropic/claude-haiku-4-5-20251001")
            == "claude-haiku-4-5-20251001"
        )

    @pytest.mark.unit
    def test_passthrough_short_name(self):
        assert normalize_model_name("sonnet") == "sonnet"

    @pytest.mark.unit
    def test_passthrough_long_name(self):
        assert normalize_model_name("claude-sonnet-4-6") == "claude-sonnet-4-6"

    @pytest.mark.unit
    def test_passthrough_non_anthropic(self):
        assert normalize_model_name("gpt-4") == "gpt-4"


# ---------------------------------------------------------------------------
# query_agent
# ---------------------------------------------------------------------------


class TestQueryAgent:
    @pytest.fixture(autouse=True)
    def _set_api_key(self, monkeypatch):
        """Set ANTHROPIC_API_KEY for query_agent tests."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_structured_output_from_result_message(self):
        """ResultMessage.structured_output is returned as dict."""
        expected = {"summary": "All good", "score": 10}
        messages = [
            AssistantMessage(content=[TextBlock(text="Analyzing...")], model="sonnet"),
            ResultMessage(**RESULT_MSG_KWARGS, structured_output=expected),
        ]

        with patch(
            "harbor.analyze.backend.query",
            return_value=_make_messages(*messages),
        ):
            output, estimated_cost_usd = await query_agent(
                prompt="test",
                model="sonnet",
                cwd="/tmp",
                output_schema={"type": "object"},
            )

        assert output == expected
        assert estimated_cost_usd == 0.01

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_structured_output_fallback_to_tool_use_block(self):
        """ToolUseBlock named 'StructuredOutput' is used when ResultMessage has None."""
        expected = {"summary": "Fallback result", "score": 5}
        messages = [
            AssistantMessage(
                content=[
                    ToolUseBlock(id="tool-1", name="StructuredOutput", input=expected)
                ],
                model="sonnet",
            ),
            AssistantMessage(content=[TextBlock(text="Done.")], model="sonnet"),
            ResultMessage(**RESULT_MSG_KWARGS, structured_output=None),
        ]

        with patch(
            "harbor.analyze.backend.query",
            return_value=_make_messages(*messages),
        ):
            output, estimated_cost_usd = await query_agent(
                prompt="test",
                model="sonnet",
                cwd="/tmp",
                output_schema={"type": "object"},
            )

        assert output == expected
        assert estimated_cost_usd == 0.01

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_result_message_preferred_over_tool_block(self):
        """ResultMessage.structured_output takes precedence over ToolUseBlock."""
        tool_output = {"summary": "Early draft", "score": 1}
        result_output = {"summary": "Final answer", "score": 10}

        messages = [
            AssistantMessage(
                content=[
                    ToolUseBlock(
                        id="tool-1", name="StructuredOutput", input=tool_output
                    )
                ],
                model="sonnet",
            ),
            ResultMessage(**RESULT_MSG_KWARGS, structured_output=result_output),
        ]

        with patch(
            "harbor.analyze.backend.query",
            return_value=_make_messages(*messages),
        ):
            output, estimated_cost_usd = await query_agent(
                prompt="test",
                model="sonnet",
                cwd="/tmp",
                output_schema={"type": "object"},
            )

        assert output == result_output
        assert estimated_cost_usd == 0.01

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_free_text_no_schema(self):
        """Without output_schema, returns concatenated text from TextBlocks."""
        messages = [
            AssistantMessage(
                content=[TextBlock(text="Hello"), TextBlock(text="World")],
                model="sonnet",
            ),
            ResultMessage(**RESULT_MSG_KWARGS, structured_output=None),
        ]

        with patch(
            "harbor.analyze.backend.query",
            return_value=_make_messages(*messages),
        ):
            output, estimated_cost_usd = await query_agent(
                prompt="test",
                model="sonnet",
                cwd="/tmp",
                output_schema=None,
            )

        assert output == "Hello\nWorld"
        assert estimated_cost_usd == 0.01

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_raises_when_schema_but_no_structured_output(self):
        """ValueError when output_schema is provided but no structured output returned."""
        messages = [
            AssistantMessage(content=[TextBlock(text="Oops")], model="sonnet"),
            ResultMessage(**RESULT_MSG_KWARGS, structured_output=None),
        ]

        with patch(
            "harbor.analyze.backend.query",
            return_value=_make_messages(*messages),
        ):
            with pytest.raises(
                ValueError, match="SDK did not return structured output"
            ):
                await query_agent(
                    prompt="test",
                    model="sonnet",
                    cwd="/tmp",
                    output_schema={"type": "object"},
                )


class TestBackendRouter:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_routes_claude_to_existing_backend(self):
        async def mock_query_agent(**kwargs):
            return {"ok": True}, 0.01

        with patch(
            "harbor.analyze.backend_router.claude_backend.query_agent",
            side_effect=mock_query_agent,
        ) as mock_query:
            output, cost = await backend_router.query_agent(
                prompt="test",
                model="sonnet",
                cwd="/tmp",
                output_schema={"type": "object"},
                sdk="claude",
            )

        assert output == {"ok": True}
        assert cost == 0.01
        assert mock_query.await_count == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_routes_codex_to_codex_backend(self):
        async def mock_query_agent(**kwargs):
            return {"ok": True}, None

        with patch(
            "harbor.analyze.backends.codex.query_agent",
            side_effect=mock_query_agent,
        ) as mock_query:
            output, cost = await backend_router.query_agent(
                prompt="test",
                model="gpt-5",
                cwd="/tmp",
                output_schema={"type": "object"},
                sdk="codex",
            )

        assert output == {"ok": True}
        assert cost is None
        assert mock_query.await_count == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unknown_sdk_raises(self):
        with pytest.raises(ValueError, match="Unknown SDK"):
            await backend_router.query_agent(
                prompt="test",
                model="sonnet",
                cwd="/tmp",
                sdk="unknown",
            )


class TestCodexAuth:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prefers_local_account_over_env_api_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        codex = SimpleNamespace(
            account=AsyncMock(
                return_value=SimpleNamespace(
                    account=SimpleNamespace(root=object()),
                    requires_openai_auth=True,
                )
            ),
            login_api_key=AsyncMock(),
        )

        await _ensure_codex_auth(codex)

        codex.account.assert_awaited_once_with(refresh_token=True)
        codex.login_api_key.assert_not_awaited()


class TestCodexSchema:
    @pytest.mark.unit
    def test_adds_additional_properties_false_to_nested_objects(self):
        schema = {
            "type": "object",
            "properties": {
                "checks": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
        }

        strict = _strict_json_schema(schema)

        assert strict["additionalProperties"] is False
        assert strict["properties"]["checks"]["additionalProperties"] is False
        assert strict["properties"]["items"]["items"]["additionalProperties"] is False
        assert "additionalProperties" not in schema["properties"]["items"]["items"]


class TestCodexConfigOverrides:
    @pytest.mark.unit
    def test_maps_add_dirs_to_writable_roots_override(self, tmp_path):
        task_dir = tmp_path / "task"
        task_dir.mkdir()

        overrides = _codex_config_overrides([str(task_dir)])

        assert len(overrides) == 1
        key, value = overrides[0].split("=", 1)
        assert key == "sandbox_workspace_write.writable_roots"
        assert json.loads(value) == [str(task_dir.resolve())]

    @pytest.mark.unit
    def test_no_add_dirs_returns_no_overrides(self):
        assert _codex_config_overrides(None) == ()


class TestCodexModelName:
    @pytest.mark.unit
    @pytest.mark.parametrize("model", ["haiku", "sonnet", "opus"])
    def test_maps_claude_aliases_to_codex_default(self, model):
        assert _codex_model_name(model) == DEFAULT_CODEX_MODEL

    @pytest.mark.unit
    def test_preserves_explicit_codex_model(self):
        assert _codex_model_name("gpt-5.4-mini") == "gpt-5.4-mini"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_falls_back_to_env_api_key_when_local_auth_missing(self, monkeypatch):
        monkeypatch.setenv("CODEX_API_KEY", "codex-key")
        codex = SimpleNamespace(
            account=AsyncMock(
                return_value=SimpleNamespace(
                    account=None,
                    requires_openai_auth=True,
                )
            ),
            login_api_key=AsyncMock(),
        )

        await _ensure_codex_auth(codex)

        codex.account.assert_awaited_once_with(refresh_token=True)
        codex.login_api_key.assert_awaited_once_with("codex-key")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_raises_when_no_local_auth_or_env_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("CODEX_API_KEY", raising=False)
        codex = SimpleNamespace(
            account=AsyncMock(
                return_value=SimpleNamespace(
                    account=None,
                    requires_openai_auth=True,
                )
            ),
            login_api_key=AsyncMock(),
        )

        with pytest.raises(RuntimeError, match="Codex local OAuth is not available"):
            await _ensure_codex_auth(codex)

        codex.login_api_key.assert_not_awaited()
