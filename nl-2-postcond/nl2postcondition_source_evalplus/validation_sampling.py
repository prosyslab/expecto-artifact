from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

VALIDATION_SAMPLING_ALL = "all"
VALIDATION_SAMPLING_DETERMINISTIC_CAP = "deterministic_cap"
VALIDATION_SAMPLING_MODES = (
    VALIDATION_SAMPLING_ALL,
    VALIDATION_SAMPLING_DETERMINISTIC_CAP,
)

T = TypeVar("T")


def _build_seed(
    *,
    benchmark: str,
    sample_id: str,
    phase: str,
    base_seed: int,
) -> int:
    payload = f"{base_seed}:{benchmark}:{sample_id}:{phase}"
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest(), 16)


def sample_sequence_for_validation(
    items: Sequence[T],
    *,
    benchmark: str,
    sample_id: str,
    phase: str,
    mode: str = VALIDATION_SAMPLING_ALL,
    cap: int | None = None,
    base_seed: int = 42,
) -> list[T]:
    copied_items = list(items)
    if mode != VALIDATION_SAMPLING_DETERMINISTIC_CAP or cap is None or cap < 1:
        return copied_items
    if len(copied_items) <= cap:
        return copied_items

    rng = random.Random(
        _build_seed(
            benchmark=benchmark,
            sample_id=sample_id,
            phase=phase,
            base_seed=base_seed,
        )
    )
    selected_indices = set(rng.sample(range(len(copied_items)), cap))
    return [
        item for index, item in enumerate(copied_items) if index in selected_indices
    ]


def sample_mapping_for_validation(
    items: Mapping[str, T],
    *,
    benchmark: str,
    sample_id: str,
    phase: str,
    mode: str = VALIDATION_SAMPLING_ALL,
    cap: int | None = None,
    base_seed: int = 42,
) -> dict[str, T]:
    copied_items = dict(items)
    if mode != VALIDATION_SAMPLING_DETERMINISTIC_CAP or cap is None or cap < 1:
        return copied_items
    if len(copied_items) <= cap:
        return copied_items

    keys = list(copied_items.keys())
    sampled_keys = sample_sequence_for_validation(
        keys,
        benchmark=benchmark,
        sample_id=sample_id,
        phase=phase,
        mode=mode,
        cap=cap,
        base_seed=base_seed,
    )
    sampled_key_set = set(sampled_keys)
    return {
        key: value for key, value in copied_items.items() if key in sampled_key_set
    }


def sample_io_pairs_payload(
    io_pairs: str | Mapping[str, Any] | None,
    *,
    benchmark: str,
    sample_id: str,
    phase: str,
    mode: str = VALIDATION_SAMPLING_ALL,
    cap: int | None = None,
    base_seed: int = 42,
) -> str | Mapping[str, Any] | None:
    if io_pairs is None:
        return None

    parsed = json.loads(io_pairs) if isinstance(io_pairs, str) else dict(io_pairs)
    inputs = list(parsed.get("inputs", []))
    outputs = list(parsed.get("outputs", []))
    sampled_pairs = sample_sequence_for_validation(
        list(zip(inputs, outputs)),
        benchmark=benchmark,
        sample_id=sample_id,
        phase=phase,
        mode=mode,
        cap=cap,
        base_seed=base_seed,
    )
    sampled_payload = {
        **parsed,
        "inputs": [input_value for input_value, _ in sampled_pairs],
        "outputs": [output_value for _, output_value in sampled_pairs],
    }
    if isinstance(io_pairs, str):
        return json.dumps(sampled_payload)
    return sampled_payload
