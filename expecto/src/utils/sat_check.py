from __future__ import annotations

import asyncio
from textwrap import dedent
from typing import Any, Optional

from src.evaluation.sandbox import Sandbox
from src.utils.dsl import (
    generate_evaluation_code,
    generate_evaluation_code_with_schema,
    get_parsed_arguments,
    pyval_to_dsl_with_schema,
)
from src.utils.monad import Err, Ok, Result


def _is_timeout_failure(
    status: str,
    stderr: Optional[str],
    stdout: Optional[str],
) -> bool:
    if status == "timeout":
        return True

    timeout_markers = (
        "dsl solver is unknown: timeout",
        "timed out",
        "timeout",
    )
    outputs = (stderr or "", stdout or "")
    for output in outputs:
        lowered = output.lower()
        if any(marker in lowered for marker in timeout_markers):
            return True
    return False


async def sat_check(
    dsl_code: str,
    ignore_timeout: bool = False,
    negate: bool = False,
) -> Result[None, str]:
    """Check satisfiability of a DSL specification.

    Returns Ok(None) if satisfiable, Err(error_message) otherwise.
    """
    solver_assertion = "solver.add(z3.Not(spec))" if negate else "solver.add(spec)"

    eval_code = dedent(f"""
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))
from expecto.src.DSL.compiler import DSLCompiler, make_solver
import z3
dsl_code = {repr(dsl_code)}
compiler = DSLCompiler()
try:
    spec = compiler.compile(dsl_code, entry_func="spec")
except Exception as err:
    print(f"Error compiling DSL code: {{err}}", file=sys.stderr)
    exit(1)
ctx = compiler.get_ctx()
solver = make_solver(ctx)
{solver_assertion}
solver.set("timeout", 29 * 1000)
solver.set("max_memory", 512 * 1024 * 1024)
checked = solver.check()
if checked == z3.unknown:
    raise TimeoutError(f"DSL solver is unknown: {{solver.reason_unknown()}}")
assert checked == z3.sat, f"Checked value: {{checked}}"
    """).strip()
    try:
        async with Sandbox() as sandbox:
            result = await sandbox.run_test(eval_code)
    except Exception as e:
        return Err(str(e))

    if result.status == "success":
        return Ok(None)

    if ignore_timeout and _is_timeout_failure(
        result.status, result.stderr, result.stdout
    ):
        return Ok(None)

    if result.stderr:
        return Err(result.stderr)
    if result.stdout:
        return Err(result.stdout)
    return Err("Unknown error during evaluation")


async def sat_check_examples(
    dsl_code: str,
    parser_code: Optional[str],
    function_signature: str,
    test_cases: list[tuple[Any, Any]] | list[dict],
    ignore_timeout: bool = False,
    no_feedback_prompt: bool = False,
    **kwargs,
) -> Result[None, str]:
    entry_schema = kwargs.get("entry_schema")
    exit_schema = kwargs.get("exit_schema")

    test_codes: list[str] = []
    for tc in test_cases:
        if isinstance(tc, tuple):
            test_input, test_output = tc
            try:
                parsed_arguments = get_parsed_arguments(
                    parser_code, function_signature, test_input, test_output
                )
                eval_code = generate_evaluation_code(
                    dsl=dsl_code,
                    parsed_arguments=parsed_arguments,
                    function_signature=function_signature,
                    is_correct=True,
                    is_local=True,
                )
                test_codes.append(eval_code)
            except Exception as e:
                return Err(f"Failed to generate evaluation code: {e}")
        else:
            if entry_schema is None or exit_schema is None:
                return Err(
                    "entry_schema and exit_schema are required for schema-based test cases"
                )
            eval_code = generate_evaluation_code_with_schema(
                dsl=dsl_code,
                val=tc,
                entry_schema=entry_schema,
                exit_schema=exit_schema,
                is_correct=True,
                is_local=True,
            )
            test_codes.append(eval_code)

    if len(test_codes) == 0:
        return Ok(None)

    async with Sandbox() as sandbox:
        tasks = [sandbox.run_test(code) for code in test_codes]
        results = await asyncio.gather(*tasks)

    errors: list[str] = []
    for res, d in zip(results, test_cases):
        if res.status == "success":
            continue
        elif ignore_timeout and res.status == "timeout":
            continue

        if isinstance(d, tuple):
            i, o = d
            parsed_arguments = get_parsed_arguments(
                parser_code, function_signature, i, o
            )
        else:
            if entry_schema is None or exit_schema is None:
                return Err(
                    "entry_schema and exit_schema are required for schema-based test cases"
                )
            parsed_arguments = pyval_to_dsl_with_schema(entry_schema, exit_schema, d)

        base = f"Failed to check test case: {repr(parsed_arguments)}"
        if res.stderr:
            errors.append(base + "\n" + res.stderr)
        elif res.stdout:
            errors.append(base + "\n" + res.stdout)
        else:
            errors.append(base + "\n" + "Unknown error during evaluation")

    if errors:
        join_errors = "\n".join(errors)
        if no_feedback_prompt:
            return Err(join_errors)
        feedback = f"""
Failed to check test cases. If smt returns UNSAT then it means your DSL code is not correct.
In this case, you should fix your DSL code.
If smt returns unknown then it means we cannot check your DSL code is correct.
When this, happens, you should try to reduce the number of quantifiers in your DSL code.
If you must reduce the quantifier, use an over-approximated condition instead of a highly precise one.
Otherwise (type error, parsing error, etc.), you should try to fix the errors.
**Errors:**
\n{join_errors}"""
        return Err(feedback)
    return Ok(None)
