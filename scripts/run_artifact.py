from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import click

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON_BIN = sys.executable
DEFAULT_OUTPUT_ROOT = Path("/workspace/data/experiment/artifact")
STANDARD_PROFILE_NAME = "full"
MINI_PROFILE_NAME = "mini"
RQ_CHOICES = ("rq1", "rq2", "rq3", "rq4")
EVALPLUS_BENCHMARKS = ("apps", "humaneval_plus")
BENCHMARK_LABELS = {
    "apps": "APPS",
    "humaneval_plus": "HumanEval+",
    "defects4j": "Defects4J",
}
EVALPLUS_RUNNERS = {
    "apps": PROJECT_ROOT / "scripts" / "run_apps.py",
    "humaneval_plus": PROJECT_ROOT / "scripts" / "run_humaneval_plus.py",
}
NL2_EVALPLUS_RUNNER = PROJECT_ROOT / "scripts" / "run_nl2postcond.py"
DEFECTS4J_EXPECTO_RUNNER = PROJECT_ROOT / "scripts" / "run_defects4j.py"
DEFECTS4J_NL2_RUNNER = PROJECT_ROOT / "scripts" / "run_defects4j_nl2postcond.py"
FIGURE_GENERATOR = PROJECT_ROOT / "analyzer" / "figure_generator.py"
MINI_EVALPLUS_SAMPLE_IDS = {
    "apps": (
        "15",
        "16",
        "23",
        "37",
        "39",
        "42",
        "47",
        "52",
        "57",
        "61",
        "71",
        "72",
        "76",
        "83",
        "90",
        "94",
        "101",
        "3701",
        "4004",
        "4005",
    ),
    "humaneval_plus": (
        "6",
        "22",
        "32",
        "34",
        "52",
        "53",
        "54",
        "61",
        "63",
        "71",
        "73",
        "75",
        "83",
        "92",
        "123",
        "124",
        "129",
        "140",
        "158",
        "162",
    ),
}
MINI_DEFECTS4J_SAMPLE_IDS = (
    "Chart_6_workspace_objdump_d4j_full_fresh_chart_6_source_org_jfree_chart_util_ShapeList_java_boolean_equals_Object_obj",
    "Cli_18_workspace_objdump_d4j_full_fresh_cli_18_src_java_org_apache_commons_cli_PosixParser_java_void_processOptionToken_String_token_boolean_stopAtNonOption",
    "Compress_40_workspace_objdump_d4j_full_compress_40_src_main_java_org_apache_commons_compress_utils_BitInputStream_java_long_readBits_int_count",
    "Jsoup_76_workspace_objdump_d4j_full_jsoup_76_src_main_java_org_jsoup_parser_HtmlTreeBuilderState_java_boolean_process_Token_t_HtmlTreeBuilder_tb",
    "Jsoup_85_workspace_objdump_d4j_full_jsoup_85_src_main_java_org_jsoup_nodes_Attribute_java_Attribute_String_key_String_val_Attributes_parent",
    "Lang_32_workspace_objdump_d4j_full_lang_32_src_main_java_org_apache_commons_lang3_builder_HashCodeBuilder_java_boolean_isRegistered_Object_value",
    "Math_35_workspace_objdump_d4j_full_math_35_src_main_java_org_apache_commons_math3_genetics_ElitisticListPopulation_java_ElitisticListPopulation_int_populationLimit_double_elitismRate",
    "Math_73_workspace_objdump_d4j_full_math_73_src_main_java_org_apache_commons_math_analysis_solvers_BrentSolver_java_double_solve_UnivariateRealFunction_f_double_min_double_max",
    "Math_80_workspace_objdump_d4j_full_math_80_src_main_java_org_apache_commons_math_linear_EigenDecompositionImpl_java_boolean_flipIfWarranted_int_n_int_step",
    "Math_96_workspace_objdump_d4j_full_math_96_src_java_org_apache_commons_math_complex_Complex_java_boolean_equals_Object_other",
    "Cli_10_workspace_objdump_d4j_full_fresh_cli_10_src_java_org_apache_commons_cli_Parser_java_CommandLine_parse_Options_options_String_arguments_Properties_properties_boolean_stopAtNonOption",
    "Cli_18_workspace_objdump_d4j_full_fresh_cli_18_src_java_org_apache_commons_cli_PosixParser_java_String_flatten_Options_options_String_arguments_boolean_stopAtNonOption",
    "Cli_32_workspace_objdump_d4j_full_fresh_cli_32_src_main_java_org_apache_commons_cli_HelpFormatter_java_int_findWrapPos_String_text_int_width_int_startPos",
    "Closure_114_workspace_objdump_d4j_full_fresh_closure_114_src_com_google_javascript_jscomp_NameAnalyzer_java_void_visit_NodeTraversal_t_Node_n_Node_parent",
    "Closure_74_workspace_objdump_d4j_full_fresh_closure_74_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldBinaryOperator_Node_subtree",
    "Closure_78_workspace_objdump_d4j_full_fresh_closure_78_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldArithmeticOp_Node_n_Node_left_Node_right",
    "Closure_97_workspace_objdump_d4j_full_fresh_closure_97_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldBinaryOperator_Node_subtree",
    "Codec_4_workspace_objdump_d4j_full_codec_4_src_java_org_apache_commons_codec_binary_Base64_java_byte_encodeBase64_byte_binaryData_boolean_isChunked_boolean_urlSafe_int_maxResultSize",
    "Jsoup_38_workspace_objdump_d4j_full_jsoup_38_src_main_java_org_jsoup_parser_HtmlTreeBuilderState_java_boolean_process_Token_t_HtmlTreeBuilder_tb",
    "Jsoup_46_workspace_objdump_d4j_full_jsoup_46_src_main_java_org_jsoup_nodes_Entities_java_void_escape_StringBuilder_accum_String_string_Document_OutputSettings_out_boolean_inAttribute_boolean_normaliseWhite_boolean_stripLeadingWhite",
)
MINI_VALIDATION_SAMPLING_MODE = "deterministic_cap"
MINI_VALIDATION_LIMIT = 30
MINI_VALIDATION_SAMPLING_SEED = 42


@dataclass(frozen=True)
class ExpectoVariant:
    solver: str
    n_completions: int
    max_attempts: int = 3
    use_test_cases: bool = True
    use_memo: bool = True
    check_unsat: bool = True
    dsl: bool = True


@dataclass(frozen=True)
class ArtifactLayout:
    output_root: Path
    profile_name: str

    @property
    def profile_root(self) -> Path:
        return self.output_root / self.profile_name

    @property
    def runs_root(self) -> Path:
        return self.profile_root / "runs"

    @property
    def figures_root(self) -> Path:
        return self.profile_root / "figures"

    @property
    def configs_root(self) -> Path:
        return self.figures_root / "configs"


@dataclass(frozen=True)
class ExperimentUnit:
    id: str
    rq: str
    benchmark: str
    variant: str
    run_dir: Path
    command: tuple[str, ...]
    marker_kind: str
    cleanup_smt: bool = False

    def is_complete(self) -> bool:
        if self.marker_kind == "expecto":
            return (self.run_dir / "evaluation_result" / "manifest.json").exists()
        if self.marker_kind == "nl2_evalplus":
            return any(self.run_dir.rglob("aggregated_result.json"))
        if self.marker_kind == "nl2_defects4j":
            return (self.run_dir / "validation" / "aggregated.json").exists()
        raise ValueError(f"Unsupported marker kind: {self.marker_kind}")


EXPECTO_VARIANTS = {
    "mono": ExpectoVariant(
        solver="monolithic",
        n_completions=1,
        use_test_cases=True,
        use_memo=True,
    ),
    "topdown": ExpectoVariant(
        solver="tree_search",
        n_completions=1,
        use_test_cases=True,
        use_memo=True,
    ),
    "ts": ExpectoVariant(
        solver="tree_search",
        n_completions=3,
        use_test_cases=True,
        use_memo=True,
    ),
    "without_tc": ExpectoVariant(
        solver="tree_search",
        n_completions=3,
        use_test_cases=False,
        use_memo=True,
    ),
    "without_smt": ExpectoVariant(
        solver="tree_search",
        n_completions=3,
        use_test_cases=False,
        use_memo=True,
        check_unsat=False,
    ),
}

RQ_TARGET_VARIANTS = {
    "rq1": {"ts", "nl2_base", "nl2_simple"},
    "rq2": {"mono", "topdown", "ts"},
    "rq3": {"ts", "without_tc", "without_smt"},
    "rq4": {"expecto", "nl2_base", "nl2_simple"},
}


def _click_path(path: Path) -> str:
    return str(path)


def _run_dir(layout: ArtifactLayout, benchmark: str, variant: str) -> Path:
    return layout.runs_root / benchmark / variant


def _dedupe_units(units: Iterable[ExperimentUnit]) -> list[ExperimentUnit]:
    ordered: dict[str, ExperimentUnit] = {}
    for unit in units:
        ordered.setdefault(unit.id, unit)
    return list(ordered.values())


def _serialize_sample_ids(sample_ids: Sequence[str] | None) -> str | None:
    if not sample_ids:
        return None
    return ",".join(sample_ids)


def _parse_sample_ids(sample_ids: str | None) -> list[str] | None:
    if sample_ids is None:
        return None
    parsed = [sample_id.strip() for sample_id in sample_ids.split(",") if sample_id.strip()]
    return parsed or None


def _resolve_expecto_variant(
    variant_name: str,
    *,
    n_completions_override: int | None = None,
    max_attempts_override: int | None = None,
) -> ExpectoVariant:
    variant = EXPECTO_VARIANTS[variant_name]
    if n_completions_override is None and max_attempts_override is None:
        return variant
    return ExpectoVariant(
        solver=variant.solver,
        n_completions=(
            variant.n_completions
            if n_completions_override is None
            else n_completions_override
        ),
        max_attempts=(
            variant.max_attempts
            if max_attempts_override is None
            else max_attempts_override
        ),
        use_test_cases=variant.use_test_cases,
        use_memo=variant.use_memo,
        check_unsat=variant.check_unsat,
        dsl=variant.dsl,
    )


def _validation_sampling_kwargs(validation_limit: int | None) -> dict[str, int | str | None]:
    if validation_limit is None:
        return {
            "validation_sampling_mode": None,
            "validation_positive_cap": None,
            "validation_negative_cap": None,
            "validation_sampling_seed": None,
        }
    return {
        "validation_sampling_mode": MINI_VALIDATION_SAMPLING_MODE,
        "validation_positive_cap": validation_limit,
        "validation_negative_cap": validation_limit,
        "validation_sampling_seed": MINI_VALIDATION_SAMPLING_SEED,
    }


def _append_validation_sampling_args(
    args: list[str],
    *,
    validation_sampling_mode: str | None,
    validation_positive_cap: int | None,
    validation_negative_cap: int | None,
    validation_sampling_seed: int | None,
) -> None:
    if validation_sampling_mode is None:
        return
    args.extend(["--validation-sampling-mode", validation_sampling_mode])
    if validation_positive_cap is not None:
        args.extend(["--validation-positive-cap", str(validation_positive_cap)])
    if validation_negative_cap is not None:
        args.extend(["--validation-negative-cap", str(validation_negative_cap)])
    if validation_sampling_seed is not None:
        args.extend(["--validation-sampling-seed", str(validation_sampling_seed)])


def _build_expecto_evalplus_command(
    benchmark: str,
    variant_name: str,
    run_dir: Path,
    limit: int | None,
    sample_ids: Sequence[str] | None = None,
    validation_sampling_mode: str | None = None,
    validation_positive_cap: int | None = None,
    validation_negative_cap: int | None = None,
    validation_sampling_seed: int | None = None,
    expecto_n_completions: int | None = None,
    expecto_max_attempts: int | None = None,
) -> tuple[str, ...]:
    variant = _resolve_expecto_variant(
        variant_name,
        n_completions_override=expecto_n_completions,
        max_attempts_override=expecto_max_attempts,
    )
    script_path = EVALPLUS_RUNNERS[benchmark]
    args: list[str] = [
        PYTHON_BIN,
        _click_path(script_path),
        "--solver",
        variant.solver,
        "--exp-name",
        run_dir.name,
        "--base_dir",
        _click_path(run_dir.parent),
        "--n_completions",
        str(variant.n_completions),
        "--max_attempts",
        str(variant.max_attempts),
    ]
    if variant.dsl:
        args.append("--dsl")
    if variant.use_test_cases:
        args.append("--use_test_cases")
    if variant.use_memo:
        args.append("--use_memo")
    if not variant.check_unsat:
        args.append("--no_check_unsat")
    serialized_sample_ids = _serialize_sample_ids(sample_ids)
    if serialized_sample_ids is not None:
        args.extend(["--sample-ids", serialized_sample_ids])
    elif limit is not None:
        args.extend(["--limit", str(limit)])
    _append_validation_sampling_args(
        args,
        validation_sampling_mode=validation_sampling_mode,
        validation_positive_cap=validation_positive_cap,
        validation_negative_cap=validation_negative_cap,
        validation_sampling_seed=validation_sampling_seed,
    )
    return tuple(args)


def _build_nl2_evalplus_command(
    benchmark: str,
    variant_name: str,
    run_dir: Path,
    limit: int | None,
    sample_ids: Sequence[str] | None = None,
    validation_sampling_mode: str | None = None,
    validation_positive_cap: int | None = None,
    validation_negative_cap: int | None = None,
    validation_sampling_seed: int | None = None,
) -> tuple[str, ...]:
    nl2_variant = "base" if variant_name == "nl2_base" else "simple"
    args = [
        PYTHON_BIN,
        _click_path(NL2_EVALPLUS_RUNNER),
        "--benchmark",
        benchmark,
        "--output-root",
        _click_path(run_dir),
        "--variant",
        nl2_variant,
    ]
    serialized_sample_ids = _serialize_sample_ids(sample_ids)
    if serialized_sample_ids is not None:
        args.extend(["--sample-ids", serialized_sample_ids])
    elif limit is not None:
        args.extend(["--limit", str(limit)])
    _append_validation_sampling_args(
        args,
        validation_sampling_mode=validation_sampling_mode,
        validation_positive_cap=validation_positive_cap,
        validation_negative_cap=validation_negative_cap,
        validation_sampling_seed=validation_sampling_seed,
    )
    return tuple(args)


def _build_defects4j_expecto_command(
    run_dir: Path,
    limit: int | None,
    sample_ids: Sequence[str] | None = None,
    validation_sampling_mode: str | None = None,
    validation_positive_cap: int | None = None,
    validation_negative_cap: int | None = None,
    validation_sampling_seed: int | None = None,
    expecto_n_completions: int | None = None,
    expecto_max_attempts: int | None = None,
) -> tuple[str, ...]:
    args = [
        PYTHON_BIN,
        _click_path(DEFECTS4J_EXPECTO_RUNNER),
        "--exp-name",
        run_dir.name,
        "--base_dir",
        _click_path(run_dir.parent),
        "--n_completions",
        str(3 if expecto_n_completions is None else expecto_n_completions),
        "--max_attempts",
        str(3 if expecto_max_attempts is None else expecto_max_attempts),
        "--dsl",
        "--use_test_cases",
    ]
    serialized_sample_ids = _serialize_sample_ids(sample_ids)
    if serialized_sample_ids is not None:
        args.extend(["--sample-ids", serialized_sample_ids])
    elif limit is not None:
        args.extend(["--limit", str(limit)])
    _append_validation_sampling_args(
        args,
        validation_sampling_mode=validation_sampling_mode,
        validation_positive_cap=validation_positive_cap,
        validation_negative_cap=validation_negative_cap,
        validation_sampling_seed=validation_sampling_seed,
    )
    return tuple(args)


def _build_defects4j_nl2_command(
    variant_name: str,
    run_dir: Path,
    limit: int | None,
    sample_ids: Sequence[str] | None = None,
) -> tuple[str, ...]:
    nl2_variant = "base" if variant_name == "nl2_base" else "simple"
    args = [
        PYTHON_BIN,
        _click_path(DEFECTS4J_NL2_RUNNER),
        "--output-dir",
        _click_path(run_dir),
        "--variant",
        nl2_variant,
    ]
    serialized_sample_ids = _serialize_sample_ids(sample_ids)
    if serialized_sample_ids is not None:
        args.extend(["--sample-ids", serialized_sample_ids])
    elif limit is not None:
        args.extend(["--limit", str(limit)])
    return tuple(args)


def _make_evalplus_expecto_unit(
    layout: ArtifactLayout,
    benchmark: str,
    variant_name: str,
    rq: str,
    limit: int | None,
    sample_ids: Sequence[str] | None = None,
    validation_sampling_mode: str | None = None,
    validation_positive_cap: int | None = None,
    validation_negative_cap: int | None = None,
    validation_sampling_seed: int | None = None,
    expecto_n_completions: int | None = None,
    expecto_max_attempts: int | None = None,
) -> ExperimentUnit:
    run_dir = _run_dir(layout, benchmark, variant_name)
    return ExperimentUnit(
        id=f"{benchmark}:{variant_name}",
        rq=rq,
        benchmark=benchmark,
        variant=variant_name,
        run_dir=run_dir,
        command=_build_expecto_evalplus_command(
            benchmark,
            variant_name,
            run_dir,
            limit,
            sample_ids,
            validation_sampling_mode,
            validation_positive_cap,
            validation_negative_cap,
            validation_sampling_seed,
            expecto_n_completions,
            expecto_max_attempts,
        ),
        marker_kind="expecto",
        cleanup_smt=True,
    )


def _make_evalplus_nl2_unit(
    layout: ArtifactLayout,
    benchmark: str,
    variant_name: str,
    rq: str,
    limit: int | None,
    sample_ids: Sequence[str] | None = None,
    validation_sampling_mode: str | None = None,
    validation_positive_cap: int | None = None,
    validation_negative_cap: int | None = None,
    validation_sampling_seed: int | None = None,
) -> ExperimentUnit:
    run_dir = _run_dir(layout, benchmark, variant_name)
    return ExperimentUnit(
        id=f"{benchmark}:{variant_name}",
        rq=rq,
        benchmark=benchmark,
        variant=variant_name,
        run_dir=run_dir,
        command=_build_nl2_evalplus_command(
            benchmark,
            variant_name,
            run_dir,
            limit,
            sample_ids,
            validation_sampling_mode,
            validation_positive_cap,
            validation_negative_cap,
            validation_sampling_seed,
        ),
        marker_kind="nl2_evalplus",
    )


def _make_defects4j_expecto_unit(
    layout: ArtifactLayout,
    rq: str,
    limit: int | None,
    sample_ids: Sequence[str] | None = None,
    validation_sampling_mode: str | None = None,
    validation_positive_cap: int | None = None,
    validation_negative_cap: int | None = None,
    validation_sampling_seed: int | None = None,
    expecto_n_completions: int | None = None,
    expecto_max_attempts: int | None = None,
) -> ExperimentUnit:
    run_dir = _run_dir(layout, "defects4j", "expecto")
    return ExperimentUnit(
        id="defects4j:expecto",
        rq=rq,
        benchmark="defects4j",
        variant="expecto",
        run_dir=run_dir,
        command=_build_defects4j_expecto_command(
            run_dir,
            limit,
            sample_ids,
            validation_sampling_mode,
            validation_positive_cap,
            validation_negative_cap,
            validation_sampling_seed,
            expecto_n_completions,
            expecto_max_attempts,
        ),
        marker_kind="expecto",
        cleanup_smt=True,
    )


def _make_defects4j_nl2_unit(
    layout: ArtifactLayout,
    variant_name: str,
    rq: str,
    limit: int | None,
    sample_ids: Sequence[str] | None = None,
) -> ExperimentUnit:
    run_dir = _run_dir(layout, "defects4j", variant_name)
    return ExperimentUnit(
        id=f"defects4j:{variant_name}",
        rq=rq,
        benchmark="defects4j",
        variant=variant_name,
        run_dir=run_dir,
        command=_build_defects4j_nl2_command(
            variant_name,
            run_dir,
            limit,
            sample_ids,
        ),
        marker_kind="nl2_defects4j",
    )


def build_rq_units(
    layout: ArtifactLayout,
    rq: str,
    *,
    limit: int | None = None,
    evalplus_sample_ids: dict[str, Sequence[str]] | None = None,
    defects4j_limit: int | None = None,
    defects4j_sample_ids: Sequence[str] | None = None,
    validation_sampling_mode: str | None = None,
    validation_positive_cap: int | None = None,
    validation_negative_cap: int | None = None,
    validation_sampling_seed: int | None = None,
    expecto_n_completions: int | None = None,
    expecto_max_attempts: int | None = None,
) -> list[ExperimentUnit]:
    if rq not in RQ_CHOICES:
        raise click.ClickException(f"Unsupported RQ: {rq}")

    units: list[ExperimentUnit] = []
    if rq == "rq1":
        for benchmark in EVALPLUS_BENCHMARKS:
            sample_ids = (
                evalplus_sample_ids.get(benchmark) if evalplus_sample_ids else None
            )
            units.extend(
                [
                    _make_evalplus_expecto_unit(
                        layout, benchmark, "ts", rq, limit, sample_ids, validation_sampling_mode, validation_positive_cap, validation_negative_cap, validation_sampling_seed, expecto_n_completions, expecto_max_attempts
                    ),
                    _make_evalplus_nl2_unit(
                        layout, benchmark, "nl2_base", rq, limit, sample_ids, validation_sampling_mode, validation_positive_cap, validation_negative_cap, validation_sampling_seed
                    ),
                    _make_evalplus_nl2_unit(
                        layout, benchmark, "nl2_simple", rq, limit, sample_ids, validation_sampling_mode, validation_positive_cap, validation_negative_cap, validation_sampling_seed
                    ),
                ]
            )
    elif rq == "rq2":
        for benchmark in EVALPLUS_BENCHMARKS:
            sample_ids = (
                evalplus_sample_ids.get(benchmark) if evalplus_sample_ids else None
            )
            units.extend(
                [
                    _make_evalplus_expecto_unit(
                        layout, benchmark, "mono", rq, limit, sample_ids, validation_sampling_mode, validation_positive_cap, validation_negative_cap, validation_sampling_seed, expecto_n_completions, expecto_max_attempts
                    ),
                    _make_evalplus_expecto_unit(
                        layout, benchmark, "topdown", rq, limit, sample_ids, validation_sampling_mode, validation_positive_cap, validation_negative_cap, validation_sampling_seed, expecto_n_completions, expecto_max_attempts
                    ),
                    _make_evalplus_expecto_unit(
                        layout, benchmark, "ts", rq, limit, sample_ids, validation_sampling_mode, validation_positive_cap, validation_negative_cap, validation_sampling_seed, expecto_n_completions, expecto_max_attempts
                    ),
                ]
            )
    elif rq == "rq3":
        for benchmark in EVALPLUS_BENCHMARKS:
            sample_ids = (
                evalplus_sample_ids.get(benchmark) if evalplus_sample_ids else None
            )
            units.extend(
                [
                    _make_evalplus_expecto_unit(
                        layout, benchmark, "ts", rq, limit, sample_ids, validation_sampling_mode, validation_positive_cap, validation_negative_cap, validation_sampling_seed, expecto_n_completions, expecto_max_attempts
                    ),
                    _make_evalplus_expecto_unit(
                        layout, benchmark, "without_tc", rq, limit, sample_ids, validation_sampling_mode, validation_positive_cap, validation_negative_cap, validation_sampling_seed, expecto_n_completions, expecto_max_attempts
                    ),
                    _make_evalplus_expecto_unit(
                        layout, benchmark, "without_smt", rq, limit, sample_ids, validation_sampling_mode, validation_positive_cap, validation_negative_cap, validation_sampling_seed, expecto_n_completions, expecto_max_attempts
                    ),
                ]
            )
    elif rq == "rq4":
        effective_defects4j_limit = (
            defects4j_limit if defects4j_limit is not None else limit
        )
        units.extend(
            [
                _make_defects4j_expecto_unit(
                    layout,
                    rq,
                    effective_defects4j_limit,
                    defects4j_sample_ids,
                    validation_sampling_mode,
                    validation_positive_cap,
                    validation_negative_cap,
                    validation_sampling_seed,
                    expecto_n_completions,
                    expecto_max_attempts,
                ),
                _make_defects4j_nl2_unit(
                    layout,
                    "nl2_base",
                    rq,
                    effective_defects4j_limit,
                    defects4j_sample_ids,
                ),
                _make_defects4j_nl2_unit(
                    layout,
                    "nl2_simple",
                    rq,
                    effective_defects4j_limit,
                    defects4j_sample_ids,
                ),
            ]
        )
    return _dedupe_units(units)


def build_full_units(
    layout: ArtifactLayout,
    *,
    limit: int | None = None,
) -> list[ExperimentUnit]:
    units: list[ExperimentUnit] = []
    for rq in RQ_CHOICES:
        units.extend(build_rq_units(layout, rq, limit=limit))
    return _dedupe_units(units)


def build_target_unit(
    layout: ArtifactLayout,
    *,
    benchmark: str,
    family: str,
    variant: str,
    limit: int | None = None,
    sample_ids: Sequence[str] | None = None,
) -> ExperimentUnit:
    if family not in RQ_CHOICES:
        raise click.ClickException(f"Unsupported family: {family}")
    if variant not in RQ_TARGET_VARIANTS[family]:
        raise click.ClickException(
            f"Variant '{variant}' is not valid for family '{family}'"
        )

    if family == "rq4":
        if benchmark != "defects4j":
            raise click.ClickException(
                "RQ4 target mode only supports benchmark=defects4j"
            )
        if variant == "expecto":
            return _make_defects4j_expecto_unit(layout, family, limit, sample_ids)
        return _make_defects4j_nl2_unit(layout, variant, family, limit, sample_ids)

    if benchmark not in EVALPLUS_BENCHMARKS:
        raise click.ClickException(
            "RQ1-RQ3 target mode supports benchmark=apps or benchmark=humaneval_plus"
        )
    if variant.startswith("nl2_"):
        return _make_evalplus_nl2_unit(
            layout, benchmark, variant, family, limit, sample_ids
        )
    return _make_evalplus_expecto_unit(
        layout, benchmark, variant, family, limit, sample_ids
    )


def _format_command(args: Sequence[str]) -> str:
    return " ".join(args)


def _echo_unit_status(unit: ExperimentUnit, status: str) -> None:
    benchmark_label = BENCHMARK_LABELS.get(unit.benchmark, unit.benchmark)
    click.echo(f"[{status}] {unit.rq} {benchmark_label} {unit.variant}")


def _ensure_dir(path: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.mkdir(parents=True, exist_ok=True)


def _remove_tree(path: Path, *, dry_run: bool) -> None:
    if not path.exists():
        return
    if dry_run:
        click.echo(f"Would remove existing directory: {path}")
        return
    shutil.rmtree(path)


def _run_subprocess(args: Sequence[str], *, dry_run: bool) -> None:
    click.echo(_format_command(args))
    if dry_run:
        return
    subprocess.run(args, cwd=PROJECT_ROOT, check=True)


def _cleanup_smt_processes(*, dry_run: bool) -> None:
    if shutil.which("pkill") is None:
        return
    args = ("pkill", "-f", "smt")
    if dry_run:
        click.echo(_format_command(args))
        return
    subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def execute_units(
    units: Sequence[ExperimentUnit],
    *,
    force: bool,
    dry_run: bool,
) -> None:
    for unit in units:
        if unit.is_complete() and not force:
            _echo_unit_status(unit, "skip")
            continue

        if unit.run_dir.exists():
            _remove_tree(unit.run_dir, dry_run=dry_run)

        _ensure_dir(unit.run_dir.parent, dry_run=dry_run)
        _echo_unit_status(unit, "run")
        _run_subprocess(unit.command, dry_run=dry_run)

        if unit.cleanup_smt:
            _cleanup_smt_processes(dry_run=dry_run)


def _write_json(path: Path, payload: object, *, dry_run: bool) -> None:
    if dry_run:
        click.echo(f"Would write config: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _figure_output_dir(layout: ArtifactLayout, rq: str) -> Path:
    return layout.figures_root / rq


def _evalplus_config_payload(
    layout: ArtifactLayout,
    required_fields: dict[str, str],
) -> dict[str, dict[str, str]]:
    payload: dict[str, dict[str, str]] = {}
    for benchmark in EVALPLUS_BENCHMARKS:
        payload[BENCHMARK_LABELS[benchmark]] = {
            field_name: _click_path(_run_dir(layout, benchmark, variant_name))
            for field_name, variant_name in required_fields.items()
        }
    return payload


def _build_rq1_figure_config(layout: ArtifactLayout) -> dict[str, dict[str, str]]:
    return _evalplus_config_payload(
        layout,
        {
            "ts": "ts",
            "nl2_postcond_base": "nl2_base",
            "nl2_postcond_simple": "nl2_simple",
        },
    )


def _build_rq2_figure_config(layout: ArtifactLayout) -> dict[str, dict[str, str]]:
    return _evalplus_config_payload(
        layout,
        {
            "mono": "mono",
            "topdown": "topdown",
            "ts": "ts",
        },
    )


def _build_rq3_figure_config(layout: ArtifactLayout) -> dict[str, dict[str, str]]:
    return _evalplus_config_payload(
        layout,
        {
            "ts": "ts",
            "without_tc": "without_tc",
            "without_smt": "without_smt",
        },
    )


def _build_rq4_figure_config(layout: ArtifactLayout) -> dict[str, str]:
    return {
        "benchmark": BENCHMARK_LABELS["defects4j"],
        "expecto": _click_path(_run_dir(layout, "defects4j", "expecto")),
        "nl2_postcond_base": _click_path(_run_dir(layout, "defects4j", "nl2_base")),
        "nl2_postcond_simple": _click_path(_run_dir(layout, "defects4j", "nl2_simple")),
    }


def _figure_expected_outputs(layout: ArtifactLayout, rq: str) -> tuple[Path, ...]:
    output_dir = _figure_output_dir(layout, rq)
    if rq == "rq1":
        return (
            output_dir / "evaluation.rq1.table.tex",
            output_dir / "evaluation.rq1.table.pdf",
            output_dir / "evaluation.thresholds.pdf",
        )
    if rq == "rq2":
        return (
            output_dir / "evaluation.rq2.table.tex",
            output_dir / "evaluation.rq2.table.pdf",
            output_dir / "evaluation.rq2.pdf",
        )
    if rq == "rq3":
        return (
            output_dir / "evaluation.rq3.testcase.table.tex",
            output_dir / "evaluation.rq3.testcase.table.pdf",
            output_dir / "evaluation.rq3.testcase.pdf",
        )
    if rq == "rq4":
        return (
            output_dir / "evaluation.rq4.defects4j.table.tex",
            output_dir / "evaluation.rq4.defects4j.table.pdf",
        )
    raise click.ClickException(f"Unsupported RQ: {rq}")


def generate_figures_for_rq(
    layout: ArtifactLayout,
    rq: str,
    *,
    force: bool,
    dry_run: bool,
) -> None:
    config_path = layout.configs_root / f"{rq}.json"
    output_dir = _figure_output_dir(layout, rq)
    expected_outputs = _figure_expected_outputs(layout, rq)

    if rq == "rq1":
        payload = _build_rq1_figure_config(layout)
        figure_args = (
            PYTHON_BIN,
            _click_path(FIGURE_GENERATOR),
            "draw-rq1-fig",
            _click_path(config_path),
            _click_path(output_dir),
        )
    elif rq == "rq2":
        payload = _build_rq2_figure_config(layout)
        figure_args = (
            PYTHON_BIN,
            _click_path(FIGURE_GENERATOR),
            "draw-rq2-fig",
            _click_path(config_path),
            _click_path(output_dir),
        )
    elif rq == "rq3":
        payload = _build_rq3_figure_config(layout)
        figure_args = (
            PYTHON_BIN,
            _click_path(FIGURE_GENERATOR),
            "draw-rq3-fig",
            _click_path(config_path),
            _click_path(output_dir),
        )
    elif rq == "rq4":
        payload = _build_rq4_figure_config(layout)
        figure_args = (
            PYTHON_BIN,
            _click_path(FIGURE_GENERATOR),
            "draw-rq4-fig",
            _click_path(config_path),
            _click_path(output_dir),
        )
    else:
        raise click.ClickException(f"Unsupported RQ: {rq}")

    _write_json(config_path, payload, dry_run=dry_run)
    if not force and all(path.exists() for path in expected_outputs):
        click.echo(f"[skip] figures {rq} -> {output_dir}")
        return
    _ensure_dir(output_dir, dry_run=dry_run)
    click.echo(f"[figure] {rq} -> {output_dir}")
    _run_subprocess(figure_args, dry_run=dry_run)


def _layout(output_root: Path, profile_name: str) -> ArtifactLayout:
    return ArtifactLayout(output_root=output_root, profile_name=profile_name)


def _print_summary(layout: ArtifactLayout) -> None:
    click.echo(f"Profile root: {layout.profile_root}")
    click.echo(f"Runs root: {layout.runs_root}")
    click.echo(f"Figures root: {layout.figures_root}")


def _run_profile_by_rq(
    layout: ArtifactLayout,
    *,
    force: bool,
    dry_run: bool,
    limit: int | None = None,
) -> None:
    for rq in RQ_CHOICES:
        units = build_rq_units(layout, rq, limit=limit)
        execute_units(units, force=force, dry_run=dry_run)
        generate_figures_for_rq(layout, rq, force=force, dry_run=dry_run)


def _run_mini_profile_by_rq(
    layout: ArtifactLayout,
    *,
    force: bool,
    dry_run: bool,
) -> None:
    for rq in RQ_CHOICES:
        units = build_rq_units(
            layout,
            rq,
            evalplus_sample_ids=MINI_EVALPLUS_SAMPLE_IDS,
            defects4j_sample_ids=MINI_DEFECTS4J_SAMPLE_IDS,
            **_validation_sampling_kwargs(MINI_VALIDATION_LIMIT),
        )
        execute_units(units, force=force, dry_run=dry_run)
        generate_figures_for_rq(layout, rq, force=force, dry_run=dry_run)


@click.group()
def cli() -> None:
    """Reviewer-facing artifact runner."""


@cli.command()
@click.option(
    "--output-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_OUTPUT_ROOT,
    show_default=True,
)
@click.option("--force", is_flag=True, help="Rerun completed experiment units.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing them.")
def full(output_root: Path, force: bool, dry_run: bool) -> None:
    """Run all experiments required for RQ1-RQ4."""

    layout = _layout(output_root, STANDARD_PROFILE_NAME)
    _print_summary(layout)
    _run_profile_by_rq(layout, force=force, dry_run=dry_run)


@cli.command()
@click.option(
    "--rq",
    type=click.Choice(RQ_CHOICES),
    required=True,
    help="Which research question to run.",
)
@click.option(
    "--output-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_OUTPUT_ROOT,
    show_default=True,
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=None,
    help="Optional sample limit for the selected RQ.",
)
@click.option(
    "--validation-limit",
    type=click.IntRange(min=1),
    default=None,
    help="Optional validation test-case cap applied to both positive and negative validation sets.",
)
@click.option(
    "--expecto-n-completions",
    type=click.IntRange(min=1),
    default=None,
    help="Optional override for Expecto --n_completions in this run.",
)
@click.option(
    "--expecto-max-attempts",
    type=click.IntRange(min=1),
    default=None,
    help="Optional override for Expecto --max_attempts in this run.",
)
@click.option(
    "--mini",
    "mini_mode",
    is_flag=True,
    help="Run this RQ with the fixed mini profile under mini/ outputs.",
)
@click.option("--force", is_flag=True, help="Rerun completed experiment units.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing them.")
def rq(
    rq: str,
    output_root: Path,
    limit: int | None,
    validation_limit: int | None,
    expecto_n_completions: int | None,
    expecto_max_attempts: int | None,
    mini_mode: bool,
    force: bool,
    dry_run: bool,
) -> None:
    """Run one research question."""

    if mini_mode and limit is not None:
        raise click.UsageError("--mini cannot be combined with --limit.")
    if mini_mode and validation_limit is not None:
        raise click.UsageError("--mini cannot be combined with --validation-limit.")

    layout = _layout(
        output_root,
        MINI_PROFILE_NAME if mini_mode else STANDARD_PROFILE_NAME,
    )
    _print_summary(layout)
    build_kwargs: dict[str, object] = {
        "expecto_n_completions": expecto_n_completions,
        "expecto_max_attempts": expecto_max_attempts,
    }
    if mini_mode:
        build_kwargs["evalplus_sample_ids"] = MINI_EVALPLUS_SAMPLE_IDS
        build_kwargs["defects4j_sample_ids"] = MINI_DEFECTS4J_SAMPLE_IDS
        build_kwargs.update(_validation_sampling_kwargs(MINI_VALIDATION_LIMIT))
    else:
        build_kwargs["limit"] = limit
        build_kwargs.update(_validation_sampling_kwargs(validation_limit))

    units = build_rq_units(
        layout,
        rq,
        **build_kwargs,
    )
    execute_units(units, force=force, dry_run=dry_run)
    generate_figures_for_rq(layout, rq, force=force, dry_run=dry_run)


@cli.command()
@click.option(
    "--output-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_OUTPUT_ROOT,
    show_default=True,
)
@click.option("--force", is_flag=True, help="Rerun completed experiment units.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing them.")
def mini(
    output_root: Path,
    force: bool,
    dry_run: bool,
) -> None:
    """Run a faster fixed-sample mini profile."""

    layout = _layout(output_root, MINI_PROFILE_NAME)
    _print_summary(layout)
    _run_mini_profile_by_rq(layout, force=force, dry_run=dry_run)


@cli.command()
@click.option(
    "--benchmark",
    type=click.Choice(("apps", "humaneval_plus", "defects4j")),
    required=True,
)
@click.option(
    "--family",
    type=click.Choice(RQ_CHOICES),
    required=True,
    help="Target family/RQ the variant belongs to.",
)
@click.option(
    "--variant",
    type=click.Choice(
        (
            "mono",
            "topdown",
            "ts",
            "without_tc",
            "without_smt",
            "expecto",
            "nl2_base",
            "nl2_simple",
        )
    ),
    required=True,
)
@click.option(
    "--output-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_OUTPUT_ROOT,
    show_default=True,
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=None,
    help="Optional sample limit for the targeted run.",
)
@click.option(
    "--sample-ids",
    type=str,
    default=None,
    help="Comma-separated benchmark problem IDs to run.",
)
@click.option("--force", is_flag=True, help="Rerun the targeted experiment unit.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing them.")
def target(
    benchmark: str,
    family: str,
    variant: str,
    output_root: Path,
    limit: int | None,
    sample_ids: str | None,
    force: bool,
    dry_run: bool,
) -> None:
    """Run one benchmark-specific experiment target."""

    parsed_sample_ids = _parse_sample_ids(sample_ids)
    if limit is not None and parsed_sample_ids:
        raise click.UsageError("Use either --limit or --sample-ids, not both.")

    layout = _layout(output_root, STANDARD_PROFILE_NAME)
    _print_summary(layout)
    unit = build_target_unit(
        layout,
        benchmark=benchmark,
        family=family,
        variant=variant,
        limit=limit,
        sample_ids=parsed_sample_ids,
    )
    execute_units([unit], force=force, dry_run=dry_run)


if __name__ == "__main__":
    cli()
