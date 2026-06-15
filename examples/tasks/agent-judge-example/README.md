# Agent-as-a-Judge Example Task

This example demonstrates how to use RewardKit with an **agent judge** (Claude Code) to evaluate the agent's output. Unlike an LLM judge that only reads file content, the agent judge can explore the filesystem and run commands.

## Overview

The agent is asked to write a funny poem. Instead of a custom Python script calling an LLM API, the verifier uses RewardKit with `judge = "claude-code"` — the judge agent reads the poem from the workspace and rates it.

## Configuration

[task.toml](task.toml) passes the API key to the verifier:

```toml
[verifier.env]
CLAUDE_CODE_OAUTH_TOKEN = "${CLAUDE_CODE_OAUTH_TOKEN}"
```

## How It Works

1. **Agent writes a poem** to `/app/poem.txt`
2. **test.sh** calls `uvx rewardkit /tests`
3. **RewardKit** finds `tests/quality/judge.toml`, which declares an agent judge:
   - `judge = "claude-code"` — uses Claude Code CLI to evaluate
   - `model = "anthropic/claude-sonnet-4-6"` — the model Claude Code uses
   - `isolated = true` — overlayfs isolation, won't mutate the workspace
4. **Claude Code** reads the poem, explores the workspace if needed, and returns a structured score
5. **Reward** is written to `/logs/verifier/reward.json`

### Judge Configuration

[tests/quality/judge.toml](tests/quality/judge.toml):

```toml
[judge]
judge = "claude-code"
model = "anthropic/claude-sonnet-4-6"
isolated = true

[[criterion]]
name = "funny"
description = "Rate how funny this poem is from 0.0 to 1.0."
type = "numeric"
min = 0.0
max = 1.0
weight = 1.0
```

### Agent Judge vs LLM Judge

| | LLM Judge | Agent Judge |
|---|---|---|
| API | Direct LLM API call | Shells out to a CLI agent |
| Filesystem | Only reads specified files | Can `ls`, `cat`, run commands |
| Speed | Fast (single API call) | Slower (multi-turn agent) |
| Cost | Low | Higher (multi-turn tokens) |
| Config | `judge = "anthropic/..."` | `judge = "claude-code"` |

## Running the Task

### Prerequisites

Claude Code OAuth token (from `claude login`):

```bash
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat-..."
```

### Run with Oracle Agent

```bash
harbor run -p examples/tasks/agent-judge-example --agent oracle
```

### Run with Any Agent

```bash
harbor run -p examples/tasks/agent-judge-example --agent terminus-2 --model anthropic/claude-sonnet-4-6
```
