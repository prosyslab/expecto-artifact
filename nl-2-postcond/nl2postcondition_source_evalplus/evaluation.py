import asyncio
import contextlib
import json
import os
import subprocess
import sys
import tempfile
from textwrap import indent
from pathlib import Path
from typing import List, Optional

import click
from models import (
    AggregatedResult,
    EvaluationResult,
)
from tqdm.asyncio import tqdm as atqdm

from dataset_paths import get_evalplus_dataset_file

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from validation_sampling import sample_io_pairs_payload, VALIDATION_SAMPLING_MODES

PPX_SAMPLE_JSONL = "preprocessed_samples.jsonl"
EVAL_TIMEOUT_SECONDS = 30

if hasattr(sys, "set_int_max_str_digits"):
    # EvalPlus fixtures can contain very large integers inside JSON payloads.
    sys.set_int_max_str_digits(0)


def get_worker_count() -> int:
    cpu_count = os.cpu_count() or 1
    return max(1, int(cpu_count * 0.8))


def sanitize_task_id(task_id: str) -> str:
    return task_id.replace("/", "__")


def get_log_path(
    target_directory: str,
    task_id: str,
    response_num: int,
    phase: str,
    stream_name: str,
) -> str:
    log_dir = os.path.join(target_directory, "evaluation_logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(
        log_dir,
        f"{sanitize_task_id(task_id)}__sample_{response_num}__{phase}.{stream_name}.log",
    )


def load_dataset(dataset: str) -> dict:
    with open(dataset, "r") as f:
        d = json.load(f)
    return {str(d["problem_id"]): d for d in d}


def read_target_directory(target_directory: str) -> list[dict]:
    assert os.path.exists(os.path.join(target_directory, PPX_SAMPLE_JSONL)), (
        f"File {os.path.join(target_directory, PPX_SAMPLE_JSONL)} does not exist"
    )
    # Lazy import to avoid hard dependency at module import time
    import jsonlines  # type: ignore

    with jsonlines.open(os.path.join(target_directory, PPX_SAMPLE_JSONL)) as reader:
        return list(reader)


def get_eval_code_with_parser(assertion: str, signature: str, args, parser: str) -> str:
    signature = signature.split("\n")[0]
    assertion = assertion.replace("return_value", "result").replace("assert", "return")
    eval_code = f"""from typing import *
import math
import re
{parser}
{signature}
{indent(assertion, " " * 4)}

true_cnt = 0
false_cnt = 0
"""
    io_pairs = json.loads(args)
    for i, o in zip(io_pairs["inputs"], io_pairs["outputs"]):
        eval_code += "try:\n"
        eval_code += f"    v = postcondition(*parser({repr(i)}, {repr(o)}))\n"
        eval_code += "    if v == True:\n        true_cnt += 1\n    else:\n        false_cnt += 1\n"
        eval_code += "except Exception:\n    false_cnt += 1\n"
    eval_code += "print(f'{true_cnt} {false_cnt}', flush=True)\n"
    return eval_code


def get_eval_code_with_io_pairs(assertion: str, signature: str, io_pairs: str) -> str:
    io_pairs_dict = json.loads(io_pairs)
    signature = signature.split("\n")[0]
    assertion = assertion.replace("return_value", "result").replace("assert", "return")
    eval_code = f"""from typing import *
import math
import re
{signature}
{indent(assertion, " " * 4)}

true_cnt = 0
false_cnt = 0
"""
    for i, o in zip(io_pairs_dict["inputs"], io_pairs_dict["outputs"]):
        input_args_str = ", ".join(repr(arg) for arg in i)
        eval_code += "try:\n"
        eval_code += f"    v = postcondition({input_args_str}, {repr(o)})\n"
        eval_code += "    if v == True:\n        true_cnt += 1\n    else:\n        false_cnt += 1\n"
        eval_code += "except Exception:\n    false_cnt += 1\n"
    eval_code += "print(f'{true_cnt} {false_cnt}', flush=True)\n"
    return eval_code


def get_eval_code(assertion: str, signature: str, args, parser: Optional[str]) -> str:
    assertion = assertion.replace("return_value", "result").replace("assert", "return")
    if parser is not None:
        return get_eval_code_with_parser(assertion, signature, args, parser)
    else:
        return get_eval_code_with_io_pairs(assertion, signature, args)


def write_log(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as log_file:
        log_file.write(content)


def normalize_output(content: bytes | str | None) -> str:
    if content is None:
        return ""
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return content


def run_code_sync(
    code: str, num_of_tc: int, stdout_log_path: str, stderr_log_path: str
) -> tuple[int, int, str]:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as tmp:
        tmp.write(code)
        tmp.flush()
        tmp_path = tmp.name

    try:
        try:
            completed = subprocess.run(
                ["python3", tmp_path],
                capture_output=True,
                text=True,
                timeout=EVAL_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            write_log(stdout_log_path, normalize_output(exc.stdout))
            write_log(stderr_log_path, normalize_output(exc.stderr) + "Timeout\n")
            return 0, num_of_tc, f"Timeout. See logs: {stdout_log_path}, {stderr_log_path}"

        write_log(stdout_log_path, completed.stdout)
        if completed.stderr:
            write_log(stderr_log_path, completed.stderr)
        elif os.path.exists(stderr_log_path):
            os.unlink(stderr_log_path)

        if completed.returncode != 0:
            return (
                0,
                num_of_tc,
                "Process exited with code "
                f"{completed.returncode}. See logs: {stdout_log_path}, {stderr_log_path}",
            )

        stdout_str = completed.stdout.strip()
        if not stdout_str:
            return 0, num_of_tc, f"No stdout. See logs: {stdout_log_path}, {stderr_log_path}"

        processed = stdout_str.split()
        if len(processed) != 2:
            return (
                0,
                num_of_tc,
                f"Invalid stdout format: {stdout_str}. See logs: {stdout_log_path}, {stderr_log_path}",
            )

        return int(processed[0]), int(processed[1]), "Success"
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)


async def run_code(
    code: str, num_of_tc: int, stdout_log_path: str, stderr_log_path: str
) -> tuple[int, int, str]:
    return await asyncio.to_thread(
        run_code_sync, code, num_of_tc, stdout_log_path, stderr_log_path
    )


def get_total(io_pairs) -> int:
    if isinstance(io_pairs, list):
        return len(io_pairs)
    else:
        return len(json.loads(io_pairs)["inputs"])


def resolve_benchmark_name(dataset_path: str) -> str:
    dataset_name = Path(dataset_path).name.lower()
    if "human" in dataset_name or "eval" in dataset_name:
        return "humaneval_plus"
    return "apps"


def sample_problem_io_pairs(
    problem: dict,
    *,
    benchmark: str,
    problem_id: str,
    validation_sampling_mode: str,
    validation_positive_cap: int | None,
    validation_negative_cap: int | None,
    validation_sampling_seed: int,
) -> tuple[str | dict | None, str | dict | None]:
    return (
        sample_io_pairs_payload(
            problem.get("input_output"),
            benchmark=benchmark,
            sample_id=problem_id,
            phase="positive",
            mode=validation_sampling_mode,
            cap=validation_positive_cap,
            base_seed=validation_sampling_seed,
        ),
        sample_io_pairs_payload(
            problem.get("mutated_input_output"),
            benchmark=benchmark,
            sample_id=problem_id,
            phase="negative",
            mode=validation_sampling_mode,
            cap=validation_negative_cap,
            base_seed=validation_sampling_seed,
        ),
    )


async def evaluate_one_assertion(
    data: dict,
    evalplus_data: dict,
    target_directory: str,
    benchmark: str,
    validation_sampling_mode: str,
    validation_positive_cap: int | None,
    validation_negative_cap: int | None,
    validation_sampling_seed: int,
) -> EvaluationResult:
    assertion = data["postcondition_alone"]
    task_id = data["task_id"]
    response_num = data.get("response_num", 0)
    problem_idx = data["task_id"].split("/")[-1]
    problem = evalplus_data[problem_idx]
    positive_io_pairs, negative_io_pairs = sample_problem_io_pairs(
        problem,
        benchmark=benchmark,
        problem_id=problem_idx,
        validation_sampling_mode=validation_sampling_mode,
        validation_positive_cap=validation_positive_cap,
        validation_negative_cap=validation_negative_cap,
        validation_sampling_seed=validation_sampling_seed,
    )

    # Check completeness
    eval_code = get_eval_code(
        assertion, problem["signature"], positive_io_pairs, problem["parser"]
    )
    complete_total = get_total(positive_io_pairs)
    if complete_total == 0:
        complete_total = 1
    complete_stdout_log_path = get_log_path(
        target_directory, task_id, response_num, "completeness", "stdout"
    )
    complete_stderr_log_path = get_log_path(
        target_directory, task_id, response_num, "completeness", "stderr"
    )
    (
        true_cnt_correct,
        false_cnt_correct,
        msg_completeness,
    ) = await run_code(
        eval_code,
        complete_total,
        complete_stdout_log_path,
        complete_stderr_log_path,
    )

    # Check soundness
    eval_code = get_eval_code(
        assertion,
        problem["signature"],
        negative_io_pairs,
        problem["parser"],
    )
    sound_total = get_total(negative_io_pairs)
    if sound_total == 0:
        sound_total = 1
    soundness_stdout_log_path = get_log_path(
        target_directory, task_id, response_num, "soundness", "stdout"
    )
    soundness_stderr_log_path = get_log_path(
        target_directory, task_id, response_num, "soundness", "stderr"
    )
    (
        true_cnt_mutated,
        false_cnt_mutated,
        msg_soundness,
    ) = await run_code(
        eval_code,
        sound_total,
        soundness_stdout_log_path,
        soundness_stderr_log_path,
    )

    return EvaluationResult(
        task_id=data["task_id"],
        assertion=assertion,
        is_complete=(false_cnt_correct == 0 and true_cnt_correct > 0),
        is_sound=false_cnt_mutated > true_cnt_mutated,
        complete_ratio=true_cnt_correct / complete_total,
        sound_ratio=false_cnt_mutated / sound_total,
        true_cnt_correct=true_cnt_correct,
        false_cnt_correct=false_cnt_correct,
        true_cnt_mutated=true_cnt_mutated,
        false_cnt_mutated=false_cnt_mutated,
        msg_completeness=msg_completeness,
        msg_soundness=msg_soundness,
    )


async def evaluate_one_assertion_with_semaphore(
    data: dict,
    evalplus_data: dict,
    target_directory: str,
    semaphore: asyncio.Semaphore,
    benchmark: str,
    validation_sampling_mode: str,
    validation_positive_cap: int | None,
    validation_negative_cap: int | None,
    validation_sampling_seed: int,
) -> EvaluationResult:
    async with semaphore:
        return await evaluate_one_assertion(
            data,
            evalplus_data,
            target_directory,
            benchmark,
            validation_sampling_mode,
            validation_positive_cap,
            validation_negative_cap,
            validation_sampling_seed,
        )


def aggregate_results(
    results: List[EvaluationResult], exp_name: str
) -> AggregatedResult:
    completeness_ratio = sum(result.is_complete for result in results) / len(results)
    soundness_ratio = sum(result.is_sound for result in results) / len(results)
    average_complete_ratio = sum(result.complete_ratio for result in results) / len(
        results
    )
    average_sound_ratio = sum(result.sound_ratio for result in results) / len(results)
    sound_and_complete = sum(
        result.is_complete and result.is_sound for result in results
    )
    complete_only = sum(
        result.is_complete and not result.is_sound for result in results
    )
    sound_only = sum(not result.is_complete and result.is_sound for result in results)
    failed = sum(not result.is_complete and not result.is_sound for result in results)
    return AggregatedResult(
        exp_name=exp_name,
        sound_and_complete=sound_and_complete,
        complete_only=complete_only,
        sound_only=sound_only,
        failed=failed,
        completeness_ratio=completeness_ratio,
        soundness_ratio=soundness_ratio,
        average_complete_ratio=average_complete_ratio,
        average_sound_ratio=average_sound_ratio,
    )


async def evaluate_target_directory(
    target_directory: str,
    dataset: str,
    worker_count: int,
    validation_sampling_mode: str,
    validation_positive_cap: int | None,
    validation_negative_cap: int | None,
    validation_sampling_seed: int,
) -> List[EvaluationResult]:
    data = read_target_directory(target_directory)
    evalplus_data = load_dataset(dataset)
    benchmark = resolve_benchmark_name(dataset)
    semaphore = asyncio.Semaphore(worker_count)
    tasks = [
        evaluate_one_assertion_with_semaphore(
            d,
            evalplus_data,
            target_directory,
            semaphore,
            benchmark,
            validation_sampling_mode,
            validation_positive_cap,
            validation_negative_cap,
            validation_sampling_seed,
        )
        for d in data
    ]
    return await atqdm.gather(*tasks)


@click.command()
@click.argument("target_directory", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--dataset",
    type=click.Path(exists=True),
    default=str(get_evalplus_dataset_file()),
    show_default=True,
)
@click.option("--exp_name", type=str, required=True)
@click.option(
    "--workers",
    type=click.IntRange(min=1),
    default=None,
    help="Maximum number of concurrent assertion evaluations.",
)
@click.option(
    "--validation-sampling-mode",
    type=click.Choice(VALIDATION_SAMPLING_MODES),
    default="all",
    show_default=True,
    help="Validation test sampling mode.",
)
@click.option(
    "--validation-positive-cap",
    type=click.IntRange(min=1),
    default=None,
    help="Maximum number of positive validation test cases.",
)
@click.option(
    "--validation-negative-cap",
    type=click.IntRange(min=1),
    default=None,
    help="Maximum number of negative validation test cases.",
)
@click.option(
    "--validation-sampling-seed",
    type=int,
    default=42,
    show_default=True,
    help="Base seed for deterministic validation sampling.",
)
def main(
    target_directory: str,
    dataset: str,
    exp_name: str,
    workers: Optional[int],
    validation_sampling_mode: str,
    validation_positive_cap: int | None,
    validation_negative_cap: int | None,
    validation_sampling_seed: int,
):
    worker_count = workers or get_worker_count()
    print(f"Running evaluation with {worker_count} workers")
    results = asyncio.run(
        evaluate_target_directory(
            target_directory,
            dataset,
            worker_count,
            validation_sampling_mode,
            validation_positive_cap,
            validation_negative_cap,
            validation_sampling_seed,
        )
    )
    with open(os.path.join(target_directory, "evaluation_results.json"), "w") as f:
        json.dump([result.model_dump() for result in results], f, indent=4)
    with open(os.path.join(target_directory, "aggregated_result.json"), "w") as f:
        agg_result = aggregate_results(results, exp_name)
        json.dump(agg_result.model_dump(), f, indent=4)
    print(agg_result)


if __name__ == "__main__":
    main()  # type: ignore[misc]
