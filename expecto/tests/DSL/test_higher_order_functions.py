"""Tests for higher-order functions with Hindley-Milner type inference."""

import sys
from pathlib import Path

import pytest

# Add root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.ast_builder import Specification
from src.DSL.compiler import DSLCompiler


class TestHigherOrderFunctions:
    """Test higher-order functions type inference."""

    @pytest.fixture
    def compiler(self):
        return DSLCompiler()

    def test_map_function_basic(self, compiler: DSLCompiler):
        """Test basic map function usage."""
        code = """
        predicate test_map() {
            map(lambda (x: int) = x + 1, [1, 2, 3]) == [2, 3, 4]
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0

    def test_map_function_polymorphic(self, compiler: DSLCompiler):
        """Test map function with different types."""
        code = """
        predicate test_map_polymorphic() {
            map(lambda (x) = x * 2, [1, 2, 3]) == [2, 4, 6] ∧
            map(lambda (b) = ¬b, [true, false]) == [false, true]
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0

    def test_filter_function(self, compiler: DSLCompiler):
        """Test filter function."""
        code = """
        predicate test_filter() {
            filter(lambda (x) = x > 0, [1, -2, 3, -4]) == [1, 3]
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0

    def test_fold_function(self, compiler: DSLCompiler):
        """Test fold function."""
        code = """
        predicate test_fold() {
            fold(lambda (acc, x) = acc + x, 0, [1, 2, 3, 4]) == 10
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0

    def test_all_function(self, compiler: DSLCompiler):
        """Test all function."""
        code = """
        predicate test_all() {
            all(lambda (x) = x > 0, [1, 2, 3]) == true ∧
            all(lambda (x) = x > 0, [1, -2, 3]) == false
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0

    def test_any_function(self, compiler: DSLCompiler):
        """Test any function."""
        code = """
        predicate test_any() {
            any(lambda (x) = x > 0, [-1, -2, 3]) == true ∧
            any(lambda (x) = x > 0, [-1, -2, -3]) == false
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0

    def test_composed_higher_order_functions(self, compiler: DSLCompiler):
        """Test composition of higher-order functions."""
        code = """
        predicate test_composition() {
            filter(lambda (x) = x > 0, 
                   map(lambda (y) = y - 2, [1, 2, 3, 4])) == [1, 2]
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0

    def test_higher_order_function_with_user_defined_function(
        self, compiler: DSLCompiler
    ):
        """Test higher-order functions with user-defined functions."""
        code = """
        function is_positive(x: int) -> (res: bool) {
            ensure res == (x > 0);
        }

        function double(x: int) -> (res: int) {
            ensure res == x * 2;
        }

        predicate test_user_functions() {
            all(is_positive, [1, 2, 3]) == true ∧
            map(double, [1, 2, 3]) == [2, 4, 6]
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0

    def test_map_type_error(self, compiler: DSLCompiler):
        """Test map function with type error."""
        code = """
        predicate test_map_error() {
            map(lambda (x: int) = x + 1, [true, false])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        # Should have type error: trying to apply int->int function to bool list
        assert len(errors) > 0
        assert any("type mismatch" in str(error).lower() for error in errors)

    def test_filter_type_error(self, compiler: DSLCompiler):
        """Test filter function with type error."""
        code = """
        predicate test_filter_error() {
            filter(lambda (x: int) = x, [1, 2, 3])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        # Should have type error: filter predicate must return bool
        assert len(errors) > 0

    def test_fold_type_error(self, compiler: DSLCompiler):
        """Test fold function with type error."""
        code = """
        predicate test_fold_error() {
            fold(lambda (x: int, y: int) = x + y, "hello", [1, 2, 3])
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        # Should have type error: accumulator type mismatch
        assert len(errors) > 0

    def test_nested_map_inference(self, compiler: DSLCompiler):
        """Test nested map with complex type inference."""
        code = """
        predicate test_nested_map() {
            map(lambda (lst: list[int]) = map(lambda (x: int) = x * 2, lst), 
                [[1, 2], [3, 4]]) == [[2, 4], [6, 8]]
        }
        """
        spec = compiler.parse(code)
        assert isinstance(spec, Specification)
        errors = compiler.type_check(spec)
        assert len(errors) == 0
