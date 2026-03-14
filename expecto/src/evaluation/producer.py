import logging
import multiprocessing as mp
from pathlib import Path
from typing import Callable, Optional, Set, Tuple

from inspect_ai.log import EvalSample, read_eval_log_async, read_eval_log_samples

logger = logging.getLogger(__name__)


def register_inspect_ai_log(
    log_path: str,
    put_sample: Callable[[EvalSample], None],
    progress_callback: Optional[Callable[[int], None]] = None,
    limit: Optional[int] = None,
    allowed_ids: Optional[Set[str]] = None,
) -> int:
    if not Path(log_path).exists():
        raise FileNotFoundError(f"Log file {log_path} does not exist")

    samples_processed_count = 0
    logger.info(
        f"[{__name__}] Starting to read samples from {log_path} with limit={limit}"
    )

    for sample in read_eval_log_samples(log_path, all_samples_required=False):
        if limit is not None and samples_processed_count >= limit:
            logger.info(
                f"Reached sample limit of {limit}. No more samples will be processed."
            )
            break

        if allowed_ids is None or str(sample.id) in allowed_ids:
            put_sample(sample)
            samples_processed_count += 1

            if progress_callback:
                progress_callback(samples_processed_count)

    logger.info(
        f"[{__name__}] Finished reading samples. Total samples put on queue: {samples_processed_count}"
    )

    return samples_processed_count


def producer_main(
    log_path: str,
    task_queue: "mp.JoinableQueue[EvalSample | None]",
    progress_queue: "mp.Queue[Tuple[str, int | str]]",
    worker_count: int,
    limit: Optional[int] = None,
    allowed_ids: Optional[Set[str]] = None,
) -> None:
    """
    Producer process entry point that streams EvalSample objects to a multiprocessing queue.
    """
    processed_count = 0
    try:
        processed_count = register_inspect_ai_log(
            log_path=log_path,
            put_sample=task_queue.put,
            progress_callback=lambda count: progress_queue.put(("progress", count)),
            limit=limit,
            allowed_ids=allowed_ids,
        )
    except Exception as exc:
        logger.exception("Producer encountered an error while reading %s", log_path)
        progress_queue.put(("error", str(exc)))
    finally:
        for _ in range(worker_count):
            task_queue.put(None)
        progress_queue.put(("done", processed_count))


async def get_task_num(log_path: str, limit: Optional[int] = None) -> int:
    logger.info(f"[{__name__}] Getting task number for {log_path} with limit={limit}")
    if not Path(log_path).exists():
        raise FileNotFoundError(f"Log file {log_path} does not exist")

    log_header = await read_eval_log_async(log_path, header_only=True)
    results = log_header.results
    if results is None:
        logger.warning("No results found in log file header. Assuming 0 samples.")
        return 0

    actual_samples = results.completed_samples
    logger.info(f"[{__name__}] Actual samples from log header: {actual_samples}")

    if limit is not None and limit > 0:
        if limit < actual_samples:
            logger.info(
                f"[{__name__}] Limiting to {limit} samples as per request (actual samples: {actual_samples})."
            )
            return limit
        else:
            logger.info(
                f"[{__name__}] Sample limit ({limit}) is >= actual samples ({actual_samples}). Processing all {actual_samples} samples."
            )
            return actual_samples
    logger.info(f"[{__name__}] Returning task number: {actual_samples}")
    return actual_samples
