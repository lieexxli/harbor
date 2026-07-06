#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


PASS_STATUSES = {"pass", "passed", "success", "ok", "true"}
TIMEOUT_EXIT_CODE = 124


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SWE-bench Live verifier")
    parser.add_argument("--config", required=True)
    parser.add_argument("--log-dir", required=True)
    return parser.parse_args()


def run_command(command: str, cwd: Path, log_path: Path) -> tuple[int, str]:
    output_parts: list[str] = []
    with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
        log_file.write(f"\n$ {command}\n")
        log_file.flush()
        process = subprocess.Popen(
            command,
            cwd=cwd,
            shell=True,
            executable="/bin/bash",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            env=os.environ.copy(),
        )
        if process.stdout is None:
            raise RuntimeError("Failed to capture command output")
        for line in process.stdout:
            print(line, end="", flush=True)
            output_parts.append(line)
            log_file.write(line)
            log_file.flush()
        return_code = process.wait()
        log_file.write(f"\n[exit code: {return_code}]\n")
        return return_code, "".join(output_parts)


def git(repo_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def find_repo_dir(cfg: dict[str, Any]) -> Path:
    candidates = [Path("/testbed"), Path("/app")]
    repo = str(cfg.get("repo", ""))
    if repo:
        candidates.extend(
            [
                Path("/workspace") / repo.split("/")[-1],
                Path("/home") / repo.split("/")[-1],
            ]
        )
    for base in [Path("/workspace"), Path("/home")]:
        if base.exists():
            candidates.extend(path for path in base.iterdir() if path.is_dir())
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    raise FileNotFoundError("Could not find repository directory with a .git folder")


def write_agent_patch(repo_dir: Path, patch_path: Path) -> bool:
    result = git(repo_dir, "diff", "HEAD", "--text", check=False)
    patch_path.write_text(result.stdout, encoding="utf-8")
    return bool(result.stdout.strip())


def reset_repo(repo_dir: Path, base_commit: str) -> None:
    git(repo_dir, "reset", "--hard", base_commit)
    git(repo_dir, "clean", "-fd")


def apply_patch_best_effort(repo_dir: Path, patch_path: Path, label: str) -> str:
    patch_text = patch_path.read_text(encoding="utf-8", errors="replace")
    if not patch_text.strip():
        return "empty"

    attempts = [
        (["git", "apply", "-v", str(patch_path)], "applied"),
        (
            ["git", "apply", "--reverse", "--check", str(patch_path)],
            "already_applied",
        ),
        (["git", "apply", "--3way", "-v", str(patch_path)], "applied_3way"),
    ]
    outputs: list[str] = []
    for command, status in attempts:
        result = subprocess.run(
            command,
            cwd=repo_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        outputs.append(
            f"$ {' '.join(command)}\nexit={result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}\n"
        )
        if result.returncode == 0:
            return status

    raise RuntimeError(f"{label} does not apply cleanly:\n{''.join(outputs)}")


def load_parser(parser_path: Path):
    spec = importlib.util.spec_from_file_location(
        "swebench_live_log_parser", parser_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load parser from {parser_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = getattr(module, "parser", None)
    if parser is None:
        raise RuntimeError("log_parser.py does not define parser(log: str)")
    return parser


def parse_junit_xml(xml_path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    root = ET.fromstring(xml_path.read_text(encoding="utf-8", errors="replace"))
    for testcase in root.iter("testcase"):
        classname = testcase.get("classname", "")
        name = testcase.get("name", "")
        if not name:
            continue
        fullname = f"{classname}::{name}" if classname else name
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            status = "fail"
        elif testcase.find("skipped") is not None:
            status = "skip"
        else:
            status = "pass"
        result[fullname] = status
    return result


def default_pytest_parser(log: str) -> dict[str, str]:
    statuses = ("FAILED", "PASSED", "SKIPPED", "ERROR", "XFAIL")
    mapping: dict[str, str] = {}
    for line in log.splitlines():
        if not any(line.startswith(status) for status in statuses):
            continue
        if line.startswith("FAILED"):
            line = line.replace(" - ", " ")
        parts = line.split()
        if len(parts) <= 1:
            continue
        raw_status = parts[0].lower()
        if "pass" in raw_status:
            status = "pass"
        elif "skip" in raw_status:
            status = "skip"
        else:
            status = "fail"
        mapping[parts[1]] = status
    return mapping


def parse_with_junit_fallback(repo_dir: Path) -> dict[str, str]:
    xml_candidates = [
        repo_dir / "report.xml",
        repo_dir / "junit.xml",
        repo_dir / "test-results.xml",
    ]
    for xml_path in xml_candidates:
        if not xml_path.exists():
            continue
        parsed = parse_junit_xml(xml_path)
        if parsed:
            return parsed
    return {}


def parse_test_results(
    cfg: dict[str, Any], repo_dir: Path, raw_log_path: Path
) -> dict[str, Any]:
    log = raw_log_path.read_text(encoding="utf-8", errors="replace")
    parser_value = str(cfg.get("log_parser") or cfg.get("parser") or "").strip()
    if parser_value.lower() == "pytest":
        parsed = default_pytest_parser(log)
        if parsed:
            return parsed
        return parse_with_junit_fallback(repo_dir)

    parser = load_parser(Path("/tests/log_parser.py"))
    parsed = parser(log)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Parser returned {type(parsed).__name__}, expected dict")
    if parsed:
        return parsed

    fallback = parse_with_junit_fallback(repo_dir)
    if fallback:
        return fallback
    return parsed


def normalize_status(value: Any) -> str:
    if isinstance(value, bool):
        return "pass" if value else "fail"
    return str(value).strip().lower()


def evaluate(
    parsed: dict[str, Any], fail_to_pass: list[str], pass_to_pass: list[str]
) -> dict[str, Any]:
    statuses = {str(name): normalize_status(status) for name, status in parsed.items()}

    success = [name for name, status in statuses.items() if status in PASS_STATUSES]
    failure = [name for name, status in statuses.items() if "fail" in status]
    success_set = set(success)
    failure_set = set(failure)

    fail_to_pass_success = sorted(success_set & set(fail_to_pass))
    fail_to_pass_failure = sorted(failure_set & set(fail_to_pass))
    pass_to_pass_success = sorted(success_set & set(pass_to_pass))
    pass_to_pass_failure = sorted(failure_set & set(pass_to_pass))

    f2p = set(fail_to_pass).issubset(set(fail_to_pass_success)) or (
        len(fail_to_pass_success) == len(fail_to_pass)
    )
    resolved = not pass_to_pass_failure and not fail_to_pass_failure and f2p

    return {
        "resolved": resolved,
        "num_reported_tests": len(statuses),
        "PASS_TO_PASS": {
            "success": pass_to_pass_success,
            "failure": pass_to_pass_failure,
        },
        "FAIL_TO_PASS": {
            "success": fail_to_pass_success,
            "failure": fail_to_pass_failure,
        },
        "missing_fail_to_pass": sorted(set(fail_to_pass) - set(statuses)),
        "missing_pass_to_pass": sorted(set(pass_to_pass) - set(statuses)),
        "tests_status": statuses,
    }


def main() -> int:
    args = parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    reward_path = log_dir / "reward.txt"
    execution_log_path = log_dir / "execution.log"
    raw_log_path = log_dir / "post_patch_log.txt"
    report_path = log_dir / "report.json"

    exit_status = 1
    try:
        repo_dir = find_repo_dir(cfg)
        base_commit = str(cfg["base_commit"])
        patch_path = Path("/tests/test.patch")
        agent_patch_path = log_dir / "pred.patch"

        execution_log_path.write_text("", encoding="utf-8")
        raw_log_path.write_text("", encoding="utf-8")
        has_agent_patch = write_agent_patch(repo_dir, agent_patch_path)
        if not has_agent_patch:
            raise RuntimeError("Empty agent patch")

        reset_repo(repo_dir, base_commit)
        apply_patch_best_effort(repo_dir, patch_path, "test_patch")
        apply_patch_best_effort(repo_dir, agent_patch_path, "agent_patch")

        parser_log_parts: list[str] = []

        for command in cfg.get("rebuild_cmds") or []:
            run_command(str(command), repo_dir, execution_log_path)

        for command in cfg.get("test_cmds") or []:
            _, output = run_command(str(command), repo_dir, execution_log_path)
            parser_log_parts.append(output)

        print_outputs: list[str] = []
        for command in cfg.get("print_cmds") or []:
            _, output = run_command(str(command), repo_dir, execution_log_path)
            print_outputs.append(output)

        if print_outputs:
            raw_log_path.write_text("".join(print_outputs), encoding="utf-8")
        elif parser_log_parts:
            raw_log_path.write_text("".join(parser_log_parts), encoding="utf-8")
        parsed = parse_test_results(cfg, repo_dir, raw_log_path)

        report = evaluate(
            parsed,
            [str(item) for item in cfg.get("FAIL_TO_PASS", [])],
            [str(item) for item in cfg.get("PASS_TO_PASS", [])],
        )
        report["instance_id"] = cfg.get("instance_id")
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        exit_status = 0 if report["resolved"] else 1
        print("SWE-bench Live results starts here")
        print("PASSED" if report["resolved"] else "FAILED")
        print("SWE-bench Live results ends here")

    except Exception as exc:
        report_path.write_text(
            json.dumps({"resolved": False, "error": str(exc)}, indent=2),
            encoding="utf-8",
        )
        print(f"Verifier failed: {exc}", file=sys.stderr)
        exit_status = 1
    finally:
        reward_path.write_text("1\n" if exit_status == 0 else "0\n", encoding="utf-8")

    return exit_status


if __name__ == "__main__":
    sys.exit(main())
