from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import click


PROJECT_DIR = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_DIR.parent.parent
JAVA_HELPER_DIR = PROJECT_DIR / "java"
CACHE_DIR = REPO_ROOT / ".cache" / "defects4j_assertion_validator"
SPOON_VERSION = "10.4.2"
SPOON_JAR_NAME = f"spoon-core-{SPOON_VERSION}-jar-with-dependencies.jar"
SPOON_JAR_URL = (
    "https://repo1.maven.org/maven2/fr/inria/gforge/spoon/spoon-core/"
    f"{SPOON_VERSION}/{SPOON_JAR_NAME}"
)
INJECTOR_CLASS_NAME = "Defects4JAssertionInjector"
JUNIT_RUNNER_CLASS_NAME = "JunitTestRunner"
GIT_SAFE_CONFIG = """[safe]
\tdirectory = *
"""


@dataclass(frozen=True)
class InputRecord:
    id: str
    project: str
    bug_id: str
    method: str
    method_signature: str
    method_file_path: str
    prompt_version: str
    assertion: str
    raw_response: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "InputRecord":
        return cls(
            id=payload["id"],
            project=payload["project"],
            bug_id=str(payload["bug_id"]),
            method=payload.get("method", ""),
            method_signature=payload["method_signature"],
            method_file_path=payload["method_file_path"],
            prompt_version=payload.get("prompt_version", ""),
            assertion=payload.get("assertion", ""),
            raw_response=payload.get("raw_response", ""),
        )


@dataclass(frozen=True)
class NormalizedAssertion:
    status: str
    text: str
    source: str
    error: str


@dataclass(frozen=True)
class CheckoutMetadata:
    dir_src_classes: str
    dir_bin_classes: str
    dir_bin_tests: str
    cp_test: str
    trigger_tests: list[str]
    relevant_tests: list[str]


@dataclass(frozen=True)
class InjectionResult:
    status: str
    executable_kind: str
    relative_file: str
    source_file_name: str
    assert_lines: list[int]
    error: str


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


class CommandError(RuntimeError):
    def __init__(self, message: str, result: CommandResult):
        super().__init__(message)
        self.result = result


def extract_code_block(text: str, language: str = "java") -> str:
    fence = f"```{language}"
    if fence in text:
        start = text.find(fence) + len(fence)
        end = text.find("```", start)
        if end != -1:
            return text[start:end].strip()

    if "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end != -1:
            return text[start:end].strip()

    return text.strip()


def normalize_assertion(record: InputRecord) -> NormalizedAssertion:
    candidates: list[tuple[str, str]] = []
    if record.assertion.strip():
        candidates.append(("assertion", record.assertion))

    raw_code = extract_code_block(record.raw_response, language="java")
    if raw_code.strip():
        candidates.append(("raw_response_code", raw_code))

    if record.raw_response.strip():
        candidates.append(("raw_response", record.raw_response))

    errors: list[str] = []
    seen_texts: set[str] = set()
    for source_name, candidate in candidates:
        normalized_candidate = candidate.strip()
        if not normalized_candidate or normalized_candidate in seen_texts:
            continue
        seen_texts.add(normalized_candidate)
        try:
            normalized_text = extract_single_assertion(candidate)
            return NormalizedAssertion(
                status="ok",
                text=normalized_text,
                source=source_name,
                error="",
            )
        except ValueError as exc:
            errors.append(f"{source_name}: {exc}")

    return NormalizedAssertion(
        status="error",
        text="",
        source="",
        error=" | ".join(errors) if errors else "No assertion candidate found",
    )


def extract_single_assertion(text: str) -> str:
    candidate = extract_code_block(text, language="java").strip()
    if not candidate:
        raise ValueError("empty assertion candidate")

    assert_positions = find_assert_positions(candidate)
    if len(assert_positions) != 1:
        raise ValueError(f"expected exactly one assert statement, found {len(assert_positions)}")

    assert_index = assert_positions[0]
    semicolon_index = find_statement_terminator(candidate, assert_index)
    if semicolon_index is None:
        raise ValueError("assert statement does not end with ';'")

    assertion_statement = candidate[assert_index:semicolon_index + 1].strip()
    trailing_text = candidate[semicolon_index + 1 :]
    if find_assert_positions(trailing_text):
        raise ValueError("multiple assert statements detected")

    return assertion_statement


def find_assert_positions(text: str) -> list[int]:
    positions: list[int] = []
    scanner = JavaScanner(text)
    for index, token in scanner.scan_identifiers():
        if token == "assert":
            positions.append(index)
    return positions


def find_statement_terminator(text: str, start_index: int) -> int | None:
    scanner = JavaScanner(text[start_index:])
    for relative_index, token in scanner.scan_special_tokens():
        if token == ";":
            return start_index + relative_index
    return None


class JavaScanner:
    def __init__(self, text: str) -> None:
        self.text = text

    def scan_identifiers(self) -> list[tuple[int, str]]:
        identifiers: list[tuple[int, str]] = []
        index = 0
        while index < len(self.text):
            index = self._skip_ignored(index)
            if index >= len(self.text):
                break
            current = self.text[index]
            if current.isalpha() or current == "_":
                start = index
                index += 1
                while index < len(self.text) and (
                    self.text[index].isalnum() or self.text[index] in {"_", "$"}
                ):
                    index += 1
                identifiers.append((start, self.text[start:index]))
                continue
            index += 1
        return identifiers

    def scan_special_tokens(self) -> list[tuple[int, str]]:
        tokens: list[tuple[int, str]] = []
        index = 0
        while index < len(self.text):
            index = self._skip_ignored(index)
            if index >= len(self.text):
                break
            if self.text[index] == ";":
                tokens.append((index, ";"))
            index += 1
        return tokens

    def _skip_ignored(self, index: int) -> int:
        while index < len(self.text):
            current = self.text[index]
            next_char = self.text[index + 1] if index + 1 < len(self.text) else ""
            if current == "/" and next_char == "/":
                newline_index = self.text.find("\n", index + 2)
                return len(self.text) if newline_index == -1 else newline_index + 1
            if current == "/" and next_char == "*":
                block_end = self.text.find("*/", index + 2)
                return len(self.text) if block_end == -1 else block_end + 2
            if current == '"':
                return self._skip_string(index, '"')
            if current == "'":
                return self._skip_string(index, "'")
            break
        return index

    def _skip_string(self, index: int, quote_char: str) -> int:
        index += 1
        escaped = False
        while index < len(self.text):
            current = self.text[index]
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == quote_char:
                return index + 1
            index += 1
        return len(self.text)


def read_jsonl(path: Path) -> list[InputRecord]:
    rows: list[InputRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(InputRecord.from_dict(json.loads(stripped)))
    return rows


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | float | None = None,
    check: bool = False,
) -> CommandResult:
    started_at = time.monotonic()
    process = subprocess.run(
        command,
        cwd=None if cwd is None else str(cwd),
        env=env,
        timeout=timeout,
        capture_output=True,
        text=True,
    )
    elapsed_seconds = time.monotonic() - started_at
    result = CommandResult(
        command=command,
        returncode=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
        elapsed_seconds=elapsed_seconds,
    )
    if check and result.returncode != 0:
        raise CommandError(
            f"Command failed: {' '.join(command)}",
            result,
        )
    return result


def ensure_spoon_jar() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    spoon_jar_path = CACHE_DIR / SPOON_JAR_NAME
    if spoon_jar_path.exists() and spoon_jar_path.stat().st_size > 0:
        return spoon_jar_path

    with urllib.request.urlopen(SPOON_JAR_URL) as response:
        with spoon_jar_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    return spoon_jar_path


def ensure_git_safe_config() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    config_path = CACHE_DIR / "git-safe.conf"
    if config_path.exists() and config_path.read_text(encoding="utf-8") == GIT_SAFE_CONFIG:
        return config_path

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=CACHE_DIR,
        prefix=f"{config_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(GIT_SAFE_CONFIG)
        temp_path = Path(handle.name)
    temp_path.replace(config_path)
    return config_path


def build_defects4j_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = str(ensure_git_safe_config())
    return env


def ensure_injector_build(spoon_jar_path: Path) -> Path:
    build_dir = CACHE_DIR / "injector_build"
    class_file = build_dir / f"{INJECTOR_CLASS_NAME}.class"
    source_file = JAVA_HELPER_DIR / f"{INJECTOR_CLASS_NAME}.java"
    if class_file.exists() and class_file.stat().st_mtime >= source_file.stat().st_mtime:
        return build_dir

    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    run_command(
        [
            "javac",
            "-cp",
            str(spoon_jar_path),
            "-d",
            str(build_dir),
            str(source_file),
        ],
        check=True,
        timeout=600,
    )
    return build_dir


def compile_junit_runner(workdir: Path, metadata: CheckoutMetadata, build_dir: Path) -> Path:
    source_file = JAVA_HELPER_DIR / f"{JUNIT_RUNNER_CLASS_NAME}.java"
    build_dir.mkdir(parents=True, exist_ok=True)
    runtime_classpath = build_runtime_classpath(workdir, metadata, build_dir=None)
    run_command(
        [
            "javac",
            "-cp",
            runtime_classpath,
            "-d",
            str(build_dir),
            str(source_file),
        ],
        check=True,
        timeout=600,
    )
    return build_dir


def defects4j_export(property_name: str, workdir: Path) -> str:
    result = run_command(
        ["defects4j", "export", "-p", property_name, "-w", str(workdir)],
        env=build_defects4j_env(),
        check=True,
        timeout=300,
    )
    return result.stdout.strip()


def defects4j_checkout(project: str, version: str, workdir: Path) -> None:
    if workdir.exists():
        shutil.rmtree(workdir)
    run_command(
        ["defects4j", "checkout", "-p", project, "-v", version, "-w", str(workdir)],
        env=build_defects4j_env(),
        check=True,
        timeout=900,
    )


def defects4j_compile(workdir: Path, timeout: int) -> CommandResult:
    return run_command(
        ["defects4j", "compile", "-w", str(workdir)],
        env=build_defects4j_env(),
        timeout=timeout,
        check=False,
    )


def load_checkout_metadata(workdir: Path) -> CheckoutMetadata:
    return CheckoutMetadata(
        dir_src_classes=defects4j_export("dir.src.classes", workdir),
        dir_bin_classes=defects4j_export("dir.bin.classes", workdir),
        dir_bin_tests=defects4j_export("dir.bin.tests", workdir),
        cp_test=defects4j_export("cp.test", workdir),
        trigger_tests=split_export_list(defects4j_export("tests.trigger", workdir)),
        relevant_tests=split_export_list(defects4j_export("tests.relevant", workdir)),
    )


def split_export_list(raw_value: str) -> list[str]:
    if not raw_value.strip():
        return []
    return [entry.strip() for entry in re.split(r"[;\n]+", raw_value) if entry.strip()]


def normalize_classpath_entries(raw_classpath: str, workdir: Path) -> list[str]:
    entries: list[str] = []
    for entry in raw_classpath.split(os.pathsep):
        stripped = entry.strip()
        if not stripped:
            continue
        if os.path.isabs(stripped):
            entries.append(stripped)
            continue
        entries.append(str(workdir / stripped))
    return entries


def build_runtime_classpath(
    workdir: Path,
    metadata: CheckoutMetadata,
    build_dir: Path | None,
) -> str:
    classpath_entries = []
    if build_dir is not None:
        classpath_entries.append(str(build_dir))
    classpath_entries.append(str(workdir / metadata.dir_bin_tests))
    classpath_entries.append(str(workdir / metadata.dir_bin_classes))
    classpath_entries.extend(normalize_classpath_entries(metadata.cp_test, workdir))
    return os.pathsep.join(classpath_entries)


def resolve_relative_source_file(method_file_path: str, source_root: Path, source_dir_hint: str) -> str:
    normalized_method_path = method_file_path.replace("\\", "/")
    normalized_hint = source_dir_hint.strip("/").replace("\\", "/")
    token = f"/{normalized_hint}/"
    if token in normalized_method_path:
        return normalized_method_path.split(token, 1)[1]

    file_name = Path(method_file_path).name
    candidates = list(source_root.rglob(file_name))
    if not candidates:
        raise FileNotFoundError(f"Could not locate source file {file_name} under {source_root}")
    if len(candidates) == 1:
        return candidates[0].relative_to(source_root).as_posix()

    target_parts = Path(method_file_path).parts
    best_candidate = max(
        candidates,
        key=lambda candidate: suffix_match_score(candidate.parts, target_parts),
    )
    return best_candidate.relative_to(source_root).as_posix()


def suffix_match_score(candidate_parts: tuple[str, ...], target_parts: tuple[str, ...]) -> int:
    score = 0
    for candidate_part, target_part in zip(reversed(candidate_parts), reversed(target_parts)):
        if candidate_part != target_part:
            break
        score += 1
    return score


def inject_assertion(
    *,
    workdir: Path,
    metadata: CheckoutMetadata,
    record: InputRecord,
    normalized_assertion: NormalizedAssertion,
    spoon_jar_path: Path,
    injector_build_dir: Path,
    scratch_dir: Path,
) -> InjectionResult:
    source_root = workdir / metadata.dir_src_classes
    relative_file = resolve_relative_source_file(
        record.method_file_path,
        source_root,
        metadata.dir_src_classes,
    )
    assertion_file = scratch_dir / "assertion.java"
    result_file = scratch_dir / "injector-result.json"
    output_root = scratch_dir / "spoon-output"
    assertion_file.write_text(normalized_assertion.text, encoding="utf-8")

    command_result = run_command(
        [
            "java",
            "-cp",
            os.pathsep.join([str(injector_build_dir), str(spoon_jar_path)]),
            INJECTOR_CLASS_NAME,
            "--source-root",
            str(source_root),
            "--relative-file",
            relative_file,
            "--method-signature",
            record.method_signature,
            "--assertion-file",
            str(assertion_file),
            "--output-root",
            str(output_root),
            "--result-file",
            str(result_file),
        ],
        timeout=900,
        check=False,
    )

    if not result_file.exists():
        return InjectionResult(
            status="error",
            executable_kind="",
            relative_file=relative_file,
            source_file_name=Path(relative_file).name,
            assert_lines=[],
            error=command_result.stderr.strip() or command_result.stdout.strip() or "Injector failed",
        )

    payload = json.loads(result_file.read_text(encoding="utf-8"))
    if payload["status"] != "ok":
        return InjectionResult(
            status="error",
            executable_kind=payload.get("executable_kind", ""),
            relative_file=relative_file,
            source_file_name=Path(relative_file).name,
            assert_lines=[],
            error=payload.get("message", "Injector failed"),
        )

    rewritten_file = output_root / relative_file
    target_file = source_root / relative_file
    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rewritten_file, target_file)

    return InjectionResult(
        status="ok",
        executable_kind=payload["executable_kind"],
        relative_file=relative_file,
        source_file_name=Path(relative_file).name,
        assert_lines=[int(line) for line in payload.get("assert_lines", [])],
        error="",
    )


def run_junit_test(
    *,
    workdir: Path,
    metadata: CheckoutMetadata,
    runner_build_dir: Path,
    class_name: str,
    method_name: str | None,
    source_file_name: str,
    assert_lines: list[int],
    timeout: int,
) -> dict[str, Any]:
    runtime_classpath = build_runtime_classpath(workdir, metadata, build_dir=runner_build_dir)
    command_result = run_command(
        [
            "java",
            "-ea",
            "-cp",
            runtime_classpath,
            JUNIT_RUNNER_CLASS_NAME,
            "--class-name",
            class_name,
            "--method-name",
            method_name or "-",
            "--source-file",
            source_file_name,
            "--assert-lines",
            ",".join(str(line) for line in assert_lines),
        ],
        cwd=workdir,
        timeout=timeout,
        check=False,
    )
    stdout = command_result.stdout.strip()
    if not stdout:
        return {
            "status": "error",
            "run_count": 0,
            "passed_count": 0,
            "failure_count": 0,
            "ignore_count": 0,
            "assertion_hit": False,
            "failures": [],
            "message": command_result.stderr.strip() or "Runner returned no output",
        }

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "status": "error",
            "run_count": 0,
            "passed_count": 0,
            "failure_count": 0,
            "ignore_count": 0,
            "assertion_hit": False,
            "failures": [],
            "message": stdout,
        }


def summarize_relevant_tests(
    *,
    workdir: Path,
    metadata: CheckoutMetadata,
    runner_build_dir: Path,
    source_file_name: str,
    assert_lines: list[int],
    timeout: int,
) -> dict[str, Any]:
    summary = {
        "classes_total": len(metadata.relevant_tests),
        "classes_passed": 0,
        "classes_failed": 0,
        "tests_total": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "tests_ignored": 0,
        "failures": [],
    }

    for class_name in metadata.relevant_tests:
        result = run_junit_test(
            workdir=workdir,
            metadata=metadata,
            runner_build_dir=runner_build_dir,
            class_name=class_name,
            method_name=None,
            source_file_name=source_file_name,
            assert_lines=assert_lines,
            timeout=timeout,
        )
        summary["tests_total"] += result["run_count"]
        summary["tests_passed"] += result["passed_count"]
        summary["tests_failed"] += result["failure_count"]
        summary["tests_ignored"] += result["ignore_count"]
        if result["status"] == "passed":
            summary["classes_passed"] += 1
        else:
            summary["classes_failed"] += 1
            summary["failures"].append(
                {
                    "class_name": class_name,
                    "status": result["status"],
                    "message": result.get("message", ""),
                    "failures": result.get("failures", []),
                }
            )
    return summary


def parse_trigger_test(test_identifier: str) -> tuple[str, str]:
    if "::" not in test_identifier:
        raise ValueError(f"Invalid trigger test identifier: {test_identifier}")
    class_name, method_name = test_identifier.split("::", 1)
    return class_name.strip(), method_name.strip()


def summarize_trigger_tests(
    *,
    workdir: Path,
    metadata: CheckoutMetadata,
    runner_build_dir: Path,
    source_file_name: str,
    assert_lines: list[int],
    timeout: int,
) -> dict[str, Any]:
    summary = {
        "total": len(metadata.trigger_tests),
        "passed": 0,
        "failed": 0,
        "detected": 0,
        "tests_total": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "tests_ignored": 0,
        "failures": [],
    }

    for test_identifier in metadata.trigger_tests:
        class_name, method_name = parse_trigger_test(test_identifier)
        result = run_junit_test(
            workdir=workdir,
            metadata=metadata,
            runner_build_dir=runner_build_dir,
            class_name=class_name,
            method_name=method_name,
            source_file_name=source_file_name,
            assert_lines=assert_lines,
            timeout=timeout,
        )
        summary["tests_total"] += result["run_count"]
        summary["tests_passed"] += result["passed_count"]
        summary["tests_failed"] += result["failure_count"]
        summary["tests_ignored"] += result["ignore_count"]

        if result["status"] == "passed":
            summary["passed"] += 1
        else:
            summary["failed"] += 1
            if result.get("assertion_hit"):
                summary["detected"] += 1
            summary["failures"].append(
                {
                    "test": test_identifier,
                    "status": result["status"],
                    "assertion_hit": result.get("assertion_hit", False),
                    "message": result.get("message", ""),
                    "failures": result.get("failures", []),
                }
            )

    return summary


def build_record_report(
    *,
    record: InputRecord,
    normalized_assertion: NormalizedAssertion,
    fixed_injection: InjectionResult | None,
    buggy_injection: InjectionResult | None,
    fixed_compile: CommandResult | None,
    buggy_compile: CommandResult | None,
    relevant_summary: dict[str, Any] | None,
    trigger_fixed_summary: dict[str, Any] | None,
    trigger_buggy_summary: dict[str, Any] | None,
    internal_error: str = "",
) -> dict[str, Any]:
    fixed_compile_success = fixed_compile is not None and fixed_compile.returncode == 0
    buggy_compile_success = buggy_compile is not None and buggy_compile.returncode == 0
    relevant_summary = relevant_summary or empty_relevant_summary()
    trigger_fixed_summary = trigger_fixed_summary or empty_trigger_summary()
    trigger_buggy_summary = trigger_buggy_summary or empty_trigger_summary()

    completeness = (
        normalized_assertion.status == "ok"
        and fixed_injection is not None
        and fixed_injection.status == "ok"
        and fixed_compile_success
        and relevant_summary["classes_failed"] == 0
    )
    soundness = (
        normalized_assertion.status == "ok"
        and fixed_injection is not None
        and fixed_injection.status == "ok"
        and buggy_injection is not None
        and buggy_injection.status == "ok"
        and fixed_compile_success
        and buggy_compile_success
        and trigger_fixed_summary["failed"] == 0
        and trigger_buggy_summary["detected"] > 0
    )

    return {
        "id": record.id,
        "project": record.project,
        "bug_id": record.bug_id,
        "prompt_version": record.prompt_version,
        "method": record.method,
        "method_signature": record.method_signature,
        "method_file_path": record.method_file_path,
        "normalized_assertion": asdict(normalized_assertion),
        "fixed_injection": None if fixed_injection is None else asdict(fixed_injection),
        "buggy_injection": None if buggy_injection is None else asdict(buggy_injection),
        "fixed_compile": serialize_command_result(fixed_compile),
        "buggy_compile": serialize_command_result(buggy_compile),
        "relevant": relevant_summary,
        "trigger_fixed": trigger_fixed_summary,
        "trigger_buggy": trigger_buggy_summary,
        "completeness": completeness,
        "soundness": soundness,
        "internal_error": internal_error,
    }


def has_compile_error(report: dict[str, Any]) -> bool:
    fixed_compile = report.get("fixed_compile")
    buggy_compile = report.get("buggy_compile")
    fixed_failed = fixed_compile is not None and fixed_compile.get("returncode") != 0
    buggy_failed = buggy_compile is not None and buggy_compile.get("returncode") != 0
    return fixed_failed or buggy_failed


def classify_report(report: dict[str, Any]) -> str:
    if has_compile_error(report):
        return "W"
    if report["soundness"] and report["completeness"]:
        return "SC"
    if report["soundness"]:
        return "S"
    if report["completeness"]:
        return "C"
    return "W"


def build_final_result_row(report: dict[str, Any]) -> dict[str, Any]:
    category = classify_report(report)
    normalized_assertion = report["normalized_assertion"]
    relevant = report["relevant"]
    trigger_fixed = report["trigger_fixed"]
    trigger_buggy = report["trigger_buggy"]

    return {
        "id": report["id"],
        "project": report["project"],
        "bug_id": report["bug_id"],
        "prompt_version": report["prompt_version"],
        "method": report["method"],
        "method_signature": report["method_signature"],
        "method_file_path": report["method_file_path"],
        "assertion_status": normalized_assertion["status"],
        "assertion_source": normalized_assertion["source"],
        "assertion": normalized_assertion["text"],
        "category": category,
        "completeness": report["completeness"],
        "soundness": report["soundness"],
        "compile_error": has_compile_error(report),
        "relevant_tests_passed": relevant["tests_passed"],
        "relevant_tests_total": relevant["tests_total"],
        "relevant_tests_failed": relevant["tests_failed"],
        "relevant_tests_ignored": relevant["tests_ignored"],
        "trigger_fixed_passed": trigger_fixed["tests_passed"],
        "trigger_fixed_total": trigger_fixed["tests_total"],
        "trigger_fixed_failed": trigger_fixed["tests_failed"],
        "trigger_buggy_passed": trigger_buggy["tests_passed"],
        "trigger_buggy_total": trigger_buggy["tests_total"],
        "trigger_buggy_failed": trigger_buggy["tests_failed"],
        "trigger_buggy_detected": trigger_buggy["detected"],
        "internal_error": report["internal_error"],
    }


def empty_relevant_summary() -> dict[str, Any]:
    return {
        "classes_total": 0,
        "classes_passed": 0,
        "classes_failed": 0,
        "tests_total": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "tests_ignored": 0,
        "failures": [],
    }


def empty_trigger_summary() -> dict[str, Any]:
    return {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "detected": 0,
        "tests_total": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "tests_ignored": 0,
        "failures": [],
    }


def serialize_command_result(result: CommandResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "command": result.command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "elapsed_seconds": result.elapsed_seconds,
    }


def format_internal_error(exc: Exception) -> str:
    if isinstance(exc, CommandError):
        stderr = exc.result.stderr.strip()
        if stderr:
            condensed_stderr = stderr[-1000:]
            return f"{exc.__class__.__name__}: {exc}\nSTDERR:\n{condensed_stderr}"
    return f"{exc.__class__.__name__}: {exc}"


def evaluate_record(
    *,
    record: InputRecord,
    spoon_jar_path: Path,
    injector_build_dir: Path,
    compile_timeout: int,
    test_timeout: int,
    keep_workdirs: bool,
    output_dir: Path,
) -> dict[str, Any]:
    normalized_assertion = normalize_assertion(record)
    if normalized_assertion.status != "ok":
        return build_record_report(
            record=record,
            normalized_assertion=normalized_assertion,
            fixed_injection=None,
            buggy_injection=None,
            fixed_compile=None,
            buggy_compile=None,
            relevant_summary=None,
            trigger_fixed_summary=None,
            trigger_buggy_summary=None,
            internal_error="",
        )
    fixed_injection = None
    buggy_injection = None
    fixed_compile = None
    buggy_compile = None
    relevant_summary = None
    trigger_fixed_summary = None
    trigger_buggy_summary = None

    try:
        work_root_parent = CACHE_DIR / "workdirs"
        work_root_parent.mkdir(parents=True, exist_ok=True)
        if keep_workdirs:
            work_root = output_dir / "_workdirs" / record.id
            if work_root.exists():
                shutil.rmtree(work_root)
            work_root.mkdir(parents=True, exist_ok=True)
            temp_context = nullcontext(work_root)
        else:
            temp_context = tempfile.TemporaryDirectory(
                prefix=f"{record.project}_{record.bug_id}_",
                dir=work_root_parent,
            )

        with temp_context as temp_dir_name:
            work_root = Path(temp_dir_name)
            fixed_workdir = work_root / "fixed"
            buggy_workdir = work_root / "buggy"
            defects4j_checkout(record.project, f"{record.bug_id}f", fixed_workdir)
            defects4j_checkout(record.project, f"{record.bug_id}b", buggy_workdir)

            fixed_metadata = load_checkout_metadata(fixed_workdir)
            buggy_metadata = load_checkout_metadata(buggy_workdir)

            fixed_scratch = work_root / "fixed-scratch"
            buggy_scratch = work_root / "buggy-scratch"
            fixed_scratch.mkdir(parents=True, exist_ok=True)
            buggy_scratch.mkdir(parents=True, exist_ok=True)

            fixed_injection = inject_assertion(
                workdir=fixed_workdir,
                metadata=fixed_metadata,
                record=record,
                normalized_assertion=normalized_assertion,
                spoon_jar_path=spoon_jar_path,
                injector_build_dir=injector_build_dir,
                scratch_dir=fixed_scratch,
            )
            buggy_injection = inject_assertion(
                workdir=buggy_workdir,
                metadata=buggy_metadata,
                record=record,
                normalized_assertion=normalized_assertion,
                spoon_jar_path=spoon_jar_path,
                injector_build_dir=injector_build_dir,
                scratch_dir=buggy_scratch,
            )

            if fixed_injection.status == "ok":
                fixed_compile = defects4j_compile(fixed_workdir, compile_timeout)
            if buggy_injection.status == "ok":
                buggy_compile = defects4j_compile(buggy_workdir, compile_timeout)

            fixed_runner_build_dir = work_root / "fixed-runner-build"
            buggy_runner_build_dir = work_root / "buggy-runner-build"

            if (
                fixed_injection.status == "ok"
                and fixed_compile is not None
                and fixed_compile.returncode == 0
            ):
                compile_junit_runner(fixed_workdir, fixed_metadata, fixed_runner_build_dir)
                relevant_summary = summarize_relevant_tests(
                    workdir=fixed_workdir,
                    metadata=fixed_metadata,
                    runner_build_dir=fixed_runner_build_dir,
                    source_file_name=fixed_injection.source_file_name,
                    assert_lines=fixed_injection.assert_lines,
                    timeout=test_timeout,
                )
                trigger_fixed_summary = summarize_trigger_tests(
                    workdir=fixed_workdir,
                    metadata=fixed_metadata,
                    runner_build_dir=fixed_runner_build_dir,
                    source_file_name=fixed_injection.source_file_name,
                    assert_lines=fixed_injection.assert_lines,
                    timeout=test_timeout,
                )

            if (
                buggy_injection.status == "ok"
                and buggy_compile is not None
                and buggy_compile.returncode == 0
            ):
                compile_junit_runner(buggy_workdir, buggy_metadata, buggy_runner_build_dir)
                trigger_buggy_summary = summarize_trigger_tests(
                    workdir=buggy_workdir,
                    metadata=buggy_metadata,
                    runner_build_dir=buggy_runner_build_dir,
                    source_file_name=buggy_injection.source_file_name,
                    assert_lines=buggy_injection.assert_lines,
                    timeout=test_timeout,
                )

    except Exception as exc:  # pragma: no cover - defensive batch guard
        return build_record_report(
            record=record,
            normalized_assertion=normalized_assertion,
            fixed_injection=fixed_injection,
            buggy_injection=buggy_injection,
            fixed_compile=fixed_compile,
            buggy_compile=buggy_compile,
            relevant_summary=relevant_summary,
            trigger_fixed_summary=trigger_fixed_summary,
            trigger_buggy_summary=trigger_buggy_summary,
            internal_error=format_internal_error(exc),
        )

    return build_record_report(
        record=record,
        normalized_assertion=normalized_assertion,
        fixed_injection=fixed_injection,
        buggy_injection=buggy_injection,
        fixed_compile=fixed_compile,
        buggy_compile=buggy_compile,
        relevant_summary=relevant_summary,
        trigger_fixed_summary=trigger_fixed_summary,
        trigger_buggy_summary=trigger_buggy_summary,
        internal_error="",
    )


def summarize_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    category_counts = {"W": 0, "S": 0, "C": 0, "SC": 0}
    for report in reports:
        category_counts[classify_report(report)] += 1

    return {
        "records_total": len(reports),
        "assertion_parse_errors": sum(
            1 for report in reports if report["normalized_assertion"]["status"] != "ok"
        ),
        "internal_errors": sum(1 for report in reports if report["internal_error"]),
        "category_counts": category_counts,
        "completeness_passed": sum(1 for report in reports if report["completeness"]),
        "soundness_passed": sum(1 for report in reports if report["soundness"]),
        "relevant_tests_total": sum(report["relevant"]["tests_total"] for report in reports),
        "relevant_tests_passed": sum(report["relevant"]["tests_passed"] for report in reports),
        "trigger_fixed_total": sum(report["trigger_fixed"]["tests_total"] for report in reports),
        "trigger_fixed_passed": sum(report["trigger_fixed"]["tests_passed"] for report in reports),
        "trigger_buggy_total": sum(report["trigger_buggy"]["tests_total"] for report in reports),
        "trigger_buggy_detected": sum(report["trigger_buggy"]["detected"] for report in reports),
        "failing_record_ids": [
            report["id"]
            for report in reports
            if not report["completeness"] or not report["soundness"]
        ],
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def write_markdown_summary(
    path: Path,
    *,
    input_file: Path,
    summary: dict[str, Any],
) -> None:
    lines = [
        f"# Validation Summary for `{input_file.name}`",
        "",
        f"- records_total: {summary['records_total']}",
        f"- assertion_parse_errors: {summary['assertion_parse_errors']}",
        f"- internal_errors: {summary['internal_errors']}",
        f"- category_W: {summary['category_counts']['W']}",
        f"- category_S: {summary['category_counts']['S']}",
        f"- category_C: {summary['category_counts']['C']}",
        f"- category_SC: {summary['category_counts']['SC']}",
        f"- completeness_passed: {summary['completeness_passed']}",
        f"- soundness_passed: {summary['soundness_passed']}",
        f"- relevant_tests_passed: {summary['relevant_tests_passed']} / {summary['relevant_tests_total']}",
        f"- trigger_fixed_passed: {summary['trigger_fixed_passed']} / {summary['trigger_fixed_total']}",
        f"- trigger_buggy_detected: {summary['trigger_buggy_detected']} / {summary['trigger_buggy_total']}",
    ]
    if summary["failing_record_ids"]:
        lines.extend(
            [
                "",
                "## Failing Records",
                "",
                *[f"- `{record_id}`" for record_id in summary["failing_record_ids"]],
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def iter_input_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(path for path in input_path.glob("*.jsonl") if path.is_file())


def evaluate_records_in_parallel(
    *,
    records: list[InputRecord],
    spoon_jar_path: Path,
    injector_build_dir: Path,
    compile_timeout: int,
    test_timeout: int,
    keep_workdirs: bool,
    output_dir: Path,
    max_concurrency: int,
) -> list[dict[str, Any]]:
    if max_concurrency <= 1 or len(records) <= 1:
        sequential_reports: list[dict[str, Any]] = []
        for index, record in enumerate(records, start=1):
            click.echo(f"  [{index}/{len(records)}] {record.id}")
            sequential_reports.append(
                evaluate_record(
                    record=record,
                    spoon_jar_path=spoon_jar_path,
                    injector_build_dir=injector_build_dir,
                    compile_timeout=compile_timeout,
                    test_timeout=test_timeout,
                    keep_workdirs=keep_workdirs,
                    output_dir=output_dir,
                )
            )
        return sequential_reports

    click.echo(f"  Running validation with max_concurrency={max_concurrency}")
    reports: list[dict[str, Any] | None] = [None] * len(records)
    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        future_to_index = {
            executor.submit(
                evaluate_record,
                record=record,
                spoon_jar_path=spoon_jar_path,
                injector_build_dir=injector_build_dir,
                compile_timeout=compile_timeout,
                test_timeout=test_timeout,
                keep_workdirs=keep_workdirs,
                output_dir=output_dir,
            ): index
            for index, record in enumerate(records)
        }

        completed = 0
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            report = future.result()
            reports[index] = report
            completed += 1
            click.echo(f"  [{completed}/{len(records)}] {records[index].id}")

    ordered_reports: list[dict[str, Any]] = []
    for report in reports:
        if report is None:
            raise RuntimeError("parallel validation produced an incomplete result set")
        ordered_reports.append(report)
    return ordered_reports


@dataclass
class nullcontext:
    value: Any

    def __enter__(self) -> Any:
        return self.value

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


@click.command()
@click.argument("input_path", type=click.Path(path_type=Path, exists=True))
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory where validation reports will be written.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Optional limit on the number of records per input file.",
)
@click.option(
    "--compile-timeout",
    type=int,
    default=900,
    show_default=True,
    help="Timeout in seconds for defects4j compile.",
)
@click.option(
    "--test-timeout",
    type=int,
    default=180,
    show_default=True,
    help="Timeout in seconds for each JUnit request.",
)
@click.option(
    "--keep-workdirs",
    is_flag=True,
    help="Keep patched Defects4J workdirs under the output directory.",
)
@click.option(
    "--max-concurrency",
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="Maximum number of records to validate in parallel.",
)
def main(
    input_path: Path,
    output_dir: Path | None,
    limit: int | None,
    compile_timeout: int,
    test_timeout: int,
    keep_workdirs: bool,
    max_concurrency: int,
) -> None:
    spoon_jar_path = ensure_spoon_jar()
    injector_build_dir = ensure_injector_build(spoon_jar_path)
    input_files = iter_input_files(input_path)
    if not input_files:
        raise click.ClickException(f"No jsonl input files found under {input_path}")

    if output_dir is None:
        output_dir = (input_path if input_path.is_dir() else input_path.parent) / "validation"
    output_dir.mkdir(parents=True, exist_ok=True)

    for jsonl_file in input_files:
        click.echo(f"Validating {jsonl_file}")
        records = read_jsonl(jsonl_file)
        if limit is not None:
            records = records[:limit]

        reports = evaluate_records_in_parallel(
            records=records,
            spoon_jar_path=spoon_jar_path,
            injector_build_dir=injector_build_dir,
            compile_timeout=compile_timeout,
            test_timeout=test_timeout,
            keep_workdirs=keep_workdirs,
            output_dir=output_dir,
            max_concurrency=max_concurrency,
        )

        summary = summarize_reports(reports)
        final_rows = [build_final_result_row(report) for report in reports]
        jsonl_report_path = output_dir / f"{jsonl_file.stem}.validation.jsonl"
        final_jsonl_path = output_dir / f"{jsonl_file.stem}.final.jsonl"
        summary_path = output_dir / f"{jsonl_file.stem}.summary.json"
        markdown_path = output_dir / f"{jsonl_file.stem}.summary.md"

        write_jsonl(jsonl_report_path, reports)
        write_jsonl(final_jsonl_path, final_rows)
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        write_markdown_summary(markdown_path, input_file=jsonl_file, summary=summary)

        click.echo(f"  Wrote {jsonl_report_path}")
        click.echo(f"  Wrote {final_jsonl_path}")
        click.echo(f"  Wrote {summary_path}")


if __name__ == "__main__":
    main()
