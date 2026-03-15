from __future__ import annotations

"""DSLType checker for the DSL with support for polymorphism and type variables."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .ast_traverse import ASTTransformer
from .ast_unparse import unparse
from .dsl_ast import (
    ASTNode,
    BinaryOp,
    Boolean,
    BoolLiteral,
    Char,
    CharLiteral,
    Comparisons,
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
    FuncType,
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
    SomeExpr,
    Specification,
    SrcPos,
    StringLiteral,
    TupleExpr,
    TupleType,
    TypeVar,
    UnaryOp,
    VarDecl,
)


class UnreachableError(Exception):
    pass


@dataclass
class TypeScheme:
    """Polymorphic type scheme for let-polymorphism (∀α₁...αₙ.τ)."""

    quantified_vars: List[TypeVar]
    type: DSLType

    def instantiate(self, fresh_var_gen) -> DSLType:
        """Instantiate scheme with fresh type variables."""
        if not self.quantified_vars:
            return self.type

        # Create fresh variables for each quantified variable
        substitution = {var: fresh_var_gen() for var in self.quantified_vars}
        return self._substitute_type(self.type, substitution)

    def _substitute_type(
        self, type_: DSLType, substitution: Dict[TypeVar, TypeVar]
    ) -> DSLType:
        """Apply substitution to a type."""
        if isinstance(type_, TypeVar):
            return substitution.get(type_, type_)
        elif isinstance(type_, ListType):
            return ListType(self._substitute_type(type_.elem, substitution))
        elif isinstance(type_, SetType):
            return SetType(self._substitute_type(type_.elem, substitution))
        elif isinstance(type_, MultisetType):
            return MultisetType(self._substitute_type(type_.elem, substitution))
        elif isinstance(type_, OptionType):
            return OptionType(self._substitute_type(type_.elem, substitution))
        elif isinstance(type_, MapType):
            return MapType(
                self._substitute_type(type_.key, substitution),
                self._substitute_type(type_.value, substitution),
            )
        elif isinstance(type_, RecordType):
            new_fields = {
                name: self._substitute_type(field_type, substitution)
                for name, field_type in type_.fields.items()
            }
            return RecordType(new_fields)
        elif isinstance(type_, FuncType):
            arg_types = [
                self._substitute_type(arg, substitution) for arg in type_.arg_types
            ]
            ret_type = self._substitute_type(type_.ret, substitution)
            return FuncType(arg_types, ret_type)  # type: ignore
        elif isinstance(type_, TupleType):
            elem_types: List[DSLType] = [
                self._substitute_type(elem, substitution) for elem in type_.elem_types
            ]
            return TupleType(elem_types)
        else:
            return type_

    def __str__(self) -> str:
        return (
            f"∀{', '.join(str(var) for var in self.quantified_vars)}. {str(self.type)}"
        )


@dataclass
class TypeConstraint:
    """DSLType constraint for constraint-based type inference."""

    left: DSLType
    right: DSLType
    source_pos: SrcPos
    context: str  # For better error messages

    def __str__(self) -> str:
        return f"{self.left} ~ {self.right} ({self.context})"


class FreshVariableGenerator:
    """Generates fresh type variables for Algorithm W."""

    def __init__(self):
        self.counter = 0

    def fresh_var(self) -> TypeVar:
        """Generate a fresh type variable."""
        self.counter += 1
        return TypeVar()

    def reset(self):
        """Reset counter (useful for testing)."""
        self.counter = 0


@dataclass
class TypeError:
    """DSLType error with source position, message, and code snippet."""

    pos: SrcPos
    message: str
    source_code: Optional[str] = None

    def format_error(self, source_lines: Optional[List[str]] = None) -> str:
        """Format error with source code context."""
        line, col, end_line, end_col = self.pos

        error_msg = f"DSLType error at line {line}, column {col}: {self.message}"

        if source_lines and 1 <= line <= len(source_lines):
            # Add source context with limited span
            source_line = source_lines[line - 1]  # Convert to 0-based indexing

            # Calculate span: show ~20 chars around error location
            span = 20
            start_idx = max(0, col - 1 - span // 2)
            end_idx = min(len(source_line), end_col + span // 2)

            snippet = source_line[start_idx:end_idx]
            prefix = "..." if start_idx > 0 else ""
            suffix = "..." if end_idx < len(source_line) else ""

            error_msg += f"\n  Source: {prefix}{snippet}{suffix}"

            # Add pointer to error location (adjusted for snippet offset)
            if 1 <= col <= len(source_line):
                pointer_offset = col - 1 - start_idx + len(prefix)
                pointer = " " * pointer_offset + "^"
                if end_col > col:
                    pointer += "~" * min(end_col - col - 1, end_idx - col)
                error_msg += f"\n          {pointer}"

        return error_msg

    def __str__(self) -> str:
        if self.source_code:
            lines = self.source_code.split("\n")
            return self.format_error(lines)
        else:
            line, col, _, _ = self.pos
            return f"DSLType error at line {line}, column {col}: {self.message}"


@dataclass
class TypeEnvironment:
    """Environment for tracking variable and function types with polymorphism support."""

    variables: Dict[str, DSLType] = field(default_factory=dict)
    functions: Dict[str, TypeScheme] = field(
        default_factory=dict
    )  # Store schemes for polymorphism
    parent: Optional[TypeEnvironment] = None

    def __str__(self) -> str:
        result = ""
        for var, type_ in self.variables.items():
            result += f"{var}: {type_}\n"
        for func, scheme in self.functions.items():
            result += f"{func}: {scheme}\n"
        return result

    def lookup_var(self, name: str) -> Optional[DSLType]:
        if name in self.variables:
            return self.variables[name]
        if self.parent:
            return self.parent.lookup_var(name)
        return None

    def lookup_func(self, name: str) -> Optional[TypeScheme]:
        if name in self.functions:
            return self.functions[name]
        if self.parent:
            return self.parent.lookup_func(name)
        return None

    def bind_var(self, name: str, type_: DSLType) -> None:
        self.variables[name] = type_

    def bind_func(self, name: str, scheme: TypeScheme) -> None:
        self.functions[name] = scheme

    def child_scope(self) -> TypeEnvironment:
        return TypeEnvironment(parent=self)

    def free_type_vars(self) -> Set[TypeVar]:
        """Get all free type variables in the environment."""
        free_vars = set()

        # Free variables in variable types
        for var_type in self.variables.values():
            free_vars.update(self._get_free_vars(var_type))

        # Free variables in function schemes (already quantified vars are not free)
        for func_scheme in self.functions.values():
            if isinstance(func_scheme, TypeScheme):
                scheme_free = self._get_free_vars(func_scheme.type)
                scheme_free -= set(func_scheme.quantified_vars)
                free_vars.update(scheme_free)
            else:
                # Handle legacy FuncType directly (backward compatibility)
                free_vars.update(self._get_free_vars(func_scheme))

        if self.parent:
            free_vars.update(self.parent.free_type_vars())

        return free_vars

    def _get_free_vars(self, type_: DSLType) -> Set[TypeVar]:
        """Get free type variables in a type."""
        if isinstance(type_, TypeVar):
            return {type_}
        elif isinstance(type_, ListType):
            return self._get_free_vars(type_.elem)
        elif isinstance(type_, SetType):
            return self._get_free_vars(type_.elem)
        elif isinstance(type_, OptionType):
            return self._get_free_vars(type_.elem)
        elif isinstance(type_, FuncType):
            free_vars = set()
            for arg_type in type_.arg_types:
                free_vars.update(self._get_free_vars(arg_type))
            free_vars.update(self._get_free_vars(type_.ret))
            return free_vars
        elif isinstance(type_, TupleType):
            free_vars = set()
            for elem_type in type_.elem_types:
                free_vars.update(self._get_free_vars(elem_type))
            return free_vars
        else:
            return set()

    def generalize(self, type_: DSLType) -> TypeScheme:
        """Generalize a type by quantifying over free variables not in current scope environment."""
        # Get free vars only from current scope (not parent scopes with built-ins)
        current_scope_free_vars = set()

        # Only consider variables and functions in current scope, not parent (built-ins)
        for var_type in self.variables.values():
            current_scope_free_vars.update(self._get_free_vars(var_type))

        for func_scheme in self.functions.values():
            if isinstance(func_scheme, TypeScheme):
                scheme_free = self._get_free_vars(func_scheme.type)
                scheme_free -= set(func_scheme.quantified_vars)
                current_scope_free_vars.update(scheme_free)
            else:
                current_scope_free_vars.update(self._get_free_vars(func_scheme))

        type_free_vars = self._get_free_vars(type_)
        quantify_vars = list(type_free_vars - current_scope_free_vars)

        return TypeScheme(quantify_vars, type_)


class TypeSubstitution(ASTTransformer[ASTNode]):
    """Manages type variable substitutions during unification."""

    def __init__(self) -> None:
        self.substitutions: Dict[TypeVar, DSLType] = {}

    def __str__(self) -> str:
        result = "\n".join([f"{k} -> {v}" for k, v in self.substitutions.items()])
        return result

    def substitute(self, type_: DSLType) -> DSLType:
        """Apply current substitutions to a type."""
        if isinstance(type_, TypeVar):
            if type_ in self.substitutions:
                return self.substitute(self.substitutions[type_])
            return type_
        elif isinstance(type_, NoneLiteralType):
            resolved = self.substitute(type_.target)
            if isinstance(resolved, TypeVar):
                return NoneLiteralType(resolved)
            return resolved
        elif isinstance(type_, ListType):
            return ListType(self.substitute(type_.elem))
        elif isinstance(type_, SetType):
            return SetType(self.substitute(type_.elem))
        elif isinstance(type_, MultisetType):
            return MultisetType(self.substitute(type_.elem))
        elif isinstance(type_, OptionType):
            return OptionType(self.substitute(type_.elem))
        elif isinstance(type_, MapType):
            return MapType(self.substitute(type_.key), self.substitute(type_.value))
        elif isinstance(type_, RecordType):
            new_fields = {
                name: self.substitute(field_type)
                for name, field_type in type_.fields.items()
            }
            return RecordType(new_fields)
        elif isinstance(type_, FuncType):
            arg_types = [self.substitute(arg) for arg in type_.arg_types]
            ret_type = self.substitute(type_.ret)
            return FuncType(arg_types, ret_type)  # type: ignore
        elif isinstance(type_, TupleType):
            elem_types: List[DSLType] = [
                self.substitute(elem) for elem in type_.elem_types
            ]
            return TupleType(elem_types)
        else:
            return type_

    def unify(self, type1: DSLType, type2: DSLType) -> bool:
        """Unify two types, updating substitutions if successful."""
        type1 = self.substitute(type1)
        type2 = self.substitute(type2)

        if type1 == type2:
            return True

        if isinstance(type1, NoneLiteralType):
            return self._unify_none_literal(type1.target, type2)
        elif isinstance(type2, NoneLiteralType):
            return self._unify_none_literal(type2.target, type1)

        if isinstance(type1, TypeVar):
            if self._occurs_check(type1, type2):
                return False
            self.substitutions[type1] = type2
            return True
        elif isinstance(type2, TypeVar):
            if self._occurs_check(type2, type1):
                return False
            self.substitutions[type2] = type1
            return True

        if isinstance(type1, ListType) and isinstance(type2, ListType):
            return self.unify(type1.elem, type2.elem)
        elif isinstance(type1, SetType) and isinstance(type2, SetType):
            return self.unify(type1.elem, type2.elem)
        elif isinstance(type1, MultisetType) and isinstance(type2, MultisetType):
            return self.unify(type1.elem, type2.elem)
        elif isinstance(type1, OptionType) and isinstance(type2, OptionType):
            return self.unify(type1.elem, type2.elem)
        elif isinstance(type1, MapType) and isinstance(type2, MapType):
            return self.unify(type1.key, type2.key) and self.unify(
                type1.value, type2.value
            )
        elif isinstance(type1, RecordType) and isinstance(type2, RecordType):
            # Records must have the same fields
            if set(type1.fields.keys()) != set(type2.fields.keys()):
                return False
            for field_name in type1.fields:
                if not self.unify(type1.fields[field_name], type2.fields[field_name]):
                    return False
            return True
        elif isinstance(type1, FuncType) and isinstance(type2, FuncType):
            if len(type1.arg_types) != len(type2.arg_types):
                return False
            for arg1, arg2 in zip(type1.arg_types, type2.arg_types):
                if not self.unify(arg1, arg2):
                    return False
            return self.unify(type1.ret, type2.ret)
        elif isinstance(type1, TupleType) and isinstance(type2, TupleType):
            if len(type1.elem_types) != len(type2.elem_types):
                return False
            for elem1, elem2 in zip(type1.elem_types, type2.elem_types):
                if not self.unify(elem1, elem2):
                    return False
            return True

        return False

    def _unify_none_literal(self, target: DSLType, other: DSLType) -> bool:
        """Resolve `none` only against nonetype or option[T]."""
        other = self.substitute(other)

        if isinstance(other, NoneLiteralType):
            other = self.substitute(other.target)

        if isinstance(other, TypeVar):
            self.substitutions[other] = DSLNoneType()
            other = DSLNoneType()

        if not isinstance(other, (DSLNoneType, OptionType)):
            return False

        return self.unify(target, other)

    def _occurs_check(self, var: TypeVar, type_: DSLType) -> bool:
        """Check if type variable occurs in type (prevents infinite types)."""
        type_ = self.substitute(type_)
        if isinstance(type_, TypeVar):
            return var == type_
        elif isinstance(type_, (ListType, SetType)):
            return self._occurs_check(var, type_.elem)
        elif isinstance(type_, MultisetType):
            return self._occurs_check(var, type_.elem)
        elif isinstance(type_, NoneLiteralType):
            return self._occurs_check(var, type_.target)
        elif isinstance(type_, OptionType):
            return self._occurs_check(var, type_.elem)
        elif isinstance(type_, MapType):
            return self._occurs_check(var, type_.key) or self._occurs_check(
                var, type_.value
            )
        elif isinstance(type_, RecordType):
            return any(
                self._occurs_check(var, field_type)
                for field_type in type_.fields.values()
            )
        elif isinstance(type_, FuncType):
            return any(
                self._occurs_check(var, arg) for arg in type_.arg_types
            ) or self._occurs_check(var, type_.ret)
        elif isinstance(type_, TupleType):
            return any(self._occurs_check(var, elem) for elem in type_.elem_types)
        return False

    def transform(self, node: ASTNode) -> ASTNode:
        if isinstance(node, Expr):
            node.ty.ty = self.substitute(node.get_type())
        return super().transform(node)


class BuiltinFunctionRegistry:
    """Registry for built-in functions with their polymorphic type schemes."""

    def __init__(self):
        self.functions: Dict[str, TypeScheme] = {}
        self._register_all_builtins()

    def _register_all_builtins(self) -> None:
        """Register all built-in functions."""
        self._register_higher_order_functions()
        self._register_aggregation_functions()
        self._register_set_operations()
        self._register_string_operations()
        self._register_conversion_functions()
        self._register_multiset_functions()
        self._register_math_functions()
        self._register_map_record_functions()

    def _register_higher_order_functions(self) -> None:
        """Register higher-order functions like map, filter, fold."""
        # len: ∀T. list[T] -> int
        len_var = TypeVar()
        len_type = FuncType([ListType(len_var)], Integer())  # type: ignore
        self.functions["len"] = TypeScheme([len_var], len_type)

        # cardinality: ∀T. set[T] -> int
        cardinality_var = TypeVar()
        cardinality_type = FuncType([SetType(cardinality_var)], Integer())  # type: ignore
        self.functions["cardinality"] = TypeScheme([cardinality_var], cardinality_type)

        # map: ∀A,B. (A -> B) -> list[A] -> list[B]
        map_a, map_b = TypeVar(), TypeVar()
        map_func_type = FuncType([map_a], map_b)  # type: ignore
        map_type = FuncType([map_func_type, ListType(map_a)], ListType(map_b))  # type: ignore
        self.functions["map"] = TypeScheme([map_a, map_b], map_type)

        # filter: ∀T. (T -> bool) -> list[T] -> list[T]
        filter_t = TypeVar()
        filter_func_type = FuncType([filter_t], Boolean())  # type: ignore
        filter_type = FuncType(
            [filter_func_type, ListType(filter_t)], ListType(filter_t)
        )  # type: ignore
        self.functions["filter"] = TypeScheme([filter_t], filter_type)

        # fold: ∀A,B. (A -> B -> A) -> A -> list[B] -> A
        fold_a, fold_b = TypeVar(), TypeVar()
        fold_func_type = FuncType([fold_a, fold_b], fold_a)  # type: ignore
        fold_type = FuncType([fold_func_type, fold_a, ListType(fold_b)], fold_a)  # type: ignore
        self.functions["fold"] = TypeScheme([fold_a, fold_b], fold_type)

        # all: ∀T. (T -> bool) -> list[T] -> bool
        all_t = TypeVar()
        all_func_type = FuncType([all_t], Boolean())  # type: ignore
        all_type = FuncType([all_func_type, ListType(all_t)], Boolean())  # type: ignore
        self.functions["all"] = TypeScheme([all_t], all_type)

        # any: ∀T. (T -> bool) -> list[T] -> bool
        any_t = TypeVar()
        any_func_type = FuncType([any_t], Boolean())  # type: ignore
        any_type = FuncType([any_func_type, ListType(any_t)], Boolean())  # type: ignore
        self.functions["any"] = TypeScheme([any_t], any_type)

        # map_i: ∀A,B. (int -> A -> B) -> list[A] -> list[B]
        map_i_a, map_i_b = TypeVar(), TypeVar()
        map_i_func_type = FuncType([Integer(), map_i_a], map_i_b)  # type: ignore
        map_i_type = FuncType([map_i_func_type, ListType(map_i_a)], ListType(map_i_b))  # type: ignore
        self.functions["map_i"] = TypeScheme([map_i_a, map_i_b], map_i_type)

        # fold_i: ∀A,B. (int -> A -> B -> A) -> A -> list[B] -> A
        fold_i_a, fold_i_b = TypeVar(), TypeVar()
        fold_i_func_type = FuncType([Integer(), fold_i_a, fold_i_b], fold_i_a)  # type: ignore
        fold_i_type = FuncType(
            [fold_i_func_type, fold_i_a, ListType(fold_i_b)], fold_i_a
        )  # type: ignore
        self.functions["fold_i"] = TypeScheme([fold_i_a, fold_i_b], fold_i_type)

        # Option helpers
        t = TypeVar()
        self.functions["is_some"] = TypeScheme(
            [t], FuncType([OptionType(t)], Boolean())
        )  # type: ignore
        self.functions["is_none"] = TypeScheme(
            [t], FuncType([OptionType(t)], Boolean())
        )  # type: ignore
        self.functions["unwrap"] = TypeScheme([t], FuncType([OptionType(t)], t))  # type: ignore
        # some: ∀T. T -> option[T]
        self.functions["some"] = TypeScheme([t], FuncType([t], OptionType(t)))  # type: ignore

    def _register_aggregation_functions(self) -> None:
        """Register aggregation functions like sum, max, min."""
        # sum: ∀T. list[T] -> T (where T is numeric)
        sum_t = TypeVar()
        sum_type = FuncType([ListType(sum_t)], sum_t)  # type: ignore
        self.functions["sum"] = TypeScheme([sum_t], sum_type)

        # product: ∀T. list[T] -> T (where T is numeric)
        product_t = TypeVar()
        product_type = FuncType([ListType(product_t)], product_t)  # type: ignore
        self.functions["product"] = TypeScheme([product_t], product_type)

        # max: ∀T. list[T] -> T (where T is comparable)
        max_t = TypeVar()
        max_type = FuncType([ListType(max_t)], max_t)  # type: ignore
        self.functions["max"] = TypeScheme([max_t], max_type)

        # min: ∀T. list[T] -> T (where T is comparable)
        min_t = TypeVar()
        min_type = FuncType([ListType(min_t)], min_t)  # type: ignore
        self.functions["min"] = TypeScheme([min_t], min_type)

        # average/mean: ∀T. list[T] -> real (where T is numeric)
        avg_t = TypeVar()
        avg_type = FuncType([ListType(avg_t)], Real())  # type: ignore
        avg_scheme = TypeScheme([avg_t], avg_type)
        self.functions["average"] = avg_scheme
        self.functions["mean"] = avg_scheme

    def _register_set_operations(self) -> None:
        """Register set operations like union, intersection, etc."""
        # Set operations
        operations = [
            ("set_add", lambda t: FuncType([SetType(t), t], SetType(t))),  # type: ignore
            ("set_del", lambda t: FuncType([SetType(t), t], SetType(t))),  # type: ignore
            ("set_union", lambda t: FuncType([SetType(t), SetType(t)], SetType(t))),  # type: ignore
            ("set_intersect", lambda t: FuncType([SetType(t), SetType(t)], SetType(t))),  # type: ignore
            (
                "set_difference",
                lambda t: FuncType([SetType(t), SetType(t)], SetType(t)),
            ),  # type: ignore
            ("set_complement", lambda t: FuncType([SetType(t)], SetType(t))),  # type: ignore
            (
                "set_is_subset",
                lambda t: FuncType([SetType(t), SetType(t)], Boolean()),
            ),  # type: ignore
            ("set_is_member", lambda t: FuncType([t, SetType(t)], Boolean())),  # type: ignore
            ("set_is_empty", lambda t: FuncType([SetType(t)], Boolean())),  # type: ignore
        ]

        for name, type_factory in operations:
            t = TypeVar()
            func_type = type_factory(t)
            self.functions[name] = TypeScheme([t], func_type)

    def _register_string_operations(self) -> None:
        """Register string operations (strings are represented as list[char])."""
        elem_t = TypeVar()

        # String operations
        operations = [
            (
                "concat",
                FuncType([ListType(elem_t), ListType(elem_t)], ListType(elem_t)),
            ),  # type: ignore
            (
                "contains",
                FuncType([ListType(elem_t), ListType(elem_t)], Boolean()),
            ),  # type: ignore
            (
                "substr",
                FuncType(
                    [ListType(elem_t), Integer(), Integer()],
                    ListType(elem_t),
                ),
            ),  # type: ignore
            (
                "indexof",
                FuncType(
                    [ListType(elem_t), ListType(elem_t), Integer()],
                    Integer(),
                ),
            ),  # type: ignore
            (
                "replace",
                FuncType(
                    [ListType(elem_t), ListType(elem_t), ListType(elem_t)],
                    ListType(elem_t),
                ),
            ),  # type: ignore
            (
                "prefixof",
                FuncType([ListType(elem_t), ListType(elem_t)], Boolean()),
            ),  # type: ignore
            (
                "suffixof",
                FuncType([ListType(elem_t), ListType(elem_t)], Boolean()),
            ),  # type: ignore
        ]

        for name, func_type in operations:
            # Note: elem_t is not quantified for these operations (they work on any specific type)
            self.functions[name] = TypeScheme([elem_t], func_type)

        # String-specific case conversion operations: list[char] -> list[char]
        string_type = ListType(Char())
        self.functions["uppercase"] = TypeScheme(
            [], FuncType([string_type], string_type)
        )  # type: ignore
        self.functions["lowercase"] = TypeScheme(
            [], FuncType([string_type], string_type)
        )  # type: ignore

    def _register_conversion_functions(self) -> None:
        """Register type conversion functions."""
        string_type = ListType(Char())

        # int2str: int -> list[char]
        int2str_type = FuncType([Integer()], string_type)  # type: ignore
        self.functions["int2str"] = TypeScheme([], int2str_type)

        # str2int: list[char] -> int
        str2int_type = FuncType([string_type], Integer())  # type: ignore
        self.functions["str2int"] = TypeScheme([], str2int_type)

        # int2real: int -> real
        int2real_type = FuncType([Integer()], Real())  # type: ignore
        self.functions["int2real"] = TypeScheme([], int2real_type)

        # real2int: real -> int
        real2int_type = FuncType([Real()], Integer())  # type: ignore
        self.functions["real2int"] = TypeScheme([], real2int_type)

        # list2set: ∀T. list[T] -> set[T]
        t = TypeVar()
        list_t = ListType(t)
        set_t = SetType(t)
        self.functions["list2set"] = TypeScheme([t], FuncType([list_t], set_t))  # type: ignore

        # Note: set2list is intentionally not supported

    def _register_multiset_functions(self) -> None:
        """Register multiset-related built-ins."""
        t = TypeVar()
        list_t = ListType(t)
        mset_t = MultisetType(t)
        # list2multiset: ∀T. list[T] -> multiset[T]
        self.functions["list2multiset"] = TypeScheme([t], FuncType([list_t], mset_t))  # type: ignore

    def _register_math_functions(self) -> None:
        """Register basic math functions like abs for integers and reals."""
        # abs: int -> int
        abs_int_type = FuncType([Integer()], Integer())  # type: ignore
        self.functions["abs"] = TypeScheme([], abs_int_type)

        # abs_real: real -> real
        abs_real_type = FuncType([Real()], Real())  # type: ignore
        self.functions["abs_real"] = TypeScheme([], abs_real_type)

        # is_infinite: real -> bool
        is_infinite_type = FuncType([Real()], Boolean())  # type: ignore
        self.functions["is_infinite"] = TypeScheme([], is_infinite_type)

        # is_nan: real -> bool
        is_nan_type = FuncType([Real()], Boolean())  # type: ignore
        self.functions["is_nan"] = TypeScheme([], is_nan_type)

    def _register_map_record_functions(self) -> None:
        """Register map and record iteration functions."""
        # keys: ∀K,V. map[K,V] -> list[K] and ∀fields. record[fields] -> list[string]
        k_var = TypeVar()
        v_var = TypeVar()
        map_type = MapType(k_var, v_var)
        keys_type = FuncType([map_type], ListType(k_var))  # type: ignore
        self.functions["keys"] = TypeScheme([k_var, v_var], keys_type)

        # values: ∀K,V. map[K,V] -> list[V] and ∀fields. record[fields] -> list[union of field types]
        values_type = FuncType([map_type], ListType(v_var))  # type: ignore
        self.functions["values"] = TypeScheme([k_var, v_var], values_type)

        # items: ∀K,V. map[K,V] -> list[tuple[K,V]] and ∀fields. record[fields] -> list[tuple[string, union of field types]]
        tuple_type = TupleType([k_var, v_var])
        items_type = FuncType([map_type], ListType(tuple_type))  # type: ignore
        self.functions["items"] = TypeScheme([k_var, v_var], items_type)

        # has_key: ∀K,V. map[K,V] -> K -> bool and ∀fields. record[fields] -> string -> bool
        has_key_type = FuncType([map_type, k_var], Boolean())  # type: ignore
        self.functions["has_key"] = TypeScheme([k_var, v_var], has_key_type)


class TypeChecker(ASTTransformer[DSLType]):
    def __init__(self, ignore_undefineds: bool = False) -> None:
        self.errors: List[TypeError] = []
        self.substitution = TypeSubstitution()
        self.fresh_var_gen = FreshVariableGenerator()
        self.registry = BuiltinFunctionRegistry()
        self.global_env = TypeEnvironment()
        self.source_code: Optional[str] = None
        self._env_stack: List[TypeEnvironment] = [self.global_env]
        self.ignore_undefineds = ignore_undefineds

        for name, scheme in self.registry.functions.items():
            self.global_env.bind_func(name, scheme)

    @property
    def current_env(self) -> TypeEnvironment:
        return self._env_stack[-1]

    def _push_env(self) -> None:
        self._env_stack.append(self.current_env.child_scope())

    def _pop_env(self) -> None:
        if self._env_stack:
            self._env_stack.pop()

    def _add_error(self, pos: SrcPos, message: str) -> None:
        self.errors.append(TypeError(pos, message, self.source_code))

    def _get_function_type_raw(self, func_def: FunctionDef) -> FuncType:
        arg_types = [arg.get_type() for arg in func_def.args]
        return_type = func_def.return_val.get_type()
        return FuncType(arg_types, return_type)  # type: ignore

    def _get_predicate_type_raw(self, pred_def: PredicateDef) -> FuncType:
        arg_types = [arg.get_type() for arg in pred_def.args]
        return FuncType(arg_types, Boolean())  # type: ignore

    def visit_NumberLiteral(self, node: NumberLiteral) -> DSLType:
        return Integer() if isinstance(node.value, int) else Real()

    def visit_BoolLiteral(self, node: BoolLiteral) -> DSLType:
        return Boolean()

    def visit_StringLiteral(self, node: StringLiteral) -> DSLType:
        return ListType(Char())

    def visit_CharLiteral(self, node: CharLiteral) -> DSLType:
        return Char()

    def visit_NoneLiteral(self, node: NoneLiteral) -> DSLType:
        return node.get_type()

    def visit_SomeExpr(self, node: SomeExpr) -> DSLType:
        """some(value) has type option[T] where T is the type of value."""
        value_type = self.transform(node.value)
        return OptionType(value_type)

    def visit_Identifier(self, node: Identifier) -> DSLType:
        result_type = self.current_env.lookup_var(node.name)
        if result_type is None:
            func_scheme = self.current_env.lookup_func(node.name)
            if func_scheme is not None:
                result_type = func_scheme.instantiate(self.fresh_var_gen.fresh_var)
            elif not self.ignore_undefineds:
                self._add_error(
                    node.pos, f"Undefined variable or function: {node.name}"
                )
                result_type = TypeVar()
            else:
                result_type = TypeVar()
        return result_type

    def visit_BinaryOp(self, node: BinaryOp) -> DSLType:
        left_type = self.transform(node.left)
        right_type = self.transform(node.right)

        if node.op in ["<", "<=", ">", ">=", "==", "!=", "∧", "∨", "==>", "<==>", "in"]:
            result_type = Boolean()
        else:
            result_type = left_type

        if node.op == "in":
            if not isinstance(right_type, (ListType, SetType, MultisetType, TypeVar)):
                self._add_error(
                    node.pos,
                    f"Operation {node.op} requires list, set or multiset, got {right_type}",
                )
            if isinstance(
                right_type, (ListType, SetType, MultisetType)
            ) and not self.substitution.unify(left_type, right_type.elem):
                self._add_error(
                    node.pos,
                    f"Collection type mismatch in binary operation {node.op}: trying to check if {left_type} is in {right_type}",
                )
            return result_type

        if not self.substitution.unify(left_type, right_type):
            self._add_error(
                node.pos,
                f"Type mismatch in binary operation {node.op}: {(left_type)} {node.op} {(right_type)}",
            )
            return result_type

        operand_type = self.substitution.substitute(left_type)
        if node.op == "+":
            if isinstance(operand_type, TupleType):
                self._add_error(
                    node.pos,
                    f"Tuple type is not supported for + operator: {left_type}",
                )
                return TypeVar()
            return operand_type

        elif node.op in ["-", "*", "/", "%", "^"]:
            if operand_type not in [Integer(), Real(), TypeVar()]:
                self._add_error(
                    node.pos,
                    f"Operation {node.op} requires numeric type (integer or real), got {operand_type}",
                )
            return operand_type

        elif node.op in ["∧", "∨", "==>", "<==>"]:
            if not self.substitution.unify(operand_type, Boolean()):
                self._add_error(
                    node.pos,
                    f"Operation {node.op} requires boolean type, got {operand_type}",
                )
            return Boolean()

        elif node.op in [
            "<",
            "<=",
            ">",
            ">=",
        ]:  # Allowed for int, real, char, and string
            if operand_type not in [
                Integer(),
                Real(),
                Char(),
                TypeVar(),
                ListType(Char()),
            ]:
                self._add_error(
                    node.pos,
                    f"Operation {node.op} requires numeric type (integer, real, char, or string), got {operand_type}",
                )
            return Boolean()
        elif node.op in ["==", "!="]:
            return Boolean()
        else:
            self._add_error(node.pos, f"Unknown binary operator: {node.op}")
            return TypeVar()

    def visit_UnaryOp(self, node: UnaryOp) -> DSLType:
        operand_type = self.transform(node.operand)
        if node.op in ["+", "-"]:
            if operand_type not in [Integer(), Real(), TypeVar()]:
                self._add_error(
                    node.pos,
                    f"Arithmetic operator '{node.op}' requires numeric type, got {operand_type}",
                )
            return operand_type
        elif node.op == "¬":
            if not self.substitution.unify(operand_type, Boolean()):
                self._add_error(
                    node.pos,
                    f"Logical negation requires {Boolean()} type, got {operand_type}",
                )
            return Boolean()
        else:
            raise UnreachableError(f"Unknown unary operator: {node.op}")

    def visit_Comparisons(self, node: Comparisons) -> DSLType:
        for comparison in node.comparisons:
            cmp_ty = self.transform(comparison)
            if not self.substitution.unify(cmp_ty, Boolean()):
                self._add_error(
                    comparison.pos,
                    f"Comparison must have type {Boolean()}, got {cmp_ty}",
                )
        return Boolean()

    def visit_IfExpr(self, node: IfExpr) -> DSLType:
        condition_type = self.transform(node.condition)
        if not self.substitution.unify(condition_type, Boolean()):
            self._add_error(
                node.condition.pos,
                f"If condition must have type {Boolean()}, got {condition_type}",
            )
        then_type = self.transform(node.then_branch)
        if node.else_branch:
            else_type = self.transform(node.else_branch)
            if not self.substitution.unify(then_type, else_type):
                self._add_error(
                    node.pos,
                    f"If branches have incompatible types: {then_type} vs {else_type}",
                )
        return then_type

    def visit_LambdaExpr(self, node: LambdaExpr) -> DSLType:
        self._push_env()
        arg_types: List[DSLType] = []
        for arg in node.args:
            arg_types.append(arg.get_type())
            self.current_env.bind_var(arg.name, arg.get_type())
        body_type = self.transform(node.body)
        self._pop_env()
        return FuncType(arg_types, body_type)

    def _visit_Quantifier(self, node: ForallExpr | ExistsExpr) -> DSLType:
        self._push_env()
        for var in node.vars:
            self.current_env.bind_var(var.name, var.get_type())
        satisfies_type = self.transform(node.satisfies_expr)
        if not self.substitution.unify(satisfies_type, Boolean()):
            self._add_error(
                node.satisfies_expr.pos,
                f"Quantifier body must have type {Boolean()}, got {satisfies_type}",
            )
        self._pop_env()
        return Boolean()

    def visit_ForallExpr(self, node: ForallExpr) -> DSLType:
        return self._visit_Quantifier(node)

    def visit_ExistsExpr(self, node: ExistsExpr) -> DSLType:
        return self._visit_Quantifier(node)

    def visit_FuncCall(self, node: FuncCall) -> DSLType:
        # Handle special built-in functions for maps and records
        if isinstance(node.func, Identifier):
            func_name = node.func.name
            if func_name in {"keys", "values", "items", "has_key"}:
                return self._handle_map_record_builtin(node, func_name)

        func_type = self.transform(node.func)
        arg_types = [self.transform(arg) for arg in node.args]

        return_type = TypeVar()
        if len(arg_types) == 0:
            expected_type = return_type
        else:
            expected_type = FuncType(arg_types, return_type)

        if not self.substitution.unify(func_type, expected_type):
            self._add_error(
                node.pos,
                f"Function call type mismatch: trying to call {unparse(node.func)}: {func_type} with arguments ({', '.join(str(arg_type) for arg_type in arg_types)})",
            )
        return return_type

    def visit_ListAccess(self, node: ListAccess) -> DSLType:
        seq_type = self.transform(node.seq)
        if isinstance(seq_type, TypeVar):
            return TypeVar()

        if not (isinstance(seq_type, (ListType, TupleType, MapType, RecordType))):
            self._add_error(
                node.seq.pos,
                f"We can only index lists, tuples, maps, and records, got {seq_type}",
            )
            return TypeVar()

        index_type = self.transform(node.index)
        # Index typing depends on the sequence type
        if isinstance(seq_type, (ListType, TupleType)):
            if not self.substitution.unify(index_type, Integer()):
                self._add_error(
                    node.index.pos,
                    f"List index must be integer, got {index_type}",
                )
        elif isinstance(seq_type, MapType):
            if not self.substitution.unify(index_type, seq_type.key):
                self._add_error(
                    node.index.pos,
                    f"Map index must have key type {seq_type.key}, got {index_type}",
                )
        elif isinstance(seq_type, RecordType):
            # For records, index must be a string literal matching a field name
            if not isinstance(node.index, StringLiteral):
                self._add_error(
                    node.index.pos,
                    f"Record field access requires a string literal, got {index_type}",
                )
                return TypeVar()
            field_name = node.index.value
            if field_name not in seq_type.fields:
                self._add_error(
                    node.index.pos,
                    f"Record has no field '{field_name}'. Available fields: {', '.join(seq_type.fields.keys())}",
                )
                return TypeVar()
            return seq_type.fields[field_name]

        if isinstance(seq_type, ListType):
            return seq_type.elem
        if isinstance(seq_type, MapType):
            return seq_type.value

        if not isinstance(node.index, NumberLiteral):
            self._add_error(
                node.index.pos,
                f"Tuple index must be constant integer, got {node.index}",
            )
            return TypeVar()

        index_val = node.index.value
        assert isinstance(index_val, int)
        return seq_type.elem_types[index_val]

    def visit_FieldAccess(self, node: FieldAccess) -> DSLType:
        record_type = self.transform(node.record)
        if isinstance(record_type, TypeVar):
            return TypeVar()

        if not isinstance(record_type, RecordType):
            self._add_error(
                node.record.pos,
                f"Field access requires a record type, got {record_type}",
            )
            return TypeVar()

        field_name = node.field_name
        if field_name not in record_type.fields:
            self._add_error(
                node.pos,
                f"Record has no field '{field_name}'. Available fields: {', '.join(record_type.fields.keys())}",
            )
            return TypeVar()

        return record_type.fields[field_name]

    def _visit_Explicit_Collection(
        self, node: ExplicitList | ExplicitSet | ExplicitMultiset
    ) -> DSLType:
        expected_elem_ty = TypeVar()
        if isinstance(node, ExplicitList):
            expected_ty = ListType(expected_elem_ty)
        elif isinstance(node, ExplicitSet):
            expected_ty = SetType(expected_elem_ty)
        else:  # ExplicitMultiset
            expected_ty = MultisetType(expected_elem_ty)

        elem_types = [self.transform(e) for e in node.elements]
        if not all(
            self.substitution.unify(elem_type, expected_elem_ty)
            for elem_type in elem_types
        ):
            self._add_error(
                node.pos,
                f"Collection elements must have the same type, got {', '.join(str(e) for e in elem_types)}",
            )

        return expected_ty

    def visit_ExplicitList(self, node: ExplicitList) -> DSLType:
        return self._visit_Explicit_Collection(node)

    def visit_ExplicitSet(self, node: ExplicitSet) -> DSLType:
        return self._visit_Explicit_Collection(node)

    def visit_ExplicitMultiset(self, node: ExplicitMultiset) -> DSLType:
        return self._visit_Explicit_Collection(node)

    def visit_ExplicitRecord(self, node: ExplicitRecord) -> DSLType:
        """Type check record literal: record{ field1: value1, field2: value2, ... }"""
        field_types: dict[str, DSLType] = {}

        # Type check each field value
        for field_name, field_expr in node.fields.items():
            field_type = self.transform(field_expr)
            field_types[field_name] = field_type

        result_type = RecordType(field_types)
        return result_type

    def visit_ExplicitMap(self, node: ExplicitMap) -> DSLType:
        key_ty = TypeVar()
        val_ty = TypeVar()
        for k in node.keys:
            if not self.substitution.unify(self.transform(k), key_ty):
                self._add_error(
                    k.pos, f"Map keys must share one type; got {k.get_type()}"
                )
        for v in node.values:
            if not self.substitution.unify(self.transform(v), val_ty):
                self._add_error(
                    v.pos, f"Map values must share one type; got {v.get_type()}"
                )
        return MapType(
            self.substitution.substitute(key_ty), self.substitution.substitute(val_ty)
        )

    def visit_RangeList(self, node: RangeList) -> DSLType:
        # Allow integer and character ranges. Enforce that both bounds share the same type.
        elem_ty = TypeVar()

        start_type = self.transform(node.start)
        if not self.substitution.unify(start_type, elem_ty):
            self._add_error(
                node.start.pos,
                f"Range start must be a consistent scalar type, got {start_type}",
            )
            return ListType(TypeVar())

        if node.end is not None:
            end_type = self.transform(node.end)
            if not self.substitution.unify(end_type, elem_ty):
                self._add_error(
                    node.end.pos,
                    f"Range end must match start type, got {end_type}",
                )
                return ListType(elem_ty)

        final_elem_ty = self.substitution.substitute(elem_ty)
        if final_elem_ty not in [Integer(), Char(), TypeVar()]:
            self._add_error(
                node.pos,
                f"Range bounds must be int or char, got {final_elem_ty}",
            )

        return ListType(final_elem_ty)

    def visit_RangeSet(self, node: RangeSet) -> DSLType:
        # Allow integer and character ranges. Enforce that both bounds share the same type.
        elem_ty = TypeVar()

        start_type = self.transform(node.start)
        if not self.substitution.unify(start_type, elem_ty):
            self._add_error(
                node.start.pos,
                f"Range start must be a consistent scalar type, got {start_type}",
            )

        if node.end is not None:
            end_type = self.transform(node.end)
            if not self.substitution.unify(end_type, elem_ty):
                self._add_error(
                    node.end.pos,
                    f"Range end must match start type, got {end_type}",
                )

        # Resolve element type and restrict to int or char
        final_elem_ty = self.substitution.substitute(elem_ty)
        if final_elem_ty not in [Integer(), Char(), TypeVar()]:
            self._add_error(
                node.pos,
                f"Range bounds must be int or char, got {final_elem_ty}",
            )

        return SetType(final_elem_ty)

    def _visit_Comprehension(
        self, node: ListComprehension | SetComprehension
    ) -> DSLType:
        self._push_env()
        for g in node.generators:
            self.transform(g.expr)

        for c in node.conditions:
            cond_type = self.transform(c)
            if not self.substitution.unify(cond_type, Boolean()):
                self._add_error(
                    c.pos,
                    f"Comprehension condition must be {Boolean()}, got {cond_type}",
                )

        elem_type = self.transform(node.expr)
        self._pop_env()
        return ListType(elem_type)

    def visit_ListComprehension(self, node: ListComprehension) -> DSLType:
        return self._visit_Comprehension(node)

    def visit_SetComprehension(self, node: SetComprehension) -> DSLType:
        return self._visit_Comprehension(node)

    def visit_Generator(self, node: Generator) -> DSLType:
        self.current_env.bind_var(node.var.name, node.expr.get_type())
        return self.transform(node.expr)

    def visit_TupleExpr(self, node: TupleExpr) -> DSLType:
        elem_types = [self.transform(element) for element in node.elements]
        return TupleType(elem_types)

    def visit_VarDecl(self, node: VarDecl) -> DSLType:
        self.current_env.bind_var(node.var.name, self.transform(node.expr))
        if not self.substitution.unify(node.expr.get_type(), node.var.get_type()):
            self._add_error(
                node.var.pos,
                f"Variable declaration type mismatch: expected {node.var.get_type()}, got {node.expr.get_type()}",
            )
        return node.expr.get_type()

    def visit_Ensure(self, node: Ensure) -> DSLType:
        return self.transform(node.expr)

    def visit_Require(self, node: Require) -> DSLType:
        return self.transform(node.expr)

    def visit_PredicateDef(self, node: PredicateDef) -> DSLType:
        arg_types = [arg.get_type() for arg in node.args]
        f_type = FuncType(arg_types, Boolean())
        if node.body is None:
            return f_type

        self._push_env()
        for arg in node.args:
            self.current_env.bind_var(arg.name, arg.get_type())
        for var_decl in node.var_decls:
            self.transform(var_decl)
        body_type = self.transform(node.body)
        self._pop_env()

        if not self.substitution.unify(body_type, Boolean()):
            self._add_error(
                node.body.pos,
                f"Predicate body must have type {Boolean()}, got {body_type}",
            )
        return f_type

    def visit_FunctionDef(self, node: FunctionDef) -> DSLType:
        arg_types = [arg.get_type() for arg in node.args]
        f_type = FuncType(arg_types, node.return_val.get_type())

        self._push_env()
        for arg in node.args:
            self.current_env.bind_var(arg.name, arg.get_type())
        self.current_env.bind_var(node.return_val.name, node.return_val.get_type())
        for var_decl in node.var_decls:
            self.transform(var_decl)

        for require in node.requires:
            self.transform(require)
        for ensure in node.ensures:
            self.transform(ensure)

        if node.body is not None:
            body_type = self.transform(node.body)
            if not self.substitution.unify(body_type, f_type.ret):
                self._add_error(
                    node.body.pos,
                    f"Function body must have type {f_type.ret}, got {body_type}",
                )
        self._pop_env()

        return f_type

    def visit_Specification(self, node: Specification):
        self._push_env()
        # === PHASE 1: Collect raw function signatures (no generalization) ===
        for decl in node.declarations:
            if isinstance(decl, FunctionDef):
                func_type = self._get_function_type_raw(decl)
            elif isinstance(decl, PredicateDef):
                func_type = self._get_predicate_type_raw(decl)

            if len(func_type.arg_types) == 0:
                self.current_env.bind_var(decl.name, func_type.ret)
            else:
                self.current_env.bind_func(decl.name, TypeScheme([], func_type))

        # === PHASE 2: Type check the specification ===
        for decl in node.declarations:
            self.transform(decl)

        # === PHASE 3: Generalize type schemes ===
        for decl in node.declarations:
            f_name = decl.name
            old_scheme = self.current_env.lookup_func(f_name)
            if old_scheme is None:
                continue
            new_scheme = self.current_env.generalize(old_scheme.type)
            self.current_env.bind_func(f_name, new_scheme)

        # === PHASE 4: Substitute type variables ===
        self.substitution.transform(node)

        self._pop_env()

        return Boolean()

    def transform(self, node: ASTNode):
        transformed = super().transform(node)
        if isinstance(node, Expr):
            if not self.substitution.unify(transformed, node.get_type()):
                self._add_error(
                    node.pos,
                    f"Type mismatch: expected {node.get_type()}, got {transformed}",
                )
        return self.substitution.substitute(transformed)

    def _handle_map_record_builtin(self, node: FuncCall, func_name: str) -> DSLType:
        """Handle built-in functions for maps and records with special typing."""
        if func_name == "keys":
            if len(node.args) != 1:
                self._add_error(node.pos, "keys() takes exactly one argument")
                return TypeVar()
            arg_type = self.transform(node.args[0])
            if isinstance(arg_type, RecordType):
                return ListType(ListType(Char()))  # list[string]
            elif isinstance(arg_type, MapType):
                return ListType(arg_type.key)
            else:
                self._add_error(node.pos, f"keys() not supported for type {arg_type}")
                return TypeVar()

        elif func_name == "values":
            if len(node.args) != 1:
                self._add_error(node.pos, "values() takes exactly one argument")
                return TypeVar()
            arg_type = self.transform(node.args[0])
            if isinstance(arg_type, RecordType):
                # For records, values have different types - use a union type
                # For simplicity, we'll use a type variable that can unify with any field type
                return ListType(TypeVar())
            elif isinstance(arg_type, MapType):
                return ListType(arg_type.value)
            else:
                self._add_error(node.pos, f"values() not supported for type {arg_type}")
                return TypeVar()

        elif func_name == "items":
            if len(node.args) != 1:
                self._add_error(node.pos, "items() takes exactly one argument")
                return TypeVar()
            arg_type = self.transform(node.args[0])
            if isinstance(arg_type, RecordType):
                # For records, items are (string, field_value) tuples
                return ListType(
                    TupleType([ListType(Char()), TypeVar()])
                )  # list[tuple[string, T]]
            elif isinstance(arg_type, MapType):
                return ListType(TupleType([arg_type.key, arg_type.value]))
            else:
                self._add_error(node.pos, f"items() not supported for type {arg_type}")
                return TypeVar()

        elif func_name == "has_key":
            if len(node.args) != 2:
                self._add_error(node.pos, "has_key() takes exactly two arguments")
                return TypeVar()
            map_type = self.transform(node.args[0])
            key_type = self.transform(node.args[1])

            if isinstance(map_type, RecordType):
                # For records, key must be string
                if not self.substitution.unify(key_type, ListType(Char())):
                    self._add_error(
                        node.args[1].pos,
                        f"has_key() for records requires string key, got {key_type}",
                    )
                return Boolean()
            elif isinstance(map_type, MapType):
                # For maps, key must match map's key type
                if not self.substitution.unify(key_type, map_type.key):
                    self._add_error(
                        node.args[1].pos,
                        f"has_key() key type {key_type} doesn't match map key type {map_type.key}",
                    )
                return Boolean()
            else:
                self._add_error(
                    node.pos, f"has_key() not supported for type {map_type}"
                )
                return TypeVar()

        return TypeVar()

    def check(self, node: Specification) -> List[TypeError]:
        self.errors = []
        self.substitution = TypeSubstitution()
        self.fresh_var_gen = FreshVariableGenerator()
        self.transform(node)
        return self.errors


def type_check(spec: Specification) -> List[TypeError]:
    """Main entry point for type checking."""
    return TypeChecker().check(spec)
