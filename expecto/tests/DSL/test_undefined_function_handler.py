"""Comprehensive test cases for the type checker."""

import sys
from pathlib import Path

import pytest
import z3

# Add root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.compiler import DSLCompiler
from src.DSL.dsl_ast import (
    Boolean,
    FuncCall,
    FuncType,
    Identifier,
    Integer,
    Specification,
)


class TestUndefinedFunctionHandler:
    """Test cases for the UndefinedFunctionHandler class."""

    @pytest.fixture
    def compiler(self):
        return DSLCompiler(ignore_undefineds=True)

    def test_undefined_function_handler(self, compiler):
        """Test the undefined function handler."""
        code = "predicate p(x: int) { undefined_func(x) }"
        parsed = compiler.parse(code)
        errors = compiler.type_check(parsed)
        assert isinstance(parsed, Specification)
        assert len(errors) == 0, "\n".join(str(error) for error in errors)

        body = parsed.declarations[0].body
        assert isinstance(body, FuncCall)
        func = body.func
        assert isinstance(func, Identifier)
        assert func.get_type() == FuncType([Integer()], Boolean()), (
            f"Function type is {func.ty}"
        )

        compiled = compiler.compile(code)
        solver = z3.Solver(ctx=compiler.get_ctx())
        solver.add(compiled)
        assert solver.check() == z3.sat
