# LLM Tool Gateway Policy Engine

This task asks an agent to implement `/app/gateway.py`, a deterministic authorization layer for LLM-proposed tool calls. The task models a production-style tool gateway: the LLM proposes a call, and a separate policy engine validates schema, scopes, provenance, taint, resource ACLs, canonicalization, and confirmation binding before execution.

## Environment

The task uses `python:3.12-slim`. The image includes:

- `/app/policy.json`: tool schemas and policy rules.
- `/app/requests.jsonl`: public authorization requests.

Agent timeout is 900 seconds.

## Verifier

The verifier is pytest-based.

| Check | Type | Measures |
| --- | --- | --- |
| Public decisions | Programmatic | Correct allow/deny/needs_confirmation decisions on public cases |
| Default invocation | Programmatic | `/app/gateway.py` runs without arguments and writes `/app/decisions.jsonl` |
| Hidden policy DSL | Programmatic | Generalization to different tool names and the same policy format |
| Taint and ACL | Programmatic | Untrusted/secret-derived arguments, resource action checks, tenant boundaries |
| Canonicalization and confirmation | Programmatic | URL/email/path normalization and SHA-256 confirmation binding |
| Output schema | Programmatic | Strict output shape, ordering, and audit metadata |

## Layout

```text
prompt-injection-tool-router/
├── instruction.md
├── task.toml
├── environment/
│   ├── Dockerfile
│   ├── policy.json
│   └── requests.jsonl
├── tests/
│   ├── test.sh
│   └── test_outputs.py
└── solution/
    └── solve.sh
```

## Running

```bash
harbor run -p mytb/prompt-injection-tool-router -a oracle
harbor run -p mytb/prompt-injection-tool-router -a claude-code
```
