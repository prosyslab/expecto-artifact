import ast
import logging
import math
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from textwrap import dedent
from typing import Any, Optional, Union, get_args, get_origin
from typing import TypedDict as _TypedDict

from lark import Lark

from src.DSL.ast_builder import ASTBuilder
from src.DSL.compiler import DSLCompiler
from src.DSL.dsl_ast import (
    DSLType,
)
from src.DSL.grammar import grammar
from src.utils.code import Tree, extract_function_node_by_name

logger = logging.getLogger(__name__)


def _convert_python_function_def_to_dsl_bootstrap(func_def: ast.FunctionDef) -> str:
    args = []
    for arg in func_def.args.args:
        assert arg.annotation is not None, "Argument must have an type annotation"
        dsl_ty = _annotation_to_dsl_type(arg.annotation, {})
        args.append(f"{arg.arg}: {dsl_ty}")
    return f"predicate spec ({', '.join(args)})"


def add_argument_mapping_to_solver(code: str, arg_mapping: str) -> str:
    return f"""{code}

predicate check_spec() {{
    spec({arg_mapping})
}}
"""


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
        docstring = "This is a template for the postcondition function"
    function_node.body.clear()
    function_node.body.append(ast.Expr(value=ast.Constant(value=docstring)))
    escaped_docstring = docstring.replace('"', "'")
    spec_predicate_def = (
        _convert_python_function_def_to_dsl_bootstrap(function_node)
        + ":"
        + f'"{str(nl_constraints)}\n{escaped_docstring}"'
    )
    return spec_predicate_def


def compile_checker(dsl_code: str) -> tuple[bool, str]:
    compiler = DSLCompiler()
    try:
        compiler.compile(dsl_code)
    except Exception as e:
        return False, str(e)
    return True, ""


def _convert_primitive_value(value: Any, from_type: type, to_type: type) -> Any:
    """Convert a primitive value from one type to another."""
    if to_type is from_type:
        return value
    elif to_type is int and isinstance(value, bool):
        return int(value)
    elif to_type is float and isinstance(value, int):
        return float(value)
    else:
        return value


def _traverse_collection(
    value: Any, origin: type, expected_type: Any, converter_func
) -> Any:
    """Generic function to traverse and convert collection types."""
    if origin is list:
        return _traverse_list(value, expected_type, converter_func)
    elif origin is tuple:
        return _traverse_tuple(value, expected_type, converter_func)
    elif origin is set:
        return _traverse_set(value, expected_type, converter_func)
    elif origin is dict:
        return _traverse_dict(value, expected_type, converter_func)
    else:
        return value


def _traverse_list(value: Any, expected_type: Any, converter_func) -> Any:
    """Traverse and convert list elements."""
    type_args = get_args(expected_type)
    if len(type_args) != 1 or not isinstance(value, list):
        return value

    element_type = type_args[0]
    return [
        _convert_value_recursive(item, element_type, converter_func) for item in value
    ]


def _traverse_tuple(value: Any, expected_type: Any, converter_func) -> Any:
    """Traverse and convert tuple elements."""
    type_args = get_args(expected_type)
    if not isinstance(value, (list, tuple)) or len(type_args) != len(value):
        return value

    return tuple(
        _convert_value_recursive(item, type_args[i], converter_func)
        for i, item in enumerate(value)
    )


def _traverse_set(value: Any, expected_type: Any, converter_func) -> Any:
    """Traverse and convert set elements."""
    type_args = get_args(expected_type)
    if len(type_args) != 1 or not isinstance(value, set):
        return value

    element_type = type_args[0]
    return {
        _convert_value_recursive(item, element_type, converter_func) for item in value
    }


def _traverse_dict(value: Any, expected_type: Any, converter_func) -> Any:
    """Traverse and convert dict elements (both keys and values)."""
    type_args = get_args(expected_type)
    if len(type_args) != 2 or not isinstance(value, dict):
        return value

    key_type, value_type = type_args
    return {
        _convert_value_recursive(
            key, key_type, converter_func
        ): _convert_value_recursive(val, value_type, converter_func)
        for key, val in value.items()
    }


def _convert_value_recursive(value: Any, expected_type: Any, converter_func) -> Any:
    """
    Recursively convert values based on expected type using a converter function.

    Args:
        value: The value to convert
        expected_type: The expected type
        converter_func: Function that converts primitive values (value, expected_type) -> converted_value
    """
    # Handle primitive types
    if expected_type in (int, bool, float, str):
        return converter_func(value, expected_type)

    # Handle collection types
    if not hasattr(expected_type, "__origin__"):
        return value

    origin = get_origin(expected_type)
    return _traverse_collection(value, origin, expected_type, converter_func)


def _convert_bool_to_int_recursive(value: Any, expected_type: Any) -> Any:
    """
    Recursively convert boolean values to integers based on expected type.
    """

    def bool_to_int_converter(val: Any, target_type: type) -> Any:
        return _convert_primitive_value(val, bool, target_type)

    return _convert_value_recursive(value, expected_type, bool_to_int_converter)


def _convert_int_to_float_recursive(value: Any, expected_type: Any) -> Any:
    """
    Recursively convert integer values to floats based on expected type.
    """

    def int_to_float_converter(val: Any, target_type: type) -> Any:
        return _convert_primitive_value(val, int, target_type)

    return _convert_value_recursive(value, expected_type, int_to_float_converter)


def _parse_signature_types(signature: str) -> list[Any]:
    """
    Parse function signature to extract argument types.
    """
    try:
        tree = ast.parse(signature)
        postcondition_node = _find_postcondition_node(tree)
        if postcondition_node is None:
            return []

        return _extract_argument_types(postcondition_node)
    except (SyntaxError, ValueError):
        return []


def _find_postcondition_node(tree: ast.AST) -> Optional[ast.FunctionDef]:
    """Find the postcondition function node in the AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "postcondition":
            return node
    return None


def _extract_argument_types(function_node: ast.FunctionDef) -> list[type]:
    """Extract argument types from function node."""
    types = []
    for arg in function_node.args.args:
        type_obj = _evaluate_type_annotation(arg.annotation)
        types.append(type_obj)
    return types


def _evaluate_type_annotation(annotation: Optional[ast.expr]) -> type:
    """Evaluate a type annotation to get the actual type object."""
    if annotation is None:
        return type(None)

    env = {}
    exec("from typing import *", env)
    return eval(ast.unparse(annotation), env)


def _annotation_to_dsl_type(
    node: ast.expr, td_env: dict[str, dict[str, ast.expr]]
) -> str:
    """Convert a Python type annotation AST node to a DSL type string.

    Supported:
      - Primitives: int → int, bool → bool, float → real, str → string
      - Collections: list[T], set[T], tuple[T1, T2, ...], dict[K, V]
      - Optional[T] (typing.Optional only) → option[T]
      - TypedDict references (by class name) → record[field: type, ...]
    """

    def _is_name(n: ast.expr, name: str) -> bool:
        return isinstance(n, ast.Name) and n.id == name

    def _is_attr(n: ast.expr, value_name: str, attr: str) -> bool:
        return (
            isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == value_name
            and n.attr == attr
        )

    # Primitives
    if isinstance(node, ast.Name):
        if node.id == "int":
            return "int"
        if node.id == "bool":
            return "bool"
        if node.id == "float":
            return "real"
        if node.id == "str":
            return "string"
        # TypedDict by name
        if node.id in td_env:
            fields = td_env[node.id]
            parts: list[str] = []
            for fname, fann in fields.items():
                parts.append(f"{fname}: {_annotation_to_dsl_type(fann, td_env)}")
            return f"record[{', '.join(parts)}]"
        # Unknown name
        raise ValueError(f"Unsupported type name: {node.id}")

    # Subscript generics: list[T], set[T], tuple[...], dict[K,V], Optional[T]
    if isinstance(node, ast.Subscript):
        base = node.value
        # Normalize slice elements to a list
        slice_node = node.slice
        if isinstance(slice_node, ast.Tuple):
            args = list(slice_node.elts)
        else:
            args = [slice_node]

        # Optional[T]
        if _is_name(base, "Optional") or _is_attr(base, "typing", "Optional"):
            if len(args) != 1:
                raise ValueError("Optional must have exactly one type argument")
            inner = _annotation_to_dsl_type(args[0], td_env)
            return f"option[{inner}]"

        # list / List
        if _is_name(base, "list") or _is_name(base, "List"):
            if len(args) != 1:
                raise ValueError("list must have exactly one type argument")
            inner = _annotation_to_dsl_type(args[0], td_env)
            return f"list[{inner}]"

        # set / Set
        if _is_name(base, "set") or _is_name(base, "Set"):
            if len(args) != 1:
                raise ValueError("set must have exactly one type argument")
            inner = _annotation_to_dsl_type(args[0], td_env)
            return f"set[{inner}]"

        # tuple / Tuple
        if _is_name(base, "tuple") or _is_name(base, "Tuple"):
            elems = ", ".join(_annotation_to_dsl_type(a, td_env) for a in args)
            return f"tuple[{elems}]"

        # dict / Dict
        if _is_name(base, "dict") or _is_name(base, "Dict"):
            if len(args) != 2:
                raise ValueError("dict must have exactly two type arguments")
            k = _annotation_to_dsl_type(args[0], td_env)
            v = _annotation_to_dsl_type(args[1], td_env)
            return f"map[{k}, {v}]"

        # typing.Optional via Attribute handled above, other typing.* not supported
        if (
            isinstance(base, ast.Attribute)
            and isinstance(base.value, ast.Name)
            and base.value.id == "typing"
        ):
            raise ValueError(f"Unsupported typing construct: typing.{base.attr}")

        # Unknown subscript base
        raise ValueError("Unsupported generic type in annotation")

    # BinOp '|' indicates PEP 604 unions; explicitly unsupported per requirements
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        raise ValueError("PEP 604 unions (T | None) are not supported; use Optional[T]")

    # Attributes like typing.X (non-subscribed) are not directly supported
    if isinstance(node, ast.Attribute):
        raise ValueError(
            "Unsupported attribute type annotation; use builtins or Optional[T]"
        )

    raise ValueError("Unsupported type annotation")


def get_parsed_arguments(
    parser_code: Optional[str], signature: str, test_input: Any, test_output: Any
) -> tuple[Any, ...]:
    """Parse and convert arguments based on signature types."""
    if parser_code is None:
        return _handle_no_parser(signature, test_input, test_output)

    return _handle_with_parser(parser_code, signature, test_input, test_output)


def _handle_no_parser(
    signature: str, test_input: Any, test_output: Any
) -> tuple[Any, ...]:
    """Handle case when no parser code is provided."""
    signature_types = _parse_signature_types(signature)
    converted = _convert_arguments_with_types(
        (*test_input, test_output), signature_types
    )
    return tuple(converted)


def _handle_with_parser(
    parser_code: str, signature: str, test_input: Any, test_output: Any
) -> tuple[Any, ...]:
    """Handle case when parser code is provided."""
    namespace = {}
    exec(parser_code, namespace)
    run_code = f"parser({repr(test_input)}, {repr(test_output)})"
    evaluated = eval(run_code, namespace)

    signature_types = _parse_signature_types(signature)
    if isinstance(evaluated, (list, tuple)):
        converted_evaluated = _convert_arguments_with_types(evaluated, signature_types)
        return tuple(converted_evaluated)

    return evaluated


def _convert_arguments_with_types(
    arguments: Any, signature_types: list[Any]
) -> list[Any]:
    """Convert arguments based on signature types."""
    if not isinstance(arguments, (list, tuple)):
        return [arguments]

    converted = []
    for i, item in enumerate(arguments):
        if i < len(signature_types):
            # First convert bool to int, then int to float
            item = _convert_bool_to_int_recursive(item, signature_types[i])
            item = _convert_int_to_float_recursive(item, signature_types[i])
            converted.append(item)
        else:
            converted.append(item)
    return converted


def _normalize_real_special_string(value: str) -> str | None:
    normalized = value.strip()
    lower = normalized.lower()
    if lower in {"nan", "+nan", "-nan"}:
        return "nan"
    if lower in {"inf", "+inf", "infinity", "+infinity"}:
        return "Infinity"
    if lower in {"-inf", "-infinity"}:
        return "-Infinity"
    return None


def _format_real_value(val: Any) -> str:
    if isinstance(val, bool):
        return "1.0" if val else "0.0"
    if isinstance(val, int):
        return f"{val}.0"

    numeric: float
    if isinstance(val, str):
        special = _normalize_real_special_string(val)
        if special is not None:
            return special
        try:
            numeric = float(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Cannot convert value {val!r} to real literal") from exc
    else:
        try:
            numeric = float(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Cannot convert value {val!r} to real literal") from exc

    if math.isnan(numeric):
        return "nan"
    if math.isinf(numeric):
        return "Infinity" if numeric > 0 else "-Infinity"
    return str(numeric)


def pyval_to_dsl_with_py_ty(val: Any, py_type) -> str:
    """Serialize a Python value to the DSL literal syntax using Python typing.

    Assumptions:
    - Records are provided as TypedDict classes for type info and dict for values.
    - Optional[T] is represented with Union[T, None] or Optional[T].
    """
    origin = get_origin(py_type)
    args = get_args(py_type)

    # Handle Optional / Union[T, None]
    if origin is Union and len(args) > 0 and type(None) in args:
        inner_type = args[0]
        if val is None:
            return "none"
        return f"some({pyval_to_dsl_with_py_ty(val, inner_type)})"

    # Primitives
    if py_type is int:
        return str(int(val))
    if py_type is bool:
        return str(bool(val))
    if py_type is float:
        return _format_real_value(val)
    if py_type is str:
        return '"' + val.replace('"', "'") + '"'

    # Collections
    if origin is list:
        assert len(args) == 1
        elem_ty = args[0]
        items = [pyval_to_dsl_with_py_ty(item, elem_ty) for item in (val or [])]
        return f"[{', '.join(items)}]"

    if origin is set:
        assert len(args) == 1
        elem_ty = args[0]
        items = [pyval_to_dsl_with_py_ty(item, elem_ty) for item in (val or set())]
        return f"{{{', '.join(items)}}}"

    if origin is tuple:
        elem_tys = args
        elems = [
            pyval_to_dsl_with_py_ty(val[i], elem_tys[i]) for i in range(len(val or ()))
        ]
        return f"({', '.join(elems)})"

    if origin is dict:
        assert len(args) == 2
        key_ty, val_ty = args
        kv_pairs = []
        for k in (val or {}).keys():
            k_str = pyval_to_dsl_with_py_ty(k, key_ty)
            v_str = pyval_to_dsl_with_py_ty((val or {})[k], val_ty)
            kv_pairs.append(f"{k_str}: {v_str}")
        return f"map{{{', '.join(kv_pairs)}}}"

    is_typed_dict = False
    annotations: dict[str, Any] | None = None

    # Heuristic detection for TypedDict across typing/typing_extensions
    if hasattr(py_type, "__annotations__") and isinstance(
        getattr(py_type, "__annotations__"), dict
    ):
        # Many TypedDicts have __total__ attribute; use annotations as signal
        if getattr(py_type, "__total__", None) is not None or (
            _TypedDict is not None
            and isinstance(py_type, type)
            and issubclass(py_type, dict) is False
        ):
            is_typed_dict = True
            annotations = getattr(py_type, "__annotations__")

    if is_typed_dict and isinstance(val, dict):
        assert annotations is not None
        kv_pairs = []
        for field_name, field_type in annotations.items():
            field_val = val.get(field_name)
            field_str = pyval_to_dsl_with_py_ty(field_val, field_type)
            kv_pairs.append(f"{field_name}: {field_str}")
        return f"record{{{', '.join(kv_pairs)}}}"

    raise ValueError(f"Unsupported Python type for DSL conversion: {py_type}")


def pyval_to_dsl_with_dsl_ty(val: Any, dsl_ty: DSLType) -> str:
    if str(dsl_ty) == "int":
        return str(int(val))
    elif str(dsl_ty) == "bool":
        return str(bool(val))
    elif str(dsl_ty) == "real":
        return _format_real_value(val)
    elif str(dsl_ty) == "char":
        return f"'{val}'"
    elif str(dsl_ty) == "string":
        return '"' + val.replace('"', "'") + '"'
    elif str(dsl_ty).startswith("list"):
        return f"[{', '.join([pyval_to_dsl_with_dsl_ty(item, dsl_ty.elem) for item in val])}]"
    elif str(dsl_ty).startswith("set"):
        return f"{{{', '.join([pyval_to_dsl_with_dsl_ty(item, dsl_ty.elem) for item in val])}}}"
    elif str(dsl_ty).startswith("tuple"):
        return f"({', '.join([pyval_to_dsl_with_dsl_ty(item, dsl_ty.elem_types[i]) for i, item in enumerate(val)])})"
    elif str(dsl_ty).startswith("map"):
        kv_pairs = []
        for key in val.keys():
            kv_pairs.append(
                f"{pyval_to_dsl_with_dsl_ty(key, dsl_ty.key)}: {pyval_to_dsl_with_dsl_ty(val[key], dsl_ty.value)}"
            )
        return f"map{{{', '.join(kv_pairs)}}}"
    elif str(dsl_ty).startswith("record"):
        kv_pairs = []
        for key in dsl_ty.fields:
            if key not in val:
                kv_pairs.append(f"{key}: none")
                continue
            kv_pairs.append(
                f"{key}: {pyval_to_dsl_with_dsl_ty(val[key], dsl_ty.fields[key])}"
            )
        return f"record{{{', '.join(kv_pairs)}}}"
    elif str(dsl_ty).startswith("option"):
        if val is None:
            return "none"
        else:
            return f"some({pyval_to_dsl_with_dsl_ty(val, dsl_ty.elem)})"
    elif str(dsl_ty) == "nonetype":
        return "none"
    else:
        raise ValueError(f"Unsupported DSL type: {dsl_ty!r}")


def pyval_to_dsl_with_schema(
    entry_schema: dict, exit_schema: dict, val: dict
) -> list[tuple[str, str]]:
    type_parser = Lark(
        grammar,
        parser="lalr",
        lexer="contextual",
        start="type",
        propagate_positions=True,
    )
    t = ASTBuilder()

    def parse(ty_str: str) -> DSLType:
        lark_ast = type_parser.parse(ty_str)
        transformed = t.transform(lark_ast)
        return transformed.ty

    args = []
    entry_val = val["entry"]
    exit_val = val["exit"]
    for entry_param in entry_schema:
        if entry_param not in entry_val:
            args.append((entry_param, "none"))
            continue
        dsl_val = pyval_to_dsl_with_dsl_ty(
            entry_val[entry_param], parse(entry_schema[entry_param])
        )
        args.append((entry_param, dsl_val))
    for exit_param in exit_schema:
        if exit_param not in exit_val:
            args.append((exit_param, "none"))
            continue
        dsl_val = pyval_to_dsl_with_dsl_ty(
            exit_val[exit_param], parse(exit_schema[exit_param])
        )
        args.append((exit_param, dsl_val))
    return args


def converter(arg: Any) -> str:
    if isinstance(arg, str):
        return f'"{arg}"'
    elif isinstance(arg, list):
        return f"[{', '.join([converter(item) for item in arg])}]"
    elif isinstance(arg, tuple):
        return f"({', '.join([converter(item) for item in arg])})"
    elif isinstance(arg, set):
        return f"{{{', '.join([converter(item) for item in arg])}}}"
    elif isinstance(arg, dict):
        return f"{{{', '.join([converter(key) + ': ' + converter(value) for key, value in arg.items()])}}}"
    else:
        return repr(arg)


def matching_with_args(
    arg_values: tuple[Any, ...],
) -> str:
    return ", ".join([converter(arg) for arg in arg_values])


def generate_evaluation_code_with_schema(
    dsl: str,
    val: dict,
    entry_schema: dict,
    exit_schema: dict,
    is_correct: bool,
    is_local: bool = False,
) -> str:
    args = pyval_to_dsl_with_schema(entry_schema, exit_schema, val)
    arg_mapping = ", ".join([f"{arg[1]}" for arg in args])
    dsl_code = add_argument_mapping_to_solver(dsl, arg_mapping)
    if is_local:
        prefix = """
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))
from expecto.src.DSL.compiler import DSLCompiler, make_solver
from expecto.src.DSL.constants import RealEncodingMode
import z3
sys.set_int_max_str_digits(10000000)
sys.setrecursionlimit(10000000)
        """
    else:
        prefix = """
from DSL.compiler import DSLCompiler, make_solver
from DSL.constants import RealEncodingMode
import z3
import sys
sys.set_int_max_str_digits(10000000)
sys.setrecursionlimit(10000000)
"""
    return dedent(f"""{prefix}
dsl_code = {repr(dsl_code)}
compiler = DSLCompiler(ignore_undefineds=True, real_encoding=RealEncodingMode.FLOATING_POINT)
try:
    spec = compiler.compile(dsl_code, entry_func="check_spec", do_ppx=False)
except Exception as err:
    print(f"Error compiling DSL code: {{err}}", file=sys.stderr)
    exit(1)
ctx = compiler.get_ctx()
solver = make_solver(ctx)
solver.add(spec)
solver.set("timeout", 29 * 1000)
solver.set("max_memory", 512 * 1024 * 1024)
checked = solver.check()
if checked == z3.unknown:
    raise TimeoutError(f"DSL solver is unknown: {{solver.reason_unknown()}}")
assert checked == z3.{"sat" if is_correct else "unsat"}, f"Checked value: {{checked}}"
    """).strip()


def generate_evaluation_code(
    dsl: str,
    function_signature: str,
    parsed_arguments: tuple[Any, ...],
    is_correct: bool,
    is_local: bool = False,
) -> str:
    dsl = dsl.replace("postcondition", "spec")
    function_node = extract_function_node_by_name(function_signature, "postcondition")
    if function_node is None:
        raise ValueError(
            f"Function signature does not contain constraint function.\n\n{function_signature}"
        )
    types = _extract_argument_types(function_node)
    converted = [
        pyval_to_dsl_with_py_ty(arg, ty) for arg, ty in zip(parsed_arguments, types)
    ]
    arg_mapping = ", ".join(converted)
    dsl_code = add_argument_mapping_to_solver(dsl, arg_mapping)
    if is_local:
        prefix = """
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))
from expecto.src.DSL.compiler import DSLCompiler, make_solver
from expecto.src.DSL.constants import RealEncodingMode
import z3
sys.set_int_max_str_digits(10000000)
sys.setrecursionlimit(10000000)
"""
    else:
        prefix = """
        from DSL.compiler import DSLCompiler, make_solver
from DSL.constants import RealEncodingMode
import z3
import sys
sys.set_int_max_str_digits(10000000)
sys.setrecursionlimit(10000000)
"""
    evaluation_code_baseline = dedent(f"""{prefix}
dsl_code = {repr(dsl_code)}
compiler = DSLCompiler(ignore_undefineds=True, real_encoding=RealEncodingMode.FLOATING_POINT)
try:
    spec = compiler.compile(dsl_code, entry_func="check_spec", do_ppx=False)
except Exception as err:
    print(f"Error compiling DSL code: {{err}}", file=sys.stderr)
    exit(1)
ctx = compiler.get_ctx()
solver = make_solver(ctx)
solver.add(spec)
solver.set("timeout", 29 * 1000)
solver.set("max_memory", 512 * 1024 * 1024)
checked = solver.check()
if checked == z3.unknown:
    raise TimeoutError(f"DSL solver is unknown: {{solver.reason_unknown()}}")
assert checked == z3.{"sat" if is_correct else "unsat"}, f"Checked value: {{checked}}"
    """).strip()
    return evaluation_code_baseline
