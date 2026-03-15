from __future__ import annotations

from abc import ABC, abstractmethod
from textwrap import indent

"""Domain-specific language (DSL) abstract-syntax tree definitions.

Each node stores its position in the source code as a tuple
(line, column, end_line, end_column).  These coordinates come from the
`meta` field that Lark attaches to every rule/token during parsing and
should be filled by the transformer when constructing the AST.

Only structural information lives here – any evaluation/translation
(Z3, interpreter, …) must be done in a dedicated stage to keep the AST
simple and inspectable.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional, Sequence, Tuple, Union

# A small helper type for node positions
SrcPos = Tuple[int, int, int, int]  # (line, col, end_line, end_col)


# ────────────────────────────────────────────────────────────────────────────────
#  Types
# ────────────────────────────────────────────────────────────────────────────────


class DSLType(ABC):
    @abstractmethod
    def __eq__(self, other: "DSLType") -> bool:
        raise NotImplementedError

    @abstractmethod
    def __str__(self) -> str:
        raise NotImplementedError

    def __hash__(self) -> int:
        return hash(str(self))


class Integer(DSLType):
    def __eq__(self, other: "DSLType") -> bool:
        return isinstance(other, Integer)

    def __str__(self) -> str:
        return "int"


class Boolean(DSLType):
    def __eq__(self, other: "DSLType") -> bool:
        return isinstance(other, Boolean)

    def __str__(self) -> str:
        return "bool"


class Real(DSLType):
    def __eq__(self, other: DSLType) -> bool:
        return isinstance(other, Real)

    def __str__(self) -> str:
        return "real"


class Char(DSLType):
    def __eq__(self, other: DSLType) -> bool:
        return isinstance(other, Char)

    def __str__(self) -> str:
        return "char"


class ListType(DSLType):
    def __init__(self, elem: DSLType):
        self.elem = elem

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ListType) and self.elem == other.elem

    def __str__(self) -> str:  # pragma: no cover
        if isinstance(self.elem, Char):
            return "string"
        return f"list[{self.elem}]"


class SetType(DSLType):
    def __init__(self, elem: DSLType):
        self.elem = elem

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SetType) and self.elem == other.elem

    def __str__(self) -> str:  # pragma: no cover
        return f"set[{self.elem}]"


class MultisetType(DSLType):
    def __init__(self, elem: DSLType):
        self.elem = elem

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MultisetType) and self.elem == other.elem

    def __str__(self) -> str:  # pragma: no cover
        return f"multiset[{self.elem}]"


class MapType(DSLType):
    def __init__(self, key: DSLType, value: DSLType):
        self.key = key
        self.value = value

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, MapType)
            and self.key == other.key
            and self.value == other.value
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"map[{self.key}, {self.value}]"


class DSLNoneType(DSLType):
    def __eq__(self, other: object) -> bool:
        return isinstance(other, DSLNoneType)

    def __str__(self) -> str:
        return "nonetype"


class NoneLiteralType(DSLType):
    """Internal inference type for the `none` literal."""

    def __init__(self, target: DSLType | None = None):
        self.target = target if target is not None else TypeVar()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, NoneLiteralType) and self.target == other.target

    def __str__(self) -> str:
        return f"none[{self.target}]"


class OptionType(DSLType):
    def __init__(self, elem: DSLType):
        self.elem = elem

    def __eq__(self, other: object) -> bool:
        return isinstance(other, OptionType) and self.elem == other.elem

    def __str__(self) -> str:  # pragma: no cover
        return f"option[{self.elem}]"


class TupleType(DSLType):
    def __init__(self, elem_types: Sequence[DSLType]):
        self.elem_types: list[DSLType] = list(elem_types)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TupleType) and self.elem_types == other.elem_types

    def __str__(self) -> str:  # pragma: no cover
        return f"tuple[{', '.join(map(str, self.elem_types))}]"


class RecordType(DSLType):
    def __init__(self, fields: dict[str, DSLType]):
        self.fields: dict[str, DSLType] = fields

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, RecordType)
            and list(self.fields.keys()) == list(other.fields.keys())
            and all(self.fields[k] == other.fields[k] for k in self.fields)
        )

    def __str__(self) -> str:  # pragma: no cover
        field_strs = [f"{name}: {ty}" for name, ty in self.fields.items()]
        return f"record[{', '.join(field_strs)}]"


class FuncType(DSLType):
    def __init__(self, arg_types: Sequence[DSLType], ret: DSLType):
        self.arg_types: list[DSLType] = list(arg_types)
        self.ret: DSLType = ret

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FuncType)
            and self.arg_types == other.arg_types
            and self.ret == other.ret
        )

    def __str__(self) -> str:  # pragma: no cover
        args = ", ".join(map(str, self.arg_types))
        return f"({args}) -> {self.ret}"


class TypeVar(DSLType):
    _counter = 0

    def __init__(self):
        self.name = f"t{TypeVar._counter}"
        TypeVar._counter += 1

    def __str__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TypeVar):
            return self.name == other.name
        return False

    def __hash__(self) -> int:  # noqa: D401
        return hash(self.name)


# ────────────────────────────────────────────────────────────────────────────────
#  Common Nodes
# ────────────────────────────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class ASTNode:
    """Base class for every AST node."""

    pos: SrcPos = field(default_factory=lambda: (0, 0, 0, 0))

    def __str__(self):
        children = [
            child
            for child in self.__dict__
            if not child.startswith("__") and child != "pos"
        ]
        stringified = []
        for child in children:
            value = self.__dict__[child]
            if isinstance(value, ASTNode):
                stringified.append(
                    "[{}]:\n".format(child) + indent(str(value), " " * 4)
                )
            elif isinstance(value, list):
                stringified.append(
                    "[{}]:\n".format(child)
                    + indent("\n".join(map(str, value)), " " * 4)
                )
            elif value is not None:
                stringified.append(f"[{child}]: {str(value)}")
        return "<{}>:\n".format(self.__class__.__name__) + indent(
            "\n".join(stringified), " " * 4
        )

    def __iter__(self):
        for field_name, value in vars(self).items():
            if field_name == "pos":
                continue
            if isinstance(value, ASTNode):
                yield value
                yield from iter(value)
            elif isinstance(value, list):
                for item in value:
                    yield item
                    yield from iter(item)


@dataclass(kw_only=True)
class TypeNode(ASTNode):
    ty: DSLType

    def __str__(self) -> str:
        return str(self.ty)


@dataclass(kw_only=True)
class Expr(ASTNode):
    ty: TypeNode = field(default_factory=lambda: TypeNode(ty=TypeVar()))

    def get_type(self) -> DSLType:
        return self.ty.ty


# ────────────────────────────────────────────────────────────────────────────────
#  Literals & identifiers
# ────────────────────────────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class NumberLiteral(Expr):
    value: Union[int, float]
    ty: TypeNode = field(default_factory=lambda: TypeNode(ty=Integer()))


@dataclass(kw_only=True)
class BoolLiteral(Expr):
    value: bool
    ty: TypeNode = field(default_factory=lambda: TypeNode(ty=Boolean()))


@dataclass(kw_only=True)
class StringLiteral(Expr):
    value: str
    ty: TypeNode = field(default_factory=lambda: TypeNode(ty=ListType(Char())))


@dataclass(kw_only=True)
class CharLiteral(Expr):
    value: str
    ty: TypeNode = field(default_factory=lambda: TypeNode(ty=Char()))


@dataclass(kw_only=True)
class NoneLiteral(Expr):
    ty: TypeNode = field(default_factory=lambda: TypeNode(ty=NoneLiteralType()))


@dataclass(kw_only=True)
class SomeExpr(Expr):
    """Some constructor: some(value) creates option[T] from T."""

    value: Expr


@dataclass(kw_only=True)
class Identifier(Expr):
    name: str


# ---------------------------------------------------------------------------
#  Operator type aliases (explicit enumerations for static type-checking)
# ---------------------------------------------------------------------------

# Unary operators supported by the DSL
UnaryOperator = Literal["-", "+", "¬"]

# Binary operators (arithmetic, logical and comparison)
BinaryOperator = Literal[
    "+",
    "-",
    "*",
    "/",
    "%",
    "^",  # arithmetic
    "∧",
    "∨",
    "==>",
    "<==>",  # boolean logic
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
    "in",  # comparisons
]


# ────────────────────────────────────────────────────────────────────────────────
#  Expressions
# ────────────────────────────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class UnaryOp(Expr):
    op: UnaryOperator
    operand: Expr


@dataclass(kw_only=True)
class BinaryOp(Expr):
    left: Expr
    op: BinaryOperator
    right: Expr


@dataclass(kw_only=True)
class Comparisons(Expr):
    comparisons: Sequence[BinaryOp]


@dataclass(kw_only=True)
class IfExpr(Expr):
    condition: Expr
    then_branch: Expr
    else_branch: Expr


@dataclass(kw_only=True)
class LambdaExpr(Expr):
    args: Sequence[Identifier]
    body: Expr


# ────────────────────────────────────────────────────────────────────────────────
#  Quantifiers
# ────────────────────────────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class ForallExpr(Expr):
    vars: Sequence[Identifier]
    satisfies_expr: Expr


@dataclass(kw_only=True)
class ExistsExpr(Expr):
    vars: Sequence[Identifier]
    satisfies_expr: Expr


# ────────────────────────────────────────────────────────────────────────────────
#  Calls & data-structure operations
# ────────────────────────────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class FuncCall(Expr):
    func: Expr  # can be Identifier or LambdaExpr
    args: Sequence[Expr]


@dataclass(kw_only=True)
class ListAccess(Expr):
    seq: Expr
    index: Expr


@dataclass(kw_only=True)
class FieldAccess(Expr):
    record: Expr
    field_name: str


@dataclass(kw_only=True)
class ExplicitList(Expr):
    elements: Sequence[Expr]


@dataclass(kw_only=True)
class ExplicitSet(Expr):
    elements: Sequence[Expr]


@dataclass(kw_only=True)
class ExplicitMultiset(Expr):
    elements: Sequence[Expr]


@dataclass(kw_only=True)
class ExplicitMap(Expr):
    keys: Sequence[Expr]
    values: Sequence[Expr]


@dataclass(kw_only=True)
class ExplicitRecord(Expr):
    fields: dict[str, Expr]


@dataclass(kw_only=True)
class RangeList(Expr):
    start: Expr
    end: Optional[Expr]


@dataclass(kw_only=True)
class RangeSet(Expr):
    start: Expr
    end: Optional[Expr]


@dataclass(kw_only=True)
class ListComprehension(Expr):
    expr: ASTNode
    generators: Sequence[Generator]
    conditions: Sequence[Expr]


@dataclass(kw_only=True)
class SetComprehension(Expr):
    expr: ASTNode
    generators: Sequence[Generator]
    conditions: Sequence[Expr]


@dataclass(kw_only=True)
class Generator(Expr):
    var: Identifier
    expr: Expr


@dataclass(kw_only=True)
class TupleExpr(Expr):
    elements: Sequence[Expr]


# ────────────────────────────────────────────────────────────────────────────────
#  Statements
# ────────────────────────────────────────────────────────────────────────────────


@dataclass
class Statement(ASTNode):
    pass


@dataclass(kw_only=True)
class Ensure(Statement):
    expr: Expr


@dataclass(kw_only=True)
class Require(Statement):
    expr: Expr


@dataclass(kw_only=True)
class VarDecl(Statement):
    var: Identifier
    expr: Expr


# ────────────────────────────────────────────────────────────────────────────────
#  Declarations
# ────────────────────────────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class Description(ASTNode):
    """String description for predicates/functions."""

    content: str


@dataclass(kw_only=True)
class PredicateDef(ASTNode):
    """Predicate definition: predicate name(args) : description | { body }"""

    name: str
    args: Sequence[Identifier]
    description: Description | None
    var_decls: Sequence[VarDecl]
    body: Optional[Expr]  # Either description OR Boolean Expression

    def get_type(self) -> FuncType:
        assert all(arg.ty is not None for arg in self.args)
        return_type = Boolean()
        arg_types: list[DSLType] = [
            arg.ty.ty for arg in self.args if arg.ty is not None
        ]
        return FuncType(arg_types, return_type)

    def get_signature(self) -> str:
        return f"{self.name}: {str(self.get_type())}"


@dataclass(kw_only=True)
class FunctionDef(ASTNode):
    """Function definition: function name(args) -> type : description | { statements }"""

    name: str
    args: Sequence[Identifier]
    return_val: Identifier = field(default_factory=lambda: Identifier(name="result"))
    description: Description | None
    # Implicit function def
    var_decls: Sequence[VarDecl]
    requires: Sequence[Require]
    ensures: Sequence[Ensure]
    # Explicit function def
    body: Optional[Expr]

    def get_type(self) -> FuncType:
        assert all(arg.ty is not None for arg in self.args)
        return_type = self.return_val.get_type()
        arg_types: list[DSLType] = [
            arg.ty.ty for arg in self.args if arg.ty is not None
        ]
        return FuncType(arg_types, return_type)

    def get_signature(self) -> str:
        return f"{self.name}: {str(self.get_type())}"


Def = PredicateDef | FunctionDef


# ────────────────────────────────────────────────────────────────────────────────
#  Program root
# ────────────────────────────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class Specification(ASTNode):
    """Top-level specification containing declarations."""

    declarations: Sequence[Def]
