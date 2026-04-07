import os
import subprocess
import sys
from pathlib import Path

import click
from run_nl2postcond import (
    log_command,
    log_ignored_nl2postcond_options,
    run_nl2postcond_for_task,
)

TASK = "apps"
EPOCHS = 1
FIXED_MODEL = "openai/gpt-4.1-mini"
FIXED_TEMPERATURE = 0.2
SOLVERS = ["monolithic", "tree_search", "nl2postcond"]
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
DEFAULT_BASE_DIR = str(WORKSPACE_DIR / "data" / "apps")


def run_apps_with_nl2postcond(
    exp_name: str,
    base_dir: str,
    limit: int | None,
    sample_ids: str | None,
    nl2_variant: str,
    validation_sampling_mode: str,
    validation_positive_cap: int | None,
    validation_negative_cap: int | None,
    validation_sampling_seed: int,
) -> None:
    run_nl2postcond_for_task(
        task=TASK,
        output_root=Path(base_dir) / exp_name / "nl-2-postcond",
        limit=limit,
        sample_ids=sample_ids,
        variant=nl2_variant,
        validation_sampling_mode=validation_sampling_mode,
        validation_positive_cap=validation_positive_cap,
        validation_negative_cap=validation_negative_cap,
        validation_sampling_seed=validation_sampling_seed,
    )


@click.command()
@click.option("--solver", type=click.Choice(SOLVERS), default="monolithic", help="Solver to use for code generation")
@click.option("--debug", is_flag=True, help="Run in debug mode")
@click.option("--exp-name", type=str, default="exp", help="The name of the experiment")
@click.option("--limit", type=int, default=None, help="The number of problems to run")
@click.option("--sample-ids", type=str, default=None, help="Comma-separated problem IDs to run.")
@click.option("--dev", is_flag=True, help="Run in dev mode")
@click.option("--n_completions", type=int, default=1, help="The number of completions to use")
@click.option("--max_attempts", type=int, default=5, help="The maximum number of attempts to use")
@click.option("--dsl", is_flag=True, help="Run in DSL mode")
@click.option("--base_dir", type=click.Path(file_okay=False), default=DEFAULT_BASE_DIR, help="The base directory to use")
@click.option("--threshold", type=float, default=0.5, help="The threshold to use for the merger")
@click.option("--use_test_cases", type=bool, default=False, help="Whether to use test cases", is_flag=True)
@click.option("--use_memo", type=bool, default=False, help="Whether to use memo", is_flag=True)
@click.option("--validation-sampling-mode", type=click.Choice(["all", "deterministic_cap"]), default="all", show_default=True, help="Validation test sampling mode.")
@click.option("--validation-positive-cap", type=click.IntRange(min=1), default=None, help="Maximum number of positive validation test cases.")
@click.option("--validation-negative-cap", type=click.IntRange(min=1), default=None, help="Maximum number of negative validation test cases.")
@click.option("--validation-sampling-seed", type=int, default=42, show_default=True, help="Base seed for deterministic validation sampling.")
@click.option("--nl2-variant", type=click.Choice(["all", "base", "simple"]), default="all", show_default=True, help="Which NL2Postcond variant to run when solver=nl2postcond.")
def run(
    solver,
    debug,
    exp_name,
    dev,
    limit,
    sample_ids,
    n_completions,
    max_attempts,
    dsl,
    base_dir,
    threshold,
    use_test_cases,
    use_memo,
    validation_sampling_mode,
    validation_positive_cap,
    validation_negative_cap,
    validation_sampling_seed,
    nl2_variant,
):
    """Run APPS benchmark with specified solver."""
    if limit is not None and sample_ids:
        raise click.ClickException("Use either --limit or --sample-ids, not both.")

    if solver == "nl2postcond":
        log_ignored_nl2postcond_options(
            debug=debug,
            dev=dev,
            n_completions=n_completions,
            max_attempts=max_attempts,
            dsl=dsl,
            threshold=threshold,
            use_test_cases=use_test_cases,
            use_memo=use_memo,
            check_unsat=True,
        )
        run_apps_with_nl2postcond(
            exp_name=exp_name,
            base_dir=base_dir,
            limit=limit,
            sample_ids=sample_ids,
            nl2_variant=nl2_variant,
            validation_sampling_mode=validation_sampling_mode,
            validation_positive_cap=validation_positive_cap,
            validation_negative_cap=validation_negative_cap,
            validation_sampling_seed=validation_sampling_seed,
        )
        return

    args = [
        "python3",
        "scripts/executor.py",
        "--base_dir",
        base_dir,
        "--task",
        str(TASK),
        "--solver",
        solver,
        "--model",
        FIXED_MODEL,
        "--temperature",
        str(FIXED_TEMPERATURE),
        "--epochs",
        str(EPOCHS),
        "--exp_name",
        exp_name,
        "--n_completions",
        str(n_completions),
        "--max_attempts",
        str(max_attempts),
        "--threshold",
        str(threshold),
        "--validation-sampling-mode",
        validation_sampling_mode,
        "--validation-sampling-seed",
        str(validation_sampling_seed),
    ]
    if debug:
        args.append("--debug")
    if dev:
        args.extend(["--max_connections", "16", "--max_subprocesses", "4", "--max_sandboxes", "4"])
    if limit:
        args.extend(["--limit", str(limit)])
    if sample_ids:
        args.extend(["--sample-ids", sample_ids])
    if dsl:
        args.append("--dsl")
    if use_test_cases:
        args.append("--use_test_cases")
    if use_memo:
        args.append("--use_memo")
    if validation_positive_cap is not None:
        args.extend(["--validation-positive-cap", str(validation_positive_cap)])
    if validation_negative_cap is not None:
        args.extend(["--validation-negative-cap", str(validation_negative_cap)])
    log_command(args)
    status = subprocess.run(args, stdout=sys.stdout, stderr=sys.stderr, cwd=os.getcwd())
    print(f"Return code: {status.returncode}")
    print("===========Done===========")


if __name__ == "__main__":
    run()
