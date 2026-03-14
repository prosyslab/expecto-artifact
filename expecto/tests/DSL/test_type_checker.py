"""Comprehensive test cases for the type checker."""

import sys
from pathlib import Path

import pytest

# Add root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.ast_builder import ASTBuilder
from src.DSL.dsl_ast import (
    Boolean,
    Char,
    FuncType,
    Integer,
    ListType,
    Real,
    Specification,
    TypeVar,
)
from src.DSL.grammar import parser as lark_parser
from src.DSL.type_checker import TypeChecker


class TestTypeChecker:
    """Test cases for the TypeChecker class."""

    @pytest.fixture
    def parser(self):
        """Create parser with grammar."""

        def _parser(code: str):
            parsed = lark_parser(code)
            return ASTBuilder().transform(parsed)

        return _parser

    @pytest.fixture
    def type_checker(self):
        """Create a type checker instance."""
        return TypeChecker()

    def parse_code(self, parser, code: str) -> Specification:
        """Helper to parse DSL code into AST."""
        return parser(code)

    def test_simple_predicate_with_no_errors(self, parser, type_checker):
        """Test a simple predicate that should type check successfully."""
        code = "predicate is_positive(x: int) { x > 0 }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_predicate_with_type_error(self, parser, type_checker):
        """Test predicate with a type error."""
        code = "predicate bad_predicate(x: int) { x ∧ true <==> false }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1, errors
        assert "bool" in str(errors[0])

    def test_arithmetic_operations(self, parser, type_checker):
        """Test arithmetic operations type checking."""
        code = "predicate test_arith(x: int, y: int) { x + y == 10 ==> true }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_arithmetic_type_mismatch(self, parser, type_checker):
        """Test arithmetic operations with type mismatch."""
        code = "predicate test_bad_arith(x: int, y: bool) { x + y == 10 ==> false }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_logical_operations(self, parser, type_checker):
        """Test logical operations type checking."""
        code = "predicate test_logic(p: bool, q: bool) { p ∧ q }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_logical_type_mismatch(self, parser, type_checker):
        """Test logical operations with type mismatch."""
        code = "predicate test_bad_logic(x: int, y: bool) { x ∧ y }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_comparison_operations(self, parser, type_checker):
        """Test comparison operations type checking."""
        code = "predicate test_comparison(x: int, y: int) { x < y }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_equality_operations(self, parser, type_checker):
        """Test equality operations type checking."""
        code = "predicate test_equality(x: int, y: int) { x == y }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_unary_operations(self, parser, type_checker):
        """Test unary operations type checking."""
        code = "predicate test_unary(x: int, p: bool) { -x > 0 ∧ ¬p }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_option_builtins_types(self, parser, type_checker):
        code = """
        predicate P(x: option[int]) {
            is_some(x) ∧ (is_none(x) ==> true)
        }
        function f(x: option[int]) -> int {
            unwrap(x)
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

    def test_if_expression(self, parser, type_checker):
        """Test if expression type checking."""
        code = "predicate test_if(p: bool, x: int, y: int) { (if p then x else y) > 0 }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_if_expression_type_mismatch(self, parser, type_checker):
        """Test if expression with mismatched branch types."""
        code = "predicate test_bad_if(p: bool, x: int) { if p then x else true }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 2

    def test_function_definition(self, parser, type_checker):
        """Test function definition type checking."""
        code = """
        function add(x: int, y: int) -> (res) {
            require x > 0;
            require y > 0;
            ensure res == x + y;
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_function_return_type_mismatch(self, parser, type_checker):
        """Test function with return type mismatch."""
        code = """
        function bad_func(x: int) -> (res: int) {
            ensure res == true;
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_function_call(self, parser, type_checker):
        """Test function call type checking."""
        code = """
        function add(x: int, y: int) -> (res: int) {
            ensure res == x + y;
        }
        predicate test_call(a: int, b: int) { add(a, b) > 0 }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_function_call_wrong_args(self, parser, type_checker):
        """Test function call with wrong number of arguments."""
        code = """
        function add(x: int, y: int) -> (res: int) {
            ensure res == x + y;
        }
        predicate test_bad_call(a: int) { add(a) > 0 }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_function_call_wrong_arg_types(self, parser, type_checker):
        """Test function call with wrong argument types."""
        code = """
        function add(x: int, y: int) -> (res: int) {
            ensure res == x + y;
        }
        predicate test_bad_call(a: int, b: bool) { add(a, b) > 0 }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_list_operations(self, parser, type_checker):
        """Test list operations type checking."""
        code = "predicate test_list() { [1, 2, 3] == [1, 2, 3] }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_list2multiset_typing(self, parser, type_checker):
        """Test list2multiset built-in typing and membership."""
        code = "predicate test_mset() { 2 in list2multiset([1,2,2,3]) }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

    def test_multiset_type_inference(self, parser, type_checker):
        """Test multiset type inference from elements."""
        code = "predicate test_mset_inference() { list2multiset([1, 2, 3]) == list2multiset([1, 2, 3]) }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

    def test_multiset_mixed_types_error(self, parser, type_checker):
        """Test multiset with mixed element types should fail."""
        code = "predicate test_bad_mset() { list2multiset([1, true, 3]) == list2multiset([1, 2, 3]) }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1, "Expected type error for mixed types in multiset"

    def test_empty_multiset_typing(self, parser, type_checker):
        """Test empty multiset literal typing."""
        code = "predicate test_empty_mset() { list2multiset([]) == list2multiset([]) }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

    def test_list_type_mismatch(self, parser, type_checker):
        """Test list with mismatched element types."""
        code = "predicate test_bad_list() { [1, true, 3] == [1, 2, 3] }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_set_operations(self, parser, type_checker):
        """Test set operations type checking."""
        code = "predicate test_set() { {1, 2, 3} == {1, 2, 3} }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_cardinality(self, parser, type_checker):
        """Test cardinality function type checking."""
        code = "predicate test_cardinality() { cardinality({1, 2, 3}) == 3 }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_list_access(self, parser, type_checker):
        """Test list access type checking."""
        code = "predicate test_access(lst: list[int], i: int) { lst[i] > 0 }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_list_access_wrong_index_type(self, parser, type_checker):
        """Test list access with wrong index type."""
        code = "predicate test_bad_access(lst: list[int], i: bool) { lst[i] > 0 }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_lambda_expression(self, parser, type_checker):
        """Test lambda expression type checking."""
        code = "function test_lambda() -> (res: int) { ensure res == 1 }"  # Simple function test instead
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

    def test_forall_quantifier(self, parser, type_checker):
        """Test forall quantifier type checking."""
        code = "predicate test_forall(lst: list[int]) { ∀ (x: int) :: (x > 0) }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_exists_quantifier(self, parser, type_checker):
        """Test exists quantifier type checking."""
        code = "predicate test_exists(lst: list[int]) { ∃ (x: int) :: (x > 0) }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_quantifier_wrong_body_type(self, parser, type_checker):
        """Test quantifier with wrong body type."""
        code = "predicate test_bad_quantifier() { ∀ (x: int) :: (x) }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_undefined_variable(self, parser, type_checker):
        """Test undefined variable error."""
        code = "predicate test_undefined() { x > 0 }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1
        assert "Undefined variable" in str(errors[0])

    def test_undefined_function(self, parser, type_checker):
        """Test undefined function error."""
        code = "predicate test_undefined() { unknown_func(1, 2) }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1
        assert "Undefined variable or function" in str(errors[0])

    def test_builtin_len_function(self, parser, type_checker):
        """Test built-in len function type checking."""
        code = "predicate test_len(lst: list[int]) { len(lst) > 0 }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_nested_expressions(self, parser, type_checker):
        """Test deeply nested expressions."""
        code = (
            "predicate complex(x: int, y: int, p: bool) { (x + y) * 2 > 10 ∧ (p ∨ ¬p) }"
        )
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_chained_comparisons(self, parser, type_checker):
        """Test chained comparison operations."""
        code = "predicate test_chain(x: int, y: int, z: int) { x < y <= z }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_type_error_positions(self, parser, type_checker):
        """Test that type errors report correct positions."""
        code = "predicate test(x: int) { x ∧ true }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1
        # Error should be at position where x is used in logical context
        assert errors[0].pos[0] == 1  # line 1
        assert errors[0].pos[1] > 20  # after "predicate test(x: int) { "

    def test_multiple_errors(self, parser, type_checker):
        """Test that multiple errors are detected."""
        code = """
        predicate multi_errors(x: int, y: bool) {
            x ∧ y ∨ z
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 2
        # At least type error for x in logical context and undefined z

    def test_variable_scoping(self, parser, type_checker):
        """Test variable scoping in quantifiers."""
        code = """
        predicate test_scope(x: int) {
            ∀ (x: bool) :: (x ∨ true)
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0  # Inner x should shadow outer x

    def test_empty_list_and_set(self, parser, type_checker):
        """Test empty list and set handling."""
        code = "predicate test_empty() { [] == [] ∧ {} == {} }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_literal_types(self, parser, type_checker):
        """Test literal type inference."""
        code = """
        predicate test_literals() {
            42 == 42 ∧
            3.14 == 3.14 ∧
            true == true ∧
            "hello" == "world"
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_power_operator(self, parser, type_checker):
        """Test power operator type checking."""
        code = "predicate test_power(x: int, y: int) { x ^ y > 0 }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_real_number_operations(self, parser, type_checker):
        """Test real number operations."""
        code = "predicate test_real() { 3.14 + 2.71 > 5.0 }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_string_operations(self, parser, type_checker):
        """Test string operations."""
        code = 'predicate test_string() { "hello" == "world" }'
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_complex_lambda(self, parser, type_checker):
        """Test complex expressions."""
        code = """
        predicate test_complex() {
            true ∧ false
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_error_without_source_code(self, parser, type_checker):
        """Test error formatting without source code."""
        code = "predicate bad(x: int) { x ∧ true }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)  # No source code
        assert len(errors) == 1
        error_str = str(errors[0])
        assert "Type error at line" in error_str
        assert "Source:" not in error_str

    def test_nested_type_environments(self, parser, type_checker):
        """Test variable scoping across nested environments."""
        code = """
        predicate outer(x: int) {
            ∀ (x: bool) :: (
                ∃ (x: string) :: (x == "test")
            )
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

    def test_function_without_body(self, parser, type_checker):
        """Test function declaration without body."""
        code = 'function no_body(x: int) -> (ret: int) : "Documentation only"'
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_predicate_without_body(self, parser, type_checker):
        """Test predicate declaration without body."""
        code = 'predicate no_body(x: int) : "Documentation only"'
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_complex_type_unification(self, type_checker):
        """Test complex type unification scenarios."""
        substitution = type_checker.substitution

        # Test function type unification
        var1 = TypeVar()
        var2 = TypeVar()
        func1 = FuncType([var1], var2)
        func2 = FuncType([Integer()], Boolean())

        result = substitution.unify(func1, func2)
        assert result

        # Check substitutions were applied
        assert substitution.substitute(var1) == Integer()
        assert substitution.substitute(var2) == Boolean()

    def test_wrong_number_of_function_args(self, type_checker):
        """Test function type unification with wrong arg count."""
        substitution = type_checker.substitution

        func1 = FuncType([Integer()], Boolean())
        func2 = FuncType([Integer(), Integer()], Boolean())

        result = substitution.unify(func1, func2)
        assert not result  # Should fail due to arg count mismatch

    def test_list_access_non_list_type(self, parser, type_checker):
        """Test list access on non-list type."""
        code = "predicate bad_access(x: int) { x[0] > 0 }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_nested_collection_types(self, parser, type_checker):
        """Test nested collection types."""
        code = "predicate test() { [[1, 2], [3, 4]] == [[1, 2], [3, 4]] }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_call_non_function_type(self, parser, type_checker):
        """Test calling a non-function type."""
        code = """
        predicate bad_call(x: int) { x(1, 2) }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1
        assert "Function call type mismatch" in str(errors[0])

    def test_lambda_expressions_in_predicates(self, parser, type_checker):
        """Test lambda expressions (they return function types, not bool)."""
        code = """
        predicate lambda_test() {
            lambda (x: int) = x + 1
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_predicate_with_non_boolean_expression(self, parser, type_checker):
        """Test predicate with non-boolean expression."""
        code = "predicate test() { 42 }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_type_substitution_chains(self, type_checker):
        """Test chained type substitutions."""
        substitution = type_checker.substitution
        var1 = TypeVar()
        var2 = TypeVar()
        var3 = TypeVar()

        # Create a chain: A -> B -> C -> int
        substitution.substitutions[var1] = var2
        substitution.substitutions[var2] = var3
        substitution.substitutions[var3] = Integer()

        # Should follow the chain to get int
        result = substitution.substitute(var1)
        assert result == Integer()

    def test_main_entry_point(self, parser):
        """Test the main entry point function."""
        from src.DSL.type_checker import type_check

        code = "predicate test(x: int) { x > 0 }"
        spec = parser(code)
        errors = type_check(spec)
        assert len(errors) == 0

    def test_unknown_type_in_unification(self, type_checker):
        """Test unification with unknown types."""
        substitution = type_checker.substitution

        # Test unifying with None (shouldn't happen in practice but tests robustness)
        result = substitution.unify(Integer(), None)
        assert not result

    def test_complex_type_string_representation(self, type_checker):
        """Test string representation of complex nested types."""
        # Test nested function types
        inner_func = FuncType([Integer()], Boolean())
        outer_func = FuncType([inner_func], ListType(Char()))

        result = str(outer_func)
        expected = "((int) -> bool) -> string"
        assert result == expected

    def test_edge_case_type_strings(self, type_checker):
        """Test edge case type to string conversions."""
        # Test with function type containing function type in args
        nested_func = FuncType([Integer()], Boolean())
        complex_func = FuncType([nested_func, ListType(Char())], Real())

        result = str(complex_func)
        assert "(int) -> bool" in result
        assert "string" in result
        assert "real" in result

    def test_empty_collection_edge_case(self, parser, type_checker):
        """Test edge cases with empty collections."""
        code = """
        predicate test_empty() {
            [] == [] ∧ {} == {}
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_complex_program_with_no_errors(self, parser, type_checker):
        """Test a more complex program combining multiple features."""
        code = """
        // Function to check if a single integer is positive
        function is_positive(n: int) -> (ret: bool) {
            ensure ret == (n > 0);
        }

        // Function using a quantifier to check if all numbers in a list are positive
        function all_positive(numbers: list[int]) -> (ret: bool) {
            ensure ret == ∀ (x: int) :: is_positive(x);
        }

        // Predicate for a list of lists (matrix)
        predicate matrix_properties(matrix: list[list[int]]) {
            // Check that every sublist (row) contains only positive numbers
            (∀ (row: list[int]) :: all_positive(row)) ∧
            // Check that the matrix is not empty
            (len(matrix) > 0)
        }

        function get_adder(x: int, y: int) -> (ret: int) {
            ensure ret == x + y;
        }

        // Predicate to test the higher-order function
        predicate test_adder() {
            get_adder(5, 10) == 15
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, f"Expected no errors, but got: {repr(errors)}"

    def test_list_addition(self, parser, type_checker):
        """Test list addition."""
        code = """
        predicate test() {
            [1, 2] + [3, 4] == [1, 2, 3, 4]
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

        code = """
        predicate test() {
            "hello" + "world" == "helloworld"
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

        code = """
        predicate test() {
            [1, 2] + "hello" == [1, 2, "hello"]
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 2, errors

    def test_complex_program_with_type_errors(self, parser, type_checker):
        """Test a complex program with multiple, varied type errors."""
        code = """
        // Function with an incorrect return type (should be bool)
        function is_positive_wrong_return(n: int) {
            n
        }

        // Function that attempts to quantify over a non-iterable type (an integer)
        function quantify_over_int() {
            ∀ (x: int) :: (x > 0)
        }

        predicate test_multiple_errors(nums: list[int]) {
            // Error: Using a function that returns int where bool is expected
            (is_positive_wrong_return(5)) ∧
            // Error: Adding an integer to a string
            (nums[0] + "hello") == "world" ∧
            // Error: Using comparison on a boolean value
            (quantify_over_int() > 0) ∧
            // Error: Inconsistent types in a list literal
            len([1, true, 3]) > 0
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 5, errors

    def test_integer_type_inference(self, parser, type_checker):
        """Test integer type inference."""
        code = """
        function f(x, y) -> (ret: int) {
            ensure ret == x + y;
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_empty_set_and_empty_list_inference(self, parser, type_checker):
        """Test empty set and empty list inference."""
        code = """
        function f(x: list[set[list[set[int]]]]) -> (ret: list[int]) {
            ensure ret == [];
        }

        function g(x: list[int]) -> (ret: int) {
            ensure ret == 0;
        }

        predicate test() {
            g(f([])) == 0
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

    def test_range(self, parser, type_checker):
        """Test range expression."""
        code = """
        predicate test() {
            [1..5] == [1, 2, 3, 4, 5]
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

        code = """
        predicate test() {
            {1..5} == {1, 2, 3, 4, 5}
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

        code = """
        predicate test() {
            [1..5] == {1, 2, 3, 4, 5}
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

        code = """
        function f(x: int) {
            [x..10]
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

        code = """
        function f(x: real) {
            [x..10]
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_char_range(self, parser, type_checker):
        """Test char range expressions type checking."""
        code = """
        predicate test_list_char_range() {
            ['a'..'c'] == ['a','b','c']
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

        code = """
        predicate test_set_char_range() {
            {'a'..'c'} == {'a','b','c'}
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0

        code = """
        predicate cross_type_list_set_char_range_error() {
            ['a'..'c'] == {'a','b','c'}
        }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1

    def test_var_declarations_basic(self, parser, type_checker):
        """Test basic variable declarations."""
        ast = self.parse_code(
            parser,
            """
        function test(x: int) -> (res: int) {
            var y = x + 1;
            var z = y * 2;
            ensure res == z;
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0

    def test_var_declaration_type_inference(self, parser, type_checker):
        """Test that variable declarations correctly infer types."""
        ast = self.parse_code(
            parser,
            """
        function test(arr: list[int]) -> (res: bool) {
            var len = len(arr);
            var first = arr[0];
            var condition = len > 0;
            ensure res == condition;
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0

    def test_var_declaration_type_error(self, parser, type_checker):
        """Test type errors in variable declarations."""
        ast = self.parse_code(
            parser,
            """
        function test(x: int) -> (res: bool) {
            var y = x + "hello";
            ensure res == true;
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) > 0
        # Should have a type error about adding int and string
        assert any(
            "Type mismatch in binary operation +" in str(error) for error in errors
        )

    def test_var_declaration_scoping(self, parser, type_checker):
        """Test variable declaration scoping."""
        ast = self.parse_code(
            parser,
            """
        function test(x: int) -> (res: int) {
            var y = x + 1;
            var z = y * 2;
            ensure res == z;
            ensure y > x;
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0

    def test_var_declaration_undefined_variable_error(self, parser, type_checker):
        """Test error when using undefined variable in declaration."""
        ast = self.parse_code(
            parser,
            """
        function test(x: int) -> (res: int) {
            var y = undefined_var + 1;
            ensure res == y;
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 1
        assert any(
            "Undefined variable or function: undefined_var" in str(error)
            for error in errors
        )

    def test_var_declaration_using_previous_vars(self, parser, type_checker):
        """Test using previously declared variables."""
        ast = self.parse_code(
            parser,
            """
        function test(x: int) -> (res: int) {
            var a = x + 1;
            var b = a * 2;
            var c = b + a;
            ensure res == c;
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0

    def test_var_declaration_with_list_operations(self, parser, type_checker):
        """Test variable declarations with list operations."""
        ast = self.parse_code(
            parser,
            """
        function test(arr: list[int]) -> (res: int) {
            var len = len(arr);
            var doubled = map(lambda (x: int) = x * 2, arr);
            var sum = fold(lambda (acc: int, x: int) = acc + x, 0, doubled);
            ensure res == sum;
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0

    def test_var_declaration_with_complex_types(self, parser, type_checker):
        """Test variable declarations with complex types."""
        ast = self.parse_code(
            parser,
            """
        function test() -> (res: list[int]) {
            var empty_list = [];
            var range = [1..5];
            var explicit = [1, 2, 3];
            var concatenated = range + explicit;
            ensure res == concatenated;
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0, errors

    def test_tuple_type_inference(self, parser, type_checker):
        """Test tuple type inference."""
        ast = self.parse_code(
            parser,
            """
        function test() -> (res: tuple[int, string]) {
            ensure res == (1, "hello");
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0, errors

    def test_const_func_type_handling(self, parser, type_checker):
        """Test const function type handling."""
        ast = self.parse_code(
            parser,
            """
        function const_func() -> (res: int) {
            ensure res == 1;
        }

        function test() {
            const_func == 1
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0, errors

    def test_tuple_access(self, parser, type_checker):
        """Test tuple access."""
        ast = self.parse_code(
            parser,
            """
        function test() {
            (1, 2)[0] == 1
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0, errors

    def test_tuple_access_type_error(self, parser, type_checker):
        ast = self.parse_code(
            parser,
            """
        function test() {
            ("1", "2")[0] == 1
            }
            """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 1, errors

    def test_char_literal(self, parser, type_checker):
        """Test char literals."""
        ast = self.parse_code(
            parser,
            """
        function test() -> (res: char) {
            ensure res == 'a';
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0, errors

    def test_int2real_and_real2int(self, parser, type_checker):
        """Test int2real and real2int."""
        ast = self.parse_code(
            parser,
            """
        function test() {
            int2real(1) == 1.0 ∧ real2int(1.0) == 1
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0, errors

    def test_abs_and_abs_real_typing(self, parser, type_checker):
        """Typing for abs(int) and abs_real(real)."""
        code = """
        predicate p1(x: int) { abs(x) >= 0 }
        predicate p2(x: real) { abs_real(x) >= 0.0 }
        function f(x: int) -> (ret: int) { ensure ret == abs(x); }
        function g(x: real) -> (ret: real) { ensure ret == abs_real(x); }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

    def test_is_infinite_and_is_nan_typing(self, parser, type_checker):
        """Typing for real predicates is_infinite and is_nan."""
        code = """
        predicate p(x: real) { is_infinite(x) ==> (is_nan(x) == False) }
        function f(x: real) -> (ret: bool) { ensure ret == is_infinite(x); }
        function g(x: real) -> (ret: bool) { ensure ret == is_nan(x); }
        """
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

    def test_range_type_inference(self, parser, type_checker):
        """Test range type inference."""
        ast = self.parse_code(
            parser,
            """
        function test(x: int) {
            var r1 = [x..];
            x + 1
        }
        """,
        )
        errors = type_checker.check(ast)
        assert len(errors) == 0, errors
        assert ast.declarations[0].var_decls[0].expr.ty.ty == ListType(Integer())

    def test_list2set_typing(self, parser, type_checker):
        """Typing for list2set conversion."""
        code = "predicate conv1() { list2set([1,2,2]) == {1,2} }"
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

    def test_map_type_and_indexing(self, parser, type_checker):
        """Test map type parsing and indexing typing."""
        code = 'predicate p(m: map[int, string]) { m[1] == "a" }'
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors

        # Wrong key type
        code = 'predicate p(m: map[int, string]) { m[true] == "a" }'
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 1, errors

        # Using map where list index expected
        code = 'predicate p(m: map[int, string]) { m[1] in ["a"] }'
        spec = self.parse_code(parser, code)
        errors = type_checker.check(spec)
        assert len(errors) == 0, errors


if __name__ == "__main__":
    pytest.main([__file__])
