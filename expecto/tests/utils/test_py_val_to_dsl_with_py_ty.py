import sys
from pathlib import Path
from typing import Optional, TypedDict

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from src.utils.dsl import pyval_to_dsl_with_py_ty  # noqa: E402


class TestPrimitiveTypes:
    """Test primitive Python types: int, bool, float, str."""

    def test_integer(self):
        assert pyval_to_dsl_with_py_ty(42, int) == "42"
        assert pyval_to_dsl_with_py_ty(0, int) == "0"
        assert pyval_to_dsl_with_py_ty(-5, int) == "-5"
        # bool to int-like string
        assert pyval_to_dsl_with_py_ty(True, int) == "1"
        assert pyval_to_dsl_with_py_ty(False, int) == "0"

    def test_boolean(self):
        assert pyval_to_dsl_with_py_ty(True, bool) == "True"
        assert pyval_to_dsl_with_py_ty(False, bool) == "False"
        # truthy/falsy
        assert pyval_to_dsl_with_py_ty(1, bool) == "True"
        assert pyval_to_dsl_with_py_ty(0, bool) == "False"
        assert pyval_to_dsl_with_py_ty("", bool) == "False"
        assert pyval_to_dsl_with_py_ty("hello", bool) == "True"

    def test_real(self):
        assert pyval_to_dsl_with_py_ty(3.14, float) == "3.14"
        assert pyval_to_dsl_with_py_ty(0.0, float) == "0.0"
        assert pyval_to_dsl_with_py_ty(-2.5, float) == "-2.5"
        # int to float representation
        assert pyval_to_dsl_with_py_ty(42, float) == "42.0"

    def test_real_special_values(self):
        assert pyval_to_dsl_with_py_ty(float("nan"), float) == "nan"
        assert pyval_to_dsl_with_py_ty(float("Infinity"), float) == "Infinity"
        assert pyval_to_dsl_with_py_ty(float("-Infinity"), float) == "-Infinity"

    def test_char_like_str_single_char(self):
        # Single-character str behaves like Char in DSL tests
        assert pyval_to_dsl_with_py_ty("a", str) == '"a"'
        assert pyval_to_dsl_with_py_ty("Z", str) == '"Z"'
        assert pyval_to_dsl_with_py_ty("0", str) == '"0"'


class TestStringType:
    """Test str special case (mirrors ListType(Char()) in DSL tests)."""

    def test_string_basic(self):
        assert pyval_to_dsl_with_py_ty("hello", str) == '"hello"'
        assert pyval_to_dsl_with_py_ty("", str) == '""'

    def test_string_escape_cases(self):
        assert pyval_to_dsl_with_py_ty('a"b', str) == '"a\'b"'
        assert pyval_to_dsl_with_py_ty('"hello"', str) == "\"'hello'\""
        # Backslashes preserved
        assert pyval_to_dsl_with_py_ty("a\\b", str) == '"a\\b"'
        assert pyval_to_dsl_with_py_ty("\n\t", str) == '"\n\t"'
        # Newlines preserved
        assert pyval_to_dsl_with_py_ty("line1\nline2", str) == '"line1\nline2"'
        # Unicode preserved
        assert pyval_to_dsl_with_py_ty("héllo", str) == '"héllo"'
        assert pyval_to_dsl_with_py_ty("🚀", str) == '"🚀"'

        # Special characters preserved
        assert (
            pyval_to_dsl_with_py_ty("\\\t\n\r\b\f\v\0\1", str) == '"\\\t\n\r\b\f\v\0\1"'
        )


class TestCollectionTypes:
    """Test list, set, tuple with various element types."""

    def test_list_basic(self):
        assert pyval_to_dsl_with_py_ty([1, 2, 3], list[int]) == "[1, 2, 3]"
        assert pyval_to_dsl_with_py_ty([], list[int]) == "[]"
        assert pyval_to_dsl_with_py_ty([True, False], list[bool]) == "[True, False]"

    def test_list_nested(self):
        assert (
            pyval_to_dsl_with_py_ty([[1, 2], [3, 4]], list[list[int]])
            == "[[1, 2], [3, 4]]"
        )
        assert (
            pyval_to_dsl_with_py_ty([(1, 2), (3, 4)], list[tuple[int, int]])
            == "[(1, 2), (3, 4)]"
        )

    def test_set_basic(self):
        # Use single-element sets to avoid ordering issues
        assert pyval_to_dsl_with_py_ty({1}, set[int]) == "{1}"
        assert pyval_to_dsl_with_py_ty(set(), set[int]) == "{}"
        assert pyval_to_dsl_with_py_ty({True}, set[bool]) == "{True}"

    def test_set_nested(self):
        assert pyval_to_dsl_with_py_ty({(1, 2)}, set[tuple[int, int]]) == "{(1, 2)}"

    def test_tuple_basic(self):
        assert pyval_to_dsl_with_py_ty((1, 2, 3), tuple[int, int, int]) == "(1, 2, 3)"
        # Empty tuple
        assert pyval_to_dsl_with_py_ty((), tuple[()]) == "()"
        assert (
            pyval_to_dsl_with_py_ty((True, 3.14), tuple[bool, float]) == "(True, 3.14)"
        )

    def test_tuple_nested(self):
        assert (
            pyval_to_dsl_with_py_ty(([1, 2], [3, 4]), tuple[list[int], list[int]])
            == "([1, 2], [3, 4])"
        )
        assert (
            pyval_to_dsl_with_py_ty(
                ((1, 2), (3, 4)), tuple[tuple[int, int], tuple[int, int]]
            )
            == "((1, 2), (3, 4))"
        )


class TestMapType:
    """Test dict with various key/value type combinations."""

    def test_map_basic(self):
        assert (
            pyval_to_dsl_with_py_ty({1: 2, 3: 4}, dict[int, int]) == "map{1: 2, 3: 4}"
        )
        assert pyval_to_dsl_with_py_ty({}, dict[int, int]) == "map{}"
        assert pyval_to_dsl_with_py_ty({"a": True}, dict[str, bool]) == 'map{"a": True}'

    def test_map_different_types(self):
        # Value types are respected
        assert pyval_to_dsl_with_py_ty({1: True}, dict[int, bool]) == "map{1: True}"
        assert pyval_to_dsl_with_py_ty({"x": 42}, dict[str, int]) == 'map{"x": 42}'

    def test_map_nested(self):
        assert (
            pyval_to_dsl_with_py_ty({1: [2, 3]}, dict[int, list[int]])
            == "map{1: [2, 3]}"
        )
        assert (
            pyval_to_dsl_with_py_ty({"a": {1: 2}}, dict[str, dict[int, int]])
            == 'map{"a": map{1: 2}}'
        )


class Person(TypedDict):
    name: str
    age: int


class Config(TypedDict):
    value: float
    enabled: bool


class Wrapper(TypedDict):
    config: Config


class TestRecordType:
    """Test TypedDict records with various field combinations."""

    def test_record_basic(self):
        assert (
            pyval_to_dsl_with_py_ty({"name": "A", "age": 30}, Person)
            == 'record{name: "A", age: 30}'
        )

        # Empty record case via an ad-hoc TypedDict
        class Empty(TypedDict):
            pass

        assert pyval_to_dsl_with_py_ty({}, Empty) == "record{}"

    def test_record_nested(self):
        assert (
            pyval_to_dsl_with_py_ty(
                {"config": {"value": 1.5, "enabled": True}}, Wrapper
            )
            == "record{config: record{value: 1.5, enabled: True}}"
        )

    def test_record_field_order(self):
        class Order(TypedDict):
            z: int
            a: int
            m: int

        assert (
            pyval_to_dsl_with_py_ty({"z": 1, "a": 2, "m": 3}, Order)
            == "record{z: 1, a: 2, m: 3}"
        )


class TestOptionType:
    """Test Optional with none and some cases."""

    def test_option_none(self):
        assert pyval_to_dsl_with_py_ty(None, Optional[int]) == "none"
        assert pyval_to_dsl_with_py_ty(None, Optional[str]) == "none"

    def test_option_some(self):
        assert pyval_to_dsl_with_py_ty(42, Optional[int]) == "some(42)"
        assert pyval_to_dsl_with_py_ty("A", Optional[str]) == 'some("A")'
        assert pyval_to_dsl_with_py_ty(True, Optional[bool]) == "some(True)"

    def test_option_nested(self):
        assert pyval_to_dsl_with_py_ty([1, 2], Optional[list[int]]) == "some([1, 2])"

        class OneField(TypedDict):
            x: int

        assert (
            pyval_to_dsl_with_py_ty({"x": 5}, Optional[OneField])
            == "some(record{x: 5})"
        )


class TestUnsupportedTypes:
    """Test that unsupported Python types raise ValueError."""

    def test_unsupported_custom_object(self):
        class Unknown:
            pass

        with pytest.raises(ValueError, match="Unsupported Python type"):
            pyval_to_dsl_with_py_ty(Unknown(), Unknown)


class TestEdgeCases:
    """Test various edge cases and complex nested structures."""

    def test_deeply_nested_structures(self):
        # List of records containing options
        class Rec(TypedDict):
            value: Optional[int]

        data = [{"value": 42}, {"value": None}]
        assert (
            pyval_to_dsl_with_py_ty(data, list[Rec])
            == "[record{value: some(42)}, record{value: none}]"
        )

    def test_mixed_collection_types(self):
        # dict with tuple keys and list values
        data: dict[tuple[int, str], list[bool]] = {
            (1, "a"): [True, False],
            (2, "b"): [False],
        }
        expected = 'map{(1, "a"): [True, False], (2, "b"): [False]}'
        assert (
            pyval_to_dsl_with_py_ty(data, dict[tuple[int, str], list[bool]]) == expected
        )

    def test_empty_collections(self):
        assert pyval_to_dsl_with_py_ty([], list[int]) == "[]"
        assert pyval_to_dsl_with_py_ty(set(), set[int]) == "{}"
        assert pyval_to_dsl_with_py_ty((), tuple[()]) == "()"
        assert pyval_to_dsl_with_py_ty({}, dict[int, int]) == "map{}"

        class Empty(TypedDict):
            pass

        assert pyval_to_dsl_with_py_ty({}, Empty) == "record{}"
