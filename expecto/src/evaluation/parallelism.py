import os
from typing import Optional

MAX_AUTO_WORKERS = 64


def get_available_cpu_count() -> int:
    """Return the number of CPUs available to the current process."""
    try:
        if hasattr(os, "sched_getaffinity"):
            return max(1, min(len(os.sched_getaffinity(0)), MAX_AUTO_WORKERS))
    except (AttributeError, OSError):
        pass

    return max(1, min(os.cpu_count() or 1, MAX_AUTO_WORKERS))


def resolve_worker_count(
    num_samples: int,
    configured_limit: int,
    available_cpu_count: Optional[int] = None,
) -> int:
    """Resolve the worker count from sample count, config limit, and CPU availability."""
    cpu_limit = max(
        1,
        min(available_cpu_count or get_available_cpu_count(), MAX_AUTO_WORKERS),
    )
    worker_limit = min(max(1, configured_limit), cpu_limit)
    estimated_parallelism = max(1, num_samples)
    return min(worker_limit, estimated_parallelism)
