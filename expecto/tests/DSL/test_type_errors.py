"""Comprehensive tests for type error detection in the DSL type checker."""

import sys
from pathlib import Path

import pytest

# Add root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.ast_builder import Specification
from src.DSL.compiler import DSLCompiler


class TestTypeErrorDetection:
    """Test comprehensive type error detection capabilities."""

    @pytest.fixture
    def compiler(self):
        return DSLCompiler()

    def assert_type_error(self, errors, expected_keyword):
        """Assert that there's a type error containing the expected keyword."""
        assert len(errors) > 0, (
            f"Expected type error containing '{expected_keyword}', but got no errors"
        )
        error_messages = [str(error).lower() for error in errors]
        assert any(expected_keyword.lower() in msg for msg in error_messages), (
            f"Expected error containing '{expected_keyword}', but got: {error_messages}"
        )

    # === Higher-Order Function Type Errors ===

    def test_map_wrong_function_signature(self, compiler: DSLCompiler):
        """Test map with wrong function signature."""
        code = """
        predicate test_map_wrong_sig() {
            map(lambda (x: int, y: int) = x + y, [1, 2, 3])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_map_wrong_list_type(self, compiler: DSLCompiler):
        """Test map with incompatible list element type."""
        code = """
        predicate test_map_wrong_list() {
            map(lambda (x: string) = x + "!", [1, 2, 3])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_filter_non_boolean_predicate(self, compiler: DSLCompiler):
        """Test filter with non-boolean returning predicate."""
        code = """
        predicate test_filter_non_bool() {
            filter(lambda (x: int) = x + 1, [1, 2, 3])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_fold_wrong_accumulator_type(self, compiler: DSLCompiler):
        """Test fold with wrong accumulator type."""
        code = """
        predicate test_fold_wrong_acc() {
            fold(lambda (acc: string, x: int) = acc + x, "hello", [1, 2, 3])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_fold_inconsistent_function_types(self, compiler: DSLCompiler):
        """Test fold with inconsistent function signature."""
        code = """
        predicate test_fold_inconsistent() {
            fold(lambda (x: int, y: string) = x + 1, 0, [1, 2, 3])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_higher_order_with_non_function(self, compiler: DSLCompiler):
        """Test higher-order function called with non-function argument."""
        code = """
        predicate test_non_function_arg() {
            map(42, [1, 2, 3])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    # === Function Definition and Call Errors ===

    def test_function_wrong_return_type(self, compiler: DSLCompiler):
        """Test function returning wrong type."""
        code = """
        function get_number() -> (ret: int) {
            ensure ret == "not a number";
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_function_multiple_inconsistent_returns(self, compiler: DSLCompiler):
        """Test function with multiple inconsistent return types."""
        code = """
        function inconsistent_returns(x: int) -> (ret: int) {
            ensure ret == if (x > 0) then x else "negative";
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "if branches have incompatible types")

    def test_function_call_wrong_arg_count(self, compiler: DSLCompiler):
        """Test function call with wrong argument count."""
        code = """
        function add(x: int, y: int) -> (ret: int) {
            ensure ret == x + y;
        }
        predicate test_wrong_args() {
            add(1, 2, 3) == 6
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "trying to call add")

    def test_function_call_wrong_arg_types(self, compiler: DSLCompiler):
        """Test function call with wrong argument types."""
        code = """
        function greet(name: string) -> (ret: string) {
            ensure ret == "Hello " + name;
        }
        predicate test_wrong_arg_type() {
            greet(42) == "Hello 42"
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_call_undefined_function(self, compiler: DSLCompiler):
        """Test calling undefined function."""
        code = """
        predicate test_undefined_func() {
            undefined_function(1, 2) == 3
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "undefined")

    def test_call_non_function_value(self, compiler: DSLCompiler):
        """Test calling a non-function value."""
        code = """
        predicate test_call_non_function(x: int) {
            x(1, 2) == 3
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(
            errors, "trying to call x: int with arguments (int, int)"
        )

    # === Arithmetic and Logical Operation Errors ===

    def test_arithmetic_with_non_numeric(self, compiler: DSLCompiler):
        """Test arithmetic operations with non-numeric types."""
        code = """
        predicate test_bad_arithmetic() {
            "hello" + 42 == "hello42"
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_logical_with_non_boolean(self, compiler: DSLCompiler):
        """Test logical operations with non-boolean types."""
        code = """
        predicate test_bad_logical(x: int) {
            x ∧ true
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "bool")

    def test_comparison_type_mismatch(self, compiler: DSLCompiler):
        """Test comparison with incompatible types."""
        code = """
        predicate test_bad_comparison() {
            "hello" < 42
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_unary_operator_wrong_type(self, compiler: DSLCompiler):
        """Test unary operators with wrong types."""
        code = """
        predicate test_bad_unary() {
            -"hello" == "olleh"
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "numeric")

    def test_negation_non_boolean(self, compiler: DSLCompiler):
        """Test logical negation with non-boolean."""
        code = """
        predicate test_bad_negation() {
            ¬42
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "bool")

    # === Collection Type Errors ===

    def test_list_heterogeneous_elements(self, compiler: DSLCompiler):
        """Test list with mixed element types."""
        code = """
        predicate test_mixed_list() {
            [1, "hello", true] == [1, 2, 3]
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "collection elements must have the same type")

    def test_set_heterogeneous_elements(self, compiler: DSLCompiler):
        """Test set with mixed element types."""
        code = """
        predicate test_mixed_set() {
            {1, "hello", true} == {1, "hello", true}
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "collection elements must have the same type")

    def test_list_access_wrong_index_type(self, compiler: DSLCompiler):
        """Test list access with non-integer index."""
        code = """
        predicate test_bad_index(lst: list[int], str_idx: string) {
            lst[str_idx] == 1
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "int")

    def test_list_access_non_list(self, compiler: DSLCompiler):
        """Test indexing a non-list value."""
        code = """
        predicate test_index_non_list(num: int) {
            num[0] == 4
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "We can only index")

    def test_len_non_collection(self, compiler: DSLCompiler):
        """Test len() with non-collection argument."""
        code = """
        predicate test_len_non_collection() {
            len(42) == 2
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    # === Conditional Expression Errors ===

    def test_if_non_boolean_condition(self, compiler: DSLCompiler):
        """Test if expression with non-boolean condition."""
        code = """
        predicate test_if_bad_condition() {
            if 42 then "yes" else "no"
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "bool")

    def test_if_incompatible_branches(self, compiler: DSLCompiler):
        """Test if expression with incompatible branch types."""
        code = """
        predicate test_if_bad_branches() {
            if true then 42 else "hello"
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "incompatible")

    # === Lambda Expression Errors ===

    def test_lambda_undefined_variable(self, compiler: DSLCompiler):
        """Test lambda using undefined variable."""
        code = """
        predicate test_lambda_undefined() {
            map(lambda (x: int) = x + undefined_var, [1, 2, 3])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "undefined")

    # === Quantifier Errors ===

    def test_forall_non_boolean_body(self, compiler: DSLCompiler):
        """Test forall with non-boolean body."""
        code = """
        predicate test_forall_bad_body(lst: list[int]) {
            ∀ (x: int) :: (x + 1)
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "bool")

    def test_exists_non_boolean_body(self, compiler: DSLCompiler):
        """Test exists with non-boolean body."""
        code = """
        predicate test_exists_bad_body(lst: list[int]) {
            ∃ (x: int) :: (x * 2)
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "bool")

    # === Variable and Scope Errors ===

    def test_undefined_variable(self, compiler: DSLCompiler):
        """Test using undefined variable."""
        code = """
        predicate test_undefined_var() {
            undefined_variable > 0
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "undefined")

    # === Complex Nested Type Errors ===

    def test_nested_function_calls_error(self, compiler: DSLCompiler):
        """Test error in nested function calls."""
        code = """
        function outer(x: int) -> (ret: int) {
            ensure ret == x * 2;
        }
        function inner(y: string) -> (ret: string) {
            ensure ret == y + "!";
        }
        predicate test_nested_error() {
            outer(inner("hello")) == 42
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_nested_higher_order_error(self, compiler: DSLCompiler):
        """Test error in nested higher-order function calls."""
        code = """
        predicate test_nested_hof_error() {
            map(lambda (x: list[int]) = filter(lambda (y: string) = y > 0, x), 
                [[1, 2], [3, 4]])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_complex_type_mismatch_in_collection(self, compiler: DSLCompiler):
        """Test complex type mismatch in nested collections."""
        code = """
        predicate test_complex_collection_error() {
            [[1, 2], ["hello", "world"]] == [[1, 2], [3, 4]]
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "collection elements must have the same type")

    # === Predicate-Specific Errors ===

    def test_predicate_non_boolean_body(self, compiler: DSLCompiler):
        """Test predicate with non-boolean body."""
        code = """
        predicate bad_predicate() {
            42 + 1
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "bool")

    # === Edge Cases ===

    def test_recursive_type_error(self, compiler: DSLCompiler):
        """Test recursive function with type error."""
        code = """
        function recursive_bad(n: int) -> (ret: int) {
            ensure ret == if (n <= 0) then "bad" else recursive_bad(n - 1) + 1;
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_higher_order_with_wrong_arity(self, compiler: DSLCompiler):
        """Test higher-order function with wrong arity lambda."""
        code = """
        predicate test_wrong_arity() {
            fold(lambda (x: int) = x * 2, 0, [1, 2, 3])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "mismatch")

    def test_type_inference(self, compiler: DSLCompiler):
        """Test type inference."""
        code = """
        predicate P(x, y) {
            x + 1 ==> y
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        self.assert_type_error(errors, "operation ==> requires boolean type")

    def test_diff_type_tuple_access(self, compiler: DSLCompiler):
        """Test different type of tuple access."""
        code = """
        predicate P(x: int, y: string) {
            (x, y)[0] == x
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0

    def test_nested_tuple_access(self, compiler: DSLCompiler):
        """Test nested tuple access."""
        code = """
        function P(x: int, y: string) -> (res: bool) {
            ensure res == (((x, y), (x, y, y, x))[0][0] == x)
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0
