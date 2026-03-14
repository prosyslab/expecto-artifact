"""Round-trip tests for AST – unparse then parse must keep structure (ignoring positions)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))


from src.DSL.ast_builder import ASTBuilder
from src.DSL.ast_unparse import unparse
from src.DSL.grammar import parser as lark_parser

# ---------------------------------------------------------------------------
#  Helper utilities
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parser():
    """Reusable Lark+ASTBuilder parser for the DSL."""

    def _parse_and_transform(code: str):
        parsed = lark_parser(code)
        return ASTBuilder().transform(parsed)

    return _parse_and_transform


# ---------------------------------------------------------------------------
#  Parameterised test cases
# ---------------------------------------------------------------------------


ROUNDTRIP_PROGRAMS = [
    "",  # empty specification
    "predicate is_positive(x: int) { x > 0 }",
    'predicate always_true() : "Returns true" {true}',
    (
        "function add(x: int, y: int) -> (res: int) {\n"
        "    require x >= 0;\n"
        "    require y >= 0;\n"
        "    ensure res == x + y;\n"
        "    ensure if ¬(x > 0) then res > 0 else res < 0;\n"
        "    ensure map(lambda (x: int) = x, [1,2,3]) == [1,2,3];\n"
        "    ensure {x, y} == {y, x};\n"
        "    ensure [1,2,3][2] == 3;\n"
        "    ensure ∃(x: int) :: x > 0;\n"
        "    ensure ∀(x: int) :: x > 0;\n"
        "    ensure -(x) == -x;\n"
        "    ensure true;\n"
        "}"
    ),
    "predicate test_var_decls() {\n    var x = 1;\n    var y = 2;\n    (x + y == 3)\n}",
    'predicate hello() { "hello world" }',
    "function add(x: int, y: int) -> (res: int) {}",
    "function add(x: int, y: int) { x + y }",
    "predicate trivial() {\n    [1,2,3] == [x | x <- [1..3]]\n}",
    "predicate trivial() {\n    {x | x <- [1..3]} == {1,2,3} == {1..3}\n}",
    "predicate test_tuple() { (1, 2) }",
    "predicate test_tuple_access() { (1, 2)[0] }",
    "predicate test_map() { map{1 : 2, 3 : 4} }",
    # Record type tests
    'predicate test_record(x: record[name: string, age: int]) { x["name"] == "Alice" }',
    "predicate test_empty_record(x: record[]) { len(keys(x)) == 0 }",
    'predicate test_nested_record(x: record[config: record[value: real, enabled: bool]]) { x["config"]["value"] == 1.0 }',
    'predicate test_record_builtins(x: record[a: int, b: string]) { len(keys(x)) == 2 and has_key(x, "a") }',
]


@pytest.mark.parametrize("source", ROUNDTRIP_PROGRAMS)
def test_roundtrip(parser, source: str):  # noqa: D401
    """Parse → unparse → parse should yield *equivalent* ASTs (ignoring pos)."""

    ast1 = parser(source)
    pretty = unparse(ast1)

    ast2 = parser(pretty)
    pretty2 = unparse(ast2)

    assert pretty == pretty2, (
        "AST mismatch after round-trip:\n"
        f"Original source:\n{pretty}\n\nPretty-printed:\n{pretty2}\n"
    )


def test_pretty_print_string_literals(parser):  # noqa: D401
    """Test that string literals with newlines are preserved correctly."""

    # Test string with newlines and indentation
    source = 'predicate test_string() { "abc\\n    def" }'
    ast = parser(source)

    # With pretty_print=True (default), should apply indentation
    pretty = unparse(ast, pretty_print=True)
    print(f"Pretty print=True: {repr(pretty)}")

    # With pretty_print=False, should preserve original string content
    compact = unparse(ast, pretty_print=False)
    print(f"Pretty print=False: {repr(compact)}")

    # Parse both back and verify the string content is preserved
    ast_pretty = parser(pretty)
    ast_compact = parser(compact)

    # Both should parse to equivalent ASTs
    assert unparse(ast_pretty, pretty_print=False) == unparse(
        ast_compact, pretty_print=False
    )


def test_pretty_print_control(parser):  # noqa: D401
    """Test that pretty_print parameter controls line breaks and indentation."""

    # Test with a complex expression that would normally be broken across lines
    source = "predicate test_long_expr() { (x + y + z + a + b + c + d + e + f + g + h + i + j + k + l + m + n + o + p + q + r + s + t + u + v + w + x + y + z) }"
    ast = parser(source)

    # With pretty_print=True, should break long lines
    pretty = unparse(ast, pretty_print=True)
    assert "\n" in pretty, (
        "Pretty print should include line breaks for long expressions"
    )

    # With pretty_print=False, should keep everything on one line
    compact = unparse(ast, pretty_print=False)
    assert "\n" not in compact, "Compact print should not include line breaks"

    # Both should parse to equivalent ASTs
    ast_pretty = parser(pretty)
    ast_compact = parser(compact)
    assert unparse(ast_pretty, pretty_print=False) == unparse(
        ast_compact, pretty_print=False
    )
