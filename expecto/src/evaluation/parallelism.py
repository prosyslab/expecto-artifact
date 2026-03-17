import os
from typing import Optional


def get_available_cpu_count() -> int:
    """Return the number of CPUs available to the current process."""
    try:
        if hasattr(os, "sched_getaffinity"):
            return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass

    return max(1, os.cpu_count() or 1)


def resolve_worker_count(
    num_samples: int,
    configured_limit: int,
    available_cpu_count: Optional[int] = None,
) -> int:
    """Resolve the worker count from sample count, config limit, and CPU availability."""
    cpu_limit = max(1, available_cpu_count or get_available_cpu_count())
    worker_limit = min(max(1, configured_limit), cpu_limit)
    estimated_parallelism = max(1, num_samples)
    return min(worker_limit, estimated_parallelism)
