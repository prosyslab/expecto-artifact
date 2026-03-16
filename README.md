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

First, obtain the Docker image that includes the datasets, dependencies, and experiment codes.
Pulling the image is the easiest option.

```bash
docker pull prosyslab/expecto-artifact
```

If you downloaded `expecto-artifact.tar.gz` from Zenodo, you can load it instead.

```bash
gunzip -c expecto-artifact.tar.gz | docker load
```

You can verify that the image was pulled or loaded correctly with:
```bash
docker images | grep expecto-artifact
> prosyslab/expecto-artifact   latest    ...
```

### Step 2. Start the container

```bash
docker run -it --name expecto-artifact prosyslab/expecto-artifact zsh
```

### Step 3. Create the `.env` file

Inside the container, move to `/workspace/expecto-artifact` and create a `.env` file containing your OpenAI API key.

```bash
cd /workspace/expecto-artifact
cat > .env <<'EOF'
OPENAI_API_KEY=YOUR_KEY_HERE
EOF
```

### Step 4. Check the setup with the test script (~2 minutes)

The following script checks whether the setup has been completed successfully.
In particular, make sure that all items in the `Summary` section are marked as `[PASS]`.

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
```

This test script checks the following:
1. Required datasets exist
2. `OPENAI_API_KEY` is set
3. The RQ1 experiment from the paper can be executed for a single sample, and the final figure files are generated correctly
*Note: the figures generated here are not intended to reproduce the exact values reported in the paper. They are meant to verify that the execution process works correctly before you begin the full reproduction.*

# 2. Directory structure
expecto-artifact has the following directory structure:
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

Generated outputs from the artifact runner are written under:
```text
/workspace/data/experiment/artifact
├── target/                            <- Outputs for targeted reproduction (See Section 3 of this README)
│   └── runs/                          <- Raw LLM outputs and raw evaluation results by benchmark and configuration
│       ├── apps/                      <- APPS outputs
│       ├── humaneval_plus/            <- HumanEval+ outputs
│       └── defects4j/                 <- Defects4J outputs
├── full/                              <- Outputs for full paper reproduction (See Sections 4 and 5 of this README)
│   ├── runs/                          <- Raw LLM outputs and raw evaluation results by benchmark and configuration
│   └── figures/                       <- Generated tables and figures used in the paper
│       ├── rq1/                       <- Figures for RQ1
│       ├── rq2/                       <- Figures for RQ2
│       ├── rq3/                       <- Figures for RQ3
│       └── rq4/                       <- Figures for RQ4
├── mini/                              <- Outputs for reduced mini benchmarks (See Section 6 of this README)
│   ├── runs/
│   └── figures/
```

# 3. Reproducing specific benchmark problems
This section explains how to generate and evaluate a specific benchmark problem with a specific configuration.
In the paper, we used three different benchmarks, four Expecto variant configurations, and two NL2Postcond variant configurations.
This section shows how to run any benchmark by specifying the problem ID for each of the 3 x (4 + 2) = 18 possible combinations.

## 3.1 Reproducing the paper's motivating example: APPS problem `75`
To compare Expecto with the two NL2Postcond variants (`nl2_base` and `nl2_simple`) on the motivating example of the paper, run the following three commands:

```bash
python3 scripts/run_artifact.py target \
  --benchmark apps \
  --variant ts \ # Expecto with tree search and test cases
  --sample-ids 75

python3 scripts/run_artifact.py target \
  --benchmark apps \
  --variant nl2_base \ # NL2Postcond base prompt strategy
  --sample-ids 75

python3 scripts/run_artifact.py target \
  --benchmark apps \
  --variant nl2_simple \ # NL2Postcond simple prompt strategy
  --sample-ids 75
```

Each command writes its result to:

- `/workspace/data/experiment/artifact/target/runs/apps/ts/sample_results.json`:
```json
[
  {
    "id": "75",
    "classification": "S&C",
    "postcondition": "predicate spec(n: int, m: int, grid: list[string], out_status: string, out_x: int, out_y: int) { ... }"
  }
]
```
- `/workspace/data/experiment/artifact/target/runs/apps/nl2_base/sample_results.json`:
```json
[
  {
    "id": "75",
    "classification": "S",
    "postcondition": "assert ..."
  }
]
```
- `/workspace/data/experiment/artifact/target/runs/apps/nl2_simple/sample_results.json`:
```json
[
  {
    "id": "75",
    "classification": "C",
    "postcondition": "assert ..."
  }
]
```

Each `sample_results.json` entry contains:

- `id`: the benchmark problem ID. Here it is always `75`.
- `classification`: the evaluation result for the generated specification. In the paper's comparison, Expecto (`ts`) produces `S&C` (sound and complete), while the two NL2Postcond variants produce `S` or `C`, matching the discussion that their monolithic outputs are incomplete or unsound.
- `postcondition`: the generated formal specification itself. Expecto emits a DSL specification like `predicate spec(...)`. NL2Postcond emits a single assertion like `assert ...`.

## 3.2 How to run other target problems
```bash
python3 scripts/run_artifact.py target \
  --benchmark <BENCHMARK> \
  --variant <VARIANT> \
  --sample-ids <SAMPLE-IDS>
```

- `BENCHMARK` specifies which benchmark to generate. You can choose one of `apps`, `humaneval_plus`, or `defects4j`.
- `VARIANT` specifies the Expecto or NL2Postcond configuration used in the paper.
  - For Expecto, the following four configurations are available:
    1. `mono`: the monolithic synthesis without top-down decomposition or tree search (section 4.3 in the paper)
    2. `topdown`: the top-down synthesis without tree search (section 4.3 in the paper)
    3. `ts`: the top-down synthesis with tree search (sections 4.2, 4.3, 4.4, and 4.5 in the paper)
    4. `without_tc`: the top-down tree-search synthesis without test cases (section 4.4 in the paper)
  - For NL2Postcond, the following two configurations are available:
    1. `nl2_base`: the NL2Postcond base prompt strategy (sections 4.2 and 4.5 in the paper)
    2. `nl2_simple`: the NL2Postcond simple prompt strategy (sections 4.2 and 4.5 in the paper)
- `SAMPLE-IDS` specifies the IDs of the benchmark problems to generate as a comma-separated list. For example, you can provide `15,23,56`. You can find the list of available problem IDs for each benchmark in `/workspace/expecto-artifact/datasets/available_target_ids.csv`.

## 3.3 What this command does
This command generates the LLM's raw output and evaluates the generated specifications for soundness and completeness.
The generated outputs and evaluation results are saved at `/workspace/data/experiment/artifact/target/runs/<BENCHMARK>/<VARIANT>`.
After the evaluation is complete, the runner also generates `/workspace/data/experiment/artifact/target/runs/<BENCHMARK>/<VARIANT>/sample_results.json`, so you can immediately inspect the classification result for each sample.

`sample_results.json` is a list of objects per sample, and each object contains the following fields:

- `id`: the sample ID
- `classification`: the sample classification result
  - `S&C`: sound and complete
  - `S`: sound but incomplete
  - `C`: complete but unsound
  - `W`: neither sound nor complete
- `postcondition`: the generated postcondition
  - Expecto generates postconditions in the form of `predicate spec(...) { ... }`
  - NL2Postcond generates postconditions in the form of `assert ...`

# 4. Reproducing the full paper results

4장에서는 `RQ1`부터 `RQ4`까지 논문의 모든 실험을 실행하는 `full` 명령에 대해서 설명합니다.
3장에서 수행한 specification generation과 evaluation을 전체 벤치마크에 대해서 수행한 후, 논문 figure와 table 형태로 최종 산출물을 생성합니다.
`full` 명령의 총 예상 소요 시간은 약 50시간입니다.

## 4.1 How to run
```bash
python3 scripts/run_artifact.py full
```

## 4.2 What this does
- 실행 및 :
  - `/workspace/data/experiment/artifact/full/runs/<BENCHMARK>/<VARIANT>/`
  - `/workspace/data/experiment/artifact/full/runs/<BENCHMARK>/<VARIANT>/sample_results.json`
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
  - Each executed variant also writes `/workspace/data/experiment/artifact/full/runs/<BENCHMARK>/<VARIANT>/sample_results.json`
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
  - Each executed variant also writes `/workspace/data/experiment/artifact/mini/runs/<BENCHMARK>/<VARIANT>/sample_results.json`
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
  - Each executed variant also writes `/workspace/data/experiment/artifact/mini/runs/<BENCHMARK>/<VARIANT>/sample_results.json`
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
