import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from harbor.cli.utils import run_async

console = Console()

_OUTCOME_STYLES = {
    "pass": "green",
    "fail": "red",
    "not_applicable": "grey50",
}


def _outcome_str(check) -> tuple[str, str]:
    """Extract (outcome, explanation) strings from a check, handling enums and dicts."""
    if isinstance(check, dict):
        return str(check.get("outcome", "")), str(check.get("explanation", ""))
    outcome = check.outcome
    outcome_s = outcome.value if hasattr(outcome, "value") else str(outcome)
    return outcome_s, str(check.explanation)


def _render_checks_table(title: str, checks: dict, summary: str | None = None):
    """Render a Rich table for rubric check results."""
    table = Table(title=title, show_lines=True)
    table.add_column("Check")
    table.add_column("Outcome")
    table.add_column("Explanation")

    for name, check in checks.items():
        outcome, explanation = _outcome_str(check)
        table.add_row(
            name.replace("_", " ").title(),
            outcome,
            explanation,
            style=_OUTCOME_STYLES.get(outcome, "white"),
        )

    if summary:
        console.print(f"\n[bold]Summary:[/bold] {summary}\n")
    console.print(table)


def _is_trial_dir(path: Path) -> bool:
    return (path / "trial.log").exists()


def _is_job_dir(path: Path) -> bool:
    return (path / "job.log").exists()


CHECK_RESULT_FILENAME = "check_result.json"


def _collect_task_dirs(path: Path) -> list[Path]:
    """Return task dirs: the path itself if valid, otherwise its valid subdirs."""
    from harbor.models.task.task import Task

    if not path.exists():
        raise FileNotFoundError(f"Path '{path}' does not exist")
    if Task.is_valid_dir(path):
        return [path]
    subdirs = sorted(p for p in path.iterdir() if p.is_dir() and Task.is_valid_dir(p))
    return subdirs


def check_command(
    task_dir: Path = typer.Argument(..., help="Path to task or dataset directory"),
    rubric: Path | None = typer.Option(
        None,
        "-r",
        "--rubric",
        help="Rubric file defining evaluation criteria (TOML/YAML/JSON). Uses built-in default if not specified.",
    ),
    prompt: Path | None = typer.Option(
        None,
        "-p",
        "--prompt",
        help="Prompt file with instructions for the evaluator agent. Uses built-in default if not specified.",
    ),
    model: str = typer.Option("sonnet", "-m", "--model", help="Model to use"),
    sdk: str = typer.Option(
        "claude",
        "--sdk",
        help="SDK backend to use: 'claude' (default) or 'codex'",
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show agent trace"),
    output: Path | None = typer.Option(
        None, "-o", "--output", help="Write JSON output to file (single task only)"
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Re-check even if check_result.json already exists"
    ),
    n_concurrent: int = typer.Option(
        5, "-n", "--n-concurrent", help="Max concurrent checks (batch mode only)"
    ),
    include: list[str] = typer.Option(
        [], "-i", "--include", help="Only check these task names (repeatable)"
    ),
    clear: bool = typer.Option(
        False, "--clear", help=f"Delete all {CHECK_RESULT_FILENAME} files and exit"
    ),
):
    """Check task quality against a rubric. Accepts a single task or a dataset directory."""
    from harbor.analyze.checker import run_check

    task_dir = Path(task_dir)

    if clear:
        removed = 0
        for f in task_dir.rglob(CHECK_RESULT_FILENAME):
            f.unlink()
            console.print(f"[yellow]Removed {f}[/yellow]")
            removed += 1
        console.print(f"[green]✓ Removed {removed} file(s)[/green]")
        return

    task_dirs = _collect_task_dirs(task_dir)
    if include:
        task_dirs = [td for td in task_dirs if td.name in include]
        missing = set(include) - {td.name for td in task_dirs}
        for name in missing:
            console.print(f"[yellow]Warning: task '{name}' not found[/yellow]")
    if not task_dirs:
        console.print(
            f"[red]❌ '{task_dir}' is not a valid task directory and contains no task subdirectories.[/red]"
        )
        raise typer.Exit(1)

    batch = len(task_dirs) > 1
    single_output = output if not batch else None
    aggregated: dict[str, object] = {}

    async def _check_one(td: Path) -> None:
        per_task_path = td / CHECK_RESULT_FILENAME
        out_path: Path = single_output if single_output is not None else per_task_path

        if not overwrite and out_path.exists():
            console.print(f"[grey50]Skipping {td.name} (already checked)[/grey50]")
            return

        console.print(f"[blue]🔎 Checking {td.name}...[/blue]")
        try:
            result = await run_check(
                task_dir=td,
                model=model,
                rubric_path=rubric,
                prompt_path=prompt,
                verbose=verbose,
                sdk=sdk,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            console.print(f"[red]❌ {td.name}: {e}[/red]")
            if not batch:
                raise
            return

        out_path.write_text(json.dumps(result.model_dump(), indent=2))
        console.print(f"[green]✓ {td.name} → {out_path}[/green]")

        if result.estimated_cost_usd is not None:
            console.print(f"[grey50]  cost: ${result.estimated_cost_usd:.4f}[/grey50]")

        if batch:
            aggregated[td.name] = result.model_dump()

        _render_checks_table(f"Task Quality Checks — {td.name}", result.checks)

    async def _run_all() -> None:
        semaphore = asyncio.Semaphore(n_concurrent)

        async def _guarded(td: Path) -> None:
            async with semaphore:
                await _check_one(td)

        async with asyncio.TaskGroup() as tg:
            for td in task_dirs:
                tg.create_task(_guarded(td))

    try:
        run_async(_run_all())
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        console.print(f"[red]❌ {e}[/red]")
        raise typer.Exit(1)

    if batch and output and aggregated:
        output.write_text(json.dumps(aggregated, indent=2))
        console.print(f"[green]✓ Aggregated results written to {output}[/green]")


def analyze_command(
    path: Path = typer.Argument(..., help="Path to trial or job directory"),
    prompt: Path | None = typer.Option(
        None,
        "-p",
        "--prompt",
        help="Prompt file with instructions for the evaluator agent. Uses built-in default if not specified.",
    ),
    rubric: Path | None = typer.Option(
        None,
        "-r",
        "--rubric",
        help="Rubric file defining evaluation criteria (TOML/YAML/JSON). Uses built-in default (reward_hacking, task_specification) if not specified.",
    ),
    job_prompt: Path | None = typer.Option(
        None,
        "--job-prompt",
        help="Prompt file for job-level aggregation (summarizing all trials). Uses built-in default if not specified.",
    ),
    model: str = typer.Option("haiku", "-m", "--model", help="Model to use"),
    sdk: str = typer.Option(
        "claude",
        "--sdk",
        help="SDK backend to use: 'claude' (default) or 'codex'",
    ),
    n_concurrent: int = typer.Option(
        5,
        "-n",
        "--n-concurrent",
        help="Max concurrent analyses (for job dirs)",
    ),
    passing: bool = typer.Option(
        False, "--passing", help="Only analyze passing trials (reward=1.0)"
    ),
    failing: bool = typer.Option(
        False, "--failing", help="Only analyze failing trials (reward<1.0 or exception)"
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Re-analyze trials even if analysis.json already exists",
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show agent trace"),
    output: Path | None = typer.Option(
        None, "-o", "--output", help="Write JSON output to file"
    ),
):
    """Analyze trial trajectories (summarize + rubric evaluation)."""
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    from harbor.analyze.analyzer import Analyzer
    from harbor.analyze.models import JobAnalyzeResult

    if passing and failing:
        console.print("[red]❌ Cannot use both --passing and --failing[/red]")
        raise typer.Exit(1)

    path = Path(path)
    if not path.exists():
        console.print(f"[red]❌ Path '{path}' does not exist[/red]")
        raise typer.Exit(1)

    console.print("\n[blue]🔍 Analyzing trial(s)...[/blue]")

    analyzer = Analyzer(
        model=model,
        prompt_path=prompt,
        rubric_path=rubric,
        job_prompt_path=job_prompt,
        n_concurrent=n_concurrent,
        verbose=verbose,
        sdk=sdk,
    )

    try:
        if _is_job_dir(path):
            filter_passing: bool | None = (
                True if passing else (False if failing else None)
            )

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
            ) as progress:
                task_id = progress.add_task("Analyzing trials...", total=None)

                def _set_total(total: int) -> None:
                    progress.update(task_id, total=total)

                def _advance(_result: object = None) -> None:
                    progress.advance(task_id)

                async def _run_job():
                    return await analyzer.analyze_job(
                        path,
                        filter_passing=filter_passing,
                        overwrite=overwrite,
                        on_total=_set_total,
                        on_trial_complete=_advance,
                    )

                result, failed_trials = run_async(_run_job())

            if failed_trials:
                console.print(
                    f"[yellow]Warning: {len(failed_trials)} trial(s) failed analysis:[/yellow]"
                )
                for msg in failed_trials:
                    console.print(f"  [yellow]{msg}[/yellow]")

        elif _is_trial_dir(path):
            if passing or failing:
                from harbor.models.trial.result import TrialResult

                try:
                    tr = TrialResult.model_validate_json(
                        (path / "result.json").read_text()
                    )
                    has_reward_one = (
                        tr.verifier_result
                        and tr.verifier_result.rewards
                        and tr.verifier_result.rewards.get("reward", 0) == 1.0
                    )
                    is_passing = has_reward_one and tr.exception_info is None
                except Exception:
                    is_passing = False

                if passing and not is_passing:
                    console.print(
                        f"[red]❌ Trial '{path.name}' is not a passing trial (--passing filter)[/red]"
                    )
                    raise typer.Exit(1)
                if failing and is_passing:
                    console.print(
                        f"[red]❌ Trial '{path.name}' is not a failing trial (--failing filter)[/red]"
                    )
                    raise typer.Exit(1)

            result = run_async(analyzer.analyze_trial(path, overwrite=overwrite))
        else:
            console.print(
                f"[red]❌ '{path}' is not a trial directory (no trial.log) or job directory "
                f"(no job.log). "
                f"For task quality checks, use 'harbor check <task-dir>' instead.[/red]"
            )
            raise typer.Exit(1)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        console.print(f"[red]❌ {e}[/red]")
        raise typer.Exit(1)

    if output:
        output.write_text(json.dumps(result.model_dump(), indent=2))
        console.print(f"[green]✓ Results written to {output}[/green]")

    if isinstance(result, JobAnalyzeResult):
        console.print(f"\n[bold]Job Summary:[/bold]\n{result.job_summary}")
        for trial in result.trials:
            _render_checks_table(
                f"Trial: {trial.trial_name}",
                trial.checks,
                summary=trial.summary,
            )
    else:
        _render_checks_table(
            f"Trial: {result.trial_name}",
            result.checks,
            summary=result.summary,
        )
