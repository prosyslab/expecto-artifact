import ast
from typing import Any, get_args, get_origin

import z3

custom_datatypes = dict[str, tuple[str, z3.DatatypeSortRef]]


def py_type_pp(py_type: type) -> str:
    """
    Pretty print Python type into a string representation.

    Args:
        py_type: Python type to convert to string

    Returns:
        String representation of the type (e.g., "list[int]", "tuple[int, bool]")
    """
    origin_type = get_origin(py_type)
    args = get_args(py_type)
    if origin_type is None:
        return f"{py_type.__name__}"
    else:
        if len(args) == 0:
            return f"{origin_type.__name__}"
        else:
            return (
                f"{origin_type.__name__}[{', '.join(py_type_pp(arg) for arg in args)}]"
            )


class PythonTypeToZ3TypeConverter(ast.NodeTransformer):
    def visit_Name(self, node: ast.Name) -> Any:
        match node.id:
            case "int":
                node.id = "z3.IntNumRef"
            case "float":
                node.id = "z3.ArithRef"
            case "str":
                node.id = "z3.SeqRef"
            case "bool":
                node.id = "z3.BoolRef"
        return node


converter = PythonTypeToZ3TypeConverter()


def convert_python_type_ast(tree: ast.AST) -> ast.AST:
    return converter.visit(tree)


def convert_python_val_to_z3_val(
    val: Any,
) -> z3.ExprRef | list | tuple:
    if isinstance(val, int):
        return z3.IntVal(val)
    elif isinstance(val, float):
        return z3.RealVal(val)
    elif isinstance(val, str):
        return z3.StringVal(val)
    elif isinstance(val, bool):
        return z3.BoolVal(val)
    elif isinstance(val, list):
        return [convert_python_val_to_z3_val(v) for v in val]
    elif isinstance(val, tuple):
        return tuple(convert_python_val_to_z3_val(v) for v in val)
    else:
        raise ValueError(f"Unsupported value type: {type(val)}")


convert_python_val_to_z3_val_str_version = """
def convert_python_val_to_z3_val(
    val,
):
    if isinstance(val, int):
        return z3.IntVal(val)
    elif isinstance(val, float):
        return z3.RealVal(val)
    elif isinstance(val, str):
        return z3.StringVal(val)
    elif isinstance(val, bool):
        return z3.BoolVal(val)
    elif isinstance(val, list):
        return [convert_python_val_to_z3_val(v) for v in val]
    elif isinstance(val, tuple):
        return tuple(convert_python_val_to_z3_val(v) for v in val)
    else:
        raise ValueError(f"Unsupported value type: {type(val)}")
"""


def z3_relevant_postprocess(code: str) -> str:
    """
    Postprocess the code to make it more relevant to Z3.

    1. Replace "//" to "/"
    """
    return code.replace("//", "/")
