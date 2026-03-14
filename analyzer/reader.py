import asyncio
import json
import re
import sys
from pathlib import Path

import click
from utils import read_score_logs

from expecto.src.evaluation.models import get_result_output_root

sys.set_int_max_str_digits(0)


def is_correct(scores: list) -> bool:
    return all([score.score == "C" for score in scores])


def is_sound_only(scores: list) -> bool:
    soundness_score = [score for score in scores if "soundness" in score.scorer_name]
    completeness_score = [
        score for score in scores if "completeness" in score.scorer_name
    ]

    return (
        len(soundness_score) > 0
        and soundness_score[0].score == "C"
        and completeness_score[0].score != "C"
    )


def is_complete_only(scores: list) -> bool:
    soundness_score = [score for score in scores if "soundness" in score.scorer_name]
    completeness_score = [
        score for score in scores if "completeness" in score.scorer_name
    ]

    return (len(soundness_score) == 0 or soundness_score[0].score != "C") and (
        len(completeness_score) > 0 and completeness_score[0].score == "C"
    )


def is_wrong_answer(scores: list) -> bool:
    return all([score.score == "I" or score.score == "TO" for score in scores])


def normalize(stderr: str) -> str:
    pattern = r"File \".*\", line \d+, in .*"
    stderr = re.sub(pattern, "", stderr)
    return stderr


def dump(f, metadata, output, sample):
    problem = metadata.get("input", "")
    difficulty = metadata.get("difficulty", "")
    nl_dsl = metadata.get("nl_dsl", "")
    parser = metadata.get("parser", "")
    generated_codes = output.get("generated_codes", [])
    total_attempts = output.get("total_attempts", 0)
    iteration = output.get("iteration", 0)
    num_of_nodes = output.get("num_of_nodes", 0)
    pruning_report = output.get("pruning_report", {})
    total_pruned_paths = pruning_report.get("total_invalid_paths_pruned", 0)
    pruned_by_checker = pruning_report.get("by_checker", {})
    scores = sample.scores

    zipped = zip(generated_codes, scores)

    flatten_scores = [score for scores in scores for score in scores]
    score_str = "U"
    if is_correct(flatten_scores):
        score_str = "Correct"
    elif is_sound_only(flatten_scores):
        score_str = "Sound Only"
    elif is_complete_only(flatten_scores):
        score_str = "Complete Only"
    elif is_wrong_answer(flatten_scores):
        score_str = "Wrong Answer"
    else:
        score_str = "Unknown"

    f.write(
        f"## Sample {sample.inspect_ai_sample.id} (Score: {score_str} Difficulty: {difficulty} Total Attempts: {total_attempts} Iteration: {iteration} Num of Nodes: {num_of_nodes} Pruned Invalid Paths: {total_pruned_paths})\n\n"
    )

    if isinstance(pruned_by_checker, dict) and len(pruned_by_checker) > 0:
        f.write("### Pruning Report\n")
        for checker_name in ("syntax&type", "testcase", "unsat"):
            count = pruned_by_checker.get(checker_name, 0)
            f.write(f"- {checker_name}: {count}\n")
        f.write("\n")

    f.write("### Generated Codes\n")
    for idx, (code, scores) in enumerate(zipped):
        assert isinstance(scores, list)
        f.write(f"#### Code {idx + 1}\n")
        f.write(f"```c\n{code}\n```\n")
        f.write("\n")
        f.write(f"#### Score {idx + 1}\n")
        for score in scores:
            f.write(f"Scorer: {score.scorer_name}\n")
            f.write(f"Score: {score.score}\n")
            f.write(f"Explanation: {score.explanation}\n")
            if score.execution_result:
                stderrs = {
                    normalize(result.stderr)
                    for result in score.execution_result
                    if result.stderr
                }
                joined = "\n".join(stderrs)
                f.write(f"STDERR:{joined}\n")
            f.write("\n\n")
    f.write("---" * 100 + "\n")
    f.write(f"{problem}\n")
    f.write("### NL DSL\n")
    f.write(f"{nl_dsl}\n")
    f.write("### Parser\n")
    f.write(f"{parser}\n")


async def runner(log_path: Path):
    logs = await read_score_logs(log_path)
    for log in logs:
        output_path = get_result_output_root(log.save_file) / "for_analyze.md"
        with open(output_path, "w") as f:
            samples = log.results
            for sample in samples:
                try:
                    output = json.loads(sample.inspect_ai_sample.output.completion)
                except json.JSONDecodeError:
                    continue
                metadata = sample.inspect_ai_sample.metadata
                if "generated_codes" not in output:
                    for method_signature in output:
                        method_output = output[method_signature]
                        dump(f, metadata, method_output, sample)
                if len(output.get("generated_codes", [])) == 0:
                    continue

                dump(f, metadata, output, sample)


@click.command()
@click.argument("log_path", type=click.Path(exists=True))
def main(log_path: str):
    asyncio.run(runner(Path(log_path)))


if __name__ == "__main__":
    asyncio.run(main())
