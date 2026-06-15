"""Route analysis queries to the selected SDK backend.

The original Claude Agent SDK implementation stays in ``backend.py`` to keep
upstream sync conflicts small. Additional SDKs live under ``backends/``.
"""

from __future__ import annotations

from typing import Any

from harbor.analyze import backend as claude_backend


SUPPORTED_SDKS = ("claude", "codex")


def _normalize_sdk(sdk: str) -> str:
    normalized = sdk.strip().lower()
    if normalized not in SUPPORTED_SDKS:
        supported = "', '".join(SUPPORTED_SDKS)
        raise ValueError(f"Unknown SDK '{sdk}'. Supported values: '{supported}'.")
    return normalized


async def query_agent(
    prompt: str,
    model: str,
    cwd: str,
    tools: list[str] | None = None,
    add_dirs: list[str] | None = None,
    output_schema: dict[str, Any] | None = None,
    verbose: bool = False,
    sdk: str = "claude",
) -> tuple[str | dict[str, Any], float | None]:
    """Run an analysis query against the selected SDK backend."""
    match _normalize_sdk(sdk):
        case "claude":
            return await claude_backend.query_agent(
                prompt=prompt,
                model=model,
                cwd=cwd,
                tools=tools,
                add_dirs=add_dirs,
                output_schema=output_schema,
                verbose=verbose,
            )
        case "codex":
            from harbor.analyze.backends.codex import query_agent as query_codex

            return await query_codex(
                prompt=prompt,
                model=model,
                cwd=cwd,
                tools=tools,
                add_dirs=add_dirs,
                output_schema=output_schema,
                verbose=verbose,
            )
    raise AssertionError("unreachable")


async def query_llm(
    prompt: str,
    model: str,
    output_schema: dict[str, Any] | None = None,
    verbose: bool = False,
    sdk: str = "claude",
) -> tuple[str | dict[str, Any], float | None]:
    """Run a plain LLM call against the selected SDK backend."""
    match _normalize_sdk(sdk):
        case "claude":
            return await claude_backend.query_llm(
                prompt=prompt,
                model=model,
                output_schema=output_schema,
                verbose=verbose,
            )
        case "codex":
            from harbor.analyze.backends.codex import query_llm as query_codex_llm

            return await query_codex_llm(
                prompt=prompt,
                model=model,
                output_schema=output_schema,
                verbose=verbose,
            )
    raise AssertionError("unreachable")
