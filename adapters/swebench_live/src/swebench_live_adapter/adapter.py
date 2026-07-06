from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any, Callable, Iterable

import pandas as pd


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    return path.read_text(encoding="utf-8")


def write_text_lf(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def render_literal(template_text: str, **repls: str) -> str:
    out = template_text
    for key, value in repls.items():
        out = out.replace("{" + key + "}", value)
    return out


def normalize_for_json(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return normalize_for_json(value.tolist())
    if isinstance(value, dict):
        return {str(k): normalize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize_for_json(v) for v in value]
    if pd.isna(value):
        return None
    return value


@dataclass
class SWEBenchLiveRecord:
    source_dataset: str
    repo: str
    pull_number: str
    instance_id: str
    issue_numbers: list[str]
    base_commit: str
    patch: str
    test_patch: str
    problem_statement: str
    hints_text: str
    all_hints_text: str
    commit_urls: list[str]
    created_at: str
    commit_url: str
    rebuild_cmds: list[str]
    test_cmds: list[str]
    print_cmds: list[str]
    log_parser: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    docker_image: str
    difficulty: str
    patch_stats: dict[str, Any]
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "SWEBenchLiveRecord":
        normalized = normalize_for_json(row)
        return cls(
            source_dataset=str(normalized["source_dataset"]),
            repo=str(normalized["repo"]),
            pull_number=str(normalized["pull_number"]),
            instance_id=str(normalized["instance_id"]),
            issue_numbers=list(normalized.get("issue_numbers") or []),
            base_commit=str(normalized["base_commit"]),
            patch=str(normalized["patch"]),
            test_patch=str(normalized["test_patch"]),
            problem_statement=str(normalized["problem_statement"]),
            hints_text=str(normalized.get("hints_text") or ""),
            all_hints_text=str(normalized.get("all_hints_text") or ""),
            commit_urls=list(normalized.get("commit_urls") or []),
            created_at=str(normalized.get("created_at") or ""),
            commit_url=str(normalized.get("commit_url") or ""),
            rebuild_cmds=list(normalized.get("rebuild_cmds") or []),
            test_cmds=list(normalized.get("test_cmds") or []),
            print_cmds=list(normalized.get("print_cmds") or []),
            log_parser=str(normalized["log_parser"]),
            fail_to_pass=list(normalized.get("FAIL_TO_PASS") or []),
            pass_to_pass=list(normalized.get("PASS_TO_PASS") or []),
            docker_image=str(normalized["docker_image"]),
            difficulty=str(normalized.get("difficulty") or "medium"),
            patch_stats=dict(normalized.get("patch_stats") or {}),
            raw=normalized,
        )


@dataclass(frozen=True)
class HarborResourceConfig:
    agent_timeout_sec: float
    verifier_timeout_sec: float
    build_timeout_sec: float
    cpus: int
    memory_mb: int
    storage_mb: int
    gpus: int


class SWEBenchLiveLoader:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        if self.data_dir.is_file():
            parquet_files = [self.data_dir]
        else:
            parquet_files = sorted(self.data_dir.glob("*.parquet"))
        if not parquet_files:
            raise FileNotFoundError(f"No parquet files found under {self.data_dir}")

        frames = [pd.read_parquet(path) for path in parquet_files]
        df = pd.concat(frames, ignore_index=True)
        self._by_id = {
            str(row["instance_id"]): normalize_for_json(row)
            for row in df.to_dict(orient="records")
        }

    def all_ids(self) -> list[str]:
        return list(self._by_id.keys())

    def load(self, instance_id: str) -> SWEBenchLiveRecord:
        if instance_id not in self._by_id:
            raise KeyError(f"Instance not found: {instance_id}")
        return SWEBenchLiveRecord.from_dict(self._by_id[instance_id])


class HarborTaskPaths:
    def __init__(self, task_dir: Path) -> None:
        self.task_dir = task_dir
        self.environment_dir = task_dir / "environment"
        self.tests_dir = task_dir / "tests"
        self.solution_dir = task_dir / "solution"

        self.environment_dir.mkdir(parents=True, exist_ok=True)
        self.tests_dir.mkdir(parents=True, exist_ok=True)
        self.solution_dir.mkdir(parents=True, exist_ok=True)

        self.instruction_path = task_dir / "instruction.md"
        self.config_path = task_dir / "task.toml"
        self.dockerfile_path = self.environment_dir / "Dockerfile"
        self.test_sh_path = self.tests_dir / "test.sh"
        self.run_tests_path = self.tests_dir / "run_tests.py"
        self.config_json_path = self.tests_dir / "config.json"
        self.test_patch_path = self.tests_dir / "test.patch"
        self.log_parser_path = self.tests_dir / "log_parser.py"
        self.solve_sh_path = self.solution_dir / "solve.sh"
        self.solution_diff_path = self.solution_dir / "solution.diff"


class SWEBenchLiveAdapter:
    def __init__(
        self,
        output_dir: Path,
        data_dir: Path,
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        instance_id: str | None = None,
        local_task_id: str | None = None,
        all_tasks: bool = True,
        max_timeout_sec: float | None = None,
        template_dir: Path | None = None,
        **kwargs: object,
    ) -> None:
        self.out_root = Path(output_dir)
        self.out_root.mkdir(parents=True, exist_ok=True)
        self.limit = limit
        self.overwrite = overwrite
        self.task_ids = task_ids
        self.instance_id = instance_id
        self.local_task_id = local_task_id
        self.all_tasks = all_tasks
        self.max_timeout = float(max_timeout_sec) if max_timeout_sec else None
        self.template_dir = Path(
            template_dir or (Path(__file__).parent / "task-template")
        )

        self.t_instruction = self.template_dir / "instruction.md"
        self.t_config = self.template_dir / "task.toml"
        self.t_dockerfile = self.template_dir / "environment" / "Dockerfile"
        self.t_test_sh = self.template_dir / "tests" / "test.sh"
        self.t_run_tests = self.template_dir / "tests" / "run_tests.py"
        self.t_solve = self.template_dir / "solution" / "solve.sh"

        self.loader = SWEBenchLiveLoader(Path(data_dir))

    @staticmethod
    def make_local_task_id(instance_id: str) -> str:
        return instance_id

    def get_all_ids(self) -> list[str]:
        return sorted(self.loader.all_ids())

    def _resource_config(self, rec: SWEBenchLiveRecord) -> HarborResourceConfig:
        verifier_difficulty_timeouts = {
            "easy": 900.0,
            "medium": 1800.0,
            "hard": 3600.0,
        }
        agent_difficulty_timeouts = {
            "easy": 1200.0,
            "medium": 1800.0,
            "hard": 3600.0,
        }
        difficulty = rec.difficulty.lower()
        agent_timeout = agent_difficulty_timeouts.get(difficulty, 1800.0)
        verifier_timeout = verifier_difficulty_timeouts.get(difficulty, 1800.0)

        transition_count = len(rec.fail_to_pass) + len(rec.pass_to_pass)
        if transition_count > 1000:
            verifier_timeout = max(verifier_timeout, 1800.0)
        if transition_count > 5000:
            verifier_timeout = max(verifier_timeout, 3600.0)
        if transition_count > 10000:
            verifier_timeout = max(verifier_timeout, 7200.0)

        command_text = " ".join(
            rec.rebuild_cmds + rec.test_cmds + rec.print_cmds
        ).lower()
        if any(token in command_text for token in ("pytest tests", "pytest -q tests")):
            verifier_timeout = max(verifier_timeout, 1800.0)
        if any(
            token in command_text
            for token in (
                "pyright",
                "mypy",
                "npm",
                "pnpm",
                "yarn",
                "playwright",
                "make test",
                "tox",
            )
        ):
            verifier_timeout = max(verifier_timeout, 2400.0)

        memory_mb = 2048
        if transition_count > 1000:
            memory_mb = 4096
        if transition_count > 5000:
            memory_mb = 8192
        if any(
            token in f"{rec.repo} {command_text}".lower()
            for token in (
                "opencompass",
                "pyright",
                "statsmodels",
                "marimo",
                "pandas",
                "torch",
                "cfn-lint",
                "sqlmesh",
            )
        ):
            memory_mb = max(memory_mb, 4096)

        cpus = 1
        if transition_count > 3000 or any(
            token in f"{rec.repo} {command_text}".lower()
            for token in ("pyright", "statsmodels", "opencompass", "marimo")
        ):
            cpus = 2
        if transition_count > 12000:
            cpus = 4

        if self.max_timeout is not None:
            agent_timeout = self.max_timeout
            verifier_timeout = self.max_timeout

        return HarborResourceConfig(
            agent_timeout_sec=agent_timeout,
            verifier_timeout_sec=verifier_timeout,
            build_timeout_sec=600.0,
            cpus=cpus,
            memory_mb=memory_mb,
            storage_mb=10240,
            gpus=0,
        )

    def generate_task(
        self, instance_id: str, local_task_id: str, *, overwrite: bool = False
    ) -> Path:
        rec = self.loader.load(instance_id)
        resources = self._resource_config(rec)
        task_dir = self.out_root / local_task_id
        if task_dir.exists():
            if not overwrite:
                raise FileExistsError(f"Target already exists: {task_dir}")
            shutil.rmtree(task_dir)

        paths = HarborTaskPaths(task_dir)

        instruction = render_literal(
            read_text(self.t_instruction),
            problem_statement=dedent(rec.problem_statement).strip(),
            repo=rec.repo,
            base_commit=rec.base_commit,
            instance_id=rec.instance_id,
        )
        write_text_lf(paths.instruction_path, instruction.rstrip() + "\n")

        task_toml = render_literal(
            read_text(self.t_config),
            instance_id=rec.instance_id,
            difficulty=rec.difficulty,
            agent_timeout=f"{resources.agent_timeout_sec:.1f}",
            verifier_timeout=f"{resources.verifier_timeout_sec:.1f}",
            build_timeout=f"{resources.build_timeout_sec:.1f}",
            cpus=str(resources.cpus),
            memory_mb=str(resources.memory_mb),
            storage_mb=str(resources.storage_mb),
            gpus=str(resources.gpus),
            source_dataset=rec.source_dataset,
            repo=rec.repo,
        )
        write_text_lf(paths.config_path, task_toml)

        dockerfile = render_literal(
            read_text(self.t_dockerfile),
            docker_image=rec.docker_image,
        )
        write_text_lf(paths.dockerfile_path, dockerfile)

        config = dict(rec.raw)
        config["FAIL_TO_PASS"] = rec.fail_to_pass
        config["PASS_TO_PASS"] = rec.pass_to_pass
        config["parser"] = rec.log_parser
        config.pop("log_parser", None)
        config.pop("test_patch", None)
        config.pop("patch", None)
        write_text_lf(
            paths.config_json_path,
            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        )
        write_text_lf(paths.test_patch_path, rec.test_patch)
        write_text_lf(paths.log_parser_path, rec.log_parser.rstrip() + "\n")

        write_text_lf(paths.test_sh_path, read_text(self.t_test_sh))
        paths.test_sh_path.chmod(0o755)
        write_text_lf(paths.run_tests_path, read_text(self.t_run_tests))
        paths.run_tests_path.chmod(0o755)

        write_text_lf(paths.solution_diff_path, rec.patch)
        write_text_lf(paths.solve_sh_path, read_text(self.t_solve))
        paths.solve_sh_path.chmod(0o755)

        return paths.task_dir

    def generate_many(
        self,
        instance_ids: Iterable[str],
        *,
        name_fn: Callable[[str], str] | None = None,
        overwrite: bool = False,
    ) -> tuple[list[Path], list[tuple[str, str]]]:
        success: list[Path] = []
        failures: list[tuple[str, str]] = []
        ids = list(instance_ids)
        for idx, instance_id in enumerate(ids, 1):
            local_name = name_fn(instance_id) if name_fn else instance_id
            try:
                out = self.generate_task(instance_id, local_name, overwrite=overwrite)
                print(f"[{idx}/{len(ids)}] OK   {instance_id} -> {out}")
                success.append(out)
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                print(f"[{idx}/{len(ids)}] FAIL {instance_id}: {msg}")
                failures.append((instance_id, msg))
        return success, failures

    def run(self) -> None:
        if self.instance_id is not None:
            out = self.generate_task(
                self.instance_id,
                self.local_task_id or self.make_local_task_id(self.instance_id),
                overwrite=self.overwrite,
            )
            print(f"Harbor task created at: {out}")
            return

        if self.task_ids is not None:
            instance_ids = list(self.task_ids)
        elif self.all_tasks:
            instance_ids = self.get_all_ids()
        else:
            raise ValueError(
                "You used --no-all but did not provide --instance-id or --task-ids."
            )

        if self.limit is not None:
            instance_ids = instance_ids[: self.limit]

        print(f"Converting {len(instance_ids)} instances into {self.out_root} ...")
        ok, bad = self.generate_many(
            instance_ids,
            name_fn=self.make_local_task_id,
            overwrite=self.overwrite,
        )
        print(f"Done. Success: {len(ok)}  Failures: {len(bad)}")
        if bad:
            print("Failures:")
            for instance_id, reason in bad:
                print(f"  - {instance_id}: {reason}")
