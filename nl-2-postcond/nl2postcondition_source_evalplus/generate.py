import asyncio
from pathlib import Path

import click
from dataset_paths import get_apps_dataset_file, get_evalplus_dataset_file

EXP_CONFIGS = [
    "generateLLMSamplesSimple.yaml",
    "generateLLMSamplesBase.yaml",
]

PPX_CONFIG = "preprocessSamples.yaml"
EVAL_CONFIG = "evaluation.yaml"


def log_cmd(args: list[str]):
    joined = " ".join(args)
    print(f"Executing {joined}")


def get_run_range_overrides(benchmark_config: str) -> list[str]:
    if benchmark_config == "apps":
        return [
            "benchmarks.run_all=false",
            "benchmarks.run_range=true",
            "benchmarks.run_start='0'",
            "benchmarks.run_end='9'",
        ]
    return [
        "benchmarks.run_all=false",
        "benchmarks.run_range=false",
        "benchmarks.run_only=[0,1,2,3,4,5,6,7,8,9]",
    ]


def get_benchmark_overrides(benchmark: str) -> tuple[str, str]:
    benchmark_key = benchmark.lower()
    if benchmark_key in {"humaneval", "evalplus", "human_eval", "human-eval"}:
        return "evalplus", str(get_evalplus_dataset_file())
    if benchmark_key in {"apps", "apps-verified-100"}:
        return "apps", str(get_apps_dataset_file())
    raise ValueError(f"Unsupported benchmark: {benchmark}")


def get_latest_run_dir(parent_dir: Path) -> str:
    run_dirs = sorted(
        (path for path in parent_dir.glob("*/*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
    )
    if not run_dirs:
        raise FileNotFoundError(f"No Hydra run directory found under {parent_dir}")
    return str(run_dirs[-1])


async def run_exp(save_dir: str, target_config: str, idx: int, benchmark: str):
    await asyncio.sleep(idx * 5)
    exp_name = target_config.replace("generateLLMSamples", "").replace(".yaml", "")
    benchmark_config, dataset_path = get_benchmark_overrides(benchmark)
    run_range_overrides = get_run_range_overrides(benchmark_config)
    generation_root = Path(save_dir) / "llm_gen_outputs" / exp_name
    args = [
        "python3",
        "llm_sample_generator.py",
        f"experiment={target_config}",
        f"benchmarks={benchmark_config}",
        f"hydra.run.dir={save_dir}/llm_gen_outputs/{exp_name}/${{now:%Y-%m-%d}}/${{now:%H-%M-%S}}",
    ]
    if benchmark_config == "apps":
        args.append(f"benchmarks.location={dataset_path}")
    args.extend(run_range_overrides)
    log_cmd(args)
    result = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE)
    stdout, _ = await result.communicate()
    exit_code = result.returncode
    if exit_code != 0:
        print(f"\033[91mGeneration failed for {target_config}\033[0m")
        return
    saved_path = get_latest_run_dir(generation_root)
    print(f"Saved path: {saved_path}")

    preprocess_root = Path(save_dir) / "response_preprocess_outputs" / exp_name
    args = [
        "python3",
        "response_preprocessing.py",
        f"experiment={PPX_CONFIG}",
        f"experiment.samplesFolder={saved_path}",
        f"benchmarks={benchmark_config}",
        f"experiment.exp_name={exp_name}",
        f"hydra.run.dir={save_dir}/response_preprocess_outputs/{exp_name}/${{now:%Y-%m-%d}}/${{now:%H-%M-%S}}",
    ]
    if benchmark_config == "apps":
        args.append(f"benchmarks.location={dataset_path}")
    args.extend(run_range_overrides)
    log_cmd(args)
    result = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE)
    stdout, _ = await result.communicate()
    exit_code = result.returncode
    if exit_code != 0:
        print(f"\033[91mResponse preprocessing failed for {target_config}\033[0m")
        return
    saved_path = get_latest_run_dir(preprocess_root)
    print(f"Saved path: {saved_path}")

    args = [
        "python3",
        "evaluation.py",
        f"{saved_path}",
        "--dataset",
        dataset_path,
        "--exp_name",
        target_config.replace("generateLLMSamples", "").replace(".yaml", ""),
    ]
    log_cmd(args)
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE)
    stdout, _ = await proc.communicate()
    return_code = proc.returncode
    if return_code != 0:
        print(f"\033[91mEvaluation failed for {saved_path}\033[0m")
        return
    else:
        print(f"\033[92mEvaluation succeeded for {saved_path}\033[0m")
        print(stdout.decode())


async def run_all(save_dir, benchmark):
    tasks = []
    for idx, config in enumerate(EXP_CONFIGS):
        tasks.append(run_exp(save_dir, config, idx, benchmark))
    return await asyncio.gather(*tasks)


@click.command()
@click.option("--save_dir", type=str, required=True)
@click.option("--benchmark", type=str, required=True)
def main(save_dir, benchmark):
    asyncio.run(run_all(save_dir, benchmark))


if __name__ == "__main__":
    main()
