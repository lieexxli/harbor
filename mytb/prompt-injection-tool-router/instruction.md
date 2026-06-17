# LLM Tool Gateway Policy Engine

Implement `/app/gateway.py`, a deterministic authorization layer for LLM-proposed tool calls.

The LLM has already proposed a tool call. Your program must not infer intent from natural language. It must decide whether each proposed call is safe to execute by applying policy, schema, provenance, taint, and confirmation rules.

Inputs:

- `/app/policy.json`: tool definitions and global policy.
- `/app/requests.jsonl`: one authorization request per line.

Default invocation:

```bash
python /app/gateway.py
```

Also support explicit paths:

```bash
python /app/gateway.py --policy /path/policy.json --requests /path/requests.jsonl --output /path/decisions.jsonl
```

Write `/app/decisions.jsonl`, preserving input order. Each output line must be:

```json
{
  "id": "request id",
  "decision": "allow | deny | needs_confirmation",
  "normalized_call": {"name": "tool.name", "arguments": {}},
  "violations": ["machine_readable_codes"],
  "audit": {
    "normalized": true,
    "tainted_arguments": [],
    "confirmation_bound": false
  }
}
```

Use `normalized_call: null` when the call cannot be normalized safely. `violations` must be non-empty for `deny` and `needs_confirmation`.

Policy semantics:

- Validate the proposed tool name exists.
- Validate arguments exactly against the tool JSON schema. Required fields must exist, extra fields are forbidden, strings must obey `format`, `pattern`, `maxLength`, and integers must obey `minimum`/`maximum`.
- Canonicalize security-sensitive values before policy checks:
  - email addresses: lowercase and strip trailing punctuation.
  - URLs: require `https`, reject credentials/userinfo, reject encoded or suffix-spoofed hosts, lowercase host, strip trailing host dot, decode path, reject traversal.
  - paths: decode percent escapes, normalize POSIX-style, require allowed prefixes, reject traversal and backslashes.
- Enforce scopes: request scopes are `user_grants.scopes - user_grants.revoked_scopes`; tool `required_scopes` must be included.
- Enforce resource ACLs. For arguments with `resource_ref`, the referenced object must exist in `data_objects`, the user must have the tool's required action for that object, and tenant IDs must match.
- Enforce provenance. Every argument has an entry in `argument_provenance`. Arguments marked `source = "trusted_user"` must come directly from `user`, not from webpage, email, file, attachment, tool_result, or model_inferred sources.
- Track taint through `data_objects` and argument provenance. Any argument sourced from an untrusted object, or from an object whose `data_class` is `secret`, is tainted unless the policy explicitly allows that source.
- External side-effect tools (`side_effect = "external_write"`) must not send tainted or secret-derived values.
- Tools with `requires_confirmation = true` return `needs_confirmation` unless the request has a confirmation token bound to the exact normalized call. The token is `sha256(policy.confirmation_salt + canonical_json(normalized_call))`, where canonical JSON uses sorted keys and compact separators.
- If multiple rules fail, report all applicable violations you can determine.

Use these canonical violation code prefixes in `violations`. You may add suffix detail after a colon for auditability, such as `schema_violation:days`, but the prefix before `:` should be one of:

- `unknown_tool`
- `schema_violation`
- `missing_scope`
- `resource_not_found`
- `resource_action_denied`
- `tenant_mismatch`
- `resource_mismatch`
- `untrusted_provenance`
- `secret_exfiltration`
- `tainted_external_write`
- `untrusted_domain`
- `confirmation_required`
- `confirmation_invalid`

The implementation should handle tools and requests following the same policy format as the provided files, not just the public examples.
