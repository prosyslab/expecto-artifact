import asyncio
import logging
import os
from typing import Optional, Set

from inspect_ai.log import read_eval_log_async
from rich.console import Console

from .models import (
    EvaluationResult,
    Sample,
    load_evaluation_result,
    sample_id_from_sample,
)

logger = logging.getLogger(__name__)
console = Console()


def parse_rerun_from_file(rerun_from: str) -> Set[str]:
    """
    Parse rerun IDs from a previous results file.

    Args:
        rerun_from: Path to the previous results file

    Returns:
        Set of sample IDs that had incorrect scores
    """
    allowed: Set[str] = set()
    prior = load_evaluation_result(rerun_from)

    for sample in prior.results:
        has_incorrect = False
        for score_item in _iter_scores(sample.scores):
            if str(score_item.score) == "I":
                has_incorrect = True
                break

        sample_id = sample_id_from_sample(sample)
        if has_incorrect and sample_id and sample_id != "None":
            allowed.add(sample_id)

    return allowed


def parse_rerun_ids(rerun_ids: str) -> Set[str]:
    """
    Parse rerun IDs from a comma-separated string.

    Args:
        rerun_ids: Comma-separated string of sample IDs

    Returns:
        Set of sample IDs
    """
    allowed_ids = set(id.strip() for id in rerun_ids.split(",") if id.strip())
    if not allowed_ids:
        console.print(
            "[bold yellow]Warning:[/] No valid IDs found in --rerun-ids. No samples will be processed."
        )
        logger.warning("No valid IDs found in --rerun-ids parameter")

    return allowed_ids


def merge_results(
    new_results: list,
    rerun_from: Optional[str],
    rerun_ids: Optional[str],
    overwrite: bool,
    log_path: str,
    scorers: str,
    save_file: str,
    limit: Optional[int],
    max_sandboxes: int,
) -> EvaluationResult:
    """
    Merge new results with previous results for rerun scenarios.

    Args:
        new_results: List of new Sample objects
        base_file: Base file to merge with (None for new file)
        rerun_from: Original rerun file path
        rerun_ids: Rerun IDs string
        overwrite: Whether to overwrite
        log_path: Log file path
        scorers: Scorers string
        save_file: Save file path
        limit: Sample limit
        max_sandboxes: Max sandboxes count

    Returns:
        Merged EvaluationResult object
    """
    if rerun_from and os.path.exists(rerun_from):
        previous_payload = load_evaluation_result(rerun_from)
    else:
        log_header = asyncio.run(read_eval_log_async(log_path, header_only=True))
        previous_payload = EvaluationResult(
            eval_spec=log_header.eval,
            scorers=[scorer.strip() for scorer in scorers.split(",")],
            save_file=save_file,
            limit=limit,
            max_sandboxes=max_sandboxes,
            results=[],
            metadata={},
        )

    # Map new results by sample id (string)
    new_by_id: dict[str, Sample] = {}
    for sample in new_results:
        try:
            sid = sample_id_from_sample(sample)
        except Exception:
            continue
        new_by_id[sid] = sample

    # Replace in-place within previous results list while preserving order
    merged_results: list[Sample] = []
    for entry in previous_payload.results:
        sid = sample_id_from_sample(entry)
        if sid in new_by_id:
            merged_results.append(new_by_id[sid])
        else:
            merged_results.append(entry)

    # Append any brand-new ids if they did not exist in prior (unlikely for rerun)
    prev_ids = {sample_id_from_sample(entry) for entry in previous_payload.results}
    for sid, sample in new_by_id.items():
        if sid not in prev_ids:
            merged_results.append(sample)

    # Update metadata
    meta = previous_payload.metadata.copy()
    if rerun_from:
        meta["rerun_from"] = rerun_from
    if rerun_ids:
        meta["rerun_ids"] = rerun_ids
    if overwrite:
        meta["overwrite"] = "true"

    return EvaluationResult(
        eval_spec=previous_payload.eval_spec,
        scorers=previous_payload.scorers,
        save_file=save_file,
        limit=previous_payload.limit,
        max_sandboxes=previous_payload.max_sandboxes,
        results=merged_results,
        metadata=meta,
    )


def _iter_scores(scores_node):
    if isinstance(scores_node, list):
        for item in scores_node:
            if isinstance(item, list):
                for sub in item:
                    yield sub
            else:
                yield item


def determine_rerun_base_file(
    rerun_from: Optional[str],
    rerun_ids: Optional[str],
    overwrite: bool,
    save_file: str,
) -> Optional[str]:
    """
    Determine the base file for merging results in rerun scenarios.

    Args:
        rerun_from: Path to prior results file
        rerun_ids: Comma-separated list of sample IDs
        overwrite: Whether to overwrite
        save_file: Save file path

    Returns:
        Base file path for merging, or None for new file
    """
    if rerun_from or rerun_ids:
        if rerun_from and not overwrite:
            # Use the original file as base for merging
            return rerun_from
        elif rerun_from and overwrite:
            # Use the save_file as base for merging (overwrite mode)
            return save_file
        else:
            # Only rerun_ids specified, create new file with only rerun results
            return None

    return None
