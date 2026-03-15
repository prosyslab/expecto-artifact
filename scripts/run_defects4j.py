import os
import subprocess
import sys

import click

TASK = "defects4j"
EPOCHS = 1
FIXED_MODEL = "openai/gpt-4.1-mini"
DEFAULT_BASE_DIR = "/workspace/data/experiment/defects4j"


@click.command()
@click.option("--debug", is_flag=True, help="Run in debug mode")
@click.option("--exp-name", type=str, default="exp", help="The name of the experiment")
@click.option("--limit", type=int, default=None, help="The number of problems to run")
@click.option("--dev", is_flag=True, help="Run in dev mode")
@click.option("--n_completions", type=int, default=1, help="The number of completions to use")
@click.option("--max_attempts", type=int, default=5, help="The maximum number of attempts to use")
@click.option("--temperature", type=float, default=0.2, help="The temperature to use for the model")
@click.option("--dsl", is_flag=True, help="Run in DSL mode")
@click.option("--base_dir", type=click.Path(file_okay=False), default=DEFAULT_BASE_DIR, help="The base directory to use")
@click.option("--use_test_cases", type=bool, default=False, help="Whether to use test cases", is_flag=True)
@click.option("--validation-sampling-mode", type=click.Choice(["all", "deterministic_cap"]), default="all", show_default=True, help="Validation test sampling mode.")
@click.option("--validation-positive-cap", type=click.IntRange(min=1), default=None, help="Maximum number of positive validation test cases.")
@click.option("--validation-negative-cap", type=click.IntRange(min=1), default=None, help="Maximum number of negative validation test cases.")
@click.option("--validation-sampling-seed", type=int, default=42, show_default=True, help="Base seed for deterministic validation sampling.")
def run(
    debug,
    exp_name,
    dev,
    limit,
    n_completions,
    max_attempts,
    temperature,
    dsl,
    base_dir,
    use_test_cases,
    validation_sampling_mode,
    validation_positive_cap,
    validation_negative_cap,
    validation_sampling_seed,
):
    """Run Defects4J benchmark with specified solver."""
    args = [
        "python3",
        "scripts/executor.py",
        "--base_dir",
        base_dir,
        "--task",
        str(TASK),
        "--solver",
        "defects4j_tree_search",
        "--model",
        FIXED_MODEL,
        "--temperature",
        str(temperature),
        "--epochs",
        str(EPOCHS),
        "--exp_name",
        exp_name,
        "--n_completions",
        str(n_completions),
        "--max_attempts",
        str(max_attempts),
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
    if dsl:
        args.append("--dsl")
    if use_test_cases:
        args.append("--use_test_cases")
    if validation_positive_cap is not None:
        args.extend(["--validation-positive-cap", str(validation_positive_cap)])
    if validation_negative_cap is not None:
        args.extend(["--validation-negative-cap", str(validation_negative_cap)])
    print("===========Begin===========")
    print(" ".join(args))
    status = subprocess.run(args, stdout=sys.stdout, stderr=sys.stderr, cwd=os.getcwd())
    print(f"Return code: {status.returncode}")
    print("===========Done===========")


if __name__ == "__main__":
    run()
