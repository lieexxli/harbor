import json
import subprocess
import sys
from pathlib import Path

import pytest
import tiktoken

TRIMMER = Path("/app/trim.py")


def _count_tokens(messages: list[dict]) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    total = 3
    for m in messages:
        total += 3
        total += len(enc.encode(m["role"]))
        total += len(enc.encode(m["content"]))
    return total


@pytest.fixture(scope="module")
def trimmed():
    return json.loads(Path("/app/trimmed.json").read_text())


@pytest.fixture(scope="module")
def stats():
    return json.loads(Path("/app/stats.json").read_text())


@pytest.fixture(scope="module")
def original():
    return json.loads(Path("/app/messages.json").read_text())


@pytest.fixture(scope="module")
def budget():
    return json.loads(Path("/app/budget.json").read_text())["max_tokens"]


def test_output_files_exist():
    assert TRIMMER.exists(), "/app/trim.py not found"
    assert Path("/app/trimmed.json").exists(), "trimmed.json not found"
    assert Path("/app/stats.json").exists(), "stats.json not found"


def test_trimmed_is_valid_json_array(trimmed):
    assert isinstance(trimmed, list), "trimmed.json must be a JSON array"
    for m in trimmed:
        assert "role" in m and "content" in m, "each message must have role and content"


def test_fits_within_budget(trimmed, budget):
    actual = _count_tokens(trimmed)
    assert actual <= budget, (
        f"trimmed conversation has {actual} tokens, exceeds budget of {budget}"
    )


def test_system_message_preserved(trimmed, original):
    system_msgs = [m for m in original if m["role"] == "system"]
    if not system_msgs:
        return
    assert trimmed[0]["role"] == "system", (
        "system message must be first in trimmed output"
    )
    assert trimmed[0]["content"] == system_msgs[0]["content"], (
        "system message content must not be modified"
    )


def test_messages_are_suffix_of_original(trimmed, original):
    """Kept messages must be a contiguous suffix of the original (after system)."""
    trimmed_non_system = [m for m in trimmed if m["role"] != "system"]
    original_non_system = [m for m in original if m["role"] != "system"]
    assert (
        trimmed_non_system
        == original_non_system[len(original_non_system) - len(trimmed_non_system) :]
    ), "kept messages must be a contiguous suffix of the original non-system messages"


def test_maximum_messages_kept(trimmed, original, budget):
    """No additional message could have been kept without exceeding the budget."""
    system_msgs = [m for m in original if m["role"] == "system"]
    trimmed_non_system = [m for m in trimmed if m["role"] != "system"]
    original_non_system = [m for m in original if m["role"] != "system"]
    removed_count = len(original_non_system) - len(trimmed_non_system)
    if removed_count > 0:
        one_more = (
            system_msgs + [original_non_system[removed_count - 1]] + trimmed_non_system
        )
        assert _count_tokens(one_more) > budget, (
            "an additional message could have been kept — trimming removed more than necessary"
        )


def test_stats_original_tokens(stats, original):
    expected = _count_tokens(original)
    assert stats["original_tokens"] == expected, (
        f"original_tokens should be {expected}, got {stats['original_tokens']}"
    )


def test_stats_trimmed_tokens(stats, trimmed):
    expected = _count_tokens(trimmed)
    assert stats["trimmed_tokens"] == expected, (
        f"trimmed_tokens should be {expected}, got {stats['trimmed_tokens']}"
    )


def test_stats_messages_removed(stats, original, trimmed):
    expected = len(original) - len(trimmed)
    assert stats["messages_removed"] == expected, (
        f"messages_removed should be {expected}, got {stats['messages_removed']}"
    )


def test_already_fits_case_is_unchanged(tmp_path):
    messages = [
        {"role": "system", "content": "Keep this system prompt."},
        {"role": "user", "content": "Short question."},
        {"role": "assistant", "content": "Short answer."},
    ]
    budget = {"max_tokens": _count_tokens(messages) + 10}

    messages_path = tmp_path / "messages.json"
    budget_path = tmp_path / "budget.json"
    output_path = tmp_path / "trimmed.json"
    stats_path = tmp_path / "stats.json"

    messages_path.write_text(json.dumps(messages), encoding="utf-8")
    budget_path.write_text(json.dumps(budget), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(TRIMMER),
            "--messages",
            str(messages_path),
            "--budget",
            str(budget_path),
            "--output",
            str(output_path),
            "--stats",
            str(stats_path),
        ],
        check=True,
        timeout=20,
    )

    trimmed = json.loads(output_path.read_text(encoding="utf-8"))
    stats = json.loads(stats_path.read_text(encoding="utf-8"))

    assert trimmed == messages, "already-fitting conversations must be unchanged"
    assert stats == {
        "original_tokens": _count_tokens(messages),
        "trimmed_tokens": _count_tokens(messages),
        "messages_removed": 0,
    }
