"""Tests for constant propagation on new built-ins and operations."""

import sys
from pathlib import Path

import pytest
import z3

# Add root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.compiler import DSLCompiler
from src.DSL.constants import RealEncodingMode


@pytest.fixture
def compiler() -> DSLCompiler:
    return DSLCompiler()


def _check_pred_true(compiler: DSLCompiler, code: str, pred_name: str = "P") -> None:
    compiled = compiler.compile(code, entry_func=pred_name)
    ctx = compiler.ast_to_z3._ctx
    solver = z3.Solver(ctx=ctx)
    solver.set("timeout", 2000)
    solver.add(compiled)
    assert solver.check() == z3.sat


class TestCPBuiltins:
    def test_cardinality_on_sets(self, compiler: DSLCompiler):
        code = """
        predicate P() {
            cardinality({1, 2, 3}) == 3 and cardinality({1..3}) == 3
        }
        """
        _check_pred_true(compiler, code)

    def test_string_case_constant_folding(self, compiler: DSLCompiler):
        code = """
        predicate P() {
            uppercase("abcXYZ") == "ABCXYZ" and lowercase("AbC123") == "abc123"
        }
        """
        _check_pred_true(compiler, code)

    def test_numeric_conversions(self, compiler: DSLCompiler):
        code = """
        predicate P() {
            int2real(2) == 2.0 and real2int(4.2) == 4
        }
        """
        _check_pred_true(compiler, code)

    def test_is_infinite_is_nan_constants(self):
        fp_compiler = DSLCompiler(real_encoding=RealEncodingMode.FLOATING_POINT)
        code = """
        predicate P() {
            is_infinite(Infinity) == True and
            is_infinite(5.0) == False and
            is_nan(nan) == True and
            is_nan(7.5) == False
        }
        """
        _check_pred_true(fp_compiler, code)

    def test_all_function_constant_propagation(self, compiler: DSLCompiler):
        code = """
        predicate P() {
            all(lambda (x) = x > 0, [1, 2, 3]) == True and
            all(lambda (x) = x > 0, [1, -2, 3]) == False and
            all(lambda (x) = x % 2 == 0, [2, 4, 6]) == True and
            all(lambda (x) = x % 2 == 0, [2, 3, 4]) == False
        }
        """
        _check_pred_true(compiler, code)

    def test_any_function_constant_propagation(self, compiler: DSLCompiler):
        code = """
        predicate P() {
            any(lambda (x) = x > 0, [-1, -2, 3]) == True and
            any(lambda (x) = x > 0, [-1, -2, -3]) == False and
            any(lambda (x) = x % 2 == 0, [1, 3, 4]) == True and
            any(lambda (x) = x % 2 == 0, [1, 3, 5]) == False
        }
        """
        _check_pred_true(compiler, code)

    def test_all_any_empty_list_edge_cases(self, compiler: DSLCompiler):
        code = """
        predicate P() {
            all(lambda (x) = x > 0, []) == True and
            any(lambda (x) = x > 0, []) == False
        }
        """
        _check_pred_true(compiler, code)
