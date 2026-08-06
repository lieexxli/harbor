# SWE-bench Live Harbor Adapter

Converts local SWE-bench Live parquet data into Harbor task directories.

## Usage

```bash
cd adapters/swebench_live
uv run swebench-live --limit 5
```

By default, the adapter reads:

```text
SWE-bench-Live-merged/data
```

and writes generated tasks to:

```text
datasets/swebench-live
```

Generate a single task:

```bash
uv run swebench-live --instance-id psf__requests-7433 --overwrite
```

Use a custom parquet directory or file:

```bash
uv run swebench-live --data-dir ../../SWE-bench-Live-merged/data --output-dir ../../datasets/swebench-live
```

## Difficulty curation

Generated `task.toml` files are build artifacts. Do not hand-edit their
`metadata.difficulty` values as the next conversion will overwrite them.

Curated difficulty changes live in:

```text
adapters/swebench_live/difficulty-overrides.toml
```

The adapter applies this file after loading the source parquet row and before
rendering `task.toml`, `tests/config.json`, and resource timeouts. Use
`--difficulty-overrides PATH` to test a different override file.

## Verification

The generated verifier uses the dataset-provided `test_patch`, `rebuild_cmds`, `test_cmds`,
`print_cmds`, `log_parser`, `FAIL_TO_PASS`, and `PASS_TO_PASS` fields. During `harbor run`,
it first saves the agent's `git diff HEAD --text` as `pred.patch`, resets the repository to
`base_commit`, then applies `test_patch` followed by `pred.patch`. This mirrors the
SWE-bench Live evaluator's patch replay flow while keeping the task self-contained inside
Harbor.

Agent execution uses a network allowlist containing only the model service
endpoints required by the supported agent harnesses (`api.anthropic.com`,
`api.openai.com`, `chatgpt.com`, `api.cursor.com`, `*.cursor.sh`,
`api.cline.bot`, `opencode.ai`). General web access, telemetry endpoints,
error-reporting services, and source-hosting sites such as GitHub remain
blocked during task solving. Verifier execution keeps `network_mode =
"public"` so rebuild and test commands can install dependencies.

## Quality checks

Use the SWE-bench Live specific rubric for Harbor semantic checks:

```bash
uv run harbor check datasets/swebench-live-check-requests/psf__requests-7433 \
  --rubric adapters/swebench_live/swebench-live-check-rubric.toml
```

This rubric assumes the source rows have already passed SWE-bench Live `validation.py`.
It is a post-validation benchmark acceptance rubric: it does not repeat gold-patch
execution validation. It focuses on whether a converted task is worth keeping as a
benchmark sample, whether the task is fair and non-leaking, whether hidden tests align
with the issue/PR behavior, and whether Harbor packaging preserves SWE-bench Live
evaluation semantics.
