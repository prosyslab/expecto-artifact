import json
import os
import random
import sys
from logging import getLogger
from pathlib import Path
from typing import Any

from inspect_ai import Epochs, Task, task
from inspect_ai.dataset import MemoryDataset, Sample, json_dataset

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

logger = getLogger(__name__)

import src.solvers as S
from src.evaluation.sandbox import initialize
from src.tasks.dataset_paths import get_dataset_path

HUMAN_EVAL_PLUS_VERIFY_TIMEOUT = 60 * 60 * 3  # 3 Hours


def parse_sample_ids(sample_ids: str | None) -> list[str]:
    if not sample_ids:
        return []

    ordered_ids: list[str] = []
    seen: set[str] = set()
    for raw_id in sample_ids.split(","):
        sample_id = raw_id.strip()
        if not sample_id or sample_id in seen:
            continue
        ordered_ids.append(sample_id)
        seen.add(sample_id)
    return ordered_ids


def filter_dataset_by_sample_ids(dataset, sample_ids: str | None):
    ordered_ids = parse_sample_ids(sample_ids)
    if not ordered_ids:
        return dataset

    sample_by_id = {str(sample.id): sample for sample in dataset}
    missing_ids = [
        sample_id for sample_id in ordered_ids if sample_id not in sample_by_id
    ]
    if missing_ids:
        logger.warning("Unknown HumanEval+ sample IDs requested: %s", missing_ids)

    filtered_samples = [
        sample_by_id[sample_id]
        for sample_id in ordered_ids
        if sample_id in sample_by_id
    ]
    logger.info("Filtered HumanEval+ dataset to %d sample(s)", len(filtered_samples))
    return MemoryDataset(filtered_samples)


@task(name="humaneval_plus")
def humaneval_plus(
    solver: str = "monolithic",
    epochs: int = 1,
    max_attempts: int = 5,
    n_completions: int = 1,
    threshold: float = 0.5,
    use_test_cases: bool = True,
    use_memo: bool = True,
    check_unsat: bool = True,
    sample_ids: str | None = None,
    *args,
    **kwargs,
) -> Task:
    initialize()
    s = S.solver_map[solver]
    solver_obj = s(
        max_attempts=max_attempts,
        n_completions=n_completions,
        threshold=threshold,
        use_test_cases=use_test_cases,
        use_memo=use_memo,
        check_unsat=check_unsat,
    )

    dataset_path = get_dataset_path()

    random.seed(42)
    dataset = json_dataset(
        json_file=os.path.join(dataset_path, "human_eval_plus.json"),
        sample_fields=lambda record: record_to_sample(record),
    )
    dataset = filter_dataset_by_sample_ids(dataset, sample_ids)

    logger.info(f"Dataset size: {len(dataset)}")

    return Task(
        dataset=dataset,
        epochs=Epochs(epochs),
        solver=solver_obj,
        sandbox="local",
        time_limit=HUMAN_EVAL_PLUS_VERIFY_TIMEOUT,
        fail_on_error=False,
    )


def record_to_sample(record: dict[str, Any]) -> Sample:
    soundness_test_list: list[tuple[str, str]] = []
    completeness_test_list: list[tuple[str, str]] = []
    if record["input_output"]:
        input_output = json.loads(record["input_output"])
        inputs = input_output.get("inputs", [])
        outputs = input_output.get("outputs", [])

        # Pair each input with its corresponding output
        soundness_test_list = list(zip(inputs, outputs))

    if record["mutated_input_output"]:
        mutated_input_output = json.loads(record["mutated_input_output"])
        mutated_inputs = mutated_input_output.get("inputs", [])
        mutated_outputs = mutated_input_output.get("outputs", [])
        completeness_test_list = list(zip(mutated_inputs, mutated_outputs))

    # Create a limited version for display in the prompt
    prompt_test_list: list[tuple[str, str]] = []
    prompt_test_string = ""
    # Pick up to 3 test cases at random, not sequentially
    if soundness_test_list:
        selected_tests = random.sample(
            soundness_test_list, min(3, len(soundness_test_list))
        )
        for input_str, output_str in selected_tests:
            test_case_str = f"assert solution({repr(input_str)}) == {repr(output_str)}"
            if len(test_case_str) <= 1000:
                prompt_test_list.append((input_str, output_str))
                prompt_test_string += test_case_str + "\n"

    return Sample(
        input=record["prompt"],
        id=record["problem_id"],
        metadata={
            "input": record["prompt"],
            "test_list": soundness_test_list,  # Full test list
            "mutated_test_list": completeness_test_list,
            "prompt_test_list": prompt_test_list,
            "problem_id": record["problem_id"],
            "difficulty": record["difficulty"],
            "parser": record["parser"],
            "signature": record["signature"],
        },
    )


if __name__ == "__main__":
    task = humaneval_plus()
