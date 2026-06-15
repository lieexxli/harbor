from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_CODEX_MODEL = "gpt-5.5"
CLAUDE_MODEL_ALIASES = {"haiku", "sonnet", "opus"}


async def _ensure_codex_auth(codex: Any, verbose: bool = False) -> None:
    """Prefer existing local Codex auth, then fall back to an env API key."""
    account = await codex.account(refresh_token=True)
    if account.account is not None:
        if verbose:
            print("\n-- Codex auth: using local account --", file=sys.stderr)
        return

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEX_API_KEY")
    if api_key:
        if verbose:
            print("\n-- Codex auth: using API key from environment --", file=sys.stderr)
        await codex.login_api_key(api_key)
        return

    raise RuntimeError(
        "Codex local OAuth is not available. Run `codex login` or set "
        "OPENAI_API_KEY/CODEX_API_KEY."
    )


def _codex_model_name(model: str) -> str:
    """Map Harbor's Claude-oriented defaults to a Codex model."""
    if model in CLAUDE_MODEL_ALIASES:
        return DEFAULT_CODEX_MODEL
    return model


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a Codex-compatible structured output schema."""
    strict_schema = json.loads(json.dumps(schema))

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(strict_schema)
    return strict_schema


def _codex_config_overrides(add_dirs: list[str] | None) -> tuple[str, ...]:
    """Map Claude-style add_dirs to Codex config overrides."""
    if not add_dirs:
        return ()

    writable_roots = [str(Path(path).resolve()) for path in add_dirs]
    return (
        "sandbox_workspace_write.writable_roots="
        f"{json.dumps(writable_roots, ensure_ascii=True)}",
    )


async def query_agent(
    prompt: str,
    model: str,
    cwd: str,
    tools: list[str] | None = None,
    add_dirs: list[str] | None = None,
    output_schema: dict[str, Any] | None = None,
    verbose: bool = False,
) -> tuple[str | dict[str, Any], float | None]:
    """Run an analysis query via the OpenAI Codex SDK."""
    from openai_codex import ApprovalMode, AsyncCodex, Sandbox
    from openai_codex.client import CodexConfig

    if verbose:
        print(f"\n── Codex Prompt ──\n{prompt}", file=sys.stderr)

    codex_model = _codex_model_name(model)
    config_overrides = _codex_config_overrides(add_dirs)
    sandbox = Sandbox.workspace_write if add_dirs else Sandbox.read_only
    config = CodexConfig(config_overrides=config_overrides)

    async with AsyncCodex(config=config) as codex:
        await _ensure_codex_auth(codex, verbose=verbose)
        thread = await codex.thread_start(
            cwd=cwd,
            model=codex_model,
            sandbox=sandbox,
            approval_mode=ApprovalMode.deny_all,
        )
        result = await thread.run(
            prompt,
            sandbox=sandbox,
            approval_mode=ApprovalMode.deny_all,
            output_schema=_strict_json_schema(output_schema) if output_schema else None,
        )

    if verbose and result.usage:
        print(
            f"\n-- Done: usage={result.usage} --",
            file=sys.stderr,
        )

    raw = result.final_response or ""
    if output_schema is None:
        return raw, None

    try:
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        raise ValueError(
            "Codex did not return valid JSON for structured output: "
            f"{e}\nRaw: {raw[:500]}"
        ) from e


async def query_llm(
    prompt: str,
    model: str,
    output_schema: dict[str, Any] | None = None,
    verbose: bool = False,
) -> tuple[str | dict[str, Any], float | None]:
    """Run a plain Codex LLM call without file access beyond read-only cwd."""
    return await query_agent(
        prompt=prompt,
        model=model,
        cwd=".",
        tools=[],
        output_schema=output_schema,
        verbose=verbose,
    )
