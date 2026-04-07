import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from time import gmtime, strftime, time
from typing import Optional

import click
from dotenv import load_dotenv
from inspect_ai import eval as eval_inspect_ai
from inspect_ai import eval_retry

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

import expecto.src.solvers as S
import expecto.src.tasks as T
from logger import get_logger

load_dotenv(project_root / ".env")
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))

COMPOSE_FILE = "expecto/docker/apps.compose.yaml"
DEFAULT_BASE_DIRS = {
    "humaneval_plus": str(WORKSPACE_DIR / "data" / "humaneval"),
    "apps_verified": str(WORKSPACE_DIR / "data" / "apps"),
    "defects4j": str(WORKSPACE_DIR / "data" / "defects4j"),
}

sys.set_int_max_str_digits(10000000)


def execute(args: list[str], logger: logging.Logger):
    logger.info(f"Running: {' '.join(args)}")
    try:
        subprocess.run(args, check=True, timeout=60 * 60 * 24 * 2)
        logger.info(f"✅ Successfully processed {' '.join(args)}")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Error processing {' '.join(args)}: {e}")


def allocate_experiment_dir(base_dir: str, exp_name: str) -> Path:
    base_path = Path(base_dir)
    candidate = base_path / exp_name
    suffix = 1

    while candidate.exists():
        candidate = base_path / f"{exp_name}_{suffix}"
        suffix += 1

    return candidate


@click.command()
@click.option("--task", type=str, help="The task to run")
@click.option("--solver", type=str, help="The solver to use")
@click.option("--debug", type=bool, default=False, is_flag=True, help="Debug mode")
@click.option("--model", type=str, help="The model to use")
@click.option("--temperature", type=float, default=0.0, help="The temperature to use")
@click.option("--epochs", type=int, default=1, help="The number of epochs to run")
@click.option("--exp_name", type=str, default="exp", help="The name of the experiment")
@click.option("--max_connections", type=int, default=64, help="The maximum number of connections to use")
@click.option("--max_subprocesses", type=int, default=64, help="The maximum number of subprocesses to use")
@click.option("--max_sandboxes", type=int, default=64, help="The maximum number of sandboxes to use")
@click.option("--n_completions", type=int, default=1, help="The number of completions to use")
@click.option("--max_attempts", type=int, default=5, help="The maximum number of attempts to use")
@click.option("--limit", type=int, default=None, help="The limit to use")
@click.option("--sample-ids", type=str, default=None, help="Comma-separated sample IDs to run.")
@click.option("--base_dir", type=str, default=None, help="The base directory to use")
@click.option("--dsl", type=bool, default=False, help="Whether to use DSL", is_flag=True)
@click.option("--threshold", type=float, default=0.5, help="The threshold to use for the merger")
@click.option("--use_test_cases", type=bool, default=False, help="Whether to use test cases", is_flag=True)
@click.option("--use_memo", type=bool, default=False, help="Whether to use memo", is_flag=True)
@click.option("--check_unsat/--no_check_unsat", default=True, help="Whether to check unsatisfiability when no test cases are available")
@click.option("--validation-sampling-mode", type=click.Choice(["all", "deterministic_cap"]), default="all", show_default=True, help="Validation test sampling mode.")
@click.option("--validation-positive-cap", type=click.IntRange(min=1), default=None, help="Maximum number of positive validation test cases.")
@click.option("--validation-negative-cap", type=click.IntRange(min=1), default=None, help="Maximum number of negative validation test cases.")
@click.option("--validation-sampling-seed", type=int, default=42, show_default=True, help="Base seed for deterministic validation sampling.")
def main(
    task: str,
    solver: str,
    epochs: int,
    debug: bool,
    model: str,
    temperature: float,
    exp_name: str,
    max_connections: int,
    max_subprocesses: int,
    max_sandboxes: int,
    n_completions: int,
    max_attempts: int,
    limit: Optional[int],
    sample_ids: Optional[str],
    base_dir: Optional[str],
    dsl: bool,
    threshold: float,
    use_test_cases: bool,
    use_memo: bool,
    check_unsat: bool,
    validation_sampling_mode: str,
    validation_positive_cap: Optional[int],
    validation_negative_cap: Optional[int],
    validation_sampling_seed: int,
):
    base_dir = base_dir or DEFAULT_BASE_DIRS.get(task, "inspect_logs")
    log_dir = allocate_experiment_dir(base_dir, exp_name)
    log_path = str(log_dir)
    os.makedirs(log_path, exist_ok=True)
    logger = get_logger(log_path)
    logger.info(
        textwrap.dedent(
            f"""
        task: {task}
        solver: {solver}
        epochs: {epochs}
        debug: {debug}
        model: {model}
        temperature: {temperature}
        n_completions: {n_completions}
        max_attempts: {max_attempts}
        threshold: {threshold}
        sample_ids: {sample_ids}
        use_test_cases: {use_test_cases}
        use_memo: {use_memo}
        check_unsat: {check_unsat}
        validation_sampling_mode: {validation_sampling_mode}
        validation_positive_cap: {validation_positive_cap}
        validation_negative_cap: {validation_negative_cap}
        validation_sampling_seed: {validation_sampling_seed}
        """
        )
    )
    cwd = Path(__file__).parent.parent
    logger.info(f"Current working directory: {cwd}")

    logger.info(f"Task name: {task}")

    if task not in T.task_map:
        logger.error(f"Task {task} not found")
        raise ValueError(f"Task {task} not found")

    task_obj = T.task_map[task]

    logger.info(f"Solver: {solver}")

    if solver not in S.solver_map:
        logger.error(f"Solver {solver} not found")
        raise ValueError(f"Solver {solver} not found")

    retry_count = 0

    model_prefix = model.split("/")[0]
    if model_prefix == "vllm":
        model_args = {
            "tensor_parallel_size": 4,
            "dtype": "half",
            "max_model_len": 10000,
            "trust_remote_code": True,
            "enforce_eager": True,
        }
    elif model_prefix == "openai":
        model_args = {}
    else:
        raise ValueError(f"Model {model} not supported")

    task_args = {
        "solver": solver,
        "n_completions": n_completions,
        "max_attempts": max_attempts,
        "threshold": threshold,
        "use_test_cases": use_test_cases,
        "use_memo": use_memo,
        "check_unsat": check_unsat,
        "validation_sampling_mode": validation_sampling_mode,
        "validation_positive_cap": validation_positive_cap,
        "validation_negative_cap": validation_negative_cap,
        "validation_sampling_seed": validation_sampling_seed,
    }
    begin_time = time()
    if debug:
        limit = 1
    if limit is not None:
        task_args["limit"] = limit
    if sample_ids:
        task_args["sample_ids"] = sample_ids
    kwargs = {}
    if "gpt-5" not in model:
        kwargs["temperature"] = temperature

    while retry_count < 3:
        if retry_count == 0:
            result = eval_inspect_ai(
                task_obj,
                model=model,
                epochs=epochs,
                task_args=task_args,
                model_args=model_args,
                sandbox_cleanup=True,
                display="rich",
                log_dir=log_path,
                max_connections=max_connections if model_prefix == "openai" else None,
                limit=limit,
                max_subprocesses=max_subprocesses,
                max_sandboxes=max_sandboxes,
                fail_on_error=False,
                retry_on_error=3,
                score=False,
                **kwargs,
            )[0]
        elif retry_count >= 1:
            result = eval_retry(
                tasks=result,
                sandbox_cleanup=True,
                display="rich",
                log_dir=log_path,
            )[0]
        if result.error:
            e = result.error
            logger.error(f"Error message: {e.message}")
            logger.error(f"Error Trace: {e.traceback}")
            retry_count += 1
        else:
            retry_count = 0
            break
    end_time = time()
    taken_time = end_time - begin_time
    hhmmss_format = strftime("%H:%M:%S", gmtime(taken_time))
    logger.info(f"Time taken: {hhmmss_format}")
    logger.info(f"Retry count: {retry_count}")
    logger.info(f"Result Status: {result.status}")

    result_path = result.location

    args = [
        "python3",
        "expecto/src/evaluation/main.py",
        "-l",
        result_path,
        "-s",
        str(Path(result_path).parent / "results.json"),
    ]
    execute(args, logger)

if __name__ == "__main__":
    main()  # type: ignore
