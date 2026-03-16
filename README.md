# Expecto: Extracting Formal Specifications from Natural Language Description for Trustworthy Oracles (Artifact)

This repository contains the artifact implementation for the paper *Expecto: Extracting Formal Specifications from Natural Language Description for Trustworthy Oracles*.

The paper studies the following four research questions:

- `RQ1` How effective is Expecto in generating formal specifications from informal descriptions?
- `RQ2` How do the top-down specification synthesis and tree search contribute to the performance of Expecto?
- `RQ3` How do test cases contribute to the performance of Expecto?
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

### Step 1. Pull or load the Docker image

Pulling the image is the easiest option.

```bash
docker pull prosyslab/expecto-artifact
```

If you downloaded `expecto-artifact.tar.gz` from Zenodo, you can load it instead.

```bash
gunzip -c expecto-artifact.tar.gz | docker load
```

You can check that the image is well pulled or loaded with:
```bash
docker images | grep expecto-artifact
> prosyslab/expecto-artifact   latest    ...
```

### Step 2. Start the container

```bash
docker run -it --name expecto-artifact prosyslab/expecto-artifact zsh
```

### Step 3. Create the `.env` file

Inside the container, move to `/workspace/expecto-artifact` and create a `.env` file with your OpenAI API key.

```bash
cat > .env <<'EOF'
OPENAI_API_KEY=YOUR_KEY_HERE
EOF
```

### Step 4. Run the test

This is quick test run (takes 2 minutes). It checks your environment and runs a very small `RQ1` reproduction.

```bash
python3 scripts/test.py
```

This script checks the creation, evaluation, and figure generation process for RQ1.
If the output appears as shown below, this confirms that all settings have been configured correctly.

Expected output:
- The script checks the environment and runs a small RQ1 smoke test.
- Raw data:
  - `/workspace/data/experiment/artifact/test-smoke/full/runs/apps/`
  - `/workspace/data/experiment/artifact/test-smoke/full/runs/humaneval_plus/`
- Outputs:
  - `/workspace/data/experiment/artifact/test-smoke/full/figures/rq1/evaluation.rq1.table.tex`
  - `/workspace/data/experiment/artifact/test-smoke/full/figures/rq1/evaluation.rq1.table.pdf`
  - `/workspace/data/experiment/artifact/test-smoke/full/figures/rq1/evaluation.thresholds.pdf`

A successful console log looks like this:

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

# 2. Directory structure

This section shows the most important top-level directories.

```text
/workspace/expecto-artifact
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
├── full/                              <- Full paper reproduction outputs
│   ├── runs/                          <- Raw experiment result data for each benchmark/variant
│   │   ├── apps/                      <- APPS raw data directories
│   │   ├── humaneval_plus/            <- HumanEval+ raw data directories
│   │   └── defects4j/                 <- Defects4J raw data directories
│   └── figures/                       <- Generated tables and figures
│       ├── configs/                   <- Auto-generated figure configuration JSON files
│       ├── rq1/                       <- RQ1 outputs
│       ├── rq2/                       <- RQ2 outputs
│       ├── rq3/                       <- RQ3 outputs
│       └── rq4/                       <- RQ4 outputs
├── mini/                              <- Reduced fixed-sample profile outputs
│   ├── runs/
│   └── figures/
└── target/                            <- Targeted reproduction outputs
    └── runs/
        ├── apps/
        ├── humaneval_plus/
        └── defects4j/
```

# 3. Reproducing only a specific `target_id`
*You can skip this section if you want to directly reproduce the full paper results*

Use this mode when you want to run only a specific benchmark problem for a selected generation variant.
This is helpful for:

- comparing outputs for one problem
- checking whether a generation setup is configured correctly
- inspecting raw artifacts before running the full paper pipeline

## Command
- For `APPS` and `HumanEval+`, `target_id` is the numeric problem ID
- For `Defects4J`, `target_id` is the full task ID string used in the dataset JSONL
- You can pass multiple IDs as a comma-separated list
- A full list of available IDs is provided in `datasets/available_target_ids.csv`

```bash
python3 scripts/run_artifact.py target \
  --benchmark <apps|humaneval_plus|defects4j> \
  --variant <mono|topdown|ts|without_tc|nl2_base|nl2_simple> \
  --sample-ids <id>
```

Expected output:
- The command runs only the requested `target_id` values for the selected benchmark and variant.
- Raw data:
  - `/workspace/data/experiment/artifact/target/runs/<benchmark>/<variant>/`
- Outputs:
  - `Expecto` variants (`mono`, `topdown`, `ts`, `without_tc`): `evaluation_result/samples/<sample_id>.json`
  - `NL2Postcond` variants (`nl2_base`, `nl2_simple`): `response_preprocess_outputs/.../evaluation_results.json`

## Example

```bash
python3 scripts/run_artifact.py target \
  --benchmark apps \
  --variant ts \
  --sample-ids 15
```
Expected output:
- Runs APPS sample `15` with the full Expecto tree-search configuration.
- Raw data:
  - `/workspace/data/experiment/artifact/target/runs/apps/ts/`
- Outputs:
  - `/workspace/data/experiment/artifact/target/runs/apps/ts/evaluation_result/samples/15.json`

## Inspecting Expecto variants

For `Expecto` variants (`mono`, `topdown`, `ts`, `without_tc`), start from the `evaluation_result/` directory.

```bash
find /workspace/data/experiment/artifact/target/runs/apps/ts/evaluation_result -maxdepth 2 -type f
```
Expected output:
- Prints the files inside the Expecto `evaluation_result/` directory, including metadata and per-sample JSON files.
- Raw data:
  - `/workspace/data/experiment/artifact/target/runs/apps/ts/evaluation_result/`
- Outputs:
  - `/workspace/data/experiment/artifact/target/runs/apps/ts/evaluation_result/manifest.json`
  - `/workspace/data/experiment/artifact/target/runs/apps/ts/evaluation_result/samples/<sample_id>.json`

Typical structure:

- `evaluation_result/manifest.json`: a metadata file for the run.
- `evaluation_result/samples/<sample_id>.json`: the raw data for one target

`samples/15.json` looks like this:

```json
{
  "sample_id": "15",
  "final_output": {
    "iteration": 2,
    "num_of_nodes": 4,
    "generated_codes": [
      "predicate spec(a: int, b: int, c: int, output: string) { ... }"
    ],
    "is_success": true,
    "num_of_defined": 2,
    "num_of_undefined": 0
  },
  "metadata": {
    "problem_id": 15,
    "difficulty": "interview",
    "input": "## Question: Vasya likes everything infinite. ...",
    "signature": "def postcondition(a: int, b: int, c: int, output: str): ..."
  },
  "scores": [
    [
      {
        "scorer_name": "dsl_completeness",
        "score": "C",
        "explanation": "{ \"C\": 30, \"I\": 0, \"TO\": 0 }"
      }
    ]
  ]
}
```

Key fields:

- `sample_id`: sample ID of the target
- `final_output.iteration` and `final_output.num_of_nodes`: tree-search statistics
- `final_output.generated_codes`: the generated formal specification
- `final_output.is_success`: whether Expecto generated specification successfully for this target
- `metadata.input`: the original natural-language problem statement
- `metadata.signature`: the postcondition signature Expecto tried to satisfy
- `scores`: evaluation results for completeness and soundness

## Inspecting NL2Postcond variants

For `NL2Postcond` variants (`nl2_base`, `nl2_simple`), sample-level results are stored together in `evaluation_results.json`.

```bash
find /workspace/data/experiment/artifact/target/runs/apps/nl2_base -name evaluation_results.json
```

Expected output:
- Prints one or more paths to `evaluation_results.json`, which stores the per-sample NL2Postcond evaluation results.
- Raw data:
  - `/workspace/data/experiment/artifact/target/runs/apps/nl2_base/`
- Outputs:
  - `/workspace/data/experiment/artifact/target/runs/apps/nl2_base/.../evaluation_results.json`

A typical entry in `evaluation_results.json` looks like this:

```json
[
  {
    "task_id": "15",
    "assertion": "...",
    "is_complete": true,
    "is_sound": true,
    "complete_ratio": 0.0,
    "sound_ratio": 0.0,
    "true_cnt_correct": 178,
    "false_cnt_correct": 0,
    "error_cnt_correct": 0,
    "true_cnt_mutated": 178,
    "false_cnt_mutated": 0,
    "error_cnt_mutated": 0,
    "msg_completeness": "Success",
    "msg_soundness": "Success"
  },
  ...
]
```

Key fields:

- `task_id`: the sample ID of the target
- `assertion`: the generated postcondition assertion
- `is_complete`: whether the assertion was complete on the evaluation set
- `is_sound`: whether the assertion was sound on the evaluation set
- `complete_ratio` and `sound_ratio`: the fraction of test cases that passed the completeness and soundness checks
- `true_cnt_correct`, `false_cnt_correct`, and `error_cnt_correct`: counts for correct test cases
- `msg_completeness` and `msg_soundness`: stderr messages from the evaluation

# 4. Reproducing the full paper results

This is the most complete run. It executes everything needed for `RQ1` to `RQ4`.

Expected runtime for `full`: about 50 hours.

```bash
python3 scripts/run_artifact.py full
```

Expected output:
- Runs all experiments required for `RQ1` to `RQ4` and generates all paper tables and figures.
- Raw data:
  - `/workspace/data/experiment/artifact/full/runs/apps/`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/`
  - `/workspace/data/experiment/artifact/full/runs/defects4j/`
- Outputs:
  - Table 1 (RQ1 main comparison): `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.rq1.table.pdf`
  - Fig. 8 (RQ1 threshold analysis): `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.thresholds.pdf`
  - Fig. 9 (RQ2 generation algorithm ablation): `/workspace/data/experiment/artifact/full/figures/rq2/evaluation.rq2.pdf`
  - Fig. 10 (RQ3 test-case ablation): `/workspace/data/experiment/artifact/full/figures/rq3/evaluation.rq3.testcase.pdf`
  - Table 2 (RQ4 Defects4J comparison): `/workspace/data/experiment/artifact/full/figures/rq4/evaluation.rq4.defects4j.table.pdf`

By default, the runner skips work that already has output files. Use `--force` if you want to rerun all over again from the same output root.

```bash
python3 scripts/run_artifact.py full --force
```
# 5. Reproducing specific RQs

Use `rq1`, `rq2`, `rq3`, or `rq4` when you want one research question and its outputs without running the entire artifact.

If you have already finished `full`, you do not need to run the individual RQ commands again unless you want to inspect or rerun one part.

```bash
python3 scripts/run_artifact.py <RQ_NUMBER>
```

Expected output:
- Runs only the selected research question under the `full` profile.
- Raw data:
  - `/workspace/data/experiment/artifact/full/runs/`
- Outputs:
  - `/workspace/data/experiment/artifact/full/figures/<RQ_NUMBER>/`

## RQ1. Effectiveness of Expecto in formal specification generation

`RQ1` compares full Expecto (`ts`) against the two NL2Postcond baselines on `APPS` and `HumanEval+`.

```bash
python3 scripts/run_artifact.py rq1
```

Expected output:
- Runs six raw experiment units for `RQ1` and generates the main comparison table and threshold figure.
- Raw data:
  - `/workspace/data/experiment/artifact/full/runs/apps/{ts,nl2_base,nl2_simple}`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/{ts,nl2_base,nl2_simple}`
- Outputs:
  - Table 1 (RQ1 main comparison): `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.rq1.table.pdf`
  - Fig. 8 (RQ1 threshold analysis): `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.thresholds.pdf`

What this command does:

- Runs six raw experiment units: `apps/ts`, `apps/nl2_base`, `apps/nl2_simple`, `humaneval_plus/ts`, `humaneval_plus/nl2_base`, and `humaneval_plus/nl2_simple`
- Uses `ts` as the full Expecto configuration and compares it against NL2Postcond `Base` and `Simple`

How this maps to the paper:

- Paper section: `Section 4.2`
- Paper artifacts: `Table 1` and `Fig. 8`
- Claim being checked: Expecto performs better than NL2Postcond `Base` and `Simple` in formal specification generation

## RQ2. Effectiveness of top-down synthesis with tree search

`RQ2` compares three Expecto variants: `mono`, `topdown`, and `ts`.

```bash
python3 scripts/run_artifact.py rq2
```
Expected output:
- Runs six Expecto ablation units and generates the `RQ2` comparison figure.
- Raw data:
  - `/workspace/data/experiment/artifact/full/runs/apps/{mono,topdown,ts}`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/{mono,topdown,ts}`
- Outputs:
  - `/workspace/data/experiment/artifact/full/figures/rq2/evaluation.rq2.pdf`

Paper mapping:

- Paper section: `Section 4.3`
- Output: `Fig. 9`
- Claim being checked: top-down decomposition and tree search improve specification generation quality

## RQ3. Impact of test cases on specification generation

`RQ3` compares the full method (`ts`) with the version that does not use test cases (`without_tc`).

```bash
python3 scripts/run_artifact.py rq3
```
Expected output:
- Runs four experiment units and generates the `RQ3` test-case ablation figure.
- Raw data:
  - `/workspace/data/experiment/artifact/full/runs/apps/{ts,without_tc}`
  - `/workspace/data/experiment/artifact/full/runs/humaneval_plus/{ts,without_tc}`
- Outputs:
  - `/workspace/data/experiment/artifact/full/figures/rq3/evaluation.rq3.testcase.pdf`

Paper mapping:

- Paper section: `Section 4.4`
- Output: `Fig. 10`
- Claim being checked: test cases improve the robustness of specification generation

## RQ4. Effectiveness of Expecto for bug detection in real-world software

`RQ4` uses the `Defects4J` benchmark to compare Expecto with the two NL2Postcond baselines.

```bash
python3 scripts/run_artifact.py rq4
```
Expected output:
- Runs three `Defects4J` experiment units and generates the `RQ4` summary table.
- Raw data:
  - `/workspace/data/experiment/artifact/full/runs/defects4j/{ts,nl2_base,nl2_simple}`
- Outputs:
  - `/workspace/data/experiment/artifact/full/figures/rq4/evaluation.rq4.defects4j.table.pdf`

Paper mapping:

- Paper section: `Section 4.5`
- Output: `Table 2`
- Claim being checked: Expecto finds more bug-detectable correct specifications than NL2Postcond on real-world Java bugs

# 6. Running reduced benchmarks for quick inspection

The `mini` profile uses fixed smaller subsets. It is useful when you want a faster run that shows the same overall trend as the paper, but not the exact final numbers.

```bash
python3 scripts/run_artifact.py mini
```
Expected output:
- Runs reduced versions of `RQ1` to `RQ4` and generates reduced figures and tables.
- Raw data:
  - `/workspace/data/experiment/artifact/mini/runs/`
- Outputs:
  - `/workspace/data/experiment/artifact/mini/figures/`

You can also run one research question with the mini profile.

```bash
python3 scripts/run_artifact.py <RQ_NUMBER> --mini
```
Expected output:
- Runs only the selected RQ on the fixed mini subset and writes reduced outputs for that RQ only.
- Raw data:
  - `/workspace/data/experiment/artifact/mini/runs/`
- Outputs:
  - `/workspace/data/experiment/artifact/mini/figures/<RQ_NUMBER>/`

The fixed sample IDs used by `mini` are listed below. You do not need these IDs unless you want to inspect exactly which subset is used.

- APPS IDs: `15, 57, 23, 76, 83, 39, 101, 3701, 4004, 37, 94, 16, 61, 52, 42, 47, 72, 90, 4005, 71`
- HumanEval+ IDs: `22, 52, 75, 61, 83, 92, 34, 53, 73, 129, 140, 158, 54, 124, 6, 71, 32, 123, 162, 63`
- Defects4J IDs:

```text
Chart_6_workspace_objdump_d4j_full_fresh_chart_6_source_org_jfree_chart_util_ShapeList_java_boolean_equals_Object_obj, Cli_18_workspace_objdump_d4j_full_fresh_cli_18_src_java_org_apache_commons_cli_PosixParser_java_void_processOptionToken_String_token_boolean_stopAtNonOption, Compress_40_workspace_objdump_d4j_full_compress_40_src_main_java_org_apache_commons_compress_utils_BitInputStream_java_long_readBits_int_count, Jsoup_76_workspace_objdump_d4j_full_jsoup_76_src_main_java_org_jsoup_parser_HtmlTreeBuilderState_java_boolean_process_Token_t_HtmlTreeBuilder_tb, Jsoup_85_workspace_objdump_d4j_full_jsoup_85_src_main_java_org_jsoup_nodes_Attribute_java_Attribute_String_key_String_val_Attributes_parent, Lang_32_workspace_objdump_d4j_full_lang_32_src_main_java_org_apache_commons_lang3_builder_HashCodeBuilder_java_boolean_isRegistered_Object_value, Math_35_workspace_objdump_d4j_full_math_35_src_main_java_org_apache_commons_math3_genetics_ElitisticListPopulation_java_ElitisticListPopulation_int_populationLimit_double_elitismRate, Math_73_workspace_objdump_d4j_full_math_73_src_main_java_org_apache_commons_math_analysis_solvers_BrentSolver_java_double_solve_UnivariateRealFunction_f_double_min_double_max, Math_80_workspace_objdump_d4j_full_math_80_src_main_java_org_apache_commons_math_linear_EigenDecompositionImpl_java_boolean_flipIfWarranted_int_n_int_step, Math_96_workspace_objdump_d4j_full_math_96_src_java_org_apache_commons_math_complex_Complex_java_boolean_equals_Object_other, Cli_10_workspace_objdump_d4j_full_fresh_cli_10_src_java_org_apache_commons_cli_Parser_java_CommandLine_parse_Options_options_String_arguments_Properties_properties_boolean_stopAtNonOption, Cli_18_workspace_objdump_d4j_full_fresh_cli_18_src_java_org_apache_commons_cli_PosixParser_java_String_flatten_Options_options_String_arguments_boolean_stopAtNonOption, Cli_32_workspace_objdump_d4j_full_fresh_cli_32_src_main_java_org_apache_commons_cli_HelpFormatter_java_int_findWrapPos_String_text_int_width_int_startPos, Closure_114_workspace_objdump_d4j_full_fresh_closure_114_src_com_google_javascript_jscomp_NameAnalyzer_java_void_visit_NodeTraversal_t_Node_n_Node_parent, Closure_74_workspace_objdump_d4j_full_fresh_closure_74_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldBinaryOperator_Node_subtree, Closure_78_workspace_objdump_d4j_full_fresh_closure_78_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldArithmeticOp_Node_n_Node_left_Node_right, Closure_97_workspace_objdump_d4j_full_fresh_closure_97_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldBinaryOperator_Node_subtree, Codec_4_workspace_objdump_d4j_full_codec_4_src_java_org_apache_commons_codec_binary_Base64_java_byte_encodeBase64_byte_binaryData_boolean_isChunked_boolean_urlSafe_int_maxResultSize, Jsoup_38_workspace_objdump_d4j_full_jsoup_38_src_main_java_org_jsoup_parser_HtmlTreeBuilderState_java_boolean_process_Token_t_HtmlTreeBuilder_tb, Jsoup_46_workspace_objdump_d4j_full_jsoup_46_src_main_java_org_jsoup_nodes_Entities_java_void_escape_StringBuilder_accum_String_string_Document_OutputSettings_out_boolean_inAttribute_boolean_normaliseWhite_boolean_stripLeadingWhite
```

`mini` is not meant to reproduce the exact paper numbers. It is meant for quick inspection and trend checking.
