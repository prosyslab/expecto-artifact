from __future__ import annotations

"""Lark -> AST transformer.

Converts the parse tree produced by the DSL grammar into the plain
`ast.py` data classes, retaining source-code positions for each node.
"""


from typing import Any, List

from lark import Token, Transformer, v_args
from lark.tree import Meta

from .dsl_ast import (
    BinaryOp,
    BinaryOperator,
    Boolean,
    BoolLiteral,
    Char,
    CharLiteral,
    Comparisons,
    Description,
    DSLNoneType,
    DSLType,
    Ensure,
    ExistsExpr,
    ExplicitList,
    ExplicitMap,
    ExplicitMultiset,
    ExplicitRecord,
    ExplicitSet,
    Expr,
    FieldAccess,
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
    NoneLiteralType,
    NumberLiteral,
    OptionType,
    PredicateDef,
    RangeList,
    RangeSet,
    Real,
    RecordType,
    Require,
    SetComprehension,
    SetType,
    Specification,
    SrcPos,
    StringLiteral,
    TupleExpr,
    TupleType,
    TypeNode,
    TypeVar,
    UnaryOp,
    VarDecl,
)

__all__ = [
    "ASTBuilder",
]


# ────────────────────────────────────────────────────────────────────────────────
#  Helper utilities
# ────────────────────────────────────────────────────────────────────────────────


def _pos_from_meta(meta: Meta) -> SrcPos:
    line = getattr(meta, "line", 0)
    column = getattr(meta, "column", 0)
    end_line = getattr(meta, "end_line", 0)
    end_column = getattr(meta, "end_column", 0)
    return (line, column, end_line, end_column)


def _pos_from_token(tok: Token) -> SrcPos:
    """Extract position from a Lark Token or Tree object."""
    line = getattr(tok, "line", 0)
    column = getattr(tok, "column", 0)
    end_line = getattr(tok, "end_line", 0)
    end_column = getattr(tok, "end_column", 0)
    return (line, column, end_line, end_column)


def _combine_pos(pos1: SrcPos, pos2: SrcPos) -> SrcPos:
    """Return a span from the beginning of pos1 to the end of pos2."""
    if pos1 < pos2:
        return (pos1[0], pos1[1], pos2[2], pos2[3])
    else:
        return (pos2[0], pos2[1], pos1[2], pos1[3])


# ────────────────────────────────────────────────────────────────────────────────
#  Transformer implementation
# ────────────────────────────────────────────────────────────────────────────────


class ASTBuilder(Transformer):
    """Builds AST nodes from the parse tree."""

    # ────────────────────────────────────────────────────────────────────────────
    #  Program structure
    # ────────────────────────────────────────────────────────────────────────────

    @v_args(meta=True)
    def specification(self, meta: Meta, children: List[Any]) -> Specification:
        """specification: declaration*"""
        pos = _pos_from_meta(meta)
        return Specification(pos=pos, declarations=children)

    @v_args(meta=True, inline=True)
    def predicate_def(self, meta: Meta, pred_name, args, *others) -> PredicateDef:
        """predicate_def: "predicate" identifier arg_list ":" description? "{" expr "}" """
        # children[0] is name (from identifier), children[1] is args (from arg_list)
        # children[2] is either description or expr
        name = pred_name.name  # Extract string from Identifier

        description = None
        var_decls = []
        exprs = []
        for child in others:
            if isinstance(child, Description):
                description = child
            elif isinstance(child, Expr):
                exprs.append(child)
            elif isinstance(child, VarDecl):
                var_decls.append(child)
        pos = _pos_from_meta(meta)

        body = None
        for e in exprs:
            if body is None:
                body = e
            else:
                body = BinaryOp(pos=pos, left=body, op="∧", right=e)

        return PredicateDef(
            pos=pos,
            name=name,
            args=args,
            description=description,
            var_decls=var_decls,
            body=body,
        )

    @v_args(meta=True)
    def function_def(
        self,
        meta: Meta,
        children: List[Any],
    ) -> FunctionDef:
        """function_def: "function" identifier arg_list ("->" (atom | type))? ":" description? "{" statement* "}" """
        assert len(children) >= 3
        identifier, arg_list = children[0], children[1]
        if children[2] == "->" and isinstance(children[3], Identifier):
            return_val = children[3]
            body_or_description = children[4:]
        elif children[2] == "->" and isinstance(children[3], TypeNode):
            return_val = Identifier(name="result", ty=children[3])
            body_or_description = children[4:]
        else:
            return_val = Identifier(name="result")
            body_or_description = children[2:]

        name = identifier.name  # Extract string from Identifier
        args = arg_list

        description = None
        var_decls = []
        requires = []
        ensures = []
        exprs = []

        for child in body_or_description:
            if isinstance(child, Description):
                description = child
            elif isinstance(child, Expr):
                exprs.append(child)
            elif isinstance(child, VarDecl):
                var_decls.append(child)
            elif isinstance(child, Require):
                requires.append(child)
            elif isinstance(child, Ensure):
                ensures.append(child)

        pos = _pos_from_meta(meta)
        if isinstance(return_val, TypeNode):
            return_val = Identifier(pos=pos, name="return_val", ty=return_val)

        body = None
        for e in exprs:
            if body is None:
                body = e
            else:
                body = BinaryOp(pos=pos, left=body, op="∧", right=e)

        return FunctionDef(
            pos=pos,
            name=name,
            args=args,
            return_val=return_val,
            description=description,
            var_decls=var_decls,
            requires=requires,
            ensures=ensures,
            body=body,
        )

    @v_args(meta=True)
    def description(self, meta: Meta, children: List[Any]) -> Description:
        """description: STRING_LIT"""
        # children[0] is already a StringLiteral from STRING_LIT transformer
        string_lit = children[0]
        pos = _pos_from_meta(meta)
        return Description(pos=pos, content=string_lit.value)

    # ────────────────────────────────────────────────────────────────────────────
    #  Statements
    # ────────────────────────────────────────────────────────────────────────────

    @v_args(meta=True, inline=True)
    def ensure(self, meta: Meta, expr: Expr) -> Ensure:
        """ensure: "ensure" expr"""
        assert isinstance(expr, Expr)
        pos = _pos_from_meta(meta)
        return Ensure(pos=pos, expr=expr)

    @v_args(meta=True, inline=True)
    def require(self, meta: Meta, expr: Expr) -> Require:
        """require: "require" expr"""
        assert isinstance(expr, Expr)
        pos = _pos_from_meta(meta)
        return Require(pos=pos, expr=expr)

    @v_args(meta=True, inline=True)
    def var_decl(self, meta: Meta, identifier: Identifier, expr: Expr) -> VarDecl:
        """var_decl: "var" identifier ":=" expr"""
        assert isinstance(identifier, Identifier)
        assert isinstance(expr, Expr)
        pos = _pos_from_meta(meta)
        return VarDecl(pos=pos, var=identifier, expr=expr)

    # ────────────────────────────────────────────────────────────────────────────
    #  Expressions
    # ────────────────────────────────────────────────────────────────────────────
    # Binary operators (left-associative)
    @v_args(meta=True, inline=True)
    def semicolon_expr(self, meta: Meta, lhs: Expr, rhs: Expr) -> Any:
        """semicolon_expr: semicolon_expr ";" equiv_expr | equiv_expr"""
        pos = _pos_from_meta(meta)
        return BinaryOp(pos=pos, left=lhs, op="∧", right=rhs)

    @v_args(meta=True, inline=True)
    def equiv_expr(self, meta: Meta, lhs: Expr, rhs: Expr) -> Any:
        """equiv_expr: equiv_expr "<==>" implies_expr | implies_expr"""
        pos = _pos_from_meta(meta)
        return BinaryOp(pos=pos, left=lhs, op="<==>", right=rhs)

    @v_args(meta=True, inline=True)
    def implies_expr(self, meta: Meta, lhs: Expr, rhs: Expr) -> Any:
        """implies_expr: implies_expr "==>" or_expr | or_expr"""
        pos = _pos_from_meta(meta)
        return BinaryOp(pos=pos, left=lhs, op="==>", right=rhs)

    @v_args(meta=True, inline=True)
    def or_expr(self, meta: Meta, lhs: Expr, rhs: Expr) -> Any:
        """or_expr: or_expr ("∨" | "\\/" | "or") and_expr | and_expr"""
        pos = _pos_from_meta(meta)
        return BinaryOp(pos=pos, left=lhs, op="∨", right=rhs)

    @v_args(meta=True, inline=True)
    def and_expr(self, meta: Meta, lhs: Expr, rhs: Expr) -> Any:
        """and_expr: and_expr ("∧" | "/\\" | "and") not_expr | not_expr"""
        pos = _pos_from_meta(meta)
        return BinaryOp(pos=pos, left=lhs, op="∧", right=rhs)

    @v_args(meta=True, inline=True)
    def not_expr(self, meta: Meta, _, expr: Expr) -> Any:
        """not_expr: "¬" not_expr"""
        pos = _pos_from_meta(meta)
        return UnaryOp(pos=pos, op="¬", operand=expr)

    @v_args(meta=True)
    def comparison_expr(self, meta: Meta, children: List[Any]) -> Any:
        """comparison_expr: arith_expr (COMP_OP_LIT arith_expr)*"""
        # children are alternating: expr, op, expr, op, expr...
        comparisons = []
        for lhs, op, rhs in zip(children[::2], children[1::2], children[2::2]):
            pos = _combine_pos(lhs.pos, rhs.pos)
            comparisons.append(BinaryOp(pos=pos, left=lhs, op=op, right=rhs))
        joined_pos = _pos_from_meta(meta)
        return Comparisons(pos=joined_pos, comparisons=comparisons)

    @v_args(meta=True, inline=True)
    def arith_expr(self, meta: Meta, lhs: Expr, op: BinaryOperator, rhs: Expr) -> Any:
        """arith_expr: arith_expr ADD_OP_LIT term | term"""
        pos = _pos_from_meta(meta)
        return BinaryOp(pos=pos, left=lhs, op=op, right=rhs)

    @v_args(meta=True, inline=True)
    def term(self, meta: Meta, lhs: Expr, op: BinaryOperator, rhs: Expr) -> Any:
        """term: term MULT_OP_LIT factor | factor"""
        pos = _pos_from_meta(meta)
        return BinaryOp(pos=pos, left=lhs, op=op, right=rhs)

    @v_args(meta=True, inline=True)
    def factor(self, meta: Meta, op: Token, operand: Expr) -> Any:
        """factor: ADD_OP_LIT? power"""
        pos = _pos_from_meta(meta)
        return UnaryOp(pos=pos, op=op.value, operand=operand)

    @v_args(meta=True, inline=True)
    def power(self, meta: Meta, base: Expr, exponent: Expr) -> Any:
        """power: atom ("^" factor)?"""
        pos = _pos_from_meta(meta)
        return BinaryOp(pos=pos, left=base, op="^", right=exponent)

    # ────────────────────────────────────────────────────────────────────────────
    #  Atoms and literals
    # ────────────────────────────────────────────────────────────────────────────

    def NUMBER(self, token: Token) -> NumberLiteral:
        """Convert number token to NumberLiteral."""
        if "e" in token.value or "." in token.value:
            value = float(token.value)
        else:
            value = int(token.value)
        pos = _pos_from_token(token)
        return NumberLiteral(
            pos=pos,
            value=value,
            ty=TypeNode(ty=Integer() if isinstance(value, int) else Real()),
        )

    def FLOAT_INF(self, token: Token) -> NumberLiteral:
        """Handle infinity floating-point literals."""
        value = float(token.value)
        pos = _pos_from_token(token)
        return NumberLiteral(pos=pos, value=value, ty=TypeNode(ty=Real()))

    def FLOAT_NAN(self, token: Token) -> NumberLiteral:
        """Handle NaN floating-point literals."""
        value = float(token.value)
        pos = _pos_from_token(token)
        return NumberLiteral(pos=pos, value=value, ty=TypeNode(ty=Real()))

    def BOOL_LIT(self, token: Token) -> BoolLiteral:
        """Convert boolean token to BoolLiteral."""
        value = token.value.lower() == "true"
        pos = _pos_from_token(token)
        return BoolLiteral(pos=pos, value=value, ty=TypeNode(ty=Boolean()))

    def CHAR_LIT(self, token: Token) -> CharLiteral:
        """Convert char token to CharLiteral."""
        value = token.value.strip("'")  # Remove quotes
        pos = _pos_from_token(token)
        return CharLiteral(pos=pos, value=value, ty=TypeNode(ty=Char()))

    def NONE_LIT(self, token: Token) -> NoneLiteral:
        """Convert None token to NoneLiteral."""
        pos = _pos_from_token(token)
        # Resolve the literal to nonetype or option[T] during type checking.
        return NoneLiteral(pos=pos, ty=TypeNode(ty=NoneLiteralType()))

    def STRING_LIT(self, token: Token) -> StringLiteral:
        """Convert string token to StringLiteral."""
        value = token.value.strip('"')  # Remove quotes
        pos = _pos_from_token(token)
        return StringLiteral(pos=pos, value=value, ty=TypeNode(ty=ListType(Char())))

    def identifier(self, children: List[Any]) -> Identifier:
        """identifier: CNAME (":" type)?"""
        name = children[0].value
        ty = children[1] if len(children) > 1 else TypeNode(ty=TypeVar())
        pos = _pos_from_token(children[0])
        return Identifier(pos=pos, name=name, ty=ty)

    # ────────────────────────────────────────────────────────────────────────────
    #  Control flow and expressions
    # ────────────────────────────────────────────────────────────────────────────

    @v_args(meta=True, inline=True)
    def if_expr(
        self, meta: Meta, condition: Expr, then_branch: Expr, else_branch: Expr
    ) -> IfExpr:
        """if_expr: "if" expr "then" expr ("else" expr)?"""
        pos = _pos_from_meta(meta)
        return IfExpr(
            pos=pos,
            condition=condition,
            then_branch=then_branch,
            else_branch=else_branch,
        )

    def arg_list(self, children: List[Any]) -> List[Identifier]:
        """arg_list: "(" arg? ("," arg)* ")"""
        return [child for child in children if isinstance(child, Identifier)]

    @v_args(meta=True)
    def lambda_expr(self, meta: Meta, children: List[Any]) -> LambdaExpr:
        """lambda_expr: "lambda" arg_list "=" expr"""
        args = children[0]  # from arg_list
        body = children[1]  # from expr
        pos = _pos_from_meta(meta)
        return LambdaExpr(pos=pos, args=args, body=body)

    # ────────────────────────────────────────────────────────────────────────────
    #  Quantifiers
    # ────────────────────────────────────────────────────────────────────────────

    @v_args(meta=True, inline=True)
    def forall(
        self, meta: Meta, args: List[Identifier], satisfies_expr: Expr
    ) -> ForallExpr:
        """forall: "∀" arg_list "::" expr"""
        pos = _pos_from_meta(meta)
        return ForallExpr(pos=pos, vars=args, satisfies_expr=satisfies_expr)

    @v_args(meta=True, inline=True)
    def exists(
        self, meta: Meta, args: List[Identifier], satisfies_expr: Expr
    ) -> ExistsExpr:
        """exists: "∃" arg_list "::" expr"""
        pos = _pos_from_meta(meta)
        return ExistsExpr(pos=pos, vars=args, satisfies_expr=satisfies_expr)

    # ────────────────────────────────────────────────────────────────────────────
    #  Function calls and data structures
    # ────────────────────────────────────────────────────────────────────────────

    @v_args(meta=True)
    def func_call(self, meta: Meta, children: List[Any]) -> FuncCall:
        """func_call: identifier "(" expr_list? ")"""
        func = children[0]  # from identifier
        if len(children) > 1 and children[1] is not None:
            args = children[1]  # from expr_list
        else:
            args = []
        pos = _pos_from_meta(meta)
        return FuncCall(pos=pos, func=func, args=args)

    def expr_list(self, children: List[Any]) -> List[Any]:
        """expr_list: expr ("," expr)*"""
        return children

    @v_args(meta=True)
    def explicit_set(self, meta: Meta, children: List[Any]) -> ExplicitSet:
        """explicit_set: "{" expr_list "}"""
        # All children are expressions (braces and commas filtered out)
        if len(children) == 1:
            elements = children[0]
        else:
            elements = []
        pos = _pos_from_meta(meta)
        return ExplicitSet(pos=pos, elements=elements)

    @v_args(meta=True)
    def explicit_multiset(self, meta: Meta, children: List[Any]) -> ExplicitMultiset:
        """explicit_multiset: "{{" expr_list "}}"""
        # All children are expressions (double braces and commas filtered out)
        if len(children) == 1:
            elements = children[0]
        else:
            elements = []
        pos = _pos_from_meta(meta)
        return ExplicitMultiset(pos=pos, elements=elements)

    @v_args(meta=True)
    def explicit_list(self, meta: Meta, children: List[Any]) -> ExplicitList:
        """explicit_list: "[" expr_list "]"""
        # All children are expressions (brackets and commas filtered out)
        if len(children) == 1:
            elements = children[0]
        else:
            elements = []
        pos = _pos_from_meta(meta)
        return ExplicitList(pos=pos, elements=elements)

    @v_args(meta=True)
    def explicit_map(self, meta: Meta, children: List[Any]) -> ExplicitMap:
        """explicit_map: "{" map_kv ("," map_kv)* "}"""
        keys: List[Expr] = []
        values: List[Expr] = []
        for child in children:
            if (
                isinstance(child, list)
                and len(child) == 2
                and isinstance(child[0], Expr)
                and isinstance(child[1], Expr)
            ):
                keys.append(child[0])
                values.append(child[1])
        pos = _pos_from_meta(meta)
        return ExplicitMap(pos=pos, keys=keys, values=values)

    @v_args(meta=True)
    def map_function(self, meta: Meta, children: List[Any]) -> FuncCall:
        """map_function: "map" "(" expr_list? ")"""
        pos = _pos_from_meta(meta)
        return FuncCall(pos=pos, func=Identifier(name="map"), args=children[0])

    @v_args(inline=True)
    def map_kv(self, k, v):
        return [k, v]

    @v_args(meta=True)
    def explicit_record(self, meta: Meta, children: List[Any]) -> ExplicitRecord:
        """explicit_record: "record" "{" record_kv ("," record_kv)* "}" | "record" "{" "}"""
        fields: dict[str, Expr] = {}
        for child in children:
            if isinstance(child, tuple) and len(child) == 2:
                field_name, field_value = child
                assert isinstance(field_name, str)
                assert isinstance(field_value, Expr)
                fields[field_name] = field_value
        pos = _pos_from_meta(meta)
        return ExplicitRecord(pos=pos, fields=fields)

    @v_args(inline=True)
    def record_kv(self, field_name: Token, field_value: Expr):
        return (field_name.value, field_value)

    @v_args(meta=True, inline=True)
    def list_access(self, meta: Meta, seq: Expr, index: Expr) -> ListAccess:
        """list_access: expr "[" expr "]"""
        pos = _pos_from_meta(meta)
        return ListAccess(pos=pos, seq=seq, index=index)

    @v_args(meta=True, inline=True)
    def field_access(self, meta: Meta, record: Expr, field_name: Token) -> FieldAccess:
        """field_access: atom "." CNAME"""
        pos = _pos_from_meta(meta)
        return FieldAccess(pos=pos, record=record, field_name=field_name.value)

    @v_args(meta=True)
    def range_list(self, meta: Meta, children: List[Any]) -> RangeList:
        """range_list: "[" expr? ".." expr? "]"""
        end = None
        if len(children) == 2:
            end = children[1]
        start = children[0]
        pos = _pos_from_meta(meta)
        return RangeList(pos=pos, start=start, end=end)

    @v_args(meta=True)
    def range_set(self, meta: Meta, children: List[Any]) -> RangeSet:
        """range_set: "{" expr? ".." expr? "}"""
        end = None
        if len(children) == 2:
            end = children[1]
        start = children[0]
        pos = _pos_from_meta(meta)
        return RangeSet(pos=pos, start=start, end=end)

    @v_args(meta=True)
    def list_comprehension(self, meta: Meta, children: List[Any]) -> ListComprehension:
        """list_comprehension: "[" expr "|" (generator | expr)("," (generator | expr))* "]"""
        pos = _pos_from_meta(meta)
        generators = []
        conditions = []

        for child in children[1:]:
            if isinstance(child, Generator):
                generators.append(child)
            else:
                conditions.append(child)
        return ListComprehension(
            pos=pos, expr=children[0], generators=generators, conditions=conditions
        )

    @v_args(meta=True)
    def set_comprehension(self, meta: Meta, children: List[Any]) -> SetComprehension:
        """set_comprehension: "{" expr "|" (generator | expr)("," (generator | expr))* "}"""
        pos = _pos_from_meta(meta)
        generators = []
        conditions = []

        for child in children[1:]:
            if isinstance(child, Generator):
                generators.append(child)
            else:
                conditions.append(child)
        return SetComprehension(
            pos=pos, expr=children[0], generators=generators, conditions=conditions
        )

    @v_args(meta=True, inline=True)
    def generator(self, meta: Meta, var: Identifier, _, expr: Expr) -> Generator:
        """generator: identifier "<-" expr"""
        pos = _pos_from_meta(meta)
        return Generator(pos=pos, var=var, expr=expr)

    @v_args(meta=True)
    def tuple(self, meta: Meta, children: List[Any]) -> TupleExpr:
        """tuple: "(" expr ("," expr)+ ")" | "(" expr "," ")" """
        pos = _pos_from_meta(meta)
        return TupleExpr(pos=pos, elements=children)

    # ────────────────────────────────────────────────────────────────────────────
    #  Types
    # ────────────────────────────────────────────────────────────────────────────

    @v_args(meta=True)
    def type(self, meta: Meta, children: List[Any]) -> TypeNode:
        if isinstance(children[0], Token):
            # Primitive type
            type_name = children[0].value
            match type_name:
                case "int":
                    ty = Integer()
                case "bool":
                    ty = Boolean()
                case "real":
                    ty = Real()
                case "char":
                    ty = Char()
                case "string":
                    ty = ListType(Char())
                case "nonetype":
                    ty = DSLNoneType()
                case _:
                    raise ValueError(f"Unknown type: {type_name}")
        else:
            # Composite type (ListType or SetType)
            ty = children[0]
            assert isinstance(ty, DSLType)
        pos = _pos_from_meta(meta)
        return TypeNode(pos=pos, ty=ty)

    def list_type(self, children: List[Any]) -> DSLType:
        """list_type: "list" "[" type "]"""
        elem_type_node = children[0]
        assert isinstance(elem_type_node, TypeNode), (
            f"Expected TypeNode, got {type(elem_type_node.ty)}"
        )
        return ListType(elem_type_node.ty)

    def set_type(self, children: List[Any]) -> DSLType:
        """set_type: "set" "[" type "]"""
        elem_type_node = children[0]
        assert isinstance(elem_type_node, TypeNode), (
            f"Expected TypeNode, got {type(elem_type_node.ty)}"
        )
        return SetType(elem_type_node.ty)

    def multiset_type(self, children: List[Any]) -> DSLType:
        """multiset_type: "multiset" "[" type "]"""
        elem_type_node = children[0]
        assert isinstance(elem_type_node, TypeNode), (
            f"Expected TypeNode, got {type(elem_type_node.ty)}"
        )
        return MultisetType(elem_type_node.ty)

    def map_type(self, children: List[Any]) -> DSLType:
        """map_type: MAP_TYPE "[" type "," type "]"""
        # children may include the MAP_TYPE token; filter down to TypeNode instances
        type_nodes = [c for c in children if isinstance(c, TypeNode)]
        assert len(type_nodes) == 2, (
            f"Expected 2 type nodes for map_type, got {len(type_nodes)}"
        )
        key_type_node = type_nodes[0]
        val_type_node = type_nodes[1]
        assert isinstance(key_type_node, TypeNode) and isinstance(
            val_type_node, TypeNode
        ), f"Expected TypeNode, got {type(key_type_node)} and {type(val_type_node)}"
        return MapType(key_type_node.ty, val_type_node.ty)

    def tuple_type(self, children: List[Any]) -> DSLType:
        """tuple_type: "tuple" "(" type ("," type)* ")" """
        assert all(isinstance(child, TypeNode) for child in children), (
            f"Expected TypeNode, got {type(child)}" for child in children
        )
        elem_types = [child.ty for child in children]
        return TupleType(elem_types)

    def option_type(self, children: List[Any]) -> DSLType:
        """option_type: "option" "[" type "]"""
        elem_type_node = children[0]
        assert isinstance(elem_type_node, TypeNode), (
            f"Expected TypeNode, got {type(elem_type_node.ty)}"
        )
        return OptionType(elem_type_node.ty)

    def record_type(self, children: List[Any]) -> DSLType:
        """record_type: RECORD_TYPE "[" field_spec? ("," field_spec)* "]"""
        # Filter out RECORD_TYPE token and keep field_spec tuples
        fields_dict = {}
        for child in children:
            if isinstance(child, tuple) and len(child) == 2:
                field_name, field_type_node = child
                assert isinstance(field_name, str)
                assert isinstance(field_type_node, TypeNode)
                fields_dict[field_name] = field_type_node.ty
        return RecordType(fields_dict)

    def field_spec(self, children: List[Any]) -> tuple[str, TypeNode]:
        """field_spec: CNAME ":" type"""
        field_name = children[0].value  # CNAME token
        field_type = children[1]  # TypeNode
        assert isinstance(field_type, TypeNode)
        return (field_name, field_type)
