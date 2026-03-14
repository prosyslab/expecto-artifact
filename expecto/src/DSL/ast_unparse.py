from __future__ import annotations

from functools import singledispatch
from textwrap import indent
from typing import List, Sequence

from . import dsl_ast as ast

__all__ = [
    "unparse",
]

# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------


def unparse(node: ast.ASTNode, indent_lvl: int = 0, pretty_print: bool = True) -> str:  # noqa: D401
    """Return a source-code representation for *node*.

    Recursively dispatches on the dynamic type of *node* using
    :pyfunc:`functools.singledispatch`.

    Args:
        node: The AST node to unparse
        indent_lvl: The current indentation level
        pretty_print: If True, apply line breaks and indentation for readability.
                     If False, keep everything on single lines to preserve string content.
    """

    return _unparse(node, indent_lvl, pretty_print)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------


_INDENT = 4  # spaces per indentation level


def _i(level: int) -> str:
    """Return indentation string for *level*."""

    return " " * (_INDENT * level)


@singledispatch  # type: ignore[misc]
def _unparse(node: ast.ASTNode, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    """Fallback implementation – called when *node* type is not registered."""

    raise NotImplementedError(f"Unparsing not implemented for {type(node).__name__}")


# ---------------------------------------------------------------------------
#  Literals & identifiers
# ---------------------------------------------------------------------------


@_unparse.register
def _(node: ast.NumberLiteral, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    return str(node.value)


@_unparse.register
def _(node: ast.BoolLiteral, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    return "true" if node.value else "false"


@_unparse.register
def _(node: ast.StringLiteral, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    # Use double quotes for output consistency
    escaped = node.value
    return f'"{escaped}"'


@_unparse.register
def _(node: ast.Identifier, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    if not isinstance(node.get_type(), (ast.TypeVar, ast.FuncType)):
        return f"{node.name}: {unparse(node.ty, pretty_print=pretty_print)}"
    return node.name


@_unparse.register
def _(node: ast.TypeNode, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    return str(node.ty)


@_unparse.register
def _(node: ast.CharLiteral, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    return f"'{node.value}'"


@_unparse.register
def _(node: ast.NoneLiteral, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    return "None"


@_unparse.register
def _(node: ast.SomeExpr, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    """Unparse SomeExpr as some(value) function call."""
    value_str = _unparse(node.value, indent_lvl, pretty_print)
    return f"some({value_str})"


# ---------------------------------------------------------------------------
#  Expressions – helpers
# ---------------------------------------------------------------------------


def _join(items: List[str], sep: str = ", ") -> str:
    return sep.join(items)


# ---------------------------------------------------------------------------
#  Expressions
# ---------------------------------------------------------------------------


@_unparse.register
def _(node: ast.UnaryOp, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    operand = unparse(node.operand, pretty_print=pretty_print)
    # For "not" / "¬" we want a space after the operator, for arithmetic we do not.
    op = node.op
    if op in {"¬", "not"}:
        return f"({op} {operand})"
    return f"({op}{operand})"


@_unparse.register
def _(node: ast.BinaryOp, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    left = unparse(node.left, pretty_print=pretty_print)
    right = unparse(node.right, pretty_print=pretty_print)
    if pretty_print and len(left) + len(right) > 20:
        return f"({left} {node.op}\n{indent(right, _i(1))})"
    return f"({left} {node.op} {right})"


@_unparse.register
def _(node: ast.Comparisons, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    comps = node.comparisons

    parts: List[str] = [unparse(comps[0].left, pretty_print=pretty_print)]
    for comp in comps:
        parts.append(comp.op)
        parts.append(unparse(comp.right, pretty_print=pretty_print))
    return f"({' '.join(parts)})"


@_unparse.register
def _(node: ast.IfExpr, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    cond = unparse(node.condition, pretty_print=pretty_print)
    then = unparse(node.then_branch, pretty_print=pretty_print)
    else_ = unparse(node.else_branch, pretty_print=pretty_print)
    if pretty_print and len(then) + len(else_) > 20:
        return f"(if {cond} then\n{indent(then, _i(1))}\nelse\n{indent(else_, _i(1))})"
    return f"(if {cond} then {then} else {else_})"


@_unparse.register
def _(node: ast.LambdaExpr, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    args = _join([unparse(arg, pretty_print=pretty_print) for arg in node.args])
    body = unparse(node.body, pretty_print=pretty_print)
    if pretty_print and len(args) + len(body) > 20:
        return f"lambda ({args}) = \n{indent(body, _i(1))}"
    return f"lambda ({args}) = {body}"


@_unparse.register
def _(node: ast.ForallExpr, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    args = _join([unparse(arg, pretty_print=pretty_print) for arg in node.vars])
    expr = unparse(node.satisfies_expr, pretty_print=pretty_print)
    if pretty_print and len(args) + len(expr) > 20:
        return f"(∀({args}) ::\n{indent(expr, _i(1))})"
    return f"(∀({args}) :: {expr})"


@_unparse.register
def _(node: ast.ExistsExpr, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    args = _join([unparse(arg, pretty_print=pretty_print) for arg in node.vars])
    expr = unparse(node.satisfies_expr, pretty_print=pretty_print)
    if pretty_print and len(args) + len(expr) > 20:
        return f"(∃({args}) ::\n{indent(expr, _i(1))})"
    return f"(∃({args}) :: {expr})"


@_unparse.register
def _(node: ast.FuncCall, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    func = unparse(node.func, pretty_print=pretty_print)
    args = _join([unparse(arg, pretty_print=pretty_print) for arg in node.args])
    return f"{func}({args})"


@_unparse.register
def _(node: ast.ListAccess, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    seq = unparse(node.seq, pretty_print=pretty_print)
    idx = unparse(node.index, pretty_print=pretty_print)
    return f"{seq}[{idx}]"


@_unparse.register
def _(node: ast.FieldAccess, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    record = unparse(node.record, pretty_print=pretty_print)
    return f"{record}.{node.field_name}"


@_unparse.register
def _(node: ast.ExplicitList, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    elems = _join([unparse(el, pretty_print=pretty_print) for el in node.elements])
    return f"[{elems}]"


@_unparse.register
def _(node: ast.ExplicitSet, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    elems = _join([unparse(el, pretty_print=pretty_print) for el in node.elements])
    return "{" + elems + "}"


@_unparse.register
def _(node: ast.ExplicitMultiset, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    elems = _join([unparse(el, pretty_print=pretty_print) for el in node.elements])
    return "multiset{" + elems + "}"


@_unparse.register
def _(node: ast.ExplicitMap, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    kv_pairs = _join(
        [
            unparse(k, pretty_print=pretty_print)
            + " : "
            + unparse(v, pretty_print=pretty_print)
            for k, v in zip(node.keys, node.values)
        ]
    )
    return "map{" + kv_pairs + "}"


@_unparse.register
def _(node: ast.ExplicitRecord, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    field_pairs = _join(
        [
            f"{field_name}: {unparse(field_value, pretty_print=pretty_print)}"
            for field_name, field_value in node.fields.items()
        ]
    )
    return "record{" + field_pairs + "}"


@_unparse.register
def _(node: ast.RangeList, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    start = unparse(node.start, pretty_print=pretty_print)
    end = unparse(node.end, pretty_print=pretty_print) if node.end is not None else ""
    return f"[{start} .. {end}]"


@_unparse.register
def _(node: ast.RangeSet, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    start = unparse(node.start, pretty_print=pretty_print)
    end = unparse(node.end, pretty_print=pretty_print) if node.end is not None else ""
    return f"{{{start} .. {end}}}"


@_unparse.register
def _(node: ast.ListComprehension, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    expr = unparse(node.expr, pretty_print=pretty_print)
    exprs = _join(
        [unparse(gen, pretty_print=pretty_print) for gen in node.generators]
        + [unparse(cond, pretty_print=pretty_print) for cond in node.conditions]
    )

    return f"[{expr} | {exprs}]"


@_unparse.register
def _(node: ast.SetComprehension, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    expr = unparse(node.expr, pretty_print=pretty_print)
    exprs = _join(
        [unparse(gen, pretty_print=pretty_print) for gen in node.generators]
        + [unparse(cond, pretty_print=pretty_print) for cond in node.conditions]
    )
    return f"{{{expr} | {exprs}}}"


@_unparse.register
def _(node: ast.Generator, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    var = unparse(node.var, pretty_print=pretty_print)
    expr = unparse(node.expr, pretty_print=pretty_print)
    return f"{var} <- {expr}"


@_unparse.register
def _(node: ast.TupleExpr, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    elems = _join([unparse(el, pretty_print=pretty_print) for el in node.elements])
    return f"({elems})"


# ---------------------------------------------------------------------------
#  Statements
# ---------------------------------------------------------------------------


@_unparse.register
def _(node: ast.Ensure, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    return _i(indent_lvl) + f"ensure {unparse(node.expr, pretty_print=pretty_print)};"


@_unparse.register
def _(node: ast.Require, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    return _i(indent_lvl) + f"require {unparse(node.expr, pretty_print=pretty_print)};"


@_unparse.register
def _(node: ast.VarDecl, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    var = unparse(node.var, pretty_print=pretty_print)
    expr = unparse(node.expr, pretty_print=pretty_print)
    if pretty_print and len(var) + len(expr) > 20:
        return indent(f"var {var} = \n{indent(expr, _i(1))};", _i(indent_lvl))
    return _i(indent_lvl) + f"var {var} = {expr};"


# ---------------------------------------------------------------------------
#  Declarations
# ---------------------------------------------------------------------------


def _unparse_arg_list(args: Sequence[ast.Identifier], pretty_print: bool = True) -> str:
    return f"({_join([unparse(arg, pretty_print=pretty_print) for arg in args])})"


@_unparse.register
def _(node: ast.Description, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    return unparse(
        ast.StringLiteral(pos=node.pos, value=node.content), pretty_print=pretty_print
    )


@_unparse.register
def _(node: ast.PredicateDef, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    sig = f"predicate {node.name}{_unparse_arg_list(node.args, pretty_print=pretty_print)}"
    if node.description is not None:
        desc = unparse(node.description, pretty_print=pretty_print)
        sig = f"{sig} : {desc}"
    if node.body is None:
        return indent(sig, _i(indent_lvl)) if pretty_print else sig
    var_decls = (
        indent(
            _join(
                [
                    unparse(var_decl, pretty_print=pretty_print)
                    for var_decl in node.var_decls
                ],
                sep="\n",
            ),
            _i(indent_lvl + 1),
        )
        if pretty_print
        else _join(
            [
                unparse(var_decl, pretty_print=pretty_print)
                for var_decl in node.var_decls
            ],
            sep=" ",
        )
    )
    body = (
        indent(
            unparse(node.body, indent_lvl + 1, pretty_print=pretty_print),
            _i(indent_lvl + 1),
        )
        if pretty_print
        else unparse(node.body, pretty_print=pretty_print)
    )
    if pretty_print:
        joined = body if not var_decls else var_decls + "\n" + body
        body = " {\n" + joined + "\n" + _i(indent_lvl) + "}"
        return _i(indent_lvl) + sig + body
    else:
        joined = body if not var_decls else var_decls + " " + body
        return sig + " { " + joined + " }"


def _is_explicit_function(node: ast.FunctionDef) -> bool:
    is_body_is_not_none = node.body is not None
    is_empty_ensures = len(node.ensures) == 0
    is_empty_requires = len(node.requires) == 0
    return is_body_is_not_none or (is_empty_ensures and is_empty_requires)


@_unparse.register
def _(node: ast.FunctionDef, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    if isinstance(node.return_val.get_type(), ast.TypeVar):
        sig = f"function {node.name}{_unparse_arg_list(node.args, pretty_print=pretty_print)}"
    elif _is_explicit_function(node):
        sig = f"function {node.name}{_unparse_arg_list(node.args, pretty_print=pretty_print)} -> {str(node.return_val.ty)}"
    else:
        sig = f"function {node.name}{_unparse_arg_list(node.args, pretty_print=pretty_print)} -> ({unparse(node.return_val, pretty_print=pretty_print)})"

    if node.description is not None:
        desc = unparse(node.description, pretty_print=pretty_print)
        sig = f"{sig} : {desc}"

    body_lines: List[str] = []
    for var_decl in node.var_decls:
        body_lines.append(unparse(var_decl, indent_lvl + 1, pretty_print=pretty_print))
    for req in node.requires:
        body_lines.append(unparse(req, indent_lvl + 1, pretty_print=pretty_print))
    for ens in node.ensures:
        body_lines.append(unparse(ens, indent_lvl + 1, pretty_print=pretty_print))
    if node.body is not None:
        body = unparse(node.body, indent_lvl + 1, pretty_print=pretty_print)
        if pretty_print:
            body = indent(body, _i(indent_lvl + 1))
        body_lines.append(body)
    if not body_lines:
        return _i(indent_lvl) + sig if pretty_print else sig
    if pretty_print:
        body = "\n".join(body_lines)
        body = "{\n" + body + "\n" + _i(indent_lvl) + "}"
        return f"{_i(indent_lvl)}{sig} {body}"
    else:
        body = " ".join(body_lines)
        return f"{sig} {{ {body} }}"


# ---------------------------------------------------------------------------
#  Program root
# ---------------------------------------------------------------------------


@_unparse.register
def _(node: ast.Specification, indent_lvl: int, pretty_print: bool = True) -> str:  # noqa: D401
    parts = [
        unparse(decl, indent_lvl, pretty_print=pretty_print)
        for decl in node.declarations
    ]
    return "\n\n".join(parts)
