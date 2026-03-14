import asyncio
import json
import logging
import re
from typing import (
    Any,
    Callable,
    Coroutine,
    Iterable,
    Literal,
    Optional,
    Tuple,
    cast,
)

from inspect_ai.log import EvalSample

from src.evaluation.config import sample_id_var
from src.evaluation.models import ExecutionResult, Sample, Score
from src.evaluation.sandbox import Sandbox
from src.tasks.defects4j import Defects4jMethodSample
from src.utils.code import scoring_code_generation
from src.utils.dsl import (
    generate_evaluation_code,
    generate_evaluation_code_with_schema,
    get_parsed_arguments,
)

logger = logging.getLogger(__name__)

_scorer = Callable[[EvalSample, Sandbox], Coroutine[None, None, list[Score]]]
scorer = Callable[[EvalSample], Coroutine[None, None, Sample]]


ScoreLabel = Literal["I"] | Literal["C"] | Literal["TO"]
INCORRECT: ScoreLabel = "I"
CORRECT: ScoreLabel = "C"
TIMEOUT: ScoreLabel = "TO"

defined_scorers: dict[str, _scorer] = {}
current_scorers: list[_scorer] = []


def register_as_scorer(name: Optional[str] = None):
    def decorator(func: _scorer):
        nonlocal name
        if name is None:
            name = func.__name__
        defined_scorers[name] = func
        return func

    return decorator


def set_current_scorers(names: Iterable[str]):
    global current_scorers
    current_scorers = [defined_scorers[name.strip()] for name in names]


def collect_score(
    results: Iterable[ExecutionResult],
    relaxed: bool = False,
) -> Tuple[ScoreLabel, dict[ScoreLabel, int]]:
    collected: dict[ScoreLabel, int] = {
        INCORRECT: 0,
        CORRECT: 0,
        TIMEOUT: 0,
    }
    for result in results:
        if result.status == "timeout" or (
            result.stderr is not None and "timeout" in result.stderr.lower()
        ):
            collected[TIMEOUT] += 1
            collected = cast(dict[ScoreLabel, int], collected)
        elif result.stderr is not None and "out of memory" in result.stderr.lower():
            collected[TIMEOUT] += 1
            collected = cast(dict[ScoreLabel, int], collected)
        elif result.status == "error" or result.status == "failure":
            collected[INCORRECT] += 1
            collected = cast(dict[ScoreLabel, int], collected)
        else:
            collected[CORRECT] += 1
            collected = cast(dict[ScoreLabel, int], collected)

    if collected[CORRECT] == 0 and collected[INCORRECT] == 0:  # I = 0 C = 0 TO = *
        result = TIMEOUT
    elif (
        collected[CORRECT] >= collected[INCORRECT] and relaxed
    ):  # I > C in relaxed mode
        result = CORRECT
    elif (
        collected[CORRECT] < collected[INCORRECT] and relaxed
    ):  # I <= C in relaxed mode
        result = INCORRECT
    elif collected[INCORRECT] > 0:  # I > 0 in strict mode
        result = INCORRECT
    else:  # I = 0 C > 0 TO > 0
        result = CORRECT

    return result, collected


async def _run_postcondition_scorer(
    sample: EvalSample,
    scorer_name: str,
    test_list_key: str,
    test_code_generator: Callable[[str, str, str, list[tuple[str, str]]], list[str]],
    sandbox: Sandbox,
) -> list[Score]:
    """Helper function for postcondition-based scorers (soundness and completeness)."""
    completion = sample.output.completion
    if completion is None:
        logger.info(f"No completion for sample {sample.id}")
        return [
            Score(
                scorer_name=scorer_name,
                score=INCORRECT,
                explanation="No completion",
                execution_result=[],
            )
        ]
    try:
        generated = json.loads(completion)
    except json.JSONDecodeError:
        logger.info(f"JSONDecodeError for sample {sample.id}")
        return [
            Score(
                scorer_name=scorer_name,
                score=INCORRECT,
                explanation="JSONDecodeError",
                execution_result=[],
            )
        ]
    codes = generated["generated_codes"]
    if len(codes) == 0:
        logger.info(f"No codes for sample {sample.id}")
        return [
            Score(
                scorer_name=scorer_name,
                score=INCORRECT,
                explanation="No codes",
                execution_result=[],
            )
        ]

    parser = sample.metadata["parser"]
    signature = sample.metadata.get("signature", "")
    test_list = sample.metadata[test_list_key]

    test_codes_for_completions: list[list[str]] = []
    for code in codes:
        test_codes_for_completions.append(
            test_code_generator(code, parser, signature, test_list)
        )

    logger.info(f"Number of test cases: {len(test_list)}")

    scores: list[Score] = []

    async with sandbox:
        for test_codes in test_codes_for_completions:
            tasks = []
            for test_code in test_codes:
                tasks.append(asyncio.create_task(sandbox.run_test(test_code)))

            results = await asyncio.gather(*tasks)

            relaxed = False
            if "soundness" in scorer_name:
                relaxed = True
            score, collected = collect_score(results, relaxed=relaxed)
            scores.append(
                Score(
                    scorer_name=scorer_name,
                    score=score,
                    execution_result=list(results),
                    explanation=json.dumps(collected, indent=4, sort_keys=True),
                )
            )

    return scores


@register_as_scorer("completeness")
async def completeness(sample: EvalSample, sandbox: Sandbox) -> list[Score]:
    def generate_completeness_test_code(
        code: str, parser: str, signature: str, test_list: list[tuple[str, str]]
    ) -> list[str]:
        base_code = code + f"\n\n{parser}" + "\n\n# Test case\n"
        test_codes = []

        for test_input, test_output in test_list:
            test_codes.append(
                scoring_code_generation(
                    model_code=base_code,
                    parser_code=parser,
                    test_input=test_input,
                    test_output=test_output,
                    is_completeness=False,
                )
            )

        return test_codes

    return await _run_postcondition_scorer(
        sample=sample,
        scorer_name="completeness",
        test_list_key="test_list",
        test_code_generator=generate_completeness_test_code,
        sandbox=sandbox,
    )


@register_as_scorer("soundness")
async def soundness(sample: EvalSample, sandbox: Sandbox) -> list[Score]:
    def generate_soundness_test_code(
        code: str, parser: str, signature: str, test_list: list[tuple[str, str]]
    ) -> list[str]:
        base_code = code + f"\n\n{parser}" + "\n\n# Test case\n"
        test_codes = []

        for test_input, test_output in test_list:
            test_codes.append(
                scoring_code_generation(
                    model_code=base_code,
                    parser_code=parser,
                    test_input=test_input,
                    test_output=test_output,
                    is_completeness=True,
                )
            )

        return test_codes

    return await _run_postcondition_scorer(
        sample=sample,
        scorer_name="soundness",
        test_list_key="mutated_test_list",
        test_code_generator=generate_soundness_test_code,
        sandbox=sandbox,
    )


@register_as_scorer("correctness")
async def correctness(sample: EvalSample, sandbox: Sandbox) -> list[Score]:
    completions = sample.output.choices
    if len(completions) == 0:
        try:
            completions = json.loads(sample.output.completion)
            if "generated_codes" in completions:
                completions = completions["generated_codes"]
            else:
                completions = [completions]
        except json.JSONDecodeError:
            logger.info(f"No completion for sample {sample.id}")
            return [
                Score(
                    scorer_name="correctness",
                    score=INCORRECT,
                    explanation="No completion",
                    execution_result=[],
                )
            ]

    def get_last_codeblock(completion: Any) -> str:
        imports = "import sys\nimport time\nimport itertools\nfrom itertools import accumulate, product, permutations, combinations\nimport collections\nfrom collections import Counter, OrderedDict, deque, defaultdict, ChainMap\nfrom functools import lru_cache\nimport math\nfrom math import sqrt, sin, cos, tan, ceil, fabs, floor, gcd, exp, log, log2\nimport fractions\nfrom typing import List, Tuple\nimport numpy as np\nimport random\nimport heapq\nfrom heapq import *\n"
        if isinstance(completion, str):
            return imports + completion + "\n\nsolution()"
        completion = completion.message.content
        pattern = r"```python\n(.*?)\n```"

        match = re.search(pattern, completion, flags=re.DOTALL)

        if match:
            logger.info(f"Match: {match.group(1)}")
            return imports + match.group(1) + "\n\nsolution()"
        return imports + completion

    test_codes = [get_last_codeblock(completion) for completion in completions]

    test_list = sample.metadata["test_list"]

    async with sandbox:
        tasks = [
            asyncio.create_task(sandbox.run_test_with_io(test_code, test_list))
            for test_code in test_codes
        ]
        results = await asyncio.gather(*tasks)

    scores: list[Score] = []
    for result in results:
        if result.status == "success":
            scores.append(
                Score(
                    scorer_name="correctness",
                    score=CORRECT,
                    execution_result=list(results),
                )
            )
        else:
            scores.append(
                Score(
                    scorer_name="correctness",
                    score=INCORRECT,
                    explanation=result.stderr,
                    execution_result=[result],
                )
            )

    return scores


@register_as_scorer("dsl_completeness")
async def dsl_completeness(sample: EvalSample, sandbox: Sandbox) -> list[Score]:
    def generate_dsl_completeness_test_code(
        code: str, parser: str, signature: str, test_list: list[tuple[str, str]]
    ) -> list[str]:
        test_codes = []
        for test_input, test_output in test_list:
            try:
                parsed_arguments = get_parsed_arguments(
                    parser, signature, test_input, test_output
                )
                # For completeness, we expect the DSL constraint to be unsatisfiable (is_sat=False)
                # for invalid/mutated test cases
                eval_code = generate_evaluation_code(
                    dsl=code,
                    parsed_arguments=parsed_arguments,
                    function_signature=signature,
                    is_correct=True,
                    is_local=True,
                )
                test_codes.append(eval_code)
            except Exception as e:
                logger.error(f"DSL evaluation generation failed: {e}")

        return test_codes

    return await _run_postcondition_scorer(
        sample=sample,
        scorer_name="dsl_completeness",
        test_list_key="test_list",
        test_code_generator=generate_dsl_completeness_test_code,
        sandbox=sandbox,
    )


@register_as_scorer("dsl_soundness")
async def dsl_soundness(sample: EvalSample, sandbox: Sandbox) -> list[Score]:
    def generate_dsl_soundness_test_code(
        code: str, parser: str, signature: str, test_list: list[tuple[str, str]]
    ) -> list[str]:
        test_codes = []
        for test_input, test_output in test_list:
            try:
                # For completeness, we expect the DSL constraint to be unsatisfiable (is_sat=False)
                # for invalid/mutated test cases
                parsed_arguments = get_parsed_arguments(
                    parser, signature, test_input, test_output
                )
                eval_code = generate_evaluation_code(
                    dsl=code,
                    parsed_arguments=parsed_arguments,
                    function_signature=signature,
                    is_correct=False,
                    is_local=True,
                )
                test_codes.append(eval_code)
            except Exception as e:
                logger.error(f"DSL evaluation generation failed: {e}")

        return test_codes

    return await _run_postcondition_scorer(
        sample=sample,
        scorer_name="dsl_soundness",
        test_list_key="mutated_test_list",
        test_code_generator=generate_dsl_soundness_test_code,
        sandbox=sandbox,
    )


async def postcondition_scorer(sample: EvalSample) -> Sample:
    sandbox = Sandbox()
    completeness_scores = await dsl_completeness(sample, sandbox)
    soundness_scores = await dsl_soundness(sample, sandbox)
    return Sample(
        inspect_ai_sample=sample,
        scores=list(zip(completeness_scores, soundness_scores)),
    )


def _generate_evaluation_tasks(
    *,
    dsl_code: str,
    method_data: Defects4jMethodSample,
    test_type: Literal["corrects", "incorrects"],
    is_correct: bool,
) -> list[tuple[str, str]]:
    """Generate evaluation code tasks for specified test type."""
    tasks: list[tuple[str, str]] = []
    for test_id, test_dump in getattr(method_data, test_type).items():
        if "entry" not in test_dump or "exit" not in test_dump:
            continue
        eval_code = generate_evaluation_code_with_schema(
            dsl=dsl_code,
            val=test_dump,
            entry_schema=method_data.method_info.entry_schema.model_dump(),
            exit_schema=method_data.method_info.exit_schema.model_dump(),
            is_correct=is_correct,
            is_local=True,
        )
        tasks.append((test_id, eval_code))

    return tasks


async def _run_evaluation_tasks(tasks: list[tuple[str, str]]) -> list:
    """Run evaluation tasks in parallel and return execution results."""
    if not tasks:
        return []

    async with Sandbox() as sandbox:
        execution_results = await asyncio.gather(
            *[sandbox.run_test(eval_code, 60) for _, eval_code in tasks],
            return_exceptions=True,
        )

    return execution_results


def _process_test_results(execution_results: list) -> dict[str, int]:
    """Process execution results into method-level statistics."""
    results = _default_method_stats()
    for result in execution_results:
        results["total"] += 1
        if isinstance(result, Exception):
            results["failed"] += 1
        else:
            execution_result = cast(ExecutionResult, result)
            if execution_result.status == "success":
                results["passed"] += 1
            elif (
                execution_result.status == "timeout"
                or execution_result.stderr == "Out of memory"
            ):
                results["timeout"] += 1
            elif execution_result.status == "error":
                results["error"] += 1
            else:
                results["failed"] += 1

    return results


def _default_method_stats() -> dict[str, int]:
    return {
        "passed": 0,
        "failed": 0,
        "timeout": 0,
        "error": 0,
        "total": 0,
    }


def _extract_method_execution_summary(
    tasks: list[tuple[str, str]],
    execution_results: list,
) -> tuple[dict[str, int], list[ExecutionResult], list[dict[str, Any]]]:
    """Summarize execution outcomes for a single method."""
    method_stats = _process_test_results(execution_results)

    filtered_execution_results = [
        result for result in execution_results if isinstance(result, ExecutionResult)
    ]

    exception_details: list[dict[str, Any]] = []
    for (test_id, _), result in zip(tasks, execution_results):
        if isinstance(result, Exception):
            exception_details.append(
                {
                    "test_id": test_id,
                    "error": repr(result),
                }
            )

    return method_stats, filtered_execution_results, exception_details


def _create_method_score(
    *,
    scorer_name: str,
    method_signature: str,
    score_label: ScoreLabel,
    passed: bool,
    description: str,
    stats: dict[str, int],
    test_ids: list[str],
    execution_results: list[ExecutionResult],
    exceptions: list[dict[str, Any]],
) -> Score:
    """Create a per-method Score with contextual metadata."""
    metadata: dict[str, Any] = {
        "method_signature": method_signature,
        "summary": stats,
        "passed": passed,
        "test_ids": test_ids,
    }
    if exceptions:
        metadata["exceptions"] = exceptions

    explanation = (
        f"{method_signature} :: {'PASSED' if passed else 'FAILED'} | {description}"
    )

    return Score(
        scorer_name=scorer_name,
        score=score_label,
        explanation=explanation,
        metadata=metadata,
        execution_result=execution_results,
    )


def _create_unavailable_method_score(
    *,
    scorer_name: str,
    method_signature: str,
    reason: str,
) -> Score:
    return Score(
        scorer_name=scorer_name,
        score=INCORRECT,
        explanation=reason,
        metadata={
            "method_signature": method_signature,
            "summary": _default_method_stats(),
            "passed": False,
            "test_ids": [],
        },
        execution_result=[],
    )


def _create_unavailable_method_score_group(
    method_signature: str, reason: str
) -> list[list[Score]]:
    return [
        [
            _create_unavailable_method_score(
                scorer_name="defects4j_completeness",
                method_signature=method_signature,
                reason=reason,
            ),
            _create_unavailable_method_score(
                scorer_name="defects4j_soundness",
                method_signature=method_signature,
                reason=reason,
            ),
        ]
    ]


async def defects4j_scorer(sample: EvalSample) -> Sample:
    """
    Score Defects4J samples for completeness and soundness.

    Completeness: The method must pass all correct tests
    Soundness: The method must reject at least one incorrect test
    """
    method_data = Defects4jMethodSample.model_validate(sample.metadata)
    method_signature = method_data.method_info.signature
    completion = sample.output.completion

    if completion is None:
        method_scores = _create_unavailable_method_score_group(
            method_signature, "No completion"
        )
    else:
        try:
            specs = json.loads(completion)
        except json.JSONDecodeError:
            specs = None

        if not isinstance(specs, dict):
            method_scores = _create_unavailable_method_score_group(
                method_signature, "JSONDecodeError"
            )
        else:
            generated_codes = specs.get("generated_codes", [])
            if not generated_codes:
                method_scores = _create_unavailable_method_score_group(
                    method_signature, "No codes"
                )
            else:
                dsl_code = generated_codes[0]
                logger.info(f"Evaluating method {method_signature}")

                completeness_tasks = _generate_evaluation_tasks(
                    dsl_code=dsl_code,
                    method_data=method_data,
                    test_type="corrects",
                    is_correct=True,
                )
                logger.info(
                    f"{len(completeness_tasks)} completeness tasks for {method_signature}"
                )

                completeness_execution_results = await _run_evaluation_tasks(
                    completeness_tasks
                )
                (
                    completeness_stats,
                    completeness_exec_results,
                    completeness_exceptions,
                ) = _extract_method_execution_summary(
                    completeness_tasks, completeness_execution_results
                )
                completeness_passed = completeness_stats["failed"] == 0
                completeness_score_label = (
                    CORRECT if completeness_passed else INCORRECT
                )
                completeness_score = _create_method_score(
                    scorer_name="defects4j_completeness",
                    method_signature=method_signature,
                    score_label=completeness_score_label,
                    passed=completeness_passed,
                    description="All correct tests must pass",
                    stats=completeness_stats,
                    test_ids=[test_id for test_id, _ in completeness_tasks],
                    execution_results=completeness_exec_results,
                    exceptions=completeness_exceptions,
                )

                soundness_tasks = _generate_evaluation_tasks(
                    dsl_code=dsl_code,
                    method_data=method_data,
                    test_type="incorrects",
                    is_correct=False,
                )
                logger.info(
                    f"{len(soundness_tasks)} soundness tasks for {method_signature}"
                )

                soundness_execution_results = await _run_evaluation_tasks(
                    soundness_tasks
                )
                (
                    soundness_stats,
                    soundness_exec_results,
                    soundness_exceptions,
                ) = _extract_method_execution_summary(
                    soundness_tasks, soundness_execution_results
                )
                soundness_passed = soundness_stats["passed"] > 0
                soundness_score_label = CORRECT if soundness_passed else INCORRECT
                soundness_score = _create_method_score(
                    scorer_name="defects4j_soundness",
                    method_signature=method_signature,
                    score_label=soundness_score_label,
                    passed=soundness_passed,
                    description="At least one incorrect test must be rejected",
                    stats=soundness_stats,
                    test_ids=[test_id for test_id, _ in soundness_tasks],
                    execution_results=soundness_exec_results,
                    exceptions=soundness_exceptions,
                )

                method_scores = [[completeness_score, soundness_score]]
    sample.events.clear()
    return Sample(
        inspect_ai_sample=sample,
        scores=method_scores,
    )


async def run_all_scorer(sample: EvalSample, scorers: Iterable[_scorer]) -> Sample:
    sample_id_var.set(str(sample.id))
    tasks = [asyncio.create_task(scorer(sample, Sandbox())) for scorer in scorers]
    results = await asyncio.gather(*tasks)
    transposed_results = list(zip(*results))
    return Sample(
        inspect_ai_sample=sample,
        scores=transposed_results,
    )


def get_scorer(scorers: str) -> scorer:
    if scorers == "postcondition":
        return postcondition_scorer
    if scorers == "defects4j":
        return defects4j_scorer
    splitted = scorers.split(",")
    set_current_scorers(splitted)

    async def wrapper(sample: EvalSample):
        global current_scorers
        sample.attachments.clear()  # For light-weight logging
        return await run_all_scorer(sample, current_scorers)

    return wrapper
