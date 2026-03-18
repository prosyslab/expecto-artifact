"""
This file is used to generate sample completions using the LLM model for a given prompt.
"""

import ast
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from textwrap import indent

import hydra
import log
import prompts
from benchmarks import load_benchmarks
from evalplus.data import write_jsonl
from log import make_header
from openai import OpenAI
from omegaconf import OmegaConf
from parallelism import get_scaled_worker_count
from tenacity import Retrying, stop_after_attempt, wait_random_exponential

CLIENT = None
DEFAULT_API_TIMEOUT_SECONDS = 120
DEFAULT_MAX_API_RETRIES = 8
MAX_GENERATION_WORKERS = 8


def get_worker_count() -> int:
    return get_scaled_worker_count(scale=0.8, maximum=MAX_GENERATION_WORKERS)


def get_positive_int(cfg, key: str, default: int) -> int:
    value = cfg.get(key, default)
    if value is None:
        return default
    return max(1, int(value))


def setup_api(api_cfg, print_and_log):
    """
    Sets up the OpenAI client.
    """
    global CLIENT
    api_key = os.getenv(api_cfg.key)
    assert api_key is not None, (
        "API key not found. Please set the {} environment variable.".format(
            api_cfg.key
        )
    )
    CLIENT = OpenAI(api_key=api_key)


def load_postconditions(evaluated_post_conditions_file):
    with open(evaluated_post_conditions_file, "r") as f:
        evals = [json.loads(line) for line in f]

    postconditions = {}
    for e in evals:
        if e["task_id"] not in postconditions:
            postconditions[e["task_id"]] = [e]
        else:
            postconditions[e["task_id"]].append(e)

    # assert that each task_id has the same number of postconditions
    assert len(set([len(postconditions[k]) for k in postconditions])) == 1, (
        "Uneven number of postconditions per task_id"
    )
    return postconditions


def get_variable_usage_sentence(benchmark_name: str) -> str:
    benchmark_name = benchmark_name.lower()
    if "apps" in benchmark_name:
        return "For variables, the ${toGenerateShort} should only use the input parameters defined in the function stub. Do not assume any additional variables or return values are defined like `return_value`."
    return "For variables, the ${toGenerateShort} should only use the input parameters defined in the function stub and a hypothetical return value of the function, which we'll assume is stored in a variable `return_value`."


def prepare_prompt(exper_cfg, problem, benchmark_name="") -> str:
    # Set all of the default values
    toGenerateFull = ""
    toGenerateShort = ""
    toGenerateGoal = ""
    toUse = ""
    toGenerateShortCaps = ""
    promptAdds = ""
    (problem.keys())
    entrypoint = problem.get("entry_point", "")
    code = problem.get("prompt", problem.get("question", ""))

    if "signature" in problem:
        parsed_signature = ast.parse(problem["signature"])
        fdef: ast.FunctionDef = parsed_signature.body[0]
        docstr = ast.get_docstring(fdef)
        docstr = "" if docstr is None else docstr
        docstr += "\n" + code
        code = (
            problem["signature"].split("\n")[0]
            + "\n"
            + indent('"""\n' + docstr + '\n"""', " " * 4)
        )

    # If we are doing the code generation task (used to generate buggy code mutants)
    if exper_cfg.to_generate == "code":
        if exper_cfg.gen_buggy == False:
            return prompts.genCode.substitute(
                codeStubAndDocstring=code, entrypoint=entrypoint
            )
        else:
            return prompts.genCodeBuggy.substitute(
                codeStubAndDocstring=code, entrypoint=entrypoint
            )

    if exper_cfg.has_reference_code:
        solution = problem.get("canonical_solution", None)
        if solution is None:
            solutions = problem.get("solutions", None)
            if solutions is not None:
                try:
                    first_solution = solutions[0]
                    code += first_solution
                except json.JSONDecodeError:
                    pass
        else:
            code += solution
        promptTemplate = prompts.genOneWithRef[exper_cfg.prompt_v]
    else:
        promptTemplate = prompts.genOneNoRef[exper_cfg.prompt_v]

    if exper_cfg.to_generate == "postcondition":
        toGenerateFull = "symbolic postcondition"
        toGenerateShort = "postcondition"
        toGenerateGoal = "means"
        toGenerateShortCaps = "Postcondition".upper()
    else:
        raise NotImplementedError

    variableUsageSentence = get_variable_usage_sentence(benchmark_name)

    if exper_cfg.prompt_v == "base":
        return promptTemplate.substitute(
            codeStubAndDocstring=code,
            toGenerateFull=toGenerateFull,
            toGenerateShort=toGenerateShort,
            toGenerateGoal=toGenerateGoal,
            toGenerateShortCaps=toGenerateShortCaps,
            promptAdds=promptAdds,
            entrypoint=entrypoint,
            variableUsageSentence=variableUsageSentence,
        )

    elif exper_cfg.prompt_v == "simple":
        return promptTemplate.substitute(
            codeStubAndDocstring=code,
            toGenerateFull=toGenerateFull,
            toGenerateShort=toGenerateShort,
            toGenerateShortCaps=toGenerateShortCaps,
            entrypoint=entrypoint,
            variableUsageSentence=variableUsageSentence,
        )


def ask(prompt, exper_cfg, log_only):
    """
    This function returns the response from the API call - can be modified to support additional models
    """

    assert CLIENT is not None, "API client is not initialized"
    max_api_retries = get_positive_int(
        exper_cfg, "max_api_retries", DEFAULT_MAX_API_RETRIES
    )
    api_timeout_seconds = get_positive_int(
        exper_cfg, "api_timeout_seconds", DEFAULT_API_TIMEOUT_SECONDS
    )
    response = None

    request_kwargs = dict(
        model=exper_cfg.model,
        messages=[
            {"role": "system", "content": exper_cfg.system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=exper_cfg.temperature,
        n=exper_cfg.n_model_responses,
        timeout=api_timeout_seconds,
    )

    for attempt in Retrying(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(max_api_retries),
        reraise=True,
    ):
        attempt_number = attempt.retry_state.attempt_number
        log_only(
            "Attempting call ({}/{}, timeout={}s)...".format(
                attempt_number, max_api_retries, api_timeout_seconds
            )
        )
        with attempt:
            try:
                response = CLIENT.chat.completions.create(**request_kwargs)
            except Exception as exc:
                log_only(
                    "API call failed on attempt {}/{}: {}".format(
                        attempt_number, max_api_retries, exc
                    )
                )
                raise

    assert response is not None, "API call did not return a response"
    return response.model_dump()


def generate_one_completion(
    exper_cfg, problem, task_id, run_num, log_only, benchmark_name="", postconditions=None
):
    """
    This function gets and processes one call from the API
    """

    prompt = prepare_prompt(exper_cfg, problem, benchmark_name=benchmark_name)

    log_only(
        "🪅  Generating {} responses for the following prompt: \n {}".format(
            exper_cfg.n_model_responses, prompt
        )
    )

    try:
        # time.sleep(10)
        response = ask(prompt, exper_cfg, log_only)
        # break # if we get a response, break out of the loop
    except Exception as e:
        log_only(
            "################### ERROR for {}, {} ###################".format(
                task_id, exper_cfg.to_generate
            )
        )
        log_only("Error for {}: {}".format(task_id, str(e)))
        log_only("\n\n\n")
        log_only(
            "Even with retries, not able to generate for {}: {}".format(
                task_id, str(e)
            )
        )
        return None

    # Log the response
    log_only(
        "################### FULL RESPONSE for {}, {} ###################".format(
            task_id, exper_cfg.to_generate
        )
    )
    log_only(json.dumps(response, sort_keys=True))
    log_only(
        "################### ONE ANSWER for {}, {} ###################".format(
            task_id, exper_cfg.to_generate
        )
    )
    log_only(response["choices"][0]["message"]["content"])
    log_only("\n\n\n")

    all_out = ""

    # Make human readable files as a byproduct
    # First, a human readable file for each response
    program_dir = os.path.join(log.OUTPUT_FOLDER, log.SUB_FOLDER)
    os.makedirs(program_dir, exist_ok=True)
    print(log.OUTPUT_FOLDER, log.SUB_FOLDER)
    for i in range(len(response["choices"])):
        file_base = task_id.replace("/", "_") + "_" + exper_cfg.to_generate + "_"
        with open(
            os.path.join(
                program_dir,
                file_base + str(i + run_num * exper_cfg.n_per_model_call) + ".py",
            ),
            "w",
        ) as f:
            thisResponse = response["choices"][i]["message"]["content"]
            f.write(thisResponse + "\n\n\n")
            all_out += "\n# Response " + str(i) + "\n" + thisResponse + "\n\n\n"
            f.flush()
            os.fsync(f.fileno())

    # Second, a file with all responses combined
    with open(os.path.join(program_dir, file_base + "_all.py"), "w") as f:
        f.write(all_out)
        f.flush()
        os.fsync(f.fileno())

    print("Finished problem " + str(task_id))
    response["version"] = exper_cfg.to_generate
    return response


def generate_samples_for_problem(
    exper_cfg, problem, task_id, log_only, benchmark_name="", postconditions=None
):
    samples = []
    for run_num in range(exper_cfg.n_per_model_call):
        samples.append(
            dict(
                task_id=task_id,
                run_num=run_num,
                completion_pre=generate_one_completion(
                    exper_cfg,
                    problem,
                    task_id,
                    run_num,
                    log_only,
                    benchmark_name,
                    postconditions,
                ),
            )
        )
    return samples


@hydra.main(version_base=None, config_path="./config", config_name="config")
def main(cfg):
    # set up the output folder
    hydra_cfg = hydra.core.hydra_config.HydraConfig.get()
    # if hydra_cfg.mode != RunMode.MULTIRUN:
    #    os.chdir(hydra_cfg.runtime.output_dir)
    print_and_log, log_only = log.setup_output_dir(hydra_cfg)

    print_and_log("Working directory : {}".format(os.getcwd()))
    print_and_log(make_header("Setting up output folder..."))

    # print the config file to standard out (this will also be dumped into the outputs folder)
    print_and_log(make_header("Loaded Config"))
    print_and_log(OmegaConf.to_yaml(cfg))

    # set up the model
    print_and_log(make_header("Setting up {} API...".format(cfg.api.name)))
    setup_api(cfg.api, print_and_log)
    print_and_log(make_header("Successfully set up {} API".format(cfg.api.name)))

    # load benchmark problems
    print_and_log(
        make_header("Loading benchmark problems from {}...".format(cfg.benchmarks.name))
    )
    problems = load_benchmarks(cfg.benchmarks)
    print_and_log(make_header("Successfully loaded {} problems".format(len(problems))))

    # If we are generating rankings, load the postconditions
    all_postconditions = None
    if cfg.experiment.to_generate == "rank":
        print_and_log(make_header("Loading postconditions..."))
        all_postconditions = load_postconditions(
            cfg.experiment.evaluated_post_conditions_file
        )
        print_and_log(
            make_header(
                "Successfully loaded {} postconditions".format(len(all_postconditions))
            )
        )

    # generate model completions for each problem
    print_and_log(
        make_header("Generating Code for {} prompts... ".format(len(problems)))
    )

    samples = []
    task_ids_to_run = []
    doRun = True

    if cfg.benchmarks.run_range and str(cfg.benchmarks.run_start) != "HumanEval/0":
        doRun = False

    for task_id in problems:
        if cfg.benchmarks.run_range and str(task_id) == str(cfg.benchmarks.run_start):
            doRun = True

        if not doRun:
            continue

        task_ids_to_run.append(task_id)

        if cfg.benchmarks.run_range and str(task_id) == str(cfg.benchmarks.run_end):
            doRun = False

    worker_count = get_worker_count()
    print_and_log(
        make_header(
            "Running generation with {} workers across {} problems".format(
                worker_count, len(task_ids_to_run)
            )
        )
    )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_task_id = {
            executor.submit(
                generate_samples_for_problem,
                cfg.experiment,
                problems[task_id],
                task_id,
                log_only,
                cfg.benchmarks.name,
                None if all_postconditions is None else all_postconditions.get(task_id),
            ): task_id
            for task_id in task_ids_to_run
        }

        for future in as_completed(future_to_task_id):
            problem_samples = future.result()
            write_jsonl(
                os.path.join(log.OUTPUT_FOLDER, "samples_partial.jsonl"),
                problem_samples,
                append=True,
            )
            samples.extend(problem_samples)

    print_and_log(make_header("COMPLETED CODE GENERATION, SAVING JSONL FILE..."))

    # save the completions to the output folder in json format
    print(cfg.experiment.to_generate)
    print(samples)
    write_jsonl(
        os.path.join(
            log.OUTPUT_FOLDER, "samples_{}.jsonl".format(cfg.experiment.to_generate)
        ),
        samples,
    )

    print_and_log(make_header("JSON SAVED, DONE"))
    print_and_log(log.OUTPUT_FOLDER)


if __name__ == "__main__":
    main()
