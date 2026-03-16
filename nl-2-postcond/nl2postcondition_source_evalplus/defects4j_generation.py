import asyncio
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping, TextIO

from benchmarks import iter_defects4j_method_examples
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, Model, get_model
from prompts import genOneWithRefJava

JAVA_SYSTEM_PROMPT = (
    "You are a programming assistant that generates executable java only. "
    "You generate correct code, so you only generate code you are sure of. "
    "You have java comments explaining your intent when possible."
)
PROMPT_TEMPLATES = genOneWithRefJava
TO_GENERATE_FULL = "symbolic postcondition"
TO_GENERATE_SHORT = "postcondition"
TO_GENERATE_GOAL = "means"
TO_GENERATE_SHORT_CAPS = "POSTCONDITION"
PROMPT_VERSIONS = ("simple", "base")


@dataclass(frozen=True)
class MethodRecord:
    id: str
    project: str
    bug_id: str
    method: str
    method_signature: str
    method_file_path: str
    javadoc: dict[str, Any]
    reference_code: str

    @classmethod
    def from_dict(cls, record: dict[str, Any]) -> "MethodRecord":
        return cls(
            id=record["id"],
            project=record["project"],
            bug_id=record["bug_id"],
            method=record.get("method", record.get("method_name", "")),
            method_signature=record["method_signature"],
            method_file_path=record.get("file", ""),
            javadoc=record["javadoc"],
            reference_code=record["reference_code"],
        )


@dataclass(frozen=True)
class GenerationResult:
    id: str
    project: str
    bug_id: str
    method: str
    method_signature: str
    method_file_path: str
    prompt_version: str
    javadoc: dict[str, Any]
    reference_code: str
    prompt: str
    raw_response: str
    assertion: str


def build_prompt(method_record: MethodRecord, prompt_version: str) -> str:
    template = PROMPT_TEMPLATES[prompt_version]
    code_stub_and_docstring = "\n\n".join(
        [
            "/**",
            json.dumps(method_record.javadoc, indent=4, ensure_ascii=True),
            "*/",
            method_record.reference_code,
        ]
    )
    return template.substitute(
        codeStubAndDocstring=code_stub_and_docstring,
        toGenerateFull=TO_GENERATE_FULL,
        toGenerateShort=TO_GENERATE_SHORT,
        toGenerateGoal=TO_GENERATE_GOAL,
        toGenerateShortCaps=TO_GENERATE_SHORT_CAPS,
        promptAdds="",
        entrypoint=method_record.method or method_record.method_signature,
        entrypointLong=method_record.method_signature,
    )


def extract_code_block(text: str, language: str = "java") -> str:
    fence = f"```{language}"
    if fence in text:
        start = text.find(fence) + len(fence)
        end = text.find("```", start)
        if end != -1:
            return text[start:end].strip()

    if "```" in text:
        first = text.find("```") + 3
        second = text.find("```", first)
        if second != -1:
            return text[first:second].strip()

    return text.strip()


def extract_java_assertion(text: str) -> str:
    code = extract_code_block(text, language="java")
    lines = [line.rstrip() for line in code.splitlines() if line.strip()]
    if not lines:
        return ""

    selected: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("assert "):
            selected.append(line)

    if selected:
        return "\n".join(selected)

    return "\n".join(lines)


async def generate_one(
    model: Model,
    method_record: MethodRecord,
    prompt_version: str,
    semaphore: asyncio.Semaphore,
) -> GenerationResult:
    prompt = build_prompt(method_record, prompt_version)
    messages = [
        ChatMessageSystem(content=JAVA_SYSTEM_PROMPT),
        ChatMessageUser(content=prompt),
    ]

    async with semaphore:
        result = await model.generate(input=messages)

    raw_response = result.message.content
    if isinstance(raw_response, list):
        raw_response = "\n".join(str(getattr(part, "text", part)) for part in raw_response)

    return GenerationResult(
        id=method_record.id,
        project=method_record.project,
        bug_id=method_record.bug_id,
        method=method_record.method,
        method_signature=method_record.method_signature,
        method_file_path=method_record.method_file_path,
        prompt_version=prompt_version,
        javadoc=method_record.javadoc,
        reference_code=method_record.reference_code,
        prompt=prompt,
        raw_response=str(raw_response),
        assertion=extract_java_assertion(str(raw_response)),
    )


async def generate_one_with_index(
    sequence_index: int,
    model: Model,
    method_record: MethodRecord,
    prompt_version: str,
    semaphore: asyncio.Semaphore,
) -> tuple[int, GenerationResult]:
    return sequence_index, await generate_one(
        model=model,
        method_record=method_record,
        prompt_version=prompt_version,
        semaphore=semaphore,
    )


def write_jsonl_row(handle: TextIO, row: GenerationResult) -> None:
    handle.write(json.dumps(asdict(row), ensure_ascii=True) + "\n")


def flush_completed_results(
    writer_by_prompt: Mapping[str, TextIO],
    completed_tasks: set[asyncio.Task],
    buffered_rows_by_prompt: dict[str, dict[int, GenerationResult]],
    next_index_by_prompt: dict[str, int],
) -> None:
    touched_prompt_versions: set[str] = set()

    for task in completed_tasks:
        sequence_index, row = task.result()
        buffered_rows_by_prompt[row.prompt_version][sequence_index] = row
        touched_prompt_versions.add(row.prompt_version)

    for prompt_version in touched_prompt_versions:
        writer = writer_by_prompt[prompt_version]
        buffered_rows = buffered_rows_by_prompt[prompt_version]
        next_index = next_index_by_prompt[prompt_version]
        wrote_row = False

        # Preserve input order per prompt while still streaming completed rows.
        while next_index in buffered_rows:
            write_jsonl_row(writer, buffered_rows.pop(next_index))
            next_index += 1
            wrote_row = True

        next_index_by_prompt[prompt_version] = next_index
        if wrote_row:
            writer.flush()


async def run_generation(
    model_name: str,
    dataset_path: str,
    output_dir: Path,
    limit: int | None,
    max_concurrency: int,
    prompt_versions: tuple[str, ...] = PROMPT_VERSIONS,
    sample_ids: list[str] | None = None,
) -> None:
    benchmark_cfg = type(
        "BenchmarksCfg",
        (),
        {"location": dataset_path, "name": "defects4j"},
    )()
    model = get_model(model_name)
    semaphore = asyncio.Semaphore(max_concurrency)
    output_dir.mkdir(parents=True, exist_ok=True)
    writer_by_prompt = {
        prompt_version: (output_dir / f"{prompt_version}.jsonl").open(
            "w", encoding="utf-8"
        )
        for prompt_version in prompt_versions
    }
    pending_tasks: set[asyncio.Task] = set()
    max_pending_tasks = max_concurrency * len(prompt_versions)
    buffered_rows_by_prompt = {prompt_version: {} for prompt_version in prompt_versions}
    next_index_by_prompt = {prompt_version: 0 for prompt_version in prompt_versions}

    try:
        for sequence_index, record in enumerate(
            iter_defects4j_method_examples(
                benchmark_cfg,
                limit=limit,
                sample_ids=sample_ids,
            )
        ):
            method_record = MethodRecord.from_dict(record)
            for prompt_version in prompt_versions:
                pending_tasks.add(
                    asyncio.create_task(
                        generate_one_with_index(
                            sequence_index,
                            model,
                            method_record,
                            prompt_version,
                            semaphore,
                        )
                    )
                )

            # Keep the pending task set bounded while streaming results to disk.
            if len(pending_tasks) >= max_pending_tasks:
                completed_tasks, pending_tasks = await asyncio.wait(
                    pending_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                flush_completed_results(
                    writer_by_prompt,
                    completed_tasks,
                    buffered_rows_by_prompt,
                    next_index_by_prompt,
                )

        while pending_tasks:
            completed_tasks, pending_tasks = await asyncio.wait(
                pending_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            flush_completed_results(
                writer_by_prompt,
                completed_tasks,
                buffered_rows_by_prompt,
                next_index_by_prompt,
            )
    except Exception:
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        raise
    finally:
        for handle in writer_by_prompt.values():
            handle.close()
