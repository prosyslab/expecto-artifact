import asyncio
import logging
import multiprocessing as mp
from typing import Any, Awaitable, Callable, Optional

from inspect_ai.log import EvalSample

from src.evaluation.config import sample_id_var
from src.evaluation.models import Sample as EvaluationSample
from src.evaluation.sandbox import Sandbox
from src.evaluation.scorer import defined_scorers, get_scorer

logger = logging.getLogger(__name__)


class WorkerScorer:
    """Resolve scorer configuration into a coroutine suitable for worker execution."""

    def __init__(self, scorers_spec: str):
        self._mode = "composite"
        self._scorers: list[Callable[[EvalSample, Sandbox], Awaitable[list[Any]]]] = []
        self._wrapped: Optional[Callable[[EvalSample], Awaitable[EvaluationSample]]] = None

        simplified = scorers_spec.strip()
        if simplified in {"postcondition", "defects4j"}:
            # Delegate to existing scorer implementation (manages its own sandbox lifecycle)
            self._mode = "wrapped"
            self._wrapped = get_scorer(simplified)
            return

        names = [name.strip() for name in scorers_spec.split(",") if name.strip()]
        if not names:
            raise ValueError("At least one scorer must be specified for worker execution.")

        missing = [name for name in names if name not in defined_scorers]
        if missing:
            raise ValueError(f"Unknown scorer(s): {', '.join(missing)}")

        self._scorers = [defined_scorers[name] for name in names]

    @property
    def requires_sandbox(self) -> bool:
        return self._mode == "composite"

    async def score(
        self,
        sample: EvalSample,
        sandbox: Optional[Sandbox],
    ) -> EvaluationSample:
        """Execute the configured scorers for the given sample."""
        sample.attachments.clear()
        sample_id_var.set(str(sample.id))

        if self._mode == "wrapped":
            if self._wrapped is None:
                raise RuntimeError("Wrapped scorer is not initialized.")
            return await self._wrapped(sample)  # type: ignore[return-value]

        if sandbox is None:
            raise RuntimeError("Sandbox required but not provided to worker scorer.")

        results = []
        for scorer_func in self._scorers:
            results.append(await scorer_func(sample, sandbox))

        if not results:
            return EvaluationSample(inspect_ai_sample=sample, scores=[])

        transposed = list(zip(*results))
        return EvaluationSample(
            inspect_ai_sample=sample,
            scores=transposed,
        )


async def _cancel_pending_tasks() -> None:
    """Cancel any pending asyncio tasks before shutting down the loop."""
    pending = [task for task in asyncio.all_tasks() if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def worker_main(
    task_queue: "mp.JoinableQueue[Optional[EvalSample]]",
    result_queue: "mp.Queue[Optional[EvaluationSample]]",
    scorers_spec: str,
) -> None:
    """
    Worker process entry point.

    Args:
        task_queue: Multiprocessing queue providing EvalSample tasks (None signals shutdown).
        result_queue: Queue to publish finished EvaluationSample objects (None signals worker exit).
        scorers_spec: Comma-separated scorer configuration string.
    """
    try:
        worker_scorer = WorkerScorer(scorers_spec)
    except Exception:
        logger.exception("Failed to initialize worker scorer.")
        result_queue.put(None)
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    sandbox: Optional[Sandbox] = Sandbox() if worker_scorer.requires_sandbox else None

    try:
        while True:
            task = task_queue.get()

            if task is None:
                task_queue.task_done()
                break

            try:
                result = loop.run_until_complete(worker_scorer.score(task, sandbox))
            except Exception:
                logger.exception("Error while scoring sample %s", getattr(task, "id", "<unknown>"))
                task.metadata.clear()
                result = EvaluationSample(
                    inspect_ai_sample=task,
                    scores=[],
                    execution_result=None,
                )

            result_queue.put(result)
            logger.info("Worker finished sample %s", getattr(task, "id", "<unknown>"))
            task_queue.task_done()
    finally:
        if sandbox is not None:
            try:
                loop.run_until_complete(sandbox.cleanup())
            except Exception:
                logger.exception("Error during sandbox cleanup in worker.")

        try:
            loop.run_until_complete(_cancel_pending_tasks())
        finally:
            loop.close()

        # Notify orchestrator that this worker has terminated.
        result_queue.put(None)