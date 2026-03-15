import asyncio
import json
import subprocess
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NL2POSTCOND_ROOT = PROJECT_ROOT / "nl-2-postcond" / "nl2postcondition_source_evalplus"
sys.path.append(str(PROJECT_ROOT))
sys.path.insert(0, str(NL2POSTCOND_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from defects4j_generation import run_generation

MODEL_NAME = "openai/gpt-4.1-mini"
DEFAULT_OUTPUT_DIR = Path("/workspace/nl-2-postcond/defects4j")
DEFAULT_DATASET_PATH = PROJECT_ROOT / "datasets" / "defects4j.jsonl"
VALIDATOR_SCRIPT = NL2POSTCOND_ROOT / "defects4j_assertion_validator.py"
VALID_PROMPT_VARIANTS = {
    "all": ("simple", "base"),
    "simple": ("simple",),
    "base": ("base",),
}


def empty_category_counts() -> dict[str, int]:
    return {"SC": 0, "S": 0, "C": 0, "W": 0}


def resolve_dataset_path() -> str:
    return str(DEFAULT_DATASET_PATH)


def resolve_validation_output_dir(output_dir: Path) -> Path:
    return output_dir / "validation"


def resolve_prompt_versions(variant: str) -> tuple[str, ...]:
    versions = VALID_PROMPT_VARIANTS.get(variant.lower())
    if versions is None:
        raise click.ClickException(f"Unsupported NL2Postcond variant: {variant}")
    return versions


def run_validation(
    *,
    input_dir: Path,
    validation_output_dir: Path,
    prompt_versions: tuple[str, ...],
    limit: int | None,
    compile_timeout: int,
    test_timeout: int,
    max_concurrency: int,
) -> None:
    preferred_inputs = [input_dir / f"{prompt_version}.jsonl" for prompt_version in prompt_versions]
    missing_inputs = [path.name for path in preferred_inputs if not path.is_file()]
    if missing_inputs:
        missing_display = ", ".join(missing_inputs)
        raise click.ClickException(
            f"Missing expected jsonl input files under {input_dir}: {missing_display}"
        )
    input_files = preferred_inputs

    for input_file in input_files:
        command = [
            sys.executable,
            str(VALIDATOR_SCRIPT),
            str(input_file),
            "--output-dir",
            str(validation_output_dir),
            "--compile-timeout",
            str(compile_timeout),
            "--test-timeout",
            str(test_timeout),
            "--max-concurrency",
            str(max_concurrency),
        ]
        if limit is not None:
            command.extend(["--limit", str(limit)])

        subprocess.run(command, check=True)


def write_aggregated_counts(validation_output_dir: Path) -> Path:
    final_jsonl_paths = sorted(validation_output_dir.glob("*.final.jsonl"))
    if not final_jsonl_paths:
        raise click.ClickException(
            f"No final JSONL outputs found in {validation_output_dir}"
        )

    aggregated = {
        "records_total": 0,
        "category_counts": empty_category_counts(),
        "files": {},
    }

    for final_jsonl_path in final_jsonl_paths:
        file_counts = {
            "records_total": 0,
            "category_counts": empty_category_counts(),
        }
        with final_jsonl_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                row = json.loads(stripped)
                category = row.get("category", "W")
                if category not in file_counts["category_counts"]:
                    raise click.ClickException(
                        f"Unexpected category '{category}' in {final_jsonl_path}"
                    )
                file_counts["records_total"] += 1
                file_counts["category_counts"][category] += 1
                aggregated["records_total"] += 1
                aggregated["category_counts"][category] += 1

        aggregated["files"][final_jsonl_path.name] = file_counts

    aggregated_path = validation_output_dir / "aggregated.json"
    aggregated_path.write_text(
        json.dumps(aggregated, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return aggregated_path


@click.command()
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_OUTPUT_DIR,
    show_default=True,
    help="Directory where simple.jsonl/base.jsonl and validation outputs will be written.",
)
@click.option(
    "--variant",
    type=click.Choice(tuple(VALID_PROMPT_VARIANTS.keys()), case_sensitive=False),
    default="all",
    show_default=True,
    help="Which NL2Postcond prompt variant to run.",
)
@click.option("--limit", type=int, default=None, help="Limit the number of methods.")
@click.option(
    "--max-concurrency",
    type=click.IntRange(min=1),
    default=8,
    show_default=True,
    help="Maximum number of concurrent generation and validation workers.",
)
@click.option(
    "--run-evaluation/--skip-evaluation",
    default=True,
    show_default=True,
    help="Run Defects4J validation on generated simple/base JSONL outputs.",
)
@click.option(
    "--evaluate-only",
    is_flag=True,
    help="Skip generation and validate existing simple/base JSONL files in output-dir.",
)
@click.option(
    "--compile-timeout",
    type=int,
    default=900,
    show_default=True,
    help="Timeout in seconds for Defects4J compile during evaluation.",
)
@click.option(
    "--test-timeout",
    type=int,
    default=180,
    show_default=True,
    help="Timeout in seconds for each JUnit test request during evaluation.",
)
def main(
    output_dir: Path,
    variant: str,
    limit: int | None,
    max_concurrency: int,
    run_evaluation: bool,
    evaluate_only: bool,
    compile_timeout: int,
    test_timeout: int,
) -> None:
    prompt_versions = resolve_prompt_versions(variant)

    if not evaluate_only:
        resolved_dataset_path = resolve_dataset_path()
        asyncio.run(
            run_generation(
                model_name=MODEL_NAME,
                dataset_path=resolved_dataset_path,
                output_dir=output_dir,
                limit=limit,
                max_concurrency=max_concurrency,
                prompt_versions=prompt_versions,
            )
        )

    if run_evaluation:
        validation_dir = resolve_validation_output_dir(output_dir)
        validation_dir.mkdir(parents=True, exist_ok=True)
        run_validation(
            input_dir=output_dir,
            validation_output_dir=validation_dir,
            prompt_versions=prompt_versions,
            limit=limit,
            compile_timeout=compile_timeout,
            test_timeout=test_timeout,
            max_concurrency=max_concurrency,
        )
        aggregated_path = write_aggregated_counts(validation_dir)
        click.echo(f"Wrote {aggregated_path}")


if __name__ == "__main__":
    main()
