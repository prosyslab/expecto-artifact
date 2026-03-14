"""Test dot notation for record field access."""

import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))
from src.DSL.compiler import DSLCompiler
from src.DSL.dsl_ast import FieldAccess


class TestDotNotation:
    """Test that dot notation works for record field access."""

    def test_basic_dot_notation(self):
        """Test basic dot notation for record field access."""
        spec = """
        predicate test(r: record[name: string, age: int]) {
            r.name == "Alice" and r.age == 30
        }
        """
        compiler = DSLCompiler()
        result = compiler.compile(spec)

        # Compilation should succeed
        assert result is not None

        # Parse to check AST structure
        ast = compiler.parse(spec)
        field_accesses = [node for node in ast if isinstance(node, FieldAccess)]
        assert len(field_accesses) == 2

    def test_nested_record_dot_notation(self):
        """Test dot notation with nested records."""
        spec = """
        predicate test(r: record[inner: record[value: int]]) {
            r.inner.value == 42
        }
        """
        compiler = DSLCompiler()
        result = compiler.compile(spec)
        # Should compile without errors
        assert result is not None

    def test_dot_notation_with_z3(self):
        """Test that dot notation works with Z3 translation."""
        spec = """
        predicate test(r: record[x: int, y: int]) {
            r.x + r.y == 10
        }
        """
        compiler = DSLCompiler()
        result = compiler.compile(spec)
        # Should compile and type check without errors
        assert result is not None

    def test_dot_notation_type_error(self):
        """Test that dot notation gives proper error for non-existent field."""
        spec = """
        predicate test(r: record[name: string]) {
            r.age == 30
        }
        """
        compiler = DSLCompiler()
        # Should raise TypeError with proper message
        with pytest.raises(TypeError) as exc_info:
            compiler.compile(spec)
        assert "no field 'age'" in str(exc_info.value).lower()

    def test_dot_notation_on_non_record(self):
        """Test that dot notation gives proper error when used on non-record."""
        spec = """
        predicate test(x: int) {
            x.field == 5
        }
        """
        compiler = DSLCompiler()
        # Should raise TypeError with proper message
        with pytest.raises(TypeError) as exc_info:
            compiler.compile(spec)
        assert "record type" in str(exc_info.value).lower()

    def test_unparse_dot_notation(self):
        """Test that dot notation is properly unparsed."""
        spec = """
        predicate test(r: record[name: string]) {
            r.name == "Alice"
        }
        """
        compiler = DSLCompiler()
        ast = compiler.parse(spec)

        # Unparse and check it contains dot notation
        from src.DSL.ast_unparse import unparse

        unparsed = unparse(ast)
        assert "r.name" in unparsed
