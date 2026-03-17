# Expecto: Extracting Formal Specifications from Natural Language Description for Trustworthy Oracles (Artifact)

This repository contains the artifact implementation for the paper *Expecto: Extracting Formal Specifications from Natural Language Description for Trustworthy Oracles*.

# 1. Getting started

## 1.1 System requirements
The experiments in the paper were conducted with the following setup:

- Ubuntu 22.04
- Docker 24.0.2
- 64 CPU cores (Xeon Gold 6226R)
- 512 GB RAM
- 256 GB storage

## 1.2 Setup with Docker

### Step 1. Pull or load the Docker image

First, obtain the Docker image that includes the datasets, dependencies, and experiment code.
Pulling the image is the easiest option.

```bash
docker pull prosyslab/expecto-artifact
```

If you downloaded `expecto-artifact.tar.gz` from Zenodo, you can load it instead.

```bash
gunzip -c expecto-artifact.tar.gz | docker load
```

You can verify that the image was pulled or loaded correctly by running:
```bash
docker images | grep expecto-artifact
> prosyslab/expecto-artifact   latest    ...
```

### Step 2. Start the container

```bash
docker run -it --name expecto-artifact prosyslab/expecto-artifact zsh
```

### Step 3. Create the `.env` file

Expecto uses GPT-4.1-mini (OpenAI) as its LLM backend, so you need a valid
OpenAI API key to run the experiments.
Inside the container, change to `/workspace/expecto-artifact` and create a `.env` file with your OpenAI API key.

```bash
cd /workspace/expecto-artifact
cat > .env <<'EOF'
OPENAI_API_KEY=YOUR_KEY_HERE
EOF
```

### Step 4. Check the setup with the test script

Run the following script to confirm that the setup completed successfully.
Make sure every item in the `Summary` section is marked as `[PASS]`.
**It takes about 2 minutes.**

Command:
```bash
python3 scripts/test.py
```

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
[PASS] sample result outputs
```

This test script checks the following:
1. Required datasets exist
2. `OPENAI_API_KEY` is set
3. The RQ1 experiment can run on a single sample, and the final figure files are generated correctly

*Note: the figures generated here are not intended to reproduce the exact values reported in the paper. They only verify that the workflow runs correctly before you begin the full reproduction.*

## 1.3 Notion before you start
- LLM non-determinism: The generated specifications and their classifications may differ from the paper because of LLM non-determinism. However, the overall tendencies (e.g., Expecto producing more `S&C` specifications than NL2Postcond) should still hold.

# 2. Directory structure
The `expecto-artifact` repository has the following directory structure:

```text
/workspace/expecto-artifact
├── README.md                          <- The top-level README (this file)
├── analyzer/                          <- Figure and table generation scripts
├── datasets/                          <- HumanEval+, APPS, and Defects4J datasets
├── expecto/                           <- Core Expecto implementation
├── nl-2-postcond/                     <- NL2Postcond baseline from FSE '24
└── scripts/                           <- Scripts for running artifact experiments
    └── run_artifact.py                <- Main artifact runner
```

Generated outputs from the artifact runner are written under (★ indicates the main output files to check):

```text
/workspace/data/experiment/artifact
├── target/                            <- Outputs for targeted reproduction
│   │                                      (See Section 3 of this README)
│   └── runs/                          <- Raw LLM outputs and raw evaluation
│       │                                  results for each benchmark and configuration
│       └── <BENCHMARK>/<CONFIG>/      <- Outputs generated for the selected benchmark/configuration
│           └── ★sample_results.json   <- JSON file summarizing generated sample results
├── full/                              <- Outputs for full paper reproduction
│   │                                      (See Sections 4 and 5 of this README)
│   ├── runs/                          <- Raw LLM outputs and raw evaluation
│   │                                      results for each benchmark and configuration
│   └── ★figures/                      <- Processed tables and figures from the paper,
│       │                                  generated from `runs/`
│       ├── rq1/                       <- Figures for RQ1
│       ├── rq2/                       <- Figures for RQ2
│       ├── rq3/                       <- Figures for RQ3
│       └── rq4/                       <- Figures for RQ4
└── mini/                              <- Outputs for reduced mini benchmarks
    │                                      (See Section 6 of this README)
    ├── runs/
    └── figures/
```

# 3. Reproducing specific benchmark problems
This section explains how to generate and evaluate a benchmark problem with a chosen configuration.
The paper uses three benchmarks, four Expecto configurations, and two NL2Postcond configurations.
You can run any of combinations by specifying the problem ID.

## 3.1 Reproducing the paper's motivating example (Fig. 2)
To compare Expecto with the two NL2Postcond configurations (`nl2_base` and `nl2_simple`) on the paper's motivating example, run the following three commands:

```bash
python3 scripts/run_artifact.py target \
  --benchmark apps \
  --config ts \
  --sample-ids 75

python3 scripts/run_artifact.py target \
  --benchmark apps \
  --config nl2_base \
  --sample-ids 75

python3 scripts/run_artifact.py target \
  --benchmark apps \
  --config nl2_simple \
  --sample-ids 75
```

Each command writes its result to:

- `/workspace/data/experiment/artifact/target/runs/apps/ts/sample_results.json`:
```json
[
  {
    "id": "75",
    "classification": "S&C",
    "nl_description": "You are given a description of a depot...",
    "specification": "predicate spec(n: int, m: int, grid: list[string], out_status: string, out_x: int, out_y: int) { ... }"
  }
]
```
- `/workspace/data/experiment/artifact/target/runs/apps/nl2_base/sample_results.json`:
```json
[
  {
    "id": "75",
    "classification": "S",
    "nl_description": "You are given a description of a depot...",
    "specification": "assert ..."
  }
]
```
- `/workspace/data/experiment/artifact/target/runs/apps/nl2_simple/sample_results.json`:
```json
[
  {
    "id": "75",
    "classification": "C",
    "nl_description": "You are given a description of a depot...",
    "specification": "assert ..."
  }
]
```

Each `sample_results.json` entry contains:

- `id`: the benchmark problem ID. Here it is always `75`.
- `classification`: the evaluation result for the generated specification. Here, Expecto produces sound and complete (`S&C`). In contrast, the two NL2Postcond configurations produce sound and incomplete (`S`) or complete and unsound (`C`) specifications, respectively.
- `nl_description`: the original natural-language description from the APPS benchmark prompt.
- `specification`: the generated formal specification itself. Figure2에 등장하는 specification들은 이 필드에 저장되어 있습니다. Expecto emits a DSL specification like `predicate spec(...)`. NL2Postcond emits a single assertion like `assert ...`.

## 3.2 How to run other target problems
```bash
python3 scripts/run_artifact.py target \
  --benchmark <BENCHMARK> \
  --config <CONFIG> \
  --sample-ids <SAMPLE-IDS>
```

- `BENCHMARK` specifies which benchmark to generate. You can choose one of `apps`, `humaneval_plus`, or `defects4j`.
- `CONFIG` specifies the Expecto or NL2Postcond configuration used in the paper.

| Method | `CONFIG` value | Description | Used paper section(s) |
| --- | --- | --- | --- |
| Expecto | `mono` | Monolithic specification synthesis + Specification validation with test cases | 4.3 |
| Expecto | `topdown` | Top-down specification synthesis + Specification validation with test cases | 4.3 |
| Expecto | `ts` | Tree search specification synthesis + Specification validation with test cases | 4.2, 4.3, 4.4, 4.5 |
| Expecto | `without_tc` | Tree search specification synthesis | 4.4 |
| NL2Postcond | `nl2_base` | NL2Postcond base prompt strategy | 4.2, 4.5 |
| NL2Postcond | `nl2_simple` | NL2Postcond simple prompt strategy | 4.2, 4.5 |
- `SAMPLE-IDS` specifies the benchmark problem IDs as a comma-separated list. For example, you can provide `15,23,56`. You can find the available IDs for each benchmark in `/workspace/expecto-artifact/datasets/available_target_ids.csv`.

## 3.3 What this command does
This command generates raw LLM outputs and evaluates the resulting specifications for soundness and completeness.
The generated outputs and evaluation results are saved at `/workspace/data/experiment/artifact/target/runs/<BENCHMARK>/<CONFIG>`.
After the evaluation is complete, the runner also generates `/workspace/data/experiment/artifact/target/runs/<BENCHMARK>/<CONFIG>/sample_results.json`, so you can immediately inspect the classification result, original natural-language description, and generated specification for each sample.

`sample_results.json` contains one object per sample, and each object has the following fields:

- `id`: the sample ID
- `classification`: the sample classification result. It can be one of the following values:
  - `S&C`: sound and complete
  - `S`: sound but incomplete
  - `C`: complete but unsound
  - `W`: neither sound nor complete
- `nl_description`: the original natural-language description
  - APPS and HumanEval+ use the benchmark prompt text
  - Defects4J uses the method Javadoc description
- `specification`: the generated specification
  - Expecto generates specifications in the form of `predicate spec(...) { ... }`
  - NL2Postcond generates specifications in the form of `assert ...`

# 4. Reproducing the full paper results

This section explains the `full` command, which runs all experiments in the paper for `RQ1` through `RQ4`.
It performs the generation and evaluation described in Section 3 on the full benchmarks, then produces the paper's figures and tables.
The total expected runtime of the `full` command is approximately 50 hours.

## 4.1 How to run
**It takes about 50 hours.**
```bash
python3 scripts/run_artifact.py full
```

## 4.2 What this does
Running the command above generates specifications for the three benchmarks, the four Expecto configurations, and the two NL2Postcond configurations used in the paper. This results in 3 x (4 + 2) = 18 generation-and-evaluation runs.
It then processes the outputs into the same figure and table formats shown in the paper.

- The results for each benchmark / generation-configuration combination are stored at:
  - `/workspace/data/experiment/artifact/full/runs/<BENCHMARK>/<CONFIG>/sample_results.json`
- The paper's figures and tables are stored at:
  - Table 1 (RQ1 main comparison): `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.rq1.table.pdf`
  - Fig. 8 (RQ1 threshold analysis): `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.thresholds.pdf`
  - Fig. 9 (RQ2 generation algorithm ablation): `/workspace/data/experiment/artifact/full/figures/rq2/evaluation.rq2.pdf`
  - Fig. 10 (RQ3 test-case ablation): `/workspace/data/experiment/artifact/full/figures/rq3/evaluation.rq3.testcase.pdf`
  - Table 2 (RQ4 Defects4J comparison): `/workspace/data/experiment/artifact/full/figures/rq4/evaluation.rq4.defects4j.table.pdf`

For details on each RQ, see Section 5.

# 5. Reproducing each RQ
This section explains the commands and outputs used to reproduce each research question (`RQ`).
If you have already completed the full experiment with the `full` command, you can inspect the generated outputs instead of running the commands again.

## 5.1 RQ1: Effectiveness of Expecto in formal specification generation (Table 1 and Fig. 8)
This experiment compares Expecto against the two NL2Postcond prompt strategies (`nl2_base` and `nl2_simple`) on the APPS and HumanEval+ benchmarks.
For Expecto, the comparison uses the tree-search-with-test-cases (`ts`) configuration.

### 5.1.1 How to run
**It takes about 12 hours from scratch, but if you have already run the `full` command, you can skip this step and inspect the generated outputs instead.** 
```bash
python3 scripts/run_artifact.py rq1
```

### 5.1.2 What this does
This command runs specification generation and evaluation for six experiment settings (2 benchmarks x 3 configs) and produces the main `RQ1` outputs: Table 1 and Fig. 8.
Table 1 shows the number of samples in each classification category (`S&C`, `S`, `C`, and `W`) for each setting.
Fig. 8 shows how the number of samples in the `S&C` and `W` categories changes as the threshold `X` in the soundness criterion varies.
For example, suppose a benchmark has 10 incorrect input-output pairs, and a generated specification rejects 8 of them.
Then the specification is sound when `X = 80`, because it catches at least 80% of the incorrect pairs, but it is not sound when `X = 90`.
Fig. 8 repeats this counting for different threshold values and shows how the classification changes.
The generated table and figure can be found at:
- Table 1 (RQ1 main comparison): `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.rq1.table.pdf`
- Fig. 8 (RQ1 threshold analysis): `/workspace/data/experiment/artifact/full/figures/rq1/evaluation.thresholds.pdf`

## 5.2 RQ2: Effectiveness of top-down synthesis with tree search
This experiment evaluates the two main generation components of Expecto: top-down specification synthesis and tree search.
It compares three Expecto configurations on the APPS and HumanEval+ benchmarks: monolithic generation (`mono`), top-down synthesis without tree search (`topdown`), and top-down synthesis with tree search (`ts`).

### 5.2.1 How to run
**It takes about 24 hours from scratch, but if you have already run the `full` command, you can skip this step and inspect the generated outputs instead.**
```bash
python3 scripts/run_artifact.py rq2
```

### 5.2.2 What this does
This command runs specification generation and evaluation for six Expecto ablation settings (2 benchmarks x 3 configs) and produces the main `RQ2` output, Fig. 9.
Fig. 9 is a bar chart comparing the number of samples in each classification category for different Expecto generation algorithms.
It shows that introducing top-down synthesis and tree search improves the quality of the generated specifications, for example by increasing the number of `S&C` specifications and decreasing the number of `W` specifications.
This can be seen from the fact that, for each benchmark, the number of `S&C` specifications increases in the order `mono < topdown < ts`.
The generated figure can be found at:
- Fig. 9 (RQ2 generation algorithm ablation): `/workspace/data/experiment/artifact/full/figures/rq2/evaluation.rq2.pdf`

## 5.3 RQ3: Impact of test cases on specification generation
This experiment measures how much user-provided test cases help Expecto during specification generation.
It compares the full tree-search configuration with test cases (`ts`) against the version that does not use test cases (`without_tc`) on the APPS and HumanEval+ benchmarks.

### 5.3.1 How to run
**It takes about 18 hours from scratch, but if you have already run the `full` command, you can skip this step and inspect the generated outputs instead.**
```bash
python3 scripts/run_artifact.py rq3
```

### 5.3.2 What this does
This command runs specification generation and evaluation for four experiment settings (2 benchmarks x 2 configs) and produces the main `RQ3` output, Fig. 10.
Fig. 10 is a bar chart comparing the number of samples in each classification category (`S&C`, `S`, `C`, `W`) between the `ts` configuration, which uses test cases, and the `without_tc` configuration, which does not.
It shows that introducing test cases improves the quality of the generated specifications, for example by increasing the number of `S&C` specifications.
The generated figure can be found at:
- Fig. 10 (RQ3 test-case ablation): `/workspace/data/experiment/artifact/full/figures/rq3/evaluation.rq3.testcase.pdf`

## 5.4 RQ4: Effectiveness of Expecto for bug detection in real-world software
This experiment evaluates whether Expecto can generate bug-detecting specifications for real-world software methods.
It compares Expecto with the two NL2Postcond prompt strategies (`nl2_base` and `nl2_simple`) on the `Defects4J` benchmark, using the tree-search configuration with test cases (`ts`) for Expecto.

### 5.4.1 How to run
**It takes about 12 hours from scratch, but if you have already run the `full` command, you can skip this step and inspect the generated outputs instead.**
```bash
python3 scripts/run_artifact.py rq4
```

### 5.4.2 What this does
This command runs specification generation and evaluation for three `Defects4J` experiment settings (1 benchmark x 3 configs) and produces the main `RQ4` output, Table 2.
Table 2 compares the number of specifications in each classification category (`S&C`, `S`, `C`, `W`) produced on the `Defects4J` benchmark by Expecto (`ts`) and the two NL2Postcond prompt strategies (`nl2_base`, `nl2_simple`).
The table shows that Expecto produces more specifications that are both correct and capable of detecting bugs (`S&C`) than NL2Postcond,
while also producing fewer `W` specifications.
The generated table can be found at:
- Table 2 (RQ4 Defects4J comparison): `/workspace/data/experiment/artifact/full/figures/rq4/evaluation.rq4.defects4j.table.pdf`

# 6. Running reduced benchmarks for quick inspection

This section explains the `mini` command, which runs a reduced version of the experiments on fixed subsets of the benchmarks used in the paper.
It performs the same generation, evaluation, and figure/table export steps as the `full` command, but uses only 20 samples from each benchmark so that results can be produced much more quickly.

We recommend running `mini` first if you want to check your setup produces reasonable results before committing to the ~50-hour full run.

*Note: `mini` is not meant to reproduce the exact paper numbers. It is meant for quick inspection and trend checking.*

## 6.1 How to run

To run the reduced-profile experiments for `RQ1` through `RQ4`, use:
```bash
python3 scripts/run_artifact.py mini
```

If you only want to run the reduced-profile experiment for a specific `RQ`, specify the `RQ` number as follows:
```bash
python3 scripts/run_artifact.py <rq1|rq2|rq3|rq4> --mini
```

## 6.2 What this does

Running the command above executes the same experiment families as the `full` profile for `RQ1` through `RQ4`, but on fixed 20-sample subsets of APPS, HumanEval+, and Defects4J.
It writes per-run outputs to:
- `/workspace/data/experiment/artifact/mini/runs/<BENCHMARK>/<CONFIG>/sample_results.json`

It also generates the corresponding reduced-profile figures and tables at:
- Table 1 (RQ1 main comparison): `/workspace/data/experiment/artifact/mini/figures/rq1/evaluation.rq1.table.pdf`
- Fig. 8 (RQ1 threshold analysis): `/workspace/data/experiment/artifact/mini/figures/rq1/evaluation.thresholds.pdf`
- Fig. 9 (RQ2 generation algorithm ablation): `/workspace/data/experiment/artifact/mini/figures/rq2/evaluation.rq2.pdf`
- Fig. 10 (RQ3 test-case ablation): `/workspace/data/experiment/artifact/mini/figures/rq3/evaluation.rq3.testcase.pdf`
- Table 2 (RQ4 Defects4J comparison): `/workspace/data/experiment/artifact/mini/figures/rq4/evaluation.rq4.defects4j.table.pdf`

The fixed sample IDs used by `mini` are listed below. You do not need these IDs unless you want to inspect exactly which subset is used.

- APPS IDs: `15, 57, 23, 76, 83, 39, 101, 3701, 4004, 37, 94, 16, 61, 52, 42, 47, 72, 90, 4005, 71`
- HumanEval+ IDs: `22, 52, 75, 61, 83, 92, 34, 53, 73, 129, 140, 158, 54, 124, 6, 71, 32, 123, 162, 63`
- Defects4J IDs:
```text
Chart_6_workspace_objdump_d4j_full_fresh_chart_6_source_org_jfree_chart_util_ShapeList_java_boolean_equals_Object_obj, Cli_18_workspace_objdump_d4j_full_fresh_cli_18_src_java_org_apache_commons_cli_PosixParser_java_void_processOptionToken_String_token_boolean_stopAtNonOption, Compress_40_workspace_objdump_d4j_full_compress_40_src_main_java_org_apache_commons_compress_utils_BitInputStream_java_long_readBits_int_count, Jsoup_76_workspace_objdump_d4j_full_jsoup_76_src_main_java_org_jsoup_parser_HtmlTreeBuilderState_java_boolean_process_Token_t_HtmlTreeBuilder_tb, Jsoup_85_workspace_objdump_d4j_full_jsoup_85_src_main_java_org_jsoup_nodes_Attribute_java_Attribute_String_key_String_val_Attributes_parent, Lang_32_workspace_objdump_d4j_full_lang_32_src_main_java_org_apache_commons_lang3_builder_HashCodeBuilder_java_boolean_isRegistered_Object_value, Math_35_workspace_objdump_d4j_full_math_35_src_main_java_org_apache_commons_math3_genetics_ElitisticListPopulation_java_ElitisticListPopulation_int_populationLimit_double_elitismRate, Math_73_workspace_objdump_d4j_full_math_73_src_main_java_org_apache_commons_math_analysis_solvers_BrentSolver_java_double_solve_UnivariateRealFunction_f_double_min_double_max, Math_80_workspace_objdump_d4j_full_math_80_src_main_java_org_apache_commons_math_linear_EigenDecompositionImpl_java_boolean_flipIfWarranted_int_n_int_step, Math_96_workspace_objdump_d4j_full_math_96_src_java_org_apache_commons_math_complex_Complex_java_boolean_equals_Object_other, Cli_10_workspace_objdump_d4j_full_fresh_cli_10_src_java_org_apache_commons_cli_Parser_java_CommandLine_parse_Options_options_String_arguments_Properties_properties_boolean_stopAtNonOption, Cli_18_workspace_objdump_d4j_full_fresh_cli_18_src_java_org_apache_commons_cli_PosixParser_java_String_flatten_Options_options_String_arguments_boolean_stopAtNonOption, Cli_32_workspace_objdump_d4j_full_fresh_cli_32_src_main_java_org_apache_commons_cli_HelpFormatter_java_int_findWrapPos_String_text_int_width_int_startPos, Closure_114_workspace_objdump_d4j_full_fresh_closure_114_src_com_google_javascript_jscomp_NameAnalyzer_java_void_visit_NodeTraversal_t_Node_n_Node_parent, Closure_74_workspace_objdump_d4j_full_fresh_closure_74_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldBinaryOperator_Node_subtree, Closure_78_workspace_objdump_d4j_full_fresh_closure_78_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldArithmeticOp_Node_n_Node_left_Node_right, Closure_97_workspace_objdump_d4j_full_fresh_closure_97_src_com_google_javascript_jscomp_PeepholeFoldConstants_java_Node_tryFoldBinaryOperator_Node_subtree, Codec_4_workspace_objdump_d4j_full_codec_4_src_java_org_apache_commons_codec_binary_Base64_java_byte_encodeBase64_byte_binaryData_boolean_isChunked_boolean_urlSafe_int_maxResultSize, Jsoup_38_workspace_objdump_d4j_full_jsoup_38_src_main_java_org_jsoup_parser_HtmlTreeBuilderState_java_boolean_process_Token_t_HtmlTreeBuilder_tb, Jsoup_46_workspace_objdump_d4j_full_jsoup_46_src_main_java_org_jsoup_nodes_Entities_java_void_escape_StringBuilder_accum_String_string_Document_OutputSettings_out_boolean_inAttribute_boolean_normaliseWhite_boolean_stripLeadingWhite
```
