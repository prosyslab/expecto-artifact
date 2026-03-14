import sys
from pathlib import Path

import pytest
import z3

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from src.DSL.compiler import DSLCompiler


class TestRecordLiterals:
    """Test that record literals work correctly."""

    def test_basic_record_literal(self):
        """Test basic record literal creation."""
        spec = """
        predicate test() {
            record{ name: "Alice", age: 30 } == record{ name: "Alice", age: 30 }
        }
        """
        compiler = DSLCompiler()
        result = compiler.compile(spec, entry_func="test")
        solver = z3.Solver(ctx=compiler.get_ctx())
        solver.add(result)
        assert solver.check() == z3.sat

    def test_record_literal_with_dot_access(self):
        """Test record literal with dot notation access."""
        spec = """
        predicate test() {
            record{ x: 5, y: 10 }.x == 5
        }
        """
        compiler = DSLCompiler()
        result = compiler.compile(spec, entry_func="test")
        solver = z3.Solver(ctx=compiler.get_ctx())
        solver.add(result)
        assert solver.check() == z3.sat

    def test_record_literal_with_bracket_access(self):
        """Test record literal with bracket notation access."""
        spec = """
        predicate test() {
            record{ x: 5, y: 10 }["x"] == 5
        }
        """
        compiler = DSLCompiler()
        result = compiler.compile(spec, entry_func="test")
        solver = z3.Solver(ctx=compiler.get_ctx())
        solver.add(result)
        assert solver.check() == z3.sat

    def test_nested_record_literals(self):
        """Test nested record literals."""
        spec = """
        predicate test() {
            record{ inner: record{ value: 42 } }.inner.value == 42
        }
        """
        compiler = DSLCompiler()
        result = compiler.compile(spec, entry_func="test")
        solver = z3.Solver(ctx=compiler.get_ctx())
        solver.add(result)
        assert solver.check() == z3.sat

    def test_record_literal_type_inference(self):
        """Test that record literal types are inferred correctly."""
        spec = """
        predicate test(r: record[name: string, age: int]) {
            r == record{ name: "Bob", age: 25 }
        }
        """
        compiler = DSLCompiler()
        result = compiler.compile(spec, entry_func="test")
        solver = z3.Solver(ctx=compiler.get_ctx())
        solver.add(result)
        assert solver.check() == z3.sat

    def test_record_literal_missing_field_error(self):
        """Test that missing fields in record literal cause error."""
        spec = """
        predicate test() {
            record{ name: "Alice" } == record{ name: "Alice", age: 30 }
        }
        """
        compiler = DSLCompiler()
        # Should raise TypeError due to type mismatch
        with pytest.raises(TypeError) as exc_info:
            compiler.compile(spec, entry_func="test")
        assert "type mismatch" in str(exc_info.value).lower()

    def test_record_literal_extra_field_error(self):
        """Test that extra fields in record literal cause error."""
        spec = """
        predicate test() {
            record{ name: "Alice", age: 30, extra: "field" } == record{ name: "Alice", age: 30 }
        }
        """
        compiler = DSLCompiler()
        # Should raise TypeError due to extra field
        with pytest.raises(TypeError) as exc_info:
            compiler.compile(spec)
        assert (
            "extra" in str(exc_info.value).lower()
            or "field" in str(exc_info.value).lower()
        )

    def test_record_literal_type_mismatch_error(self):
        """Test that type mismatches in record literal cause error."""
        spec = """
        predicate test() {
            record{ name: "Alice", age: "thirty" } == record{ name: "Alice", age: 30 }
        }
        """
        compiler = DSLCompiler()
        # Should raise TypeError due to type mismatch
        with pytest.raises(TypeError) as exc_info:
            compiler.compile(spec)
        assert "type" in str(exc_info.value).lower()

    def test_record_literal_unparsing(self):
        """Test that record literals are properly unparsed."""
        spec = """
        predicate test() {
            record{ name: "Alice", age: 30 } == record{ name: "Alice", age: 30 }
        }
        """
        compiler = DSLCompiler()
        ast = compiler.parse(spec)

        # Unparse and check it contains record literal syntax
        from src.DSL.ast_unparse import unparse

        unparsed = unparse(ast)
        assert "record{" in unparsed
        assert 'name: "Alice"' in unparsed
        assert "age: 30" in unparsed

    def test_record_literal_with_z3(self):
        """Test that record literals work with Z3 translation."""
        spec = """
        predicate test() {
            record{ x: 5, y: 10 }.x + record{ x: 3, y: 7 }.y == 17
        }
        """
        compiler = DSLCompiler()
        result = compiler.compile(spec)
        # Should compile and type check without errors
        assert result is not None

    def test_empty_record_literal_error(self):
        """Test that empty record literals cause error."""
        spec = """
        predicate test() {
            record{} == record{ name: "Alice" }
        }
        """
        compiler = DSLCompiler()
        # Should raise TypeError due to type mismatch
        with pytest.raises(TypeError) as exc_info:
            compiler.compile(spec)
        assert "type mismatch" in str(exc_info.value).lower()

    def test_record_literal_field_order_independence(self):
        """Test that field order doesn't matter for record equality."""
        spec = """
        predicate test() {
            record{ name: "Alice", age: 30 } == record{ age: 30, name: "Alice" }
        }
        """
        compiler = DSLCompiler()
        result = compiler.compile(spec)
        # Should compile without errors (field order shouldn't matter)
        assert result is not None
