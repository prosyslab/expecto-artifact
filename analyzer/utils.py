import asyncio
import sys
from pathlib import Path

from inspect_ai.log import EvalLog, read_eval_log_async
from tqdm import tqdm

# project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

from expecto.src.evaluation.models import (
    EvaluationResult,
    discover_evaluation_result_paths,
    load_evaluation_result,
)


def get_model_name_from_log(log: EvalLog | EvaluationResult) -> str:
    if isinstance(log, EvaluationResult):
        eval_spec = log.eval_spec
    else:
        eval_spec = log.eval
    model_name = eval_spec.model
    return model_name.split("/")[-1]


def get_solver_name_from_log(log: EvalLog | EvaluationResult) -> str:
    if isinstance(log, EvaluationResult):
        eval_spec = log.eval_spec
    else:
        eval_spec = log.eval
    solver_name = eval_spec.task_args.get("solver", "Unknown")
    return solver_name


def get_task_name_from_log(log: EvalLog | EvaluationResult) -> str:
    if isinstance(log, EvaluationResult):
        eval_spec = log.eval_spec
    else:
        eval_spec = log.eval
    task_name = eval_spec.task.replace("/", "_")
    task_opt = eval_spec.task_args
    if "level" in task_opt:
        return f"{task_name} (level {task_opt['level']})"
    return task_name


def get_level_from_log(log: EvalLog | EvaluationResult) -> str:
    if isinstance(log, EvaluationResult):
        eval_spec = log.eval_spec
    else:
        eval_spec = log.eval
    task_opt = eval_spec.task_args
    if "level" in task_opt:
        return task_opt["level"]
    return "Unknown"


def get_files_with_extension(path: Path, extension: str) -> list[Path]:
    """Get all files with specific extension from a path (file or directory)"""
    if path.is_file():
        return [path]
    else:
        return list(path.rglob(f"*.{extension}"))


async def read_logs(log_dir: Path) -> list[EvalLog]:
    log_paths = get_files_with_extension(log_dir, "eval")

    pbar = tqdm(total=len(log_paths), desc="Reading eval logs")

    async def read_eval_log_wrapper(log_file: Path) -> EvalLog:
        log = await read_eval_log_async(log_file, header_only=True)
        pbar.update(1)
        return log

    tasks = [read_eval_log_wrapper(log_file) for log_file in log_paths]
    logs = await asyncio.gather(*tasks)
    pbar.close()

    valid_logs = []
    for log_file, log in zip(log_paths, logs):
        model = log.eval.model
        results = log.results
        if results is None:
            continue
        if len(results.scores) == 0:
            continue
        print(f"{model} : {log_file}")
        print(results.scores[0].metrics["accuracy"].value)
        print("=" * 100)
        valid_logs.append(log)
    return valid_logs


async def read_score_logs(score_log_path: Path) -> list[EvaluationResult]:
    score_log_paths = discover_evaluation_result_paths(score_log_path)

    pbar = tqdm(total=len(score_log_paths), desc="Reading score logs")

    async def read_and_validate_score_log(file_path: Path) -> EvaluationResult | None:
        try:
            return await asyncio.to_thread(load_evaluation_result, file_path)
        except Exception:
            return None
        finally:
            pbar.update(1)

    tasks = [
        read_and_validate_score_log(score_log_path)
        for score_log_path in score_log_paths
    ]
    results = await asyncio.gather(*tasks)

    pbar.close()

    # Filter out None values (failed validations)
    score_logs = [result for result in results if result is not None]
    return score_logs
