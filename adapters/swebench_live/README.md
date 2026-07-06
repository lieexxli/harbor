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

## Verification

The generated verifier uses the dataset-provided `test_patch`, `rebuild_cmds`, `test_cmds`,
`print_cmds`, `log_parser`, `FAIL_TO_PASS`, and `PASS_TO_PASS` fields. During `harbor run`,
it first saves the agent's `git diff HEAD --text` as `pred.patch`, resets the repository to
`base_commit`, then applies `test_patch` followed by `pred.patch`. This mirrors the
SWE-bench Live evaluator's patch replay flow while keeping the task self-contained inside
Harbor.

## Quality checks

Use the SWE-bench Live specific rubric for Harbor semantic checks:

```bash
uv run harbor check datasets/swebench-live-check-requests/psf__requests-7433 \
  --rubric adapters/swebench_live/swebench-live-rubric.toml \
  --prompt adapters/swebench_live/swebench-live-check-prompt.txt
```

This rubric assumes the source rows have already passed SWE-bench Live `validation.py`.
It is a post-validation benchmark acceptance rubric: it does not repeat gold-patch
execution validation. It focuses on whether a converted task is worth keeping as a
benchmark sample, whether the task is fair and non-leaking, whether hidden tests align
with the issue/PR behavior, and whether Harbor packaging preserves SWE-bench Live
evaluation semantics.
