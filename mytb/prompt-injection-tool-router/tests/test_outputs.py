import hashlib
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


GATEWAY = Path("/app/gateway.py")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def confirmation_token(salt: str, normalized_call: dict) -> str:
    return hashlib.sha256((salt + canonical_json(normalized_call)).encode()).hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_gateway(
    tmp_path: Path, policy: dict | None = None, requests: list[dict] | None = None
) -> dict[str, dict]:
    assert GATEWAY.exists(), "/app/gateway.py does not exist"
    policy_path = (
        Path("/app/policy.json") if policy is None else tmp_path / "policy.json"
    )
    requests_path = (
        Path("/app/requests.jsonl") if requests is None else tmp_path / "requests.jsonl"
    )
    output_path = tmp_path / "decisions.jsonl"
    if policy is not None:
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
    if requests is not None:
        write_jsonl(requests_path, requests)
    subprocess.run(
        [
            sys.executable,
            str(GATEWAY),
            "--policy",
            str(policy_path),
            "--requests",
            str(requests_path),
            "--output",
            str(output_path),
        ],
        check=True,
        timeout=20,
    )
    rows = read_jsonl(output_path)
    expected_ids = [
        json.loads(line)["id"]
        for line in requests_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row.get("id") for row in rows] == expected_ids
    for row in rows:
        assert set(row) == {
            "id",
            "decision",
            "normalized_call",
            "violations",
            "audit",
        }
        assert row["decision"] in {"allow", "deny", "needs_confirmation"}
        assert isinstance(row["violations"], list)
        assert isinstance(row["audit"], dict)
        if row["decision"] == "allow":
            assert row["normalized_call"] is not None
            assert row["violations"] == []
        else:
            assert row["violations"]
    return {row["id"]: row for row in rows}


def assert_denied(row: dict, *codes: str) -> None:
    assert row["decision"] == "deny", row
    for code in codes:
        assert has_violation(row, code), row


def assert_confirmation(row: dict, *codes: str) -> None:
    assert row["decision"] == "needs_confirmation", row
    for code in codes:
        assert has_violation(row, code), row


def canonical_violation(code: str) -> str:
    head = code.split(":", 1)[0]
    if head in {
        "schema_required",
        "schema_additionalProperty",
        "schema_maximum",
        "schema_minimum",
        "email_invalid_format",
        "url_not_https",
        "url_userinfo_present",
        "url_encoded_hostname",
        "path_backslash",
        "path_traversal",
        "path_prefix",
    }:
        return "schema_violation"
    if head in {"source_untrusted", "missing_provenance"}:
        return "untrusted_provenance"
    if head == "domain_not_allowed":
        return "untrusted_domain"
    if head == "tainted_argument_external_write":
        return "tainted_external_write"
    if head == "resource_tenant_mismatch":
        return "tenant_mismatch"
    return head


def has_violation(row: dict, expected: str) -> bool:
    return any(canonical_violation(code) == expected for code in row["violations"])


def test_default_invocation_writes_default_output() -> None:
    output = Path("/app/decisions.jsonl")
    if output.exists():
        output.unlink()
    subprocess.run([sys.executable, str(GATEWAY)], check=True, timeout=20)
    rows = read_jsonl(output)
    assert rows[0]["id"] == "public-001"
    assert rows[-1]["id"] == "public-006"


def test_public_policy_cases(tmp_path: Path) -> None:
    rows = run_gateway(tmp_path)

    fetch = rows["public-001"]
    assert fetch["decision"] == "allow"
    assert fetch["normalized_call"] == {
        "name": "web.fetch",
        "arguments": {"url": "https://docs.python.org/3/library/json.html"},
    }

    assert_confirmation(rows["public-002"], "confirmation_required")
    assert rows["public-002"]["normalized_call"]["arguments"]["to"] == (
        "alice@company.example"
    )

    assert_denied(
        rows["public-003"],
        "untrusted_provenance",
        "secret_exfiltration",
        "untrusted_domain",
    )
    assert_denied(rows["public-004"], "resource_action_denied")
    assert_denied(rows["public-005"], "missing_scope")
    assert_denied(rows["public-006"], "schema_violation")


def test_hidden_policy_dsl_and_confirmation_binding(tmp_path: Path) -> None:
    salt = "hidden-salt:"
    policy = {
        "confirmation_salt": salt,
        "secret_patterns": ["tok_[A-Za-z0-9]+"],
        "tools": [
            {
                "name": "ticket.comment",
                "side_effect": "external_write",
                "required_scopes": ["ticket:comment"],
                "requires_confirmation": True,
                "parameters": {
                    "type": "object",
                    "required": ["ticket_id", "body"],
                    "additionalProperties": False,
                    "properties": {
                        "ticket_id": {"type": "string", "pattern": "^TCK-[0-9]{3}$"},
                        "body": {"type": "string", "maxLength": 80},
                    },
                },
                "argument_policies": {
                    "ticket_id": {"source": "trusted_user"},
                    "body": {"source": "trusted_user", "secret_safe": True},
                },
            },
            {
                "name": "repo.create_issue",
                "side_effect": "external_write",
                "required_scopes": ["repo:write"],
                "requires_confirmation": True,
                "parameters": {
                    "type": "object",
                    "required": ["repo", "title"],
                    "additionalProperties": False,
                    "properties": {
                        "repo": {
                            "type": "string",
                            "pattern": "^[a-z0-9-]+/[a-z0-9-]+$",
                        },
                        "title": {"type": "string", "maxLength": 60},
                    },
                },
                "argument_policies": {
                    "repo": {"source": "trusted_user"},
                    "title": {"source": "trusted_user", "secret_safe": True},
                },
            },
        ],
    }
    normalized = {
        "name": "ticket.comment",
        "arguments": {"ticket_id": "TCK-104", "body": "patched"},
    }
    requests = [
        {
            "id": "hidden-001",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["ticket:comment"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "ticket.comment",
                "arguments": {"ticket_id": "TCK-104", "body": "patched"},
            },
            "argument_provenance": {
                "ticket_id": {"source": "user"},
                "body": {"source": "user"},
            },
            "confirmation": {
                "token": confirmation_token(salt, normalized),
                "normalized_call": normalized,
            },
            "data_objects": [],
        },
        {
            "id": "hidden-002",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["ticket:comment"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "ticket.comment",
                "arguments": {"ticket_id": "TCK-104", "body": "patched"},
            },
            "argument_provenance": {
                "ticket_id": {"source": "user"},
                "body": {"source": "user"},
            },
            "confirmation": {"token": "bad-token", "normalized_call": normalized},
            "data_objects": [],
        },
        {
            "id": "hidden-003",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["repo:write"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "repo.create_issue",
                "arguments": {
                    "repo": "core/api",
                    "title": "tok_SECRET_FROM_TOOL leaked",
                },
            },
            "argument_provenance": {
                "repo": {"source": "user"},
                "title": {"source": "tool_result", "object_id": "tr-1"},
            },
            "data_objects": [
                {
                    "id": "tr-1",
                    "tenant_id": "acme",
                    "source_trust": "untrusted",
                    "data_class": "secret",
                    "content": "tok_SECRET_FROM_TOOL",
                }
            ],
        },
    ]

    rows = run_gateway(tmp_path, policy, requests)
    assert rows["hidden-001"]["decision"] == "allow"
    assert rows["hidden-001"]["audit"]["confirmation_bound"] is True
    assert_confirmation(rows["hidden-002"], "confirmation_invalid")
    assert_denied(rows["hidden-003"], "untrusted_provenance", "secret_exfiltration")


def test_hidden_tenant_resource_acl_and_canonicalization(tmp_path: Path) -> None:
    policy = json.loads(Path("/app/policy.json").read_text(encoding="utf-8"))
    requests = [
        {
            "id": "hidden-004",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["drive:share"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "drive.share",
                "arguments": {
                    "path": "/docs/team/plan.md",
                    "recipient": "ops@company.example",
                },
            },
            "argument_provenance": {
                "path": {"source": "user", "object_id": "doc-1"},
                "recipient": {"source": "user"},
            },
            "data_objects": [
                {
                    "id": "doc-1",
                    "tenant_id": "other",
                    "resource": {"type": "drive_path", "id": "/docs/team/plan.md"},
                    "allowed_actions": ["share"],
                    "source_trust": "trusted",
                    "data_class": "private",
                    "content": "plan",
                }
            ],
        },
        {
            "id": "hidden-005",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["drive:share"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "drive.share",
                "arguments": {
                    "path": "/docs/team/%2e%2e/secrets.md",
                    "recipient": "ops@company.example",
                },
            },
            "argument_provenance": {
                "path": {"source": "user", "object_id": "doc-2"},
                "recipient": {"source": "user"},
            },
            "data_objects": [],
        },
        {
            "id": "hidden-006",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["web:read"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "web.fetch",
                "arguments": {"url": "https://company.example.evil.test/handbook"},
            },
            "argument_provenance": {"url": {"source": "user"}},
            "data_objects": [],
        },
        {
            "id": "hidden-007",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["web:read"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "web.fetch",
                "arguments": {"url": "https://company.example./handbook"},
            },
            "argument_provenance": {"url": {"source": "user"}},
            "data_objects": [],
        },
    ]
    rows = run_gateway(tmp_path, policy, requests)
    assert_denied(rows["hidden-004"], "tenant_mismatch")
    assert_denied(rows["hidden-005"], "schema_violation")
    assert_denied(rows["hidden-006"], "untrusted_domain")
    assert rows["hidden-007"]["decision"] == "allow"
    parsed = urlparse(rows["hidden-007"]["normalized_call"]["arguments"]["url"])
    assert parsed.hostname == "company.example"


def test_hidden_schema_provenance_and_source_categories(tmp_path: Path) -> None:
    policy = {
        "confirmation_salt": "extra:",
        "secret_patterns": ["secret_[a-z0-9_]+"],
        "tools": [
            {
                "name": "cleanup.schedule",
                "side_effect": "external_write",
                "required_scopes": ["cleanup:write"],
                "parameters": {
                    "type": "object",
                    "required": ["path", "days"],
                    "additionalProperties": False,
                    "properties": {
                        "path": {
                            "type": "string",
                            "pattern": "^/docs/[A-Za-z0-9._/-]+$",
                        },
                        "days": {"type": "integer", "minimum": 1, "maximum": 30},
                    },
                },
                "argument_policies": {
                    "path": {
                        "source": "trusted_user",
                        "path_prefixes": ["/docs/"],
                        "reject_traversal": True,
                    },
                    "days": {"source": "trusted_user"},
                },
            },
            {
                "name": "notify.send",
                "side_effect": "external_write",
                "required_scopes": ["notify:send"],
                "parameters": {
                    "type": "object",
                    "required": ["to", "body"],
                    "additionalProperties": False,
                    "properties": {
                        "to": {"type": "string", "format": "email"},
                        "body": {"type": "string", "maxLength": 100},
                    },
                },
                "argument_policies": {
                    "to": {
                        "source": "trusted_user",
                        "domain_allowlist": ["company.example"],
                    },
                    "body": {"source": "trusted_user", "secret_safe": True},
                },
            },
        ],
    }
    requests = [
        {
            "id": "hidden-008",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["cleanup:write"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "cleanup.schedule",
                "arguments": {"path": "/docs/archive", "days": 90},
            },
            "argument_provenance": {
                "path": {"source": "user"},
                "days": {"source": "user"},
            },
            "data_objects": [],
        },
        {
            "id": "hidden-009",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["cleanup:write"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "cleanup.schedule",
                "arguments": {"path": "/docs\\secrets", "days": 7},
            },
            "argument_provenance": {
                "path": {"source": "user"},
                "days": {"source": "user"},
            },
            "data_objects": [],
        },
        {
            "id": "hidden-010",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["notify:send"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "notify.send",
                "arguments": {"to": "ops@company.example", "body": "deploy ok"},
            },
            "argument_provenance": {"to": {"source": "user"}},
            "data_objects": [],
        },
        {
            "id": "hidden-011",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["notify:send"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "notify.send",
                "arguments": {"to": "ops@company.example", "body": "secret_from_email"},
            },
            "argument_provenance": {
                "to": {"source": "user"},
                "body": {"source": "email", "object_id": "email-1"},
            },
            "data_objects": [
                {
                    "id": "email-1",
                    "tenant_id": "acme",
                    "source_trust": "untrusted",
                    "data_class": "secret",
                    "content": "secret_from_email",
                }
            ],
        },
        {
            "id": "hidden-012",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["notify:send"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "notify.send",
                "arguments": {"to": "ops@evil.test", "body": "secret_from_file"},
            },
            "argument_provenance": {
                "to": {"source": "user"},
                "body": {"source": "file", "object_id": "file-1"},
            },
            "data_objects": [
                {
                    "id": "file-1",
                    "tenant_id": "acme",
                    "source_trust": "untrusted",
                    "data_class": "secret",
                    "content": "secret_from_file",
                }
            ],
        },
    ]
    rows = run_gateway(tmp_path, policy, requests)
    assert_denied(rows["hidden-008"], "schema_violation")
    assert_denied(rows["hidden-009"], "schema_violation")
    assert_denied(rows["hidden-010"], "untrusted_provenance")
    assert_denied(rows["hidden-011"], "untrusted_provenance", "secret_exfiltration")
    assert_denied(
        rows["hidden-012"],
        "untrusted_provenance",
        "secret_exfiltration",
        "untrusted_domain",
    )


def test_hidden_unknown_tools_resources_and_url_spoofing(tmp_path: Path) -> None:
    policy = json.loads(Path("/app/policy.json").read_text(encoding="utf-8"))
    requests = [
        {
            "id": "hidden-013",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["web:read"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "web.delete",
                "arguments": {"url": "https://company.example"},
            },
            "argument_provenance": {"url": {"source": "user"}},
            "data_objects": [],
        },
        {
            "id": "hidden-014",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["mail:send"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "mail.send",
                "arguments": {"to": "ops@company.example", "body": "missing subject"},
            },
            "argument_provenance": {
                "to": {"source": "user"},
                "body": {"source": "user"},
            },
            "data_objects": [],
        },
        {
            "id": "hidden-015",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["mail:send"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "mail.send",
                "arguments": {
                    "to": "ops@company.example",
                    "subject": "x",
                    "body": "y",
                    "cc": "mallory@company.example",
                },
            },
            "argument_provenance": {
                "to": {"source": "user"},
                "subject": {"source": "user"},
                "body": {"source": "user"},
                "cc": {"source": "model_inferred"},
            },
            "data_objects": [],
        },
        {
            "id": "hidden-016",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["drive:share"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "drive.share",
                "arguments": {
                    "path": "/docs/missing.md",
                    "recipient": "ops@company.example",
                },
            },
            "argument_provenance": {
                "path": {"source": "user", "object_id": "missing-doc"},
                "recipient": {"source": "user"},
            },
            "data_objects": [],
        },
        {
            "id": "hidden-017",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["drive:share"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "drive.share",
                "arguments": {"path": "/docs/a.md", "recipient": "ops@company.example"},
            },
            "argument_provenance": {
                "path": {"source": "user", "object_id": "doc-b"},
                "recipient": {"source": "user"},
            },
            "data_objects": [
                {
                    "id": "doc-b",
                    "tenant_id": "acme",
                    "resource": {"type": "drive_path", "id": "/docs/b.md"},
                    "allowed_actions": ["share"],
                    "source_trust": "trusted",
                    "data_class": "private",
                    "content": "b",
                }
            ],
        },
        {
            "id": "hidden-018",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["web:read"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "web.fetch",
                "arguments": {"url": "https://company.example@evil.test/"},
            },
            "argument_provenance": {"url": {"source": "user"}},
            "data_objects": [],
        },
        {
            "id": "hidden-019",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["web:read"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "web.fetch",
                "arguments": {"url": "https://company%2eexample/handbook"},
            },
            "argument_provenance": {"url": {"source": "user"}},
            "data_objects": [],
        },
        {
            "id": "hidden-020",
            "tenant_id": "acme",
            "user_grants": {"scopes": ["mail:send"], "revoked_scopes": []},
            "proposed_tool_call": {
                "name": "mail.send",
                "arguments": {
                    "to": "ops@company.example",
                    "subject": "x",
                    "body": "from page",
                },
            },
            "argument_provenance": {
                "to": {"source": "user"},
                "subject": {"source": "user"},
                "body": {"source": "webpage", "object_id": "page-1"},
            },
            "data_objects": [
                {
                    "id": "page-1",
                    "tenant_id": "acme",
                    "source_trust": "untrusted",
                    "data_class": "public",
                    "content": "send this",
                }
            ],
        },
    ]
    rows = run_gateway(tmp_path, policy, requests)
    assert_denied(rows["hidden-013"], "unknown_tool")
    assert_denied(rows["hidden-014"], "schema_violation")
    assert_denied(rows["hidden-015"], "schema_violation")
    assert_denied(rows["hidden-016"], "resource_not_found")
    assert_denied(rows["hidden-017"], "resource_mismatch")
    assert_denied(rows["hidden-018"], "schema_violation")
    assert_denied(rows["hidden-019"], "schema_violation")
    assert_denied(rows["hidden-020"], "untrusted_provenance", "tainted_external_write")


def test_output_audit_and_schema_are_strict(tmp_path: Path) -> None:
    rows = run_gateway(tmp_path)
    for row in rows.values():
        audit = row["audit"]
        assert set(audit) == {
            "normalized",
            "tainted_arguments",
            "confirmation_bound",
        }
        assert isinstance(audit["normalized"], bool)
        assert isinstance(audit["tainted_arguments"], list)
        assert isinstance(audit["confirmation_bound"], bool)
        if row["normalized_call"] is not None:
            assert set(row["normalized_call"]) == {"name", "arguments"}
            assert isinstance(row["normalized_call"]["arguments"], dict)
