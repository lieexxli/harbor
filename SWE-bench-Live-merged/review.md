# Merged Dataset Review

This local dataset merges the remaining reviewed samples from `swetry1` and `SWE-bench-Live`.

## Current State

- Current retained rows: **25** (easy 12 / medium 9 / hard 4)
- duplicate `instance_id`: none
- Post-merge removals (26 total) are recorded per sample in
  `harbor-check-notes.md` ("Removed Samples" table); structured entries for
  the cross-model-run and post-run-analyze batches are in `provenance.json`.

## Merge-Time State (historical)

- `swetry1` retained rows: 7
- `SWE-bench-Live` retained rows: 44
- merged rows: 51

## Included Sources

- `swetry1/data/python-00000-of-00001.parquet`
- `SWE-bench-Live/data/python-00000-of-00001.parquet`

## Output Files

- `data/python-00000-of-00001.parquet`
- `readable/index.md`
- `readable/summary.csv`
- `readable/summary.json`
- `provenance.json`
- `difficulty-rubric.md`
- `difficulty-labels.csv`
- `difficulty-distribution.json`

## Difficulty Schema

The original patch-size object formerly stored in `difficulty` has been renamed to `patch_stats`.

The new `difficulty` field is a benchmark task difficulty label with allowed values:

- `easy`
- `medium`
- `hard`
- `unknown`

These labels estimate solving difficulty for benchmark evaluation and are not mechanically derived from patch size. The rubric is documented in `difficulty-rubric.md`.

Current distribution (25 retained rows, matches `difficulty-distribution.json`):

- `easy`: 12
- `medium`: 9
- `hard`: 4
- `unknown`: 0

Merge-time distribution over the original 51 rows was easy 10 / medium 30 /
hard 11.

## Verification Notes

The source datasets were already cleaned before merging. Removed samples are recorded in `provenance.json` and in each source dataset's `review.md`.

Docker execution verification was deferred at merge time. It has since been
covered by cross-model Harbor run validation (DeepSeek V4 Flash/Pro, Cursor
Auto, Cursor Claude Sonnet 5, Codex GPT-5.5) and post-run analyze; see
`harbor-check-notes.md` for outcomes and removals.
