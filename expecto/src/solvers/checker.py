import asyncio
import logging
import sys
from pathlib import Path
from textwrap import indent
from typing import Any, Callable, Coroutine

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    Model,
)
from inspect_ai.util import sandbox

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))


from src.prompts.prompt import (
    execution_error_fix_prompt,
    syntax_error_fix_prompt,
    type_error_fix_prompt,
)
from src.utils.code import (
    add_necessary_imports,
    auto_function_argument_filler,
    check_and_generate_feedback,
    check_assertions_in_code,
    find_code,
    has_type_annotation,
    run_test,
    syntax_check,
    type_check,
)
from src.utils.dsl import compile_checker
from src.utils.z3utils import z3_relevant_postprocess

logger = logging.getLogger(__name__)


async def type_checker(code: str, *args, **kwargs) -> tuple[bool, str]:
    is_valid, error_message = await type_check(code)
    if is_valid:
        return True, ""
    return False, type_error_fix_prompt.format(error_message=error_message)


async def syntax_checker(code: str, *args, **kwargs) -> tuple[bool, str]:
    is_valid, error_message = await syntax_check(code)
    if is_valid:
        return True, ""
    return False, syntax_error_fix_prompt.format(error_message=error_message)


async def dsl_syntax_checker(code: str, *args, **kwargs) -> tuple[bool, str]:
    async def wrapper():
        return compile_checker(code)

    try:
        is_valid, error_message = await asyncio.wait_for(wrapper(), timeout=10)
    except asyncio.TimeoutError:
        logger.warning(f"TIMEOUT!!!!\n{code}")
        return (
            False,
            "During compilation, the DSL code timed out. Please simplify your DSL code.",
        )
    if is_valid:
        return True, ""
    return False, error_message


async def assertion_checker(code: str, *args, **kwargs) -> tuple[bool, str]:
    is_valid, error_message = await check_assertions_in_code(code)
    if is_valid:
        return True, ""
    return False, error_message


async def no_assertion_checker(code: str, *args, **kwargs) -> tuple[bool, str]:
    is_valid, error_message = await check_assertions_in_code(code)
    if is_valid:
        return False, "Please remove all the assert statements in the code."
    return True, ""


async def execution_checker(code: str, *args, **kwargs) -> tuple[bool, str]:
    try:
        call = auto_function_argument_filler(
            kwargs.get("function_signature", ""), "postcondition"
        )
    except ValueError:
        logger.warning(
            f"Failed to fill the function arguments: {kwargs.get('function_signature', '')}"
        )
        return True, "Warning: Failed to fill the function arguments."
    code += "\n\n" + call
    is_valid, _, error_message = await run_test(code, sandbox(), timeout=10)
    if "IndexError" in error_message:  # IndexError is false alarm
        return True, ""
    if is_valid:
        return True, ""
    return False, execution_error_fix_prompt.format(error_message=error_message)


async def has_type_annotation_checker(code: str, *args, **kwargs) -> tuple[bool, str]:
    is_valid, error_message = await has_type_annotation(code, "postcondition")
    if is_valid:
        return True, ""
    return False, error_message


async def generate_with_checkers(
    messages: list[ChatMessage],
    model: Model,
    max_attempts: int,
    n_completions: int,
    checkers: list[Callable[..., Coroutine[Any, Any, tuple[bool, str]]]],
    language: str = "python",
    *args: Any,
    **kwargs: Any,
) -> list[str]:
    checker_with_feedback = check_and_generate_feedback(
        checkers
    )  # Feedback function generator
    valid_codes: list[str] = []

    copied_messages = messages[:]

    for _ in range(max_attempts):
        if len(valid_codes) >= n_completions:
            break
        results = await model.generate(
            input=copied_messages,
            config=GenerateConfig(num_choices=n_completions - len(valid_codes)),
        )
        last_completion_content = ""
        last_feedback = ""
        for completion in results.choices:
            completion_content = completion.message.content
            if not isinstance(completion_content, str):
                raise ValueError(
                    f"Completion content is not a string: {completion_content}"
                )
            code = find_code(completion_content, language)
            if language == "python":
                code = add_necessary_imports(code)
                code = z3_relevant_postprocess(code)
            is_valid, _, feedback = await checker_with_feedback(code, *args, **kwargs)
            if is_valid:
                valid_codes.append(code)
            else:
                logger.info(f"FEEDBACK:\n{indent(feedback, ' ' * 4)}")
                last_completion_content = completion_content
                last_feedback = feedback
        copied_messages.append(ChatMessageAssistant(content=last_completion_content))
        copied_messages.append(ChatMessageUser(content=last_feedback))
    return valid_codes
