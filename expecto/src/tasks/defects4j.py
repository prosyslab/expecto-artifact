import json
import random
import re
import sys
from collections.abc import Callable
from logging import getLogger
from pathlib import Path
from typing import Any

import ijson
from inspect_ai import Epochs, Task, task
from inspect_ai.dataset import Dataset, MemoryDataset, Sample

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from src.evaluation.sandbox import initialize
from src.prompts.prompt import defects4j_prompt
from src.tasks.dataset_paths import resolve_defects4j_dataset_file

logger = getLogger(__name__)

from pydantic import BaseModel

import src.solvers as S

META_FIELDS = {"file_path", "id", "method_signature", "phase", "_type", "type_name"}
METHOD_ID_SANITIZER = re.compile(r"[^0-9A-Za-z]+")
OMITTED_METHOD_CODE = "// Method code omitted."

DEFECTS4J_VERIFY_TIMEOUT = 60 * 60 * 5  # 5 Hours


class EntrySchema(BaseModel):
    params: str
    self: str


class ExitSchema(BaseModel):
    self: str
    ret: str


class MethodInfo(BaseModel):
    code: str
    file: str
    javadoc: dict
    signature: str
    entry_schema: EntrySchema
    exit_schema: ExitSchema

    def to_dict(self):
        return self.model_dump()


class DumpData(BaseModel):
    class_path: str
    method_sig: str
    entry: dict
    exit: dict

    def to_dict(self):
        return self.model_dump()


class MethodDumpData(BaseModel):
    corrects: dict[str, dict[str, dict]]  # id -> phase -> dump
    incorrects: dict[str, dict[str, dict]]  # id -> phase -> dump
    method_info: MethodInfo

    def to_dict(self):
        return self.model_dump()


class BugData(BaseModel):
    project: str
    bug_id: str
    method_dumps: list[MethodDumpData]

    def to_dict(self):
        return self.model_dump()


class Defects4jMethodSample(BaseModel):
    project: str
    bug_id: str
    method_info: MethodInfo
    corrects: dict[str, dict[str, dict]]
    incorrects: dict[str, dict[str, dict]]

    def to_dict(self):
        return self.model_dump()


def sanitize_method_identifier(text: str) -> str:
    sanitized = METHOD_ID_SANITIZER.sub("_", text).strip("_")
    return sanitized or "method"


def build_method_sample_id(
    project: str,
    bug_id: str,
    method_info: MethodInfo,
    ids_count: dict[str, int],
) -> str:
    method_token = sanitize_method_identifier(
        f"{method_info.file}_{method_info.signature}"
    )
    base_id = f"{project}_{bug_id}_{method_token}"
    ids_count[base_id] = ids_count.get(base_id, 0) + 1
    if ids_count[base_id] == 1:
        return base_id
    return f"{base_id}_{ids_count[base_id]}"


def build_defects4j_method_prompt(
    method_info: MethodInfo, include_method_code: bool
) -> str:
    method_code = method_info.code if include_method_code else OMITTED_METHOD_CODE
    return defects4j_prompt.format(
        method_signature=method_info.signature,
        javadoc=json.dumps(method_info.javadoc or {}, indent=4),
        code=method_code,
    )


def _build_method_sample(
    bug_data: BugData,
    method_index: int,
    include_method_code: bool,
    ids_count: dict[str, int],
) -> Sample:
    method_dump = bug_data.method_dumps[method_index]
    method_metadata = Defects4jMethodSample(
        project=bug_data.project,
        bug_id=bug_data.bug_id,
        method_info=method_dump.method_info,
        corrects=method_dump.corrects,
        incorrects=method_dump.incorrects,
    )
    sample_id = build_method_sample_id(
        bug_data.project,
        bug_data.bug_id,
        method_dump.method_info,
        ids_count,
    )
    return Sample(
        input=build_defects4j_method_prompt(
            method_dump.method_info, include_method_code=include_method_code
        ),
        id=sample_id,
        metadata=method_metadata.model_dump(),
    )


def record_to_sample(
    bug_data: dict[str, Any],
    include_method_code: bool,
    method_index: int = 0,
) -> Sample:
    """Convert one bug record into a single method-level Sample."""
    validated_bug_data = BugData.model_validate(bug_data)
    if method_index < 0 or method_index >= len(validated_bug_data.method_dumps):
        raise IndexError(method_index)

    ids_count: dict[str, int] = {}
    for current_index in range(method_index + 1):
        sample = _build_method_sample(
            validated_bug_data,
            current_index,
            include_method_code,
            ids_count,
        )
    return sample


def record_to_samples(
    bug_data: dict[str, Any], include_method_code: bool
) -> list[Sample]:
    """Convert one bug record into method-level Samples."""
    validated_bug_data = BugData.model_validate(bug_data)
    ids_count: dict[str, int] = {}
    return [
        _build_method_sample(
            validated_bug_data,
            method_index,
            include_method_code,
            ids_count,
        )
        for method_index in range(len(validated_bug_data.method_dumps))
    ]


def _collect_jsonl_method_locations(
    jsonl_file: Path, limit: int | None = None
) -> list[tuple[int, int]]:
    locations: list[tuple[int, int]] = []
    with jsonl_file.open("rb") as file:
        while True:
            offset = file.tell()
            line = file.readline()
            if not line:
                break
            if not line.strip():
                continue
            record = json.loads(line)
            method_count = len(record.get("method_dumps") or [])
            for method_index in range(method_count):
                locations.append((offset, method_index))
                if limit is not None and len(locations) >= limit:
                    return locations
    return locations


class Defects4jJsonlDataset(Dataset):
    """Read Defects4J method samples lazily from the JSONL artifact."""

    def __init__(
        self,
        jsonl_file: Path,
        sample_factory: Callable[[dict[str, Any], int], Sample],
        limit: int | None = None,
    ):
        self._jsonl_file = jsonl_file
        self._sample_factory = sample_factory
        self._method_locations = _collect_jsonl_method_locations(jsonl_file, limit=limit)
        self._order = list(range(len(self._method_locations)))
        self._cache: dict[int, Sample] = {}
        self._name = jsonl_file.stem
        self._location = str(jsonl_file)
        self._shuffled = False

    @property
    def name(self) -> str | None:
        return self._name

    @property
    def location(self) -> str | None:
        return self._location

    @property
    def shuffled(self) -> bool:
        return self._shuffled

    def _load_sample(self, physical_index: int) -> Sample:
        cached = self._cache.get(physical_index)
        if cached is not None:
            return cached

        offset, method_index = self._method_locations[physical_index]
        with self._jsonl_file.open("r", encoding="utf-8") as file:
            file.seek(offset)
            line = file.readline()
        record = json.loads(line)
        sample = self._sample_factory(record, method_index)
        self._cache[physical_index] = sample
        return sample

    def __getitem__(self, index: int | slice) -> Sample | Dataset:
        if isinstance(index, slice):
            samples = [self[i] for i in range(*index.indices(len(self)))]
            return MemoryDataset(
                samples=samples,
                name=self.name,
                location=self.location,
                shuffled=self.shuffled,
            )

        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)

        physical_index = self._order[index]
        return self._load_sample(physical_index)

    def __len__(self) -> int:
        return len(self._order)

    def sort(
        self,
        reverse: bool = False,
        key: Callable[[Sample], Any] | None = None,
    ) -> None:
        sample_key = key or (lambda sample: len(str(sample.input)))
        self._order.sort(
            key=lambda physical_index: sample_key(self._load_sample(physical_index)),
            reverse=reverse,
        )

    def filter(
        self,
        predicate: Callable[[Sample], bool],
        name: str | None = None,
    ) -> Dataset:
        samples = [sample for sample in self if predicate(sample)]
        return MemoryDataset(
            samples=samples,
            name=name or self.name,
            location=self.location,
            shuffled=self.shuffled,
        )

    def shuffle(self, seed: int | None = None) -> None:
        rng = random.Random(seed)
        rng.shuffle(self._order)
        self._shuffled = True

    def shuffle_choices(self, seed: int | None = None) -> None:
        return None


@task(name="defects4j")
def defects4j(
    solver: str = "baseline",
    epochs: int = 1,
    max_attempts: int = 5,
    n_completions: int = 1,
    threshold: float = 0.5,
    use_test_cases: bool = True,
    use_memo: bool = True,
    check_unsat: bool = True,
    include_method_code: bool = True,
    limit: int | None = None,
    *args,
    **kwargs,
) -> Task:
    s = S.solver_map[solver]
    solver_obj = s(
        max_attempts=max_attempts,
        n_completions=n_completions,
        threshold=threshold,
        use_test_cases=use_test_cases,
        use_memo=use_memo,
        check_unsat=check_unsat,
    )

    random.seed(42)
    dataset = load_defects4j_dataset(include_method_code, limit=limit)

    logger.info(f"Dataset size: {len(dataset)}")

    initialize()

    return Task(
        dataset=dataset,
        epochs=Epochs(epochs),
        solver=solver_obj,
        sandbox="local",
        time_limit=DEFECTS4J_VERIFY_TIMEOUT,
        fail_on_error=False,
    )


def load_defects4j_dataset(
    include_method_code: bool,
    limit: int | None = None,
) -> Dataset:
    """Load Defects4J samples, preferring the streaming JSONL artifact."""

    dataset_file = resolve_defects4j_dataset_file(prefer_jsonl=True)
    sample_factory = lambda record, method_index: record_to_sample(
        record,
        include_method_code,
        method_index=method_index,
    )
    if dataset_file.suffix == ".jsonl":
        return Defects4jJsonlDataset(
            dataset_file,
            sample_factory=sample_factory,
            limit=limit,
        )

    return load_legacy_defects4j_dataset(
        dataset_file,
        include_method_code=include_method_code,
        limit=limit,
    )


def load_legacy_defects4j_dataset(
    json_file: Path,
    *,
    include_method_code: bool,
    limit: int | None,
) -> Dataset:
    """Fallback loader for the legacy JSON array artifact."""

    samples: list[Sample] = []
    if limit is not None:
        with json_file.open("rb") as file:
            for bug_data in ijson.items(file, "item"):
                remaining = limit - len(samples)
                if remaining <= 0:
                    break
                samples.extend(record_to_samples(bug_data, include_method_code)[:remaining])
    else:
        with json_file.open("r", encoding="utf-8") as file:
            data = json.load(file)
        for bug_data in data:
            samples.extend(record_to_samples(bug_data, include_method_code))

    return MemoryDataset(
        samples=samples,
        name=json_file.stem,
        location=str(json_file),
    )
