from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_DIR.parent.parent
DATASETS_DIR = REPO_ROOT / "datasets"


def get_datasets_dir() -> Path:
    return DATASETS_DIR


def get_apps_dataset_file() -> Path:
    return DATASETS_DIR / "apps.json"


def get_evalplus_dataset_file() -> Path:
    return DATASETS_DIR / "human_eval_plus.json"


def get_defects4j_dataset_file() -> Path:
    return DATASETS_DIR / "defects4j.jsonl"
