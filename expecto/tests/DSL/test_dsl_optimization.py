"""Test cases for DSL optimizer functionality."""

import sys
from pathlib import Path
from typing import cast

import pytest

# Add root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.ast_builder import ASTBuilder
from src.DSL.dsl_ast import (
    BoolLiteral,
    Comparisons,
    ExplicitList,
    ExplicitMultiset,
    ExplicitSet,
    ForallExpr,
    FuncCall,
    FunctionDef,
    Identifier,
    IfExpr,
    NoneLiteral,
    NumberLiteral,
    PredicateDef,
    SomeExpr,
    Specification,
)
from src.DSL.dsl_optimizer import DSLOptimizer, FiniteCollectionQuantifierElimination
from src.DSL.grammar import parser as lark_parser


class TestDSLOptimizer:
    """Test cases for DSL AST optimization."""

    @pytest.fixture
    def parser(self):
        """Create parser with grammar."""

        def _parser(code: str):
            parsed = lark_parser(code)
            return ASTBuilder().transform(parsed)

        return _parser

    @pytest.fixture
    def optimizer(self):
        return DSLOptimizer()

    # Shared helper for quantifier detection
    def _contains_forall(self, node):
        from src.DSL.dsl_ast import ForallExpr

        if isinstance(node, ForallExpr):
            return True
        for _, val in vars(node).items():
            if isinstance(val, list):
                for item in val:
                    if hasattr(item, "pos") and self._contains_forall(item):
                        return True
            elif hasattr(val, "pos"):
                if self._contains_forall(val):
                    return True
        return False

    # Shared helper for existential quantifier detection
    def _contains_exists(self, node):
        from src.DSL.dsl_ast import ExistsExpr

        if isinstance(node, ExistsExpr):
            return True
        for _, val in vars(node).items():
            if isinstance(val, list):
                for item in val:
                    if hasattr(item, "pos") and self._contains_exists(item):
                        return True
            elif hasattr(val, "pos"):
                if self._contains_exists(val):
                    return True
        return False

    def test_basic_implicit_to_explicit_optimization(self, parser, optimizer):
        """Test basic function optimization from implicit to explicit form."""

        # DSL code with implicit function definition
        code = """
        function f(x: int) -> (res: int) {
            ensure res == x + 1;
        }
        """

        # Parse into AST
        spec = parser(code)
        assert isinstance(spec, Specification)

        # Apply optimization
        optimized_spec = optimizer.optimize(spec)

        # Verify the optimization
        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert optimized_func.name == "f"
        assert len(optimized_func.ensures) == 0, (
            "Ensures should be empty after optimization"
        )
        assert optimized_func.body is not None, "Body should be set after optimization"
        assert optimized_func.return_val is not None, "Return val should exist"
        assert optimized_func.return_val.name == "return_val", (
            "Return val should be renamed to 'return_val'"
        )

    def test_reverse_equality_optimization(self, parser, optimizer):
        """Test optimization when equality is reversed: expr == return_var."""

        code = """
        function multiply_by_two(x: int) -> (result: int) {
            ensure x * 2 == result;
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        # Verify optimization
        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert len(optimized_func.ensures) == 0
        assert optimized_func.body is not None

    def test_complex_expression_optimization(self, parser, optimizer):
        """Test optimization with more complex expressions."""

        code = """
        function complex_function(x: int, y: int) -> (result: int) {
            ensure result == (x + y) * 2;
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        # Verify optimization
        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert len(optimized_func.ensures) == 0
        assert optimized_func.body is not None

    def test_no_optimization_multiple_ensures(self, parser, optimizer):
        """Test that functions with multiple ensures are not optimized."""

        code = """
        function multiple_ensures(x: int) -> (res: int) {
            ensure res > 0;
            ensure res == x;
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert len(optimized_func.ensures) == 2
        assert optimized_func.body is None

    def test_no_optimization_no_return_var(self, parser, optimizer):
        """Test that functions without return variable are not optimized."""

        code = """
        function no_return(x: int) {
            require x > 0;
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        # Verify no optimization occurred
        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert optimized_func.body is None

    def test_no_optimization_already_explicit(self, parser, optimizer):
        """Test that functions with existing body are not optimized."""

        code = """
        function already_explicit(x: int) -> (res: int) {
            x + 1
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        # Verify no optimization occurred
        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert optimized_func.body is not None, "Existing body should be preserved"

    def test_no_optimization_wrong_operator(self, parser, optimizer):
        """Test that ensures with non-equality operators are not optimized."""

        code = """
        function wrong_operator(x: int) -> (res: int) {
            ensure res != x;
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        # Verify no optimization occurred
        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert len(optimized_func.ensures) == 1
        assert optimized_func.body is None

    def test_no_optimization_no_return_var_in_equality(self, parser, optimizer):
        """Test that ensures not involving the return variable are not optimized."""

        code = """
        function no_return_var_ref(x: int) -> (res: int) {
            ensure x == 5;
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        # Verify no optimization occurred
        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert len(optimized_func.ensures) == 1
        assert optimized_func.body is None

    def test_optimization_with_var_declarations(self, parser, optimizer):
        """Test optimization with variable declarations present."""

        code = """
        function with_vars(x: int) -> (result: int) {
            var temp = x + 1;
            var doubled = temp * 2;
            ensure result == doubled - 1;
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        # Verify optimization
        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert len(optimized_func.ensures) == 0
        assert optimized_func.body is not None
        assert len(optimized_func.var_decls) == 2, (
            "Variable declarations should be preserved"
        )

    def test_optimization_with_requires_and_ensures(self, parser, optimizer):
        """Test optimization with requires statements present."""

        code = """
        function with_requires(x: int) -> (result: int) {
            require x > 0;
            require x < 100;
            ensure result == x * x;
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        # Verify optimization
        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert len(optimized_func.ensures) == 0
        assert optimized_func.body is not None
        assert len(optimized_func.requires) == 2, (
            "Require statements should be preserved"
        )

    def test_mixed_declarations_optimization(self, parser, optimizer):
        """Test optimization with both functions and predicates."""

        code = """
        predicate is_positive(x: int) {
            x > 0
        }

        function square(x: int) -> (result: int) {
            ensure result == x * x;
        }

        predicate is_even(x: int) {
            x % 2 == 0
        }

        function double(x: int) -> (result: int) {
            require x > 0;
            ensure result == x * 2;
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        # Verify that predicates are unchanged and functions are optimized
        assert len(optimized_spec.declarations) == 4

        # First predicate should be unchanged
        pred1 = optimized_spec.declarations[0]
        assert pred1.name == "is_positive"

        # First function should be optimized
        func1 = optimized_spec.declarations[1]
        assert isinstance(func1, FunctionDef)
        assert func1.name == "square"
        assert len(func1.ensures) == 0
        assert func1.body is not None

        # Second predicate should be unchanged
        pred2 = optimized_spec.declarations[2]
        assert pred2.name == "is_even"

        # Second function should be optimized
        func2 = optimized_spec.declarations[3]
        assert isinstance(func2, FunctionDef)
        assert func2.name == "double"
        assert len(func2.ensures) == 0
        assert func2.body is not None
        assert len(func2.requires) == 1, "Requires should be preserved"

    def test_nested_expressions_optimization(self, parser, optimizer):
        """Test optimization with deeply nested expressions."""

        code = """
        function nested_expr(a: int, b: int, c: int) -> (result: int) {
            ensure result == ((a + b) * c) - (a * (b + c));
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        # Verify optimization preserves complex expression structure
        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert len(optimized_func.ensures) == 0
        assert optimized_func.body is not None

    def test_multiple_ensures_are_not_collapsed(self, parser, optimizer):
        """Multiple ensures should remain implicit to preserve semantics."""

        code = """
        function multiple_ensures(x: int) -> (result: int) {
            ensure result >= 0;
            ensure result <= 100;
            ensure result == x * x;
        }
        """

        spec = parser(code)
        optimized_spec = optimizer.optimize(spec)

        # Verify optimization
        optimized_func = optimized_spec.declarations[0]
        assert isinstance(optimized_func, FunctionDef)
        assert len(optimized_func.ensures) == 3
        assert optimized_func.body is None

    def test_constant_implicit_sort_contract_is_folded(self, parser, optimizer):
        code = """
        function sort(arr: list[int]) -> (res: list[int]) {
            ensure is_sorted(res) ∧ is_permutation(res, arr);
        }

        predicate is_sorted(arr: list[int]) {
            ∀ (i: int) :: 0 <= i < len(arr) - 1 ==> arr[i] <= arr[i + 1]
        }

        predicate is_permutation(l1: list[int], l2: list[int]) {
            list2multiset(l1) == list2multiset(l2)
        }

        predicate spec() {
            sort([1, 0, 1]) == [0, 1, 1]
        }
        """

        spec = parser(code)
        optimized = optimizer.optimize(spec)
        pred = optimized.declarations[-1]
        assert isinstance(pred, PredicateDef)
        assert isinstance(pred.body, BoolLiteral)
        assert pred.body.value is True

    # New tests for constant propagation and quantifier unrolling
    def test_constant_propagation_len_and_index(self, parser, optimizer):
        code = """
        function f() {
            len("abc") == 3
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        func = optimized.declarations[0]
        assert isinstance(func, FunctionDef)
        assert isinstance(func.body, BoolLiteral)
        assert func.body.value is True

        code2 = """
        function g() {
            "abc"[1] == 'b'
        }
        """
        spec2 = parser(code2)
        optimized2 = optimizer.optimize(spec2)

        func2 = optimized2.declarations[0]
        assert isinstance(func2.body, BoolLiteral)
        assert func2.body.value is True

    def test_constant_propagation_higher_order_functions(self, parser, optimizer):
        code = """
        function map_direct() {
            map(lambda (x: int) = x * 2, [1, 2, 3])
        }

        function map_bool() {
            map(lambda (x: int) = x + 1, [1, 2]) == [2, 3]
        }

        function map_i_direct() {
            map_i(lambda (i: int, x: int) = x + i, [1, 2, 3])
        }

        function filter_bool() {
            filter(lambda (x: int) = x % 2 == 0, [1, 2, 3, 4]) == [2, 4]
        }

        function fold_bool() {
            fold(lambda (acc: int, x: int) = acc + x, 0, [1, 2, 3]) == 6
        }

        function fold_i_bool() {
            fold_i(lambda (i: int, acc: int, x: int) = acc + i + x, 0, [1, 2]) == 4
        }

        function map_over_list_substr() {
            sum(map(lambda (d: int) = if 1 >= 2 * d then d else 3 * d - 1, substr([1, 0, 0], 0, 2))) == 2
        }
        """

        spec = parser(code)
        optimized = optimizer.optimize(spec)

        map_direct = optimized.declarations[0]
        assert isinstance(map_direct, FunctionDef)
        assert isinstance(map_direct.body, ExplicitList)
        map_vals = map_direct.body.elements
        assert all(isinstance(v, NumberLiteral) for v in map_vals)
        assert [cast(NumberLiteral, v).value for v in map_vals] == [2, 4, 6]

        map_bool = optimized.declarations[1]
        assert isinstance(map_bool.body, BoolLiteral)
        assert map_bool.body.value is True

        map_i_direct = optimized.declarations[2]
        assert isinstance(map_i_direct.body, ExplicitList)
        map_i_vals = map_i_direct.body.elements
        assert all(isinstance(v, NumberLiteral) for v in map_i_vals)
        assert [cast(NumberLiteral, v).value for v in map_i_vals] == [1, 3, 5]

        filter_bool = optimized.declarations[3]
        assert isinstance(filter_bool.body, BoolLiteral)
        assert filter_bool.body.value is True

        fold_bool = optimized.declarations[4]
        assert isinstance(fold_bool.body, BoolLiteral)
        assert fold_bool.body.value is True

        fold_i_bool = optimized.declarations[5]
        assert isinstance(fold_i_bool.body, BoolLiteral)
        assert fold_i_bool.body.value is True

        map_over_list_substr = optimized.declarations[6]
        assert isinstance(map_over_list_substr.body, BoolLiteral)
        assert map_over_list_substr.body.value is True

    def test_quantifier_unrolling(self, parser, optimizer):
        code = """
        predicate P() {
            ∀ (i: int) :: (0 <= i ∧ i < 3) ==> (i == 0 \\/ i == 1 \\/ i == 2)
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)
        pred = optimized.declarations[0]
        assert not self._contains_forall(pred)

        code2 = """
        predicate Q() {
            ∀ (i: int) :: (0 <= i ∧ i < len("abc")) ==> ("abc"[i] == "abc"[i])
        }
        """
        spec2 = parser(code2)
        optimized2 = optimizer.optimize(spec2)
        pred2 = optimized2.declarations[0]
        assert not self._contains_forall(pred2)

    def test_qe_set_subset_enumeration(self, parser, optimizer):
        # ∀ s subset of constant set -> enumerate all subsets and remove quantifier
        code = """
        predicate P() {
            ∀ (s: set[int]) :: set_is_subset(s, {1,2}) ==> (set_is_subset(s, {1,2}))
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)
        pred = optimized.declarations[0]
        assert not self._contains_forall(pred)

    def test_qe_list_contains_enumeration(self, parser, optimizer):
        # ∀ l: contains(const_list, l) -> enumerate all sublists
        code = """
        predicate Q() {
            ∀ (l: list[int]) :: contains([1,2,3], l) ==> (contains([1,2,3], l))
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)
        pred = optimized.declarations[0]
        assert not self._contains_forall(pred)

    def test_qe_range_set_and_list(self, parser, optimizer):
        # Range-based finite domains also enumerate
        code = """
        predicate R() {
            ∀ (s: set[int]) :: set_is_subset(s, {1..3}) ==> (set_is_subset(s, {1..3}))
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)
        pred = optimized.declarations[0]
        assert not self._contains_forall(pred)

        code2 = """
        predicate S() {
            ∀ (l: list[int]) :: contains([1..3], l) ==> (contains([1..3], l))
        }
        """
        spec2 = parser(code2)
        optimized2 = optimizer.optimize(spec2)
        pred2 = optimized2.declarations[0]
        assert not self._contains_forall(pred2)

    def test_multi_var_exists_unrolling(self, parser, optimizer):
        code = """
        predicate E() {
            ∃ (i: int, j: int) ::
                ((0 <= i ∧ i < j ∧ j < 3) ∧ ("aba"[i] != "aba"[j]))
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)
        pred = optimized.declarations[0]
        assert not self._contains_exists(pred)

        assert isinstance(pred.body, BoolLiteral)

    def test_multi_var_forall_unrolling(self, parser, optimizer):
        code = """
        predicate F() {
            ∀ (i: int, j: int) ::
                (0 <= i ∧ i < j ∧ j < 3) ==> ("abc"[i] != "abc"[j])
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)
        pred = optimized.declarations[0]
        assert not self._contains_forall(pred)
        assert isinstance(pred.body, BoolLiteral)

    def test_three_var_exists_unrolling(self, parser, optimizer):
        code = """
        predicate E3() {
            ∃ (i: int, j: int, k: int) ::
                ((0 <= i ∧ i < j ∧ j < k ∧ k < 4) ∧ i == j == k)
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)
        pred = optimized.declarations[0]
        assert not self._contains_exists(pred)
        assert isinstance(pred.body, BoolLiteral)

    def test_interprocedural_specialization_drives_unrolling(self, parser, optimizer):
        code = """
        predicate Q(s: string) {
            ∀ (i: int) :: (0 <= i ∧ i < len(s)) ==> (s[i] == 'a')
        }

        predicate S() {
            Q("hello")
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)
        pred_S = optimized.declarations[1]
        assert not self._contains_forall(pred_S)

    def test_constant_propagation_arithmetic(self, parser, optimizer):
        code = """
        function h() {
            1 + 2 * 3 == 7
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        func = optimized.declarations[0]
        assert isinstance(func, FunctionDef)
        assert isinstance(func.body, BoolLiteral)
        assert func.body.value is True

    def test_constant_propagation_string_builtins(self, parser, optimizer):
        code = """
        function s1() { concat("ab","c") == "abc" }
        function s2() { contains("abc","bc") }
        function s3() { substr("abcdef", 2, 3) == "cde" }
        function s4() { indexof("ababa","ba", 0) == 1 }
        function s5() { replace("abcabc","ab","xy") == "xycxyc" }
        function s6() { prefixof("ab","abc") }
        function s7() { suffixof("bc","abc") }
        function s8() { int2str(123) == "123" }
        function s9() { str2int("456") == 456 }
        function s10() { str2int("12x") == -1 }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        # All functions should fold to True
        for i in range(10):
            func = optimized.declarations[i]
            assert isinstance(func, FunctionDef)
            assert isinstance(func.body, BoolLiteral)
            assert func.body.value is True

    def test_constant_propagation_aggregate_and_math_builtins(self, parser, optimizer):
        code = """
        function a1() { sum([1,2,3]) == 6 }
        function a2() { product([2,3,4]) == 24 }
        function a3() { max([2,5,1]) == 5 }
        function a4() { min([2,5,1]) == 1 }
        function a5() { average([2,4,6]) == 4 }
        function a6() { mean([2,4,6]) == 4 }
        function a7() { abs(-5) == 5 }
        function a8() { abs_real(-5.0) == 5.0 }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        for i in range(8):
            func = optimized.declarations[i]
            assert isinstance(func, FunctionDef)
            assert isinstance(func.body, BoolLiteral)
            assert func.body.value is True

    def test_constant_propagation_set_builtins(self, parser, optimizer):
        code = """
        function t1() { set_is_subset(list2set([1,2,2]), {1,2}) }
        function t2() { set_is_empty({}) }
        function t3() { set_is_member(2, {1,2,3}) }
        function t4() { set_is_subset({1,2}, {1,2,3}) }
        function t5() { set_is_subset({1,2}, set_union({1}, {2})) }
        function t6() { set_is_subset(set_intersect({1,2}, {2,3}), {2}) }
        function t7() { set_is_empty(set_difference({1,2}, {1,2})) }
        function t8() { set_is_member(3, set_add({1,2}, 3)) }
        function t9() { set_is_empty(set_del({1}, 1)) }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        for i in range(9):
            func = optimized.declarations[i]
            assert isinstance(func, FunctionDef)
            assert isinstance(func.body, BoolLiteral)
            assert func.body.value is True

    def test_constant_propagation_multiset_builtins(self, parser, optimizer):
        """Test constant propagation for multiset operations."""
        code = """
        function t1() { list2multiset([1,2,2,3]) }
        function t2() { 2 in list2multiset([1,2,2,3]) }
        function t3() { list2multiset([1,2,2,3]) == list2multiset([1,2,2,3]) }
        function t4() { list2multiset([1,2,2,3]) != list2multiset([1,2,3,3]) }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        # Test that list2multiset with constant list gets optimized to ExplicitMultiset
        func1 = optimized.declarations[0]
        assert isinstance(func1, FunctionDef)
        assert isinstance(func1.body, ExplicitMultiset)
        assert len(func1.body.elements) == 4  # [1,2,2,3] -> 4 elements

        # Test that membership operations get optimized to boolean literals
        func2 = optimized.declarations[1]
        assert isinstance(func2, FunctionDef)
        assert isinstance(func2.body, BoolLiteral)
        assert func2.body.value is True  # 2 is in [1,2,2,3]

        # Test that equality operations get optimized to boolean literals
        func3 = optimized.declarations[2]
        assert isinstance(func3, FunctionDef)
        assert isinstance(func3.body, BoolLiteral)
        assert func3.body.value is True  # Same multisets are equal

        func4 = optimized.declarations[3]
        assert isinstance(func4, FunctionDef)
        assert isinstance(func4.body, BoolLiteral)
        assert func4.body.value is True  # Different multisets are not equal

    def test_constant_propagation_map_builtins(self, parser, optimizer):
        code = """
        function t1() { map_get(map_add(map_add(map{1:2}, 1, 3), 2, 4), 1) == 3 }
        function t2() { map_get(map_add(map_add(map{1:2}, 1, 3), 2, 4), 2) == 4 }
        function t3() { map_get(map_add(map_add(map{1:2}, 1, 3), 2, 4), 3) == None }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)
        for i in range(3):
            func = optimized.declarations[i]
            assert isinstance(func, FunctionDef)
            assert isinstance(func.body, BoolLiteral)
            assert func.body.value is True

    def test_constant_propagation_tuple_builtins(self, parser, optimizer):
        code = """
        function t1() { (1,2,3)[1] == 2 }
        function t2() { (1,2,3)[2] == 3 }
        function t3() { (1,2,3)[0] == 1 }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)
        for i in range(3):
            func = optimized.declarations[i]
            assert isinstance(func, FunctionDef)
            assert isinstance(func.body, BoolLiteral)
            assert func.body.value is True

    def test_constant_propagation_boolean(self, parser, optimizer):
        # ∧, ∨ identities simplify operands but keep comparisons structure
        code = """
        function b1() {
            (true ∧ (1 == 1)) <==> (false ∨ (1 == 1))
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        func = optimized.declarations[0]
        assert isinstance(func, FunctionDef)
        assert isinstance(func.body, BoolLiteral)
        assert func.body.value is True

        # ==> identities
        code2 = """
        function b2() {
            (false ==> (1 == 0)) ∧ (true ==> (1 == 1))
        }
        """
        spec2 = parser(code2)
        optimized2 = optimizer.optimize(spec2)
        func2 = optimized2.declarations[0]
        # Left becomes true, right becomes (1==1), whole ∧ -> (1==1)
        assert isinstance(func2, FunctionDef)
        assert isinstance(func2.body, BoolLiteral)
        assert func2.body.value is True

    def test_constant_propagation_comparisons(self, parser, optimizer):
        # Arithmetic within comparisons should fold on both sides
        code = """
        function c1() {
            (1 + 2) < (2 + 2)
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        func = optimized.declarations[0]
        assert isinstance(func, FunctionDef)
        # All comparisons constant -> BoolLiteral
        assert isinstance(func.body, BoolLiteral)
        assert func.body.value is True

        # Equality sides fold too
        code2 = """
        function c2() {
            (2 * 2) == (1 + 3)
        }
        """
        spec2 = parser(code2)
        optimized2 = optimizer.optimize(spec2)
        func2 = optimized2.declarations[0]
        assert isinstance(func2.body, BoolLiteral)
        assert func2.body.value is True

    def test_constant_propagation_option_builtins(self, parser, optimizer):
        code = """
        function s() { is_some(None) }
        function n() { is_none(None) }
        function u() { unwrap(None) }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        f_s = optimized.declarations[0]
        assert isinstance(f_s, FunctionDef)
        assert isinstance(f_s.body, BoolLiteral)
        assert f_s.body.value is False

        f_n = optimized.declarations[1]
        assert isinstance(f_n, FunctionDef)
        assert isinstance(f_n.body, BoolLiteral)
        assert f_n.body.value is True

        f_u = optimized.declarations[2]
        assert isinstance(f_u, FunctionDef)
        # unwrap(None) is not folded to a constant; keep as call
        assert isinstance(f_u.body, FuncCall)
        assert isinstance(f_u.body.func, Identifier) and f_u.body.func.name == "unwrap"
        assert len(f_u.body.args) == 1 and isinstance(f_u.body.args[0], NoneLiteral)

    def test_list2set_option_literals_preserved(self, parser, optimizer):
        code = """
        function some_set() { list2set([some(1), some(2), some(1)]) }
        function none_set() { list2set([None, None]) }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        some_set = optimized.declarations[0]
        assert isinstance(some_set, FunctionDef)
        assert isinstance(some_set.body, ExplicitSet)
        assert len(some_set.body.elements) == 2

        first = some_set.body.elements[0]
        second = some_set.body.elements[1]
        assert isinstance(first, SomeExpr)
        assert isinstance(second, SomeExpr)
        assert isinstance(first.value, NumberLiteral)
        assert first.value.value == 1
        assert isinstance(second.value, NumberLiteral)
        assert second.value.value == 2

        none_set = optimized.declarations[1]
        assert isinstance(none_set, FunctionDef)
        assert isinstance(none_set.body, ExplicitSet)
        assert len(none_set.body.elements) == 1
        assert isinstance(none_set.body.elements[0], NoneLiteral)

    def test_constant_multiset_and_set_equality_are_order_insensitive(
        self, parser, optimizer
    ):
        code = """
        function multiset_eq() {
            list2multiset([0, 1, 1]) == list2multiset([1, 0, 1])
        }
        function multiset_neq() {
            list2multiset([0, 1, 1]) != list2multiset([1, 0, 1])
        }
        function multiset_diff() {
            list2multiset([0, 1, 1]) == list2multiset([0, 0, 1])
        }
        function set_eq() {
            list2set([1, 2]) == list2set([2, 1])
        }
        function set_neq() {
            list2set([1, 2]) != list2set([2, 1])
        }
        function set_dup_eq() {
            list2set([1, 2, 2]) == list2set([2, 1])
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        bodies = [decl.body for decl in optimized.declarations]
        assert all(isinstance(body, BoolLiteral) for body in bodies)

        assert cast(BoolLiteral, bodies[0]).value is True
        assert cast(BoolLiteral, bodies[1]).value is False
        assert cast(BoolLiteral, bodies[2]).value is False
        assert cast(BoolLiteral, bodies[3]).value is True
        assert cast(BoolLiteral, bodies[4]).value is False
        assert cast(BoolLiteral, bodies[5]).value is True

    def test_qe_subset_threshold_skips_eager_enumeration(self, parser, monkeypatch):
        code = """
        predicate P() {
            ∀ (s: set[int]) :: set_is_subset(s, {1,2,3,4,5,6,7}) ==> true
        }
        """
        spec = parser(code)
        qelim = FiniteCollectionQuantifierElimination(unroll_threshold=64)

        def _raise_if_called(*_args, **_kwargs):
            raise AssertionError("subset enumeration should be skipped above threshold")

        monkeypatch.setattr(qelim, "_enumerate_subsets", _raise_if_called)
        optimized = qelim.transform(spec)
        assert isinstance(optimized, Specification)

        pred = optimized.declarations[0]
        assert self._contains_forall(pred)

    def test_equality_constraint_propagation_respects_scope(self, parser, optimizer):
        # Substitution from guard/cond must not leak into inner bound scopes
        code = """
        function scope_eq_prop(x: int) {
            if (x == 1) then (∀ (x: int) :: x == 2) else (x == 3)
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        func = optimized.declarations[0]
        assert isinstance(func, FunctionDef)
        assert isinstance(func.body, IfExpr)

        then_branch = func.body.then_branch
        else_branch = func.body.else_branch

        assert isinstance(then_branch, ForallExpr)
        assert not isinstance(then_branch.satisfies_expr, BoolLiteral)
        if isinstance(else_branch, Comparisons):
            assert len(else_branch.comparisons) == 1
            comp = else_branch.comparisons[0]
            from src.DSL.dsl_ast import Identifier

            assert (isinstance(comp.left, Identifier) and comp.left.name == "x") or (
                isinstance(comp.right, Identifier) and comp.right.name == "x"
            )
        else:
            assert not isinstance(else_branch, BoolLiteral)

    def test_equality_constraint_propagation_in_implication(self, parser, optimizer):
        code = """
        function imp(x: int) {
            (x == 1) ==> (x + 2 == 3)
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        func = optimized.declarations[0]
        assert isinstance(func, FunctionDef)
        # After propagation and constant folding: (x==1) ==> True  => True
        assert isinstance(func.body, BoolLiteral)
        assert func.body.value is True

    def test_equality_constraint_propagation_in_conjunction(self, parser, optimizer):
        code = """
        function conj(x: int) {
            (x == 1) ∧ (x == 1)
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        func = optimized.declarations[0]
        assert isinstance(func, FunctionDef)
        # After propagation and folding: left ∧ True => left, so final body is x == 1
        assert isinstance(func.body, Comparisons)
        comp = func.body.comparisons[0]
        assert isinstance(comp.left, Identifier) and comp.left.name == "x"
        assert isinstance(comp.right, NumberLiteral) and comp.right.value == 1

    def test_equality_constraint_propagation_in_if(self, parser, optimizer):
        code = """
        function iff(x: int) {
            if (x == 1) then (x == 1) else (x == 2)
        }
        """
        spec = parser(code)
        optimized = optimizer.optimize(spec)

        func = optimized.declarations[0]
        assert isinstance(func, FunctionDef)
        assert isinstance(func.body, IfExpr)

        # Then branch becomes 1 == 1, which folds to True
        then_b = func.body.then_branch
        assert isinstance(then_b, BoolLiteral) and then_b.value is True

        # Else branch remains x == 2 (no substitution into else)
        else_b = func.body.else_branch
        assert isinstance(else_b, Comparisons)
        ecomp = else_b.comparisons[0]
        assert isinstance(ecomp.left, Identifier) and ecomp.left.name == "x"
        assert isinstance(ecomp.right, NumberLiteral) and ecomp.right.value == 2
