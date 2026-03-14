"""Unit tests for ReferenceCollector collecting referenced function names.

Covers:
- Direct function/predicate call references
- Higher-order usage where a user-defined function is passed as an argument
- Ensures built-ins and plain parameters are not counted as references
"""

import sys
from pathlib import Path

import pytest

# Add project root to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.compiler import DSLCompiler
from src.DSL.dsl_ast import Specification
from src.DSL.reference_collector import ReferenceCollector
from src.solvers.tree_search import filter_unused_defs


@pytest.fixture
def compiler() -> DSLCompiler:
    return DSLCompiler()


class TestReferenceCollector:
    def test_collects_direct_and_hof(self, compiler: DSLCompiler):
        code = """
        function double(x: int) -> (res: int) {
            ensure res == x * 2;
        }

        function helper(y: int) -> (res: int) {
            ensure res == y + 1;
        }

        function unused(z: int) -> (res: int) {
            ensure res == z - 1;
        }

        predicate p() {
            helper(1) == 2 ∧
            map(double, [1, 2]) == [2, 4]
        }
        """

        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        defined_functions = {d.name for d in spec.declarations}

        entry_def = spec.declarations[-1]

        rc = ReferenceCollector(defined_functions)
        names = rc.collect(entry_def)

        # Should include only user-defined functions that are referenced
        assert names == {"helper", "double"}

    def test_ignores_builtins_and_params_but_counts_user_defined(
        self, compiler: DSLCompiler
    ):
        code = """
        function double(x: int) -> (res: int) {
            ensure res == x * 2;
        }

        function apply_twice(f, x) -> (res: int) {
            ensure res == f(f(x));
        }

        predicate q() {
            apply_twice(double, 3) == 12 ∧
            all(lambda (t) = t > 0, [1]) == true
        }
        """

        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        defined_functions = {d.name for d in spec.declarations}
        rc = ReferenceCollector(defined_functions)

        entry_def = spec.declarations[-1]
        names = rc.collect(entry_def)

        # Built-ins like 'all' should not be collected; parameters like 'f' should not be collected
        assert names == {"apply_twice", "double"}


class TestFilterUnusedDefs:
    def test_filters_formals_only(self, compiler: DSLCompiler):
        code = """
        function double(x: int) -> (res: int) {
            ensure res == x * 2;
        }

        function helper(y: int) -> (res: int) {
            ensure res == y + 1;
        }

        function unused(z: int) -> (res: int) {
            ensure res == z - 1;
        }

        predicate p() {
            helper(1) == 2 ∧
            map(double, [1, 2]) == [2, 4]
        }
        """

        spec = compiler.parse(code)
        assert isinstance(spec, Specification)

        formal_defs = list(spec.declarations)
        placeholders: list = []

        kept_formals, kept_placeholders = filter_unused_defs(
            formal_defs, placeholders, entry_point="p"
        )

        formal_names = {d.name for d in kept_formals}
        placeholder_names = {d.name for d in kept_placeholders}

        assert formal_names == {"p", "double", "helper"}
        assert placeholder_names == set()

    def test_filters_across_formals_and_placeholders(self, compiler: DSLCompiler):
        code = """
        function double(x: int) -> (res: int) {
            ensure res == x * 2;
        }

        function helper(y: int) -> (res: int) {
            ensure res == y + 1;
        }

        function unused(z: int) -> (res: int) {
            ensure res == z - 1;
        }

        function ghost(t: int) -> (res: int) {
            ensure res == t;
        }

        predicate p() {
            helper(1) == 2 ∧
            map(double, [1, 2]) == [2, 4]
        }
        """

        spec = compiler.parse(code)
        assert isinstance(spec, Specification)

        # Split defs across formals and placeholders: keep p, double, unused as formals;
        # move helper and ghost to placeholders. Only helper is reachable.
        name_to_def = {d.name: d for d in spec.declarations}
        formal_defs = [name_to_def[n] for n in ["p", "double", "unused"]]
        placeholders = [name_to_def[n] for n in ["helper", "ghost"]]

        kept_formals, kept_placeholders = filter_unused_defs(
            formal_defs, placeholders, entry_point="p"
        )

        formal_names = {d.name for d in kept_formals}
        placeholder_names = {d.name for d in kept_placeholders}

        assert formal_names == {"p", "double"}
        assert placeholder_names == {"helper"}
