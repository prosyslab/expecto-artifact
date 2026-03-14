import json
import os
import random
import sys
import textwrap
from logging import getLogger
from pathlib import Path
from typing import Any

from inspect_ai import Epochs, Task, task
from inspect_ai.dataset import Sample, json_dataset

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from src.evaluation.sandbox import (
    initialize,
)

logger = getLogger(__name__)

import src.solvers as S
from src.tasks.dataset_paths import get_dataset_path

APPS_VERIFY_TIMEOUT = 60 * 60 * 3  # 3 Hours

INPUT = textwrap.dedent("""
        ## Question:
        {question}

        ## Test Cases:
        ```python
        {test_list_str}
        ```
        """).strip()


@task(name="apps")
def apps(
    solver: str = "monolithic",
    epochs: int = 1,
    max_attempts: int = 5,
    n_completions: int = 1,
    threshold: float = 0.5,
    use_test_cases: bool = True,
    use_memo: bool = True,
    check_unsat: bool = True,
    *args,
    **kwargs,
) -> Task:
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
        json_file=os.path.join(dataset_path, f"apps.json"),
        sample_fields=lambda record: record_to_sample(record),
    )

    logger.info(f"Dataset size: {len(dataset)}")

    initialize()

    return Task(
        dataset=dataset,
        epochs=Epochs(epochs),
        solver=solver_obj,
        sandbox="local",
        time_limit=APPS_VERIFY_TIMEOUT,
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
    for input_str, output_str in soundness_test_list:
        test_case_str = f"assert solution({repr(input_str)}) == {repr(output_str)}"
        if len(test_case_str) <= 1000:
            prompt_test_list.append((input_str, output_str))
            prompt_test_string += test_case_str + "\n"
        if len(prompt_test_list) >= 3:
            break

    input = INPUT.format(question=record["prompt"], test_list_str=prompt_test_string)

    return Sample(
        input=input,
        id=record["problem_id"],
        metadata={
            "input": input,
            "test_list": soundness_test_list,  # Full test list
            "mutated_test_list": completeness_test_list,
            "prompt_test_list": prompt_test_list,
            "problem_id": record["problem_id"],
            "difficulty": record["difficulty"],
            "parser": record["parser"],
            "signature": record["signature"],
        },
    )
