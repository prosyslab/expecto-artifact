from pathlib import Path

TASKS_DIR = Path(__file__).resolve().parent
EXPECTO_ROOT = TASKS_DIR.parent.parent
REPO_ROOT = EXPECTO_ROOT.parent
DEFAULT_DATASET_PATH = REPO_ROOT / "datasets"
DEFECTS4J_JSON_FILE = DEFAULT_DATASET_PATH / "defects4j.json"
DEFECTS4J_JSONL_FILE = DEFAULT_DATASET_PATH / "defects4j.jsonl"


def get_dataset_path() -> Path:
    return DEFAULT_DATASET_PATH


def get_defects4j_dataset_file() -> Path:
    return DEFECTS4J_JSON_FILE


def get_defects4j_dataset_jsonl_file() -> Path:
    return DEFECTS4J_JSONL_FILE


def resolve_defects4j_dataset_file(prefer_jsonl: bool = True) -> Path:
    candidates = (
        [DEFECTS4J_JSONL_FILE, DEFECTS4J_JSON_FILE]
        if prefer_jsonl
        else [DEFECTS4J_JSON_FILE, DEFECTS4J_JSONL_FILE]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
