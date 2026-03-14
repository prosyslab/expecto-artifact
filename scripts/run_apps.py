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
DEFAULT_BASE_DIR = "/workspace/data/apps"


def run_apps_with_nl2postcond(
    exp_name: str,
    base_dir: str,
    limit: int | None,
    sample_ids: str | None,
    nl2_variant: str,
) -> None:
    run_nl2postcond_for_task(
        task=TASK,
        output_root=Path(base_dir) / exp_name / "nl-2-postcond",
        limit=limit,
        sample_ids=sample_ids,
        variant=nl2_variant,
    )


@click.command()
@click.option(
    "--solver",
    type=click.Choice(SOLVERS),
    default="monolithic",
    help="Solver to use for code generation",
)
@click.option("--debug", is_flag=True, help="Run in debug mode")
@click.option("--exp-name", type=str, default="exp", help="The name of the experiment")
@click.option("--limit", type=int, default=None, help="The number of problems to run")
@click.option(
    "--sample-ids",
    type=str,
    default=None,
    help="Comma-separated problem IDs to run.",
)
@click.option("--dev", is_flag=True, help="Run in dev mode")
@click.option(
    "--n_completions",
    type=int,
    default=1,
    help="The number of completions to use",
)
@click.option(
    "--max_attempts",
    type=int,
    default=5,
    help="The maximum number of attempts to use",
)
@click.option("--dsl", is_flag=True, help="Run in DSL mode")
@click.option(
    "--base_dir",
    type=click.Path(file_okay=False),
    default=DEFAULT_BASE_DIR,
    help="The base directory to use",
)
@click.option(
    "--threshold",
    type=float,
    default=0.5,
    help="The threshold to use for the merger",
)
@click.option(
    "--use_test_cases",
    type=bool,
    default=False,
    help="Whether to use test cases",
    is_flag=True,
)
@click.option(
    "--use_memo",
    type=bool,
    default=False,
    help="Whether to use memo",
    is_flag=True,
)
@click.option(
    "--check_unsat/--no_check_unsat",
    default=True,
    help="Whether to check unsatisfiability when no test cases are available",
)
@click.option(
    "--nl2-variant",
    type=click.Choice(["all", "base", "simple"]),
    default="all",
    show_default=True,
    help="Which NL2Postcond variant to run when solver=nl2postcond.",
)
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
    check_unsat,
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
            check_unsat=check_unsat,
        )
        run_apps_with_nl2postcond(
            exp_name=exp_name,
            base_dir=base_dir,
            limit=limit,
            sample_ids=sample_ids,
            nl2_variant=nl2_variant,
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
    ]
    if debug:
        args.append("--debug")
    if dev:
        args.extend(
            [
                "--max_connections",
                "16",
                "--max_subprocesses",
                "4",
                "--max_sandboxes",
                "4",
            ]
        )
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
    if not check_unsat:
        args.append("--no_check_unsat")
    log_command(args)
    status = subprocess.run(args, stdout=sys.stdout, stderr=sys.stderr, cwd=os.getcwd())
    print(f"Return code: {status.returncode}")
    print("===========Done===========")


if __name__ == "__main__":
    run()
