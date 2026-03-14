import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import click
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NL2POSTCOND_ROOT = PROJECT_ROOT / "nl-2-postcond" / "nl2postcondition_source_evalplus"
DATASETS_ROOT = PROJECT_ROOT / "datasets"
DEFAULT_SAVE_DIR = Path("/workspace/data")
TIMEOUT_SECONDS = 60 * 60 * 24 * 2

NL2POSTCOND_EXPERIMENTS = [
    {"config": "generateLLMSamplesSimple", "name": "Simple"},
    {"config": "generateLLMSamplesBase", "name": "Base"},
]
NL2POSTCOND_VARIANT_ALIASES = {
    "all": {"Simple", "Base"},
    "simple": {"Simple"},
    "base": {"Base"},
}

BCH_HUMANEVAL_PLUS = "humaneval_plus"
BCH_APPS = "apps"
BENCHMARK_ALIASES = {
    "humaneval": BCH_HUMANEVAL_PLUS,
    "humaneval_plus": BCH_HUMANEVAL_PLUS,
    "human_eval": BCH_HUMANEVAL_PLUS,
    "human-eval": BCH_HUMANEVAL_PLUS,
    "evalplus": BCH_HUMANEVAL_PLUS,
    "apps": BCH_APPS,
}
BENCHMARKS = {
    BCH_HUMANEVAL_PLUS: {
        "name": "humaneval",
        "output_dir": "humaneval/nl-2-postcond",
        "hydra_name": "evalplus",
        "dataset": DATASETS_ROOT / "human_eval_plus.json",
        "extra_overrides": [],
    },
    BCH_APPS: {
        "name": "apps",
        "output_dir": "apps/nl-2-postcond",
        "hydra_name": "apps",
        "dataset": DATASETS_ROOT / "apps.json",
        "extra_overrides": [f"benchmarks.location={DATASETS_ROOT / 'apps.json'}"],
    },
}


def get_benchmark_config(benchmark_name: str) -> dict[str, object]:
    benchmark_key = BENCHMARK_ALIASES.get(benchmark_name.lower())
    if benchmark_key is None:
        raise click.ClickException(f"Unsupported benchmark: {benchmark_name}")
    return BENCHMARKS[benchmark_key]


def select_nl2postcond_experiments(variant: str) -> list[dict[str, str]]:
    selected_names = NL2POSTCOND_VARIANT_ALIASES.get(variant.lower())
    if selected_names is None:
        raise click.ClickException(f"Unsupported NL2Postcond variant: {variant}")
    return [
        experiment
        for experiment in NL2POSTCOND_EXPERIMENTS
        if experiment["name"] in selected_names
    ]


def get_benchmark_overrides(
    benchmark: dict[str, object],
    limit: int | None = None,
    test_mode: bool = False,
) -> list[str]:
    overrides = list(cast(list[str], benchmark["extra_overrides"]))
    effective_limit = 1 if test_mode else limit
    if effective_limit is None or effective_limit < 1:
        return overrides

    if benchmark["hydra_name"] == "evalplus":
        run_only = ",".join(str(index) for index in range(effective_limit))
        overrides.extend(
            [
                "benchmarks.run_all=false",
                "benchmarks.run_range=false",
                f"benchmarks.run_only=[{run_only}]",
            ]
        )
        return overrides

    if benchmark["hydra_name"] == "apps":
        overrides.extend(
            [
                "benchmarks.run_all=false",
                "benchmarks.run_range=true",
                "benchmarks.run_start='0'",
                f"benchmarks.run_end='{effective_limit - 1}'",
            ]
        )
        return overrides

    return overrides


def load_env() -> dict[str, str]:
    load_dotenv(PROJECT_ROOT / ".env")
    env = os.environ.copy()
    openai_key = env.get("OPENAI_KEY") or env.get("OPENAI_API_KEY")
    if not openai_key:
        raise click.ClickException(
            "Missing OpenAI key. Set OPENAI_API_KEY or OPENAI_KEY in the project root .env file."
        )
    env["OPENAI_KEY"] = openai_key
    return env


def log_command(args: list[str]) -> None:
    print("===========Begin===========")
    print(" ".join(args))


def log_ignored_nl2postcond_options(
    debug: bool,
    dev: bool,
    n_completions: int,
    max_attempts: int,
    dsl: bool,
    threshold: float,
    use_test_cases: bool,
    use_memo: bool,
    check_unsat: bool,
) -> None:
    ignored_options: list[str] = []

    if debug:
        ignored_options.append("--debug")
    if dev:
        ignored_options.append("--dev")
    if dsl:
        ignored_options.append("--dsl")
    if n_completions != 1:
        ignored_options.append(f"--n_completions={n_completions}")
    if max_attempts != 5:
        ignored_options.append(f"--max_attempts={max_attempts}")
    if threshold != 0.5:
        ignored_options.append(f"--threshold={threshold}")
    if use_test_cases:
        ignored_options.append("--use_test_cases")
    if use_memo:
        ignored_options.append("--use_memo")
    if not check_unsat:
        ignored_options.append("--no_check_unsat")

    if ignored_options:
        print(
            "Ignoring Expecto-only options for solver=nl2postcond: "
            + ", ".join(ignored_options)
        )


def run_command(args: list[str], env: dict[str, str]) -> None:
    log_command(args)
    try:
        subprocess.run(
            args,
            cwd=NL2POSTCOND_ROOT,
            env=env,
            check=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            f"Command failed with exit code {exc.returncode}"
        ) from exc
    print("===========Done===========")


def get_latest_run_dir(parent_dir: Path) -> Path:
    run_dirs = sorted(
        (path for path in parent_dir.glob("*/*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
    )
    if not run_dirs:
        raise click.ClickException(f"No Hydra run directory found under {parent_dir}")
    return run_dirs[-1]


def get_default_worker_count() -> int:
    return max(1, int((os.cpu_count() or 2) * 0.75))


def run_benchmark_experiment(
    benchmark: dict[str, object],
    output_root: Path,
    env: dict[str, str],
    limit: int | None = None,
    workers: int | None = None,
    variant: str = "all",
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    python_bin = sys.executable
    worker_count = workers if workers is not None else get_default_worker_count()
    benchmark_overrides = get_benchmark_overrides(benchmark, limit=limit)

    for experiment in select_nl2postcond_experiments(variant):
        generation_root = output_root / "llm_gen_outputs" / experiment["name"]
        preprocess_root = (
            output_root / "response_preprocess_outputs" / experiment["name"]
        )

        generation_args = [
            python_bin,
            "llm_sample_generator.py",
            f"experiment={experiment['config']}",
            f"benchmarks={benchmark['hydra_name']}",
            f"hydra.run.dir={generation_root}/${{now:%Y-%m-%d}}/${{now:%H-%M-%S}}",
            *benchmark_overrides,
        ]
        run_command(generation_args, env)
        generation_dir = get_latest_run_dir(generation_root)

        preprocess_args = [
            python_bin,
            "response_preprocessing.py",
            "experiment=preprocessSamples.yaml",
            f"experiment.samplesFolder={generation_dir}",
            f"benchmarks={benchmark['hydra_name']}",
            f"experiment.exp_name={experiment['name']}",
            f"hydra.run.dir={preprocess_root}/${{now:%Y-%m-%d}}/${{now:%H-%M-%S}}",
            *benchmark_overrides,
        ]
        run_command(preprocess_args, env)
        preprocess_dir = get_latest_run_dir(preprocess_root)

        evaluation_args = [
            python_bin,
            "evaluation.py",
            str(preprocess_dir),
            "--dataset",
            str(benchmark["dataset"]),
            "--exp_name",
            experiment["name"],
            "--workers",
            str(worker_count),
        ]
        run_command(evaluation_args, env)


def run_nl2postcond_for_task(
    task: str,
    output_root: Path,
    limit: int | None = None,
    workers: int | None = None,
    variant: str = "all",
) -> None:
    env = load_env()
    benchmark = get_benchmark_config(task)
    run_benchmark_experiment(
        benchmark=benchmark,
        output_root=output_root.resolve(),
        env=env,
        limit=limit,
        workers=workers,
        variant=variant,
    )


def run_full_experiment(
    save_dir: Path,
    env: dict[str, str],
    test_mode: bool,
    workers: int | None,
    limit: int | None = None,
    variant: str = "all",
) -> None:
    effective_limit = 1 if test_mode else limit
    for benchmark in BENCHMARKS.values():
        benchmark_root = save_dir / cast(str, benchmark["output_dir"])
        run_benchmark_experiment(
            benchmark=benchmark,
            output_root=benchmark_root,
            env=env,
            limit=effective_limit,
            workers=workers,
            variant=variant,
        )


@click.command()
@click.option(
    "--save-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_SAVE_DIR,
    show_default=True,
    help="Base directory for all nl2postcond outputs.",
)
@click.option(
    "--test",
    is_flag=True,
    help="Run a quick smoke test with 1 problem per benchmark.",
)
@click.option(
    "--workers",
    type=click.IntRange(min=1),
    default=None,
    help="Override evaluation worker count.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=None,
    help="Limit the number of problems for benchmark-specific runs or mini sweeps.",
)
@click.option(
    "--benchmark",
    type=click.Choice(sorted(BENCHMARKS.keys())),
    default=None,
    help="Run a single benchmark instead of the full sweep.",
)
@click.option(
    "--output-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output root for a single-benchmark run.",
)
@click.option(
    "--variant",
    type=click.Choice(sorted(NL2POSTCOND_VARIANT_ALIASES.keys())),
    default="all",
    show_default=True,
    help="Which NL2Postcond variant to run.",
)
def main(
    save_dir: Path,
    test: bool,
    workers: int | None,
    limit: int | None,
    benchmark: str | None,
    output_root: Path | None,
    variant: str,
) -> None:
    save_dir.mkdir(parents=True, exist_ok=True)
    if workers is None:
        workers = get_default_worker_count()
    if benchmark is not None:
        effective_limit = 1 if test else limit
        target_output_root = output_root
        if target_output_root is None:
            benchmark_config = get_benchmark_config(benchmark)
            target_output_root = save_dir / cast(str, benchmark_config["output_dir"])
        run_nl2postcond_for_task(
            task=benchmark,
            output_root=target_output_root.resolve(),
            limit=effective_limit,
            workers=workers,
            variant=variant,
        )
        return

    if output_root is not None:
        raise click.UsageError("--output-root requires --benchmark")
    if variant != "all":
        raise click.UsageError("--variant requires --benchmark")

    env = load_env()
    run_full_experiment(
        save_dir.resolve(),
        env,
        test,
        workers,
        limit=limit,
        variant=variant,
    )


if __name__ == "__main__":
    main()
