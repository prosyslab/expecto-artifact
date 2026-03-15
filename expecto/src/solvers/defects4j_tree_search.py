from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from inspect_ai.model import Model, get_model
from inspect_ai.solver import Generate, Solver, TaskState, solver

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))


from src.DSL.ast_unparse import unparse
from src.DSL.dsl_ast import Specification
from src.solvers.tree_search import Node, State, TreeSearch, parse
from src.tasks.defects4j import (
    Defects4jMethodSample,
    build_defects4j_method_prompt,
)

logger = logging.getLogger(__name__)


async def generate_spec_per_method(
    method_data: Defects4jMethodSample,
    model: Model,
    max_attempts: int,
    n_completions: int,
    use_test_cases: bool,
    use_memo: bool,
    check_unsat: bool,
    root_spec: str,
) -> dict:
    entry_schema = method_data.method_info.entry_schema
    exit_schema = method_data.method_info.exit_schema
    signature = f'predicate spec(param: {entry_schema.params}, entry_self: {entry_schema.self}, exit_self: {exit_schema.self}, ret: {exit_schema.ret}): "This is entry point of the specification"'
    parsed_signature = parse(signature)
    if parsed_signature.is_err():
        logger.info(f"Failed to parse signature: {parsed_signature.err()}")
        return {
            "generated_codes": [],
            "method_signature": method_data.method_info.signature,
            "signature": signature,
            "error": parsed_signature.err(),
        }
    entry_def = parsed_signature.ok()[0]

    if use_test_cases:
        test_cases = list(method_data.corrects.values())[:3]
    else:
        test_cases = []
    kwargs = {
        "entry_schema": entry_schema.model_dump(),
        "exit_schema": exit_schema.model_dump(),
    }

    ts = TreeSearch(
        model=model,
        patient=max_attempts,
        n_completions=n_completions,
        max_iteration=10,
        test_cases=test_cases,
        root_spec=root_spec,
        use_memo=use_memo,
        root_node=Node(
            None,
            State([], [entry_def]),
            function_signature=signature,
            parser_code=None,
            check_unsat=check_unsat,
            **kwargs,
        ),
    )
    try:
        metadata, final_node = await asyncio.wait_for(
            asyncio.create_task(ts.run()), timeout=60 * 60 * 3
        )
    except asyncio.TimeoutError:
        metadata, final_node = ts.pick_best_leaf()
    root = ts.root_node

    if metadata is None:
        return {
            "generated_codes": [],
            "method_signature": method_data.method_info.signature,
        }
    spec = Specification(
        declarations=final_node.state.defined + final_node.state.undefined
    )
    code = unparse(spec)
    metadata["generated_codes"] = [code]
    metadata["method_signature"] = method_data.method_info.signature
    metadata["is_success"] = len(final_node.state.undefined) == 0
    metadata["num_of_defined"] = len(final_node.state.defined)
    metadata["num_of_undefined"] = len(final_node.state.undefined)
    metadata["tree"] = root.__dict__()
    return metadata


@solver(name="defects4j_tree_search")
def defects4j_tree_search(
    model: str | None = None,
    max_attempts: int = 5,
    n_completions: int = 1,
    use_test_cases: bool = True,
    use_memo: bool = True,
    check_unsat: bool = True,
    *args,
    **kwargs,
) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        method_data = Defects4jMethodSample.model_validate(state.metadata)
        root_spec = state.input or build_defects4j_method_prompt(
            method_data.method_info,
            include_method_code=True,
        )
        model_obj = get_model(model)
        result = await generate_spec_per_method(
            method_data,
            model_obj,
            max_attempts,
            n_completions,
            use_test_cases,
            use_memo,
            check_unsat,
            root_spec=root_spec,
        )
        state.output.completion = json.dumps(result, indent=4, sort_keys=True)
        return state

    return solve
