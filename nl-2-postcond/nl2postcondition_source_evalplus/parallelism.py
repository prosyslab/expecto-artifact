import os


def get_available_cpu_count() -> int:
    """Return the number of CPUs available to the current process."""
    try:
        if hasattr(os, "sched_getaffinity"):
            return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass

    return max(1, os.cpu_count() or 1)


def get_scaled_worker_count(scale: float = 1.0, maximum: int | None = None) -> int:
    """Return a CPU-derived worker count with an optional upper bound."""
    worker_count = max(1, int(get_available_cpu_count() * scale))
    if maximum is not None:
        worker_count = min(worker_count, max(1, maximum))
    return worker_count
