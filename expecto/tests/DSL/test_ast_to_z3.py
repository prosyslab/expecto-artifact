"""Comprehensive test cases for ast_to_z3 module."""

import sys
from pathlib import Path

import pytest
import z3

# Add root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.compiler import DSLCompiler
from src.DSL.constants import RealEncodingMode
from src.DSL.dsl_ast import Specification


class TestASTToZ3:
    """Comprehensive test cases for AST to Z3 conversion."""

    @pytest.fixture
    def compiler(self):
        return DSLCompiler()

    def test_no_arg_function(self, compiler: DSLCompiler):
        """Test function with no arguments."""
        code = """
        function no_arg() {
            1
        }

        predicate P() {
            false
        }
        """

        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)

        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        assert solver.check() == z3.sat

        no_arg = z3.Int("no_arg", ctx=ctx)
        assert solver.model().eval(no_arg).py_value() == 1

        P = z3.Bool("P")
        assert not solver.model().eval(P).py_value()

    def test_simple_predicates_and_arithmetic(self, compiler: DSLCompiler):
        """Integration test for simple predicates and arithmetic operations."""
        code = """
        predicate isPositive(x: int) {
            x > 0
        }

        predicate isEven(x: int) {
            x % 2 == 0
        }

        function add(a: int, b: int) -> (res: int) {
            ensure res == a + b;
        }

        function multiply(a: int, b: int) -> (res: int) {
            ensure res == a * b;
        }

        predicate Main() {
            isPositive(1) ∧
            isEven(2) ∧
            add(3, 4) == 7 ∧
            add(1, 2) == 3 ∧
            add(10, 11) == 21 ∧
            multiply(3, 4) == 12
        }
        """

        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)

        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        result = solver.check()

        # Should be satisfiable or unknown (Z3 timeout/complexity issues are OK)
        assert result == z3.sat

    def test_conditional_expressions_and_boolean_logic(self, compiler: DSLCompiler):
        """Integration test for conditional expressions and complex boolean logic."""
        code = """
        function sign(x: int) {
            if x > 0 then 1 else if x < 0 then -1 else 0
        }

        function absoluteValue(x: int) {
            if x >= 0 then x else -x
        }

        predicate sameSign(x: int, y: int) {
            (x > 0 ∧ y > 0) ∨ (x < 0 ∧ y < 0) ∨ (x == 0 ∧ y == 0)
        }

        predicate bothPositive(x: int, y: int) {
            x > 0 ∧ y > 0
        }

        predicate Main() {
            sign(1) == 1 ∧
            sign(-1) == -1 ∧
            sign(0) == 0 ∧
            absoluteValue(1) == 1 ∧
            absoluteValue(-1) == 1 ∧
            absoluteValue(0) == 0 ∧
            sameSign(1, 2) ∧
            ¬ sameSign(-1, -2) ∧
            ¬ sameSign(0, 0) ∧
            ¬ sameSign(1, -2) ∧
            bothPositive(1, 2) ∧
            ¬ bothPositive(-1, 2) ∧
            ¬ bothPositive(1, -2) ∧
            ¬ bothPositive(0, 0)
        }

        """

        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)

        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        result = solver.check()

        assert result == z3.sat, solver.reason_unknown()

    def test_list_operations_and_access(self, compiler: DSLCompiler):
        """Integration test for list operations, indexing, and predicates."""
        code = """
        function getLength(lst: list[int]) {
            len(lst)
        }

        function getElement(lst: list[int], index: int) {
            if index >= 0 ∧ index < len(lst) then lst[index] else 0
        }

        predicate isEmpty(lst: list[int]) {
            len(lst) == 0
        }

        predicate hasElements(lst: list[int]) {
            len(lst) > 0
        }

        function firstElement(lst: list[int]) {
            if len(lst) > 0 then lst[0] else -1
        }

        predicate Main() {
            getElement([], 0) == 0 ∧
            getLength([]) == 0 ∧
            getLength([1, 2, 3]) == 3 ∧
            getElement([1, 2, 3], 1) == 2 ∧
            getElement([1, 2, 3], 5) == 0 ∧
            firstElement([]) == -1 ∧
            firstElement([1, 2, 3]) == 1 ∧
            isEmpty([]) ∧
            hasElements([1, 2, 3]) ∧
            ¬ hasElements([])
        }
        """

        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)

        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        result = solver.check()

        assert result == z3.sat, solver.reason_unknown()

    def test_set_operations_and_comprehensions(self, compiler: DSLCompiler):
        """Integration test for set operations."""
        code = """
        function isEmpty(s: set[int]) {
            set_is_empty(s)
        }

        function singletonSet(x: int) {
            {x}
        }

        predicate membership(s: set[int], x: int) {
            x in s
        }

        predicate isSubset(s1: set[int], s2: set[int]) {
            ∀ (x: int) :: x in s1 ==> x in s2
        }

        predicate Main() {
            isEmpty({}) ∧
            ¬ isEmpty({1}) ∧
            membership({1, 2, 3}, 2) ∧
            isSubset({1, 2}, {1, 2, 3}) ∧
            ¬ isSubset({1, 2, 3}, {1, 2}) ∧
            isSubset({1, 2, 3}, {1, 2, 3}) ∧
            ¬ isSubset({1, 2, 3}, {1, 2, 3, 4}) ∧
            isSubset({1, 2, 3}, {1, 2, 3, 4}) ∧
            ¬ isSubset({1, 2, 3}, {1, 2, 3, 4, 5})
        }
        """

        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)

        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        result = solver.check()

        assert result == z3.sat

    def test_multiset_permutation(self, compiler: DSLCompiler):
        """Equality of multisets should hold for permutations of the same list (same multiplicities)."""
        code = """
        predicate perm_ok() {
            list2multiset([1,2,2,3]) == list2multiset([2,1,3,2])
        }
        """

        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)

        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 3000)
        solver.add(z3_expr)
        solver.assert_and_track(z3.Bool("perm_ok", ctx=ctx), "perm_ok")
        result = solver.check()

        assert result == z3.sat

    def test_multiset_and_list2multiset(self, compiler: DSLCompiler):
        """Integration test for multiset support and list2multiset conversion with multiplicity."""
        code = """
        predicate test_membership() {
            2 in list2multiset([1,2,2,3])
        }

        predicate test_equality() {
            // multiplicity preserved → different counts make them unequal
            list2multiset([1,2,2,3]) != list2multiset([1,2,3,3])
        }
        """

        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)

        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 3000)
        solver.add(z3_expr)
        solver.assert_and_track(z3.Bool("test_membership", ctx=ctx), "test_membership")
        solver.assert_and_track(z3.Bool("test_equality", ctx=ctx), "test_equality")
        result = solver.check()

        assert result == z3.sat

    def test_explicit_multiset_literals(self, compiler: DSLCompiler):
        """Test explicit multiset literal encoding and operations."""
        code = """
        predicate test_explicit_multiset() {
            // Test membership in explicit multiset
            2 in multiset {1, 2, 2, 3}
        }

        predicate test_multiset_equality() {
            // Test equality of explicit multisets
            multiset {1, 2, 2, 3} == multiset {1, 2, 2, 3}
        }

        predicate test_multiset_inequality() {
            // Test inequality due to different multiplicities
            multiset {1, 2, 2, 3} != multiset {1, 2, 3, 3}
        }
        """

        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)

        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 3000)
        solver.add(z3_expr)
        solver.assert_and_track(
            z3.Bool("test_explicit_multiset", ctx=ctx), "test_explicit_multiset"
        )
        solver.assert_and_track(
            z3.Bool("test_multiset_equality", ctx=ctx), "test_multiset_equality"
        )
        solver.assert_and_track(
            z3.Bool("test_multiset_inequality", ctx=ctx), "test_multiset_inequality"
        )
        result = solver.check()

        assert result == z3.sat

    def test_empty_multiset_operations(self, compiler: DSLCompiler):
        """Test operations on empty multisets."""
        code = """
        predicate test_empty_multiset() {
            // Empty multiset should not contain any elements
            not (1 in multiset {})
        }

        predicate test_empty_multiset_equality() {
            // Empty multisets should be equal
            multiset {} == multiset {}
        }
        """

        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)

        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 3000)
        solver.add(z3_expr)
        solver.assert_and_track(
            z3.Bool("test_empty_multiset", ctx=ctx), "test_empty_multiset"
        )
        solver.assert_and_track(
            z3.Bool("test_empty_multiset_equality", ctx=ctx),
            "test_empty_multiset_equality",
        )
        result = solver.check()

        assert result == z3.sat

    def test_inlining_preserves_congruence_unsat(self, compiler: DSLCompiler):
        """Function inlining must preserve congruence so identical calls return identical results.

        This ensures cases like f(0) == 1 ∧ f(0) == 2 are UNSAT when f has only ensures.
        """
        code = """
        predicate spec() {
            f(0) == 1 and f(0) == 2
        }
        function f(x: int) -> (res: int) {
            ensure res >= x;
        }
        """

        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 3000)
        solver.add(z3_expr)
        # Assert the predicate holds to force the body constraints
        solver.add(z3.Bool("spec", ctx=ctx))
        result = solver.check()

        assert result == z3.unsat

    def test_hof_functions(self, compiler: DSLCompiler):
        """Integration test for higher-order functions."""
        code = """
        predicate map_test() {
            map(lambda (x: int) = x + 1, [1, 2, 3]) == [2, 3, 4]
        }

        predicate map_i_test() {
            map_i(lambda (i: int, elem: int) = i * 2 + elem, [1, 2, 3]) == [1, 4, 7]
        }

        predicate fold_test() {
            fold(lambda (x: int, y: int) = x + y, 0, [1, 2, 3]) == 6
        }

        predicate fold_i_test() {
            fold_i(lambda (i: int, acc: int, elem: int) = acc + i * 2 + elem, 0, [1, 2, 3]) == 12
        }

        predicate filter_test() {
            filter(lambda (x: int) = x % 2 == 0, [1, 2, 3]) == [2]
        }
        """
        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 10000)
        solver.add(z3_expr)
        solver.assert_and_track(z3.Bool("map_test", ctx=ctx), "map_test")
        solver.assert_and_track(z3.Bool("map_i_test", ctx=ctx), "map_i_test")
        solver.assert_and_track(z3.Bool("filter_test", ctx=ctx), "filter_test")
        solver.assert_and_track(z3.Bool("fold_test", ctx=ctx), "fold_test")
        solver.assert_and_track(z3.Bool("fold_i_test", ctx=ctx), "fold_i_test")
        result = solver.check()

        assert result == z3.sat, f"Solver failed with: {solver.unsat_core()}"

    def test_constraint_passing_in_quantifiers(self, compiler: DSLCompiler):
        """Test constraint passing in quantifiers."""
        code1 = """
        predicate list_range_test() {
            ∀ (x: list[int]) :: (x == [1..5]) ==> (x == [1,2,3,4,5])
        }
        """

        code2 = """predicate set_intersect_test() {
            ∀ (x: set[int], y: set[int]) :: (x == {1..5} ∧ y == {1..3}) ==> (set_intersect(x, y) == {1..3})
        }
        """
        compiled_1 = compiler.compile(code1, entry_func="list_range_test")
        ctx = compiler.get_ctx()
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 5000)
        solver.add(compiled_1)
        result = solver.check()
        assert result == z3.sat
        compiled_2 = compiler.compile(code2, entry_func="set_intersect_test")
        ctx = compiler.get_ctx()
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 5000)
        solver.add(compiled_2)
        result = solver.check()
        assert result == z3.sat

    def test_char_range_to_z3(self, compiler: DSLCompiler):
        """Test Z3 translation for char ranges in list and set."""
        code = """
        predicate char_list_range_test() {
            ∀ (x: list[char]) :: (x == ['a'..'c']) ==> (x == ['a','b','c'])
        }

        predicate char_set_range_test() {
            ∀ (s: set[char]) :: (s == {'a'..'c'}) ==> (set_is_subset({'a','b','c'}, s))
        }
        """
        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx

        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 5000)
        solver.add(z3_expr)
        solver.assert_and_track(
            z3.Bool("char_list_range_test", ctx=ctx) == z3.BoolVal(True, ctx=ctx),
            "char_list_range_test",
        )
        solver.assert_and_track(
            z3.Bool("char_set_range_test", ctx=ctx) == z3.BoolVal(True, ctx=ctx),
            "char_set_range_test",
        )
        result = solver.check()

        assert result == z3.sat

    def test_var_declarations_in_functions(self, compiler: DSLCompiler):
        """Test variable declarations in function definitions."""
        code = """
        function test(x: int) -> (res: int) {
            var y = x + 1;
            var z = y * 2;
            ensure res == z;
        }
        """

        z3_expr = compiler.compile(code)
        ctx = compiler.ast_to_z3._ctx

        # Create a solver and add the constraints
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)

        # The function should be satisfiable
        result = solver.check()
        assert result == z3.sat

        # Test with specific values
        test_func = z3.Function("test", z3.IntSort(ctx=ctx), z3.IntSort(ctx=ctx))
        solver.add(test_func(5) == 12)  # y = 6, z = 12

        result = solver.check()
        assert result == z3.sat

    def test_var_declarations_with_complex_expressions(self, compiler: DSLCompiler):
        """Test variable declarations with complex expressions."""
        code = """
        function process_list(arr: list[int]) -> (res: bool) {
            var length = len(arr);
            var first = arr[0];
            var condition = length > 0 ∧ first > 10;
            ensure res == condition;
        }
        """

        z3_expr = compiler.compile(code, entry_func="process_list")
        ctx = compiler.ast_to_z3._ctx
        # Create a solver and add the constraints
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)

        # The function should be satisfiable
        result = solver.check()
        assert result == z3.sat

    def test_var_declarations_type_constraints(self, compiler: DSLCompiler):
        """Test that variable declarations create proper type constraints."""
        code = """
        function arithmetic(a: int, b: int) -> (res: int) {
            var addition = a + b;
            var multiplication = a * b;
            var difference = addition - multiplication;
            require a > 0 ∧ b > 0;
            ensure res == difference;
            ensure addition > 0;
            ensure multiplication >= 0;
        }
        """

        z3_expr = compiler.compile(code)
        ctx = compiler.ast_to_z3._ctx
        # Create a solver and add the constraints
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)

        # The function should be satisfiable
        result = solver.check()
        assert result == z3.sat, f"Solver failed with: {solver.reason_unknown()}"

        # Test specific case: a=3, b=2 -> sum=5, product=6, difference=-1
        test_func = z3.Function(
            "arithmetic", z3.IntSort(ctx=ctx), z3.IntSort(ctx=ctx), z3.IntSort(ctx=ctx)
        )
        solver.add(test_func(3, 2) == -1)

        result = solver.check()
        assert result == z3.sat

    def test_var_declarations_scoping(self, compiler: DSLCompiler):
        """Test variable declaration scoping and dependencies."""
        code = """
        function chain_operations(x: int) -> (res: int) {
            var a = x + 1;
            var b = a * 2;
            var c = b + a;
            var d = c - x;
            ensure res == d;
        }
        """

        z3_expr = compiler.compile(code)
        ctx = compiler.ast_to_z3._ctx
        # Create a solver and add the constraints
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 5000)
        solver.add(z3_expr)

        # The function should be satisfiable
        result = solver.check()
        assert result == z3.sat

        # Test specific case: x=5 -> a=6, b=12, c=18, d=13
        test_func = z3.Function(
            "chain_operations", z3.IntSort(ctx=ctx), z3.IntSort(ctx=ctx)
        )
        solver.add(test_func(5) == 13)

        result = solver.check()
        assert result == z3.sat

    def test_forward_references(self, compiler: DSLCompiler):
        """Test forward references between functions and predicates."""
        code = """
        function f(x: int) {
            g(x) + 1
        }

        function g(x: int) {
            x * 2
        }

        predicate P() {
            f(5) == 11 ∧ g(5) == 10
        }
        """

        spec = compiler.parse(code)

        # Type checking should show no errors
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        result = solver.check()

        # Should be satisfiable
        assert result == z3.sat, (
            f"Forward reference test failed: {solver.reason_unknown()}"
        )

    def test_mutual_recursion(self, compiler: DSLCompiler):
        """Test mutually recursive functions."""
        code = """
        function isEven(n: int) {
            if n == 0 then true else isOdd(n - 1)
        }

        function isOdd(n: int) {
            if n == 0 then false else isEven(n - 1)
        }

        predicate TestMutualRecursion() {
            isEven(4) ∧ ¬isEven(3) ∧ isOdd(3) ∧ ¬isOdd(4)
        }
        """

        z3_expr = compiler.compile(code, entry_func="TestMutualRecursion")
        ctx = compiler.get_ctx()
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        result = solver.check()

        assert result == z3.sat

    def test_tuple_construction(self, compiler: DSLCompiler):
        """Test tuple construction."""
        code = """
        function test() {
            (1, 2) == (1, 2)
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        solver.add(z3.Bool("test", ctx=ctx))
        result = solver.check()

        assert result == z3.sat

    def test_tuple_access(self, compiler: DSLCompiler):
        """Test tuple access."""
        code = """
        function test() {
            (1, 2)[0] == 1
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        solver.add(z3.Bool("test", ctx=ctx))
        result = solver.check()

        assert result == z3.sat

    def test_complex_tuple_access(self, compiler: DSLCompiler):
        """Test tuple access."""
        code = """
        function test() {
            ((1, 2), (1, 2, 3))[1][2] == 3
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        solver.add(z3.Bool("test", ctx=ctx))
        result = solver.check()

        assert result == z3.sat

    def test_char_literal(self, compiler: DSLCompiler):
        """Test char literals."""
        code = """
        function test() {
            'a'
        }
        predicate P() {
            test == 'a'
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        solver.add(z3.Bool("P", ctx=ctx))
        result = solver.check()

        assert result == z3.sat

    def test_int2real_and_real2int(self, compiler: DSLCompiler):
        """Test int2real and real2int."""
        code = """
        function test() {
            int2real(1) == 1.0 ∧ real2int(1.0) == 1
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec, entry_func="test")
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        result = solver.check()
        assert result == z3.sat

    def test_uppercase_lowercase_integration(self, compiler: DSLCompiler):
        """Ensure Z3 lowering for uppercase/lowercase works in integration flow."""
        code = """
        predicate P() {
            prefixof("ABC", uppercase("abcxyz")) ∧
            suffixof("xyz", lowercase("XYZ")) ∧
            contains(uppercase("aBc"), "ABC")
        }
        """
        spec = compiler.parse(code)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"
        z3_expr = compiler.to_z3(spec, entry_func="P")
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 2000)
        any_asserted = False
        for expr in z3_expr:
            expr_sort = expr.sort() if hasattr(expr, "sort") else None
            print("expr info:", type(expr), expr_sort)
            if isinstance(expr, bool):
                assert expr is True
            elif z3.is_bool(expr):
                print("adding expr:", expr, expr.sort())
                solver.add(expr)
                any_asserted = True
            else:
                raise AssertionError(f"Unexpected non-boolean constraint: {expr}")
        if any_asserted:
            result = solver.check()
            assert result == z3.sat, solver.reason_unknown()

    def test_abs_and_abs_real(self, compiler: DSLCompiler):
        """Test abs on int and abs_real on real in integration flow."""
        code = """
        function abs_int(x: int) {
            abs(x)
        }

        function abs_r(x: real) {
            abs_real(x)
        }

        predicate P() {
            abs_int(-5) == 5 ∧ abs_int(5) == 5 ∧ abs_r(-3.5) == 3.5 ∧ abs_r(2.0) == 2.0
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec, entry_func="P")
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 2000)
        solver.add(z3_expr)
        result = solver.check()
        assert result == z3.sat, solver.reason_unknown()

    def test_is_infinite_and_is_nan_fp(self):
        fp_compiler = DSLCompiler(real_encoding=RealEncodingMode.FLOATING_POINT)
        code = """
        predicate P() {
            is_infinite(Infinity) ∧ is_infinite(-Infinity) ∧ is_nan(nan)
        }
        """
        spec = fp_compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = fp_compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = fp_compiler.to_z3(spec, entry_func="P")
        assert z3_expr, "Expected at least one constraint"
        for expr in z3_expr:
            if isinstance(expr, bool):
                assert expr is True
            else:
                assert z3.is_bool(expr), f"Unexpected non-boolean constraint: {expr}"

    def test_membership(self, compiler: DSLCompiler):
        """Test membership."""
        code = """
        predicate test() {
            3 in [1..5] ∧ 3 in {1..5}
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 1000)
        solver.add(z3_expr)
        result = solver.check()
        assert result == z3.sat

    def test_list2set_semantics(self, compiler: DSLCompiler):
        """Integration test for list2set conversion only."""
        code = """
        predicate p1() {
            set_is_subset(list2set([1,2,2,3]), {1..5}) ∧ set_is_subset({1,2,3}, list2set([1,2,3]))
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec, entry_func="p1")
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 5000)
        solver.add(z3_expr)
        solver.assert_and_track(z3.Bool("p1", ctx=ctx), "p1")
        result = solver.check()
        assert result == z3.sat, solver.reason_unknown()

    def test_cardinality(self, compiler: DSLCompiler):
        code = """
        predicate test() {
            cardinality({1, 2, 3}) == 3
        }
        """
        spec = compiler.parse(code)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, errors
        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 2000)
        solver.add(z3_expr)
        solver.add(z3.Bool("test", ctx=ctx))
        assert solver.check() == z3.sat

    def test_rec_add_definition_local_constraints_predicate_unsat(
        self, compiler: DSLCompiler
    ):
        """RecAddDefinition must include local constraints for boolean predicates.

        The union size is bounded: |s ∪ s| <= |s| + |s| = 2|s|. If local constraints from
        set_union are dropped inside the recursive definition, the predicate could become SAT.
        With correct RecAddDefinition (including local constraints), it is UNSAT.
        """
        code = """
        predicate violates_union_size(s: set[int]) {
            cardinality(set_union(s, s)) > 2 * cardinality(s)
        }

        predicate SPEC() { violates_union_size({1, 2}) }
        """
        spec = compiler.parse(code)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, errors
        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 3000)
        solver.add(z3_expr)
        solver.add(z3.Bool("SPEC", ctx=ctx))
        assert solver.check() == z3.unsat

    def test_rec_add_definition_local_constraints_bool_function_unsat(
        self, compiler: DSLCompiler
    ):
        """RecAddDefinition must include local constraints for boolean-returning functions.

        Same scenario as the predicate case, but implemented as a function returning bool.
        Correct handling yields UNSAT.
        """
        code = """
        function violates_union_size_f(s: set[int]) {
            cardinality(set_union(s, s)) > 2 * cardinality(s)
        }

        predicate SPEC2() { violates_union_size_f({1, 2}) }
        """
        spec = compiler.parse(code)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, errors
        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 3000)
        solver.add(z3_expr)
        solver.add(z3.Bool("SPEC2", ctx=ctx))
        assert solver.check() == z3.unsat

    def test_explicit_map_literal_and_access(self, compiler: DSLCompiler):
        """Test explicit map literal parsing, typing, and Z3 translation."""
        code = """
        predicate map_literal_test() {
            var m: map[int, int] = map{ 1: 10, 2: 20 };
            m[1] == 10 ∧ m[2] == 20
        }

        function get(m: map[int, int], k: int) {
            m[k]
        }

        predicate map_access_test() {
            get(map{ 1: 10, 2: 20 }, 2) == 20
        }
        """

        spec = compiler.parse(code)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, f"Type checking failed with errors: {errors}"

        z3_expr = compiler.to_z3(spec)
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 5000)
        solver.add(z3_expr)
        solver.assert_and_track(
            z3.Bool("map_literal_test", ctx=ctx), "map_literal_test"
        )
        solver.assert_and_track(z3.Bool("map_access_test", ctx=ctx), "map_access_test")
        result = solver.check()
        assert result == z3.sat, solver.reason_unknown()

    def test_callsite_req_check(self, compiler: DSLCompiler):
        code = """
        function f(x: int) {
            require x < 0;
        }
        predicate P() { f(1) }
        """
        spec = compiler.parse(code)
        errors = compiler.type_check(spec)
        assert len(errors) == 0, errors
        z3_expr = compiler.to_z3(spec, entry_func="P")
        ctx = compiler.ast_to_z3._ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", 2000)
        solver.add(z3_expr)
        assert solver.check() == z3.unsat, solver
