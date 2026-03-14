# Expecto: Extracting Formal Specifications from Natural Language Description for Trustworthy Oracles (Artifact)

This repository contains the artifact implementation for the paper *Expecto: Extracting Formal Specifications from Natural Language Description for Trustworthy Oracles*.

The paper studies the following four research questions:

- `RQ1` How effective is Expecto in generating formal specifications from informal descriptions?
- `RQ2` How do the top-down specification synthesis and tree search contribute to the performance of Expecto?
- `RQ3` How do test cases and SMT-based validation contribute to the performance of Expecto?
- `RQ4` Can Expecto be practically applied to detect functional bugs in real-world software?

The artifact entrypoint is [`./scripts/run_artifact.py`](./scripts/run_artifact.py).

## 1. Getting started
### System requirements
In the paper, the experiments were conducted with:

- Ubuntu 22.04
- Docker 24.0.2
- 64 CPU cores (Xeon Gold 6226R)
- 512 GB RAM
- 256 GB storage

For a quick smoke check, the `mini` mode is sufficient on a much smaller machine. For the full artifact, use as many CPU cores and as much memory as possible.

### Setup with Docker

1. Build the Docker image:

```bash
docker build -t expecto-artifact .
docker run -it \
  --name expecto-artifact \
  expecto-artifact \
  zsh
```

2. Inside the container, create `.env` in `/workspace/expecto-artifact`:

```bash
cat > .env <<'EOF'
OPENAI_API_KEY=YOUR_KEY_HERE
EOF
```

3. Before running the artifact, download the dataset bundle from Zenodo and extract it at the repository root.

Replace the placeholder URL below with the final Zenodo URL when it is available:

```bash
wget -O datasets.tar.gz https://zenodo.org/records/00000000/files/datasets.tar.gz
rm -rf datasets
tar -xzf datasets.tar.gz
```

After extraction, the repository should contain the `datasets/` directory with the benchmark files used by the artifact.

---
## 2. Directory structure
```text
├── README.md                          <- The top-level README (this file)
├── analyzer/                          <- Figure and table generation scripts
├── datasets/                          <- HumanEval+, APPS, and Defects4J datasets
├── expecto/                           <- Core Expecto implementation
├── nl-2-postcond/                     <- NL2Postcond baseline implementation
└── scripts/                           <- Benchmark wrappers and artifact entrypoint
    ├── run_artifact.py                <- Main artifact runner
    ├── run_humaneval_plus.py          <- HumanEval+ benchmark runner
    ├── run_apps.py                    <- APPS benchmark runner
    ├── run_defects4j.py               <- Defects4J runner for Expecto
    ├── run_nl2postcond.py             <- Shared NL2Postcond wrapper
    └── run_defects4j_nl2postcond.py   <- Defects4J NL2Postcond wrapper
```

Generated outputs from the artifact runner are written under:

```text
/workspace/data/experiment/artifact
├── full/
│   ├── runs/
│   │   ├── apps/
│   │   ├── humaneval_plus/
│   │   └── defects4j/
│   └── figures/
│       ├── configs/
│       ├── rq1/
│       ├── rq2/
│       ├── rq3/
│       └── rq4/
└── mini/
    ├── runs/
    └── figures/
```

---
## 3. Step-by-step reproduction with command, output, and paper mapping
This section combines the command reference for paper reproduction and the RQ-oriented results guide for paper claims. You can follow it from top to bottom and check, for each command, what it does, where its results are written, and which paper claim it supports.

All commands below use `/workspace/data/experiment/artifact` as the default `--output-root`.

### Runner modes at a glance
The main artifact runner supports four modes:

- `full`: run all experiment units needed for `RQ1`-`RQ4`, then generate all figures and tables under `full/figures/`
- `rq`: run only one research question and generate only that RQ's outputs under `full/figures/rq*/`
- `mini`: run a reduced trend-preserving sweep and write the reduced results under `mini/`
- `target`: run one benchmark-specific experiment unit only and write only its raw run directory

For every successful run, the artifact writes two kinds of outputs:

- Raw experiment outputs under `.../runs/...`
- Summary outputs under `.../figures/...` as `.pdf` and `.json`

The raw run directories are considered complete when the following marker files exist:

- Expecto unit: `evaluation_result/manifest.json`
- HumanEval+/APPS NL2Postcond unit: `aggregated_result.json`
- Defects4J NL2Postcond unit: `validation/aggregated.json`

### Recommended usage flow
Use the commands in this order if you want a predictable review path:

- Inspect the workflow without executing it first: `python3 scripts/run_artifact.py full --dry-run`
- Reproduce the full paper claims first: `python3 scripts/run_artifact.py full`
- Reproduce one paper claim in detail with `rq --rq ...`
- Run the reduced smoke test separately when needed: `python3 scripts/run_artifact.py mini`
- If one unit failed or you want to inspect one cell of a paper figure/table, rerun just that unit with `target`

### Full paper reproduction: `full`
Run everything:

**Expected runtime for `full`: about 50 hours.**

```bash
python3 scripts/run_artifact.py full
```

Run everything and force reruns:

```bash
python3 scripts/run_artifact.py full --force
```

Preview the full workflow without executing:

```bash
python3 scripts/run_artifact.py full --dry-run
```

What this command does:

- Runs all raw experiment units needed for `RQ1`-`RQ4`
- Deduplicates shared units across RQs
- Generates all tables and figures after the runs finish

Where the results are stored:

- Raw runs:
  - `/workspace/data/experiment/artifact/full/runs/apps/`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/`
  - `/workspace/data/experiment/artifact/full/runs/defects4j/`
- Final outputs (paper mapping):
    - [`Table 1 (RQ1 main comparison)`](/workspace/data/experiment/artifact/full/figures/rq1/evaluation.rq1.table.pdf)
    - [`Fig. 8 (RQ1 threshold analysis)`](/workspace/data/experiment/artifact/full/figures/rq1/evaluation.thresholds.pdf)
    - [`Fig. 9 (RQ2 ablation)`](/workspace/data/experiment/artifact/full/figures/rq2/evaluation.rq2.pdf)
    - [`Fig. 10 (RQ3 test-case ablation)`](/workspace/data/experiment/artifact/full/figures/rq3/evaluation.rq3.testcase.pdf)
    - [`Table 2 (RQ4 Defects4J comparison)`](/workspace/data/experiment/artifact/full/figures/rq4/evaluation.rq4.defects4j.table.pdf)

How this maps to the paper:

- `§4.1 Experimental Setup`: benchmark choices, baselines, and implementation settings
- `§4.2 RQ1`: baseline comparison on HumanEval+ and APPS
- `§4.3 RQ2`: top-down and tree-search ablation
- `§4.4 RQ3`: test-case and validation ablation
- `§4.5 RQ4`: Defects4J bug-detection evaluation

What to check:

- All paper-mapped files above exist after the run
- The `full/runs/...` tree contains per-variant run directories for the benchmarks used by each RQ

### Reproduce one paper claim at a time: `rq`
Use `rq` when you want one paper result and its associated outputs without running the full artifact.

Preview one RQ without executing:

```bash
python3 scripts/run_artifact.py rq --rq rq1 --dry-run
```

#### RQ1. Effectiveness of Expecto in formal specification generation
Run `RQ1`:

```bash
python3 scripts/run_artifact.py rq --rq rq1
```

What this command does:

- Runs six raw experiment units: `apps/ts`, `apps/nl2_base`, `apps/nl2_simple`, `humaneval_plus/ts`, `humaneval_plus/nl2_base`, and `humaneval_plus/nl2_simple`
- Uses `ts` as the full Expecto configuration and compares it against NL2Postcond `Base` and `Simple`

Where the results are stored:

- Raw runs:
  - `/workspace/data/experiment/artifact/full/runs/apps/{ts,nl2_base,nl2_simple}`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/{ts,nl2_base,nl2_simple}`
- Outputs (paper mapping):
    - [`Table 1`](/workspace/data/experiment/artifact/full/figures/rq1/evaluation.rq1.table.pdf)
    - [`Fig. 8`](/workspace/data/experiment/artifact/full/figures/rq1/evaluation.thresholds.pdf)

How this maps to the paper:

- Paper section: `§4.2`
- Table/figure coverage: `Table 1` and `Fig. 8`
- Benchmarks: `HumanEval+` and `APPS`
- Claim being checked: Expecto outperforms NL2Postcond `Base` and `Simple` in formal specification generation

What to check:

- `evaluation.rq1.table.pdf` is the compiled table-only PDF artifact for the same comparison
- `evaluation.thresholds.pdf` is the figure for the threshold analysis in `Fig. 8`

#### RQ2. Effectiveness of the top-down specification synthesis with tree search
Run `RQ2`:

```bash
python3 scripts/run_artifact.py rq --rq rq2
```

What this command does:

- Runs six raw Expecto ablation units: `apps/mono`, `apps/topdown`, `apps/ts`, `humaneval_plus/mono`, `humaneval_plus/topdown`, and `humaneval_plus/ts`
- Compares the monolithic baseline (`mono`), top-down without tree search (`topdown`), and full tree-search configuration (`ts`)

Where the results are stored:

- Raw runs:
  - `/workspace/data/experiment/artifact/full/runs/apps/{mono,topdown,ts}`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/{mono,topdown,ts}`
- Outputs (paper mapping):
    - [`Fig. 9`](/workspace/data/experiment/artifact/full/figures/rq2/evaluation.rq2.pdf)

How this maps to the paper:

- Paper section: `§4.3`
- Figure coverage: `Fig. 9`
- Benchmarks: `HumanEval+` and `APPS`
- Claim being checked: the top-down decomposition reduces wrong specifications and tree search increases sound-and-complete specifications

What to check:

- `evaluation.rq2.pdf` is the paper-facing visualization for `Fig. 9`

#### RQ3. Impact of Test Cases and SMT-Based Validation on Specification Generation
Run `RQ3`:

```bash
python3 scripts/run_artifact.py rq --rq rq3
```

What this command does:

- Runs six raw Expecto validation-ablation units: `apps/ts`, `apps/without_tc`, `apps/without_smt`, `humaneval_plus/ts`, `humaneval_plus/without_tc`, and `humaneval_plus/without_smt`
- Uses the figure/config labels `ts`, `without_tc`, and `without_smt`

Where the results are stored:

- Raw runs:
  - `/workspace/data/experiment/artifact/full/runs/apps/{ts,without_tc,without_smt}`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/{ts,without_tc,without_smt}`
- Outputs (paper mapping):
    - [`Fig. 10`](/workspace/data/experiment/artifact/full/figures/rq3/evaluation.rq3.testcase.pdf)

How this maps to the paper:

- Paper section: `§4.4`
- Figure coverage: `Fig. 10`
- Methodology linkage: the `without_smt` ablation isolates the SMT-based validation logic described in `§3.4`
- Benchmarks: `HumanEval+` and `APPS`
- Claim being checked: test cases improve robustness, and the validation pipeline materially contributes to Expecto's final quality

What to check:

- `evaluation.rq3.testcase.pdf` includes both the `without_tc` and `without_smt` ablations against `ts`

#### RQ4. Effectiveness of Expecto for bug detection in real-world software
Run `RQ4`:

```bash
python3 scripts/run_artifact.py rq --rq rq4
```

What this command does:

- Runs three Defects4J raw experiment units: `defects4j/expecto`, `defects4j/nl2_base`, and `defects4j/nl2_simple`
- Compares Expecto against the two NL2Postcond baselines on the real-world bug benchmark

Where the results are stored:

- Raw runs:
  - `/workspace/data/experiment/artifact/full/runs/defects4j/{expecto,nl2_base,nl2_simple}`
- Output (paper mapping):
    - [`Table 2`](/workspace/data/experiment/artifact/full/figures/rq4/evaluation.rq4.defects4j.table.pdf)

How this maps to the paper:

- Paper section: `§4.5`
- Table coverage: `Table 2`
- Benchmark: `Defects4J`
- Claim being checked: Expecto generates more bug-detectable correct specifications than NL2Postcond on real-world Java bugs

What to check:

- `evaluation.rq4.defects4j.table.pdf` is the compiled table-only PDF for the same comparison
- The corresponding raw run directories under `full/runs/defects4j/` exist for all three compared systems

### Quick smoke check: `mini`
Run the reduced sweep:

```bash
python3 scripts/run_artifact.py mini
```

Use a different reduced limit:

```bash
python3 scripts/run_artifact.py mini --mini-limit 2
```

Preview the reduced sweep without executing:

```bash
python3 scripts/run_artifact.py mini --dry-run
```

What this command does:

- Runs the same experiment families as `full`, but with a reduced per-benchmark problem limit (`--mini-limit`, default `5`)
- Generates reduced outputs for `RQ1`-`RQ4`
- Writes everything under `/workspace/data/experiment/artifact/mini`

Where the results are stored:

- Raw reduced runs:
  - `/workspace/data/experiment/artifact/mini/runs/...`
- Reduced outputs: `/workspace/data/experiment/artifact/mini/figures/rq1/` through `rq4/`

How this maps to the paper:

- `mini` is not meant to reproduce the exact paper numbers
- It is the short AE smoke-test path for checking that the full `§4` evaluation pipeline is wired correctly

What to check:

- The `mini/runs/` and `mini/figures/` directories are created
- Each `mini/figures/rq*/` directory contains the same output file types as the corresponding `full` run

### Inspect one unit or rerun one failed cell: `target`
Run one benchmark-specific target:

```bash
python3 scripts/run_artifact.py target --benchmark apps --family rq2 --variant topdown
python3 scripts/run_artifact.py target --benchmark humaneval_plus --family rq3 --variant without_smt
python3 scripts/run_artifact.py target --benchmark defects4j --family rq4 --variant nl2_base
```

Target mode also accepts `--limit` and `--force`:

```bash
python3 scripts/run_artifact.py target --benchmark apps --family rq2 --variant mono --limit 3 --force
```

What this command does:

- Runs exactly one raw experiment unit and does not generate paper-facing figures or tables
- Lets you inspect one component of a larger RQ result or rerun only the unit that failed

Where the results are stored:

- `apps` and `humaneval_plus` targets: `/workspace/data/experiment/artifact/full/runs/<benchmark>/<variant>`
- `defects4j` targets: `/workspace/data/experiment/artifact/full/runs/defects4j/<variant>`

How this maps to the paper:

- `--benchmark apps --family rq2 --variant topdown`: the APPS / TopDown cell inside the `§4.3` ablation
- `--benchmark humaneval_plus --family rq3 --variant without_smt`: the HumanEval+ / `without_smt` ablation tied to `§4.4` and `§3.4`
- `--benchmark defects4j --family rq4 --variant nl2_base`: the Defects4J / NL2Postcond Base comparison unit in `§4.5`

What to check:

- The expected completion marker appears in the target run directory
- `target` is the right command when one unit was interrupted and you do not want to rerun the whole RQ or full artifact

---
## 4. Claims supported by the artifact
The artifact supports the following paper claims:

- `RQ1` (`§4.2`): Expecto outperforms NL2Postcond `Base` and `Simple` on formal specification generation for `HumanEval+` and `APPS`. Reproduce with `python3 scripts/run_artifact.py rq --rq rq1` or `full`.
- `RQ2` (`§4.3`): the top-down decomposition and tree search are both important contributors to Expecto's performance. Reproduce with `python3 scripts/run_artifact.py rq --rq rq2` or `full`.
- `RQ3` (`§4.4`, linked to `§3.4`): both test cases and SMT-based validation improve robustness. Reproduce with `python3 scripts/run_artifact.py rq --rq rq3` or `full`.
- `RQ4` (`§4.5`): Expecto is effective for bug detection on `Defects4J`. Reproduce with `python3 scripts/run_artifact.py rq --rq rq4` or `full`.
- Reuse claim: the source, benchmark wrappers, and figure-generation scripts needed to rerun and extend the evaluation are included in this repository.

The artifact does not directly support the following claims as standalone push-button outputs:

- The qualitative example figures `Fig. 7`, `Fig. 11`, and `Fig. 12` are discussed in the paper, but `run_artifact.py` does not regenerate them as dedicated outputs. The artifact focuses on the quantitative evaluation claims in `§4.2`-`§4.5`.
- `mini` is a reduced smoke-test profile and is not intended to reproduce the exact final paper numbers.

---
## 5. Experimental setting from the paper
The paper evaluates Expecto on three benchmarks:

- `HumanEval+`: 164 Python problems
- `APPS`: 127 selected problems with at least 100 test cases
- `Defects4J`: 336 methods selected from 501 bugs reproducible on Java 8+

Natural language inputs used in the paper:

- HumanEval+ and APPS: problem descriptions
- Defects4J: method-level Javadoc comments

Baseline used in the paper:

- NL2Postcond `Base`
- NL2Postcond `Simple`

---
## 6. Reuse, force, and output management
The artifact runner checks whether a unit has already completed before launching it again.

- Expecto units are considered complete when `evaluation_result/manifest.json` exists.
- HumanEval+/APPS NL2Postcond units are considered complete when `aggregated_result.json` exists.
- Defects4J NL2Postcond units are considered complete when `validation/aggregated.json` exists.

Examples:

```bash
python3 scripts/run_artifact.py full
python3 scripts/run_artifact.py full --force
python3 scripts/run_artifact.py rq --rq rq3 --force
```

The `mini` profile is stored separately from the `full` profile so that reduced runs do not pollute the main outputs.
