from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = Path("/workspace/data/experiment/artifact/test-smoke")
REQUIRED_DATASET_FILES = (
    PROJECT_ROOT / "datasets" / "apps.json",
    PROJECT_ROOT / "datasets" / "human_eval_plus.json",
    PROJECT_ROOT / "datasets" / "defects4j.jsonl",
)
RQ1_FIGURE_OUTPUTS = (
    Path("full/figures/rq1/evaluation.rq1.table.tex"),
    Path("full/figures/rq1/evaluation.rq1.table.pdf"),
    Path("full/figures/rq1/evaluation.thresholds.pdf"),
)
RQ1_EXPECTO_MARKERS = (
    Path("full/runs/apps/ts/evaluation_result/manifest.json"),
    Path("full/runs/humaneval_plus/ts/evaluation_result/manifest.json"),
)
RQ1_NL2_MARKER_DIRS = (
    Path("full/runs/apps/nl2_base"),
    Path("full/runs/apps/nl2_simple"),
    Path("full/runs/humaneval_plus/nl2_base"),
    Path("full/runs/humaneval_plus/nl2_simple"),
)
RQ1_SAMPLE_RESULT_FILES = (
    Path("full/runs/apps/ts/sample_results.json"),
    Path("full/runs/apps/nl2_base/sample_results.json"),
    Path("full/runs/apps/nl2_simple/sample_results.json"),
    Path("full/runs/humaneval_plus/ts/sample_results.json"),
    Path("full/runs/humaneval_plus/nl2_base/sample_results.json"),
    Path("full/runs/humaneval_plus/nl2_simple/sample_results.json"),
)


def _print_status(ok: bool, label: str, detail: str | None = None) -> None:
    status = "PASS" if ok else "FAIL"
    if detail:
        click.echo(f"[{status}] {label}: {detail}")
        return
    click.echo(f"[{status}] {label}")


def _record_check(
    checks: list[tuple[str, bool]],
    issues: list[str],
    label: str,
    ok: bool,
    failure_reason: str | None = None,
) -> None:
    checks.append((label, ok))
    if not ok and failure_reason:
        issues.append(failure_reason)


def _print_summary(checks: list[tuple[str, bool]], issues: list[str]) -> None:
    click.echo("\nSummary:")
    for label, result in checks:
        _print_status(result, label)

    if issues:
        click.echo("\nProblems found:")
        for issue in issues:
            click.echo(f"- {issue}")


def _check_env_file() -> tuple[bool, Path]:
    env_path = PROJECT_ROOT / ".env"
    exists = env_path.exists()
    _print_status(exists, ".env file", str(env_path))
    return exists, env_path


def _check_openai_api_key(env_path: Path) -> bool:
    if not env_path.exists():
        _print_status(False, "OPENAI_API_KEY", "skipped because .env is missing")
        return False

    env_values = dotenv_values(env_path)
    raw_value = env_values.get("OPENAI_API_KEY")
    api_key = raw_value.strip() if isinstance(raw_value, str) else ""

    if raw_value is None:
        _print_status(False, "OPENAI_API_KEY", "OPENAI_API_KEY is missing from .env")
        return False

    if not api_key:
        _print_status(False, "OPENAI_API_KEY", "OPENAI_API_KEY is empty in .env")
        return False

    has_valid_prefix = api_key.startswith("sk-")
    detail = (
        "OPENAI_API_KEY is defined in .env and starts with 'sk-'"
        if has_valid_prefix
        else "OPENAI_API_KEY must start with 'sk-'"
    )
    _print_status(has_valid_prefix, "OPENAI_API_KEY", detail)
    return has_valid_prefix


def _check_datasets_dir() -> bool:
    datasets_dir = PROJECT_ROOT / "datasets"
    exists = datasets_dir.is_dir()
    _print_status(exists, "datasets directory", str(datasets_dir))
    return exists


def _check_dataset_files() -> bool:
    ok = True
    for dataset_path in REQUIRED_DATASET_FILES:
        exists = dataset_path.is_file()
        _print_status(exists, "dataset file", str(dataset_path.relative_to(PROJECT_ROOT)))
        ok = ok and exists
    return ok


def _run_rq1_smoke(output_root: Path) -> bool:
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_artifact.py"),
        "rq1",
        "--limit",
        "1",
        "--validation-limit",
        "1",
        "--expecto-n-completions",
        "1",
        "--expecto-max-attempts",
        "1",
        "--output-root",
        str(output_root),
        "--force",
    ]
    click.echo("Running RQ1 smoke test:")
    click.echo(" ".join(command))
    try:
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        _print_status(
            False,
            "RQ1 execution",
            f"run_artifact.py exited with code {exc.returncode}",
        )
        return False

    _print_status(True, "RQ1 execution", "run_artifact.py completed successfully")
    return True


def _check_expecto_markers(output_root: Path) -> bool:
    ok = True
    for relative_path in RQ1_EXPECTO_MARKERS:
        marker_path = output_root / relative_path
        exists = marker_path.is_file()
        _print_status(exists, "Expecto marker", str(marker_path))
        ok = ok and exists
    return ok


def _check_nl2_markers(output_root: Path) -> bool:
    ok = True
    for relative_dir in RQ1_NL2_MARKER_DIRS:
        run_dir = output_root / relative_dir
        matches = sorted(run_dir.rglob("aggregated_result.json")) if run_dir.exists() else []
        exists = bool(matches)
        detail = str(matches[0]) if exists else f"missing aggregated_result.json under {run_dir}"
        _print_status(exists, "NL2Postcond marker", detail)
        ok = ok and exists
    return ok


def _check_figure_outputs(output_root: Path) -> bool:
    ok = True
    for relative_path in RQ1_FIGURE_OUTPUTS:
        output_path = output_root / relative_path
        exists = output_path.is_file()
        _print_status(exists, "RQ1 figure output", str(output_path))
        ok = ok and exists
    return ok


def _check_sample_result_outputs(output_root: Path) -> bool:
    ok = True
    for relative_path in RQ1_SAMPLE_RESULT_FILES:
        output_path = output_root / relative_path
        exists = output_path.is_file()
        _print_status(exists, "sample result output", str(output_path))
        ok = ok and exists
    return ok


@click.command()
@click.option(
    "--output-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_OUTPUT_ROOT,
    show_default=True,
)
def main(output_root: Path) -> None:
    """Run environment checks and an RQ1 smoke test."""

    checks: list[tuple[str, bool]] = []
    issues: list[str] = []

    env_ok, env_path = _check_env_file()
    _record_check(
        checks,
        issues,
        ".env file",
        env_ok,
        f"Missing .env file at the project root: {env_path}",
    )

    key_ok = _check_openai_api_key(env_path)
    _record_check(
        checks,
        issues,
        "OPENAI_API_KEY",
        key_ok,
        "OPENAI_API_KEY is missing, empty, or does not start with 'sk-'.",
    )

    datasets_dir_ok = _check_datasets_dir()
    _record_check(
        checks,
        issues,
        "datasets directory",
        datasets_dir_ok,
        f"Missing datasets directory: {PROJECT_ROOT / 'datasets'}",
    )

    datasets_ok = _check_dataset_files()
    missing_datasets = [
        str(path.relative_to(PROJECT_ROOT))
        for path in REQUIRED_DATASET_FILES
        if not path.is_file()
    ]
    dataset_issue = None
    if missing_datasets:
        dataset_issue = "Missing required dataset files: " + ", ".join(missing_datasets)
    _record_check(checks, issues, "dataset files", datasets_ok, dataset_issue)

    preflight_ok = all(result for _, result in checks)
    if not preflight_ok:
        _print_summary(checks, issues)
        raise SystemExit(1)

    execution_ok = _run_rq1_smoke(output_root)
    _record_check(
        checks,
        issues,
        "RQ1 execution",
        execution_ok,
        "RQ1 execution failed. Check the run_artifact.py exit code and logs above.",
    )

    if execution_ok:
        expecto_ok = _check_expecto_markers(output_root)
        missing_expecto = [
            str(output_root / relative_path)
            for relative_path in RQ1_EXPECTO_MARKERS
            if not (output_root / relative_path).is_file()
        ]
        expecto_issue = None
        if missing_expecto:
            expecto_issue = "Missing Expecto result markers: " + ", ".join(missing_expecto)
        _record_check(
            checks,
            issues,
            "Expecto markers",
            expecto_ok,
            expecto_issue,
        )

        nl2_ok = _check_nl2_markers(output_root)
        missing_nl2 = [
            str(output_root / relative_dir)
            for relative_dir in RQ1_NL2_MARKER_DIRS
            if not any((output_root / relative_dir).rglob("aggregated_result.json"))
        ]
        nl2_issue = None
        if missing_nl2:
            nl2_issue = "Missing NL2Postcond result files: " + ", ".join(missing_nl2)
        _record_check(checks, issues, "NL2Postcond markers", nl2_ok, nl2_issue)

        figure_ok = _check_figure_outputs(output_root)
        missing_figures = [
            str(output_root / relative_path)
            for relative_path in RQ1_FIGURE_OUTPUTS
            if not (output_root / relative_path).is_file()
        ]
        figure_issue = None
        if missing_figures:
            figure_issue = "Missing RQ1 output files: " + ", ".join(missing_figures)
        _record_check(checks, issues, "RQ1 figure outputs", figure_ok, figure_issue)

        sample_results_ok = _check_sample_result_outputs(output_root)
        missing_sample_results = [
            str(output_root / relative_path)
            for relative_path in RQ1_SAMPLE_RESULT_FILES
            if not (output_root / relative_path).is_file()
        ]
        sample_results_issue = None
        if missing_sample_results:
            sample_results_issue = (
                "Missing sample result files: " + ", ".join(missing_sample_results)
            )
        _record_check(
            checks,
            issues,
            "sample result outputs",
            sample_results_ok,
            sample_results_issue,
        )

    overall_ok = all(result for _, result in checks)

    _print_summary(checks, issues)

    raise SystemExit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
