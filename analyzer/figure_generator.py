import asyncio
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from collections.abc import Sequence
from itertools import cycle
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterable, Mapping, cast

import click
import numpy as np
import pandas as pd
from inspect_ai.log import read_eval_log_samples
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.container import BarContainer
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    DirectoryPath,
    Field,
    RootModel,
    ValidationError,
)


def _format_experiment_label(name: str) -> str:
    """Render experiment names with small caps for key systems."""

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0).lower()
        if token == "expecto":
            return r"\textsc{Expecto}"
        if token == "nl2postcond":
            return r"\textsc{NL2Postcond}"
        return match.group(0)

    return re.sub(r"\b(expecto|nl2postcond)\b", _replace, name, flags=re.IGNORECASE)


project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from utils import read_score_logs

from expecto.src.DSL.compiler import DSLCompiler
from expecto.src.evaluation.models import (
    EvaluationResult,
    Sample,
    Score,
    discover_evaluation_result_paths,
    load_evaluation_result,
)

plt.rcParams["text.usetex"] = True


# Colors for bar segments
COLOR_SOUND_AND_COMPLETE = "#4CAF50"  # green for correct and complete
COLOR_COMPLETE_ONLY = "#FFC107"  # amber for incomplete soundness
COLOR_SOUND_ONLY = "#2196F3"  # blue for sound only
COLOR_WRONG = "#F44336"  # red for incorrect results
COLOR_PURPLE = "#9C27B0"
COLOR_CYAN = "#00BCD4"
COLOR_PINK = "#E91E63"
COLOR_INDIGO = "#3F51B5"
COLOR_TEAL = "#009688"

# Unified color and marker configuration shared across all figures
PLOT_COLOR_CYCLE: tuple[str, ...] = (
    COLOR_SOUND_AND_COMPLETE,
    COLOR_SOUND_ONLY,
    COLOR_COMPLETE_ONLY,
    COLOR_PURPLE,
    COLOR_CYAN,
    COLOR_PINK,
    COLOR_INDIGO,
    COLOR_TEAL,
)
PLOT_MARKER_CYCLE: tuple[str, ...] = ("o", "^", "X", "v", "P", "*")

# Global font sizing
TITLE_FONT_SIZE = 28
LABEL_FONT_SIZE = 24
TICK_FONT_SIZE = 24
LEGEND_FONT_SIZE = 24

plt.rcParams.update(
    {
        "font.size": LABEL_FONT_SIZE,
        "axes.titlesize": TITLE_FONT_SIZE,
        "axes.labelsize": LABEL_FONT_SIZE,
        "xtick.labelsize": TICK_FONT_SIZE,
        "ytick.labelsize": TICK_FONT_SIZE,
        "legend.fontsize": LEGEND_FONT_SIZE,
    }
)

# Threshold values used for soundness/completeness analysis plots
THRESHOLD_VALUES: tuple[float, ...] = tuple(i / 10 for i in range(0, 11))


class AggregatedResult(BaseModel):
    benchmark: str
    exp_name: str
    sound_and_complete: int
    sound_only: int
    complete_only: int
    wrong: int


class _ExpectoCategoryCounts(BaseModel):
    sound_and_complete: int = 0
    sound_only: int = 0
    complete_only: int = 0
    wrong: int = 0


def _classify_expecto_sample(sample: Sample) -> str:
    flattened_scores = _flatten_scores(sample.scores)
    if not flattened_scores:
        return "wrong"

    first_score = flattened_scores[0]
    explanation = first_score.explanation
    if explanation:
        lowered = explanation.lower()
        if (
            "no codes" in lowered
            or "no code" in lowered
            or "jsondecodeerror" in lowered
        ):
            return "wrong"

    execution_results = first_score.execution_result
    if execution_results:
        stderr = execution_results[0].stderr
        if stderr and "Error Message:" in stderr:
            return "wrong"

    correctness_score: str | None = None
    soundness_score: str | None = None
    completeness_score: str | None = None

    for score in flattened_scores:
        scorer_name = score.scorer_name.lower()
        score_value = str(score.score) if score.score is not None else None
        if "soundness" in scorer_name:
            soundness_score = score_value
        elif "completeness" in scorer_name:
            completeness_score = score_value
        elif (
            "correctness" in scorer_name
            or "accuracy" in scorer_name
            or "verify" in scorer_name
        ):
            correctness_score = score_value

    if correctness_score == "C":
        return "sound_and_complete"
    if correctness_score == "I":
        return "wrong"
    if soundness_score is None or completeness_score is None:
        return "wrong"
    if soundness_score == "TO" and completeness_score == "TO":
        return "complete_only"
    if soundness_score == "C" and completeness_score == "C":
        return "sound_and_complete"
    if soundness_score == "C":
        return "sound_only"
    if completeness_score == "C":
        return "complete_only"
    return "wrong"


def _category_label(category: str) -> str:
    labels = {
        "sound_and_complete": "S&C",
        "sound_only": "S",
        "complete_only": "C",
        "wrong": "W",
        "SC": "S&C",
        "S": "S",
        "C": "C",
        "W": "W",
    }
    return labels.get(category, category)


def _normalize_exported_sample_id(benchmark: str, sample_id: Any) -> str:
    normalized = str(sample_id).strip()
    if benchmark == "humaneval_plus" and normalized.startswith("HumanEval/"):
        return normalized.split("/", 1)[1]
    return normalized


_APPS_QUESTION_BLOCK_PATTERN = re.compile(
    r"## Question:\s*(.*?)\s*(?:## Test Cases:|\Z)",
    flags=re.DOTALL,
)
_DEFECTS4J_METHOD_ID_SANITIZER = re.compile(r"[^0-9A-Za-z]+")


def _normalize_nl_description(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _extract_apps_question_block(text: str) -> str:
    match = _APPS_QUESTION_BLOCK_PATTERN.search(text)
    if match is None:
        return _normalize_nl_description(text)
    return _normalize_nl_description(match.group(1))


def _extract_expecto_nl_description(sample: Sample, benchmark: str) -> str:
    inspect_sample = sample.inspect_ai_sample
    metadata = getattr(inspect_sample, "metadata", None)
    if not isinstance(metadata, Mapping):
        return ""

    raw_input = metadata.get("input")
    if not isinstance(raw_input, str):
        return ""

    if benchmark == "apps":
        return _extract_apps_question_block(raw_input)
    if benchmark == "humaneval_plus":
        return _normalize_nl_description(raw_input)
    return ""


def _iter_json_array_records(path: Path) -> Iterable[dict[str, Any]]:
    try:
        import ijson
    except ImportError:
        payload = json.loads(path.read_text())
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    yield cast(dict[str, Any], item)
        return

    with path.open("rb") as handle:
        for item in ijson.items(handle, "item"):
            if isinstance(item, dict):
                yield cast(dict[str, Any], item)


def _resolve_evalplus_dataset_path(benchmark: str, run_dir: Path) -> Path:
    if benchmark == "apps":
        subset_path = run_dir / "_datasets" / "apps_subset.json"
        if subset_path.is_file():
            return subset_path
        return project_root / "datasets" / "apps.json"
    if benchmark == "humaneval_plus":
        return project_root / "datasets" / "human_eval_plus.json"
    raise click.ClickException(
        f"Unsupported EvalPlus-style benchmark for nl_description export: {benchmark}"
    )


def _load_evalplus_nl_descriptions(
    benchmark: str,
    sample_ids: Iterable[str],
    *,
    run_dir: Path,
) -> dict[str, str]:
    remaining = {str(sample_id) for sample_id in sample_ids if str(sample_id).strip()}
    if not remaining:
        return {}

    descriptions: dict[str, str] = {}
    dataset_path = _resolve_evalplus_dataset_path(benchmark, run_dir)
    for record in _iter_json_array_records(dataset_path):
        sample_id = _normalize_exported_sample_id(benchmark, record.get("problem_id", ""))
        if sample_id not in remaining:
            continue
        descriptions[sample_id] = _normalize_nl_description(record.get("prompt", ""))
        remaining.remove(sample_id)
        if not remaining:
            break

    return descriptions


def _sanitize_defects4j_method_identifier(text: str) -> str:
    sanitized = _DEFECTS4J_METHOD_ID_SANITIZER.sub("_", text).strip("_")
    return sanitized or "method"


def _build_defects4j_sample_id(
    project: str,
    bug_id: str,
    file_path: str,
    signature: str,
    ids_count: dict[str, int],
) -> str:
    method_token = _sanitize_defects4j_method_identifier(f"{file_path}_{signature}")
    base_id = f"{project}_{bug_id}_{method_token}"
    ids_count[base_id] = ids_count.get(base_id, 0) + 1
    if ids_count[base_id] == 1:
        return base_id
    return f"{base_id}_{ids_count[base_id]}"


def _extract_defects4j_javadoc_description(javadoc: Any) -> str:
    if not isinstance(javadoc, Mapping):
        return ""
    return _normalize_nl_description(javadoc.get("description"))


def _load_defects4j_nl2_run_descriptions(
    run_dir: Path,
    sample_ids: Iterable[str],
) -> dict[str, str]:
    remaining = {str(sample_id) for sample_id in sample_ids if str(sample_id).strip()}
    if not remaining:
        return {}

    descriptions: dict[str, str] = {}
    jsonl_paths = sorted(
        path
        for path in run_dir.glob("*.jsonl")
        if path.is_file() and not path.name.endswith(".final.jsonl")
    )
    for jsonl_path in jsonl_paths:
        with jsonl_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                row = json.loads(stripped)
                sample_id = _normalize_exported_sample_id(
                    "defects4j", row.get("id", row.get("task_id", ""))
                )
                if sample_id not in remaining:
                    continue
                descriptions[sample_id] = _extract_defects4j_javadoc_description(
                    row.get("javadoc")
                )
                remaining.remove(sample_id)
                if not remaining:
                    return descriptions

    return descriptions


def _load_defects4j_dataset_descriptions(
    sample_ids: Iterable[str],
) -> dict[str, str]:
    remaining = {str(sample_id) for sample_id in sample_ids if str(sample_id).strip()}
    if not remaining:
        return {}

    descriptions: dict[str, str] = {}
    dataset_path = project_root / "datasets" / "defects4j.jsonl"
    ids_count: dict[str, int] = {}
    with dataset_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            bug = json.loads(stripped)
            if not isinstance(bug, dict):
                continue

            project = str(bug.get("project", ""))
            bug_id = str(bug.get("bug_id", ""))
            for method_dump in bug.get("method_dumps", []):
                if not isinstance(method_dump, dict):
                    continue
                method_info = method_dump.get("method_info", {})
                if not isinstance(method_info, dict):
                    continue
                sample_id = _build_defects4j_sample_id(
                    project,
                    bug_id,
                    str(method_info.get("file", "")),
                    str(method_info.get("signature", "")),
                    ids_count,
                )
                if sample_id not in remaining:
                    continue
                descriptions[sample_id] = _extract_defects4j_javadoc_description(
                    method_info.get("javadoc")
                )
                remaining.remove(sample_id)
                if not remaining:
                    return descriptions

    return descriptions


def _attach_nl_descriptions(
    rows: list[dict[str, Any]],
    *,
    benchmark: str,
    variant: str,
    run_dir: Path,
) -> None:
    missing_ids = [
        row["id"]
        for row in rows
        if isinstance(row.get("id"), str) and not row.get("nl_description")
    ]
    if not missing_ids:
        return

    descriptions: dict[str, str] = {}
    if benchmark in {"apps", "humaneval_plus"}:
        descriptions.update(
            _load_evalplus_nl_descriptions(benchmark, missing_ids, run_dir=run_dir)
        )
    elif benchmark == "defects4j":
        if variant.startswith("nl2_"):
            descriptions.update(_load_defects4j_nl2_run_descriptions(run_dir, missing_ids))
            still_missing = [sample_id for sample_id in missing_ids if sample_id not in descriptions]
        else:
            still_missing = missing_ids
        descriptions.update(_load_defects4j_dataset_descriptions(still_missing))

    for row in rows:
        if row.get("nl_description"):
            continue
        row["nl_description"] = descriptions.get(str(row.get("id", "")), "")


class LLMCallRow(BaseModel):
    benchmark: str
    exp_name: str
    avg_llm_calls: float
    sample_count: int


class BenchmarkRunDirs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    mono: DirectoryPath | None = None
    topdown: DirectoryPath | None = None
    ts: DirectoryPath | None = None
    without_tc: DirectoryPath | None = Field(
        default=None,
        validation_alias=AliasChoices("without_tc", "ts_no_tc"),
    )
    nl2_postcond_base: DirectoryPath | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "nl-2-postcond-base",
            "nl2_postcond_base",
        ),
    )
    nl2_postcond_simple: DirectoryPath | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "nl-2-postcond-simple",
            "nl2_postcond_simple",
        ),
    )

    def iter_expecto_runs(self) -> list[tuple[str, Path]]:
        runs: list[tuple[str, Path | None]] = [
            ("mono", self.mono),
            ("topdown", self.topdown),
            ("ts", self.ts),
            ("without_tc", self.without_tc),
        ]
        return [(name, path) for name, path in runs if path is not None]


class FigureRunConfig(RootModel[dict[str, BenchmarkRunDirs]]):
    def items(self) -> Iterable[tuple[str, BenchmarkRunDirs]]:
        return self.root.items()


class Defects4JBaselineRunDirs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expecto: DirectoryPath
    nl2_postcond_base: DirectoryPath = Field(
        validation_alias=AliasChoices(
            "nl-2-postcond-base",
            "nl2_postcond_base",
        ),
    )
    nl2_postcond_simple: DirectoryPath = Field(
        validation_alias=AliasChoices(
            "nl-2-postcond-simple",
            "nl2_postcond_simple",
        ),
    )
    benchmark: str = "Defects4J"


EXPECTO_RUN_LABELS: dict[str, str] = {
    "mono": "Mono",
    "topdown": "TopDown",
    "ts": "TreeSearch",
    "without_tc": "without_tc",
}
BASELINE_NL2_RUNS: tuple[tuple[str, str], ...] = (
    ("nl2_postcond_base", "Base"),
    ("nl2_postcond_simple", "Simple"),
)


def _init_threshold_buckets(thresholds: Iterable[float]) -> dict[float, dict[str, int]]:
    """Create zero-initialised buckets for each threshold."""

    return {
        tau: {
            "sound_and_complete": 0,
            "sound_only": 0,
            "complete_only": 0,
            "wrong": 0,
        }
        for tau in thresholds
    }


def _parse_json_explanation(explanation: str | None) -> dict[str, Any] | None:
    """Parse a score explanation into a dictionary when possible."""

    if not explanation:
        return None
    try:
        data = json.loads(explanation)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _get_numeric(payload: dict[str, Any], key: str) -> float:
    """Coerce payload value to float, defaulting to 0.0 on failure."""

    value = payload.get(key, 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _flatten_scores(scores: Sequence[Score] | Sequence[Sequence[Score]]) -> list[Score]:
    """Flatten nested score sequences emitted by Expecto evaluation logs."""

    flattened: list[Score] = []
    for entry in scores:
        if isinstance(entry, Score):
            flattened.append(entry)
        elif isinstance(entry, Sequence):
            for inner in entry:
                if isinstance(inner, Score):
                    flattened.append(inner)
    return flattened


def _merge_threshold_counts(
    dest: dict[float, dict[str, int]], src: dict[float, dict[str, int]]
) -> None:
    """Accumulate per-threshold counts from src into dest."""

    for tau, metrics in src.items():
        bucket = dest.setdefault(
            tau,
            {
                "sound_and_complete": 0,
                "sound_only": 0,
                "complete_only": 0,
                "wrong": 0,
            },
        )
        bucket["sound_and_complete"] += metrics.get("sound_and_complete", 0)
        bucket["sound_only"] += metrics.get("sound_only", 0)
        bucket["complete_only"] += metrics.get("complete_only", 0)
        bucket["wrong"] += metrics.get("wrong", 0)


def _compute_expecto_threshold_counts(
    results: Sequence[Sample], thresholds: Iterable[float]
) -> dict[float, dict[str, int]]:
    """Compute sound-and-complete and sound-only counts for Expecto logs."""

    counts = _init_threshold_buckets(thresholds)
    for result in results:
        flattened = _flatten_scores(result.scores)
        soundness_payload: dict[str, Any] | None = None
        completeness_payload: dict[str, Any] | None = None

        for score in flattened:
            name = score.scorer_name.lower()
            if "soundness" in name and soundness_payload is None:
                soundness_payload = _parse_json_explanation(score.explanation)
            elif "completeness" in name and completeness_payload is None:
                completeness_payload = _parse_json_explanation(score.explanation)
            if soundness_payload and completeness_payload:
                break

        if soundness_payload is None:
            soundness_payload = {
                "C": 0,
                "I": 0,
            }
        if completeness_payload is None:
            completeness_payload = {
                "C": 0,
                "I": 0,
            }

        c_value = _get_numeric(soundness_payload, "C")
        i_value = _get_numeric(soundness_payload, "I")
        comp_c_value = _get_numeric(completeness_payload, "C")
        comp_i_value = _get_numeric(completeness_payload, "I")

        for tau in thresholds:
            is_sound = c_value >= tau * (i_value + c_value) and c_value > 0
            is_complete = comp_c_value > 0 and comp_i_value == 0

            if is_sound and is_complete:
                counts[tau]["sound_and_complete"] += 1
            elif is_sound:
                counts[tau]["sound_only"] += 1
            elif is_complete:
                counts[tau]["complete_only"] += 1
            elif not is_sound and not is_complete:
                counts[tau]["wrong"] += 1

    return counts


def _compute_nl2_threshold_counts(
    rows: Sequence[dict[str, Any]], thresholds: Iterable[float]
) -> dict[float, dict[str, int]]:
    """Compute sound-and-complete and sound-only counts for NL2Postcond payloads."""

    counts = _init_threshold_buckets(thresholds)
    for row in rows:
        true_mutated = _get_numeric(row, "true_cnt_mutated")
        false_mutated = _get_numeric(row, "false_cnt_mutated")
        true_correct = _get_numeric(row, "true_cnt_correct")
        false_correct = _get_numeric(row, "false_cnt_correct")
        # Older NL2Postcond outputs tracked exceptions separately. Newer outputs
        # fold per-test exceptions into false counts. Treat both formats
        # consistently by absorbing legacy error counters into false totals.
        false_mutated += _get_numeric(row, "error_cnt_mutated")
        false_correct += _get_numeric(row, "error_cnt_correct")

        for tau in thresholds:
            total_mutated = true_mutated + false_mutated
            is_sound = (
                total_mutated > 0
                and false_mutated >= tau * total_mutated
                and false_mutated > 0
            )
            is_complete = true_correct > 0 and false_correct == 0

            if is_sound and is_complete:
                counts[tau]["sound_and_complete"] += 1
            elif is_sound:
                counts[tau]["sound_only"] += 1
            elif is_complete:
                counts[tau]["complete_only"] += 1
            else:
                counts[tau]["wrong"] += 1

    return counts


def _prepare_counts_for_plot(
    counts: dict[float, dict[str, int]], thresholds: Iterable[float]
) -> dict[str, list[int]]:
    """Convert threshold counts into lists ordered by thresholds."""

    ordered_thresholds = list(thresholds)
    return {
        "sound_and_complete": [
            counts[t]["sound_and_complete"] for t in ordered_thresholds
        ],
        "sound_only": [counts[t]["sound_only"] for t in ordered_thresholds],
        "wrong": [counts[t]["wrong"] for t in ordered_thresholds],
    }


def draw_threshold_plot(
    thresholds: Iterable[float],
    counts_by_benchmark: dict[str, dict[str, dict[str, list[int]]]],
    output_file: str,
) -> None:
    """Draw threshold figures per benchmark with vertical panels."""

    if not counts_by_benchmark:
        return

    threshold_values = list(thresholds)
    ordered_benchmarks = sorted(counts_by_benchmark.keys(), key=_benchmark_sort_key)

    experiment_sequence: list[str] = []
    seen_experiments: set[str] = set()
    for benchmark in ordered_benchmarks:
        for exp_name in counts_by_benchmark[benchmark].keys():
            if exp_name not in seen_experiments:
                experiment_sequence.append(exp_name)
                seen_experiments.add(exp_name)

    if not experiment_sequence:
        return

    color_cycle = cycle([COLOR_COMPLETE_ONLY, COLOR_WRONG, COLOR_SOUND_AND_COMPLETE])
    marker_cycle = cycle(PLOT_MARKER_CYCLE)
    style_map: dict[str, tuple[str, str]] = {}
    for exp_name in experiment_sequence:
        style_map[exp_name] = (next(color_cycle), next(marker_cycle))
    for exp_name, (color, marker) in list(style_map.items()):
        if "base" in exp_name.lower():
            style_map[exp_name] = (COLOR_COMPLETE_ONLY, marker)
        elif "simple" in exp_name.lower():
            style_map[exp_name] = (COLOR_WRONG, marker)
        elif "expecto" in exp_name.lower():
            style_map[exp_name] = (COLOR_SOUND_AND_COMPLETE, marker)

    legend_order = sorted(
        experiment_sequence,
        key=lambda name: (0 if "expecto" in name.lower() else 1, name),
    )

    output_path = Path(output_file)

    legend_handles: list[Line2D] = []
    legend_labels: list[str] = []

    if len(ordered_benchmarks) == 2:
        if output_path.suffix:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            figure_path = output_path
        else:
            output_path.mkdir(parents=True, exist_ok=True)
            base_name = (
                output_path.name if output_path.name not in {"", "."} else "thresholds"
            )
            figure_path = output_path / f"{base_name}.pdf"

        fig, axes = plt.subplots(
            2,
            2,
            figsize=(18, 10),
            sharex=True,
            constrained_layout=False,
        )
        fig.subplots_adjust(wspace=0.05, hspace=0.0, top=0.3, bottom=0.1)

        for ax in axes.flatten():
            ax.tick_params(axis="both", labelsize=TICK_FONT_SIZE)

        legend_handle_map: dict[str, Line2D] = {}

        x_tick_labels = [f"{int(round(value * 100))}%" for value in threshold_values]

        for col, benchmark in enumerate(ordered_benchmarks):
            sc_ax = axes[0, col]
            wrong_ax = axes[1, col]

            local_max_sc = 0.0
            local_max_wrong = 0.0

            counts_by_experiment = counts_by_benchmark[benchmark]

            for exp_name in experiment_sequence:
                exp_counts = counts_by_experiment.get(exp_name)
                if not exp_counts:
                    continue

                color, marker = style_map[exp_name]
                sac_values = exp_counts.get("sound_and_complete", [])
                if sac_values:
                    local_max_sc = max(local_max_sc, max(sac_values))
                line_sc = sc_ax.plot(
                    threshold_values,
                    sac_values,
                    color=color,
                    marker=marker,
                    linestyle="-",
                    linewidth=2.5,
                    markersize=14,
                )[0]
                legend_handle_map.setdefault(exp_name, line_sc)

                wrong_values = exp_counts.get("wrong") or [0] * len(threshold_values)
                if wrong_values:
                    local_max_wrong = max(local_max_wrong, max(wrong_values))
                wrong_ax.plot(
                    threshold_values,
                    wrong_values,
                    color=color,
                    marker=marker,
                    linestyle="-",
                    linewidth=2.5,
                    markersize=14,
                )

            sc_ax.set_title(_format_benchmark_label(benchmark))
            sc_ax.grid(True, linestyle=":", linewidth=0.9)
            wrong_ax.grid(True, linestyle=":", linewidth=0.9)

            sc_ax.set_xticks(threshold_values)
            sc_ax.set_xticklabels(x_tick_labels)
            sc_ax.tick_params(labelbottom=True)
            sc_ax.set_xlabel(r"$X$(\%)")
            wrong_ax.set_xticks(threshold_values)
            wrong_ax.set_xticklabels(x_tick_labels)
            wrong_ax.set_xlabel(r"$X$(\%)")

            sc_ax.set_ylabel(r"S\&C")
            wrong_ax.set_ylabel("W")

            if local_max_sc > 0:
                sc_ax.set_ylim(0, max(1.0, local_max_sc) * 1.1)
            else:
                sc_ax.set_ylim(0, 1.0)
            if local_max_wrong > 0:
                wrong_ax.set_ylim(0, max(1.0, local_max_wrong) * 1.1)
            else:
                wrong_ax.set_ylim(0, 1.0)

        for exp_name in legend_order:
            handle = legend_handle_map.get(exp_name)
            if handle is None:
                continue
            legend_handles.append(handle)
            legend_labels.append(_format_experiment_label(exp_name))

        if legend_handles:
            fig.legend(
                legend_handles,
                legend_labels,
                loc="upper center",
                bbox_to_anchor=(0.5, 0.94),
                ncol=min(3, len(legend_handles)),
                frameon=True,
            )

        fig.tight_layout(rect=(0, 0, 1, 0.88))
        fig.savefig(figure_path, bbox_inches="tight")
        plt.close(fig)
        return

    if output_path.suffix:
        base_stem = output_path.stem
        suffix = output_path.suffix
        output_dir = output_path.parent
    else:
        base_stem = (
            output_path.name if output_path.name not in {"", "."} else "thresholds"
        )
        suffix = ".pdf"
        output_dir = output_path

    output_dir.mkdir(parents=True, exist_ok=True)

    for benchmark in ordered_benchmarks:
        fig, (left_ax, right_ax) = plt.subplots(
            2, 1, figsize=(12, 8), sharex=True, constrained_layout=False
        )
        fig.subplots_adjust(hspace=0.12)

        counts_by_experiment = counts_by_benchmark[benchmark]
        local_max_sc = 0.0
        local_max_wrong = 0.0
        local_handles_map: dict[str, Line2D] = {}

        for exp_name in counts_by_experiment.keys():
            color, marker = style_map[exp_name]
            sac_values = counts_by_experiment[exp_name].get("sound_and_complete", [])
            if sac_values:
                local_max_sc = max(local_max_sc, max(sac_values))
            line_sc = left_ax.plot(
                threshold_values,
                sac_values,
                label=exp_name,
                color=color,
                marker=marker,
                linestyle="-",
                linewidth=3.0,
                markersize=11,
            )[0]
            local_handles_map[exp_name] = line_sc
            wrong_values = counts_by_experiment[exp_name].get("wrong")
            if not wrong_values:
                wrong_values = [0] * len(threshold_values)
            else:
                local_max_wrong = max(local_max_wrong, max(wrong_values))
            right_ax.plot(
                threshold_values,
                wrong_values,
                color=color,
                marker=marker,
                linestyle="-",
                linewidth=3.0,
                markersize=11,
            )

        x_tick_labels = [f"{int(round(value * 100))}%" for value in threshold_values]
        for ax in (left_ax, right_ax):
            ax.set_xticks(threshold_values)
            ax.set_xticklabels(x_tick_labels)
            ax.set_xlabel(r"$X(\%)$")
            ax.grid(True, linestyle=":", linewidth=0.9)
            ax.tick_params(axis="both", labelsize=TICK_FONT_SIZE)

        left_ax.set_ylabel(r"S\&C")
        right_ax.set_ylabel("W")

        if local_max_sc > 0:
            left_ax.set_ylim(0, max(1.0, local_max_sc) * 1.15)
        else:
            left_ax.set_ylim(0, 1.0)
        if local_max_wrong > 0:
            right_ax.set_ylim(0, max(1.0, local_max_wrong) * 1.15)
        else:
            right_ax.set_ylim(0, 1.0)

        bench_label = _format_benchmark_label(benchmark)
        for exp_name in legend_order:
            handle = local_handles_map.get(exp_name)
            if not handle:
                continue
            legend_handles.append(handle)
            legend_labels.append(_format_experiment_label(exp_name))

        should_draw_legend = not bench_label.lower().startswith("humaneval")
        if legend_handles and should_draw_legend:
            fig.legend(
                legend_handles,
                legend_labels,
                loc="upper center",
                bbox_to_anchor=(0.5, 1.02),
                ncol=min(3, len(legend_handles)),
                frameon=True,
            )

        fig.tight_layout(rect=(0, 0, 1, 0.92))

        if len(ordered_benchmarks) == 1 and output_path.suffix:
            figure_path = output_path
        else:
            safe_name = re.sub(r"[^0-9A-Za-z]+", "_", benchmark.lower()).strip("_")
            if not safe_name:
                safe_name = "benchmark"
            figure_path = output_dir / f"{base_stem}.{safe_name}{suffix}"

        fig.savefig(figure_path, bbox_inches="tight")
        plt.close(fig)


def get_dataframe(inputs: list[AggregatedResult]) -> pd.DataFrame:
    return pd.DataFrame([i.model_dump() for i in inputs])


def _build_table_pdf_document(table_tex: str) -> str:
    """Wrap a generated LaTeX table in a standalone document for PDF export."""

    return "\n".join(
        [
            r"\documentclass{article}",
            r"\usepackage[margin=0.4in]{geometry}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage{booktabs}",
            r"\usepackage{multirow}",
            r"\usepackage{array}",
            r"\usepackage{textcomp}",
            r"\pagestyle{empty}",
            r"\setlength{\parindent}{0pt}",
            r"\setlength{\textfloatsep}{8pt}",
            r"\setlength{\floatsep}{8pt}",
            r"\setlength{\intextsep}{8pt}",
            r"\newcolumntype{C}{>{\centering\arraybackslash}p{1.8cm}}",
            r"\newcommand{\tool}{\textsc{Expecto}}",
            r"\newcommand{\nltopostcond}{\textsc{NL2Postcond}}",
            r"\newcommand{\apps}{\textsc{APPS}}",
            r"\newcommand{\humanevalplus}{\textsc{HumanEval+}}",
            r"\begin{document}",
            r"\thispagestyle{empty}",
            table_tex,
            r"\end{document}",
        ]
    )


def _compile_table_pdf(table_tex: str, output_pdf_path: Path) -> None:
    """Compile a generated LaTeX table into a PDF artifact."""

    latexmk = shutil.which("latexmk")
    pdflatex = shutil.which("pdflatex")
    if latexmk is None and pdflatex is None:
        raise click.ClickException(
            "Could not find `latexmk` or `pdflatex` to compile table PDFs."
        )

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="expecto-table-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        source_path = temp_dir_path / "table_wrapper.tex"
        source_path.write_text(_build_table_pdf_document(table_tex))

        if latexmk is not None:
            command = [
                latexmk,
                "-pdf",
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={temp_dir_path}",
                source_path.name,
            ]
        else:
            command = [
                cast(str, pdflatex),
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={temp_dir_path}",
                source_path.name,
            ]

        try:
            subprocess.run(
                command,
                cwd=temp_dir_path,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            combined_output = "\n".join(
                part for part in (exc.stdout, exc.stderr) if part
            )
            excerpt = "\n".join(combined_output.splitlines()[-25:])
            message = f"Failed to compile LaTeX table PDF `{output_pdf_path.name}`."
            if excerpt:
                message = f"{message}\n{excerpt}"
            raise click.ClickException(message) from exc

        built_pdf_path = temp_dir_path / "table_wrapper.pdf"
        if not built_pdf_path.exists():
            raise click.ClickException(
                f"LaTeX compilation did not produce `{output_pdf_path.name}`."
            )
        shutil.copyfile(built_pdf_path, output_pdf_path)


def _write_table_outputs(table_tex: str, tex_path: Path) -> Path:
    """Write both .tex and compiled .pdf artifacts for a generated table."""

    tex_path.write_text(table_tex)
    pdf_path = tex_path.with_suffix(".pdf")
    _compile_table_pdf(table_tex, pdf_path)
    return pdf_path


def get_tex_table(inputs: list[AggregatedResult], caption: str, label: str) -> str:
    df = get_dataframe(inputs)

    # Group by benchmark and exp_name
    benchmarks = sorted(df["benchmark"].unique())
    exp_names = sorted(df["exp_name"].unique())

    # Metric names and their display labels
    metrics = [
        ("sound_and_complete", "S\\&C"),
        ("sound_only", "S"),
        ("complete_only", "C"),
        ("wrong", "W"),
    ]

    # Build table header
    num_cols = len(exp_names)
    col_format = "l" + "C" * (num_cols + 1)

    lines = []
    lines.append("\\begin{table}[t]")
    lines.append("\\centering")
    lines.append(f"\\caption{{{caption}}}")
    lines.append(f"\\label{{{label}}}")
    lines.append(f"\\begin{{tabular}}{{{col_format}}}")
    lines.append("\\toprule")

    # Header row
    exp_headers = " & ".join(
        [
            name.replace("Expecto", "\\textsc{Expecto}")
            .replace("NL2Postcond", "\\textsc{NL2Postcond}")
            .replace("(", "(\\textbf{")
            .replace(")", "})")
            for name in exp_names
        ]
    )
    lines.append(f"\\textbf{{Benchmark}} & \\textbf{{Result}} & {exp_headers} \\\\")
    lines.append("\\midrule")

    # Data rows
    for i, benchmark in enumerate(benchmarks):
        benchmark_data = df[df["benchmark"] == benchmark]
        num_metrics = len(metrics)

        # Format benchmark name
        bench_name = benchmark.replace("APPS", "\\apps{}")
        bench_name = bench_name.replace("humanevalplus", "\\humanevalplus{}")
        bench_name = bench_name.replace("HumanEval+", "\\humanevalplus{}")

        for j, (metric_key, metric_label) in enumerate(metrics):
            if j == 0:
                # First metric row includes benchmark name with multirow
                row_parts = [
                    f"\\multirow{{{num_metrics}}}{{*}}{{{bench_name}}}",
                    metric_label,
                ]
            else:
                # Subsequent rows have empty first column
                row_parts = ["", metric_label]

            # Add values for each experiment
            for exp_name in exp_names:
                exp_data = benchmark_data[benchmark_data["exp_name"] == exp_name]
                values_series = cast(pd.Series, exp_data[metric_key])
                values = values_series.tolist()
                if values:
                    row_parts.append(str(int(values[0])))
                else:
                    row_parts.append("-")

            lines.append(" & ".join(row_parts) + " \\\\")

        # Add midrule between benchmarks (but not after the last one)
        if i < len(benchmarks) - 1:
            lines.append("\\midrule")

    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    lines.append("\\end{table}")

    return "\n".join(lines)


def parse_nl2_postcond_data(
    data: Sequence[dict[str, Any]], benchmark: str, exp_name: str = "NL2Postcond"
) -> AggregatedResult:
    sound_and_complete = 0
    sound_only = 0
    complete_only = 0
    wrong = 0
    for row in data:
        if row["is_complete"] and row["is_sound"]:
            sound_and_complete += 1
        elif row["is_complete"]:
            complete_only += 1
        elif row["is_sound"]:
            sound_only += 1
        else:
            wrong += 1
    return AggregatedResult(
        exp_name=exp_name,
        benchmark=benchmark,
        sound_and_complete=sound_and_complete,
        sound_only=sound_only,
        complete_only=complete_only,
        wrong=wrong,
    )


def parse_expecto_data(
    data: EvaluationResult, benchmark: str, exp_name: str = "Expecto"
) -> AggregatedResult:
    counts = _ExpectoCategoryCounts()
    for result in data.results:
        category = _classify_expecto_sample(result)
        if category == "sound_and_complete":
            counts.sound_and_complete += 1
        elif category == "sound_only":
            counts.sound_only += 1
        elif category == "complete_only":
            counts.complete_only += 1
        else:
            counts.wrong += 1

    return AggregatedResult(
        exp_name=exp_name,
        benchmark=benchmark,
        sound_and_complete=counts.sound_and_complete,
        sound_only=counts.sound_only,
        complete_only=counts.complete_only,
        wrong=counts.wrong,
    )


def parse_defects4j_nl2_data(
    aggregate_payload: Mapping[str, Any],
    benchmark: str,
    exp_name: str,
) -> AggregatedResult:
    category_counts = aggregate_payload.get("category_counts", {})
    if not isinstance(category_counts, Mapping):
        raise click.ClickException(
            "Defects4J aggregate payload must include a 'category_counts' object"
        )

    def _get_count(key: str) -> int:
        value = category_counts.get(key, 0)
        if not isinstance(value, (int, float)):
            return 0
        return int(value)

    return AggregatedResult(
        exp_name=exp_name,
        benchmark=benchmark,
        sound_and_complete=_get_count("SC"),
        sound_only=_get_count("S"),
        complete_only=_get_count("C"),
        wrong=_get_count("W"),
    )


def find_files(p: Path, filename: str) -> list[Path]:
    return list(p.rglob(f"{filename}"))


def _load_figure_run_config(config_path: str | Path) -> FigureRunConfig:
    config_file = Path(config_path)
    try:
        raw_config = json.loads(config_file.read_text())
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"Failed to parse config file {config_file}: {exc}"
        ) from exc

    try:
        return FigureRunConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise click.ClickException(
            f"Invalid figure config in {config_file}:\n{exc}"
        ) from exc


def _load_defects4j_baseline_config(
    config_path: str | Path,
) -> Defects4JBaselineRunDirs:
    config_file = Path(config_path)
    try:
        raw_config = json.loads(config_file.read_text())
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"Failed to parse JSON config {config_file}: {exc}"
        ) from exc

    try:
        return Defects4JBaselineRunDirs.model_validate(raw_config)
    except ValidationError as exc:
        raise click.ClickException(
            f"Invalid Defects4J config in {config_file}:\n{exc}"
        ) from exc


def _require_run_dir(run_dir: Path | None, benchmark: str, field_name: str) -> Path:
    if run_dir is None:
        raise click.ClickException(
            f"Benchmark '{benchmark}' is missing required run directory '{field_name}'"
        )
    return run_dir


def _require_expecto_run(
    benchmark_config: BenchmarkRunDirs,
    benchmark: str,
    field_name: str,
) -> Path:
    return _require_run_dir(
        getattr(benchmark_config, field_name), benchmark, field_name
    )


def _get_expecto_run_label(run_key: str) -> str:
    return EXPECTO_RUN_LABELS.get(run_key, run_key)


def collect_nl2_postcond_data(
    run_dir: Path,
) -> list[tuple[list[dict[str, Any]], dict[str, Any]]]:
    eval_files = sorted(find_files(run_dir, "evaluation_results.json"))
    agg_files = sorted(find_files(run_dir, "aggregated_result.json"))
    eval_files = [file for file in eval_files if "ref" not in str(file).lower()]
    agg_files = [file for file in agg_files if "ref" not in str(file).lower()]
    sorted_eval_files = sorted(eval_files, key=lambda x: str(x))
    sorted_agg_files = sorted(agg_files, key=lambda x: str(x))

    if not sorted_eval_files or not sorted_agg_files:
        raise click.ClickException(
            f"No NL2Postcond evaluation artifacts found under {run_dir}"
        )
    if len(sorted_eval_files) != len(sorted_agg_files):
        raise click.ClickException(
            "Mismatched NL2Postcond artifacts under "
            f"{run_dir}: found {len(sorted_eval_files)} evaluation_results.json files "
            f"but {len(sorted_agg_files)} aggregated_result.json files"
        )

    return [
        (
            cast(list[dict[str, Any]], json.loads(eval_file.read_text())),
            cast(dict[str, Any], json.loads(agg_file.read_text())),
        )
        for eval_file, agg_file in zip(sorted_eval_files, sorted_agg_files)
    ]


def collect_defects4j_nl2_data(run_dir: Path) -> dict[str, Any]:
    aggregate_files = sorted(find_files(run_dir, "aggregated.json"))
    if not aggregate_files:
        raise click.ClickException(
            f"No Defects4J NL2Postcond aggregate found under {run_dir}"
        )
    if len(aggregate_files) != 1:
        raise click.ClickException(
            f"Expected exactly one Defects4J aggregate under {run_dir}, "
            f"but found {len(aggregate_files)}"
        )
    return cast(dict[str, Any], json.loads(aggregate_files[0].read_text()))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                rows.append(cast(dict[str, Any], payload))
    return rows


def collect_defects4j_nl2_rows(run_dir: Path) -> list[dict[str, Any]]:
    final_jsonl_paths = sorted((run_dir / "validation").glob("*.final.jsonl"))
    if not final_jsonl_paths:
        raise click.ClickException(
            f"No Defects4J NL2Postcond final JSONL outputs found under {run_dir}"
        )

    rows: list[dict[str, Any]] = []
    for final_jsonl_path in final_jsonl_paths:
        rows.extend(_read_jsonl(final_jsonl_path))
    return rows


def _extract_expecto_completion_payload(sample: Sample) -> Any:
    inspect_sample = sample.inspect_ai_sample
    output = getattr(inspect_sample, "output", None)
    completion = getattr(output, "completion", None) if output is not None else None
    if isinstance(completion, str):
        stripped = completion.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
    return completion


def _normalize_sample_result_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    return "\n".join(line.rstrip() for line in normalized.splitlines())


def _compact_for_format_compare(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _format_sample_specification(specification: str, *, is_expecto: bool) -> str:
    normalized = _normalize_sample_result_text(specification)
    if not normalized or not is_expecto:
        return normalized

    try:
        compiler = DSLCompiler()
        ast = compiler.parse(normalized)
        round_tripped = compiler.unparse(ast, pretty_print=False).strip()
        if len(_compact_for_format_compare(round_tripped)) < len(
            _compact_for_format_compare(normalized)
        ):
            return normalized
        return compiler.unparse(ast, pretty_print=True).strip()
    except Exception:
        return normalized


def _extract_expecto_specification(sample: Sample) -> str:
    payload = _extract_expecto_completion_payload(sample)
    if isinstance(payload, Mapping):
        generated_codes = payload.get("generated_codes")
        if isinstance(generated_codes, Sequence) and not isinstance(
            generated_codes, (str, bytes, bytearray)
        ):
            codes = [str(code).strip() for code in generated_codes if str(code).strip()]
            if codes:
                return _format_sample_specification(
                    "\n\n".join(codes),
                    is_expecto=True,
                )
    if isinstance(payload, str):
        return _format_sample_specification(payload, is_expecto=True)
    return ""


def _sample_id_from_expecto_sample(sample: Sample) -> str:
    inspect_sample = sample.inspect_ai_sample
    sample_id = getattr(inspect_sample, "id", None)
    return str(sample_id) if sample_id is not None else ""


def build_expecto_sample_rows(
    data: EvaluationResult,
    *,
    benchmark: str,
    variant: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample in data.results:
        category = _classify_expecto_sample(sample)
        rows.append(
            {
                "id": _normalize_exported_sample_id(
                    benchmark, _sample_id_from_expecto_sample(sample)
                ),
                "classification": _category_label(category),
                "nl_description": _extract_expecto_nl_description(sample, benchmark),
                "specification": _extract_expecto_specification(sample),
            }
        )
    return rows


def build_evalplus_nl2_sample_rows(
    run_dir: Path,
    *,
    benchmark: str,
    variant: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for eval_data, _ in collect_nl2_postcond_data(run_dir):
        for entry in eval_data:
            is_sound = bool(entry.get("is_sound", False))
            is_complete = bool(entry.get("is_complete", False))
            if is_sound and is_complete:
                category = "S&C"
            elif is_sound:
                category = "S"
            elif is_complete:
                category = "C"
            else:
                category = "W"
            rows.append(
                {
                    "id": _normalize_exported_sample_id(
                        benchmark, entry.get("task_id", entry.get("id", ""))
                    ),
                    "classification": category,
                    "nl_description": "",
                    "specification": _format_sample_specification(
                        str(entry.get("assertion", "")),
                        is_expecto=False,
                    ),
                }
            )
    return rows


def build_defects4j_nl2_sample_rows(
    run_dir: Path,
    *,
    benchmark: str,
    variant: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in collect_defects4j_nl2_rows(run_dir):
        category = _category_label(str(entry.get("category", "W")))
        rows.append(
            {
                "id": _normalize_exported_sample_id(benchmark, entry.get("id", "")),
                "classification": category,
                "nl_description": "",
                "specification": _format_sample_specification(
                    str(entry.get("assertion", "")),
                    is_expecto=False,
                ),
            }
        )
    return rows


def export_target_sample_json(
    run_dir: Path,
    *,
    benchmark: str,
    variant: str,
    output_path: Path | None = None,
) -> Path:
    if variant.startswith("nl2_"):
        if benchmark == "defects4j":
            rows = build_defects4j_nl2_sample_rows(
                run_dir, benchmark=benchmark, variant=variant
            )
        else:
            rows = build_evalplus_nl2_sample_rows(
                run_dir, benchmark=benchmark, variant=variant
            )
    else:
        expecto_result_dir = run_dir / "evaluation_result"
        expecto_data = asyncio.run(collect_expecto_data(expecto_result_dir))
        rows = build_expecto_sample_rows(
            expecto_data, benchmark=benchmark, variant=variant
        )

    _attach_nl_descriptions(
        rows,
        benchmark=benchmark,
        variant=variant,
        run_dir=run_dir,
    )
    rows.sort(key=lambda row: row["id"])
    destination = output_path or (run_dir / "sample_results.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


async def collect_expecto_data(run_dir: Path) -> EvaluationResult:
    results = await read_score_logs(run_dir)
    if not results:
        raise click.ClickException(
            f"No Expecto evaluation result found under {run_dir}"
        )
    if len(results) != 1:
        raise click.ClickException(
            f"Expected exactly one Expecto evaluation result under {run_dir}, "
            f"but found {len(results)}"
        )
    return results[0]


def _get_log_files(path: Path, extension: str) -> list[Path]:
    """Collect files matching the requested extension."""

    normalized_extension = f".{extension.lower().lstrip('.')}"
    if path.is_file():
        return [path] if path.suffix.lower() == normalized_extension else []
    return sorted(candidate for candidate in path.rglob(f"*{normalized_extension}"))


def _extract_sample_events(sample: Any) -> Sequence[Any] | None:
    """Return the event stream for a raw or scored Inspect sample."""

    inspect_sample = getattr(sample, "inspect_ai_sample", sample)
    events = getattr(inspect_sample, "events", None)
    if events is None and isinstance(inspect_sample, Mapping):
        events = inspect_sample.get("events")
    if isinstance(events, Sequence) and not isinstance(events, (str, bytes, bytearray)):
        return events
    return None


def _extract_event_name(event: Any) -> str | None:
    """Extract event name from Inspect event objects or dictionaries."""

    if isinstance(event, Mapping):
        event_name = event.get("event")
    else:
        event_name = getattr(event, "event", None)
    return event_name if isinstance(event_name, str) else None


def _count_model_events(sample: Any) -> int | None:
    """Count model-call events for a sample."""

    events = _extract_sample_events(sample)
    if events is None:
        return None
    return sum(1 for event in events if _extract_event_name(event) == "model")


def _build_llm_call_rows(
    aggregates: Mapping[str, Mapping[str, list[int]]],
) -> list[LLMCallRow]:
    rows: list[LLMCallRow] = []
    for benchmark, benchmark_rows in aggregates.items():
        for exp_name, call_counts in benchmark_rows.items():
            if not call_counts:
                continue
            rows.append(
                LLMCallRow(
                    benchmark=benchmark,
                    exp_name=exp_name,
                    avg_llm_calls=float(np.mean(call_counts)),
                    sample_count=len(call_counts),
                )
            )
    return rows


async def _read_score_logs_with_paths(
    score_log_path: Path,
) -> list[tuple[Path, EvaluationResult]]:
    """Read scored logs while preserving their on-disk paths."""

    score_log_paths = discover_evaluation_result_paths(score_log_path)

    async def read_one(path: Path) -> tuple[Path, EvaluationResult] | None:
        try:
            return path, await asyncio.to_thread(load_evaluation_result, path)
        except Exception:
            return None

    results = await asyncio.gather(*[read_one(path) for path in score_log_paths])
    return [result for result in results if result is not None]


async def _collect_model_event_counts_from_eval_logs(
    eval_paths: Sequence[Path],
) -> tuple[list[int], int]:
    call_counts: list[int] = []
    eventful_sample_count = 0

    for eval_path in eval_paths:
        for sample in read_eval_log_samples(str(eval_path), all_samples_required=False):
            model_event_count = _count_model_events(sample)
            if model_event_count is None:
                continue
            call_counts.append(model_event_count)
            eventful_sample_count += 1

    return call_counts, eventful_sample_count


async def _collect_model_event_counts_from_score_logs(
    log_path: Path,
) -> tuple[list[int], int]:
    call_counts: list[int] = []
    eventful_sample_count = 0
    score_logs_with_paths = await _read_score_logs_with_paths(log_path)

    for _, log in score_logs_with_paths:
        for sample in log.results:
            model_event_count = _count_model_events(sample)
            if model_event_count is None:
                continue
            call_counts.append(model_event_count)
            eventful_sample_count += 1

    return call_counts, eventful_sample_count


async def _collect_llm_call_counts(log_path: Path) -> tuple[list[int], str]:
    """Collect per-sample LLM call counts from one experiment run root."""

    eval_paths = _get_log_files(log_path, "eval")
    if eval_paths:
        (
            call_counts,
            eventful_sample_count,
        ) = await _collect_model_event_counts_from_eval_logs(eval_paths)
        if eventful_sample_count == 0:
            raise click.ClickException(
                "Eval logs were found, but none of their samples contained event streams"
            )
        return call_counts, "eval"

    (
        call_counts,
        eventful_sample_count,
    ) = await _collect_model_event_counts_from_score_logs(log_path)
    if not call_counts:
        raise click.ClickException("No Inspect eval logs or scored JSON logs found")
    if eventful_sample_count == 0:
        raise click.ClickException(
            "Scored JSON logs were found, but none of their samples contained event streams"
        )
    return call_counts, "json"


async def _collect_llm_call_rows(
    config: FigureRunConfig,
) -> tuple[list[LLMCallRow], str]:
    """Collect average LLM call counts for configured Expecto runs."""

    aggregates: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    source_kinds: set[str] = set()

    async def collect_one(
        benchmark: str, run_key: str, run_dir: Path
    ) -> tuple[str, str, list[int], str]:
        try:
            call_counts, source_kind = await _collect_llm_call_counts(run_dir)
        except click.ClickException as exc:
            raise click.ClickException(
                f"Failed to collect LLM calls for '{run_key}' at {run_dir}: {exc.message}"
            ) from exc
        return benchmark, _get_expecto_run_label(run_key), call_counts, source_kind

    tasks = [
        collect_one(benchmark, run_key, run_dir)
        for benchmark, benchmark_config in config.items()
        for run_key, run_dir in benchmark_config.iter_expecto_runs()
    ]
    if not tasks:
        raise click.ClickException("No Expecto run directories were configured")

    results = await asyncio.gather(*tasks)
    for benchmark, exp_name, call_counts, source_kind in results:
        if not call_counts:
            continue
        aggregates[benchmark][exp_name].extend(call_counts)
        source_kinds.add(source_kind)

    rows = _build_llm_call_rows(aggregates)
    if not rows:
        raise click.ClickException("No model events found in the configured logs")
    return rows, ", ".join(sorted(source_kinds))


def _escape_latex_text(value: str) -> str:
    """Escape plain text so it is safe to render inside LaTeX tables."""

    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    escaped = value
    for old, new in replacements.items():
        escaped = escaped.replace(old, new)
    return escaped


def _format_llm_call_table(rows: list[LLMCallRow], caption: str, label: str) -> str:
    if not rows:
        return ""

    benchmark_order = {"apps": 0, "humanevalplus": 1, "human eval+": 1, "humaneval+": 1}
    benchmark_names = sorted(
        {row.benchmark for row in rows},
        key=lambda name: (benchmark_order.get(name.strip().lower(), 99), name),
    )
    exp_names_present = {row.exp_name for row in rows}
    ordered_exp_names = [
        EXPECTO_RUN_LABELS[run_key]
        for run_key in ("mono", "topdown", "ts")
        if EXPECTO_RUN_LABELS[run_key] in exp_names_present
    ]
    if not ordered_exp_names:
        return ""

    row_lookup = {(row.benchmark, row.exp_name): row for row in rows}
    col_format = "l" + "C" * len(ordered_exp_names)
    exp_headers = " & ".join(f"\\textsf{{{name}}}" for name in ordered_exp_names)
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        f"\\begin{{tabular}}{{{col_format}}}",
        "\\toprule",
        f"\\textbf{{Benchmark}} & {exp_headers} \\\\",
        "\\midrule",
    ]

    for benchmark in benchmark_names:
        benchmark_tex = _format_benchmark_tex(benchmark)
        avg_cells = [benchmark_tex]

        for exp_name in ordered_exp_names:
            row = row_lookup.get((benchmark, exp_name))
            avg_cells.append(f"{row.avg_llm_calls:.2f}" if row else "-")

        lines.append(" & ".join(avg_cells) + r" \\")

    lines.extend(
        [
            "\\bottomrule",
            "\\end{tabular}",
            "\\end{table}",
        ]
    )
    return "\n".join(lines)


def _format_benchmark_tex(name: str) -> str:
    normalized = name.strip()
    if normalized.lower() == "apps":
        return "\\apps{}"
    if normalized.lower() in {"humanevalplus", "human eval+", "humaneval+"}:
        return "\\humanevalplus{}"
    return normalized


def _order_results_by_experiment(
    results: Sequence[AggregatedResult], exp_order: Sequence[str] | None
) -> list[AggregatedResult]:
    if not exp_order:
        return list(results)
    order_map = {name: idx for idx, name in enumerate(exp_order)}
    return sorted(
        results,
        key=lambda item: (order_map.get(item.exp_name, len(order_map)), item.exp_name),
    )


def _plot_grouped_bars(
    ax: Axes,
    results: Sequence[AggregatedResult],
    exp_order: Sequence[str] | None = None,
    annotate: bool = True,
    show_ylabel: bool = True,
    exp_color_map: Mapping[str, str] | None = None,
) -> tuple[dict[str, BarContainer | None], list[str], float]:
    grouped = _order_results_by_experiment(results, exp_order)
    if not grouped:
        return {}, [], 0.0

    exp_names = [item.exp_name for item in grouped]
    value_matrix = np.array(
        [
            [
                item.sound_and_complete,
                item.sound_only,
                item.complete_only,
                item.wrong,
            ]
            for item in grouped
        ],
        dtype=float,
    )

    metric_labels = [r"S\&C", "S", "C", "W"]
    n_metrics = len(metric_labels)
    n_experiments = len(exp_names)

    if n_metrics == 0 or n_experiments == 0:
        return {}, exp_names, 0.0

    BAR_WIDTH = 0.18
    INTRA_GAP = 0.04

    centers = np.arange(n_metrics, dtype=float)
    base_offsets = (np.arange(n_experiments) - (n_experiments - 1) / 2.0) * (
        BAR_WIDTH + INTRA_GAP
    )

    color_cycle = cycle(PLOT_COLOR_CYCLE)
    bar_map: dict[str, BarContainer | None] = {}
    for idx, exp_name in enumerate(exp_names):
        color = (
            exp_color_map[exp_name]
            if exp_color_map and exp_name in exp_color_map
            else next(color_cycle)
        )
        values = value_matrix[idx]
        bars = ax.bar(
            centers + base_offsets[idx],
            values,
            width=BAR_WIDTH,
            label=exp_name,
            color=color,
        )
        bar_map[exp_name] = bars

    if show_ylabel:
        ax.set_ylabel(r"\# Tasks")
    else:
        ax.set_ylabel("")
    ax.set_xticks(centers)
    ax.set_xticklabels(metric_labels, rotation=0, ha="center")

    if annotate:
        for container in bar_map.values():
            if container is None:
                continue
            for rect in container:
                height = rect.get_height()
                ax.text(
                    rect.get_x() + rect.get_width() / 2.0,
                    height + 0.02 * max(1.0, float(height)),
                    str(int(round(height))),
                    ha="center",
                    va="bottom",
                )

    max_bar_height = float(value_matrix.max()) if value_matrix.size else 0.0
    y_upper = max(1.0, max_bar_height) * 1.25
    ax.set_ylim(0, y_upper)

    return bar_map, exp_names, max_bar_height


def _benchmark_sort_key(name: str) -> tuple[int, str]:
    normalized = name.lower()
    if normalized in {"humanevalplus", "human eval+", "humaneval+"}:
        return (0, name)
    if normalized == "apps":
        return (1, name)
    return (2, name)


def _format_benchmark_label(name: str) -> str:
    normalized = name.strip()
    if normalized.lower() == "apps":
        return "APPS"
    if normalized.lower() in {"humanevalplus", "human eval+", "humaneval+"}:
        return "HumanEval+"
    return normalized


def _format_benchmark_caption(benchmarks: Sequence[str]) -> str:
    ordered = sorted(dict.fromkeys(benchmarks), key=_benchmark_sort_key)
    benchmark_names = [_format_benchmark_tex(name) for name in ordered]
    if not benchmark_names:
        return "benchmarks"
    if len(benchmark_names) == 1:
        return f"{benchmark_names[0]} benchmark"
    if len(benchmark_names) == 2:
        return f"{benchmark_names[0]} and {benchmark_names[1]} benchmarks"
    return f"{', '.join(benchmark_names[:-1])}, and {benchmark_names[-1]} benchmarks"


def draw_ablation_subplots(
    data_by_benchmark: dict[str, list[AggregatedResult]],
    output_file: str | Path,
    exp_order: Sequence[str],
    exp_color_map: Mapping[str, str] | None = None,
    suptitle: str | None = None,
) -> None:
    if not data_by_benchmark:
        return

    ordered_benchmarks = sorted(data_by_benchmark.keys(), key=_benchmark_sort_key)

    legend_handles: list[Patch] = []
    legend_labels: list[str] = []

    if len(ordered_benchmarks) == 1:
        benchmark = ordered_benchmarks[0]
        fig, ax = plt.subplots(figsize=(10, 7))
        bar_map, _, _ = _plot_grouped_bars(
            ax,
            data_by_benchmark[benchmark],
            exp_order=exp_order,
            exp_color_map=exp_color_map,
        )
        ax.grid(True, linestyle=":", linewidth=0.9, axis="y")
        label = _format_benchmark_label(benchmark)
        ax.set_title(label)
        ax.tick_params(axis="both", labelsize=TICK_FONT_SIZE)

        for exp_name in exp_order:
            if exp_name in legend_labels:
                continue
            container = bar_map.get(exp_name)
            if container is None or len(container) == 0:
                continue
            color = (
                exp_color_map[exp_name]
                if exp_color_map and exp_name in exp_color_map
                else container.patches[0].get_facecolor()
            )
            legend_handles.append(Patch(facecolor=color, label=exp_name))
            legend_labels.append(exp_name)
        if legend_handles:
            ax.legend(
                legend_handles,  # type: ignore[arg-type]
                legend_labels,
                loc="upper center",
                ncol=len(legend_handles),
                bbox_to_anchor=(0.5, 1.08),
                frameon=True,
            )
        if suptitle:
            fig.suptitle(suptitle, y=0.98)
        fig.tight_layout()
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_file, bbox_inches="tight")
        plt.close(fig)
        return

    if len(ordered_benchmarks) != 2:
        raise ValueError(
            "Expected exactly two benchmarks to draw ablation subplots horizontally."
        )

    first_benchmark, second_benchmark = ordered_benchmarks
    fig, axes = plt.subplots(1, 2, figsize=(16.5, 6.8), sharey=True)
    fig.subplots_adjust(wspace=0.12, top=0.82, bottom=0.12)

    left_ax, right_ax = axes
    has_data = False
    global_max = 0.0

    bar_map_l, _, max_l = _plot_grouped_bars(
        left_ax,
        data_by_benchmark[first_benchmark],
        exp_order=exp_order,
        show_ylabel=True,
        exp_color_map=exp_color_map,
    )
    left_ax.grid(True, linestyle=":", linewidth=0.9, axis="y")
    first_label = _format_benchmark_label(first_benchmark)
    left_ax.set_title(first_label)
    left_ax.tick_params(axis="both", labelsize=TICK_FONT_SIZE)
    if any(container is not None for container in bar_map_l.values()):
        has_data = True
    global_max = max(global_max, max_l)

    bar_map_r, _, max_r = _plot_grouped_bars(
        right_ax,
        data_by_benchmark[second_benchmark],
        exp_order=exp_order,
        show_ylabel=False,
        exp_color_map=exp_color_map,
    )
    right_ax.grid(True, linestyle=":", linewidth=0.9, axis="y")
    second_label = _format_benchmark_label(second_benchmark)
    right_ax.set_title(second_label)
    right_ax.tick_params(axis="both", labelsize=TICK_FONT_SIZE)
    right_ax.tick_params(axis="y", labelleft=True)
    global_max = max(global_max, max_r)
    if any(container is not None for container in bar_map_r.values()):
        has_data = True

    if global_max > 0:
        y_upper = max(1.0, global_max) * 1.25
        left_ax.set_ylim(0, y_upper)
        right_ax.set_ylim(0, y_upper)

    if has_data:
        for exp_name in exp_order:
            if exp_name in legend_labels:
                continue
            color = (
                exp_color_map[exp_name]
                if exp_color_map and exp_name in exp_color_map
                else None
            )
            if color is None:
                container = bar_map_l.get(exp_name) or bar_map_r.get(exp_name)
                if container is not None and len(container) > 0:
                    color = container.patches[0].get_facecolor()
            if color is None:
                continue
            legend_handles.append(Patch(facecolor=color, label=exp_name))
            legend_labels.append(exp_name)
        if not legend_handles:
            for exp_name, container in {**bar_map_l, **bar_map_r}.items():
                if container is None or len(container) == 0:
                    continue
                if exp_name in legend_labels:
                    continue
                legend_handles.append(
                    Patch(
                        facecolor=container.patches[0].get_facecolor(), label=exp_name
                    )
                )
                legend_labels.append(exp_name)
        top_line = left_ax.get_position().y1 + 0.05
        if legend_handles:
            fig.legend(
                handles=legend_handles,
                labels=legend_labels,
                loc="lower center",
                bbox_to_anchor=(0.5, top_line),
                bbox_transform=fig.transFigure,
                ncol=len(legend_handles),
                frameon=True,
            )
    if suptitle:
        fig.suptitle(suptitle, y=0.97)
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_file, bbox_inches="tight")
    plt.close(fig)


def draw_bar_plot(
    inputs: list[AggregatedResult],
    output_file: str,
    title: str | None = None,
    exp_order: Sequence[str] | None = None,
    exp_color_map: Mapping[str, str] | None = None,
):
    if not inputs:
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    bar_map, exp_names, _ = _plot_grouped_bars(
        ax,
        inputs,
        exp_order=exp_order,
        exp_color_map=exp_color_map,
    )
    if title:
        ax.set_title(title, loc="center", y=1.08)

    legend_sequence = list(exp_order) if exp_order else exp_names
    legend_handles: list[Patch] = []
    legend_labels: list[str] = []
    for name in legend_sequence:
        container = bar_map.get(name)
        if container is None or len(container) == 0:
            continue
        color = (
            exp_color_map[name]
            if exp_color_map and name in exp_color_map
            else container.patches[0].get_facecolor()
        )
        legend_handles.append(Patch(facecolor=color, label=name))
        legend_labels.append(name)
    if legend_handles:
        ax.legend(
            legend_handles,  # type: ignore[arg-type]
            legend_labels,
            loc="upper center",
            ncol=len(legend_handles),
            bbox_to_anchor=(0.5, 1.08),
            frameon=True,
        )

    fig.tight_layout()
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_file, bbox_inches="tight")


def read_expecto(paths: list[Path]) -> list[EvaluationResult]:
    async def read_expecto_wrapper(path: Path) -> EvaluationResult:
        return await collect_expecto_data(path)

    async def gather_expecto_data():
        tasks = [read_expecto_wrapper(path) for path in paths]
        return await asyncio.gather(*tasks)

    return asyncio.run(gather_expecto_data())


@click.group()
def cli():
    pass


@cli.command(name="draw-rq1-fig")
@click.argument(
    "json_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    required=True,
)
@click.argument(
    "output_path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=".",
    required=False,
)
def draw_rq1_fig(json_path: str, output_path: str):
    config = _load_figure_run_config(json_path)
    output_dir = Path(output_path)
    datas: list[AggregatedResult] = []
    threshold_counts_by_benchmark: dict[str, dict[str, dict[float, dict[str, int]]]] = (
        defaultdict(dict)
    )
    threshold_plot_data: dict[str, dict[str, dict[str, list[int]]]] = {}
    benchmarks: list[str] = []
    for benchmark, benchmark_config in config.items():
        benchmarks.append(benchmark)
        expecto_data = asyncio.run(
            collect_expecto_data(
                _require_expecto_run(benchmark_config, benchmark, "ts")
            )
        )
        benchmark_threshold_counts = threshold_counts_by_benchmark.setdefault(
            benchmark, {}
        )

        for run_field, variant_name in BASELINE_NL2_RUNS:
            nl2_run_dir = _require_run_dir(
                getattr(benchmark_config, run_field),
                benchmark,
                run_field,
            )
            for eval_data, _ in collect_nl2_postcond_data(nl2_run_dir):
                exp_name = f"nl2postcond ({variant_name})"
                datas.append(parse_nl2_postcond_data(eval_data, benchmark, exp_name))
                counts = _compute_nl2_threshold_counts(eval_data, THRESHOLD_VALUES)
                accumulator = benchmark_threshold_counts.setdefault(
                    exp_name, _init_threshold_buckets(THRESHOLD_VALUES)
                )
                _merge_threshold_counts(accumulator, counts)

        datas.append(parse_expecto_data(expecto_data, benchmark))
        expecto_counts = _compute_expecto_threshold_counts(
            expecto_data.results, THRESHOLD_VALUES
        )
        accumulator = benchmark_threshold_counts.setdefault(
            "Expecto", _init_threshold_buckets(THRESHOLD_VALUES)
        )
        _merge_threshold_counts(accumulator, expecto_counts)

    caption = f"Performance on {_format_benchmark_caption(benchmarks)}"
    label = "tab:rq1-performance"
    tex_table = get_tex_table(datas, caption, label)
    _write_table_outputs(tex_table, output_dir / "evaluation.rq1.table.tex")

    for benchmark, exp_counts in threshold_counts_by_benchmark.items():
        if not exp_counts:
            continue
        formatted = {
            exp_name: _prepare_counts_for_plot(counts, THRESHOLD_VALUES)
            for exp_name, counts in exp_counts.items()
        }
        threshold_plot_data[benchmark] = formatted

    if threshold_plot_data:
        threshold_plot_path = output_dir / "evaluation.thresholds.pdf"
        draw_threshold_plot(
            THRESHOLD_VALUES, threshold_plot_data, str(threshold_plot_path)
        )


@cli.command(name="draw-rq2-fig")
@click.argument(
    "json_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    required=True,
)
@click.argument(
    "output_path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=".",
    required=False,
)
def draw_rq2_fig(json_path: str, output_path: str):
    config = _load_figure_run_config(json_path)
    datas: list[AggregatedResult] = []
    by_benchmark: dict[str, list[AggregatedResult]] = defaultdict(list)
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    for benchmark, benchmark_config in config.items():
        mono_path = _require_expecto_run(benchmark_config, benchmark, "mono")
        topdown_path = _require_expecto_run(benchmark_config, benchmark, "topdown")
        ts_path = _require_expecto_run(benchmark_config, benchmark, "ts")
        mono_data, topdown_data, ts_data = read_expecto(
            [mono_path, topdown_path, ts_path]
        )
        benchmark_results = [
            parse_expecto_data(mono_data, benchmark, "Mono"),
            parse_expecto_data(topdown_data, benchmark, "TopDown"),
            parse_expecto_data(ts_data, benchmark, "TreeSearch"),
        ]
        datas.extend(benchmark_results)
        by_benchmark[benchmark].extend(benchmark_results)

    caption = "Effectiveness of Mono, TopDown, and TreeSearch"
    label = "tab:rq2-algorithm-variants"
    tex_table = get_tex_table(datas, caption, label)
    tex_path = output_dir / "evaluation.rq2.table.tex"
    _write_table_outputs(tex_table, tex_path)

    pdf_path = output_dir / "evaluation.rq2.pdf"
    colors = {
        "Mono": COLOR_WRONG,
        "TopDown": COLOR_COMPLETE_ONLY,
        "TreeSearch": COLOR_SOUND_AND_COMPLETE,
    }
    draw_ablation_subplots(
        by_benchmark,
        pdf_path,
        exp_order=("Mono", "TopDown", "TreeSearch"),
        exp_color_map=colors,
    )


@cli.command(name="draw-rq3-fig")
@click.argument(
    "json_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    required=True,
)
@click.argument(
    "output_path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=".",
    required=False,
)
def draw_rq3_fig(json_path: str, output_path: str):
    config = _load_figure_run_config(json_path)
    testcase_ablation_datas: list[AggregatedResult] = []
    testcase_by_benchmark: dict[str, list[AggregatedResult]] = defaultdict(list)
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    for benchmark, benchmark_config in config.items():
        ts_path = _require_expecto_run(benchmark_config, benchmark, "ts")
        without_tc_path = _require_expecto_run(benchmark_config, benchmark, "without_tc")
        ts_data, without_tc_data = read_expecto([ts_path, without_tc_path])

        testcase_results = [parse_expecto_data(without_tc_data, benchmark, "Without TC")]
        testcase_results.append(parse_expecto_data(ts_data, benchmark, "With TC"))
        testcase_ablation_datas.extend(testcase_results)
        testcase_by_benchmark[benchmark].extend(testcase_results)

    testcase_caption = (
        "Effectiveness of approximated completeness check with test cases"
    )
    testcase_label = "tab:rq3-testcase-ablation"
    testcase_tex = get_tex_table(
        testcase_ablation_datas,
        testcase_caption,
        testcase_label,
    )
    testcase_tex_path = output_dir / "evaluation.rq3.testcase.table.tex"
    _write_table_outputs(testcase_tex, testcase_tex_path)

    testcase_pdf_path = output_dir / "evaluation.rq3.testcase.pdf"
    testcase_colors: dict[str, str] = {
        "Without TC": COLOR_WRONG,
        "With TC": COLOR_SOUND_AND_COMPLETE,
    }
    draw_ablation_subplots(
        testcase_by_benchmark,
        testcase_pdf_path,
        exp_order=("Without TC", "With TC"),
        exp_color_map=testcase_colors,
    )


@cli.command(name="draw-rq4-fig")
@click.argument(
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    required=True,
)
@click.argument(
    "output_path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=".",
    required=False,
)
def draw_rq4_fig(config_path: str, output_path: str):
    config = _load_defects4j_baseline_config(config_path)
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    expecto_data = asyncio.run(collect_expecto_data(config.expecto))
    nl2_base_data = collect_defects4j_nl2_data(config.nl2_postcond_base)
    nl2_simple_data = collect_defects4j_nl2_data(config.nl2_postcond_simple)

    datas = [
        parse_expecto_data(expecto_data, config.benchmark, "Expecto"),
        parse_defects4j_nl2_data(
            nl2_base_data,
            config.benchmark,
            "nl2postcond (Base)",
        ),
        parse_defects4j_nl2_data(
            nl2_simple_data,
            config.benchmark,
            "nl2postcond (Simple)",
        ),
    ]
    tex_table = get_tex_table(
        datas,
        caption="Performance on Defects4J",
        label="tab:rq4-defects4j-performance",
    )
    output_file = output_dir / "evaluation.rq4.defects4j.table.tex"
    _write_table_outputs(tex_table, output_file)


@cli.command(name="draw-llm-call-table")
@click.argument(
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    required=True,
)
@click.argument(
    "output_path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=".",
    required=False,
)
@click.option(
    "--caption",
    default="Comparison of the average number of LLM calls of monolithic, top-down, and tree search in \\tool{}.",
    show_default=True,
    help="Caption for the generated LaTeX table.",
)
@click.option(
    "--label",
    default="tab:llm-call-summary",
    show_default=True,
    help="Label for the generated LaTeX table.",
)
def draw_llm_call_table(config_path: str, output_path: str, caption: str, label: str):
    """Compute average LLM call counts and emit a LaTeX table."""

    config = _load_figure_run_config(config_path)
    rows, source_kind = asyncio.run(_collect_llm_call_rows(config))
    table_tex = _format_llm_call_table(rows, caption=caption, label=label)
    if not table_tex:
        raise click.ClickException("No model events found in the provided logs")

    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "evaluation.llm.calls.table.tex"
    output_pdf = _write_table_outputs(table_tex, output_file)

    click.echo(
        f"Saved LLM call table to {output_file} and {output_pdf} (source={source_kind})"
    )


@cli.command(name="export-target-sample-json")
@click.argument(
    "run_dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    required=True,
)
@click.option(
    "--benchmark",
    type=click.Choice(("apps", "humaneval_plus", "defects4j")),
    required=True,
)
@click.option(
    "--variant",
    type=click.Choice(
        ("mono", "topdown", "ts", "without_tc", "nl2_base", "nl2_simple")
    ),
    required=True,
)
@click.option(
    "--output-path",
    type=click.Path(file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional JSON path. Defaults to <run_dir>/sample_results.json.",
)
def export_target_sample_json_command(
    run_dir: Path,
    benchmark: str,
    variant: str,
    output_path: Path | None,
):
    output_file = export_target_sample_json(
        run_dir,
        benchmark=benchmark,
        variant=variant,
        output_path=output_path,
    )
    click.echo(f"Wrote {output_file}")


if __name__ == "__main__":
    cli()
