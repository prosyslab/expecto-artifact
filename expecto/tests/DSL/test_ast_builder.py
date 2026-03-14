"""Test cases for AST builder transformer."""

import sys
from pathlib import Path

import pytest

root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.ast_builder import ASTBuilder
from src.DSL.dsl_ast import (
    BinaryOp,
    Boolean,
    BoolLiteral,
    Char,
    CharLiteral,
    Comparisons,
    Description,
    ExistsExpr,
    ExplicitList,
    ExplicitMap,
    ExplicitSet,
    ForallExpr,
    FuncCall,
    FunctionDef,
    Generator,
    Identifier,
    IfExpr,
    Integer,
    LambdaExpr,
    ListAccess,
    ListComprehension,
    ListType,
    MapType,
    MultisetType,
    NoneLiteral,
    NumberLiteral,
    PredicateDef,
    RangeList,
    RangeSet,
    Real,
    SetComprehension,
    SetType,
    Specification,
    StringLiteral,
    TupleExpr,
    TupleType,
    UnaryOp,
    VarDecl,
)
from src.DSL.grammar import parser


class TestASTBuilder:
    """Test cases for the ASTBuilder transformer."""

    @pytest.fixture
    def parser(self):
        """Create parser with grammar."""
        # Read the grammar file
        transformer = ASTBuilder()

        def _helper(code: str):
            parsed = parser(code)
            print(parsed.pretty())
            return transformer.transform(parsed)

        return _helper

    def test_empty_specification(self, parser):
        """Test parsing empty specification."""
        result = parser("")
        assert isinstance(result, Specification)
        assert result.declarations == []

    def test_number_literal(self, parser):
        """Test parsing number literals."""
        # Test integer
        result = parser("predicate test() { 42 }")
        pred = result.declarations[0]
        assert isinstance(pred.body, NumberLiteral)
        assert pred.body.value == 42

        # Test float
        result = parser("predicate test() { 3.14 }")
        pred = result.declarations[0]
        assert isinstance(pred.body, NumberLiteral)
        assert pred.body.value == 3.14

    def test_none_literal(self, parser):
        """Test parsing None literal as option[T]."""
        result = parser("predicate test() { None }")
        pred = result.declarations[0]
        assert isinstance(pred.body, NoneLiteral)

    def test_bool_literal(self, parser):
        """Test parsing boolean literals."""
        result = parser("predicate test() { true }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BoolLiteral)
        assert pred.body.value is True

        result = parser("predicate test() { false }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BoolLiteral)
        assert pred.body.value is False

    def test_string_literal(self, parser):
        """Test parsing string literals."""
        result = parser('predicate test() { "hello" }')
        pred = result.declarations[0]
        assert isinstance(pred.body, StringLiteral)
        assert pred.body.value == "hello"

    def test_identifier(self, parser):
        """Test parsing identifiers."""
        result = parser("predicate test() { x }")
        pred = result.declarations[0]
        assert isinstance(pred.body, Identifier)
        assert pred.body.name == "x"

    def test_predicate_def_with_body(self, parser):
        """Test predicate definition with expression body."""
        result = parser("predicate is_positive(x: int) { x > 0 }")

        assert isinstance(result, Specification)
        assert len(result.declarations) == 1

        pred = result.declarations[0]
        assert isinstance(pred, PredicateDef)
        assert pred.name == "is_positive"
        assert len(pred.args) == 1
        assert pred.args[0].name == "x"
        assert pred.args[0].ty is not None
        assert pred.args[0].ty.ty == Integer()
        assert pred.description is None
        assert isinstance(pred.body, Comparisons)
        assert pred.body.comparisons[0].op == ">"

    def test_predicate_def_with_description(self, parser):
        """Test predicate definition with description."""
        result = parser(
            'predicate is_positive(x: int) : "Checks if x is positive" {x == 10}'
        )

        pred = result.declarations[0]
        assert isinstance(pred, PredicateDef)
        assert pred.name == "is_positive"
        assert isinstance(pred.description, Description)
        assert pred.description.content == "Checks if x is positive"
        assert pred.body is not None

    def test_function_def_with_body(self, parser):
        """Test function definition with statement body."""
        result = parser("""
        function add(x: int, y: int) -> (res: int) {
            ensure res == x + y;
        }
        """)

        func = result.declarations[0]
        assert isinstance(func, FunctionDef)
        assert func.name == "add"
        assert len(func.args) == 2
        assert func.args[0].name == "x"
        assert func.args[1].name == "y"
        assert func.return_val is not None
        assert func.return_val.name == "res"
        assert func.return_val.ty.ty == Integer()  # type: ignore
        assert func.description is None
        assert len(func.requires) == 0
        assert len(func.ensures) == 1
        assert isinstance(func.ensures[0].expr, Comparisons)
        assert func.ensures[0].expr.comparisons[0].op == "=="

    def test_explicit_function_def_with_body(self, parser):
        """Test explicit function definition with expression body."""
        result = parser("""
        function add(x: int, y: int) {
            x + y
        }
        """)
        func = result.declarations[0]
        assert isinstance(func, FunctionDef)
        assert func.name == "add"
        assert len(func.args) == 2
        assert func.args[0].name == "x"
        assert func.args[1].name == "y"

    def test_function_def_with_description(self, parser):
        """Test function definition with description."""
        result = parser(
            'function add(x: int, y: int) -> (res: int) : "Adds two numbers" { x + y }'
        )

        func = result.declarations[0]
        assert isinstance(func, FunctionDef)
        assert isinstance(func.description, Description)
        assert func.description.content == "Adds two numbers"
        assert func.requires == []
        assert func.ensures == []

    def test_binary_operators(self, parser):
        """Test various binary operators."""
        # Arithmetic
        result = parser("predicate test() { x + y }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BinaryOp)
        assert pred.body.op == "+"

        # Comparison
        result = parser("predicate test() { x == y }")
        pred = result.declarations[0]
        assert isinstance(pred.body, Comparisons)
        assert pred.body.comparisons[0].op == "=="

        # Logical
        result = parser("predicate test() { x ∧ y }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BinaryOp)
        assert pred.body.op == "∧"

        # Implication
        result = parser("predicate test() { x ==> y }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BinaryOp)
        assert pred.body.op == "==>"

        # Equivalence
        result = parser("predicate test() { x <==> y }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BinaryOp)
        assert pred.body.op == "<==>"

    def test_unary_operators(self, parser):
        """Test unary operators."""
        # Negation
        result = parser("predicate test() { ¬x }")
        pred = result.declarations[0]
        assert isinstance(pred.body, UnaryOp)
        assert pred.body.op == "¬"

        # Unary minus
        result = parser("predicate test() { -x }")
        pred = result.declarations[0]
        assert isinstance(pred.body, UnaryOp)
        assert pred.body.op == "-"

        # Unary plus
        result = parser("predicate test() { +x }")
        pred = result.declarations[0]
        assert isinstance(pred.body, UnaryOp)
        assert pred.body.op == "+"

    def test_if_expression(self, parser):
        """Test if expressions."""
        # With else
        result = parser("predicate test() { if x > 0 then y else z }")
        pred = result.declarations[0]
        assert isinstance(pred.body, IfExpr)
        assert isinstance(pred.body.condition, Comparisons)
        assert isinstance(pred.body.then_branch, Identifier)
        assert isinstance(pred.body.else_branch, Identifier)

    def test_lambda_expression(self, parser):
        """Test lambda expressions."""
        result = parser("predicate test() { lambda (x: int, y: int) = x + y }")
        pred = result.declarations[0]
        assert isinstance(pred.body, LambdaExpr)
        assert len(pred.body.args) == 2
        assert pred.body.args[0].name == "x"
        assert pred.body.args[1].name == "y"
        assert isinstance(pred.body.body, BinaryOp)

    def test_forall_quantifier(self, parser):
        """Test forall quantifiers."""
        # With domain
        result = parser("predicate test() { ∀ (x: int) :: (x > 0) }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ForallExpr)
        assert len(pred.body.vars) == 1
        assert pred.body.vars[0].name == "x"
        assert isinstance(pred.body.satisfies_expr, Comparisons)

        # Without domain
        result = parser("predicate test() { ∀ (x: int) :: (x > 0) }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ForallExpr)

    def test_exists_quantifier(self, parser):
        """Test exists quantifiers."""
        # With domain
        result = parser("predicate test() { ∃ (x: int) :: (x > 0) }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ExistsExpr)
        assert len(pred.body.vars) == 1
        assert pred.body.vars[0].name == "x"
        assert isinstance(pred.body.satisfies_expr, Comparisons)

        # Without domain
        result = parser("predicate test() { ∃ (x: int) :: (x > 0) }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ExistsExpr)

    def test_function_call(self, parser):
        """Test function calls."""
        # With arguments
        result = parser("predicate test() { foo(x, y, z) }")
        pred = result.declarations[0]
        assert isinstance(pred.body, FuncCall)
        assert isinstance(pred.body.func, Identifier)
        assert pred.body.func.name == "foo"
        assert len(pred.body.args) == 3

        # Without arguments
        result = parser("predicate test() { foo() }")
        pred = result.declarations[0]
        assert isinstance(pred.body, FuncCall)
        assert len(pred.body.args) == 0

    def test_explicit_list(self, parser):
        """Test explicit list literals."""
        # Non-empty list
        result = parser("predicate test() { [1, 2, 3] }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ExplicitList)
        assert len(pred.body.elements) == 3
        assert all(isinstance(elem, NumberLiteral) for elem in pred.body.elements)

        # Empty list
        result = parser("predicate test() { [] }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ExplicitList)
        assert len(pred.body.elements) == 0

    def test_explicit_set(self, parser):
        """Test explicit set literals."""
        # Non-empty set
        result = parser("predicate test() { {1, 2, 3} }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ExplicitSet)
        assert len(pred.body.elements) == 3

        # Empty set
        result = parser("predicate test() { {} }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ExplicitSet)
        assert len(pred.body.elements) == 0

    def test_list_access(self, parser):
        """Test list access operations."""
        # Single index
        result = parser("predicate test() { arr[0] }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ListAccess)
        assert isinstance(pred.body.seq, Identifier)
        assert pred.body.seq.name == "arr"

        # Multiple indices
        result = parser("predicate test() { matrix[i][j] }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ListAccess)

    def test_types(self, parser):
        """Test type parsing."""
        # Primitive types
        result = parser(
            "function test(x: int, y: bool, z: string, w: real) -> (res: int) { ensure res == 0 }"
        )
        func = result.declarations[0]
        assert func.args[0].get_type() == Integer()
        assert func.args[1].get_type() == Boolean()
        assert func.args[2].get_type() == ListType(Char())
        assert func.args[3].get_type() == Real()
        assert func.return_val.get_type() == Integer()

        # List type
        result = parser("function test(x: list[int]) -> (res: int) { ensure res == 0 }")
        func = result.declarations[0]
        assert isinstance(func.args[0].ty.ty, ListType)
        assert func.args[0].ty.ty.elem == Integer()
        # Set type
        result = parser(
            "function test(x: set[string]) -> (res: int) { ensure res == 0 }"
        )
        func = result.declarations[0]
        assert isinstance(func.args[0].get_type(), SetType)
        assert func.args[0].get_type().elem == ListType(Char())

        # Multiset type
        result = parser(
            "function test(x: multiset[int]) -> (res: int) { ensure res == 0 }"
        )
        func = result.declarations[0]
        assert isinstance(func.args[0].get_type(), MultisetType)
        assert func.args[0].get_type().elem == Integer()

        # Tuple type
        result = parser(
            "function test(x: tuple[int, string]) -> (res: int) { ensure res == 0 }"
        )
        func = result.declarations[0]
        assert isinstance(func.args[0].get_type(), TupleType)
        assert func.args[0].get_type().elem_types == [Integer(), ListType(Char())]

        # Map type
        result = parser(
            "function test(m: map[int, string]) -> (res: int) { ensure res == 0 }"
        )
        func = result.declarations[0]
        assert isinstance(func.args[0].get_type(), MapType)
        assert func.args[0].get_type().key == Integer()
        assert func.args[0].get_type().value == ListType(Char())

    def test_arg_list_optional_types(self, parser):
        """Test argument lists with optional type annotations."""
        result = parser("predicate test(x, y: int, z) { true }")
        pred = result.declarations[0]
        assert len(pred.args) == 3
        assert pred.args[0].name == "x"
        assert pred.args[1].name == "y"
        assert pred.args[1].get_type() == Integer()
        assert pred.args[2].name == "z"

    def test_operator_precedence(self, parser):
        """Test operator precedence."""
        # Arithmetic precedence: + has lower precedence than *
        result = parser("predicate test() { x + y * z }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BinaryOp)
        assert pred.body.op == "+"
        assert isinstance(pred.body.right, BinaryOp)
        assert pred.body.right.op == "*"

        # Logical precedence: ∨ has lower precedence than ∧
        result = parser("predicate test() { x ∨ y ∧ z }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BinaryOp)
        assert pred.body.op == "∨"
        assert isinstance(pred.body.right, BinaryOp)
        assert pred.body.right.op == "∧"

    def test_associativity(self, parser):
        """Test operator associativity."""
        # Left-associative: subtraction
        result = parser("predicate test() { x - y - z }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BinaryOp)
        assert pred.body.op == "-"
        assert isinstance(pred.body.left, BinaryOp)
        assert pred.body.left.op == "-"

        # Right-associative: power
        result = parser("predicate test() { x ^ y ^ z }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BinaryOp)
        assert pred.body.op == "^"
        assert isinstance(pred.body.right, BinaryOp)
        assert pred.body.right.op == "^"

    def test_parentheses(self, parser):
        """Test parentheses override precedence."""
        result = parser("predicate test() { (x + y) * z }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BinaryOp)
        assert pred.body.op == "*"
        assert isinstance(pred.body.left, BinaryOp)
        assert pred.body.left.op == "+"

    def test_complex_expression(self, parser):
        """Test complex nested expressions."""
        result = parser("""
        predicate complex(x: int, y: int) {
            if x > 0 then
                ∀ (i: int) :: (
                    ∃ (j: int) :: (i + j == x ∧ j > y)
                )
            else
                false
        }
        """)

        pred = result.declarations[0]
        assert isinstance(pred.body, IfExpr)
        assert isinstance(pred.body.then_branch, ForallExpr)
        assert isinstance(pred.body.then_branch.satisfies_expr, ExistsExpr)

    def test_multiple_declarations(self, parser):
        """Test multiple declarations in one specification."""
        result = parser("""
        predicate is_positive(x: int) { x > 0 }
        
        function double(x: int) -> (res: int) {
            ensure res == x * 2;
        }
        
        predicate is_even(x: int) { x % 2 == 0 }
        """)

        assert len(result.declarations) == 3
        assert isinstance(result.declarations[0], PredicateDef)
        assert isinstance(result.declarations[1], FunctionDef)
        assert isinstance(result.declarations[2], PredicateDef)

    def test_position_tracking(self, parser):
        """Test that position information is preserved."""
        result = parser("predicate test() { x + y }")
        pred = result.declarations[0]

        # Check that AST nodes have position information
        assert hasattr(pred, "pos")
        assert hasattr(pred.body, "pos")
        assert len(pred.pos) == 4  # (line, col, end_line, end_col)
        assert all(isinstance(x, int) for x in pred.pos)

    def test_edge_cases(self, parser):
        """Test various edge cases."""
        # Predicate with simple body (empty body not supported by grammar)
        result = parser("predicate empty() { true }")
        pred = result.declarations[0]
        assert isinstance(pred.body, BoolLiteral)
        assert pred.body.value is True

        # Single character identifier
        result = parser("predicate x() { y }")
        pred = result.declarations[0]
        assert pred.name == "x"
        assert isinstance(pred.body, Identifier)
        assert pred.body.name == "y"

        # Nested parentheses
        result = parser("predicate test() { ((x)) }")
        pred = result.declarations[0]
        assert isinstance(pred.body, Identifier)
        assert pred.body.name == "x"

    def test_nested_collections(self, parser):
        """Test nested list and set structures."""
        # Nested lists
        result = parser("predicate test() { [[1, 2], [3, 4]] }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ExplicitList)
        assert len(pred.body.elements) == 2
        assert all(isinstance(elem, ExplicitList) for elem in pred.body.elements)

        # Mixed collections
        result = parser("predicate test() { [{1, 2}, {3, 4}] }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ExplicitList)
        assert len(pred.body.elements) == 2
        assert all(isinstance(elem, ExplicitSet) for elem in pred.body.elements)

    def test_chained_comparisons(self, parser):
        """Test chained comparison operators."""
        result = parser("predicate test() { x < y <= z }")
        pred = result.declarations[0]
        assert isinstance(pred.body, Comparisons)
        assert len(pred.body.comparisons) == 2
        assert pred.body.comparisons[0].op == "<"
        assert pred.body.comparisons[1].op == "<="

    def test_complex_quantifiers(self, parser):
        """Test complex quantifier expressions."""
        # Nested quantifiers
        result = parser(
            "predicate test() { ∀ (x: int) :: (∃ (y: int) :: (x + y > 0)) }"
        )
        pred = result.declarations[0]
        assert isinstance(pred.body, ForallExpr)
        assert isinstance(pred.body.satisfies_expr, ExistsExpr)

        # Quantifier with complex domain
        result = parser("predicate test() { ∀ (x: int) :: (x > 0) }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ForallExpr)
        assert isinstance(pred.body.satisfies_expr, Comparisons)

    def test_function_with_no_args(self, parser):
        """Test function with empty argument list."""
        result = parser(
            "function getValue() -> (res: int) { require true; ensure res == 42 }"
        )
        func = result.declarations[0]
        assert isinstance(func, FunctionDef)
        assert func.name == "getValue"
        assert len(func.args) == 0
        assert func.return_val.get_type() == Integer()  # type: ignore

    def test_special_characters_in_strings(self, parser):
        """Test string literals with special characters."""
        result = parser('predicate test() { "hello\\nworld" }')
        pred = result.declarations[0]
        assert isinstance(pred.body, StringLiteral)
        assert pred.body.value == "hello\\nworld"

    def test_complex_lambda(self, parser):
        """Test lambda expressions with complex bodies."""
        result = parser(
            "predicate test() { lambda (x: int, y: int) = if x > y then x else y }"
        )
        pred = result.declarations[0]
        assert isinstance(pred.body, LambdaExpr)
        assert len(pred.body.args) == 2
        assert isinstance(pred.body.body, IfExpr)

    def test_list_access_chaining(self, parser):
        """Test chained list access operations."""
        result = parser("predicate test() { matrix[i][j][k] }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ListAccess)
        assert pred.body.seq.seq.seq.name == "matrix"  # type: ignore
        assert isinstance(pred.body.index, Identifier)
        assert pred.body.index.name == "k"

    def test_negative_numbers(self, parser):
        """Test negative number literals."""
        # Negative numbers are parsed as negative literals, not unary operations
        result = parser("predicate test() { -42 }")
        pred = result.declarations[0]
        assert isinstance(pred.body, UnaryOp)
        assert isinstance(pred.body.operand, NumberLiteral)
        assert pred.body.operand.value == 42

        result = parser("predicate test() { -3.14 }")
        pred = result.declarations[0]
        assert isinstance(pred.body, UnaryOp)
        assert isinstance(pred.body.operand, NumberLiteral)
        assert pred.body.operand.value == 3.14

        # Test explicit unary minus with variable
        result = parser("predicate test() { -(x) }")
        pred = result.declarations[0]
        assert isinstance(pred.body, UnaryOp)
        assert pred.body.op == "-"
        assert isinstance(pred.body.operand, Identifier)

    def test_expr_list_edge_cases(self, parser):
        """Test expression list edge cases."""
        # Single element list
        result = parser("predicate test() { func(x) }")
        pred = result.declarations[0]
        assert isinstance(pred.body, FuncCall)
        assert len(pred.body.args) == 1

        # Function call with expressions
        result = parser("predicate test() { func(x + y, z * w) }")
        pred = result.declarations[0]
        assert isinstance(pred.body, FuncCall)
        assert len(pred.body.args) == 2
        assert all(isinstance(arg, BinaryOp) for arg in pred.body.args)

    def test_type_edge_cases(self, parser):
        """Test edge cases in type parsing."""
        # Nested list types
        result = parser(
            "function test() -> (res: list[list[int]]) { ensure res == [] }"
        )
        func = result.declarations[0]
        assert isinstance(func.return_val.get_type(), ListType)
        assert isinstance(func.return_val.get_type().elem, ListType)
        assert func.return_val.get_type().elem.elem == Integer()

        # Set of lists
        result = parser(
            "function test() -> (res: set[list[string]]) { ensure res == {} }"
        )
        func = result.declarations[0]
        assert isinstance(func.return_val.get_type(), SetType)
        assert isinstance(func.return_val.get_type().elem, ListType)
        assert func.return_val.get_type().elem.elem == ListType(Char())

    def test_range(self, parser):
        """Test range expressions."""
        result = parser("predicate test() { [1..10] }")
        pred = result.declarations[0]
        assert isinstance(pred.body, RangeList)
        assert isinstance(pred.body.start, NumberLiteral)
        assert pred.body.start.value == 1
        assert isinstance(pred.body.end, NumberLiteral)
        assert pred.body.end.value == 10

        result = parser("predicate test() { {1..10} }")
        pred = result.declarations[0]
        assert isinstance(pred.body, RangeSet)
        assert isinstance(pred.body.start, NumberLiteral)
        assert pred.body.start.value == 1
        assert isinstance(pred.body.end, NumberLiteral)
        assert pred.body.end.value == 10

        result = parser("predicate test() { [1..] }")
        pred = result.declarations[0]
        assert isinstance(pred.body, RangeList)
        assert isinstance(pred.body.start, NumberLiteral)
        assert pred.body.start.value == 1

        result = parser("predicate test() { {1..} }")
        pred = result.declarations[0]
        assert isinstance(pred.body, RangeSet)
        assert isinstance(pred.body.start, NumberLiteral)
        assert pred.body.start.value == 1

    def test_char_range(self, parser):
        """Test char range expressions in list and set."""
        result = parser("predicate test() { ['a'..'z'] }")
        pred = result.declarations[0]
        assert isinstance(pred.body, RangeList)
        assert isinstance(pred.body.start, CharLiteral)
        assert pred.body.start.value == "a"
        assert isinstance(pred.body.end, CharLiteral)
        assert pred.body.end.value == "z"

        result = parser("predicate test() { {'a'..'z'} }")
        pred = result.declarations[0]
        assert isinstance(pred.body, RangeSet)
        assert isinstance(pred.body.start, CharLiteral)
        assert pred.body.start.value == "a"
        assert isinstance(pred.body.end, CharLiteral)
        assert pred.body.end.value == "z"

    def test_list_comprehension(self, parser):
        """Test list comprehensions."""
        result = parser("predicate test() { [x | x <- [1,2,3], x < 10] }")
        pred = result.declarations[0]
        assert isinstance(pred.body, ListComprehension)
        assert isinstance(pred.body.expr, Identifier)
        assert pred.body.expr.name == "x"
        assert isinstance(pred.body.generators[0], Generator)
        assert pred.body.generators[0].var.name == "x"
        assert isinstance(pred.body.conditions[0], Comparisons)
        assert len(pred.body.conditions[0].comparisons) == 1
        assert isinstance(pred.body.conditions[0].comparisons[0], BinaryOp)
        assert pred.body.conditions[0].comparisons[0].op == "<"
        assert isinstance(pred.body.conditions[0].comparisons[0].left, Identifier)
        assert pred.body.conditions[0].comparisons[0].left.name == "x"
        assert isinstance(pred.body.conditions[0].comparisons[0].right, NumberLiteral)
        assert pred.body.conditions[0].comparisons[0].right.value == 10

    def test_set_comprehension(self, parser):
        """Test set comprehensions."""
        result = parser("predicate test() { {x | x <- {1,2,3}, x < 10} }")
        pred = result.declarations[0]
        assert isinstance(pred.body, SetComprehension)
        assert isinstance(pred.body.expr, Identifier)
        assert pred.body.expr.name == "x"
        assert isinstance(pred.body.generators[0], Generator)
        assert pred.body.generators[0].var.name == "x"
        assert isinstance(pred.body.conditions[0], Comparisons)
        assert len(pred.body.conditions[0].comparisons) == 1
        assert isinstance(pred.body.conditions[0].comparisons[0], BinaryOp)
        assert pred.body.conditions[0].comparisons[0].op == "<"
        assert isinstance(pred.body.conditions[0].comparisons[0].left, Identifier)
        assert pred.body.conditions[0].comparisons[0].left.name == "x"
        assert isinstance(pred.body.conditions[0].comparisons[0].right, NumberLiteral)
        assert pred.body.conditions[0].comparisons[0].right.value == 10

    def test_var_declarations(self, parser):
        """Test variable declarations in function bodies."""
        result = parser("""
        function test(x: int) -> (res: int) {
            var y = x + 1;
            var z = y * 2;
            ensure res == z;
        }
        """)

        func = result.declarations[0]
        assert isinstance(func, FunctionDef)
        assert func.name == "test"

        # Check variable declarations
        assert len(func.var_decls) == 2

        # First var decl: var y = x + 1
        var_y = func.var_decls[0]
        assert isinstance(var_y, VarDecl)
        assert var_y.var.name == "y"
        assert isinstance(var_y.expr, BinaryOp)
        assert var_y.expr.op == "+"
        assert isinstance(var_y.expr.left, Identifier)
        assert var_y.expr.left.name == "x"
        assert isinstance(var_y.expr.right, NumberLiteral)
        assert var_y.expr.right.value == 1

        # Second var decl: var z = y * 2
        var_z = func.var_decls[1]
        assert isinstance(var_z, VarDecl)
        assert var_z.var.name == "z"
        assert isinstance(var_z.expr, BinaryOp)
        assert var_z.expr.op == "*"
        assert isinstance(var_z.expr.left, Identifier)
        assert var_z.expr.left.name == "y"
        assert isinstance(var_z.expr.right, NumberLiteral)
        assert var_z.expr.right.value == 2

        # Check ensures
        assert len(func.ensures) == 1
        ensure = func.ensures[0]
        assert isinstance(ensure.expr, Comparisons)
        assert ensure.expr.comparisons[0].op == "=="

    def test_var_declaration_with_complex_expr(self, parser):
        """Test variable declaration with complex expression."""
        result = parser("""
        function test(arr: list[int]) -> (res: bool) {
            var length = len(arr);
            var first = arr[0];
            var condition = length > 0 ∧ first > 10;
            ensure res == condition;
        }
        """)

        func = result.declarations[0]
        assert len(func.var_decls) == 3

        # var len = len(arr)
        var_len = func.var_decls[0]
        assert var_len.var.name == "length"
        assert isinstance(var_len.expr, FuncCall)
        assert isinstance(var_len.expr.func, Identifier)
        assert var_len.expr.func.name == "len"

        # var first = arr[0]
        var_first = func.var_decls[1]
        assert var_first.var.name == "first"
        assert isinstance(var_first.expr, ListAccess)

        # var condition = len > 0 ∧ first > 10
        var_condition = func.var_decls[2]
        assert var_condition.var.name == "condition"
        assert isinstance(var_condition.expr, BinaryOp)
        assert var_condition.expr.op == "∧"

    def test_mixed_statements_order(self, parser):
        """Test function with mixed statement order."""
        result = parser("""
        function test(x: int) -> (res: int) {
            require x > 0;
            var doubled = x * 2;
            var squared = doubled * doubled;
            ensure res == squared;
            ensure res > 0;
        }
        """)

        func = result.declarations[0]
        assert len(func.var_decls) == 2
        assert len(func.requires) == 1
        assert len(func.ensures) == 2

        # Check that var_decls are correctly parsed
        assert func.var_decls[0].var.name == "doubled"
        assert func.var_decls[1].var.name == "squared"

    def test_tuple(self, parser):
        """Test tuple expressions."""
        result = parser("function test() { (x, y) }")
        pred = result.declarations[0]
        assert isinstance(pred.body, TupleExpr)
        assert len(pred.body.elements) == 2
        assert isinstance(pred.body.elements[0], Identifier)
        assert pred.body.elements[0].name == "x"
        assert isinstance(pred.body.elements[1], Identifier)
        assert pred.body.elements[1].name == "y"

    def test_char_literal(self, parser):
        """Test char literals."""
        result = parser("function test() -> (res: char) { 'a' }")
        func = result.declarations[0]
        assert isinstance(func, FunctionDef)
        assert func.return_val is not None
        assert func.return_val.get_type() == Char()
        assert isinstance(func.body, CharLiteral)
        assert func.body.value == "a"

    def test_map(self, parser):
        """Test map expressions."""
        result = parser("function test() -> (res: map[int, int]) { map{1 : 2, 3 : 4} }")
        func = result.declarations[0]
        assert isinstance(func, FunctionDef)
        assert func.return_val is not None
        assert func.return_val.get_type() == MapType(Integer(), Integer())
        assert isinstance(func.body, ExplicitMap)
        assert len(func.body.keys) == 2
        assert len(func.body.values) == 2
