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


def _build_expecto_evalplus_command(
    benchmark: str,
    variant_name: str,
    run_dir: Path,
    limit: int | None,
) -> tuple[str, ...]:
    variant = EXPECTO_VARIANTS[variant_name]
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
    if limit is not None:
        args.extend(["--limit", str(limit)])
    return tuple(args)


def _build_nl2_evalplus_command(
    benchmark: str,
    variant_name: str,
    run_dir: Path,
    limit: int | None,
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
    if limit is not None:
        args.extend(["--limit", str(limit)])
    return tuple(args)


def _build_defects4j_expecto_command(
    run_dir: Path,
    limit: int | None,
) -> tuple[str, ...]:
    args = [
        PYTHON_BIN,
        _click_path(DEFECTS4J_EXPECTO_RUNNER),
        "--exp-name",
        run_dir.name,
        "--base_dir",
        _click_path(run_dir.parent),
        "--n_completions",
        "3",
        "--max_attempts",
        "3",
        "--dsl",
        "--use_test_cases",
    ]
    if limit is not None:
        args.extend(["--limit", str(limit)])
    return tuple(args)


def _build_defects4j_nl2_command(
    variant_name: str,
    run_dir: Path,
    limit: int | None,
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
    if limit is not None:
        args.extend(["--limit", str(limit)])
    return tuple(args)


def _make_evalplus_expecto_unit(
    layout: ArtifactLayout,
    benchmark: str,
    variant_name: str,
    rq: str,
    limit: int | None,
) -> ExperimentUnit:
    run_dir = _run_dir(layout, benchmark, variant_name)
    return ExperimentUnit(
        id=f"{benchmark}:{variant_name}",
        rq=rq,
        benchmark=benchmark,
        variant=variant_name,
        run_dir=run_dir,
        command=_build_expecto_evalplus_command(
            benchmark, variant_name, run_dir, limit
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
) -> ExperimentUnit:
    run_dir = _run_dir(layout, benchmark, variant_name)
    return ExperimentUnit(
        id=f"{benchmark}:{variant_name}",
        rq=rq,
        benchmark=benchmark,
        variant=variant_name,
        run_dir=run_dir,
        command=_build_nl2_evalplus_command(benchmark, variant_name, run_dir, limit),
        marker_kind="nl2_evalplus",
    )


def _make_defects4j_expecto_unit(
    layout: ArtifactLayout,
    rq: str,
    limit: int | None,
) -> ExperimentUnit:
    run_dir = _run_dir(layout, "defects4j", "expecto")
    return ExperimentUnit(
        id="defects4j:expecto",
        rq=rq,
        benchmark="defects4j",
        variant="expecto",
        run_dir=run_dir,
        command=_build_defects4j_expecto_command(run_dir, limit),
        marker_kind="expecto",
        cleanup_smt=True,
    )


def _make_defects4j_nl2_unit(
    layout: ArtifactLayout,
    variant_name: str,
    rq: str,
    limit: int | None,
) -> ExperimentUnit:
    run_dir = _run_dir(layout, "defects4j", variant_name)
    return ExperimentUnit(
        id=f"defects4j:{variant_name}",
        rq=rq,
        benchmark="defects4j",
        variant=variant_name,
        run_dir=run_dir,
        command=_build_defects4j_nl2_command(variant_name, run_dir, limit),
        marker_kind="nl2_defects4j",
    )


def build_rq_units(
    layout: ArtifactLayout,
    rq: str,
    *,
    limit: int | None = None,
) -> list[ExperimentUnit]:
    if rq not in RQ_CHOICES:
        raise click.ClickException(f"Unsupported RQ: {rq}")

    units: list[ExperimentUnit] = []
    if rq == "rq1":
        for benchmark in EVALPLUS_BENCHMARKS:
            units.extend(
                [
                    _make_evalplus_expecto_unit(layout, benchmark, "ts", rq, limit),
                    _make_evalplus_nl2_unit(layout, benchmark, "nl2_base", rq, limit),
                    _make_evalplus_nl2_unit(layout, benchmark, "nl2_simple", rq, limit),
                ]
            )
    elif rq == "rq2":
        for benchmark in EVALPLUS_BENCHMARKS:
            units.extend(
                [
                    _make_evalplus_expecto_unit(layout, benchmark, "mono", rq, limit),
                    _make_evalplus_expecto_unit(
                        layout, benchmark, "topdown", rq, limit
                    ),
                    _make_evalplus_expecto_unit(layout, benchmark, "ts", rq, limit),
                ]
            )
    elif rq == "rq3":
        for benchmark in EVALPLUS_BENCHMARKS:
            units.extend(
                [
                    _make_evalplus_expecto_unit(layout, benchmark, "ts", rq, limit),
                    _make_evalplus_expecto_unit(
                        layout, benchmark, "without_tc", rq, limit
                    ),
                    _make_evalplus_expecto_unit(
                        layout, benchmark, "without_smt", rq, limit
                    ),
                ]
            )
    elif rq == "rq4":
        units.extend(
            [
                _make_defects4j_expecto_unit(layout, rq, limit),
                _make_defects4j_nl2_unit(layout, "nl2_base", rq, limit),
                _make_defects4j_nl2_unit(layout, "nl2_simple", rq, limit),
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
            return _make_defects4j_expecto_unit(layout, family, limit)
        return _make_defects4j_nl2_unit(layout, variant, family, limit)

    if benchmark not in EVALPLUS_BENCHMARKS:
        raise click.ClickException(
            "RQ1-RQ3 target mode supports benchmark=apps or benchmark=humaneval_plus"
        )
    if variant.startswith("nl2_"):
        return _make_evalplus_nl2_unit(layout, benchmark, variant, family, limit)
    return _make_evalplus_expecto_unit(layout, benchmark, variant, family, limit)


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
@click.option("--force", is_flag=True, help="Rerun completed experiment units.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing them.")
def rq(
    rq: str,
    output_root: Path,
    limit: int | None,
    force: bool,
    dry_run: bool,
) -> None:
    """Run one research question."""

    layout = _layout(output_root, STANDARD_PROFILE_NAME)
    _print_summary(layout)
    units = build_rq_units(layout, rq, limit=limit)
    execute_units(units, force=force, dry_run=dry_run)
    generate_figures_for_rq(layout, rq, force=force, dry_run=dry_run)


@cli.command()
@click.option(
    "--output-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_OUTPUT_ROOT,
    show_default=True,
)
@click.option(
    "--mini-limit",
    type=click.IntRange(min=1),
    default=5,
    show_default=True,
    help="Problem limit used for mini mode.",
)
@click.option("--force", is_flag=True, help="Rerun completed experiment units.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing them.")
def mini(
    output_root: Path,
    mini_limit: int,
    force: bool,
    dry_run: bool,
) -> None:
    """Run a faster trend-preserving mini profile."""

    layout = _layout(output_root, MINI_PROFILE_NAME)
    _print_summary(layout)
    _run_profile_by_rq(layout, force=force, dry_run=dry_run, limit=mini_limit)


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
@click.option("--force", is_flag=True, help="Rerun the targeted experiment unit.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing them.")
def target(
    benchmark: str,
    family: str,
    variant: str,
    output_root: Path,
    limit: int | None,
    force: bool,
    dry_run: bool,
) -> None:
    """Run one benchmark-specific experiment target."""

    layout = _layout(output_root, STANDARD_PROFILE_NAME)
    _print_summary(layout)
    unit = build_target_unit(
        layout,
        benchmark=benchmark,
        family=family,
        variant=variant,
        limit=limit,
    )
    execute_units([unit], force=force, dry_run=dry_run)


if __name__ == "__main__":
    cli()
