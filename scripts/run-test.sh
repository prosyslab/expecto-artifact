#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# load .env file
source "${REPO_ROOT}/.env"

run_step() {
    local name="$1"
    shift

    echo "=== Running ${name} ==="
    "$@"
    echo "=== Finished ${name} ==="
}

run_step "HumanEval+" \
    python3 scripts/run_humaneval_plus.py --limit 1 --exp-name test --solver tree_search

run_step "APPS" \
    python3 scripts/run_apps.py --limit 1 --exp-name test --solver tree_search

run_step "Defects4J" \
    python3 scripts/run_defects4j.py --limit 1 --exp-name test

# run_step "nl2postcond" \
#     python3 scripts/run_nl2postcond.py --test
