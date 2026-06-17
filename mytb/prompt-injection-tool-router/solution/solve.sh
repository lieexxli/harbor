#!/bin/bash
cat > /app/gateway.py <<'PY'
import argparse
import hashlib
import json
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def load_jsonl(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl(path, rows):
    Path(path).write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


def make_result(rid, decision, normalized_call, violations, audit):
    return {
        "id": rid,
        "decision": decision,
        "normalized_call": normalized_call,
        "violations": sorted(set(violations)),
        "audit": audit,
    }


def tool_by_name(policy, name):
    return {tool["name"]: tool for tool in policy.get("tools", [])}.get(name)


def canonical_email(value):
    return str(value).strip().lower().rstrip(".,;:")


def canonical_url(value):
    raw = str(value).strip().rstrip(".,;)")
    if "\\" in raw or "\x00" in raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https" or parsed.username or parsed.password:
        return None
    if not parsed.hostname or "%" in parsed.hostname:
        return None
    host = parsed.hostname.lower().rstrip(".")
    path = unquote(parsed.path or "/")
    if path.startswith("//") or "/../" in path or path.endswith("/.."):
        return None
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    return urlunparse(("https", netloc, path or "/", "", parsed.query, ""))


def canonical_path(value):
    raw = unquote(str(value).strip().rstrip(".,;:"))
    if "\\" in raw or "\x00" in raw:
        return None
    if "/../" in raw or raw.endswith("/..") or raw.startswith("../"):
        return None
    norm = posixpath.normpath(raw)
    if not norm.startswith("/docs/"):
        return None
    return norm


def normalize_args(tool, args):
    schema = tool.get("parameters", {})
    required = set(schema.get("required", []))
    props = schema.get("properties", {})
    violations = []
    if set(args) != required:
        violations.append("schema_violation")
    normalized = {}
    for key in required:
        if key not in args:
            continue
        spec = props.get(key, {})
        value = args[key]
        policy = tool.get("argument_policies", {}).get(key, {})
        if spec.get("format") == "email":
            value = canonical_email(value)
        elif spec.get("format") == "uri" or policy.get("https_only"):
            value = canonical_url(value)
            if value is None:
                violations.append("schema_violation")
                continue
        elif policy.get("path_prefixes") or key == "path":
            value = canonical_path(value)
            if value is None:
                violations.append("schema_violation")
                continue
        normalized[key] = value
    return normalized, violations


def validate_schema(tool, args):
    schema = tool.get("parameters", {})
    props = schema.get("properties", {})
    violations = []
    if set(args) != set(schema.get("required", [])):
        violations.append("schema_violation")
        return violations
    for key, spec in props.items():
        value = args.get(key)
        if spec.get("type") == "string":
            if not isinstance(value, str):
                violations.append("schema_violation")
                continue
            if len(value) > spec.get("maxLength", len(value)):
                violations.append("schema_violation")
            if spec.get("format") == "email" and not EMAIL_RE.fullmatch(value):
                violations.append("schema_violation")
            if spec.get("format") == "uri":
                parsed = urlparse(value)
                if parsed.scheme != "https" or not parsed.hostname:
                    violations.append("schema_violation")
            if "pattern" in spec and not re.fullmatch(spec["pattern"], value):
                violations.append("schema_violation")
        if spec.get("type") == "integer":
            if not isinstance(value, int):
                violations.append("schema_violation")
                continue
            if value < spec.get("minimum", value) or value > spec.get("maximum", value):
                violations.append("schema_violation")
    return violations


def effective_scopes(req):
    grants = req.get("user_grants", {})
    return set(grants.get("scopes", [])) - set(grants.get("revoked_scopes", []))


def data_object_map(req):
    return {obj.get("id"): obj for obj in req.get("data_objects", [])}


def compile_secret_patterns(policy):
    patterns = []
    for pat in policy.get("secret_patterns", []):
        try:
            patterns.append(re.compile(pat))
        except re.error:
            pass
    return patterns


def object_is_tainted(obj, patterns):
    if not obj:
        return False
    if obj.get("source_trust") != "trusted":
        return True
    if obj.get("data_class") == "secret":
        return True
    content = str(obj.get("content", ""))
    return any(p.search(content) for p in patterns)


def check_policies(policy, tool, req, normalized_call):
    violations = []
    tainted = []
    args = normalized_call["arguments"]
    provenance = req.get("argument_provenance", {})
    objects = data_object_map(req)
    patterns = compile_secret_patterns(policy)
    for key, arg_policy in tool.get("argument_policies", {}).items():
        value = args.get(key)
        prov = provenance.get(key, {})
        source = prov.get("source")
        obj = objects.get(prov.get("object_id"))
        if arg_policy.get("source") == "trusted_user" and source != "user":
            violations.append("untrusted_provenance")
            tainted.append(key)
        if obj and object_is_tainted(obj, patterns):
            tainted.append(key)
        if arg_policy.get("secret_safe"):
            if any(p.search(str(value)) for p in patterns):
                violations.append("secret_exfiltration")
                tainted.append(key)
            if obj and object_is_tainted(obj, patterns):
                violations.append("secret_exfiltration")
        domains = arg_policy.get("domain_allowlist", [])
        if domains and value is not None:
            if key in {"to", "recipient"}:
                domain = str(value).split("@")[-1].lower()
                if domain not in {d.lower() for d in domains}:
                    violations.append("untrusted_domain")
            if key == "url":
                host = (urlparse(str(value)).hostname or "").lower().rstrip(".")
                if host not in {d.lower().rstrip(".") for d in domains}:
                    violations.append("untrusted_domain")
        prefixes = arg_policy.get("path_prefixes", [])
        if prefixes and value is not None and not any(str(value).startswith(p) for p in prefixes):
            violations.append("schema_violation")
        if arg_policy.get("resource_ref"):
            if not obj:
                violations.append("resource_not_found")
            else:
                if obj.get("tenant_id") != req.get("tenant_id"):
                    violations.append("tenant_mismatch")
                action = tool.get("resource_action")
                if action and action not in obj.get("allowed_actions", []):
                    violations.append("resource_action_denied")
                resource = obj.get("resource", {})
                if resource.get("id") != value:
                    violations.append("resource_mismatch")
    if tool.get("side_effect") == "external_write" and tainted:
        violations.append("tainted_external_write")
    return violations, sorted(set(tainted))


def confirmation_status(policy, tool, req, normalized_call):
    if not tool.get("requires_confirmation"):
        return None, False
    confirmation = req.get("confirmation") or {}
    expected = hashlib.sha256(
        (policy.get("confirmation_salt", "") + canonical_json(normalized_call)).encode()
    ).hexdigest()
    if confirmation.get("token") == expected and confirmation.get("normalized_call") == normalized_call:
        return None, True
    if confirmation:
        return "confirmation_invalid", False
    return "confirmation_required", False


def authorize(policy, req):
    rid = req.get("id")
    call = req.get("proposed_tool_call", {})
    tool = tool_by_name(policy, call.get("name"))
    audit = {"normalized": False, "tainted_arguments": [], "confirmation_bound": False}
    if not tool:
        return make_result(rid, "deny", None, ["unknown_tool"], audit)
    normalized_args, violations = normalize_args(tool, call.get("arguments", {}))
    normalized_call = {"name": tool["name"], "arguments": normalized_args}
    if "schema_violation" not in violations:
        violations.extend(validate_schema(tool, normalized_args))
    if not set(tool.get("required_scopes", [])).issubset(effective_scopes(req)):
        violations.append("missing_scope")
    policy_violations, tainted = check_policies(policy, tool, req, normalized_call)
    violations.extend(policy_violations)
    audit = {"normalized": not violations or normalized_args != {}, "tainted_arguments": tainted, "confirmation_bound": False}
    if "schema_violation" in violations:
        return make_result(rid, "deny", None, violations, audit)
    conf_violation, bound = confirmation_status(policy, tool, req, normalized_call)
    audit["confirmation_bound"] = bound
    if conf_violation:
        violations.append(conf_violation)
        if set(violations) == {conf_violation}:
            return make_result(rid, "needs_confirmation", normalized_call, violations, audit)
    if violations:
        return make_result(rid, "deny", normalized_call, violations, audit)
    return make_result(rid, "allow", normalized_call, [], audit)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default="/app/policy.json")
    parser.add_argument("--requests", default="/app/requests.jsonl")
    parser.add_argument("--output", default="/app/decisions.jsonl")
    args = parser.parse_args()
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    rows = [authorize(policy, req) for req in load_jsonl(args.requests)]
    write_jsonl(args.output, rows)


if __name__ == "__main__":
    main()
PY
