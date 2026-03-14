"""Tests for option[T] type support in the DSL."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import z3

# Add root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.compiler import DSLCompiler
from src.DSL.dsl_ast import Specification


@pytest.fixture
def compiler() -> DSLCompiler:
    return DSLCompiler()


def test_predicate_with_option_arg(compiler: DSLCompiler):
    code = """
    predicate P(x: option[int]) { true }
    """
    spec = compiler.parse(code)
    assert isinstance(spec, Specification)
    errors = compiler.type_check(spec)
    assert errors == []


def test_function_with_option_return_and_arg(compiler: DSLCompiler):
    code = """
    function id_opt(x: option[int]) -> option[int] {
        x
    }
    """
    spec = compiler.parse(code)
    assert isinstance(spec, Specification)
    errors = compiler.type_check(spec)
    assert errors == []


def test_nested_option_in_list_and_tuple(compiler: DSLCompiler):
    code = """
    predicate Q(xs: list[option[int]], t: tuple[option[int], option[bool]]) { true }
    """
    spec = compiler.parse(code)
    assert isinstance(spec, Specification)
    errors = compiler.type_check(spec)
    assert errors == []


def test_unparse_preserves_option(compiler: DSLCompiler):
    from src.DSL.ast_unparse import unparse

    code = """
    function f(x: option[int]) -> option[int] { x }
    """
    spec = compiler.parse(code)
    pretty = unparse(spec)
    assert "option[int]" in pretty


def test_none_literal_polymorphic(compiler: DSLCompiler):
    code = """
    function f() -> option[int] { None }
    predicate P(x: option[bool]) { x == None }
    """
    spec = compiler.parse(code)
    errors = compiler.type_check(spec)
    assert errors == []


def test_none_literal_accepts_nonetype_argument(compiler: DSLCompiler):
    code = """
    predicate spec(x: nonetype) : "doc"
    predicate check_spec() {
        spec(none)
    }
    """
    compiled = compiler.compile(code, entry_func="check_spec")
    solver = z3.Solver(ctx=compiler.get_ctx())
    solver.add(compiled)
    assert solver.check() == z3.sat


def test_none_literal_accepts_nonetype_return(compiler: DSLCompiler):
    code = """
    function f() { none }
    predicate spec() { f() == none }
    """
    compiled = compiler.compile(code)
    solver = z3.Solver(ctx=compiler.get_ctx())
    solver.add(compiled)
    assert solver.check() == z3.sat


def test_option_builtins(compiler: DSLCompiler):
    code = """
    function f(x: option[int]) -> bool {
        is_some(x) == (unwrap(x) == 0) || is_none(x)
    }
    """
    spec = compiler.parse(code)
    errors = compiler.type_check(spec)
    assert errors == []


def test_some_constructor(compiler: DSLCompiler):
    code = """
    function f(x: int) -> option[int] { some(x) }
    """
    spec = compiler.parse(code)
    errors = compiler.type_check(spec)
    assert errors == []


def test_constant_propagation(compiler: DSLCompiler):
    code = """
    predicate P() {
        is_some(some(0))
    }
    """
    compiled = compiler.compile(code)
    solver = z3.Solver(ctx=compiler.get_ctx())
    solver.add(compiled)
    assert solver.check() == z3.sat

    code = """
    predicate P() {
        is_none(none)
    }
    """
    compiled = compiler.compile(code)
    solver = z3.Solver(ctx=compiler.get_ctx())
    solver.add(compiled)
    assert solver.check() == z3.sat


def test_unparse_option(compiler: DSLCompiler):
    code = "function f() -> option[int] { none }"
    spec = compiler.parse(code)
    pretty = compiler.unparse(spec)
    round_trip = compiler.unparse(compiler.parse(pretty))
    assert pretty == round_trip


def test_mixing_list(compiler: DSLCompiler):
    code = """
    predicate P() {unwrap([some(0), none, some(1)][2]) == 1}
    """
    spec = compiler.parse(code)
    errors = compiler.type_check(spec)
    assert errors == []
