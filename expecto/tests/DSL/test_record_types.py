"""Test cases for record type functionality."""

import sys
from pathlib import Path

import pytest

root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.ast_builder import ASTBuilder
from src.DSL.compiler import DSLCompiler
from src.DSL.dsl_ast import Integer, ListType, RecordType
from src.DSL.grammar import parser as lark_parser


@pytest.fixture(scope="module")
def parser():
    """Reusable Lark+ASTBuilder parser for the DSL."""

    def _parse_and_transform(code: str):
        parsed = lark_parser(code)
        return ASTBuilder().transform(parsed)

    return _parse_and_transform


@pytest.fixture(scope="module")
def compiler():
    """Reusable DSL compiler for full pipeline testing."""
    return DSLCompiler()


class TestRecordTypeParsing:
    """Test parsing of record types."""

    def test_basic_record_type(self, parser):
        """Test parsing basic record type."""
        code = "predicate test(x: record[name: string, age: int]) { true }"
        ast = parser(code)

        assert len(ast.declarations) == 1
        pred = ast.declarations[0]
        assert pred.name == "test"
        assert len(pred.args) == 1

        arg_type = pred.args[0].ty.ty
        assert isinstance(arg_type, RecordType)
        assert "name" in arg_type.fields
        assert "age" in arg_type.fields
        assert isinstance(arg_type.fields["name"], ListType)
        assert isinstance(arg_type.fields["age"], Integer)

    def test_nested_record_type(self, parser):
        """Test parsing nested record types."""
        code = "predicate test(x: record[config: record[value: real, enabled: bool]]) { true }"
        ast = parser(code)

        pred = ast.declarations[0]
        arg_type = pred.args[0].ty.ty
        assert isinstance(arg_type, RecordType)
        assert "config" in arg_type.fields

        config_type = arg_type.fields["config"]
        assert isinstance(config_type, RecordType)
        assert "value" in config_type.fields
        assert "enabled" in config_type.fields

    def test_empty_record_type(self, parser):
        """Test parsing empty record type."""
        code = "predicate test(x: record[]) { true }"
        ast = parser(code)

        pred = ast.declarations[0]
        arg_type = pred.args[0].ty.ty
        assert isinstance(arg_type, RecordType)
        assert len(arg_type.fields) == 0

    def test_record_type_string_representation(self, parser):
        """Test string representation of record types."""
        code = "predicate test(x: record[a: int, b: string]) { true }"
        ast = parser(code)

        pred = ast.declarations[0]
        arg_type = pred.args[0].ty.ty
        assert str(arg_type) == "record[a: int, b: string]"


class TestRecordFieldAccess:
    """Test record field access functionality."""

    def test_basic_field_access(self, compiler):
        """Test basic field access."""
        code = """
        predicate test(x: record[name: string, age: int]) {
            x["name"] == "Alice"
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

    def test_nested_field_access(self, compiler):
        """Test nested field access."""
        code = """
        predicate test(x: record[config: record[value: real, enabled: bool]]) {
            x["config"]["value"] == 1.0 and x["config"]["enabled"] == true
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

    def test_field_access_type_errors(self, compiler):
        """Test that accessing non-existent fields raises type errors."""
        code = """
        predicate test(x: record[name: string, age: int]) {
            x["email"] == "test@test.com"
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 1
        assert "Record has no field 'email'" in str(errors[0])
        assert "Available fields: name, age" in str(errors[0])

    def test_field_access_wrong_type(self, compiler):
        """Test that accessing with wrong index type raises errors."""
        code = """
        predicate test(x: record[name: string, age: int]) {
            x[42] == "Alice"
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 1
        assert "Record field access requires a string literal" in str(errors[0])


class TestRecordBuiltinFunctions:
    """Test built-in functions for records."""

    def test_keys_function(self, compiler):
        """Test keys() function."""
        code = """
        predicate test(x: record[a: int, b: string, c: bool]) {
            len(keys(x)) == 3
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

    def test_values_function(self, compiler):
        """Test values() function."""
        code = """
        predicate test(x: record[a: int, b: string]) {
            len(values(x)) == 2
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

    def test_items_function(self, compiler):
        """Test items() function."""
        code = """
        predicate test(x: record[a: int, b: string]) {
            len(items(x)) == 2
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

    def test_has_key_function(self, compiler):
        """Test has_key() function."""
        code = """
        predicate test(x: record[a: int, b: string]) {
            has_key(x, "a") and has_key(x, "b") and not has_key(x, "c")
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

    def test_has_key_wrong_type(self, compiler):
        """Test has_key() with wrong key type."""
        code = """
        predicate test(x: record[a: int, b: string]) {
            has_key(x, 42)
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 1
        assert "has_key() for records requires string key" in str(errors[0])


class TestRecordTypeChecking:
    """Test type checking for records."""

    def test_record_type_unification(self, compiler):
        """Test that record types unify correctly."""
        code = """
        predicate test(x: record[a: int, b: string]) {
            var y: record[a: int, b: string] = x;
            y["a"] == 42
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

    def test_record_type_mismatch(self, compiler):
        """Test that mismatched record types raise errors."""
        code = """
        predicate test(x: record[a: int, b: string]) {
            var y: record[a: int, c: bool] = x;
            true
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 1
        assert "type mismatch" in str(errors[0]).lower()

    def test_record_vs_map_distinction(self, compiler):
        """Test that records and maps are distinct types."""
        code = """
        predicate test_record(x: record[a: int]) {
            x["a"] == 42
        }
        
        predicate test_map(x: map[string, int]) {
            x["a"] == 42
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

        # Check that the signatures are different
        record_sig = ast.declarations[0].get_signature()
        map_sig = ast.declarations[1].get_signature()

        assert "record" in record_sig
        assert "map" in map_sig
        assert record_sig != map_sig


class TestRecordZ3Translation:
    """Test Z3 translation for records."""

    def test_basic_record_z3(self, compiler):
        """Test basic record Z3 translation."""
        code = """
        predicate test(x: record[name: string, age: int]) {
            x["name"] == "Alice"
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

        z3_exprs = compiler.to_z3(ast)
        assert len(z3_exprs) == 1

    def test_nested_record_z3(self, compiler):
        """Test nested record Z3 translation."""
        code = """
        predicate test(x: record[config: record[value: real]]) {
            x["config"]["value"] == 1.0
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

        z3_exprs = compiler.to_z3(ast)
        assert len(z3_exprs) == 1

    def test_record_builtin_functions_z3(self, compiler):
        """Test Z3 translation of record built-in functions."""
        code = """
        predicate test(x: record[a: int, b: string]) {
            len(keys(x)) == 2 and has_key(x, "a")
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

        z3_exprs = compiler.to_z3(ast)
        assert len(z3_exprs) == 1


class TestRecordUnparsing:
    """Test unparsing of record types."""

    def test_record_type_unparsing(self, compiler):
        """Test that record types unparse correctly."""
        code = """
        predicate test(x: record[name: string, age: int]) {
            x["name"] == "Alice"
        }
        """

        ast = compiler.parse(code)
        unparsed = compiler.unparse(ast)

        assert "record[name: string, age: int]" in unparsed
        assert 'x["name"]' in unparsed

    def test_nested_record_unparsing(self, compiler):
        """Test that nested record types unparse correctly."""
        code = """
        predicate test(x: record[config: record[value: real, enabled: bool]]) {
            x["config"]["value"] == 1.0
        }
        """

        ast = compiler.parse(code)
        unparsed = compiler.unparse(ast)

        assert "record[config: record[value: real, enabled: bool]]" in unparsed
        assert 'x["config"]["value"]' in unparsed

    def test_empty_record_unparsing(self, compiler):
        """Test that empty record types unparse correctly."""
        code = """
        predicate test(x: record[]) {
            len(keys(x)) == 0
        }
        """

        ast = compiler.parse(code)
        unparsed = compiler.unparse(ast)

        assert "record[]" in unparsed


class TestRecordRoundTrip:
    """Test round-trip parsing and unparsing for records."""

    def test_basic_record_roundtrip(self, compiler):
        """Test round-trip for basic record."""
        original = """
        predicate test(x: record[name: string, age: int]) {
            x["name"] == "Alice" and x["age"] > 18
        }
        """

        ast1 = compiler.parse(original)
        unparsed = compiler.unparse(ast1)
        ast2 = compiler.parse(unparsed)

        # Check that the structure is preserved
        assert len(ast1.declarations) == len(ast2.declarations)
        assert ast1.declarations[0].name == ast2.declarations[0].name

    def test_nested_record_roundtrip(self, compiler):
        """Test round-trip for nested record."""
        original = """
        predicate test(x: record[phase: string, self: record[sigma: real, mu: int], params: record[]]) {
            x["phase"] == "entry" and x["self"]["sigma"] == 0.0
        }
        """

        ast1 = compiler.parse(original)
        unparsed = compiler.unparse(ast1)
        ast2 = compiler.parse(unparsed)

        # Check that the structure is preserved
        assert len(ast1.declarations) == len(ast2.declarations)
        assert ast1.declarations[0].name == ast2.declarations[0].name

    def test_record_with_builtins_roundtrip(self, compiler):
        """Test round-trip for record with built-in functions."""
        original = """
        predicate test(x: record[a: int, b: string, c: bool]) {
            len(keys(x)) == 3 and has_key(x, "a") and len(values(x)) == 3
        }
        """

        ast1 = compiler.parse(original)
        unparsed = compiler.unparse(ast1)
        ast2 = compiler.parse(unparsed)

        # Check that the structure is preserved
        assert len(ast1.declarations) == len(ast2.declarations)
        assert ast1.declarations[0].name == ast2.declarations[0].name


class TestRecordEdgeCases:
    """Test edge cases for record functionality."""

    def test_record_with_single_field(self, compiler):
        """Test record with single field."""
        code = """
        predicate test(x: record[value: int]) {
            x["value"] == 42
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

    def test_record_with_many_fields(self, compiler):
        """Test record with many fields."""
        code = """
        predicate test(x: record[a: int, b: string, c: bool, d: real, e: int]) {
            x["a"] == 1 and x["b"] == "test" and x["c"] == true
        }
        """

        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        assert len(errors) == 0

    def test_record_field_order_preservation(self, parser):
        """Test that field order is preserved in record types."""
        code = "predicate test(x: record[z: int, a: string, m: bool]) { true }"
        ast = parser(code)

        pred = ast.declarations[0]
        arg_type = pred.args[0].ty.ty
        field_names = list(arg_type.fields.keys())

        # Field order should be preserved as declared
        assert field_names == ["z", "a", "m"]

    def test_record_equality(self, parser):
        """Test record type equality."""
        code1 = "predicate test1(x: record[a: int, b: string]) { true }"
        code2 = "predicate test2(x: record[a: int, b: string]) { true }"
        code3 = "predicate test3(x: record[b: string, a: int]) { true }"

        ast1 = parser(code1)
        ast2 = parser(code2)
        ast3 = parser(code3)

        type1 = ast1.declarations[0].args[0].ty.ty
        type2 = ast2.declarations[0].args[0].ty.ty
        type3 = ast3.declarations[0].args[0].ty.ty

        # Same fields, same order should be equal
        assert type1 == type2

        # Different field order should not be equal
        assert type1 != type3
