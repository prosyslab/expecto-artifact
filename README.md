# Expecto: Extracting Formal Specifications from Natural Language Description for Trustworthy Oracles (Artifact)

This repository contains the artifact implementation for the paper *Expecto: Extracting Formal Specifications from Natural Language Description for Trustworthy Oracles*.

The paper studies the following four research questions:

- `RQ1` How effective is Expecto in generating formal specifications from informal descriptions?
- `RQ2` How do the top-down specification synthesis and tree search contribute to the performance of Expecto?
- `RQ3` How do test cases and SMT-based validation contribute to the performance of Expecto?
- `RQ4` Can Expecto be practically applied to detect functional bugs in real-world software?

The artifact execution script is `./scripts/run_artifact.py`.

# 1. Getting started
## System requirements
In the paper, the experiments were conducted with:

- Ubuntu 22.04
- Docker 24.0.2
- 64 CPU cores (Xeon Gold 6226R)
- 512 GB RAM
- 256 GB storage

## Setup with Docker

**1. Pull, Build, or Load the Docker image:**

Pull (Recommended):
```bash
docker pull prosyslab/expecto-artifact
```

Build:
```bash
git clone https://github.com/prosyslab/expecto-artifact
cd expecto-artifact
docker build -t expecto-artifact .
```

Load `expecto-artifact.tar.gz` from Zenodo):
```bash
gunzip -c expecto-artifact.tar.gz | docker load
```

**2. Run the container:**
```bash
docker run -it --name expecto-artifact prosyslab/expecto-artifact zsh
```

**3. Inside the container, create `.env` in `/workspace/expecto-artifact` and set the API key:**

```bash
cat > .env <<'EOF'
OPENAI_API_KEY=YOUR_KEY_HERE
EOF
```

**4. Run the test to confirm that the setup is complete (takes about 2 minutes):**

```bash
python3 scripts/test.py
```

This script reproduces the creation, evaluation, and figure generation process for RQ1.
If the output appears as shown below, this confirms that all settings have been configured correctly.

Expected output:

```text
[PASS] .env file: /workspace/expecto-artifact/.env
[PASS] OPENAI_API_KEY: OPENAI_API_KEY is defined in .env and starts with 'sk-'
[PASS] datasets directory: /workspace/expecto-artifact/datasets
[PASS] dataset file: datasets/apps.json
[PASS] dataset file: datasets/human_eval_plus.json
[PASS] dataset file: datasets/defects4j.jsonl
Running RQ1 smoke test:
/usr/bin/python3 /workspace/expecto-artifact/scripts/run_artifact.py rq1 --limit 1 --output-root /workspace/data/experiment/artifact/test-smoke --force
...
[PASS] RQ1 execution: run_artifact.py completed successfully
[PASS] Expecto markers: .../full/runs/apps/ts/evaluation_result/manifest.json
[PASS] NL2Postcond marker: .../full/runs/apps/nl2_base/.../aggregated_result.json
[PASS] RQ1 figure output: .../full/figures/rq1/evaluation.rq1.table.pdf

Summary:
[PASS] .env file
[PASS] OPENAI_API_KEY
[PASS] datasets directory
[PASS] dataset files
[PASS] RQ1 execution
[PASS] Expecto markers
[PASS] NL2Postcond markers
[PASS] RQ1 figure outputs
```

---
# 2. Directory structure
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
# 3. Full reproduction

This command runs all the experiments required for the paper.
**Expected runtime for `full`: about 50 hours.**

```bash
python3 scripts/run_artifact.py full
```
By default, it will not run if an execution result already exists. You can force it to run again by using `--force`:

```bash
python3 scripts/run_artifact.py full --force
```

What this command does:

- Runs all experiments required for reproducing paper results.
- Generates all tables and figures after the runs finish.

Where the results are stored:

- Raw runs:
  - `/workspace/data/experiment/artifact/full/runs/apps/`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/`
  - `/workspace/data/experiment/artifact/full/runs/defects4j/`
- Final outputs (paper mapping):
    - `Table 1 (RQ1 main comparison)`: `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.rq1.table.pdf`
    - `Fig. 8 (RQ1 threshold analysis)`: `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.thresholds.pdf`
    - `Fig. 9 (RQ2 generation algorithm ablation)`: `/workspace/data/experiment/artifact/full/figures/rq2/evaluation.rq2.pdf`
    - `Fig. 10 (RQ3 test-case and SMT-based validation ablation)`: `/workspace/data/experiment/artifact/full/figures/rq3/evaluation.rq3.testcase.pdf`
    - `Table 2 (RQ4 Defects4J comparison)`: `/workspace/data/experiment/artifact/full/figures/rq4/evaluation.rq4.defects4j.table.pdf`

Please refer to Section 4 for the claims that must be checked for each RQ.

---
# 4. RQ reproduction
Use `rq1`, `rq2`, `rq3`, or `rq4` when you want one paper result and its associated outputs without running the full artifact.

> **Note:** If you have already completed the `full` run, all figures and tables for the paper will have been generated. There is no need to run `rq1`-`rq4` separately unless you want to rerun or inspect a specific research question in detail.

Run one RQ (`RQ_NUMBER` can be `rq1`, `rq2`, `rq3`, or `rq4`):

```bash
python3 scripts/run_artifact.py <RQ_NUMBER>
```

## RQ1. Effectiveness of Expecto in formal specification generation
Run `RQ1`:

```bash
python3 scripts/run_artifact.py rq1
```

What this command does:

- Runs six raw experiment units: `apps/ts`, `apps/nl2_base`, `apps/nl2_simple`, `humaneval_plus/ts`, `humaneval_plus/nl2_base`, and `humaneval_plus/nl2_simple`
- Uses `ts` as the full Expecto configuration and compares it against NL2Postcond `Base` and `Simple`

Where the results are stored:

- Raw runs:
  - `/workspace/data/experiment/artifact/full/runs/apps/{ts,nl2_base,nl2_simple}`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/{ts,nl2_base,nl2_simple}`
- Outputs (paper mapping):
    - `Table 1 (RQ1 main comparison)`: `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.rq1.table.pdf`
    - `Fig. 8 (RQ1 threshold analysis)`: `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.thresholds.pdf`

How this maps to the paper:

- Paper section: `§4.2`
- Table/figure coverage: `Table 1` and `Fig. 8`
- Benchmarks: `HumanEval+` and `APPS`
- Claim being checked: Expecto outperforms NL2Postcond `Base` and `Simple` in formal specification generation

## RQ2. Effectiveness of the top-down specification synthesis with tree search
Run `RQ2`:

```bash
python3 scripts/run_artifact.py rq2
```

What this command does:

- Runs six raw Expecto ablation units: `apps/mono`, `apps/topdown`, `apps/ts`, `humaneval_plus/mono`, `humaneval_plus/topdown`, and `humaneval_plus/ts`
- Compares the monolithic baseline (`mono`), top-down without tree search (`topdown`), and full tree-search configuration (`ts`)

Where the results are stored:

- Raw runs:
  - `/workspace/data/experiment/artifact/full/runs/apps/{mono,topdown,ts}`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/{mono,topdown,ts}`
- Outputs (paper mapping):
    - `Fig. 9 (RQ2 generation algorithm ablation)`: `/workspace/data/experiment/artifact/full/figures/rq2/evaluation.rq2.pdf`

How this maps to the paper:

- Paper section: `§4.3`
- Figure coverage: `Fig. 9`
- Benchmarks: `HumanEval+` and `APPS`
- Claim being checked: the top-down decomposition reduces wrong specifications and tree search increases sound-and-complete (S&C) specifications

What to check:

- `evaluation.rq2.pdf` is the paper-facing visualization for `Fig. 9`

## RQ3. Impact of Test Cases and SMT-Based Validation on Specification Generation
Run `RQ3`:

```bash
python3 scripts/run_artifact.py rq3
```

What this command does:

- Runs six raw Expecto validation-ablation units: `apps/ts`, `apps/without_tc`, `apps/without_smt`, `humaneval_plus/ts`, `humaneval_plus/without_tc`, and `humaneval_plus/without_smt`
- Uses the figure/config labels `ts`, `without_tc`, and `without_smt`

Where the results are stored:

- Raw runs:
  - `/workspace/data/experiment/artifact/full/runs/apps/{ts,without_tc,without_smt}`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/{ts,without_tc,without_smt}`
- Outputs (paper mapping):
    - `Fig. 10 (RQ3 test-case and SMT-based validation ablation)`: `/workspace/data/experiment/artifact/full/figures/rq3/evaluation.rq3.testcase.pdf`

How this maps to the paper:

- Paper section: `§4.4`
- Figure coverage: `Fig. 10`
- Methodology: `Without SMT` and `Without TC` ablations isolate the SMT-based validation logic and test case usage in validation step in `§3.4`
- Benchmarks: `HumanEval+` and `APPS`
- Claim being checked: test cases and SMT-based validation improve robustness of specification generation

## RQ4. Effectiveness of Expecto for bug detection in real-world software
Run `RQ4`:

```bash
python3 scripts/run_artifact.py rq4
```

What this command does:

- Runs three Defects4J raw experiment units: `defects4j/expecto`, `defects4j/nl2_base`, and `defects4j/nl2_simple`
- Compares Expecto against the two NL2Postcond baselines on the real-world bug benchmark

Where the results are stored:

- Raw runs:
  - `/workspace/data/experiment/artifact/full/runs/defects4j/{expecto,nl2_base,nl2_simple}`
- Output (paper mapping):
    - `Table 2 (RQ4 Defects4J comparison)`: `/workspace/data/experiment/artifact/full/figures/rq4/evaluation.rq4.defects4j.table.pdf`

How this maps to the paper:

- Paper section: `§4.5`
- Table coverage: `Table 2`
- Benchmark: `Defects4J`
- Claim being checked: Expecto generates more bug-detectable correct specifications than NL2Postcond on real-world Java bugs

## Quick check: `mini`
Run the reduced sweep:

```bash
python3 scripts/run_artifact.py mini
```

What this command does:

- Runs the same experiment families as `full`, but uses fixed benchmark subsets for the EvalPlus-style benchmarks
- Uses these 20 APPS problem IDs: `15, 57, 23, 76, 83, 39, 101, 3701, 4004, 37, 94, 16, 61, 52, 42, 47, 72, 90, 4005, 71`
- Uses these 20 HumanEval+ problem IDs: `22, 52, 75, 61, 83, 92, 34, 53, 73, 129, 140, 158, 54, 124, 6, 71, 32, 123, 162, 63`
- Uses these 20 Defects4J task IDs:
```
Chart_6_workspace_objdump_d4j_full_fresh_chart_6_source_org_jfree_chart_util_ShapeList_java_boolean_equals_Object_obj, Cli_18_workspace_objdump_d4j_full_fresh_cli_18_src_java_org_apache_commons_cli_PosixParser_java_void_processOptionToken_String_token_boolean_stopAtNonOption, Compress_40_workspace_objdump_d4j_full_compress_40_src_main_java_org_apache_commons_compress_utils_BitInputStream_java_long_readBits_int_count, Jsoup_76_workspace_objdump_d4j_full_jsoup_76_src_main_java_org_jsoup_parser_HtmlTreeBuilderState_java_boolean_process_Token_t_HtmlTreeBuilder_tb, Jsoup_85_workspace_objdump_d4j_full_jsoup_85_src_main_java_org_jsoup_nodes_Attribute_java_Attribute_String_key_String_val_Attributes_parent, Lang_32_workspace_objdump_d4j_full_lang_32_src_main_java_org_apache_commons_lang3_builder_HashCodeBuilder_java_boolean_isRegistered_Object_value, Math_35_workspace_objdump_d4j_full_math_35_src_main_java_org_apache_commons_math3_genetics_ElitisticListPopulation_java_ElitisticListPopulation_int_populationLimit_double_elitismRate, Math_73_workspace_objdump_d4j_full_math_73_src_main_java_org_apache_commons_math_analysis_solvers_BrentSolver_java_double_solve_UnivariateRealFunction_f_double_min_double_max, Math_80_workspace_objdump_d4j_full_math_80_src_main_java_org_apache_commons_math_linear_EigenDecompositionImpl_java_boolean_flipIfWarranted_int_n_int_step, Math_96_workspace_objdump_d4j_full_math_96_src_java_org_apache_commons_math_complex_Complex_java_boolean_equals_Object_other, Cli_10_workspace_objdump_d4j_full_fresh_cli_10_src_java_org_apache_commons_cli_Parser_java_CommandLine_parse_Options_options_String_arguments_Properties_properties_boolean_stopAtNonOption, Cli_18_workspace_objdump_d4j_full_fresh_cli_18_src_java_org_apache_commons_cli_PosixParser_java_String_flatten_Options_options_String_arguments_boolean_stopAtNonOption, Cli_32_workspace_objdump_d4j_full_fresh_cli_32_src_main_java_org_apache_commons_cli_HelpFormatter_java_int_findWrapPos_String_text_int_width_int_startPos, Closure_114_workspace_objdump_d4j_full_fresh_closure_114_src_com_google_javascript_jscomp_NameAnalyzer_java_void_visit_NodeTraversal_t_Node_n_Node_parent, Closure_74_workspace_objdump_d4j_full_fresh_closure_74_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldBinaryOperator_Node_subtree, Closure_78_workspace_objdump_d4j_full_fresh_closure_78_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldArithmeticOp_Node_n_Node_left_Node_right, Closure_97_workspace_objdump_d4j_full_fresh_closure_97_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldBinaryOperator_Node_subtree, Codec_4_workspace_objdump_d4j_full_codec_4_src_java_org_apache_commons_codec_binary_Base64_java_byte_encodeBase64_byte_binaryData_boolean_isChunked_boolean_urlSafe_int_maxResultSize, Jsoup_38_workspace_objdump_d4j_full_jsoup_38_src_main_java_org_jsoup_parser_HtmlTreeBuilderState_java_boolean_process_Token_t_HtmlTreeBuilder_tb, Jsoup_46_workspace_objdump_d4j_full_jsoup_46_src_main_java_org_jsoup_nodes_Entities_java_void_escape_StringBuilder_accum_String_string_Document_OutputSettings_out_boolean_inAttribute_boolean_normaliseWhite_boolean_stripLeadingWhite
```
- Generates reduced outputs for `RQ1`-`RQ4`
- Writes everything under `/workspace/data/experiment/artifact/mini`

Where the results are stored:

- Raw reduced runs:
  - `/workspace/data/experiment/artifact/mini/runs/...`
- Reduced outputs: `/workspace/data/experiment/artifact/mini/figures/rq1/` through `rq4/`

How this maps to the paper:

- `mini` is not meant to reproduce the exact paper numbers. It is only reproducing the paper's overall trend.

---
# 5. Target reproduction
Run one benchmark-specific target:

```bash
python3 scripts/run_artifact.py target --benchmark apps --family rq2 --variant topdown
python3 scripts/run_artifact.py target --benchmark humaneval_plus --family rq3 --variant without_smt
python3 scripts/run_artifact.py target --benchmark defects4j --family rq4 --variant nl2_base
```

What this command does:

- Runs exactly one raw experiment unit and does not generate paper-facing figures or tables
- Lets you inspect one component of a larger RQ result or rerun only the unit that failed

Where the results are stored:

- `apps` and `humaneval_plus` targets: `/workspace/data/experiment/artifact/full/runs/<benchmark>/<variant>`
- `defects4j` targets: `/workspace/data/experiment/artifact/full/runs/defects4j/<variant>`

---
# 6. Reproducing only a specific `target_id`
If you want to reproduce exactly one benchmark instance instead of the default sweep, use `run_artifact.py target` with `--sample-ids`.

General rules:

- For `APPS` and `HumanEval+`, `target_id` is the numeric problem ID
- For `Defects4J`, `target_id` is the full task ID string used in the dataset JSONL
- You can pass multiple IDs as a comma-separated list if needed

```bash
python3 scripts/run_artifact.py target \
  --benchmark apps \
  --family rq2 \
  --variant topdown \
  --sample-ids 3701
```

This example reproduces only APPS problem `3701` for the `rq2/topdown` target, and writes the result to:

- `/workspace/data/experiment/artifact/full/runs/apps/topdown`

For `HumanEval+`, run:

```bash
python3 scripts/run_artifact.py target \
  --benchmark humaneval_plus \
  --family rq3 \
  --variant without_smt \
  --sample-ids 123
```

This example reproduces only HumanEval+ problem `123` for the `rq3/without_smt` target.

For `Defects4J`, run:

```bash
python3 scripts/run_artifact.py target \
  --benchmark defects4j \
  --family rq4 \
  --variant nl2_base \
  --sample-ids "Chart_6_workspace_objdump_d4j_full_fresh_chart_6_source_org_jfree_chart_util_ShapeList_java_boolean_equals_Object_obj"
```

What this command does:

- Reproduces only the requested `target_id` for the selected benchmark/variant
- Preserves the same output directory layout used by Section 5 target runs
- Does not generate paper-facing figures or tables automatically

If you want the corresponding paper figure or table after reproducing a specific `target_id`, rerun the appropriate `rq1`, `rq2`, `rq3`, or `rq4` command once the needed raw runs are available.
