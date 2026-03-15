from __future__ import annotations

import copy
from dataclasses import replace
from typing import Mapping, Optional, Sequence, cast

from .ast_traverse import ASTTransformer
from .dsl_ast import (
    ASTNode,
    BinaryOp,
    Boolean,
    BoolLiteral,
    CharLiteral,
    Comparisons,
    Ensure,
    ExistsExpr,
    ExplicitList,
    ExplicitSet,
    Expr,
    ForallExpr,
    FuncCall,
    FunctionDef,
    Identifier,
    IfExpr,
    NumberLiteral,
    PredicateDef,
    RangeList,
    RangeSet,
    Specification,
    TypeNode,
    UnaryOp,
)
from .dsl_constant_propagation import ConstantPropagation
from .reference_collector import ReferenceCollector


class EqualityConstraintPropagation(ASTTransformer[ASTNode]):
    """Propagate equalities of the form (x == const) into dependent parts.

    Rules applied conservatively:
    - In conjunction: (A ∧ B), collect equalities from A that are top-level
      conjuncts (recursively under ∧ only) and substitute them into B.
    - In implication: (A ==> B), collect equalities from A (again under ∧ only)
      and substitute them into B.
    - In conditional: if (cond) then t else e, collect equalities from cond
      (under ∧ only) and substitute them into the then-branch.

    We only substitute when the right-hand side is a constant expression
    (contains no identifiers). Substitution respects inner binders via
    _subst_expr which avoids replacing shadowed identifiers inside nested
    quantifiers/lambdas.
    """

    def _is_constant_expr(self, expr: Expr) -> bool:
        collector = _FreeVarCollector(shadow_stack=[set()])
        collector.transform(expr)
        return len(collector.names) == 0

    def _collect_equalities_from_conj(self, expr: Expr) -> dict[str, Expr]:
        eqs: dict[str, Expr] = {}

        def add_eq(lhs: Expr, rhs: Expr) -> None:
            if isinstance(lhs, Identifier) and self._is_constant_expr(rhs):
                # Do not overwrite if already present; first match wins
                if lhs.name not in eqs:
                    eqs[lhs.name] = rhs

        def rec(e: Expr) -> None:
            if isinstance(e, BinaryOp) and e.op == "∧":
                # Only traverse under conjunctions
                rec(e.left)
                rec(e.right)
                return
            if isinstance(e, Comparisons):
                for comp in e.comparisons:
                    if isinstance(comp, BinaryOp) and comp.op == "==":
                        if isinstance(comp.left, Identifier) and self._is_constant_expr(
                            comp.right
                        ):
                            add_eq(comp.left, comp.right)
                        elif isinstance(
                            comp.right, Identifier
                        ) and self._is_constant_expr(comp.left):
                            add_eq(comp.right, comp.left)
                return
            if isinstance(e, BinaryOp) and e.op == "==":
                if isinstance(e.left, Identifier) and self._is_constant_expr(e.right):
                    add_eq(e.left, e.right)
                elif isinstance(e.right, Identifier) and self._is_constant_expr(e.left):
                    add_eq(e.right, e.left)

        rec(expr)
        return eqs

    def visit_BinaryOp(self, node: BinaryOp):
        left = self.transform(node.left)
        # Default: transform right under current state
        if node.op in {"∧", "==>"}:
            eqs = {}
            if isinstance(left, Expr):
                eqs = self._collect_equalities_from_conj(left)
            right_src = node.right
            if eqs:
                right_src = _subst_expr(right_src, eqs)
            right = self.transform(right_src)
            assert isinstance(left, Expr) and isinstance(right, Expr)
            return replace(node, left=left, right=right)

        right = self.transform(node.right)
        assert isinstance(left, Expr) and isinstance(right, Expr)
        return replace(node, left=left, right=right)

    def visit_IfExpr(self, node: IfExpr):
        cond = self.transform(node.condition)
        then_b_src = node.then_branch
        if isinstance(cond, Expr):
            eqs = self._collect_equalities_from_conj(cond)
            if eqs:
                then_b_src = _subst_expr(then_b_src, eqs)
        then_b = self.transform(then_b_src)
        else_b = self.transform(node.else_branch)
        assert (
            isinstance(cond, Expr)
            and isinstance(then_b, Expr)
            and isinstance(else_b, Expr)
        )
        return replace(node, condition=cond, then_branch=then_b, else_branch=else_b)

    def visit_Comparisons(self, node: Comparisons):
        transformed: list[BinaryOp] = []
        for comp in node.comparisons:
            left = self.transform(comp.left)
            right = self.transform(comp.right)
            assert isinstance(left, Expr) and isinstance(right, Expr)
            transformed.append(replace(comp, left=left, right=right))
        return replace(node, comparisons=transformed)


class BooleanSimplify(ASTTransformer[ASTNode]):
    """Simplify boolean formulas: flatten, deduplicate, and remove tautologies.

    - Flatten associative ops (∧, ∨)
    - Deduplicate identical terms (structural equality)
    - Identities/annihilators: remove True/False where applicable
    - Complement pairs: a ∧ ¬a -> False, a ∨ ¬a -> True
    - Tautologies: a ==> a -> True, a <==> a -> True
    """

    # -------------------------- helpers --------------------------
    def _structurally_equal(self, a: Expr, b: Expr) -> bool:
        if type(a) is not type(b):
            return False
        if isinstance(a, Identifier):
            return a.name == cast(Identifier, b).name
        if isinstance(a, BoolLiteral):
            return a.value == cast(BoolLiteral, b).value
        if isinstance(a, NumberLiteral):
            return a.value == cast(NumberLiteral, b).value
        if isinstance(a, CharLiteral):
            return a.value == cast(CharLiteral, b).value
        if isinstance(a, FuncCall):
            bb = cast(FuncCall, b)
            return self._structurally_equal(
                cast(Expr, a.func), cast(Expr, bb.func)
            ) and self._list_structural_eq(a.args, bb.args)
        if isinstance(a, IfExpr):
            bb = cast(IfExpr, b)
            return (
                self._structurally_equal(a.condition, bb.condition)
                and self._structurally_equal(a.then_branch, bb.then_branch)
                and self._structurally_equal(a.else_branch, bb.else_branch)
            )
        if isinstance(a, BinaryOp):
            bb = cast(BinaryOp, b)
            return (
                a.op == bb.op
                and self._structurally_equal(cast(Expr, a.left), cast(Expr, bb.left))
                and self._structurally_equal(cast(Expr, a.right), cast(Expr, bb.right))
            )
        return False

    def _list_structural_eq(self, xs: Sequence[Expr], ys: Sequence[Expr]) -> bool:
        if len(xs) != len(ys):
            return False
        return all(
            self._structurally_equal(cast(Expr, x), cast(Expr, y))
            for x, y in zip(xs, ys)
        )

    def _is_true(self, e: Expr) -> bool:
        return isinstance(e, BoolLiteral) and e.value is True

    def _is_false(self, e: Expr) -> bool:
        return isinstance(e, BoolLiteral) and e.value is False

    def _is_negation_of(self, a: Expr, b: Expr) -> bool:
        if isinstance(a, UnaryOp) and a.op == "¬":
            return self._structurally_equal(cast(Expr, a.operand), b)
        if isinstance(b, UnaryOp) and b.op == "¬":
            return self._structurally_equal(a, cast(Expr, b.operand))
        return False

    def _flatten(self, op: str, e: Expr) -> list[Expr]:
        items: list[Expr] = []

        def rec(x: Expr) -> None:
            if isinstance(x, BinaryOp) and x.op == op:
                rec(cast(Expr, x.left))
                rec(cast(Expr, x.right))
            else:
                items.append(x)

        rec(e)
        return items

    # -------------------------- visitors --------------------------
    def visit_BinaryOp(self, node: BinaryOp):
        left = self.transform(node.left)
        right = self.transform(node.right)
        assert isinstance(left, Expr) and isinstance(right, Expr)

        if node.op in {"∧", "∨"}:
            parts = self._flatten(
                node.op,
                cast(Expr, BinaryOp(left=left, op=node.op, right=right, ty=node.ty)),
            )

            # Deduplicate and apply identities/annihilators
            uniq: list[Expr] = []
            seen: list[Expr] = []
            has_true = any(self._is_true(p) for p in parts)
            has_false = any(self._is_false(p) for p in parts)
            if node.op == "∧" and has_false:
                return BoolLiteral(value=False)
            if node.op == "∨" and has_true:
                return BoolLiteral(value=True)

            for p in parts:
                if (node.op == "∧" and self._is_true(p)) or (
                    node.op == "∨" and self._is_false(p)
                ):
                    continue
                if any(self._structurally_equal(p, q) for q in seen):
                    continue
                # Complement pair short-circuit
                if any(self._is_negation_of(p, q) for q in seen):
                    return BoolLiteral(value=(node.op == "∨"))
                seen.append(p)
                uniq.append(p)

            if len(uniq) == 0:
                return BoolLiteral(
                    value=(node.op == "∧")
                )  # empty ∧ -> True, empty ∨ -> False
            if len(uniq) == 1:
                return uniq[0]
            # Rebuild balanced-ish tree left-associatively
            acc = uniq[0]
            for e in uniq[1:]:
                acc = BinaryOp(left=acc, op=node.op, right=e, ty=node.ty)
            return acc

        if node.op in {"==>", "<==>"}:
            if self._structurally_equal(left, right):
                return BoolLiteral(value=True)
        return replace(node, left=left, right=right)


class ScopeCollector(ASTTransformer[ASTNode]):
    """Base transformer that manages bound identifier scopes.

    This class centralizes scope management for constructs that bind identifiers
    (universal/existential quantifiers and lambdas). Subclasses can query
    whether a name is currently bound via `is_bound` and rely on the default
    visitors to only traverse into the expression bodies under the correct
    extended scope.
    """

    def __init__(self, *, shadow_stack: Optional[list[set[str]]] = None):
        super().__init__()
        # The top of the stack holds the set of names bound in the current scope
        # (including all ancestors). Using a cumulative set avoids repeated set
        # unions on lookups and mirrors the previous implementation semantics.
        self._shadow_stack: list[set[str]] = (
            shadow_stack if shadow_stack is not None else [set()]
        )

    def _push_shadow(self, names: list[str]) -> None:
        current = set(self._shadow_stack[-1])
        for n in names:
            current.add(n)
        self._shadow_stack.append(current)

    def _pop_shadow(self) -> None:
        self._shadow_stack.pop()

    def is_bound(self, name: str) -> bool:
        """Return True if `name` is bound in the current scope."""
        return name in self._shadow_stack[-1]

    def visit_ForallExpr(self, node: ForallExpr):  # type: ignore[override]
        bound = [v.name for v in node.vars]
        self._push_shadow(bound)
        try:
            body = self.transform(node.satisfies_expr)
            return replace(node, satisfies_expr=body)
        finally:
            self._pop_shadow()

    def visit_ExistsExpr(self, node):  # type: ignore[override]
        bound = [v.name for v in node.vars]
        self._push_shadow(bound)
        try:
            body = self.transform(node.satisfies_expr)
            return replace(node, satisfies_expr=body)
        finally:
            self._pop_shadow()

    def visit_LambdaExpr(self, node):  # type: ignore[override]
        bound = [arg.name for arg in node.args]
        self._push_shadow(bound)
        try:
            body = self.transform(node.body)
            return replace(node, body=body)
        finally:
            self._pop_shadow()


class _Substitution(ScopeCollector):
    """Identifier substitution with shadowing for bound variables.

    Replaces free occurrences of identifiers per `subs` mapping while avoiding
    replacement in scopes that bind the same names (quantifiers, lambdas).
    """

    def __init__(self, subs: Mapping[str, Expr]):
        super().__init__()
        self._subs = subs
        self._changed: bool = False

    def visit_Identifier(self, node: Identifier):
        if node.name in self._subs and not self.is_bound(node.name):
            rep = self._subs[node.name]
            self._changed = True
            return replace(rep, ty=node.ty)
        return node

    def visit_FuncCall(self, node: FuncCall):
        return replace(node, args=[self.transform(arg) for arg in node.args])


class _FreeVarCollector(ScopeCollector):
    def __init__(self, *, shadow_stack: list[set[str]]):
        super().__init__(shadow_stack=shadow_stack)
        self.names: set[str] = set()

    def visit_Identifier(self, node: Identifier):  # type: ignore[override]
        if not self.is_bound(node.name):
            self.names.add(node.name)
        return node


def _subst_expr(expr: Expr, subs: Mapping[str, Expr]) -> Expr:
    """Apply identifier substitution using a pruned, single-pass strategy.

    - Filter the substitution map to identifiers actually free in `expr`,
      closed under dependencies among substitution right-hand sides.
    - Detect cycles within the used portion of the map and raise ValueError.
    - Topologically resolve dependencies to compose replacements, then apply
      a single scope-aware substitution traversal over `expr`.
    """

    def _collect_free_identifiers(
        e: ASTNode, *, shadow_stack: list[set[str]]
    ) -> set[str]:
        """Collect free identifier names from `e`, respecting quantifier/lambda scoping."""

        collector = _FreeVarCollector(shadow_stack=shadow_stack)
        collector.transform(e)
        return collector.names

    if not subs:
        return expr

    # Collect free identifiers of the target expression
    expr_free = _collect_free_identifiers(expr, shadow_stack=[set()])
    if not expr_free:
        return expr

    # Compute dependency-closed set of keys that actually matter for this expr
    all_keys = set(subs.keys())
    used_keys: set[str] = set(k for k in all_keys if k in expr_free)
    if not used_keys:
        return expr

    # Build dependency map only for keys we might use
    def rhs_deps(name: str) -> set[str]:
        names = _collect_free_identifiers(subs[name], shadow_stack=[set()])
        return {n for n in names if n in all_keys}

    work = list(used_keys)
    while work:
        k = work.pop()
        for d in rhs_deps(k):
            if d not in used_keys:
                used_keys.add(d)
                work.append(d)

    # Cycle detection and topological order on the used subset
    deps: dict[str, set[str]] = {name: rhs_deps(name) for name in used_keys}
    visiting: set[str] = set()
    visited: set[str] = set()
    topo: list[str] = []

    def dfs(n: str, path: list[str]) -> None:
        if n in visiting:
            cycle = path[path.index(n) :] + [n]
            msg = " -> ".join(cycle)
            raise ValueError(f"Cyclic substitution detected: {msg}")
        if n in visited:
            return
        visiting.add(n)
        for m in deps.get(n, set()):
            dfs(m, path + [m])
        visiting.remove(n)
        visited.add(n)
        topo.append(n)

    for k in list(used_keys):
        if k not in visited:
            dfs(k, [k])

    # Compose substitutions along topological order so that each RHS is expanded
    resolved_subs: dict[str, Expr] = {}
    for name in topo:
        rhs = copy.deepcopy(subs[name])
        rhs_resolved = _Substitution(resolved_subs).transform(rhs)
        assert isinstance(rhs_resolved, Expr)
        resolved_subs[name] = rhs_resolved

    # Apply a single scope-aware substitution over the expression
    transformer = _Substitution(resolved_subs)
    result = transformer.transform(expr)
    assert isinstance(result, Expr)
    return result


class DropUnusedQuantifiers(ASTTransformer[ASTNode]):
    """Remove quantifiers whose bound vars do not occur in the body.

    Also folds: ∀x. true -> true, ∃x. false -> false.
    """

    def _free_vars(self, e: Expr) -> set[str]:
        collector = _FreeVarCollector(shadow_stack=[set()])
        collector.transform(e)
        return collector.names

    def visit_ForallExpr(self, node: ForallExpr):  # type: ignore[override]
        body = self.transform(node.satisfies_expr)
        assert isinstance(body, Expr)
        if isinstance(body, BoolLiteral) and body.value is True:
            return body
        free = self._free_vars(body)
        bound_names = {v.name for v in node.vars}
        if bound_names.isdisjoint(free):
            return body
        return replace(node, satisfies_expr=body)

    def visit_ExistsExpr(self, node: ExistsExpr):  # type: ignore[override]
        body = self.transform(node.satisfies_expr)
        assert isinstance(body, Expr)
        if isinstance(body, BoolLiteral) and body.value is False:
            return body
        free = self._free_vars(body)
        bound_names = {v.name for v in node.vars}
        if bound_names.isdisjoint(free):
            return body
        return replace(node, satisfies_expr=body)


class QuantifierElimination(ASTTransformer[ASTNode]):
    """Bounded unrolling of quantifiers with simple guards."""

    def __init__(self, *, unroll_threshold: int = 64):
        self._unroll_threshold = unroll_threshold

    def _is_const_int(self, node: Expr) -> Optional[int]:
        if isinstance(node, NumberLiteral) and isinstance(node.value, int):
            return int(node.value)
        return None

    def _extract_bound(self, expr: Expr, var_name: str) -> Optional[tuple[int, int]]:
        def collect_conj(e: Expr) -> list[Expr]:
            if isinstance(e, BinaryOp) and e.op == "∧":
                return collect_conj(e.left) + collect_conj(e.right)
            return [e]

        candidates = collect_conj(expr)
        lower: Optional[int] = None
        upper: Optional[int] = None
        for c in candidates:
            if isinstance(c, Comparisons):
                for comp in c.comparisons:
                    if not isinstance(comp, BinaryOp):
                        continue
                    if comp.op in ("<=", ">="):
                        if (
                            self._is_const_int(comp.left) == 0
                            and isinstance(comp.right, Identifier)
                            and comp.right.name == var_name
                        ):
                            lower = 0
                        if (
                            isinstance(comp.left, Identifier)
                            and comp.left.name == var_name
                            and self._is_const_int(comp.right) == 0
                        ):
                            lower = 0
                    if (
                        comp.op == "<"
                        and isinstance(comp.left, Identifier)
                        and comp.left.name == var_name
                    ):
                        up = self._is_const_int(comp.right)
                        if up is not None:
                            upper = up
        if lower is not None and upper is not None and lower <= upper:
            return lower, upper
        return None

    def _subst_ident(self, expr: Expr, name: str, replacement: Expr) -> Expr:
        return _subst_expr(expr, {name: replacement})

    # ────────────────────────────────────────────────────────────────────────
    #  Generalized multi-variable unrolling helpers
    # ────────────────────────────────────────────────────────────────────────

    def _flatten_conjuncts(self, e: Expr) -> list[Expr]:
        items: list[Expr] = []

        def rec(x: Expr) -> None:
            if isinstance(x, BinaryOp) and x.op == "∧":
                rec(x.left)
                rec(x.right)
            else:
                items.append(x)

        rec(e)
        return items

    def _collect_comparisons(self, e: Expr) -> list[BinaryOp]:
        comps: list[BinaryOp] = []

        def rec(x: Expr) -> None:
            if isinstance(x, Comparisons):
                for c in x.comparisons:
                    if isinstance(c, BinaryOp):
                        comps.append(c)
            elif isinstance(x, BinaryOp) and x.op in {"∧", "∨", "==>", "<==>"}:
                rec(x.left)
                rec(x.right)

        rec(e)
        return comps

    def _is_simple_bound_term(self, node: Expr, var_names: list[str]) -> bool:
        """Return True when `node` is a plain quantified var or integer literal."""
        return isinstance(node, NumberLiteral) or (
            isinstance(node, Identifier) and node.name in var_names
        )

    def _is_bound_comparison(self, comp: BinaryOp, var_names: list[str]) -> bool:
        """Recognize only comparisons that can contribute enumeration bounds."""
        if comp.op not in {"<", "<=", ">", ">="}:
            return False
        if not self._is_simple_bound_term(comp.left, var_names):
            return False
        if not self._is_simple_bound_term(comp.right, var_names):
            return False
        left_is_bound_var = (
            isinstance(comp.left, Identifier) and comp.left.name in var_names
        )
        right_is_bound_var = (
            isinstance(comp.right, Identifier) and comp.right.name in var_names
        )
        return left_is_bound_var or right_is_bound_var

    def _is_bound_relevant(self, e: Expr, var_names: list[str]) -> bool:
        if not isinstance(e, Comparisons):
            return False
        saw_bound = False
        for comp in e.comparisons:
            if not isinstance(comp, BinaryOp):
                continue
            if not self._is_bound_comparison(comp, var_names):
                return False
            saw_bound = True
        return saw_bound

    def _split_guard_bound_vs_rest(
        self, guard: Expr, var_names: list[str]
    ) -> tuple[list[Expr], list[Expr]]:
        parts = self._flatten_conjuncts(guard)
        bound_rel: list[Expr] = []
        rest: list[Expr] = []
        for c in parts:
            if self._is_bound_relevant(c, var_names):
                bound_rel.append(c)
            else:
                rest.append(c)
        return bound_rel, rest

    def _post_instance_opt(self, e: Expr) -> Expr:
        # Apply a light, local optimization pipeline to avoid AST bloat
        tmp: ASTNode = e
        repeat_cp = 2
        for _ in range(repeat_cp):
            tmp = ConstantPropagation().transform(tmp)
            tmp = EqualityConstraintPropagation().transform(tmp)
        tmp = BooleanSimplify().transform(tmp)
        assert isinstance(tmp, Expr)
        return tmp

    def _extract_bounds_multi(
        self, guard: Expr, var_names: list[str]
    ) -> tuple[dict[str, int], dict[str, list[tuple[str, int]]]]:
        """From guard, extract constant upper bounds and ordering edges among vars.

        Returns (hi_map, edges) where:
        - hi_map[name] = exclusive upper bound constant for that variable
        - edges[u] contains (v, delta) meaning u <= v - delta, derived from u < v or u <= v
        """
        hi_map: dict[str, int] = {}
        edges: dict[str, list[tuple[str, int]]] = {n: [] for n in var_names}

        def is_id_of_var(node: Expr) -> Optional[str]:
            if isinstance(node, Identifier) and node.name in var_names:
                return node.name
            return None

        def const_int(node: Expr) -> Optional[int]:
            return self._is_const_int(node)

        for comp in self._collect_comparisons(guard):
            op = comp.op
            l_id = is_id_of_var(comp.left)
            r_id = is_id_of_var(comp.right)
            l_num = const_int(comp.left)
            r_num = const_int(comp.right)

            # Normalize to patterns setting exclusive upper bounds
            # x < K  or  x <= K  -> hi(x) <= K or K+1
            if l_id is not None and r_num is not None:
                if op == "<":
                    hi_map[l_id] = min(hi_map.get(l_id, r_num), r_num)
                elif op == "<=":
                    hi_map[l_id] = min(hi_map.get(l_id, r_num + 1), r_num + 1)

            # K > x  or  K >= x  -> same as above
            if l_num is not None and r_id is not None:
                if op == ">":
                    hi_map[r_id] = min(hi_map.get(r_id, l_num), l_num)
                elif op == ">=":
                    hi_map[r_id] = min(hi_map.get(r_id, l_num + 1), l_num + 1)

            # x < y  /  x <= y  -> edge x -> y with delta 1 or 0
            if l_id is not None and r_id is not None:
                if op == "<":
                    edges[l_id].append((r_id, 1))
                elif op == "<=":
                    edges[l_id].append((r_id, 0))
            # x > y or x >= y -> edge y -> x
            if l_id is not None and r_id is not None:
                if op == ">":
                    edges[r_id].append((l_id, 1))
                elif op == ">=":
                    edges[r_id].append((l_id, 0))

        return hi_map, edges

    def _extract_lower_bounds_multi(
        self, guard: Expr, var_names: list[str]
    ) -> dict[str, int]:
        """Extract constant inclusive lower bounds for variables from guard.

        Supported patterns (using integers):
        - x > K      -> lo(x) >= K+1
        - x >= K     -> lo(x) >= K
        - K < x      -> lo(x) >= K+1
        - K <= x     -> lo(x) >= K
        """
        lo_map: dict[str, int] = {}

        def is_id_of_var(node: Expr) -> Optional[str]:
            if isinstance(node, Identifier) and node.name in var_names:
                return node.name
            return None

        def const_int(node: Expr) -> Optional[int]:
            return self._is_const_int(node)

        for comp in self._collect_comparisons(guard):
            op = comp.op
            l_id = is_id_of_var(comp.left)
            r_id = is_id_of_var(comp.right)
            l_num = const_int(comp.left)
            r_num = const_int(comp.right)

            # x > K or x >= K
            if l_id is not None and r_num is not None:
                if op == ">":
                    lo_map[l_id] = max(lo_map.get(l_id, r_num + 1), r_num + 1)
                elif op == ">=":
                    lo_map[l_id] = max(lo_map.get(l_id, r_num), r_num)

            # K < x or K <= x
            if l_num is not None and r_id is not None:
                if op == "<":
                    lo_map[r_id] = max(lo_map.get(r_id, l_num + 1), l_num + 1)
                elif op == "<=":
                    lo_map[r_id] = max(lo_map.get(r_id, l_num), l_num)

        return lo_map

    def _propagate_hi_via_edges(
        self,
        base_hi: dict[str, int],
        edges: dict[str, list[tuple[str, int]]],
        var_names: list[str],
    ) -> dict[str, Optional[int]]:
        """Propagate upper bounds along ordering edges (u < v implies hi(u) <= hi(v) - 1).

        Returns a map name -> hi or None if unknown.
        """
        memo: dict[str, Optional[int]] = {}
        visiting: set[str] = set()

        def compute(name: str) -> Optional[int]:
            if name in memo:
                return memo[name]
            if name in visiting:
                # Cycle in ordering; cannot determine safely
                memo[name] = None
                return None
            visiting.add(name)
            # Start with any direct constant bound
            best: Optional[int] = base_hi.get(name)
            for nbr, delta in edges.get(name, []):
                if nbr not in var_names:
                    continue
                hi_nbr = compute(nbr)
                if hi_nbr is not None:
                    cand = hi_nbr - delta
                    best = cand if best is None else min(best, cand)
            visiting.remove(name)
            memo[name] = best
            return best

        for v in var_names:
            compute(v)
        return memo

    def _split_guard_phi(
        self, body: Expr, var_names: list[str]
    ) -> Optional[tuple[Expr, Expr]]:
        """Split body into (guard, phi) suitable for unrolling.

        - If body is implication, use its parts directly.
        - If body is conjunction, try choosing one conjunct as guard such that
          it yields bounds for at least one variable; phi is the conjunction of the rest.
        - Otherwise, return None (unsupported form).
        """

        if isinstance(body, BinaryOp) and body.op == "==>":
            return body.left, body.right

        if isinstance(body, BinaryOp) and body.op == "∧":
            conjuncts = self._flatten_conjuncts(body)
            guard_parts = [c for c in conjuncts if self._is_bound_relevant(c, var_names)]
            phi_parts = [
                c for c in conjuncts if not self._is_bound_relevant(c, var_names)
            ]

            if not guard_parts:
                return None

            guard = guard_parts[0]
            for c in guard_parts[1:]:
                guard = BinaryOp(left=guard, op="∧", right=c, ty=TypeNode(ty=Boolean()))

            if not phi_parts:
                return None
            phi = phi_parts[0]
            for c in phi_parts[1:]:
                phi = BinaryOp(left=phi, op="∧", right=c, ty=TypeNode(ty=Boolean()))
            return guard, phi
        return None

    def _unroll_quantifier(
        self,
        is_forall: bool,
        vars: Sequence[Identifier],
        body: Expr,
    ) -> Optional[Expr]:
        # Split into a guard that provides bounds and the remaining phi
        var_names = [v.name for v in vars]
        split = self._split_guard_phi(body, var_names)
        if split is None:
            return None
        guard, phi = split

        # Further split guard into bound-only and the rest; we will drop bound-only in instances
        bound_only, guard_rest_parts = self._split_guard_bound_vs_rest(guard, var_names)
        # Use only the bound-only part to extract bounds
        if bound_only:
            bound_guard = bound_only[0]
            for c in bound_only[1:]:
                bound_guard = BinaryOp(
                    left=bound_guard, op="∧", right=c, ty=TypeNode(ty=Boolean())
                )
        else:
            bound_guard = guard
        # Build guard_rest (default True if nothing remains)
        if not guard_rest_parts:
            guard_rest: Expr = BoolLiteral(value=True)
        else:
            guard_rest = guard_rest_parts[0]
            for c in guard_rest_parts[1:]:
                guard_rest = BinaryOp(
                    left=guard_rest, op="∧", right=c, ty=TypeNode(ty=Boolean())
                )

        # Extract bounds information from guard
        base_hi, edges = self._extract_bounds_multi(bound_guard, var_names)
        base_lo = self._extract_lower_bounds_multi(bound_guard, var_names)
        propagated_hi = self._propagate_hi_via_edges(base_hi, edges, var_names)

        # Decide which variables we can enumerate (those with known constant hi)
        enum_vars: list[Identifier] = []
        enum_lo: list[int] = []
        enum_hi: list[int] = []
        leftover_vars: list[Identifier] = []
        for v in vars:
            hi = propagated_hi.get(v.name)
            if hi is not None:
                enum_vars.append(v)
                enum_hi.append(hi)
                enum_lo.append(base_lo.get(v.name, 0))
            else:
                leftover_vars.append(v)

        # If nothing can be enumerated, bail out
        if not enum_vars:
            return None

        # Check product threshold across enumerated variables
        total_space = 1
        for lo, hi in zip(enum_lo, enum_hi):
            size = hi - lo
            if size <= 0:
                total_space = 0
                break
            total_space *= size
            if total_space > self._unroll_threshold:
                return None

        # Generate nested enumeration
        instances: list[Expr] = []

        def build_instance(subs: dict[str, Expr]) -> Expr:
            g_rest_inst = _subst_expr(copy.deepcopy(guard_rest), subs)
            p_inst = _subst_expr(copy.deepcopy(phi), subs)
            # Drop bound-only guard (already enforced by enumeration). Keep any remaining guard.
            if isinstance(g_rest_inst, BoolLiteral) and g_rest_inst.value is True:
                return self._post_instance_opt(p_inst)
            if is_forall:
                return self._post_instance_opt(
                    BinaryOp(pos=p_inst.pos, left=g_rest_inst, op="==>", right=p_inst)
                )
            else:
                return self._post_instance_opt(
                    BinaryOp(pos=p_inst.pos, left=g_rest_inst, op="∧", right=p_inst)
                )

        def recurse(idx: int, subs: dict[str, Expr]) -> None:
            if idx == len(enum_vars):
                instances.append(build_instance(subs))
                return
            v = enum_vars[idx]
            lo = enum_lo[idx]
            hi = enum_hi[idx]
            for i in range(lo, hi):
                subs2 = dict(subs)
                subs2[v.name] = NumberLiteral(pos=v.pos, value=i)
                recurse(idx + 1, subs2)

        if total_space == 0:
            # Empty domain
            return BoolLiteral(pos=body.pos, value=is_forall)

        recurse(0, {})
        if not instances:
            return BoolLiteral(pos=body.pos, value=is_forall)

        def fold_and(exprs: list[Expr]) -> Expr:
            acc = exprs[0]
            for e in exprs[1:]:
                acc = BinaryOp(pos=e.pos, left=acc, op="∧", right=e, ty=e.ty)
            return acc

        def fold_or(exprs: list[Expr]) -> Expr:
            acc = exprs[0]
            for e in exprs[1:]:
                acc = BinaryOp(pos=e.pos, left=acc, op="∨", right=e, ty=e.ty)
            return acc

        folded = fold_and(instances) if is_forall else fold_or(instances)
        folded = self._post_instance_opt(folded)

        # If there are leftover variables (unbounded), keep a quantifier for them
        if leftover_vars:
            if is_forall:
                return ForallExpr(
                    pos=body.pos,
                    vars=leftover_vars,
                    satisfies_expr=folded,
                    ty=folded.ty,
                )
            else:
                return ExistsExpr(
                    pos=body.pos,
                    vars=leftover_vars,
                    satisfies_expr=folded,
                    ty=folded.ty,
                )
        return folded

    def visit_ForallExpr(self, node: ForallExpr):
        body = self.transform(node.satisfies_expr)
        node = replace(node, satisfies_expr=body)
        unrolled = self._unroll_quantifier(True, node.vars, node.satisfies_expr)
        return unrolled if unrolled is not None else node

    def visit_ExistsExpr(self, node):
        body = self.transform(node.satisfies_expr)
        node = replace(node, satisfies_expr=body)
        unrolled = self._unroll_quantifier(False, node.vars, node.satisfies_expr)
        return unrolled if unrolled is not None else node


class FiniteCollectionQuantifierElimination(ASTTransformer[ASTNode]):
    """Eliminate quantifiers by enumerating finite set/list domains from guards.

    Supported patterns in the quantifier guard (left of ==>):
      - set_is_subset(s, {c1, c2, ...}) where s is a bound set variable
      - contains([c1, c2, ...], l) where l is a bound list variable

    For these cases we enumerate all possible values of the bound variable
    (all subsets or all contiguous sublists respectively) when the total
    enumeration size is below a configurable threshold.
    """

    def __init__(self, *, unroll_threshold: int = 64):
        super().__init__()
        self._unroll_threshold = unroll_threshold

    # -------------------------- helpers: structure --------------------------
    def _flatten_conjuncts(self, e: Expr) -> list[Expr]:
        items: list[Expr] = []

        def rec(x: Expr) -> None:
            if isinstance(x, BinaryOp) and x.op == "∧":
                rec(x.left)
                rec(x.right)
            else:
                items.append(x)

        rec(e)
        return items

    # ---------------------- helpers: constant extraction --------------------
    def _expand_range_elements(self, node: RangeList | RangeSet) -> list[Expr] | None:
        # Numeric literal ranges
        if isinstance(node.start, NumberLiteral) and isinstance(
            node.end, NumberLiteral
        ):
            lo = int(node.start.value)
            hi = int(node.end.value)
            hi_range = range(lo, hi + 1) if lo <= hi else []
            return [NumberLiteral(value=i) for i in hi_range]
        # Char literal ranges
        if isinstance(node.start, CharLiteral) and isinstance(node.end, CharLiteral):
            s = node.start.value
            e = node.end.value
            if len(s) == 1 and len(e) == 1:
                lo = ord(s)
                hi = ord(e)
                rng = range(lo, hi + 1) if lo <= hi else []
                return [CharLiteral(value=chr(i)) for i in rng]
        return None

    def _const_set_elems(self, expr: Expr) -> list[Expr] | None:
        if isinstance(expr, ExplicitSet):
            return list(expr.elements)
        if isinstance(expr, RangeSet):
            return self._expand_range_elements(expr)
        return None

    def _const_list_elems(self, expr: Expr) -> list[Expr] | None:
        if isinstance(expr, ExplicitList):
            return list(expr.elements)
        if isinstance(expr, RangeList):
            return self._expand_range_elements(expr)
        return None

    # ------------------------- helpers: guard finding -----------------------
    def _find_subset_guard(
        self, guard: Expr, bound_names: set[str]
    ) -> tuple[str, list[Expr], Expr] | None:
        for g in self._flatten_conjuncts(guard):
            if isinstance(g, FuncCall) and isinstance(g.func, Identifier):
                if g.func.name == "set_is_subset" and len(g.args) == 2:
                    left, right = g.args
                    if isinstance(left, Identifier) and left.name in bound_names:
                        elems = self._const_set_elems(right)  # type: ignore[arg-type]
                        if elems is not None:
                            return left.name, elems, guard
        return None

    def _find_contains_guard(
        self, guard: Expr, bound_names: set[str]
    ) -> tuple[str, list[Expr], Expr] | None:
        for g in self._flatten_conjuncts(guard):
            if isinstance(g, FuncCall) and isinstance(g.func, Identifier):
                if g.func.name == "contains" and len(g.args) == 2:
                    left, right = g.args
                    # Only support finite enumeration when the constant is the FIRST arg:
                    # contains(const_list, _)
                    elems = self._const_list_elems(left)
                    if elems is not None and isinstance(right, Identifier):
                        if right.name in bound_names:
                            return right.name, elems, guard
        return None

    def _find_in_guard(
        self, guard: Expr, bound_names: set[str]
    ) -> tuple[str, list[Expr], Expr] | None:
        for g in self._flatten_conjuncts(guard):
            if isinstance(g, BinaryOp) and g.op == "in":
                left = g.left
                right = g.right
                if isinstance(left, Identifier) and left.name in bound_names:
                    elems = self._const_list_elems(right) or self._const_set_elems(
                        right
                    )
                    if elems is not None:
                        return left.name, elems, guard
        return None

    def _is_domain_guard_for_var(self, g: Expr, var_name: str) -> bool:
        # Matches: set_is_subset(var, CONST)
        if isinstance(g, FuncCall) and isinstance(g.func, Identifier):
            if g.func.name == "set_is_subset" and len(g.args) == 2:
                left, right = g.args
                if isinstance(left, Identifier) and left.name == var_name:
                    if self._const_set_elems(right) is not None:
                        return True
            if g.func.name == "contains" and len(g.args) == 2:
                left, right = g.args
                # contains(CONST_LIST, var)
                if (
                    self._const_list_elems(left) is not None
                    and isinstance(right, Identifier)
                    and right.name == var_name
                ):
                    return True
        # Matches: var in CONST
        if isinstance(g, BinaryOp) and g.op == "in":
            left = g.left
            right = g.right
            if isinstance(left, Identifier) and left.name == var_name:
                if (
                    self._const_list_elems(right) is not None
                    or self._const_set_elems(right) is not None
                ):
                    return True
        return False

    def _strip_domain_guards(self, guard: Expr, var_name: str) -> Expr:
        parts = self._flatten_conjuncts(guard)
        kept: list[Expr] = [
            p for p in parts if not self._is_domain_guard_for_var(p, var_name)
        ]
        if not kept:
            return BoolLiteral(value=True)
        acc = kept[0]
        for e in kept[1:]:
            acc = BinaryOp(left=acc, op="∧", right=e, ty=TypeNode(ty=Boolean()))
        return acc

    def _post_instance_opt(self, e: Expr) -> Expr:
        # Apply a light, local optimization pipeline to avoid AST bloat
        tmp: ASTNode = e
        repeat_cp = 2
        for _ in range(repeat_cp):
            tmp = ConstantPropagation().transform(tmp)
            tmp = EqualityConstraintPropagation().transform(tmp)
        tmp = BooleanSimplify().transform(tmp)
        assert isinstance(tmp, Expr)
        return tmp

    # ------------------------ helpers: enumeration -------------------------
    def _enumerate_subsets(self, elems: list[Expr], *, ty_node) -> list[ExplicitSet]:
        n = len(elems)
        results: list[ExplicitSet] = []
        for mask in range(1 << n):
            subset: list[Expr] = []
            for i in range(n):
                if (mask >> i) & 1:
                    subset.append(copy.deepcopy(elems[i]))
            results.append(ExplicitSet(elements=subset, ty=ty_node))
        return results

    def _enumerate_sublists(self, elems: list[Expr], *, ty_node) -> list[ExplicitList]:
        n = len(elems)
        results: list[ExplicitList] = []
        for i in range(n + 1):
            for j in range(i, n + 1):
                results.append(
                    ExplicitList(
                        elements=[copy.deepcopy(e) for e in elems[i:j]], ty=ty_node
                    )
                )
        return results

    def _subset_count_exceeds_threshold(self, elem_count: int) -> bool:
        threshold = self._unroll_threshold
        if threshold < 0:
            return True
        return elem_count >= threshold.bit_length()

    def _sublists_count(self, elem_count: int) -> int:
        return (elem_count + 1) * (elem_count + 2) // 2

    # ----------------------- core elimination algorithm ---------------------
    def _eliminate(
        self, is_forall: bool, vars: Sequence[Identifier], body: Expr
    ) -> Expr | None:
        # Only consider implications for now: guard ==> phi
        if not (isinstance(body, BinaryOp) and body.op == "==>"):
            return None
        guard = body.left
        phi = body.right
        bound = {v.name for v in vars}

        guard_kind: str | None = None
        found = self._find_subset_guard(guard, bound)
        if found is not None:
            guard_kind = "subset"
        else:
            found = self._find_contains_guard(guard, bound)
            if found is not None:
                guard_kind = "contains"
            else:
                found = self._find_in_guard(guard, bound)
                if found is not None:
                    guard_kind = "membership"

        if found is None or guard_kind is None:
            return None
        var_name, const_elems, full_guard = found

        if guard_kind == "subset":
            if self._subset_count_exceeds_threshold(len(const_elems)):
                return None
        elif guard_kind == "contains":
            if self._sublists_count(len(const_elems)) > self._unroll_threshold:
                return None
        else:
            if len(const_elems) == 0:
                return BoolLiteral(pos=body.pos, value=is_forall)
            if len(const_elems) > self._unroll_threshold:
                return None

        guard_rest = self._strip_domain_guards(full_guard, var_name)
        var_ident = next((v for v in vars if v.name == var_name), None)
        var_ty_node = var_ident.ty if var_ident is not None else None

        # Determine enumeration domain by which finder matched
        domain_values_exprs: Sequence[Expr] | None = None
        domain_values_collections: Sequence[ExplicitSet | ExplicitList] | None = None
        if guard_kind == "subset":
            # Enumerate subsets for set variables
            domain_values_collections = self._enumerate_subsets(
                const_elems, ty_node=var_ty_node
            )
        elif guard_kind == "contains":
            # Enumerate contiguous sublists for list variables
            domain_values_collections = self._enumerate_sublists(
                const_elems, ty_node=var_ty_node
            )
        else:
            # x in const-set/list: enumerate element values directly
            domain_values_exprs = const_elems

        # Threshold check
        if (domain_values_exprs is not None and len(domain_values_exprs) == 0) or (
            domain_values_collections is not None
            and len(domain_values_collections) == 0
        ):
            return BoolLiteral(pos=body.pos, value=is_forall)
        if (
            domain_values_exprs is not None
            and len(domain_values_exprs) > self._unroll_threshold
        ) or (
            domain_values_collections is not None
            and len(domain_values_collections) > self._unroll_threshold
        ):
            return None

        # Leftover quantified variables
        leftover_vars = [v for v in vars if v.name != var_name]

        instances: list[Expr] = []
        if domain_values_exprs is not None:
            for val in domain_values_exprs:
                subst_map_e: Mapping[str, Expr] = {var_name: copy.deepcopy(val)}
                g_inst = _subst_expr(copy.deepcopy(guard_rest), subst_map_e)
                p_inst = _subst_expr(copy.deepcopy(phi), subst_map_e)
                if isinstance(g_inst, BoolLiteral) and g_inst.value is True:
                    instances.append(self._post_instance_opt(p_inst))
                elif is_forall:
                    instances.append(
                        self._post_instance_opt(
                            BinaryOp(
                                pos=p_inst.pos, left=g_inst, op="==>", right=p_inst
                            )
                        )
                    )
                else:
                    instances.append(
                        self._post_instance_opt(
                            BinaryOp(pos=p_inst.pos, left=g_inst, op="∧", right=p_inst)
                        )
                    )
        elif domain_values_collections is not None:
            for val in domain_values_collections:
                subst_map_c: Mapping[str, Expr] = {var_name: val}
                g_inst = _subst_expr(copy.deepcopy(guard_rest), subst_map_c)
                p_inst = _subst_expr(copy.deepcopy(phi), subst_map_c)
                if isinstance(g_inst, BoolLiteral) and g_inst.value is True:
                    instances.append(self._post_instance_opt(p_inst))
                elif is_forall:
                    instances.append(
                        self._post_instance_opt(
                            BinaryOp(
                                pos=p_inst.pos, left=g_inst, op="==>", right=p_inst
                            )
                        )
                    )
                else:
                    instances.append(
                        self._post_instance_opt(
                            BinaryOp(pos=p_inst.pos, left=g_inst, op="∧", right=p_inst)
                        )
                    )

        # Fold results
        def fold_and(exprs: list[Expr]) -> Expr:
            acc = exprs[0]
            for e in exprs[1:]:
                acc = BinaryOp(pos=e.pos, left=acc, op="∧", right=e, ty=e.ty)
            return acc

        def fold_or(exprs: list[Expr]) -> Expr:
            acc = exprs[0]
            for e in exprs[1:]:
                acc = BinaryOp(pos=e.pos, left=acc, op="∨", right=e, ty=e.ty)
            return acc

        folded = fold_and(instances) if is_forall else fold_or(instances)
        folded = self._post_instance_opt(folded)

        if leftover_vars:
            if is_forall:
                return ForallExpr(
                    pos=body.pos,
                    vars=leftover_vars,
                    satisfies_expr=folded,
                    ty=folded.ty,
                )
            else:
                return ExistsExpr(
                    pos=body.pos,
                    vars=leftover_vars,
                    satisfies_expr=folded,
                    ty=folded.ty,
                )
        return folded

    # ------------------------------- visitors --------------------------------
    def visit_ForallExpr(self, node: ForallExpr):
        body = self.transform(node.satisfies_expr)
        node = replace(node, satisfies_expr=body)
        elim = self._eliminate(True, node.vars, node.satisfies_expr)
        return elim if elim is not None else node

    def visit_ExistsExpr(self, node: ExistsExpr):
        body = self.transform(node.satisfies_expr)
        node = replace(node, satisfies_expr=body)
        elim = self._eliminate(False, node.vars, node.satisfies_expr)
        return elim if elim is not None else node


class ImplicitToExplicit(ASTTransformer[ASTNode]):
    """Convert implicit functions with ensures to explicit bodies when possible."""

    def visit_FunctionDef(self, func: FunctionDef):
        if func.body is not None or func.return_val is None:
            return func
        if len(func.ensures) != 1:
            return func
        only_ensure = func.ensures[0]
        if self._is_return_equality(only_ensure, func.return_val.name):
            body_expr = self._extract_body_expression(
                only_ensure.expr, func.return_val.name
            )
            new_return_val = Identifier(
                name="return_val", ty=func.return_val.ty, pos=func.return_val.pos
            )
            return FunctionDef(
                name=func.name,
                args=func.args,
                return_val=new_return_val,
                description=func.description,
                var_decls=func.var_decls,
                requires=func.requires,
                ensures=[],
                body=body_expr,
                pos=func.pos,
            )
        return func

    def _is_return_equality(self, ensure: Ensure, return_var_name: str) -> bool:
        expr = ensure.expr
        if isinstance(expr, BinaryOp):
            return self._check_binary_op_equality(expr, return_var_name)
        if isinstance(expr, Comparisons) and len(expr.comparisons) == 1:
            return self._check_binary_op_equality(expr.comparisons[0], return_var_name)
        return False

    def _check_binary_op_equality(
        self, binary_op: BinaryOp, return_var_name: str
    ) -> bool:
        if binary_op.op != "==":
            return False
        if (
            isinstance(binary_op.left, Identifier)
            and binary_op.left.name == return_var_name
        ):
            return True
        if (
            isinstance(binary_op.right, Identifier)
            and binary_op.right.name == return_var_name
        ):
            return True
        return False

    def _extract_body_expression(self, expr: ASTNode, return_var_name: str) -> Expr:
        if isinstance(expr, BinaryOp):
            return self._extract_from_binary_op(expr, return_var_name)
        if isinstance(expr, Comparisons) and len(expr.comparisons) == 1:
            return self._extract_from_binary_op(expr.comparisons[0], return_var_name)
        raise ValueError(f"Cannot extract body expression from {type(expr).__name__}")

    def _extract_from_binary_op(
        self, binary_op: BinaryOp, return_var_name: str
    ) -> Expr:
        if (
            isinstance(binary_op.left, Identifier)
            and binary_op.left.name == return_var_name
        ):
            return binary_op.right
        if (
            isinstance(binary_op.right, Identifier)
            and binary_op.right.name == return_var_name
        ):
            return binary_op.left
        return binary_op


class FoldConstantImplicitContracts(ASTTransformer[ASTNode]):
    """Fold selected implicit contract calls when constant arguments determine the result."""

    def __init__(self, *, entry_func: str = "spec"):
        super().__init__()
        self._entry_func = entry_func
        self._defs: dict[str, PredicateDef | FunctionDef] = {}

    def visit_Specification(self, node: Specification):  # type: ignore[override]
        self._defs = {}
        for decl in node.declarations:
            if isinstance(decl, (PredicateDef, FunctionDef)):
                self._defs[decl.name] = copy.deepcopy(decl)

        new_decls = []
        for decl in node.declarations:
            if decl.name == self._entry_func:
                new_decls.append(self.transform(decl))
            else:
                new_decls.append(decl)
        return replace(node, declarations=new_decls)

    def visit_FunctionDef(self, node: FunctionDef):
        body = self.transform(node.body) if node.body is not None else None
        requires = [self.transform(expr) for expr in node.requires]
        ensures = [self.transform(expr) for expr in node.ensures]
        return replace(node, body=body, requires=requires, ensures=ensures)

    def visit_PredicateDef(self, node: PredicateDef):
        if node.body is None:
            return node
        body = self.transform(node.body)
        return replace(node, body=body)

    def visit_FuncCall(self, node: FuncCall):
        func = self.transform(node.func)
        args = [self.transform(arg) for arg in node.args]
        args = cast(list[Expr], args)
        node = replace(node, func=func, args=args)

        if not isinstance(func, Identifier):
            return node

        ast_def = self._defs.get(func.name)
        if not isinstance(ast_def, FunctionDef) or ast_def.body is not None:
            return node

        folded = self._fold_constant_sort_contract(ast_def, args, node)
        return folded if folded is not None else node

    def _fold_constant_sort_contract(
        self, func: FunctionDef, args: list[Expr], node: FuncCall
    ) -> Expr | None:
        if not self._matches_sort_contract(func):
            return None
        if len(args) != 1:
            return None

        elems = self._const_list_elems(args[0])
        if elems is None:
            return None

        decorated: list[tuple[tuple[int, object], Expr]] = []
        for elem in elems:
            sort_key = self._sort_key(elem)
            if sort_key is None:
                return None
            decorated.append((sort_key, elem))

        sorted_elems = [elem for _, elem in sorted(decorated, key=lambda item: item[0])]
        return ExplicitList(pos=node.pos, elements=sorted_elems, ty=node.ty)

    def _matches_sort_contract(self, func: FunctionDef) -> bool:
        if (
            func.return_val is None
            or func.body is not None
            or len(func.args) != 1
            or len(func.requires) != 0
            or len(func.ensures) != 1
        ):
            return False

        conjuncts = self._flatten_conjuncts(func.ensures[0].expr)
        if len(conjuncts) != 2:
            return False

        return_name = func.return_val.name
        arg_name = func.args[0].name
        saw_sorted = False
        saw_perm = False
        for conjunct in conjuncts:
            if self._is_call_to(conjunct, "is_sorted", [return_name]):
                saw_sorted = True
                continue
            if self._is_call_to(
                conjunct, "is_permutation", [return_name, arg_name]
            ) or self._is_call_to(conjunct, "is_permutation", [arg_name, return_name]):
                saw_perm = True
                continue
            return False
        return saw_sorted and saw_perm

    def _flatten_conjuncts(self, expr: Expr) -> list[Expr]:
        if isinstance(expr, BinaryOp) and expr.op == "∧":
            return self._flatten_conjuncts(expr.left) + self._flatten_conjuncts(
                expr.right
            )
        return [expr]

    def _is_call_to(self, expr: Expr, name: str, arg_names: list[str]) -> bool:
        if not isinstance(expr, FuncCall):
            return False
        if not isinstance(expr.func, Identifier) or expr.func.name != name:
            return False
        if len(expr.args) != len(arg_names):
            return False
        return all(
            isinstance(arg, Identifier) and arg.name == expected
            for arg, expected in zip(expr.args, arg_names)
        )

    def _const_list_elems(self, expr: Expr) -> list[Expr] | None:
        if isinstance(expr, ExplicitList):
            return list(expr.elements)
        if isinstance(expr, RangeList):
            return self._expand_range_elements(expr)
        return None

    def _expand_range_elements(self, expr: RangeList) -> list[Expr] | None:
        if isinstance(expr.start, NumberLiteral) and isinstance(
            expr.end, NumberLiteral
        ):
            lo = int(expr.start.value)
            hi = int(expr.end.value)
            return (
                [NumberLiteral(value=i) for i in range(lo, hi + 1)] if lo <= hi else []
            )
        if isinstance(expr.start, CharLiteral) and isinstance(expr.end, CharLiteral):
            if len(expr.start.value) != 1 or len(expr.end.value) != 1:
                return None
            lo = ord(expr.start.value)
            hi = ord(expr.end.value)
            return (
                [CharLiteral(value=chr(i)) for i in range(lo, hi + 1)]
                if lo <= hi
                else []
            )
        return None

    def _sort_key(self, expr: Expr) -> tuple[int, object] | None:
        if isinstance(expr, NumberLiteral):
            return (0, expr.value)
        if isinstance(expr, CharLiteral):
            return (1, expr.value)
        return None


class VarSubstitution(ASTTransformer[ASTNode]):
    """Substitute all VarDecls in PredicateDef and FunctionDef with their expressions."""

    def visit_PredicateDef(self, node: PredicateDef):
        subs = {vd.var.name: vd.expr for vd in node.var_decls}
        if node.body is not None:
            node.body = _subst_expr(node.body, subs)
        return node

    def visit_FunctionDef(self, node: FunctionDef):
        subs = {vd.var.name: vd.expr for vd in node.var_decls}
        if node.body is not None:
            node.body = _subst_expr(node.body, subs)
        for req in node.requires:
            req.expr = _subst_expr(req.expr, subs)
        for ens in node.ensures:
            ens.expr = _subst_expr(ens.expr, subs)
        return node


class InlineCallsWithFuel(ASTTransformer[ASTNode]):
    """Inline explicit predicate/function bodies with fuel-based recursion handling.

    - Only inlines calls whose target has an explicit body (i.e., `body is not None`).
    - Uses a per-function fuel counter to avoid infinite inlining for recursive calls.
    - Assumes all `var_decls` have already been substituted away by earlier passes.
    """

    def __init__(self, *, default_fuel: int = 8, entry_func="spec"):
        super().__init__()
        if default_fuel < 0:
            raise ValueError("Fuel must be non-negative")
        self._default_fuel: int = default_fuel
        self._entry_func = entry_func
        self._fuel_env_stack: list[dict[str, int]] = []
        self._defs: dict[str, PredicateDef | FunctionDef] = {}
        # Cache for memoized inlining: (func_name, args_fingerprint, fuel) -> Expr
        self._inline_cache: dict[tuple[str, tuple, int], Expr] = {}

    def set_default_fuel(self, fuel: int) -> None:
        if fuel < 0:
            raise ValueError("Fuel must be non-negative")
        self._default_fuel = fuel

    def _get_fuel(self) -> int:
        return self._default_fuel - len(self._fuel_env_stack)

    def _push_fuel_frame(self, func_name: str) -> bool:
        remaining = self._get_fuel()
        if remaining <= 0:
            return False
        self._fuel_env_stack.append({func_name: remaining - 1})
        return True

    def _pop_fuel_frame(self):
        if not self._fuel_env_stack:
            return
        self._fuel_env_stack.pop()

    # --------------- memoization helpers ---------------
    def _fingerprint_expr(self, e: Expr):  # returns a hashable structural fingerprint
        if isinstance(e, Identifier):
            return ("id", e.name)
        if isinstance(e, BoolLiteral):
            return ("bool", e.value)
        if isinstance(e, NumberLiteral):
            return ("num", e.value)
        if isinstance(e, CharLiteral):
            return ("char", e.value)
        if isinstance(e, FuncCall):
            # fingerprint callee structurally; often Identifier
            callee_fp = (
                ("id", e.func.name)
                if isinstance(e.func, Identifier)
                else ("expr", self._fingerprint_expr(cast(Expr, e.func)))
            )
            args_fp = tuple(self._fingerprint_expr(a) for a in e.args)
            return ("call", callee_fp, args_fp)
        if isinstance(e, IfExpr):
            return (
                "if",
                self._fingerprint_expr(e.condition),
                self._fingerprint_expr(e.then_branch),
                self._fingerprint_expr(e.else_branch),
            )
        if isinstance(e, BinaryOp):
            return (
                "bin",
                e.op,
                self._fingerprint_expr(cast(Expr, e.left)),
                self._fingerprint_expr(cast(Expr, e.right)),
            )
        if isinstance(e, Comparisons):
            comps = []
            for c in e.comparisons:
                if isinstance(c, BinaryOp):
                    comps.append(
                        (
                            c.op,
                            self._fingerprint_expr(cast(Expr, c.left)),
                            self._fingerprint_expr(cast(Expr, c.right)),
                        )
                    )
            return ("cmps", tuple(comps))
        if isinstance(e, ExplicitList):
            return ("list", tuple(self._fingerprint_expr(el) for el in e.elements))
        if isinstance(e, ExplicitSet):
            # Keep order as in AST; it's stable for our purposes
            return ("set", tuple(self._fingerprint_expr(el) for el in e.elements))
        if isinstance(e, RangeList):
            return (
                "range_list",
                self._fingerprint_expr(cast(Expr, e.start)),
                self._fingerprint_expr(cast(Expr, e.end)),
            )
        if isinstance(e, RangeSet):
            return (
                "range_set",
                self._fingerprint_expr(cast(Expr, e.start)),
                self._fingerprint_expr(cast(Expr, e.end)),
            )
        # Fallback: type name only (conservative)
        return ("node", type(e).__name__)

    def _args_fingerprint(self, args: list[Expr]) -> tuple:
        return tuple(self._fingerprint_expr(a) for a in args)

    # Definition table
    def visit_Specification(self, node: Specification):  # type: ignore[override]
        # Build a simple name -> def mapping for use during inlining.
        self._defs = {}
        for d in node.declarations:
            if isinstance(d, (PredicateDef, FunctionDef)):
                self._defs[d.name] = copy.deepcopy(d)
        new_decls = []
        for d in node.declarations:
            if d.name == self._entry_func:
                new_decls.append(self.transform(d))
            else:
                new_decls.append(d)
        return replace(node, declarations=new_decls)

    def visit_FunctionDef(self, node: FunctionDef):
        body = self.transform(node.body) if node.body is not None else None
        requires = [self.transform(e) for e in node.requires]
        ensures = [self.transform(e) for e in node.ensures]
        return replace(node, body=body, requires=requires, ensures=ensures)

    def visit_PredicateDef(self, node: PredicateDef):
        if node.body is None:
            return node
        body = self.transform(node.body)
        return replace(node, body=body)

    def _inline_explicit_body(
        self,
        ast_def: PredicateDef | FunctionDef,
        actual_args: list[Expr],
    ) -> Expr:
        assert ast_def.body is not None
        # Map formal parameters to actual arguments (already transformed).
        subs: dict[str, Expr] = {
            formal.name: actual for formal, actual in zip(ast_def.args, actual_args)
        }
        body_copy = copy.deepcopy(ast_def.body)
        inlined = _Substitution(subs).transform(body_copy)
        inlined = self.transform(inlined)
        assert isinstance(inlined, Expr)
        return inlined

    def visit_FuncCall(self, node: FuncCall):
        # First, transform callee and arguments.
        func = self.transform(node.func)
        args = [self.transform(a) for a in node.args]
        args = cast(list[Expr], args)
        node = replace(node, func=func, args=args)

        # Only consider identifier calls that target explicit definitions.
        if not isinstance(func, Identifier):
            return node
        target_name = func.name
        ast_def = self._defs.get(target_name)
        if ast_def is None:
            return node

        if ast_def.body is None:
            return node

        # Do not inline functions that declare preconditions; we must preserve
        # the call so that callsite precondition checks can be enforced.
        if isinstance(ast_def, FunctionDef) and len(ast_def.requires) > 0:
            return node

        # Memoization: reuse inlining result when arguments and fuel match
        remaining_fuel = self._get_fuel()
        cache_key = (target_name, self._args_fingerprint(args), remaining_fuel)
        cached = self._inline_cache.get(cache_key)
        if cached is not None:
            reuse = copy.deepcopy(cached)
            reuse = replace(reuse, ty=node.ty)
            return reuse

        if not self._push_fuel_frame(target_name):
            return node

        try:
            result = self._inline_explicit_body(ast_def, args)
            result = replace(result, ty=node.ty)
            # Store a deep copy to avoid accidental aliasing
            self._inline_cache[cache_key] = copy.deepcopy(result)
            return result
        finally:
            self._pop_fuel_frame()


class RemoveUnusedDefinitions(ASTTransformer[ASTNode]):
    """Remove unreferenced FunctionDef/PredicateDef starting from entry function.

    Uses ReferenceCollector to compute reachability from the given entry point.
    """

    def __init__(self, *, entry_func: str = "spec"):
        super().__init__()
        self._entry_func = entry_func

    def visit_Specification(self, node: Specification):  # type: ignore[override]
        # Map names to defs
        defs: dict[str, PredicateDef | FunctionDef] = {}
        for d in node.declarations:
            if isinstance(d, (PredicateDef, FunctionDef)):
                defs[d.name] = d

        entry = self._entry_func
        if entry not in defs:
            return node

        defined_names = set(defs.keys())
        rc = ReferenceCollector(defined_names)

        reachable: set[str] = set()
        work: list[str] = [entry]

        while work:
            name = work.pop()
            if name in reachable:
                continue
            reachable.add(name)
            d = defs.get(name)
            if d is None:
                continue

            referenced: set[str] = set()
            if isinstance(d, FunctionDef):
                for req in d.requires:
                    referenced |= rc.collect(req)
                for ens in d.ensures:
                    referenced |= rc.collect(ens)
                if d.body is not None:
                    referenced |= rc.collect(d.body)
            else:  # PredicateDef
                if d.body is not None:
                    referenced |= rc.collect(d.body)

            for ref in referenced:
                if ref not in reachable and ref in defined_names:
                    work.append(ref)

        # Keep reachable defs and any non-function/predicate declarations
        new_decls = []
        for d in node.declarations:
            if isinstance(d, (PredicateDef, FunctionDef)):
                if d.name in reachable:
                    new_decls.append(d)
            else:
                new_decls.append(d)

        return replace(node, declarations=new_decls)


class DSLOptimizer:
    """Compatibility wrapper exposing an optimize(spec) method."""

    def __init__(self, *, unroll_threshold: int = 256, inline_fuel: int = 8):
        self._unroll_threshold = unroll_threshold
        self._inline_fuel = inline_fuel

    def optimize(self, spec: Specification, entry_func: str = "spec") -> Specification:
        current: Specification = spec

        def _apply(transformer: ASTTransformer[ASTNode]) -> bool:
            nonlocal current
            # Run a transformer and preserve the most recent successful AST if recursion overflows.
            try:
                result = transformer.transform(current)
            except RecursionError:
                return False
            assert isinstance(result, Specification)
            current = result
            return True

        def _pre_simplify(*, rounds: int = 2) -> bool:
            """Lightweight simplification pass to keep later substitutions small."""
            for _ in range(rounds):
                if not _apply(ConstantPropagation()):
                    return False
                if not _apply(EqualityConstraintPropagation()):
                    return False
            return _apply(BooleanSimplify())

        if not _pre_simplify():
            return current

        if not _apply(VarSubstitution()):
            return current

        if not _pre_simplify(rounds=1):
            return current

        if not _apply(ImplicitToExplicit()):
            return current

        if not _pre_simplify(rounds=1):
            return current

        if not _apply(
            InlineCallsWithFuel(default_fuel=self._inline_fuel, entry_func=entry_func)
        ):
            return current
        if not _apply(RemoveUnusedDefinitions(entry_func=entry_func)):
            return current

        repeat_cp = 3
        for _ in range(repeat_cp):
            if not _apply(ConstantPropagation()):
                return current
            if not _apply(EqualityConstraintPropagation()):
                return current
            if not _apply(ConstantPropagation()):
                return current
            if not _apply(EqualityConstraintPropagation()):
                return current

        if not _apply(FoldConstantImplicitContracts(entry_func=entry_func)):
            return current
        if not _pre_simplify(rounds=1):
            return current
        if not _apply(DropUnusedQuantifiers()):
            return current
        if not _apply(
            FiniteCollectionQuantifierElimination(
                unroll_threshold=self._unroll_threshold
            )
        ):
            return current
        if not _apply(QuantifierElimination(unroll_threshold=self._unroll_threshold)):
            return current
        if not _apply(BooleanSimplify()):
            return current
        if not _apply(RemoveUnusedDefinitions(entry_func=entry_func)):
            return current

        return current
