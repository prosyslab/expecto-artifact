import ast
import asyncio
import json
import logging
import os
import re
import shlex
import symtable
import sys
import tempfile
import traceback
from collections import defaultdict
from textwrap import dedent, indent
from typing import (
    Any,
    Callable,
    Coroutine,
    Optional,
    ParamSpec,
    Union,
    cast,
)

from dotenv import load_dotenv
from inspect_ai.util import ExecResult, SandboxEnvironment

sys.path.append(os.path.join(os.path.dirname(__file__)))

from z3utils import (
    convert_python_type_ast,
    convert_python_val_to_z3_val_str_version,
)

load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))


PYTHON_PATH = os.getenv("PYTHON_PATH")
logger = logging.getLogger(__name__)


def find_code(completion: str, kind: str = "python") -> str:
    """
    Remove Markdown formatting around generated code blocks.

    It is assumed that generated output is of the form:
    ```python
    [code output]
    ```

    If there are multiple code blocks, return the longest one.
    """
    pattern = re.compile(rf"```{kind}(.*?)```", re.DOTALL)
    weak_pattern = re.compile(r"```(.*?)```", re.DOTALL)
    matches = pattern.findall(completion)
    if len(matches) >= 1:
        longest_match = max(matches, key=len)
        return str(longest_match).strip()
    matches = weak_pattern.findall(completion)
    if len(matches) >= 1:
        longest_match = max(matches, key=len)
        return str(longest_match).strip()
    return completion.replace("```python", "").replace("```", "").strip()


def extract_input_output(assertion: str) -> tuple[str, str]:
    """
    Extract the input and output variables from the assertion.
    'assert ???(args) == output' -> ('args', 'output')
    """
    pattern = re.compile(r"assert .*\((.*?)\).*==(.*)", re.DOTALL)
    matches = pattern.findall(assertion)
    if len(matches) >= 1:
        input_var, output_var = matches[-1]
        return input_var.strip(), output_var.strip()
    return "", ""


def remove_asserts(explanation: str) -> str:
    """Remove all assert lines from the explanation."""
    return "\n".join([line for line in explanation.split("\n") if "assert" not in line])


async def run_test(
    code: str, sandbox: SandboxEnvironment, timeout: int
) -> tuple[bool, str, str]:
    """Run a test on the given code."""
    explanation = ""
    explanation += "The following code was executed:\n\n```python\n"
    explanation += code
    explanation += "\n```\n"

    try:
        await sandbox.write_file("test.py", code)
        result = await sandbox.exec(
            cmd=["python3", "test.py"], timeout=timeout, timeout_retry=False
        )
        if result.success:
            explanation += "All test cases passed.\n"
        else:
            explanation += "Code did not pass all test cases.\n"
            if result.stderr:
                explanation += "See details below.\n"
                explanation += result.stderr
    except TimeoutError:
        result = ExecResult(False, 1, "", "Verification timed out.")
        explanation += "Verification timed out."
    except Exception as e:
        result = ExecResult(False, 1, "", str(e))
        explanation += f"Verification failed with error:\n{str(e)}"

    return result.success, explanation, result.stderr


def postprocess_type_check_result(data: dict) -> str:
    diagnostics = data["generalDiagnostics"]
    for diagnostic in diagnostics:
        if "file" in diagnostic:
            del diagnostic["file"]
    messages: list[str] = []
    for diagnostic in diagnostics:
        if "message" in diagnostic:
            messages.append(diagnostic["message"])
    return "\n".join(messages)


async def type_check(code: str) -> tuple[bool, str]:
    """Typecheck the given code."""
    with (
        tempfile.NamedTemporaryFile(delete=True) as code_file,
        tempfile.NamedTemporaryFile(delete=True, suffix=".json") as pyright_file,
    ):
        code_file.write(code.encode("utf-8"))
        code_file.flush()
        command = f"pyright --threads 1 --outputjson {shlex.quote(code_file.name)} --project utils/pyrightconfig.json --pythonpath {PYTHON_PATH}"
        try:
            proc = await asyncio.create_subprocess_shell(command, stdout=pyright_file)
            await proc.wait()
        except Exception as ex:
            print(f"failed with {ex}: {pyright_file.name}")
        pyright_file.seek(0)
        data = json.load(pyright_file)
        if data["summary"]["errorCount"] == 0:
            return True, ""
        else:
            return False, postprocess_type_check_result(data)


async def syntax_check(code: str, *args: Any, **kwargs: Any) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except Exception:
        return False, traceback.format_exc()


async def is_false_alarm(llm_output: str) -> bool:
    if "FALSE ALARM" in llm_output:
        return True
    return False


async def check_assertions_in_code(code: str) -> tuple[bool, str]:
    """
    Check if the code contains any assert statement using AST.
    Returns True if at least one assert is present, otherwise False.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False, traceback.format_exc()
    # Return True if any Assert node is found
    has_assert = any(isinstance(node, ast.Assert) for node in ast.walk(tree))
    return (
        has_assert,
        "There is no testcase assertion in the code. Please add testcase refering to the requirements."
        if not has_assert
        else "",
    )


P = ParamSpec("P")


def check_and_generate_feedback(
    checkers: list[Callable[P, Coroutine[Any, Any, tuple[bool, str]]]],
) -> Callable[P, Coroutine[Any, Any, tuple[bool, str, str]]]:
    async def generator(*args: P.args, **kwargs: P.kwargs) -> tuple[bool, str, str]:
        for checker in checkers:
            success, feedback = await checker(*args, **kwargs)
            if not success:
                checker_name = checker.__name__
                return False, checker_name, feedback.strip()
        return True, "", ""

    return generator


def extract_function_node_by_name(code: str, name: str) -> Optional[ast.FunctionDef]:
    """
    Extract the function node by the given name from the code.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def extract_parser_function(code: str) -> Optional[str]:
    """
    Extract the parser function from the code.
    """
    parser_function_node = extract_function_node_by_name(code, "parser")
    if parser_function_node is None:
        return None
    return ast.unparse(parser_function_node)


def extract_postcondition_function_signature(code: str) -> Optional[str]:
    """
    Extract the function signature of the postcondition function from the code.
    """
    postcondition_function_node = extract_function_node_by_name(code, "postcondition")
    if postcondition_function_node is None:
        return None
    docstring = ast.get_docstring(postcondition_function_node)
    postcondition_function_node.body = [ast.Pass()]  # Remove the body of the function
    if docstring is not None:
        postcondition_function_node.body.insert(
            0, ast.Expr(ast.Constant(value=docstring))
        )
    unparsed = ast.unparse(postcondition_function_node)
    return unparsed


class Tree:
    def __init__(self, content: str, children: list["Tree"] = []):
        self.content = content
        self.children = children

    def __str__(self):
        children_str = "".join([indent(str(child), "    ") for child in self.children])
        if self.content == "":
            return dedent(children_str)
        else:
            # Remove all escaping characters (e.g., backslashes) and double quotes from content
            cleaned_content = self.content.replace("\\", "").replace('"', "")
            return f"- {cleaned_content}\n" + children_str


def parse_enumeration_string(enumeration_string: str) -> Tree:
    """
    Parse the enumeration string into a list of strings.
    """
    # Use regex to capture indent and content
    pattern = re.compile(r"^(?P<indent>\s*)-\s*(?P<content>.*)$")
    lines = [line for line in enumeration_string.splitlines() if line.strip()]
    entries: list[tuple[int, str]] = []
    indent_levels: list[int] = []
    for line in lines:
        m = pattern.match(line)
        if m:
            indent_len = len(m.group("indent"))
            text = m.group("content")
        else:
            indent_len = 0
            text = line.strip()
        entries.append((indent_len, text))
        if indent_len > 0:
            indent_levels.append(indent_len)
    indent_unit = min(indent_levels) if indent_levels else 0
    # Build tree
    root = Tree("", [])
    stack = [root]
    for indent_len, text in entries:
        depth = indent_len // indent_unit if indent_unit else 0
        while len(stack) > depth + 1:
            stack.pop()
        parent = stack[-1]
        node = Tree(text, [])
        parent.children.append(node)
        stack.append(node)
    return root


def insert_docstring(code: str, docstring: str, target_function_name: str) -> str:
    """
    Insert the docstring into the code.
    If the function already has a docstring, replace the existing one.
    """
    try:
        ast_root = ast.parse(code)
    except SyntaxError or IndentationError:
        return code
    for node in ast.walk(ast_root):
        if isinstance(node, ast.FunctionDef) and node.name == target_function_name:
            original_docstring = ast.get_docstring(node)
            if original_docstring is None:
                node.body.insert(0, ast.Expr(ast.Constant(value=docstring)))
            else:
                node.body.pop(0)
                node.body.insert(0, ast.Expr(ast.Constant(value=docstring)))
    return ast.unparse(ast_root)


def auto_fix_non_boolean_expression_in_assert_and_track(code: str) -> str:
    """
    Auto fix non-boolean expression in assert_and_track based on static analysis.
    """

    def checker(root: ast.AST, params: tuple[str, ...]) -> bool:
        """
        Check some expressions are directly using params in the assert_and_track
        """
        # Check the very first expression is a comparison (Module --> Expr --> Compare)
        if not isinstance(root, ast.Module):
            return False
        if not isinstance(root.body[0], ast.Expr):
            return False
        if not isinstance(root.body[0].value, ast.Compare):
            return False

        # Check all identifiers are in params
        for node in ast.walk(root):
            if isinstance(node, ast.Name):
                if node.id not in params:
                    return False

        return True

    pattern = re.compile(r"assert_and_track\((.*?),\s+\".*?\"\)", re.DOTALL)
    matches = pattern.findall(code)
    unique_matched_strings = {match.strip() for match in matches}
    s_table = symtable.symtable(code, "<string>", "exec")
    postcond_symtable = cast(symtable.Function, s_table.get_children()[0])
    params = postcond_symtable.get_parameters()

    for match in unique_matched_strings:
        trimed = match.strip()
        try:
            parsed = ast.parse(trimed)
        except SyntaxError:
            continue
        if checker(parsed, params):
            fixed = f"Bool({trimed})"
            code = code.replace(match, fixed)
    return code


def type_expression_to_literal(type_expression: ast.expr) -> Any:
    literal_map = {
        "int": 5,
        "str": "'thisisstring'",
        "bool": True,
        "float": 3.10,
        "list": [],
        "tuple": (),
        "dict": {},
        "set": set(),
        "union": Union,
        "None": None,
    }
    if isinstance(type_expression, ast.Name):
        return literal_map[type_expression.id.lower()]
    elif isinstance(type_expression, ast.Subscript):
        # value[slice]
        value = type_expression_to_literal(type_expression.value)
        slice = type_expression_to_literal(type_expression.slice)
        if not isinstance(slice, tuple):
            slice = (slice,)
        if isinstance(value, dict) and len(slice) == 2:
            key = slice[0]
            value = slice[1]
            return {key: value}
        if value is Union:
            return slice[0]
        for elem in slice:
            if isinstance(value, list):
                value = value + [elem]
            elif isinstance(value, tuple):
                value = value + (elem,)
            elif isinstance(value, set):
                value = value | {elem}
            else:
                raise ValueError(f"Unsupported type expression: {type_expression}")
        return value
    elif isinstance(type_expression, ast.Tuple):
        return tuple(type_expression_to_literal(arg) for arg in type_expression.elts)
    elif isinstance(type_expression, ast.BoolOp) and isinstance(
        type_expression.op, ast.Or
    ):
        first_type = type_expression_to_literal(type_expression.values[0])
        return first_type
    elif isinstance(type_expression, ast.BinOp) and isinstance(
        type_expression.op, ast.BitOr
    ):
        lhs = type_expression_to_literal(type_expression.left)
        return lhs
    else:
        raise ValueError(f"Unsupported type expression: {ast.unparse(type_expression)}")


def auto_function_argument_filler(function_code: str, target_function_name: str) -> str:
    """
    Auto fill the function arguments based on the function signature.
    """
    parsed = ast.parse(function_code)
    arguments = []
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == target_function_name:
            arguments = [
                (arg.arg, type_expression_to_literal(arg.annotation))
                for arg in node.args.args
                if arg.annotation is not None
            ]
    result: str = "import z3\n"
    result += convert_python_val_to_z3_val_str_version
    result += "\n"
    result += f"solver={target_function_name}("
    result += ", ".join(
        [f"{arg[0]}=convert_python_val_to_z3_val({arg[1]})" for arg in arguments]
    )
    result += ")"
    return result


def compare_ast_tree(tree1: ast.AST, tree2: ast.AST) -> bool:
    """
    Compare two AST trees.
    """
    return ast.dump(tree1) == ast.dump(tree2)


def merge_functions(codes: list[str], target_function_name: str) -> str:
    """
    Merge the functions into a single function.

    Args:
        code: List of code strings containing functions to merge
        target_function_name: Name of the function to merge

    Returns:
        str: Merged function as a string
    """
    merged_params: list[ast.arg] = []
    merged_body: list[ast.stmt] = []

    for code in codes:
        try:
            tree = ast.parse(code.strip())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == target_function_name:
                # Merge parameters
                for param in node.args.args:
                    if not any(p.arg == param.arg for p in merged_params):
                        merged_params.append(param)

                # Merge body
                for stmt in node.body:
                    if not any(
                        compare_ast_tree(stmt, m_stmt) for m_stmt in merged_body
                    ):
                        merged_body.append(stmt)

    # Create merged function
    merged_function = ast.FunctionDef(
        name=target_function_name,
        args=ast.arguments(
            posonlyargs=[],
            args=merged_params,
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=merged_body,
        decorator_list=[],
        returns=None,
        type_comment=None,
        type_params=[],
    )

    ast.fix_missing_locations(merged_function)

    # Convert to string
    return ast.unparse(merged_function)


def add_necessary_imports(code: str) -> str:
    """
    Add necessary imports to the code.
    """
    import_1 = "from typing import *"
    import_2 = "from z3 import *"
    if import_1 not in code:
        code = import_1 + "\n" + code
    if import_2 not in code:
        code = import_2 + "\n" + code
    return code


async def has_type_annotation(code: str, target_function_name: str) -> tuple[bool, str]:
    """
    Check if the code has type annotation.
    """
    function_node = extract_function_node_by_name(code, target_function_name)
    if function_node is None:
        return False, f"Target function not found: {target_function_name}"
    for arg in function_node.args.args:
        if arg.annotation is None:
            return (
                False,
                f"Function {target_function_name} has no type annotation. Please add type annotation to the function.",
            )
    return True, ""


def extract_constraints(code: str) -> dict[int, str]:
    """
    Extract the implemented constraints from the code.
    """
    lines = code.split("\n")
    implemented_constraints: defaultdict[int, list[str]] = defaultdict(list)
    constraint_comment_pattern = re.compile(r"# (\d+)\.(.*)")
    constraint_end_pattern = re.compile(r"END OF CONSTRAINT")
    current_key_idx: int | None = None
    for current_line in lines:
        begin_match = constraint_comment_pattern.search(current_line)
        end_match = constraint_end_pattern.search(current_line)

        if begin_match is not None:
            current_key_idx = int(begin_match.group(1))
        elif end_match is not None:
            current_key_idx = None
        elif current_line.strip().startswith(
            "#"
        ):  # Comment lines except for the first line
            continue
        elif current_key_idx is None:
            continue
        else:
            implemented_constraints[current_key_idx].append(current_line)
    if len(implemented_constraints) == 0:
        return {}
    min_key = 1
    max_key = max(implemented_constraints.keys())
    for key in range(min_key, max_key + 1):
        if key not in implemented_constraints:  # Add missing constraints
            implemented_constraints[key] = []
        if key in implemented_constraints:  # Leave only non-empty constraints
            implemented_constraints[key] = [
                c for c in implemented_constraints[key] if c.strip()
            ]
    return {
        key: dedent("\n".join(implemented_constraints[key]))
        for key in implemented_constraints
    }


async def check_code_implement_all_constraints(
    code: str,
    nl_constraints: dict[int, str],
) -> tuple[bool, str]:
    implemented_constraints = extract_constraints(code)
    nl_constraints_keys = nl_constraints.keys()
    missing_keys = [
        key for key in nl_constraints_keys if key not in implemented_constraints
    ]
    if len(missing_keys) > 0:
        feedback_message = "The following constraints are not implemented:\n"
        for key in missing_keys:
            feedback_message += f"{key}. {nl_constraints[key]}\n"
        return False, feedback_message
    return True, ""


def normalize_code(code: str) -> str:
    """
    Normalize the format of the code.
    """
    try:
        parsed = ast.parse(code)
        unparsed = ast.unparse(parsed)
    except SyntaxError or IndentationError:
        return code
    return unparsed


def template_generation(function_signature: str, nl_constraints: Tree) -> str:
    """
    Generate a constraint function template from the given function signature and natural language constraints.
    """
    function_node = extract_function_node_by_name(function_signature, "postcondition")
    if function_node is None:
        raise ValueError(
            f"Function signature does not contain constraint function.\n\n{function_signature}"
        )
    docstring = ast.get_docstring(function_node)
    if docstring is None:
        docstring = "This is a template for the postcondition function."
    function_node.body.clear()
    function_node.body.append(ast.Expr(value=ast.Constant(value=docstring)))
    function_node = convert_python_type_ast(function_node)

    z3_modeling_str: str = ""
    z3_modeling_str += "# Create a Solver instance\n"
    z3_modeling_str += "solver = Solver()\n"
    nl_constraints_str = str(nl_constraints)
    nl_constraints_str = indent(nl_constraints_str, "# ")
    z3_modeling_str += nl_constraints_str
    z3_modeling_str += "\n\nreturn solver"
    return (
        "import z3\n\n"
        + ast.unparse(function_node)
        + "\n"
        + indent(z3_modeling_str, " " * 4)
    )


def scoring_code_generation(
    model_code: str,
    parser_code: str,
    test_input: str,
    test_output: str,
    is_completeness: bool,
) -> str:
    neg_code = """assertions = solver.assertions()
negated_assertions = z3.Not(z3.And(*assertions))
solver.reset()
solver.add(negated_assertions)
"""
    return f"""
import z3
{model_code}

{convert_python_val_to_z3_val_str_version}

{parser_code}

parsed_input = parser({repr(test_input)}, {repr(test_output)})
converted_input = (convert_python_val_to_z3_val(arg) for arg in parsed_input)

solver = postcondition(*converted_input)
solver.set("timeout", 1000 * 10) # 10 seconds
{neg_code if is_completeness else ""}
assert solver.check() == z3.sat
"""
