"""Test suite for pyval_to_dsl_with_dsl_ty function."""

import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from src.DSL.dsl_ast import (
    Boolean,
    Char,
    DSLNoneType,
    DSLType,
    FuncType,
    Integer,
    ListType,
    MapType,
    OptionType,
    Real,
    RecordType,
    SetType,
    TupleType,
)
from src.utils.dsl import pyval_to_dsl_with_dsl_ty


class TestPrimitiveTypes:
    """Test primitive DSL types: Integer, Boolean, Real, Char."""

    def test_integer(self):
        """Test Integer type conversion."""
        assert pyval_to_dsl_with_dsl_ty(42, Integer()) == "42"
        assert pyval_to_dsl_with_dsl_ty(0, Integer()) == "0"
        assert pyval_to_dsl_with_dsl_ty(-5, Integer()) == "-5"
        # Test boolean conversion to int
        assert pyval_to_dsl_with_dsl_ty(True, Integer()) == "1"
        assert pyval_to_dsl_with_dsl_ty(False, Integer()) == "0"

    def test_boolean(self):
        """Test Boolean type conversion."""
        assert pyval_to_dsl_with_dsl_ty(True, Boolean()) == "True"
        assert pyval_to_dsl_with_dsl_ty(False, Boolean()) == "False"
        # Test truthy/falsy conversion
        assert pyval_to_dsl_with_dsl_ty(1, Boolean()) == "True"
        assert pyval_to_dsl_with_dsl_ty(0, Boolean()) == "False"
        assert pyval_to_dsl_with_dsl_ty("", Boolean()) == "False"
        assert pyval_to_dsl_with_dsl_ty("hello", Boolean()) == "True"

    def test_real(self):
        """Test Real type conversion."""
        assert pyval_to_dsl_with_dsl_ty(3.14, Real()) == "3.14"
        assert pyval_to_dsl_with_dsl_ty(0.0, Real()) == "0.0"
        assert pyval_to_dsl_with_dsl_ty(-2.5, Real()) == "-2.5"
        # Test int to float conversion
        assert pyval_to_dsl_with_dsl_ty(42, Real()) == "42.0"

    def test_real_special_values(self):
        """Test Real type conversion for special floating-point values."""
        assert pyval_to_dsl_with_dsl_ty(float("NaN"), Real()) == "nan"
        assert pyval_to_dsl_with_dsl_ty(float("Infinity"), Real()) == "Infinity"
        assert pyval_to_dsl_with_dsl_ty(float("-Infinity"), Real()) == "-Infinity"
        assert pyval_to_dsl_with_dsl_ty("NaN", Real()) == "nan"
        assert pyval_to_dsl_with_dsl_ty("Infinity", Real()) == "Infinity"
        assert pyval_to_dsl_with_dsl_ty("-Infinity", Real()) == "-Infinity"

    def test_char(self):
        """Test Char type conversion with escape edge cases."""
        assert pyval_to_dsl_with_dsl_ty("a", Char()) == "'a'"
        assert pyval_to_dsl_with_dsl_ty("Z", Char()) == "'Z'"
        assert pyval_to_dsl_with_dsl_ty("0", Char()) == "'0'"
        # Edge cases - note: current implementation doesn't escape
        assert pyval_to_dsl_with_dsl_ty("'", Char()) == "'''"  # Single quote
        assert pyval_to_dsl_with_dsl_ty("\\", Char()) == "'\\'"  # Backslash
        assert pyval_to_dsl_with_dsl_ty("\n", Char()) == "'\n'"  # Newline
        assert pyval_to_dsl_with_dsl_ty("\t", Char()) == "'\t'"  # Tab


class TestStringType:
    """Test ListType(Char()) special case for strings."""

    def test_string_basic(self):
        """Test basic string conversion."""
        assert pyval_to_dsl_with_dsl_ty("hello", ListType(Char())) == '"hello"'
        assert pyval_to_dsl_with_dsl_ty("", ListType(Char())) == '""'

    def test_string_escape_cases(self):
        """Test string conversion with escape edge cases."""
        # Double quotes should be replaced with single quotes
        assert pyval_to_dsl_with_dsl_ty('a"b', ListType(Char())) == '"a\'b"'
        assert pyval_to_dsl_with_dsl_ty('"hello"', ListType(Char())) == "\"'hello'\""

        # Backslashes should be preserved
        assert pyval_to_dsl_with_dsl_ty("a\\b", ListType(Char())) == '"a\\b"'
        assert pyval_to_dsl_with_dsl_ty("\n\t", ListType(Char())) == '"\n\t"'

        # Newlines should be preserved
        assert (
            pyval_to_dsl_with_dsl_ty("line1\nline2", ListType(Char()))
            == '"line1\nline2"'
        )

        # Unicode should be preserved
        assert pyval_to_dsl_with_dsl_ty("héllo", ListType(Char())) == '"héllo"'
        assert pyval_to_dsl_with_dsl_ty("🚀", ListType(Char())) == '"🚀"'


class TestCollectionTypes:
    """Test ListType, SetType, TupleType with various element types."""

    def test_list_basic(self):
        """Test basic list conversion."""
        assert pyval_to_dsl_with_dsl_ty([1, 2, 3], ListType(Integer())) == "[1, 2, 3]"
        assert pyval_to_dsl_with_dsl_ty([], ListType(Integer())) == "[]"
        assert (
            pyval_to_dsl_with_dsl_ty([True, False], ListType(Boolean()))
            == "[True, False]"
        )

    def test_list_nested(self):
        """Test nested list structures."""
        # List of lists
        assert (
            pyval_to_dsl_with_dsl_ty([[1, 2], [3, 4]], ListType(ListType(Integer())))
            == "[[1, 2], [3, 4]]"
        )
        # List of tuples
        assert (
            pyval_to_dsl_with_dsl_ty(
                [(1, 2), (3, 4)], ListType(TupleType([Integer(), Integer()]))
            )
            == "[(1, 2), (3, 4)]"
        )

    def test_set_basic(self):
        """Test basic set conversion."""
        # Use single-element sets to avoid ordering issues
        assert pyval_to_dsl_with_dsl_ty({1}, SetType(Integer())) == "{1}"
        assert pyval_to_dsl_with_dsl_ty(set(), SetType(Integer())) == "{}"
        assert pyval_to_dsl_with_dsl_ty({True}, SetType(Boolean())) == "{True}"

    def test_set_nested(self):
        """Test nested set structures."""
        # Set of tuples (single element to avoid ordering)
        assert (
            pyval_to_dsl_with_dsl_ty(
                {(1, 2)}, SetType(TupleType([Integer(), Integer()]))
            )
            == "{(1, 2)}"
        )

    def test_tuple_basic(self):
        """Test basic tuple conversion."""
        assert (
            pyval_to_dsl_with_dsl_ty(
                (1, 2, 3), TupleType([Integer(), Integer(), Integer()])
            )
            == "(1, 2, 3)"
        )
        assert pyval_to_dsl_with_dsl_ty((), TupleType([])) == "()"
        assert (
            pyval_to_dsl_with_dsl_ty((True, 3.14), TupleType([Boolean(), Real()]))
            == "(True, 3.14)"
        )

    def test_tuple_nested(self):
        """Test nested tuple structures."""
        # Tuple containing lists
        assert (
            pyval_to_dsl_with_dsl_ty(
                ([1, 2], [3, 4]), TupleType([ListType(Integer()), ListType(Integer())])
            )
            == "([1, 2], [3, 4])"
        )
        # Tuple containing tuples
        assert (
            pyval_to_dsl_with_dsl_ty(
                ((1, 2), (3, 4)),
                TupleType(
                    [
                        TupleType([Integer(), Integer()]),
                        TupleType([Integer(), Integer()]),
                    ]
                ),
            )
            == "((1, 2), (3, 4))"
        )


class TestMapType:
    """Test MapType with various key/value type combinations."""

    def test_map_basic(self):
        """Test basic map conversion."""
        assert (
            pyval_to_dsl_with_dsl_ty({1: 2, 3: 4}, MapType(Integer(), Integer()))
            == "map{1: 2, 3: 4}"
        )
        assert pyval_to_dsl_with_dsl_ty({}, MapType(Integer(), Integer())) == "map{}"
        # Current implementation treats keys as raw (no quotes) and converts values using key type
        # so Boolean value True under Char key becomes "'True'", and key string is unquoted
        assert (
            pyval_to_dsl_with_dsl_ty({"a": True}, MapType(Char(), Boolean()))
            == "map{'a': True}"
        )

    def test_map_different_types(self):
        """Test map with different key/value types."""
        # This exposes the current bug where value type is ignored
        # Value is converted using key type: True -> 1 for Integer key
        assert (
            pyval_to_dsl_with_dsl_ty({1: True}, MapType(Integer(), Boolean()))
            == "map{1: True}"
        )
        # Key string is unquoted; value uses Char key type wrapping in single quotes
        assert (
            pyval_to_dsl_with_dsl_ty({"x": 42}, MapType(Char(), Integer()))
            == "map{'x': 42}"
        )

    def test_map_nested(self):
        """Test nested map structures."""
        assert (
            pyval_to_dsl_with_dsl_ty(
                {1: [2, 3]}, MapType(Integer(), ListType(Integer()))
            )
            == "map{1: [2, 3]}"
        )
        assert (
            pyval_to_dsl_with_dsl_ty(
                {"a": {1: 2}}, MapType(Char(), MapType(Integer(), Integer()))
            )
            == "map{'a': map{1: 2}}"
        )


class TestRecordType:
    """Test RecordType with various field combinations."""

    def test_record_basic(self):
        """Test basic record conversion."""
        record_type = RecordType({"name": Char(), "age": Integer()})
        assert (
            pyval_to_dsl_with_dsl_ty({"name": "A", "age": 30}, record_type)
            == "record{name: 'A', age: 30}"
        )

        # Empty record
        empty_record_type = RecordType({})
        assert pyval_to_dsl_with_dsl_ty({}, empty_record_type) == "record{}"

    def test_record_nested(self):
        """Test nested record structures."""
        # Record with nested record
        nested_record_type = RecordType(
            {"config": RecordType({"value": Real(), "enabled": Boolean()})}
        )
        assert (
            pyval_to_dsl_with_dsl_ty(
                {"config": {"value": 1.5, "enabled": True}}, nested_record_type
            )
            == "record{config: record{value: 1.5, enabled: True}}"
        )

    def test_record_field_order(self):
        """Test that field order is preserved according to type definition."""
        record_type = RecordType({"z": Integer(), "a": Integer(), "m": Integer()})
        assert (
            pyval_to_dsl_with_dsl_ty({"z": 1, "a": 2, "m": 3}, record_type)
            == "record{z: 1, a: 2, m: 3}"
        )


class TestOptionType:
    """Test OptionType with none and some cases."""

    def test_option_none(self):
        """Test OptionType with None value."""
        assert pyval_to_dsl_with_dsl_ty(None, OptionType(Integer())) == "none"
        assert pyval_to_dsl_with_dsl_ty(None, OptionType(Char())) == "none"

    def test_option_some(self):
        """Test OptionType with some value."""
        assert pyval_to_dsl_with_dsl_ty(42, OptionType(Integer())) == "some(42)"
        assert pyval_to_dsl_with_dsl_ty("A", OptionType(Char())) == "some('A')"
        assert pyval_to_dsl_with_dsl_ty(True, OptionType(Boolean())) == "some(True)"

    def test_option_with_escapes(self):
        assert (
            pyval_to_dsl_with_dsl_ty("\n\t\r\b\f\v\0\1", OptionType(ListType(Char())))
            == 'some("\n\t\r\b\f\v\0\1")'
        )

    def test_option_nested(self):
        """Test OptionType with nested types."""
        # Option of list
        assert (
            pyval_to_dsl_with_dsl_ty([1, 2], OptionType(ListType(Integer())))
            == "some([1, 2])"
        )
        # Option of record
        record_type = RecordType({"x": Integer()})
        assert (
            pyval_to_dsl_with_dsl_ty({"x": 5}, OptionType(record_type))
            == "some(record{x: 5})"
        )
        # Option of option
        assert (
            pyval_to_dsl_with_dsl_ty(42, OptionType(OptionType(Integer())))
            == "some(some(42))"
        )

    def test_nonetype(self):
        """Test that DSLNoneType is converted to none."""
        assert pyval_to_dsl_with_dsl_ty(None, DSLNoneType()) == "none"
        assert pyval_to_dsl_with_dsl_ty(123, DSLNoneType()) == "none"


class TestUnsupportedTypes:
    """Test that unsupported DSL types raise ValueError."""

    def test_unsupported_func_type(self):
        """Test that FuncType raises ValueError."""
        func_type = FuncType([Integer()], Boolean())
        with pytest.raises(ValueError, match="Unsupported DSL type"):
            pyval_to_dsl_with_dsl_ty(lambda x: x > 0, func_type)

    def test_unsupported_unknown_type(self):
        """Test that unknown DSL type raises ValueError."""

        class UnknownType(DSLType):
            def __eq__(self, other):
                return isinstance(other, UnknownType)

            def __str__(self):
                return "unknown"

        with pytest.raises(ValueError, match="Unsupported DSL type"):
            pyval_to_dsl_with_dsl_ty("test", UnknownType())


class TestEdgeCases:
    """Test various edge cases and complex nested structures."""

    def test_deeply_nested_structures(self):
        """Test deeply nested combinations."""
        # List of records containing options
        record_type = RecordType({"value": OptionType(Integer())})
        list_of_records = ListType(record_type)
        data = [{"value": 42}, {"value": None}]
        expected = "[record{value: some(42)}, record{value: none}]"
        assert pyval_to_dsl_with_dsl_ty(data, list_of_records) == expected

    def test_mixed_collection_types(self):
        """Test mixed collection types in complex structures."""
        # Map with tuple keys and list values
        map_type = MapType(TupleType([Integer(), Char()]), ListType(Boolean()))
        data = {(1, "a"): [True, False], (2, "b"): [False]}
        expected = "map{(1, 'a'): [True, False], (2, 'b'): [False]}"
        assert pyval_to_dsl_with_dsl_ty(data, map_type) == expected

    def test_empty_collections(self):
        """Test empty collections of various types."""
        assert pyval_to_dsl_with_dsl_ty([], ListType(Integer())) == "[]"
        assert pyval_to_dsl_with_dsl_ty(set(), SetType(Integer())) == "{}"
        assert pyval_to_dsl_with_dsl_ty((), TupleType([])) == "()"
        assert pyval_to_dsl_with_dsl_ty({}, MapType(Integer(), Integer())) == "map{}"
        assert pyval_to_dsl_with_dsl_ty({}, RecordType({})) == "record{}"
