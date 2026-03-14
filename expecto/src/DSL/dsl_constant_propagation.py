from __future__ import annotations

import math
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from typing import Iterator, Mapping, Optional, cast

from .ast_traverse import ASTTransformer
from .dsl_ast import (
    ASTNode,
    BinaryOp,
    BoolLiteral,
    Char,
    CharLiteral,
    Comparisons,
    ExplicitList,
    ExplicitMap,
    ExplicitMultiset,
    ExplicitRecord,
    ExplicitSet,
    Expr,
    FieldAccess,
    FuncCall,
    Identifier,
    IfExpr,
    LambdaExpr,
    ListAccess,
    ListType,
    NoneLiteral,
    NumberLiteral,
    RangeList,
    RangeSet,
    SomeExpr,
    StringLiteral,
    TupleExpr,
    UnaryOp,
)


class ConstantPropagation(ASTTransformer[ASTNode]):
    """Propagate constants such as len(constant) and s[i] with constant s and i."""

    def __init__(self):
        # Environment stack mapping identifier names to optional constant expressions.
        # None marks a symbol as intentionally unbound (e.g., lambda parameters).
        self._env_stack: list[dict[str, Expr | None]] = []

    def _lookup_binding(self, name: str) -> Expr | None:
        for scope in reversed(self._env_stack):
            if name in scope:
                return scope[name]
        return None

    @contextmanager
    def _scoped_bindings(
        self, bindings: Optional[Mapping[str, Expr | None]] = None
    ) -> Iterator[None]:
        self._env_stack.append({})
        try:
            if bindings:
                self._env_stack[-1].update(bindings)
            yield
        finally:
            self._env_stack.pop()

    def visit_Identifier(self, node: Identifier) -> Expr:
        bound = self._lookup_binding(node.name)
        if bound is not None:
            return bound
        return node

    def visit_LambdaExpr(self, node: LambdaExpr) -> Expr:
        shadow_bindings = {arg.name: None for arg in node.args}
        with self._scoped_bindings(shadow_bindings):
            body = self.transform(node.body)
            assert isinstance(body, Expr)
            return replace(node, body=body)

    def _is_const_int(self, node: Expr) -> Optional[int]:
        if isinstance(node, NumberLiteral) and isinstance(node.value, int):
            return int(node.value)
        return None

    def _is_const_str(self, node: Expr) -> Optional[str]:
        if isinstance(node, StringLiteral):
            return node.value
        if isinstance(node, ExplicitList) and node.ty.ty == ListType(Char()):
            return "".join(e.value for e in node.elements)  # type: ignore
        return None

    def _is_const_num(self, node: Expr) -> Optional[int | float]:
        if isinstance(node, NumberLiteral):
            return node.value
        return None

    def _is_const_bool(self, node: Expr) -> Optional[bool]:
        if isinstance(node, BoolLiteral):
            return node.value
        return None

    def _is_none(self, node: Expr) -> bool:
        if isinstance(node, NoneLiteral):
            return True
        return False

    def _len_of(self, expr: Expr) -> Optional[int]:
        s = self._is_const_str(expr)
        if s is not None:
            return len(s)
        if isinstance(expr, ExplicitList):
            return len(expr.elements)
        if isinstance(expr, RangeList):
            elems = self._expand_range_elements(expr.start, expr.end)
            if elems is not None:
                return len(elems)
        return None

    def _index_str(self, s_expr: Expr, idx_expr: Expr) -> Optional[Expr]:
        s = self._is_const_str(s_expr)
        i = self._is_const_int(idx_expr)
        if s is None or i is None:
            return None
        if 0 <= i < len(s):
            return CharLiteral(pos=s_expr.pos, value=s[i])
        return None

    # ------------------- helpers: constant extraction/builders -------------------
    def _expand_range_elements(
        self, start: Expr, end: Optional[Expr]
    ) -> list[Expr] | None:
        # Numeric literal ranges
        if isinstance(start, NumberLiteral) and (
            end is None or isinstance(end, NumberLiteral)
        ):
            lo = int(start.value)
            hi = int(end.value) if isinstance(end, NumberLiteral) else lo
            rng = range(lo, hi + 1) if lo <= hi else []
            return [NumberLiteral(value=i) for i in rng]
        # Char literal ranges
        if isinstance(start, CharLiteral) and (
            end is None or isinstance(end, CharLiteral)
        ):
            s = start.value
            e = end.value if isinstance(end, CharLiteral) else s
            if len(s) == 1 and len(e) == 1:
                lo = ord(s)
                hi = ord(e)
                rng = range(lo, hi + 1) if lo <= hi else []
                return [CharLiteral(value=chr(i)) for i in rng]
        return None

    def _const_list_elems(self, expr: Expr) -> list[Expr] | None:
        # Treat string literals and explicit char lists as lists of chars
        s = self._is_const_str(expr)
        if s is not None:
            return [CharLiteral(value=c) for c in s]
        if isinstance(expr, ExplicitList):
            return list(expr.elements)
        if isinstance(expr, RangeList):
            return self._expand_range_elements(expr.start, expr.end)
        return None

    def _const_set_elems(self, expr: Expr) -> list[Expr] | None:
        if isinstance(expr, ExplicitSet):
            return list(expr.elements)
        if isinstance(expr, RangeSet):
            return self._expand_range_elements(expr.start, expr.end)
        # list2set input handled separately where needed
        return None

    def _const_multiset_elems(self, expr: Expr) -> list[Expr] | None:
        if isinstance(expr, ExplicitMultiset):
            return list(expr.elements)
        if isinstance(expr, RangeSet):
            return self._expand_range_elements(expr.start, expr.end)
        # list2multiset input handled separately where needed
        return None

    def _const_map_elems(self, expr: Expr) -> tuple[list[Expr], list[Expr]] | None:
        """Extract constant map key-value pairs."""
        if isinstance(expr, ExplicitMap):
            return list(expr.keys), list(expr.values)
        return None

    def _const_tuple_elems(self, expr: Expr) -> list[Expr] | None:
        """Extract constant tuple elements."""
        if isinstance(expr, TupleExpr):
            return list(expr.elements)
        return None

    def _const_record_fields(self, expr: Expr) -> dict[str, Expr] | None:
        """Extract constant record fields."""
        if isinstance(expr, ExplicitRecord):
            return dict(expr.fields)
        return None

    def _value_key(self, e: Expr) -> object | None:
        # Hashable key for comparing constant elements
        if isinstance(e, NumberLiteral):
            return e.value
        if isinstance(e, BoolLiteral):
            return e.value
        if isinstance(e, NoneLiteral):
            return ("none",)
        if isinstance(e, CharLiteral):
            return ("char", e.value)
        if isinstance(e, StringLiteral):
            return ("str", e.value)
        if isinstance(e, SomeExpr):
            inner_key = self._value_key(e.value)
            if inner_key is not None:
                return ("some", inner_key)
            return None
        # Allow comparing explicit char lists by their string
        s = self._is_const_str(e)
        if s is not None:
            return ("str", s)
        # Handle maps
        map_elems = self._const_map_elems(e)
        if map_elems is not None:
            keys, values = map_elems
            key_keys = [self._value_key(k) for k in keys]
            val_keys = [self._value_key(v) for v in values]
            if None not in key_keys and None not in val_keys:
                return ("map", tuple(zip(key_keys, val_keys)))
        # Handle tuples
        tuple_elems = self._const_tuple_elems(e)
        if tuple_elems is not None:
            elem_keys = [self._value_key(elem) for elem in tuple_elems]
            if None not in elem_keys:
                return ("tuple", tuple(elem_keys))
        return None

    def _mk_string(self, node: FuncCall, s: str) -> StringLiteral:
        return StringLiteral(pos=node.pos, value=s, ty=node.ty)

    def _mk_list(self, node: FuncCall, elems: list[Expr]) -> ExplicitList:
        return ExplicitList(pos=node.pos, elements=elems, ty=node.ty)

    def _mk_set(self, node: FuncCall, elems: list[Expr]) -> ExplicitSet:
        return ExplicitSet(pos=node.pos, elements=elems, ty=node.ty)

    def _mk_multiset(self, node: FuncCall, elems: list[Expr]) -> ExplicitMultiset:
        return ExplicitMultiset(pos=node.pos, elements=elems, ty=node.ty)

    def _mk_map(
        self, node: FuncCall, keys: list[Expr], values: list[Expr]
    ) -> ExplicitMap:
        return ExplicitMap(pos=node.pos, keys=keys, values=values, ty=node.ty)

    def _canonicalize_map_entries(
        self, keys: list[Expr], values: list[Expr]
    ) -> tuple[list[Expr], list[Expr]]:
        order: list[object] = []
        entries: dict[object, tuple[Expr, Expr]] = {}
        for key_expr, value_expr in zip(keys, values):
            key = self._value_key(key_expr)
            if key is None:
                return keys, values
            if key not in entries:
                order.append(key)
            entries[key] = (key_expr, value_expr)
        out_keys: list[Expr] = []
        out_values: list[Expr] = []
        for key in order:
            key_expr, value_expr = entries[key]
            out_keys.append(key_expr)
            out_values.append(value_expr)
        return out_keys, out_values

    def _mk_tuple(self, node: FuncCall, elems: list[Expr]) -> TupleExpr:
        return TupleExpr(pos=node.pos, elements=elems, ty=node.ty)

    def _mk_seq_from_elems(self, node: FuncCall, elems: list[Expr]) -> Expr:
        ty = node.ty.ty
        if isinstance(ty, ListType) and isinstance(ty.elem, Char):
            if all(isinstance(e, CharLiteral) for e in elems):
                return self._mk_string(
                    node, "".join(cast(CharLiteral, e).value for e in elems)
                )
        return self._mk_list(node, elems)

    def _as_lambda(self, expr: Expr) -> Optional[LambdaExpr]:
        if isinstance(expr, LambdaExpr):
            return expr
        return None

    def _apply_lambda(self, fn_expr: Expr, arg_values: list[Expr]) -> Expr | None:
        lam = self._as_lambda(fn_expr)
        if lam is None or len(lam.args) != len(arg_values):
            return None
        bindings = {param.name: arg for param, arg in zip(lam.args, arg_values)}
        with self._scoped_bindings(bindings):
            result = self.transform(lam.body)
            assert isinstance(result, Expr)
            return result

    def _is_constant_expr(self, expr: Expr) -> bool:
        if self._value_key(expr) is not None:
            return True
        if isinstance(expr, NoneLiteral):
            return True
        if isinstance(expr, SomeExpr):
            return self._is_constant_expr(expr.value)
        list_elems = self._const_list_elems(expr)
        if list_elems is not None:
            return all(self._is_constant_expr(e) for e in list_elems)
        set_elems = self._const_set_elems(expr)
        if set_elems is not None:
            return all(self._is_constant_expr(e) for e in set_elems)
        multiset_elems = self._const_multiset_elems(expr)
        if multiset_elems is not None:
            return all(self._is_constant_expr(e) for e in multiset_elems)
        map_elems = self._const_map_elems(expr)
        if map_elems is not None:
            keys, values = map_elems
            return all(self._is_constant_expr(k) for k in keys) and all(
                self._is_constant_expr(v) for v in values
            )
        tuple_elems = self._const_tuple_elems(expr)
        if tuple_elems is not None:
            return all(self._is_constant_expr(e) for e in tuple_elems)
        record_fields = self._const_record_fields(expr)
        if record_fields is not None:
            return all(self._is_constant_expr(v) for v in record_fields.values())
        return False

    def _mk_constant_option(self, node: FuncCall, value: Expr) -> Expr:
        """Create a constant option value for some(constant)."""
        # For now, we'll just return the original some(constant) call
        # but mark it as a constant option for further optimization
        # In a more sophisticated implementation, we could create a special
        # constant option node that can be optimized by is_some, is_none, etc.
        return replace(node, func=node.func, args=node.args, ty=node.ty)

    def visit_FuncCall(self, node: FuncCall):
        func = self.transform(node.func)
        args = [self.transform(a) for a in node.args]
        node = replace(node, func=func, args=args)
        if isinstance(func, Identifier):
            fname = func.name
            # ---------------------------- option helpers ----------------------------
            if fname in {"is_some", "is_none", "unwrap"} and len(args) == 1:
                arg0 = args[0]
                if isinstance(arg0, NoneLiteral):
                    if fname == "is_some":
                        return BoolLiteral(pos=node.pos, value=False, ty=node.ty)
                    if fname == "is_none":
                        return BoolLiteral(pos=node.pos, value=True, ty=node.ty)
                    # unwrap(None) cannot be folded safely to a concrete value
                    # Leave as-is for solver/type checker to handle

                # Optimize is_some(SomeExpr) -> true
                if fname == "is_some" and isinstance(arg0, SomeExpr):
                    return BoolLiteral(pos=node.pos, value=True, ty=node.ty)

                # Optimize is_none(SomeExpr) -> false
                if fname == "is_none" and isinstance(arg0, SomeExpr):
                    return BoolLiteral(pos=node.pos, value=False, ty=node.ty)

                # Optimize unwrap(SomeExpr) -> value
                if fname == "unwrap" and isinstance(arg0, SomeExpr):
                    return arg0.value

            # some constructor: T -> option[T]
            if fname == "some" and len(args) == 1:
                arg0 = cast(Expr, args[0])
                # Convert some(value) to SomeExpr for better constant propagation
                return SomeExpr(pos=node.pos, value=arg0, ty=node.ty)
            # len
            if fname == "len" and len(args) == 1:
                assert isinstance(args[0], Expr)
                n = self._len_of(args[0])
                if n is not None:
                    return NumberLiteral(pos=node.pos, value=n, ty=node.ty)

            if fname in {"is_infinite", "is_nan"} and len(args) == 1:
                arg0 = args[0]
                if isinstance(arg0, NumberLiteral) and isinstance(
                    arg0.value, (int, float)
                ):
                    if fname == "is_infinite":
                        result = math.isinf(float(arg0.value))
                    else:
                        result = math.isnan(float(arg0.value))
                    return BoolLiteral(pos=node.pos, value=result, ty=node.ty)

            # ----------------------- higher-order sequence ops -----------------------
            if fname == "map" and len(args) == 2:
                fn_expr = cast(Expr, args[0])
                seq_expr = cast(Expr, args[1])
                lam = self._as_lambda(fn_expr)
                elems = self._const_list_elems(seq_expr)
                if lam is not None and elems is not None:
                    out: list[Expr] = []
                    for elem in elems:
                        applied = self._apply_lambda(lam, [elem])
                        if applied is None or not self._is_constant_expr(applied):
                            break
                        out.append(applied)
                    else:
                        return self._mk_seq_from_elems(node, out)

            elif fname == "map_i" and len(args) == 2:
                fn_expr = cast(Expr, args[0])
                seq_expr = cast(Expr, args[1])
                lam = self._as_lambda(fn_expr)
                elems = self._const_list_elems(seq_expr)
                if lam is not None and elems is not None and len(lam.args) == 2:
                    out: list[Expr] = []
                    for idx, elem in enumerate(elems):
                        idx_expr = NumberLiteral(pos=node.pos, value=idx)
                        applied = self._apply_lambda(lam, [idx_expr, elem])
                        if applied is None or not self._is_constant_expr(applied):
                            break
                        out.append(applied)
                    else:
                        return self._mk_seq_from_elems(node, out)

            elif fname == "filter" and len(args) == 2:
                fn_expr = cast(Expr, args[0])
                seq_expr = cast(Expr, args[1])
                lam = self._as_lambda(fn_expr)
                elems = self._const_list_elems(seq_expr)
                if lam is not None and elems is not None and len(lam.args) == 1:
                    out: list[Expr] = []
                    for elem in elems:
                        applied = self._apply_lambda(lam, [elem])
                        if applied is None:
                            break
                        keep = self._is_const_bool(applied)
                        if keep is None:
                            break
                        if keep:
                            out.append(elem)
                    else:
                        return self._mk_seq_from_elems(node, out)

            elif fname == "fold" and len(args) == 3:
                fn_expr = cast(Expr, args[0])
                acc_expr = cast(Expr, args[1])
                seq_expr = cast(Expr, args[2])
                lam = self._as_lambda(fn_expr)
                elems = self._const_list_elems(seq_expr)
                if (
                    lam is not None
                    and elems is not None
                    and len(lam.args) == 2
                    and self._is_constant_expr(acc_expr)
                ):
                    acc_val: Expr = acc_expr
                    for elem in elems:
                        applied = self._apply_lambda(lam, [acc_val, elem])
                        if applied is None or not self._is_constant_expr(applied):
                            break
                        acc_val = applied
                    else:
                        return acc_val

            elif fname == "fold_i" and len(args) == 3:
                fn_expr = cast(Expr, args[0])
                acc_expr = cast(Expr, args[1])
                seq_expr = cast(Expr, args[2])
                lam = self._as_lambda(fn_expr)
                elems = self._const_list_elems(seq_expr)
                if (
                    lam is not None
                    and elems is not None
                    and len(lam.args) == 3
                    and self._is_constant_expr(acc_expr)
                ):
                    acc_val: Expr = acc_expr
                    for idx, elem in enumerate(elems):
                        idx_expr = NumberLiteral(pos=node.pos, value=idx)
                        applied = self._apply_lambda(lam, [idx_expr, acc_val, elem])
                        if applied is None or not self._is_constant_expr(applied):
                            break
                        acc_val = applied
                    else:
                        return acc_val

            elif fname == "all" and len(args) == 2:
                fn_expr = cast(Expr, args[0])
                seq_expr = cast(Expr, args[1])
                lam = self._as_lambda(fn_expr)
                elems = self._const_list_elems(seq_expr)
                if lam is not None and elems is not None and len(lam.args) == 1:
                    # Handle empty list: all on empty list is True (vacuous truth)
                    if len(elems) == 0:
                        return BoolLiteral(pos=node.pos, value=True, ty=node.ty)
                    # Apply predicate to each element
                    for elem in elems:
                        applied = self._apply_lambda(lam, [elem])
                        if applied is None:
                            break
                        keep = self._is_const_bool(applied)
                        if keep is None:
                            break
                        # If any element fails the predicate, return False early
                        if not keep:
                            return BoolLiteral(pos=node.pos, value=False, ty=node.ty)
                    else:
                        # All elements satisfied the predicate
                        return BoolLiteral(pos=node.pos, value=True, ty=node.ty)

            elif fname == "any" and len(args) == 2:
                fn_expr = cast(Expr, args[0])
                seq_expr = cast(Expr, args[1])
                lam = self._as_lambda(fn_expr)
                elems = self._const_list_elems(seq_expr)
                if lam is not None and elems is not None and len(lam.args) == 1:
                    # Handle empty list: any on empty list is False
                    if len(elems) == 0:
                        return BoolLiteral(pos=node.pos, value=False, ty=node.ty)
                    # Apply predicate to each element
                    for elem in elems:
                        applied = self._apply_lambda(lam, [elem])
                        if applied is None:
                            break
                        keep = self._is_const_bool(applied)
                        if keep is None:
                            break
                        # If any element satisfies the predicate, return True early
                        if keep:
                            return BoolLiteral(pos=node.pos, value=True, ty=node.ty)
                    else:
                        # No element satisfied the predicate
                        return BoolLiteral(pos=node.pos, value=False, ty=node.ty)

            # ---------------------------- string operations ----------------------------
            # Treat strings as list[char]; prefer StringLiteral results when applicable
            if fname == "concat" and len(args) == 2:
                s1 = self._is_const_str(cast(Expr, args[0]))
                s2 = self._is_const_str(cast(Expr, args[1]))
                if s1 is not None and s2 is not None:
                    return self._mk_string(node, s1 + s2)
                l1 = self._const_list_elems(cast(Expr, args[0]))
                l2 = self._const_list_elems(cast(Expr, args[1]))
                if l1 is not None and l2 is not None:
                    # If both are strings but came as lists, still emit StringLiteral
                    if all(isinstance(e, CharLiteral) for e in l1) and all(
                        isinstance(e, CharLiteral) for e in l2
                    ):
                        return self._mk_string(
                            node,
                            "".join(
                                [e.value for e in cast(list[CharLiteral], l1 + l2)]
                            ),
                        )
                    return self._mk_list(node, l1 + l2)

            elif fname == "contains" and len(args) == 2:
                hay = self._is_const_str(cast(Expr, args[0]))
                needle = self._is_const_str(cast(Expr, args[1]))
                if hay is not None and needle is not None:
                    return BoolLiteral(pos=node.pos, value=(needle in hay), ty=node.ty)

            elif fname == "substr" and len(args) == 3:
                s = self._is_const_str(cast(Expr, args[0]))
                elems = self._const_list_elems(cast(Expr, args[0]))
                begin = self._is_const_int(cast(Expr, args[1]))
                length = self._is_const_int(cast(Expr, args[2]))
                if (
                    s is not None
                    and begin is not None
                    and length is not None
                    and begin >= 0
                    and length >= 0
                ):
                    return self._mk_string(node, s[begin : begin + length])
                if (
                    elems is not None
                    and begin is not None
                    and length is not None
                    and begin >= 0
                    and length >= 0
                ):
                    return self._mk_seq_from_elems(node, elems[begin : begin + length])

            elif fname == "indexof" and len(args) == 3:
                s = self._is_const_str(cast(Expr, args[0]))
                sub = self._is_const_str(cast(Expr, args[1]))
                start = self._is_const_int(cast(Expr, args[2]))
                if (
                    s is not None
                    and sub is not None
                    and start is not None
                    and start >= 0
                ):
                    return NumberLiteral(
                        pos=node.pos, value=s.find(sub, start), ty=node.ty
                    )

            elif fname == "replace" and len(args) == 3:
                s = self._is_const_str(cast(Expr, args[0]))
                old = self._is_const_str(cast(Expr, args[1]))
                new = self._is_const_str(cast(Expr, args[2]))
                if s is not None and old is not None and new is not None:
                    return self._mk_string(node, s.replace(old, new))

            elif fname == "prefixof" and len(args) == 2:
                a = self._is_const_str(cast(Expr, args[0]))
                b = self._is_const_str(cast(Expr, args[1]))
                if a is not None and b is not None:
                    return BoolLiteral(pos=node.pos, value=b.startswith(a), ty=node.ty)

            elif fname == "suffixof" and len(args) == 2:
                a = self._is_const_str(cast(Expr, args[0]))
                b = self._is_const_str(cast(Expr, args[1]))
                if a is not None and b is not None:
                    return BoolLiteral(pos=node.pos, value=b.endswith(a), ty=node.ty)

            elif fname == "uppercase" and len(args) == 1:
                s = self._is_const_str(cast(Expr, args[0]))
                if s is not None:
                    return self._mk_string(node, s.upper())

            elif fname == "lowercase" and len(args) == 1:
                s = self._is_const_str(cast(Expr, args[0]))
                if s is not None:
                    return self._mk_string(node, s.lower())

            elif fname == "int2str" and len(args) == 1:
                n = self._is_const_int(cast(Expr, args[0]))
                if n is not None:
                    return self._mk_string(node, str(n))

            elif fname == "str2int" and len(args) == 1:
                s = self._is_const_str(cast(Expr, args[0]))
                if s is not None:
                    try:
                        val = int(s)
                    except Exception:
                        val = -1
                    return NumberLiteral(pos=node.pos, value=val, ty=node.ty)

            # -------------------------- numeric aggregations --------------------------
            elif (
                fname in {"sum", "product", "max", "min", "average", "mean"}
                and len(args) == 1
            ):
                elems = self._const_list_elems(cast(Expr, args[0]))
                if (
                    elems is not None
                    and len(elems) > 0
                    and all(isinstance(e, NumberLiteral) for e in elems)
                ):
                    numbers = [cast(NumberLiteral, e).value for e in elems]
                    try:
                        if fname == "sum":
                            val = sum(numbers)  # type: ignore[arg-type]
                        elif fname == "product":
                            prod = 1
                            for v in numbers:
                                prod *= v  # type: ignore[operator]
                            val = prod
                        elif fname == "max":
                            val = max(numbers)
                        elif fname == "min":
                            val = min(numbers)
                        else:  # average/mean
                            val = sum(numbers) / len(numbers)  # type: ignore[operator]
                        return NumberLiteral(pos=node.pos, value=val, ty=node.ty)
                    except Exception:
                        pass

            elif fname in {"abs", "abs_real"} and len(args) == 1:
                n = self._is_const_num(cast(Expr, args[0]))
                if n is not None:
                    return NumberLiteral(pos=node.pos, value=abs(n), ty=node.ty)

            # ------------------------------- set operations -------------------------------
            elif fname == "list2set" and len(args) == 1:
                elems = self._const_list_elems(cast(Expr, args[0]))
                if elems is not None:
                    # Deduplicate while preserving order by value
                    seen: set[object] = set()
                    out: list[Expr] = []
                    for e in elems:
                        k = self._value_key(e)
                        if k is not None and k not in seen:
                            seen.add(k)
                            out.append(e)
                    return self._mk_set(node, out)

            # ------------------------------- multiset operations -------------------------------
            elif fname == "list2multiset" and len(args) == 1:
                elems = self._const_list_elems(cast(Expr, args[0]))
                if elems is not None:
                    # Keep all elements (including duplicates) for multiset
                    return self._mk_multiset(node, elems)

            # ------------------------------- map operations -------------------------------
            elif fname == "map_add" and len(args) == 3:
                map_elems = self._const_map_elems(cast(Expr, args[0]))
                key = self._value_key(cast(Expr, args[1]))
                value = self._value_key(cast(Expr, args[2]))
                if map_elems is not None and key is not None and value is not None:
                    keys, values = map_elems
                    keys.append(cast(Expr, args[1]))
                    values.append(cast(Expr, args[2]))
                    keys, values = self._canonicalize_map_entries(keys, values)
                    return self._mk_map(node, keys, values)

            elif fname == "map_keys" and len(args) == 1:
                map_elems = self._const_map_elems(cast(Expr, args[0]))
                if map_elems is not None:
                    keys, _ = map_elems
                    return self._mk_list(node, keys)

            elif fname == "map_values" and len(args) == 1:
                map_elems = self._const_map_elems(cast(Expr, args[0]))
                if map_elems is not None:
                    _, values = map_elems
                    return self._mk_list(node, values)

            elif fname == "map_get" and len(args) == 2:
                map_elems = self._const_map_elems(cast(Expr, args[0]))
                key = self._value_key(cast(Expr, args[1]))
                if map_elems is not None and key is not None:
                    keys, values = map_elems
                    for i in range(len(keys) - 1, -1, -1):
                        k = keys[i]
                        if self._value_key(k) == key:
                            return values[i]
                    # Key not found, return None or handle appropriately
                    return NoneLiteral(pos=node.pos, ty=node.ty)

            elif fname == "map_domain" and len(args) == 1:
                map_elems = self._const_map_elems(cast(Expr, args[0]))
                if map_elems is not None:
                    keys, _ = map_elems
                    return self._mk_set(node, keys)

            elif fname == "map_range" and len(args) == 1:
                map_elems = self._const_map_elems(cast(Expr, args[0]))
                if map_elems is not None:
                    _, values = map_elems
                    return self._mk_set(node, values)

            # New: align with BuiltinFunctionRegistry names
            elif fname == "keys" and len(args) == 1:
                map_elems = self._const_map_elems(cast(Expr, args[0]))
                if map_elems is not None:
                    keys, _ = map_elems
                    return self._mk_list(node, keys)

            elif fname == "values" and len(args) == 1:
                map_elems = self._const_map_elems(cast(Expr, args[0]))
                if map_elems is not None:
                    _, values = map_elems
                    return self._mk_list(node, values)

            elif fname == "items" and len(args) == 1:
                map_elems = self._const_map_elems(cast(Expr, args[0]))
                if map_elems is not None:
                    keys, values = map_elems
                    pairs: list[Expr] = []
                    for k, v in zip(keys, values):
                        pairs.append(self._mk_tuple(node, [k, v]))
                    return self._mk_list(node, pairs)

            elif fname == "has_key" and len(args) == 2:
                map_elems = self._const_map_elems(cast(Expr, args[0]))
                key = self._value_key(cast(Expr, args[1]))
                if map_elems is not None and key is not None:
                    keys, _ = map_elems
                    key_set = {self._value_key(k) for k in keys}
                    if None not in key_set:
                        return BoolLiteral(
                            pos=node.pos, value=(key in key_set), ty=node.ty
                        )

            # ------------------------------- tuple operations -------------------------------
            elif fname == "tuple_get" and len(args) == 2:
                tuple_elems = self._const_tuple_elems(cast(Expr, args[0]))
                idx = self._is_const_int(cast(Expr, args[1]))
                if (
                    tuple_elems is not None
                    and idx is not None
                    and 0 <= idx < len(tuple_elems)
                ):
                    return tuple_elems[idx]

            elif fname == "tuple_len" and len(args) == 1:
                tuple_elems = self._const_tuple_elems(cast(Expr, args[0]))
                if tuple_elems is not None:
                    return NumberLiteral(
                        pos=node.pos, value=len(tuple_elems), ty=node.ty
                    )

            elif fname == "set_is_empty" and len(args) == 1:
                elems = self._const_set_elems(cast(Expr, args[0]))
                if elems is not None:
                    return BoolLiteral(
                        pos=node.pos, value=(len(elems) == 0), ty=node.ty
                    )

            elif fname == "set_is_member" and len(args) == 2:
                elems = self._const_set_elems(cast(Expr, args[1]))
                k = self._value_key(cast(Expr, args[0]))
                if elems is not None and k is not None:
                    keys = {self._value_key(e) for e in elems}
                    if None not in keys:
                        return BoolLiteral(pos=node.pos, value=(k in keys), ty=node.ty)

            elif fname == "set_is_subset" and len(args) == 2:
                left = self._const_set_elems(cast(Expr, args[0]))
                right = self._const_set_elems(cast(Expr, args[1]))
                if left is not None and right is not None:
                    lkeys = {self._value_key(e) for e in left}
                    rkeys = {self._value_key(e) for e in right}
                    if None not in lkeys and None not in rkeys:
                        return BoolLiteral(
                            pos=node.pos, value=lkeys.issubset(rkeys), ty=node.ty
                        )

            elif (
                fname in {"set_union", "set_intersect", "set_difference"}
                and len(args) == 2
            ):
                a = self._const_set_elems(cast(Expr, args[0]))
                b = self._const_set_elems(cast(Expr, args[1]))
                if a is not None and b is not None:
                    a_map: dict[object, Expr] = {}
                    b_map: dict[object, Expr] = {}
                    for e in a:
                        k = self._value_key(e)
                        if k is not None and k not in a_map:
                            a_map[k] = e
                    for e in b:
                        k = self._value_key(e)
                        if k is not None and k not in b_map:
                            b_map[k] = e
                    if fname == "set_union":
                        keys = list(a_map.keys()) + [
                            k for k in b_map.keys() if k not in a_map
                        ]
                    elif fname == "set_intersect":
                        keys = [k for k in a_map.keys() if k in b_map]
                    else:  # set_difference
                        keys = [k for k in a_map.keys() if k not in b_map]
                    o = [a_map.get(k, b_map.get(k)) for k in keys]
                    out_filtered = [e for e in o if e is not None]
                    return self._mk_set(node, cast(list[Expr], out_filtered))

            elif fname in {"set_add", "set_del"} and len(args) == 2:
                elems = self._const_set_elems(cast(Expr, args[0]))
                k = self._value_key(cast(Expr, args[1]))
                if elems is not None and k is not None:
                    elem_map: dict[object, Expr] = {}
                    for e in elems:
                        ek = self._value_key(e)
                        if ek is not None and ek not in elem_map:
                            elem_map[ek] = e
                    if fname == "set_add":
                        if k not in elem_map:
                            elem_map[k] = cast(Expr, args[1])
                    else:  # set_del
                        elem_map.pop(k, None)
                    out = [elem_map[ek] for ek in elem_map]
                    return self._mk_set(node, out)

            # ------------------------------- set cardinality -------------------------------
            elif fname == "cardinality" and len(args) == 1:
                elems = self._const_set_elems(cast(Expr, args[0]))
                if elems is not None:
                    return NumberLiteral(pos=node.pos, value=len(elems), ty=node.ty)

            # ------------------------------- numeric conversions -------------------------------
            elif fname == "int2real" and len(args) == 1:
                n = self._is_const_int(cast(Expr, args[0]))
                if n is not None:
                    return NumberLiteral(pos=node.pos, value=float(n), ty=node.ty)

            elif fname == "real2int" and len(args) == 1:
                num = self._is_const_num(cast(Expr, args[0]))
                if num is not None:
                    try:
                        return NumberLiteral(
                            pos=node.pos, value=math.floor(num), ty=node.ty
                        )
                    except Exception:
                        pass
        return node

    def visit_ListAccess(self, node: ListAccess) -> Expr:
        seq = self.transform(node.seq)
        idx = self.transform(node.index)
        assert isinstance(seq, Expr)
        assert isinstance(idx, Expr)

        # Handle string indexing
        folded = self._index_str(seq, idx)
        if folded is not None:
            return folded

        # Handle explicit/constant list indexing (including range lists and char lists)
        elems = self._const_list_elems(seq)
        const_idx = self._is_const_int(idx)
        if elems is not None and const_idx is not None and 0 <= const_idx < len(elems):
            return elems[const_idx]

        # Handle map access
        map_elems = self._const_map_elems(seq)
        key = self._value_key(idx)
        if map_elems is not None and key is not None:
            keys, values = map_elems
            for i in range(len(keys) - 1, -1, -1):
                k = keys[i]
                if self._value_key(k) == key:
                    return values[i]
            # Key not found, return None or handle appropriately
            return NoneLiteral(pos=node.pos, ty=node.ty)

        # Handle tuple access
        tuple_elems = self._const_tuple_elems(seq)
        tuple_idx = self._is_const_int(idx)
        if (
            tuple_elems is not None
            and tuple_idx is not None
            and 0 <= tuple_idx < len(tuple_elems)
        ):
            return tuple_elems[tuple_idx]

        return replace(node, seq=seq, index=idx)

    def visit_FieldAccess(self, node: FieldAccess) -> Expr:
        record = self.transform(node.record)
        assert isinstance(record, Expr)

        # Handle constant propagation for field access with ExplicitRecord
        record_fields = self._const_record_fields(record)
        if record_fields is not None:
            field_name = node.field_name
            if field_name in record_fields:
                # Return the constant field value directly
                return record_fields[field_name]
            # Field not found in constant record - this should be handled by type checker
            # but we can return the original field access for now

        return replace(node, record=record)

    def visit_ExplicitRecord(self, node: ExplicitRecord) -> Expr:
        """Propagate constants in record literals."""
        new_fields = {}
        for field_name, field_expr in node.fields.items():
            new_field_expr = self.transform(field_expr)
            assert isinstance(new_field_expr, Expr)
            new_fields[field_name] = new_field_expr
        return replace(node, fields=new_fields)

    def visit_ExplicitList(self, node: ExplicitList) -> Expr:
        new_elements: list[Expr] = []
        for e in node.elements:
            te = self.transform(e)
            assert isinstance(te, Expr)
            new_elements.append(te)
        return replace(node, elements=new_elements)

    def visit_ExplicitSet(self, node: ExplicitSet) -> Expr:
        new_elements: list[Expr] = []
        for e in node.elements:
            te = self.transform(e)
            assert isinstance(te, Expr)
            new_elements.append(te)
        return replace(node, elements=new_elements)

    def visit_ExplicitMultiset(self, node: ExplicitMultiset) -> Expr:
        new_elements: list[Expr] = []
        for e in node.elements:
            te = self.transform(e)
            assert isinstance(te, Expr)
            new_elements.append(te)
        return replace(node, elements=new_elements)

    def visit_ExplicitMap(self, node: ExplicitMap) -> Expr:
        new_keys: list[Expr] = []
        new_values: list[Expr] = []
        for k in node.keys:
            tk = self.transform(k)
            assert isinstance(tk, Expr)
            new_keys.append(tk)
        for v in node.values:
            tv = self.transform(v)
            assert isinstance(tv, Expr)
            new_values.append(tv)
        return replace(node, keys=new_keys, values=new_values)

    def visit_TupleExpr(self, node: TupleExpr) -> Expr:
        new_elements: list[Expr] = []
        for e in node.elements:
            te = self.transform(e)
            assert isinstance(te, Expr)
            new_elements.append(te)
        return replace(node, elements=new_elements)

    def visit_RangeList(self, node: RangeList) -> Expr:
        start_t = self.transform(node.start)
        end_t = None if node.end is None else self.transform(node.end)
        assert isinstance(start_t, Expr)
        assert (end_t is None) or isinstance(end_t, Expr)
        # When both bounds fold to constants, replace the range with an explicit list.
        elems = self._expand_range_elements(start_t, end_t)
        if elems is not None:
            return ExplicitList(pos=node.pos, elements=elems, ty=node.ty)
        return replace(node, start=start_t, end=end_t)

    def visit_RangeSet(self, node: RangeSet) -> Expr:
        start_t = self.transform(node.start)
        end_t = None if node.end is None else self.transform(node.end)
        assert isinstance(start_t, Expr)
        assert (end_t is None) or isinstance(end_t, Expr)
        # When both bounds fold to constants, replace the range with an explicit set.
        elems = self._expand_range_elements(start_t, end_t)
        if elems is not None:
            return ExplicitSet(pos=node.pos, elements=elems, ty=node.ty)
        return replace(node, start=start_t, end=end_t)

    def visit_UnaryOp(self, node: UnaryOp):
        operand = self.transform(node.operand)
        assert isinstance(operand, Expr)
        # Fold arithmetic sign and boolean not when operand is constant
        if node.op == "-":
            n = self._is_const_num(operand)
            if n is not None:
                return NumberLiteral(value=-n)
        if node.op == "+":
            n = self._is_const_num(operand)
            if n is not None:
                return NumberLiteral(value=+n)
        if node.op == "¬":
            # Double negation: ¬(¬a) -> a
            if isinstance(operand, UnaryOp) and operand.op == "¬":
                inner = operand.operand
                assert isinstance(inner, Expr)
                return inner
            b = self._is_const_bool(operand)
            if b is not None:
                return BoolLiteral(value=(not b))
        return replace(node, operand=operand)

    def visit_BinaryOp(self, node: BinaryOp):
        left = self.transform(node.left)
        right = self.transform(node.right)
        assert isinstance(left, Expr)
        assert isinstance(right, Expr)

        # Numeric folding: only for safe ops (+, -, *, ^)
        if node.op in {"+", "-", "*", "^", "/", "%"}:
            lnum = self._is_const_num(left)
            rnum = self._is_const_num(right)
            if lnum is not None and rnum is not None:
                try:
                    if node.op == "+":
                        val = lnum + rnum
                    elif node.op == "-":
                        val = lnum - rnum
                    elif node.op == "*":
                        val = lnum * rnum
                    elif node.op == "/":
                        if isinstance(lnum, int) and isinstance(rnum, int):
                            if rnum == 0:
                                return replace(node, left=left, right=right)
                            quotient = lnum / rnum
                            val = (
                                math.floor(quotient)
                                if rnum > 0
                                else math.ceil(quotient)
                            )
                        else:
                            val = lnum / rnum
                    elif (
                        node.op == "%"
                        and isinstance(lnum, int)
                        and isinstance(rnum, int)
                    ):
                        if rnum == 0:
                            return replace(node, left=left, right=right)
                        quotient = lnum / rnum
                        div_val = (
                            math.floor(quotient) if rnum > 0 else math.ceil(quotient)
                        )
                        val = lnum - (rnum * div_val)
                    else:  # "^" power
                        val = lnum**rnum  # type: ignore[operator]
                    return NumberLiteral(value=val)
                except Exception:
                    pass

        # Self-comparison and simple tautologies
        if node.op in {"==", "!="}:
            if self._structurally_equal(left, right):
                return BoolLiteral(value=(node.op == "=="))

        if node.op in {"==>", "<==>"}:
            # a ==> a  ==> True,  a <==> a ==> True
            if self._structurally_equal(left, right):
                return BoolLiteral(value=True)

        # "in" operator constant folding
        if node.op == "in":
            # Check if right operand is a constant collection
            right_elems = (
                self._const_list_elems(right)
                or self._const_set_elems(right)
                or self._const_multiset_elems(right)
            )
            if right_elems is None:
                return replace(node, left=left, right=right)

            # Check if left operand is constant
            left_val = self._value_key(left)
            if left_val is None:
                return replace(node, left=left, right=right)

            # Check membership in the constant collection
            right_keys = {self._value_key(e) for e in right_elems}
            if None in right_keys:
                return replace(node, left=left, right=right)

            return BoolLiteral(value=(left_val in right_keys))

        # Support comparisons for explicit collections & primitive literals
        if node.op in {"==", "!=", "<", "<=", ">", ">="}:
            # Check if both operands are constants
            left_val = self._value_key(left)
            right_val = self._value_key(right)

            if left_val is not None and right_val is not None:
                result: bool | None = None
                # Both operands are constants, evaluate the comparison
                if node.op == "==":
                    if isinstance(left_val, float) and isinstance(right_val, float):
                        if math.isnan(left_val) or math.isnan(right_val):
                            result = False
                        else:
                            result = left_val == right_val
                    else:
                        result = left_val == right_val
                elif node.op == "!=":
                    if isinstance(left_val, float) and isinstance(right_val, float):
                        if math.isnan(left_val) or math.isnan(right_val):
                            result = True
                        else:
                            result = left_val != right_val
                    else:
                        result = left_val != right_val
                elif node.op in {"<", "<=", ">", ">="}:
                    # Only numeric and string values support ordering comparisons
                    # Both values must be of the same type for comparison
                    if isinstance(left_val, (int, float)) and isinstance(
                        right_val, (int, float)
                    ):
                        # Both are numeric
                        if node.op == "<":
                            result = left_val < right_val
                        elif node.op == "<=":
                            result = left_val <= right_val
                        elif node.op == ">":
                            result = left_val > right_val
                        elif node.op == ">=":
                            result = left_val >= right_val
                    elif isinstance(left_val, str) and isinstance(right_val, str):
                        # Both are strings
                        if node.op == "<":
                            result = left_val < right_val
                        elif node.op == "<=":
                            result = left_val <= right_val
                        elif node.op == ">":
                            result = left_val > right_val
                        else:
                            result = left_val >= right_val
                    else:
                        # Non-comparable types, fall back to original
                        return replace(node, left=left, right=right)
                if result is None:
                    return replace(node, left=left, right=right)
                return BoolLiteral(value=result)

            # Check if both operands are constant collections of the same type
            left_list_elems = self._const_list_elems(left)
            right_list_elems = self._const_list_elems(right)
            left_set_elems = self._const_set_elems(left)
            right_set_elems = self._const_set_elems(right)
            left_multiset_elems = self._const_multiset_elems(left)
            right_multiset_elems = self._const_multiset_elems(right)
            left_tuple_elems = self._const_tuple_elems(left)
            right_tuple_elems = self._const_tuple_elems(right)

            collection_kind: str | None = None
            left_elems: list[Expr] | None = None
            right_elems: list[Expr] | None = None

            if left_multiset_elems is not None and right_multiset_elems is not None:
                collection_kind = "multiset"
                left_elems = left_multiset_elems
                right_elems = right_multiset_elems
            elif left_set_elems is not None and right_set_elems is not None:
                collection_kind = "set"
                left_elems = left_set_elems
                right_elems = right_set_elems
            elif left_tuple_elems is not None and right_tuple_elems is not None:
                collection_kind = "tuple"
                left_elems = left_tuple_elems
                right_elems = right_tuple_elems
            elif left_list_elems is not None and right_list_elems is not None:
                collection_kind = "list"
                left_elems = left_list_elems
                right_elems = right_list_elems

            if (
                collection_kind is not None
                and left_elems is not None
                and right_elems is not None
            ):
                # Both are constant collections, compare their elements
                # Only equality and inequality make sense for collections
                if node.op in {"==", "!="}:
                    left_keys = [self._value_key(e) for e in left_elems]
                    right_keys = [self._value_key(e) for e in right_elems]

                    # If any element couldn't be converted to a key, fall back to original
                    if None in left_keys or None in right_keys:
                        return replace(node, left=left, right=right)

                    left_key_values = [cast(object, k) for k in left_keys]
                    right_key_values = [cast(object, k) for k in right_keys]

                    if collection_kind == "set":
                        are_equal = set(left_key_values) == set(right_key_values)
                    elif collection_kind == "multiset":
                        are_equal = Counter(left_key_values) == Counter(
                            right_key_values
                        )
                    else:
                        are_equal = left_key_values == right_key_values

                    if node.op == "==":
                        result = are_equal
                    else:  # "!="
                        result = not are_equal
                    return BoolLiteral(value=result)

            # Check if both operands are constant maps
            left_map = self._const_map_elems(left)
            right_map = self._const_map_elems(right)
            if left_map is not None and right_map is not None:
                # Both are constant maps, compare their key-value pairs
                # Only equality and inequality make sense for maps
                if node.op in {"==", "!="}:
                    left_keys, left_values = left_map
                    right_keys, right_values = right_map

                    # Convert to key-value pairs for comparison
                    left_pairs = [
                        (self._value_key(k), self._value_key(v))
                        for k, v in zip(left_keys, left_values)
                    ]
                    right_pairs = [
                        (self._value_key(k), self._value_key(v))
                        for k, v in zip(right_keys, right_values)
                    ]

                    # If any key or value couldn't be converted, fall back to original
                    if any(
                        pair[0] is None or pair[1] is None
                        for pair in left_pairs + right_pairs
                    ):
                        return replace(node, left=left, right=right)

                    def canonicalize_pairs(
                        pairs: list[tuple[object | None, object | None]],
                    ) -> list[tuple[object, object]]:
                        order: list[object] = []
                        entries: dict[object, object] = {}
                        for key, value in pairs:
                            assert key is not None and value is not None
                            if key not in entries:
                                order.append(key)
                            entries[key] = value
                        return [(key, entries[key]) for key in order]

                    left_pairs = canonicalize_pairs(left_pairs)
                    right_pairs = canonicalize_pairs(right_pairs)

                    if node.op == "==":
                        result = left_pairs == right_pairs
                    else:  # "!="
                        result = left_pairs != right_pairs
                    return BoolLiteral(value=result)

            # Check if both operands are none
            if self._is_none(left) and self._is_none(right):
                if node.op == "==":
                    return BoolLiteral(value=True)
                if node.op == "!=":
                    return BoolLiteral(value=False)
            return replace(node, left=left, right=right)
        # Boolean folding for logic ops with constants and identities
        if node.op in {"∧", "∨", "==>", "<==>"}:
            lbool = self._is_const_bool(left)
            rbool = self._is_const_bool(right)

            if node.op == "∧":
                if lbool is False or rbool is False:
                    return BoolLiteral(value=False)
                if lbool is True and rbool is True:
                    return BoolLiteral(value=True)
                if lbool is True:
                    return replace(right, ty=node.ty)
                if rbool is True:
                    return replace(left, ty=node.ty)

            if node.op == "∨":
                if lbool is True or rbool is True:
                    return BoolLiteral(value=True)
                if lbool is False and rbool is False:
                    return BoolLiteral(value=False)
                if lbool is False:
                    return replace(right, ty=node.ty)
                if rbool is False:
                    return replace(left, ty=node.ty)

            if node.op == "==>":
                if lbool is False:
                    return BoolLiteral(value=True)
                if lbool is True:
                    return replace(right, ty=node.ty)
                if rbool is True:
                    return BoolLiteral(value=True)
                if rbool is False:
                    return UnaryOp(
                        pos=node.pos, op="¬", operand=cast(Expr, left), ty=node.ty
                    )

            if node.op == "<==>":
                if lbool is not None and rbool is not None:
                    return BoolLiteral(value=(lbool == rbool))
                if lbool is True:
                    return replace(right, ty=node.ty)
                if lbool is False:
                    return UnaryOp(
                        pos=node.pos, op="¬", operand=cast(Expr, right), ty=node.ty
                    )
                if rbool is True:
                    return replace(left, ty=node.ty)
                if rbool is False:
                    return UnaryOp(
                        pos=node.pos, op="¬", operand=cast(Expr, left), ty=node.ty
                    )

        return replace(node, left=left, right=right)

    # ------------------- helpers: structural checks -------------------
    def _structurally_equal(self, a: Expr, b: Expr) -> bool:
        """Best-effort structural equality for small boolean/algebraic folds.

        This intentionally handles only common Expr cases used in folds.
        """
        if type(a) is not type(b):
            return False
        # Identifiers
        if isinstance(a, Identifier):
            return a.name == cast(Identifier, b).name
        # Literals
        if isinstance(a, NumberLiteral):
            return a.value == cast(NumberLiteral, b).value
        if isinstance(a, BoolLiteral):
            return a.value == cast(BoolLiteral, b).value
        if isinstance(a, CharLiteral):
            return a.value == cast(CharLiteral, b).value
        if isinstance(a, StringLiteral):
            return a.value == cast(StringLiteral, b).value
        # Unary
        if isinstance(a, UnaryOp):
            bb = cast(UnaryOp, b)
            return a.op == bb.op and self._structurally_equal(
                cast(Expr, a.operand), cast(Expr, bb.operand)
            )
        # Binary
        if isinstance(a, BinaryOp):
            bb = cast(BinaryOp, b)
            return (
                a.op == bb.op
                and self._structurally_equal(cast(Expr, a.left), cast(Expr, bb.left))
                and self._structurally_equal(cast(Expr, a.right), cast(Expr, bb.right))
            )
        return False

    def visit_Comparisons(self, node: Comparisons):
        transformed = [self.transform(e) for e in node.comparisons]
        transformed = cast(list[Expr], transformed)
        const_bools = [
            self._is_const_bool(e)
            for e in transformed
            if self._is_const_bool(e) is not None
        ]
        non_const_bools = [e for e in transformed if self._is_const_bool(e) is None]
        if not all(const_bools):
            return BoolLiteral(value=False)
        if len(const_bools) == len(node.comparisons):
            return BoolLiteral(value=True)
        return replace(node, comparisons=non_const_bools)

    def visit_SomeExpr(self, node: SomeExpr) -> Expr:
        """Handle some(value) expressions with constant propagation."""
        value = self.transform(node.value)
        assert isinstance(value, Expr)

        # Constant propagation for some(constant)
        if isinstance(value, (NumberLiteral, BoolLiteral, StringLiteral, CharLiteral)):
            # some(constant) can be optimized - keep as SomeExpr but mark as constant
            return replace(node, value=value)

        return replace(node, value=value)

    def visit_IfExpr(self, node: IfExpr):
        cond = self.transform(node.condition)
        then_b = self.transform(node.then_branch)
        else_b = self.transform(node.else_branch)
        assert (
            isinstance(cond, Expr)
            and isinstance(then_b, Expr)
            and isinstance(else_b, Expr)
        )
        b = self._is_const_bool(cond)
        if b is True:
            return replace(then_b, ty=node.ty)
        if b is False:
            return replace(else_b, ty=node.ty)
        return replace(node, condition=cond, then_branch=then_b, else_branch=else_b)
