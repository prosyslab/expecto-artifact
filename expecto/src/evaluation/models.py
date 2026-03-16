import json
import hashlib
import math
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Optional, Sequence
from urllib.parse import quote

from inspect_ai.log import EvalSample, EvalSpec
from pydantic import BaseModel, Field

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from src.evaluation.config import config


class CodeExecutionTask(BaseModel):
    code: str  # Python code string
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timeout_seconds: int = Field(default=config.DEFAULT_EXECUTION_TIMEOUT)


class ExecutionResult(BaseModel):
    sample_id: str
    status: Literal["success", "failure", "timeout", "error"]
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    duration: Optional[float | Decimal] = None
    metadata: Optional[dict[str, Any]] = None


class Score(BaseModel):
    scorer_name: str
    score: int | float | str | Decimal
    explanation: str | None = None
    metadata: Optional[dict[str, Any]] = None
    execution_result: Optional[Sequence[ExecutionResult]] = None


class PersistedOutput(BaseModel):
    completion: str | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class PersistedInspectSample(BaseModel):
    id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    output: PersistedOutput = Field(default_factory=PersistedOutput)
    model_usage: dict[str, Any] = Field(default_factory=dict)
    difficulty: Any = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class Sample(BaseModel):
    inspect_ai_sample: EvalSample | PersistedInspectSample
    scores: Sequence[Score] | Sequence[Sequence[Score]]
    execution_result: Optional[ExecutionResult] = None


class EvaluationResult(BaseModel):
    # Accept raw dict as fallback; callers can up-convert to EvalSpec if needed
    eval_spec: EvalSpec
    scorers: list[str]
    save_file: str
    limit: Optional[int]
    max_sandboxes: Optional[int]
    results: list[Sample]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def model_validate_json(cls, json_data: str, *args: Any, **kwargs: Any):  # type: ignore[override]
        """Parse JSON using stdlib loader with Decimal to prevent range errors, then validate.

        This sidesteps pydantic-core's JSON number range limits for very large floats.
        """
        if isinstance(json_data, (bytes, bytearray)):
            json_data = json_data.decode()
        obj = json.loads(json_data, parse_float=Decimal)
        # Drop out-of-range/non-finite numbers from nested payloads that map to strict models
        if isinstance(obj, dict):
            if "eval_spec" in obj:
                obj["eval_spec"] = _sanitize_json_numbers(obj["eval_spec"])  # type: ignore[index]
            if "results" in obj and isinstance(obj["results"], list):
                for sample in obj["results"]:
                    if isinstance(sample, dict) and "inspect_ai_sample" in sample:
                        sample["inspect_ai_sample"] = _sanitize_json_numbers(
                            sample["inspect_ai_sample"]
                        )  # type: ignore[index]
        return cls.model_validate(obj, *args, **kwargs)


RESULT_STORE_DIRNAME = "evaluation_result"
RESULT_STORE_SAMPLES_DIRNAME = "samples"
RESULT_STORE_MANIFEST_FILENAME = "manifest.json"
RESULT_STORE_FORMAT = "evaluation_result_store"
RESULT_STORE_VERSION = 1
RESULT_STORE_MAX_FILENAME_BYTES = 255
RESULT_STORE_SAMPLE_HASH_LENGTH = 16
STRIPPED_METADATA_KEYS = {
    "test_list",
    "mutated_test_list",
    "prompt_test_list",
    "method_dumps",
    "corrects",
    "incorrects",
}


class PersistedSampleFile(BaseModel):
    sample_id: str
    final_output: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    model_usage: dict[str, Any] = Field(default_factory=dict)
    difficulty: Any = None
    scores: Sequence[Score] | Sequence[Sequence[Score]]
    execution_result: Optional[ExecutionResult] = None
    inspect_ai_sample: PersistedInspectSample | None = None


class PersistedSampleRef(BaseModel):
    sample_id: str
    file_name: str


class EvaluationResultManifest(BaseModel):
    format: str = RESULT_STORE_FORMAT
    version: int = RESULT_STORE_VERSION
    eval_spec: EvalSpec
    scorers: list[str]
    save_file: str
    limit: Optional[int]
    max_sandboxes: Optional[int]
    metadata: dict[str, Any] = Field(default_factory=dict)
    samples: list[PersistedSampleRef] = Field(default_factory=list)


def sample_id_from_sample(sample: Sample) -> str:
    return str(sample.inspect_ai_sample.id)


def build_result_store_root(save_file: str | Path) -> Path:
    save_path = Path(save_file)
    if (
        save_path.name == RESULT_STORE_MANIFEST_FILENAME
        and save_path.parent.name == RESULT_STORE_DIRNAME
    ):
        return save_path.parent
    return save_path.parent / RESULT_STORE_DIRNAME


def build_result_store_manifest_path(save_file: str | Path) -> Path:
    return build_result_store_root(save_file) / RESULT_STORE_MANIFEST_FILENAME


def build_result_store_samples_dir(save_file: str | Path) -> Path:
    return build_result_store_root(save_file) / RESULT_STORE_SAMPLES_DIRNAME


def get_result_output_root(save_file: str | Path) -> Path:
    save_path = Path(save_file)
    if (
        save_path.name == RESULT_STORE_MANIFEST_FILENAME
        and save_path.parent.name == RESULT_STORE_DIRNAME
    ):
        return save_path.parent
    return save_path.parent


def get_experiment_root(save_file: str | Path) -> Path:
    output_root = get_result_output_root(save_file)
    if output_root.name == RESULT_STORE_DIRNAME:
        return output_root.parent
    return output_root


def resolve_result_store_manifest(path: str | Path) -> Path | None:
    candidate = Path(path)
    if candidate.is_file():
        if (
            candidate.name == RESULT_STORE_MANIFEST_FILENAME
            and candidate.parent.name == RESULT_STORE_DIRNAME
        ):
            return candidate
        return None

    direct_manifest = candidate / RESULT_STORE_MANIFEST_FILENAME
    if candidate.name == RESULT_STORE_DIRNAME and direct_manifest.exists():
        return direct_manifest

    nested_manifest = candidate / RESULT_STORE_DIRNAME / RESULT_STORE_MANIFEST_FILENAME
    if nested_manifest.exists():
        return nested_manifest

    if direct_manifest.exists():
        return direct_manifest
    return None


def is_result_store_artifact(path: str | Path) -> bool:
    candidate = Path(path)
    return RESULT_STORE_DIRNAME in candidate.parts


def discover_evaluation_result_paths(path: str | Path) -> list[Path]:
    root = Path(path)
    if root.is_file():
        manifest_path = resolve_result_store_manifest(root)
        return [manifest_path or root]

    manifest_path = resolve_result_store_manifest(root)
    if manifest_path is not None and root.name == RESULT_STORE_DIRNAME:
        return [manifest_path]

    manifest_paths = sorted(
        root.rglob(f"{RESULT_STORE_DIRNAME}/{RESULT_STORE_MANIFEST_FILENAME}")
    )
    manifest_set = {manifest.resolve() for manifest in manifest_paths}

    legacy_paths: list[Path] = []
    for json_path in sorted(root.rglob("*.json")):
        resolved = json_path.resolve()
        if resolved in manifest_set:
            continue
        if is_result_store_artifact(json_path):
            continue
        legacy_paths.append(json_path)

    return manifest_paths + legacy_paths


def load_evaluation_result(path: str | Path) -> EvaluationResult:
    manifest_path = resolve_result_store_manifest(path)
    if manifest_path is not None:
        return load_evaluation_result_store(manifest_path)

    file_path = Path(path)
    return EvaluationResult.model_validate_json(file_path.read_text())


def load_evaluation_result_store(manifest_path: str | Path) -> EvaluationResult:
    manifest = _load_manifest(Path(manifest_path))
    results: list[Sample] = []
    samples_dir = Path(manifest.save_file).parent / RESULT_STORE_SAMPLES_DIRNAME

    for sample_ref in manifest.samples:
        sample_file = samples_dir / sample_ref.file_name
        payload = PersistedSampleFile.model_validate_json(sample_file.read_text())
        legacy_sample = payload.inspect_ai_sample
        completion = _serialize_persisted_final_output(payload.final_output)
        if completion is None and legacy_sample is not None:
            completion = legacy_sample.output.completion

        metadata = payload.metadata
        if not metadata and legacy_sample is not None:
            metadata = legacy_sample.metadata

        model_usage = payload.model_usage
        if not model_usage and legacy_sample is not None:
            model_usage = legacy_sample.model_usage

        difficulty = payload.difficulty
        if difficulty is None and legacy_sample is not None:
            difficulty = legacy_sample.difficulty

        results.append(
            Sample(
                inspect_ai_sample=PersistedInspectSample(
                    id=payload.sample_id,
                    metadata=metadata,
                    output=PersistedOutput(completion=completion),
                    model_usage=model_usage,
                    difficulty=difficulty,
                ),
                scores=payload.scores,
                execution_result=payload.execution_result,
            )
        )

    return EvaluationResult(
        eval_spec=manifest.eval_spec,
        scorers=manifest.scorers,
        save_file=manifest.save_file,
        limit=manifest.limit,
        max_sandboxes=manifest.max_sandboxes,
        results=results,
        metadata=manifest.metadata,
    )


def build_persisted_sample_file(sample: Sample) -> PersistedSampleFile:
    sample_id = sample_id_from_sample(sample)
    inspect_sample = sample.inspect_ai_sample
    output = getattr(inspect_sample, "output", None)
    completion = getattr(output, "completion", None) if output is not None else None
    metadata = _compact_sample_metadata(
        _to_jsonable(getattr(inspect_sample, "metadata", {}) or {})
    )
    model_usage = _to_jsonable(getattr(inspect_sample, "model_usage", {}) or {})
    difficulty = getattr(inspect_sample, "difficulty", None)
    if difficulty is None and isinstance(metadata, dict):
        difficulty = metadata.get("difficulty")

    return PersistedSampleFile(
        sample_id=sample_id,
        final_output=_extract_persisted_final_output(completion),
        metadata=metadata if isinstance(metadata, dict) else {},
        model_usage=model_usage if isinstance(model_usage, dict) else {},
        difficulty=_to_jsonable(difficulty),
        scores=_to_jsonable(sample.scores),
        execution_result=_to_jsonable(sample.execution_result),
    )


def build_sample_file_name(sample_id: str) -> str:
    quoted_sample_id = quote(sample_id, safe="")
    candidate = f"{quoted_sample_id}.json"
    if len(candidate.encode("utf-8")) <= RESULT_STORE_MAX_FILENAME_BYTES:
        return candidate

    digest = hashlib.sha256(sample_id.encode("utf-8")).hexdigest()[
        :RESULT_STORE_SAMPLE_HASH_LENGTH
    ]
    suffix = f"--{digest}.json"
    max_prefix_length = RESULT_STORE_MAX_FILENAME_BYTES - len(suffix)
    truncated_prefix = quoted_sample_id[:max_prefix_length]

    # Avoid leaving a partial percent-escape at the end after truncation.
    last_escape_start = truncated_prefix.rfind("%")
    if last_escape_start != -1 and len(truncated_prefix) - last_escape_start < 3:
        truncated_prefix = truncated_prefix[:last_escape_start]

    return f"{truncated_prefix}{suffix}"


def _load_manifest(manifest_path: Path) -> EvaluationResultManifest:
    manifest_obj = json.loads(manifest_path.read_text(), parse_float=Decimal)
    if isinstance(manifest_obj, dict) and "eval_spec" in manifest_obj:
        manifest_obj["eval_spec"] = _sanitize_json_numbers(manifest_obj["eval_spec"])
    return EvaluationResultManifest.model_validate(manifest_obj)


def _extract_persisted_final_output(completion: str | None) -> Any:
    if completion is None:
        return None

    try:
        parsed = json.loads(completion)
    except json.JSONDecodeError:
        return completion

    return _compact_final_output(parsed)


def _serialize_persisted_final_output(final_output: Any) -> str | None:
    if final_output is None:
        return None
    if isinstance(final_output, str):
        return final_output
    return json.dumps(final_output, indent=4)


def _compact_final_output(value: Any) -> Any:
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"tree", "latency_reports"}:
                continue
            compacted[str(key)] = _compact_final_output(item)
        return compacted
    if isinstance(value, list):
        return [_compact_final_output(item) for item in value]
    return _to_jsonable(value)


def _compact_sample_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compacted: dict[str, Any] = {}
    for key, item in value.items():
        if key in STRIPPED_METADATA_KEYS:
            continue
        if key == "method_info" and isinstance(item, dict):
            compacted[str(key)] = {
                nested_key: _to_jsonable(nested_item)
                for nested_key, nested_item in item.items()
                if nested_key not in {"code", "javadoc"}
            }
            continue
        compacted[str(key)] = _to_jsonable(item)
    return compacted


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {
            key: _to_jsonable(item)
            for key, item in value.model_dump(mode="python").items()
        }
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump(mode="python"))
    if hasattr(value, "__dict__"):
        return _to_jsonable(vars(value))
    return str(value)


def _sanitize_json_numbers(value: Any, max_abs: Decimal = Decimal("1e308")) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _is_out_of_range_number(item, max_abs):
                continue
            cleaned[key] = _sanitize_json_numbers(item, max_abs)
        return cleaned
    if isinstance(value, list):
        cleaned_list: list[Any] = []
        for item in value:
            if _is_out_of_range_number(item, max_abs):
                cleaned_list.append(None)
            else:
                cleaned_list.append(_sanitize_json_numbers(item, max_abs))
        return cleaned_list
    if isinstance(value, Decimal):
        return float(value)
    return value


def _is_out_of_range_number(value: Any, max_abs: Decimal) -> bool:
    """Return True if value is a non-finite or too-large number (Decimal/float)."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            return True
        try:
            return value.copy_abs() > max_abs
        except Exception:
            return True
    if isinstance(value, float):
        if not math.isfinite(value):
            return True
        try:
            return abs(value) > float(max_abs)
        except Exception:
            return True
    return False
