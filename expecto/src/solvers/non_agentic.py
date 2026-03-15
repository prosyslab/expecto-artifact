import json
import logging
import re
import sys
from pathlib import Path
from time import sleep

from inspect_ai.model import ChatMessageSystem, ChatMessageUser, get_model
from inspect_ai.solver import Generate, Solver, TaskState, solver

logger = logging.getLogger(__name__)

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from prompts.prompt import (
    dsl_generation_prompt,
    dsl_sys_prompt,
)
from src.solvers.multigen import MultiGen
from src.utils.dsl import Tree
from src.utils.dsl import template_generation as dsl_template_generation
from src.utils.monad import Err, Ok, Result
from src.utils.sat_check import sat_check_examples

@solver(name="monolithic")
def monolithic(
    model: str | None = None, max_attempts: int = 5, *args, **kwargs
) -> Solver:
    def find_code(response: str) -> Result[str, str]:
        dsl_block_pattern = r"```dsl(.*)```"
        dsls = re.findall(dsl_block_pattern, response, re.DOTALL)
        if len(dsls) == 0:
            return Err("No DSL block found")
        longest_dsl = max(dsls, key=len)
        return Ok(longest_dsl)

    async def async_find_code(response: str) -> Result[str, str]:
        return find_code(response)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        signature = state.metadata["signature"]
        parser = state.metadata.get("parser", None)
        test_cases = state.metadata.get("prompt_test_list", [])
        signature = state.metadata["signature"]

        template_code = dsl_template_generation(
            state.metadata["signature"],
            Tree(
                "This is the formal specification on input and output pair generated from the given natural language specification"
            ),
        )

        async def checker(
            response: str,
            *args,
            **kwargs,
        ) -> Result[None, str]:
            code = find_code(response)
            if code.is_err():
                return Err(code.err())
            longest_dsl = code.ok()
            return await sat_check_examples(
                dsl_code=longest_dsl,
                parser_code=parser,
                function_signature=signature,
                test_cases=test_cases,
                **kwargs,
            )

        state.messages.clear()

        messages = [
            ChatMessageSystem(content=dsl_sys_prompt),
            ChatMessageUser(
                content=dsl_generation_prompt.format(
                    function_spec=state.input, baseline_dsl_specification=template_code
                )
            ),
        ]
        model_obj = get_model(model)
        mg = MultiGen(
            model=model_obj,
            n_completions=1,
            n_attempts=max_attempts,
            checkers=[checker],
            baseline_messages=messages,
            postprocess=async_find_code,
        )
        generated = await mg.generate()
        corrects = []
        for meta, code in generated:
            logger.info(meta.model_dump_json(indent=4))
            if code.is_ok():
                logger.info(code.ok())
                corrects.append(code.ok())
            else:
                logger.error(code.err())

        result_json = {
            "generated_codes": corrects,
        }

        state.output.completion = json.dumps(result_json, indent=4, sort_keys=True)
        return state

    return solve
