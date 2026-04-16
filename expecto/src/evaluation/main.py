import asyncio
import logging
import multiprocessing as mp
import sys
from contextlib import suppress
from pathlib import Path
from typing import Optional, Set

import click
from inspect_ai.log import read_eval_log_async
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.evaluation.config import config
from src.evaluation.consumer import worker_main
from src.evaluation.models import Sample
from src.evaluation.parallelism import get_available_cpu_count, resolve_worker_count
from src.evaluation.producer import get_task_num, producer_main
from src.evaluation.rerun_handler import (
    parse_rerun_from_file,
    parse_rerun_ids,
)
from src.evaluation.result_manager import convert_legacy_result, save_results
from src.evaluation.sandbox import initialize, shutdown

sys.set_int_max_str_digits(10000000)

# Create a console instance for rich output
console = Console()

logger = logging.getLogger(__name__)

TASK_SCORERS = {
    "apps": "postcondition",
    "humaneval_plus": "postcondition",
    "defects4j": "defects4j",
}


def get_logger_path(log_path: str):
    lp = Path(log_path).parent / "eval_logs"
    return str(lp)


def get_default_scorers(task: str) -> str:
    scorers = TASK_SCORERS.get(task)
    if scorers is None:
        raise ValueError(f"No default scorers configured for task {task}")
    return scorers


async def run_executor(
    log_path: str,
    save_file: str = "results.json",
    scorers: Optional[str] = None,
    limit: Optional[int] = None,
    max_sandboxes: Optional[int] = None,
    rerun_from: Optional[str] = None,
    rerun_ids: Optional[str] = None,
    overwrite: bool = False,
    no_merge: bool = False,
):
    """
    Main function that orchestrates the code execution process.

    Args:
        save_file: Anchor path used to determine where `evaluation_result/` is written.
        limit: Limit the number of samples to process from the log. Processes all if not set.
        max_sandboxes: Maximum number of concurrent sandboxes.
    """
    # 1. Setup phase
    logger_path = get_logger_path(log_path)
    config._setup_logging(logger_path)

    if max_sandboxes is not None:
        config.MAX_SANDBOXES = max_sandboxes

    # Initialize semaphores for the current event loop
    initialize()

    # 2. Configuration phase
    log_header = await read_eval_log_async(log_path, header_only=True)
    eval_spec = log_header.eval
    model = eval_spec.model
    task = eval_spec.task
    scorers = scorers or get_default_scorers(task)
    level = eval_spec.task_args.get("level", "unknown")

    console.print(
        Panel.fit(
            f"Model: [bold cyan]{model}[/]\nTask: [bold cyan]{task}[/]\nLevel: [bold cyan]{level}[/]",
            border_style="green",
        )
    )
    logger.info("Using scorers: %s", scorers)

    # Prepare re-run filtering if requested
    allowed_ids: Optional[Set[str]] = None
    if rerun_from:
        allowed_ids = parse_rerun_from_file(rerun_from)

    # Handle explicit ID list for re-run
    if rerun_ids:
        allowed_ids = parse_rerun_ids(rerun_ids)

    # 3. Execution phase
    if allowed_ids is not None:
        # For re-run mode, we know exactly how many samples will be processed
        num_samples = len(allowed_ids)
        if limit is not None and limit > 0:
            num_samples = min(num_samples, limit)
    else:
        # For normal mode, get total samples from log
        num_samples = await get_task_num(
            log_path, limit=limit
        )  # Pass limit to get_task_num

    logger.info(f"Number of samples to process: {num_samples}")

    ctx = mp.get_context("spawn")
    task_queue = ctx.JoinableQueue()
    result_queue = ctx.Queue()
    progress_queue = ctx.Queue()
    results: list[Sample] = []

    available_cpu_count = get_available_cpu_count()
    worker_count = resolve_worker_count(
        num_samples=num_samples,
        configured_limit=config.MAX_CONSUMER_PROCESSES,
        available_cpu_count=available_cpu_count,
    )
    subprocess_semaphore = ctx.Semaphore(config.MAX_SUBPROCESS_CONCURRENT)
    logger.info(
        "Spawning %d worker process(es) (available_cpus=%d, configured_limit=%d, samples=%d).",
        worker_count,
        available_cpu_count,
        config.MAX_CONSUMER_PROCESSES,
        num_samples,
    )

    worker_processes = []
    for index in range(worker_count):
        process = ctx.Process(
            target=worker_main,
            args=(task_queue, result_queue, scorers, subprocess_semaphore),
            name=f"consumer-worker-{index}",
        )
        process.daemon = True
        process.start()
        worker_processes.append(process)

    producer_process = ctx.Process(
        target=producer_main,
        args=(log_path, task_queue, progress_queue, worker_count),
        kwargs={"limit": limit, "allowed_ids": allowed_ids},
        name="task producer process",
    )
    producer_process.daemon = True
    producer_process.start()

    expected_results_total = 0
    expected_results_event = asyncio.Event()
    producer_done = False
    producer_errors: list[str] = []

    # Create progress display
    progress = Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(complete_style="green", finished_style="green"),
        TaskProgressColumn(
            text_format="{task.completed:.0f}/{task.total:.0f}",
            text_format_no_percentage="{task.completed:.0f}/?",
            style="progress.percentage",
        ),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )

    # Add tasks to track
    # Overall progress and consumer progress will have their totals updated once the producer determines the actual number of tasks.
    overall_task = progress.add_task("[green]Overall Progress", total=num_samples)
    producer_sample_id = progress.add_task(
        "[yellow]Producing Tasks", total=num_samples
    )  # Total based on samples
    consumer_sample_id = progress.add_task("[cyan]Processing Tasks", total=num_samples)

    # Create producer and consumer tasks
    async def monitor_producer():
        nonlocal expected_results_total, producer_done
        loop = asyncio.get_running_loop()

        while True:
            try:
                message_type, payload = await loop.run_in_executor(
                    None, progress_queue.get
                )
            except Exception as exc:
                logger.error("Producer progress queue failed: %s", exc)
                expected_results_event.set()
                break

            if message_type == "progress":
                processed_count = int(payload)
                progress.update(producer_sample_id, completed=processed_count)
                if processed_count != num_samples:
                    progress.update(overall_task, total=processed_count)
                    progress.update(consumer_sample_id, total=processed_count)
            elif message_type == "error":
                error_message = str(payload)
                producer_errors.append(error_message)
                logger.error("Producer reported error: %s", error_message)
            elif message_type == "done":
                processed_count = int(payload)
                expected_results_total = processed_count
                expected_results_event.set()
                progress.update(producer_sample_id, completed=processed_count)
                if processed_count != num_samples:
                    progress.update(overall_task, total=processed_count)
                    progress.update(consumer_sample_id, total=processed_count)
                producer_done = True
                logger.info(
                    "Producer has finished processing samples. Generated %d tasks.",
                    processed_count,
                )
                break
            else:
                logger.warning(
                    "Unknown producer message type received: %s", message_type
                )

        return expected_results_total

    async def collect_results():
        collected_results = 0
        completed_workers = 0
        loop = asyncio.get_running_loop()

        while True:
            item = await loop.run_in_executor(None, result_queue.get)

            if item is None:
                completed_workers += 1
            else:
                results.append(item)
                collected_results += 1
                progress.update(consumer_sample_id, advance=1)
                progress.update(overall_task, advance=1)

            if (
                expected_results_event.is_set()
                and collected_results >= expected_results_total
                and (producer_done or completed_workers >= worker_count)
            ):
                break

            if producer_done and completed_workers >= worker_count:
                if expected_results_total > collected_results:
                    logger.warning(
                        "Producer finished but only %d/%d samples reported results.",
                        collected_results,
                        expected_results_total,
                    )
                break

        return collected_results

    # Start the tasks
    with progress:
        consumer_task_handle = asyncio.create_task(
            collect_results(), name="result collector"
        )
        producer_task_handle = asyncio.create_task(
            monitor_producer(), name="producer monitor"
        )
        producer_monitor_completed = False

        try:
            await producer_task_handle
            producer_monitor_completed = True

            await asyncio.get_running_loop().run_in_executor(None, task_queue.join)
            logger.info("All tasks have been processed from the queue.")

            await consumer_task_handle
            logger.info("All consumer workers have completed.")
        finally:
            loop = asyncio.get_running_loop()

            if not expected_results_event.is_set():
                expected_results_event.set()

            if not producer_monitor_completed and not producer_done:
                for _ in range(worker_count):
                    await loop.run_in_executor(None, task_queue.put, None)

            if not consumer_task_handle.done():
                consumer_task_handle.cancel()
                with suppress(asyncio.CancelledError):
                    await consumer_task_handle

            if not producer_task_handle.done():
                producer_task_handle.cancel()
                with suppress(asyncio.CancelledError):
                    await producer_task_handle

            with suppress(Exception):
                await loop.run_in_executor(None, task_queue.join)

        progress_queue.close()
        with suppress(Exception):
            progress_queue.join_thread()

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, producer_process.join, 5.0)
    if producer_process.is_alive():
        producer_process.terminate()
        await loop.run_in_executor(None, producer_process.join)

    for process in worker_processes:
        await loop.run_in_executor(None, process.join, 5.0)
        if process.is_alive():
            process.terminate()
            await loop.run_in_executor(None, process.join)

    # 4. Save phase
    console.print("\n[bold green]Execution Complete![/]")

    save_results(
        results=results,
        save_file=save_file,
        eval_spec=eval_spec,
        scorers=scorers,
        limit=limit,
        max_sandboxes=config.MAX_SANDBOXES,
        rerun_from=rerun_from,
        rerun_ids=rerun_ids,
        overwrite=overwrite,
        no_merge=no_merge,
        log_path=log_path,
    )

    event = asyncio.Event()
    await shutdown(event)

    if producer_errors:
        logger.error(
            "Producer encountered %d error(s) during execution: %s",
            len(producer_errors),
            "; ".join(producer_errors),
        )


@click.group(invoke_without_command=True)
@click.pass_context
@click.option(
    "--log-path",
    "-l",
    type=str,
    default=None,
    help="Full path to the log file",
)
@click.option(
    "--save-file",
    "-s",
    type=str,
    default="results.json",
    help="Anchor file path used to derive the `evaluation_result/` output directory",
)
@click.option(
    "--scorers",
    type=str,
    default=None,
    help=(
        "Explicit scorer configuration, e.g. `postcondition`, `defects4j`, "
        "or a comma-separated scorer list. If omitted, uses the built-in task map."
    ),
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=None,
    help="Limit the number of samples to process from the log. Processes all if not set.",
    show_default=True,
)
@click.option(
    "--max-sandboxes",
    "-m",
    type=int,
    default=None,
    help="Maximum number of concurrent sandboxes (overrides config).",
    show_default=True,
)
@click.option(
    "--rerun-from",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
    default=None,
    help="Path to a prior legacy results JSON or `evaluation_result/manifest.json`",
)
@click.option(
    "--rerun-ids",
    type=str,
    default=None,
    help="Comma-separated list of sample IDs to re-run (e.g., '1,5,10')",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="When re-running, overwrite the original file instead of creating a new one",
)
@click.option(
    "--no-merge",
    is_flag=True,
    default=False,
    help="When re-running, save only the current execution results without merging with previous results",
)
def main(
    ctx,
    log_path,
    save_file,
    scorers,
    limit,
    max_sandboxes,
    rerun_from,
    rerun_ids,
    overwrite,
    no_merge,
):
    """Run evaluation or convert legacy evaluation results."""
    if ctx.invoked_subcommand is not None:
        return

    if not log_path:
        raise click.UsageError("`--log-path` is required when running evaluation.")
    if not Path(log_path).is_file():
        raise click.UsageError(
            f"`--log-path` must point to an existing file: {log_path}"
        )

    console.print(Panel.fit("[bold blue]LLM Code Execution[/]", border_style="blue"))
    asyncio.run(
        run_executor(
            log_path=log_path,
            save_file=save_file,
            scorers=scorers,
            limit=limit,
            max_sandboxes=max_sandboxes,
            rerun_from=rerun_from,
            rerun_ids=rerun_ids,
            overwrite=overwrite,
            no_merge=no_merge,
        )
    )


@main.command("convert")
@click.argument(
    "source_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
)
@click.option(
    "--save-file",
    "-s",
    type=str,
    default=None,
    help="Optional anchor file path for the migrated `evaluation_result/` output",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite an existing target `evaluation_result/` store if it already exists",
)
def convert_command(source_path: str, save_file: str | None, overwrite: bool) -> None:
    """Convert a legacy monolithic evaluation JSON into `evaluation_result/`."""
    console.print(
        Panel.fit("[bold blue]Legacy Result Conversion[/]", border_style="blue")
    )
    store_root = convert_legacy_result(
        source_path=source_path,
        save_file=save_file,
        overwrite=overwrite,
    )
    console.print(f"\n[bold green]Converted results saved to: {store_root}[/]")


if __name__ == "__main__":
    main()
