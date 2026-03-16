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


def write_filtered_jsonl(
    input_path: Path,
    output_path: Path,
    sample_ids: list[str],
) -> list[str]:
    rows_by_id: dict[str, dict] = {}
    requested_ids = set(sample_ids)

    with input_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            sample_id = str(row.get("id") or row.get("task_id") or "").strip()
            if sample_id not in requested_ids or sample_id in rows_by_id:
                continue
            rows_by_id[sample_id] = row
            if len(rows_by_id) == len(sample_ids):
                break

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for sample_id in sample_ids:
            row = rows_by_id.get(sample_id)
            if row is None:
                continue
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    return [sample_id for sample_id in sample_ids if sample_id not in rows_by_id]


def prepare_validation_input_dir(
    *,
    input_dir: Path,
    validation_output_dir: Path,
    prompt_versions: tuple[str, ...],
    sample_ids: list[str],
) -> Path:
    if not sample_ids:
        return input_dir

    filtered_input_dir = validation_output_dir / "_filtered_inputs"
    filtered_input_dir.mkdir(parents=True, exist_ok=True)
    for prompt_version in prompt_versions:
        input_path = input_dir / f"{prompt_version}.jsonl"
        output_path = filtered_input_dir / f"{prompt_version}.jsonl"
        missing_ids = write_filtered_jsonl(input_path, output_path, sample_ids)
        if missing_ids:
            click.echo(
                f"Warning: {input_path.name} is missing requested Defects4J sample IDs: {', '.join(missing_ids)}",
                err=True,
            )

    return filtered_input_dir


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
    "--sample-ids",
    type=str,
    default=None,
    help="Comma-separated Defects4J sample IDs to run.",
)
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
    sample_ids: str | None,
    max_concurrency: int,
    run_evaluation: bool,
    evaluate_only: bool,
    compile_timeout: int,
    test_timeout: int,
) -> None:
    parsed_sample_ids = parse_sample_ids(sample_ids)
    if limit is not None and parsed_sample_ids:
        raise click.UsageError("Use either --limit or --sample-ids, not both.")

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
                sample_ids=parsed_sample_ids,
            )
        )

    if run_evaluation:
        validation_dir = resolve_validation_output_dir(output_dir)
        validation_dir.mkdir(parents=True, exist_ok=True)
        validation_input_dir = prepare_validation_input_dir(
            input_dir=output_dir,
            validation_output_dir=validation_dir,
            prompt_versions=prompt_versions,
            sample_ids=parsed_sample_ids,
        )
        run_validation(
            input_dir=validation_input_dir,
            validation_output_dir=validation_dir,
            prompt_versions=prompt_versions,
            limit=None if parsed_sample_ids else limit,
            compile_timeout=compile_timeout,
            test_timeout=test_timeout,
            max_concurrency=max_concurrency,
        )
        aggregated_path = write_aggregated_counts(validation_dir)
        click.echo(f"Wrote {aggregated_path}")


if __name__ == "__main__":
    main()
