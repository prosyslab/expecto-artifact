import logging
from pathlib import Path
from typing import Optional

from rich.console import Console

from src.evaluation.models import (
    EvaluationResult,
    EvaluationResultManifest,
    PersistedSampleRef,
    build_persisted_sample_file,
    build_result_store_manifest_path,
    build_result_store_root,
    build_result_store_samples_dir,
    build_sample_file_name,
    load_evaluation_result,
    resolve_result_store_manifest,
)
from src.evaluation.rerun_handler import (
    merge_results,
)

logger = logging.getLogger(__name__)
console = Console()


def create_evaluation_result(
    eval_spec,
    scorers: str,
    save_file: str,
    limit: Optional[int],
    max_sandboxes: int,
    results: list,
    metadata: Optional[dict] = None,
) -> EvaluationResult:
    """
    Create an EvaluationResult object from the execution parameters and results.

    Args:
        eval_spec: Evaluation specification from log header
        scorers: Comma-separated scorers string
        save_file: Save file path
        limit: Sample limit
        max_sandboxes: Maximum sandboxes count
        results: List of Sample objects

    Returns:
        EvaluationResult object
    """
    return EvaluationResult(
        eval_spec=eval_spec,
        scorers=[scorer.strip() for scorer in scorers.split(",")],
        save_file=save_file,
        limit=limit,
        max_sandboxes=max_sandboxes,
        results=results,
        metadata=metadata or {},
    )


def write_result_store(evaluation_result: EvaluationResult, save_file: str) -> Path:
    store_root = build_result_store_root(save_file)
    manifest_path = build_result_store_manifest_path(save_file)
    samples_dir = build_result_store_samples_dir(save_file)

    store_root.mkdir(parents=True, exist_ok=True)
    samples_dir.mkdir(parents=True, exist_ok=True)

    for existing_file in samples_dir.glob("*.json"):
        existing_file.unlink()

    sample_refs: list[PersistedSampleRef] = []
    for sample in evaluation_result.results:
        persisted_sample = build_persisted_sample_file(sample)
        file_name = build_sample_file_name(persisted_sample.sample_id)
        sample_path = samples_dir / file_name
        sample_path.write_text(persisted_sample.model_dump_json(indent=4))
        sample_refs.append(
            PersistedSampleRef(
                sample_id=persisted_sample.sample_id,
                file_name=file_name,
            )
        )

    manifest = EvaluationResultManifest(
        eval_spec=evaluation_result.eval_spec,
        scorers=evaluation_result.scorers,
        save_file=str(manifest_path),
        limit=evaluation_result.limit,
        max_sandboxes=evaluation_result.max_sandboxes,
        metadata=evaluation_result.metadata,
        samples=sample_refs,
    )
    manifest_path.write_text(manifest.model_dump_json(indent=4))
    return store_root


def convert_legacy_result(
    source_path: str | Path,
    save_file: str | Path | None = None,
    overwrite: bool = False,
) -> Path:
    source = Path(source_path)
    if resolve_result_store_manifest(source) is not None:
        raise ValueError(
            f"Source is already an `{build_result_store_root(source).name}` store: {source}"
        )

    if not source.is_file():
        raise FileNotFoundError(f"Legacy result file not found: {source}")

    target_anchor = Path(save_file) if save_file is not None else source
    store_root = build_result_store_root(target_anchor)
    if store_root.exists() and not overwrite:
        raise FileExistsError(
            f"Target store already exists at {store_root}. Use overwrite to replace it."
        )

    loaded = load_evaluation_result(source)
    migrated_metadata = dict(loaded.metadata)
    migrated_metadata["migrated_from"] = str(source)

    migrated = EvaluationResult(
        eval_spec=loaded.eval_spec,
        scorers=loaded.scorers,
        save_file=str(target_anchor),
        limit=loaded.limit,
        max_sandboxes=loaded.max_sandboxes,
        results=loaded.results,
        metadata=migrated_metadata,
    )

    return write_result_store(migrated, str(target_anchor))


def save_results(
    results: list,
    save_file: str,
    eval_spec,
    scorers: str,
    limit: Optional[int],
    max_sandboxes: int,
    rerun_from: Optional[str] = None,
    rerun_ids: Optional[str] = None,
    overwrite: bool = False,
    no_merge: bool = False,
    log_path: str = "",
) -> None:
    """
    Save evaluation results to file, handling rerun scenarios and merging.

    Args:
        results: List of Sample objects to save
        save_file: Path to save the results file
        eval_spec: Evaluation specification
        scorers: Comma-separated scorers string
        limit: Sample limit
        max_sandboxes: Maximum sandboxes count
        rerun_from: Path to prior results file for rerun
        rerun_ids: Comma-separated list of sample IDs for rerun
        overwrite: Whether to overwrite existing file
        no_merge: Whether to skip merging with previous results
    """

    if overwrite and rerun_from:
        save_file = rerun_from

    metadata: dict[str, str] = {}
    if log_path:
        metadata["log_path"] = log_path
    if rerun_from:
        metadata["rerun_from"] = rerun_from
    if rerun_ids:
        metadata["rerun_ids"] = rerun_ids
    if overwrite:
        metadata["overwrite"] = "true"

    # If rerun mode is enabled, merge new results into prior results file
    if (rerun_from or rerun_ids) and not no_merge:
        merged_payload = merge_results(
            new_results=results,
            rerun_from=rerun_from,
            rerun_ids=rerun_ids,
            overwrite=overwrite,
            log_path=log_path,
            scorers=scorers,
            save_file=save_file,
            limit=limit,
            max_sandboxes=max_sandboxes,
        )
        store_root = write_result_store(merged_payload, save_file)
    else:
        execution_info = create_evaluation_result(
            eval_spec=eval_spec,
            scorers=scorers,
            save_file=save_file,
            limit=limit,
            max_sandboxes=max_sandboxes,
            results=results,
            metadata=metadata,
        )
        store_root = write_result_store(execution_info, save_file)

    console.print(f"\n[bold green]Results saved to: {store_root}[/]")
