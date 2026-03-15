from __future__ import annotations

"""Convert DSL AST into Z3 expressions.

Supports the full DSL specification language including:
  • Predicates and functions with type inference
  • Variable declarations and statements
  • Full expression language (arithmetic, boolean, comparisons)
  • Quantifiers (forall/exists)
  • Collections (lists, sets) and higher-order functions
  • String operations

Integrates with the type checker to obtain type information for variables.
"""

import math
from typing import Dict, List, Optional, Sequence, Union, cast

import z3

from . import dsl_ast as _ast
from .ast_traverse import ASTTransformer
from .constants import RealEncodingMode
from .type_checker import TypeChecker


class ASTToZ3(ASTTransformer[z3.ExprRef]):
    """Visitor that converts DSL AST to Z3 expressions."""

    def __init__(
        self,
        negate_result: bool = False,
        real_encoding: RealEncodingMode | str = RealEncodingMode.REAL,
    ):
        super().__init__()
        self._ctx = z3.Context()
        self._negate = negate_result
        self._real_encoding = (
            real_encoding
            if isinstance(real_encoding, RealEncodingMode)
            else RealEncodingMode(real_encoding)
        )
        fp_sort: z3.FPSortRef | None = None
        fp_rounding: z3.FPRMRef | None = None
        if self._real_encoding == RealEncodingMode.FLOATING_POINT:
            fp_sort = z3.FPSort(11, 53, ctx=self._ctx)
            fp_rounding = z3.RNE(ctx=self._ctx)
        self._fp_sort = fp_sort
        self._fp_rounding = fp_rounding
        self._env: List[Dict[str, Union[z3.ExprRef, z3.FuncDeclRef]]] = [{}]
        self._constraints: List[z3.BoolRef] = []
        self._local_constraints: List[
            List[z3.BoolRef]
        ] = []  # Stack of local constraint contexts
        self._type_checker: TypeChecker = TypeChecker()
        self._var_types: Dict[str, _ast.DSLType] = {}  # Track variable types
        self._tuple_datatypes: Dict[
            str, tuple[z3.DatatypeSortRef, z3.FuncDeclRef, List[z3.FuncDeclRef]]
        ] = {}
        self._record_datatypes: Dict[
            str, tuple[z3.DatatypeSortRef, z3.FuncDeclRef, Dict[str, z3.FuncDeclRef]]
        ] = {}
        self._sized_set_datatypes: Dict[
            str, tuple[z3.DatatypeSortRef, z3.FuncDeclRef, List[z3.FuncDeclRef]]
        ] = {}
        self._option_datatypes: Dict[
            str, tuple[z3.DatatypeSortRef, z3.FuncDeclRef, List[z3.FuncDeclRef]]
        ] = {}
        self._dsl_none_sort: z3.DatatypeSortRef | None = None
        self._dsl_none_value: z3.ExprRef | None = None
        # Store original AST nodes for functions/predicates to support callsite inlining
        self._func_ast_nodes: Dict[str, _ast.FunctionDef | _ast.PredicateDef] = {}
        # Default inlining fuel per function (Dafny-style unrolling). When fuel is 0, fallback to UF.
        self._default_fuel: int = 8
        # Stack of partial fuel environments; most recent frame overrides previous ones
        self._fuel_env_stack: List[Dict[str, int]] = []

    # ------------------------------------------------------------------
    # Floating-point helpers
    # ------------------------------------------------------------------

    def _fp_enabled(self) -> bool:
        return self._fp_sort is not None and self._fp_rounding is not None

    def _fp_const(self, value: float) -> z3.FPRef:
        assert self._fp_sort is not None
        return z3.FPVal(value, self._fp_sort, ctx=self._ctx)

    def _to_fp(self, expr: z3.ExprRef) -> z3.FPRef:
        if not self._fp_enabled():
            raise ValueError("Floating-point encoding is not enabled")
        assert self._fp_rounding is not None and self._fp_sort is not None
        if z3.is_fp(expr):
            return cast(z3.FPRef, expr)
        if z3.is_int(expr):
            real_expr = z3.ToReal(expr)
            return z3.fpToFP(self._fp_rounding, real_expr, self._fp_sort, ctx=self._ctx)
        if z3.is_real(expr):
            return z3.fpToFP(self._fp_rounding, expr, self._fp_sort, ctx=self._ctx)
        raise TypeError(
            f"Cannot convert expression of sort {expr.sort()} to floating-point"
        )

    def _handle_fp_binary_op(
        self, op: str, left: z3.ExprRef, right: z3.ExprRef
    ) -> z3.ExprRef:
        assert self._fp_rounding is not None
        left_fp = self._to_fp(left)
        right_fp = self._to_fp(right)

        if op == "+":
            return z3.fpAdd(self._fp_rounding, left_fp, right_fp, ctx=self._ctx)
        if op == "-":
            return z3.fpSub(self._fp_rounding, left_fp, right_fp, ctx=self._ctx)
        if op == "*":
            return z3.fpMul(self._fp_rounding, left_fp, right_fp, ctx=self._ctx)
        if op == "/":
            return z3.fpDiv(self._fp_rounding, left_fp, right_fp, ctx=self._ctx)
        if op == "==":
            return cast(
                z3.ExprRef,
                z3.fpEQ(left_fp, right_fp, ctx=self._ctx),
            )
        if op == "!=":
            return cast(
                z3.ExprRef,
                z3.Not(z3.fpEQ(left_fp, right_fp, ctx=self._ctx)),
            )
        if op == "<":
            return cast(
                z3.ExprRef,
                z3.fpLT(left_fp, right_fp, ctx=self._ctx),
            )
        if op == "<=":
            return cast(
                z3.ExprRef,
                z3.fpLEQ(left_fp, right_fp, ctx=self._ctx),
            )
        if op == ">":
            return cast(
                z3.ExprRef,
                z3.fpGT(left_fp, right_fp, ctx=self._ctx),
            )
        if op == ">=":
            return cast(
                z3.ExprRef,
                z3.fpGEQ(left_fp, right_fp, ctx=self._ctx),
            )
        if op in {"%", "^"}:
            raise NotImplementedError(
                f"Operator '{op}' is not supported for floating-point reals"
            )
        raise NotImplementedError(f"Floating-point operator '{op}' not implemented")

    # ------------------------------------------------------------------
    # Environment management
    # ------------------------------------------------------------------

    def _push_scope(self):
        """Push new scope for variable/function bindings."""
        self._env.append({})

    def _pop_scope(self):
        """Pop current scope."""
        return list(self._env.pop().values())

    def _push_local_constraints(self):
        """Push new local constraint context."""
        self._local_constraints.append([])

    def _pop_local_constraints(self) -> List[z3.BoolRef]:
        """Pop and return local constraints."""
        return self._local_constraints.pop()

    def _add_constraint(self, constraint: z3.BoolRef):
        """Add constraint to current context (local if in local context, otherwise global)."""
        if self._local_constraints:
            self._local_constraints[-1].append(constraint)
        else:
            self._constraints.append(constraint)

    def _bind(self, name: str, value: Union[z3.ExprRef, z3.FuncDeclRef]):
        """Bind name to value in current scope."""
        self._env[-1][name] = value

    def _lookup(
        self, name: str, ty: Optional[_ast.DSLType] = None
    ) -> Union[z3.ExprRef, z3.FuncDeclRef]:
        """Look up name in environment stack."""
        for scope in reversed(self._env):
            if name in scope:
                return scope[name]
        if ty is not None:
            return z3.FreshConst(self._type_to_sort(ty))
        raise NameError(f"Unbound variable or function: '{name}'")

    def _declare_const(self, name: str, sort: z3.SortRef) -> z3.ExprRef:
        """Declare a constant with given sort."""
        var = z3.Const(name, sort)
        self._bind(name, var)
        return var

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def to_z3(
        self, ast: _ast.Specification, entry_func: Optional[str] = None
    ) -> list[z3.ExprRef]:
        """Convert DSL AST to Z3 expressions."""
        self._env = [{}]
        self._constraints = []
        entry_func_decl = None
        others = []
        for decl in ast.declarations:
            if entry_func == decl.name:
                entry_func_decl = decl
            else:
                others.append(decl)
        if entry_func_decl is None:
            return [self.transform(ast)]
        dummy_spec = _ast.Specification(declarations=others)
        _ = self.transform(dummy_spec)
        body = self._compile_entry_func(entry_func_decl)
        return [body] + self._constraints

    # ------------------------------------------------------------------
    # Binary operator mappings
    # ------------------------------------------------------------------

    def _handle_binary_op(self, node: _ast.BinaryOp) -> z3.ExprRef:
        """Handle binary operations with proper operator mapping."""
        left = self.transform(node.left)
        right = self.transform(node.right)

        # Map DSL operators to Z3 equivalents
        op_map = {
            # Arithmetic
            "+": lambda a, b: a + b,
            "-": lambda a, b: a - b,
            "*": lambda a, b: a * b,
            "/": lambda a, b: a / b,
            "%": lambda a, b: a % b,
            "^": lambda a, b: a**b,
            # Comparisons
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
            # Boolean logic
            "∧": lambda a, b: z3.And(a, b),
            "∨": lambda a, b: z3.Or(a, b),
            "==>": lambda a, b: z3.Implies(a, b, ctx=self._ctx),
            "<==>": lambda a, b: a == b,
        }

        # Special-case equality/inequality for option types: compare presence, then values
        if node.op in {"==", "!="}:
            lty = node.left.get_type()
            rty = node.right.get_type()
            if isinstance(lty, _ast.OptionType) and isinstance(rty, _ast.OptionType):
                is_some_l = self._option_is_some(left, lty)
                is_some_r = self._option_is_some(right, rty)
                val_l = self._option_val(left, lty)
                val_r = self._option_val(right, rty)
                eq = z3.And(
                    is_some_l == is_some_r, z3.Implies(is_some_l, val_l == val_r)
                )
                if node.op == "==":
                    return cast(z3.ExprRef, eq)
                return cast(z3.ExprRef, z3.Not(eq))

        if (
            self._real_encoding == RealEncodingMode.FLOATING_POINT
            and self._fp_enabled()
            and (z3.is_fp(left) or z3.is_fp(right))
        ):
            return self._handle_fp_binary_op(node.op, left, right)

        if node.op in op_map:
            try:
                result = op_map[node.op](left, right)
            except z3.Z3Exception as e:
                e.value += f"left_sort: {left.sort()}, right_sort: {right.sort()}, op: {node.op}"
                raise e
            # Handle int/real arithmetic result type
            if node.op in ["+", "-", "*", "/", "%", "^"]:
                if z3.is_int(left) and z3.is_int(right) and not z3.is_int(result):
                    return z3.ToInt(result)
            return result
        # Handle 'in' separately to distinguish between set, multiset, and sequence
        if node.op == "in":
            # Decide by DSL type instead of runtime Z3 sort to avoid ambiguity
            assert isinstance(node.right, _ast.Expr)
            right_ty = node.right.get_type()
            # list (including string)
            if isinstance(right_ty, _ast.ListType):
                return z3.Contains(right, z3.Unit(left))
            # set
            if isinstance(right_ty, _ast.SetType):
                members = self._sizedset_members(right, right_ty)
                return z3.IsMember(left, members)
            # multiset: encoded as Array elem -> Int count
            if isinstance(right_ty, _ast.MultisetType):
                return z3.Select(right, left) > z3.IntVal(0, self._ctx)
            # Fallback to set semantics
            return z3.IsMember(left, right)

        raise NotImplementedError(f"Binary operator {node.op} not implemented")

    # ------------------------------------------------------------------
    # Visitor methods for literals and basic expressions
    # ------------------------------------------------------------------

    def visit_NumberLiteral(self, node: _ast.NumberLiteral) -> z3.ExprRef:
        """Convert number literal to Z3 expression."""
        node_type = node.get_type()
        if isinstance(node_type, _ast.Real):
            if self._real_encoding == RealEncodingMode.FLOATING_POINT:
                numeric = float(node.value)
                return self._fp_const(numeric)
            if isinstance(node.value, float):
                if math.isnan(node.value) or math.isinf(node.value):
                    raise ValueError(
                        "NaN and Infinity literals require floating-point real encoding"
                    )
                return z3.RealVal(str(node.value), self._ctx)
            return z3.RealVal(str(node.value), self._ctx)

        if isinstance(node.value, float):
            return z3.RealVal(str(node.value), self._ctx)
        return z3.IntVal(int(node.value), self._ctx)

    def visit_BoolLiteral(self, node: _ast.BoolLiteral) -> z3.ExprRef:
        """Convert boolean literal to Z3 expression."""
        return z3.BoolVal(node.value, self._ctx)

    def visit_StringLiteral(self, node: _ast.StringLiteral) -> z3.ExprRef:
        """Convert string literal to Z3 expression."""
        return z3.StringVal(node.value, self._ctx)

    def visit_CharLiteral(self, node: _ast.CharLiteral) -> z3.ExprRef:
        """Convert char literal to Z3 expression."""
        return z3.CharVal(node.value, self._ctx)

    def visit_NoneLiteral(self, node: _ast.NoneLiteral) -> z3.ExprRef:
        """Encode None for either nonetype or option[T]."""
        ty = node.get_type()
        if isinstance(ty, _ast.DSLNoneType):
            _, none_value = self._get_dsl_none_info()
            return none_value
        if isinstance(ty, _ast.OptionType):
            _, ctor, accessors = self._get_option_info(ty)
            _ = accessors
            val_sort = self._type_to_sort(ty.elem)
            return ctor(z3.BoolVal(False, self._ctx), z3.FreshConst(val_sort))
        raise TypeError(f"none literal must have type nonetype or option[T], got {ty}")

    def visit_SomeExpr(self, node: _ast.SomeExpr) -> z3.ExprRef:
        """Encode some(value) as (is_some=True, val=value)."""
        ty = node.get_type()
        assert isinstance(ty, _ast.OptionType)
        _, ctor, accessors = self._get_option_info(ty)
        _ = accessors
        value_expr = self.transform(node.value)
        return ctor(z3.BoolVal(True, self._ctx), value_expr)

    def visit_Identifier(self, node: _ast.Identifier) -> z3.ExprRef | z3.FuncDeclRef:
        """Look up identifier in environment."""
        return self._lookup(node.name, node.get_type())

    def visit_UnaryOp(self, node: _ast.UnaryOp) -> z3.ExprRef:
        """Handle unary operations."""
        operand = self.transform(node.operand)
        assert isinstance(operand, z3.ExprRef)

        if node.op == "¬":
            assert z3.is_bool(operand)
            return ~operand  # type: ignore[operator]
        elif node.op == "-":
            if self._real_encoding == RealEncodingMode.FLOATING_POINT and z3.is_fp(
                operand
            ):
                return z3.fpNeg(cast(z3.FPRef, operand), ctx=self._ctx)
            assert z3.is_arith(operand)
            return -operand  # type: ignore[operator]
        elif node.op == "+":
            assert z3.is_arith(operand)
            return operand
        else:
            raise NotImplementedError(f"Unary operator {node.op} not implemented")

    def visit_BinaryOp(self, node: _ast.BinaryOp) -> z3.ExprRef:
        """Handle binary operations."""
        return self._handle_binary_op(node)

    def visit_Comparisons(self, node: _ast.Comparisons) -> z3.ExprRef:
        """Handle chained comparisons (e.g., a < b < c)."""
        if not node.comparisons:
            return z3.BoolVal(True, self._ctx)

        results = []
        for comp in node.comparisons:
            results.append(self.visit_BinaryOp(comp))

        result = z3.And(*results) if len(results) > 1 else results[0]
        assert isinstance(result, z3.ExprRef)
        return result

    def visit_IfExpr(self, node: _ast.IfExpr) -> z3.ExprRef:
        """Handle if-then-else expressions."""
        cond = self.transform(node.condition)
        then_expr = self.transform(node.then_branch)

        if node.else_branch:
            else_expr = self.transform(node.else_branch)
        else:
            else_expr = z3.BoolVal(True, self._ctx)  # Default else for predicates

        result = z3.If(cond, then_expr, else_expr)
        assert isinstance(result, z3.ExprRef)
        return result

    # ------------------------------------------------------------------
    # Collections and data structures
    # ------------------------------------------------------------------
    def visit_ExplicitList(self, node: _ast.ExplicitList) -> z3.ExprRef:
        """Handle explicit list literals."""
        if not node.elements:
            # For empty lists, try to infer the element type using context
            assert node.ty is not None
            list_sort = self._type_to_sort(node.get_type())
            return z3.Empty(list_sort)

        elements = [self.transform(elem) for elem in node.elements]

        list_ty = node.get_type()
        elem_target_sort: z3.SortRef | None = None
        if isinstance(list_ty, _ast.ListType):
            elem_target_sort = self._type_to_sort(list_ty.elem)
        if elem_target_sort is not None:
            elements = [
                self._coerce_expr_to_sort(elem_expr, elem_target_sort)
                for elem_expr in elements
            ]

        if len(elements) == 1:
            return z3.Unit(elements[0])

        # Build sequence by concatenating units
        seq = z3.Unit(elements[0])
        for elem in elements[1:]:
            seq = z3.Concat(seq, z3.Unit(elem))
        return seq

    def visit_ExplicitSet(self, node: _ast.ExplicitSet) -> z3.ExprRef:
        """Handle explicit set literals with sized-set encoding."""
        target_set_ty: Optional[_ast.SetType] = None
        if node.ty is not None and isinstance(node.get_type(), _ast.SetType):
            target_set_ty = node.get_type()  # type: ignore[assignment]

        # Empty set literal requires a concrete set type
        if not node.elements:
            if target_set_ty is None:
                raise ValueError("Empty set literal requires a concrete set type")
            elem_sort = self._type_to_sort(target_set_ty.elem)
            _, ctor, _ = self._get_sizedset_info(target_set_ty)
            return ctor(z3.EmptySet(elem_sort), z3.IntVal(0, self._ctx))

        # Transform elements first and infer element type from Z3 sort if needed
        elements = [self.transform(elem) for elem in node.elements]
        if target_set_ty is None:
            first_sort = elements[0].sort()
            inferred_elem_ty = self._dsl_type_from_sort(first_sort)
            target_set_ty = _ast.SetType(inferred_elem_ty)

        elem_sort = self._type_to_sort(target_set_ty.elem)
        elements = [self._coerce_expr_to_sort(elem, elem_sort) for elem in elements]
        members = z3.EmptySet(elem_sort)
        size_expr: z3.ArithRef = z3.IntVal(0, self._ctx)
        for elem in elements:
            increment = z3.If(
                z3.IsMember(elem, members),
                z3.IntVal(0, self._ctx),
                z3.IntVal(1, self._ctx),
            )
            size_expr = cast(z3.ArithRef, size_expr + cast(z3.ArithRef, increment))
            members = z3.SetAdd(members, elem)
        _, ctor, _ = self._get_sizedset_info(target_set_ty)
        return ctor(members, size_expr)

    def visit_ExplicitMultiset(self, node: _ast.ExplicitMultiset) -> z3.ExprRef:
        """Handle explicit multiset literals using Z3 Arrays with element counts."""
        target_multiset_ty: Optional[_ast.MultisetType] = None
        if node.ty is not None and isinstance(node.get_type(), _ast.MultisetType):
            target_multiset_ty = node.get_type()  # type: ignore[assignment]

        # Empty multiset literal requires a concrete multiset type
        if not node.elements:
            if target_multiset_ty is None:
                raise ValueError(
                    "Empty multiset literal requires a concrete multiset type"
                )
            elem_sort = self._type_to_sort(target_multiset_ty.elem)
            zero = z3.IntVal(0, self._ctx)
            return z3.K(elem_sort, zero)

        # Transform elements first and infer element type from Z3 sort if needed
        elements = [self.transform(elem) for elem in node.elements]
        if target_multiset_ty is None:
            first_sort = elements[0].sort()
            inferred_elem_ty = self._dsl_type_from_sort(first_sort)
            target_multiset_ty = _ast.MultisetType(inferred_elem_ty)

        elem_sort = self._type_to_sort(target_multiset_ty.elem)
        zero = z3.IntVal(0, self._ctx)
        multiset = z3.K(elem_sort, zero)

        # Count occurrences of each element
        elements = [self._coerce_expr_to_sort(elem, elem_sort) for elem in elements]
        for elem in elements:
            multiset = z3.Store(
                multiset,
                elem,
                z3.Select(multiset, elem) + z3.IntVal(1, self._ctx),
            )

        return multiset

    def visit_ExplicitMap(self, node: _ast.ExplicitMap) -> z3.ExprRef:
        """Handle explicit map literals using Z3 Arrays with default values.

        We initialize a default array with an unconstrained fresh default element,
        then store each key->value binding in sequence (last store wins).
        """
        target_map_ty: Optional[_ast.MapType] = None
        if node.ty is not None and isinstance(node.get_type(), _ast.MapType):
            target_map_ty = node.get_type()  # type: ignore[assignment]

        # If empty literal, we require a concrete map type (from type checker)
        if len(node.keys) == 0:
            if target_map_ty is None:
                raise ValueError("Empty map literal requires a concrete map type")
            key_sort = self._type_to_sort(target_map_ty.key)
            val_sort = self._type_to_sort(target_map_ty.value)
            default_val = z3.FreshConst(val_sort)
            return z3.K(key_sort, default_val)

        # Transform first pair to infer sorts if needed
        first_k = self.transform(node.keys[0])
        first_v = self.transform(node.values[0])
        if target_map_ty is None:
            # Infer from Z3 sorts
            key_sort = first_k.sort()
            val_sort = first_v.sort()
        else:
            key_sort = self._type_to_sort(target_map_ty.key)
            val_sort = self._type_to_sort(target_map_ty.value)

        first_k = self._coerce_expr_to_sort(first_k, key_sort)
        first_v = self._coerce_expr_to_sort(first_v, val_sort)
        default_val = z3.FreshConst(val_sort)
        arr = z3.K(key_sort, default_val)

        # Store all pairs
        keys = [first_k] + [
            self._coerce_expr_to_sort(self.transform(k), key_sort)
            for k in node.keys[1:]
        ]
        vals = [first_v] + [
            self._coerce_expr_to_sort(self.transform(v), val_sort)
            for v in node.values[1:]
        ]
        for k, v in zip(keys, vals):
            arr = z3.Store(arr, k, v)
        return arr

    def visit_ExplicitRecord(self, node: _ast.ExplicitRecord) -> z3.ExprRef:
        """Handle explicit record literals using Z3 datatypes."""
        # Get the record type from the node
        record_ty = node.get_type()
        if not isinstance(record_ty, _ast.RecordType):
            raise ValueError(f"Expected RecordType, got {type(record_ty)}")

        # Generate the datatype if not already done
        self._record_datatype_generator(record_ty)

        # Use normalized key for lookup
        sorted_fields = sorted(record_ty.fields.items())
        normalized_key = f"record[{', '.join(f'{name}: {field_ty}' for name, field_ty in sorted_fields)}]"
        _, constructor, _ = self._record_datatypes[normalized_key]

        # Transform field values in the correct order (sorted by field name for consistency)
        field_values = []
        for field_name in sorted(record_ty.fields.keys()):
            if field_name in node.fields:
                field_ty = record_ty.fields[field_name]
                field_sort = self._type_to_sort(field_ty)
                field_value = self.transform(node.fields[field_name])
                field_value = self._coerce_expr_to_sort(field_value, field_sort)
                field_values.append(field_value)
            else:
                raise ValueError(f"Record literal missing field '{field_name}'")

        # Create the record using the constructor
        return constructor(*field_values)

    def visit_ListAccess(self, node: _ast.ListAccess) -> z3.ExprRef:
        """Handle list/sequence access."""
        seq = self.transform(node.seq)

        # Handle multiple indices for nested access
        idx = self.transform(node.index)
        if isinstance(seq, (z3.SeqRef, z3.ArrayRef)):
            result = seq[idx]
        elif isinstance(seq, z3.DatatypeRef):
            seq_ty = node.seq.get_type()
            # Normalize key for lookup (records use sorted-field key)
            key_for_lookup = None
            if isinstance(seq_ty, _ast.RecordType):
                sorted_fields = sorted(seq_ty.fields.items())
                key_for_lookup = f"record[{', '.join(f'{name}: {field_ty}' for name, field_ty in sorted_fields)}]"
                if key_for_lookup not in self._tuple_datatypes:
                    self._record_datatype_generator(seq_ty)
            elif isinstance(seq_ty, _ast.TupleType):
                key_for_lookup = str(seq_ty)
                if key_for_lookup not in self._tuple_datatypes:
                    self._tuple_datatype_generator(seq_ty)
            else:
                raise ValueError(f"Unexpected type for datatype access: {seq_ty}")

            if isinstance(seq_ty, _ast.RecordType):
                _, _, accessors_map = self._record_datatypes[key_for_lookup]
            else:
                _, _, accessors = self._tuple_datatypes[key_for_lookup]

            if isinstance(seq_ty, _ast.RecordType) and isinstance(
                node.index, _ast.StringLiteral
            ):
                # For records, map field name to index
                field_name = node.index.value
                if field_name not in seq_ty.fields:
                    raise ValueError(f"Record has no field '{field_name}'")
                result = accessors_map[field_name](seq)
            else:
                # For tuples, use integer index
                idx_const = z3.simplify(idx).py_value()
                assert isinstance(idx_const, int)
                result = accessors[idx_const](seq)
        else:
            raise ValueError(f"Invalid type: {type(seq)}")
        return result

    def visit_FieldAccess(self, node: _ast.FieldAccess) -> z3.ExprRef:
        """Handle record field access with dot notation."""
        record = self.transform(node.record)
        record_ty = node.record.get_type()

        if not isinstance(record_ty, _ast.RecordType):
            raise ValueError(f"Field access requires a record type, got {record_ty}")
        # Normalize key for record datatypes (sorted field order)
        sorted_fields = sorted(record_ty.fields.items())
        normalized_key = f"record[{', '.join(f'{name}: {field_ty}' for name, field_ty in sorted_fields)}]"
        if normalized_key not in self._record_datatypes:
            self._record_datatype_generator(record_ty)

        _, _, accessors_map = self._record_datatypes[normalized_key]

        field_name = node.field_name
        if field_name not in record_ty.fields:
            raise ValueError(f"Record has no field '{field_name}'")

        return accessors_map[field_name](record)

    def _visit_Range(self, node: _ast.RangeList | _ast.RangeSet) -> z3.ExprRef:
        """Handle range literals."""
        # Expand numeric literal ranges eagerly
        if isinstance(node.start, _ast.NumberLiteral) and isinstance(
            node.end, _ast.NumberLiteral
        ):
            lower = int(node.start.value)
            upper = int(node.end.value)
            elements = [_ast.NumberLiteral(value=i) for i in range(lower, upper + 1)]
            if isinstance(node, _ast.RangeList):
                return self.transform(_ast.ExplicitList(elements=elements, ty=node.ty))
            else:
                return self.transform(_ast.ExplicitSet(elements=elements, ty=node.ty))

        # Expand char literal ranges eagerly
        if isinstance(node.start, _ast.CharLiteral) and isinstance(
            node.end, _ast.CharLiteral
        ):
            s = node.start.value
            e = node.end.value
            if len(s) != 1 or len(e) != 1:
                # Defensive: fallback to uninterpreted constant
                pass
            else:
                lower = ord(s)
                upper = ord(e)
                step_range = range(lower, upper + 1) if lower <= upper else []
                elements = [_ast.CharLiteral(value=chr(i)) for i in step_range]
                if isinstance(node, _ast.RangeList):
                    return self.transform(
                        _ast.ExplicitList(elements=elements, ty=node.ty)
                    )
                else:
                    return self.transform(
                        _ast.ExplicitSet(elements=elements, ty=node.ty)
                    )
        start = self.transform(node.start)
        end = None
        if node.end:
            end = self.transform(node.end)

        assert node.ty is not None
        sort = self._type_to_sort(node.get_type())

        lst_const = z3.FreshConst(sort)
        self._bind(str(lst_const), lst_const)
        # Only add numeric iterator constraints when bounds are integers
        if z3.is_int(start) and (end is None or z3.is_int(end)):
            iterator = z3.FreshInt(ctx=self._ctx)

            lower_bound = iterator >= start
            upper_bound = (
                iterator < end if end is not None else z3.BoolVal(True, self._ctx)
            )

            if isinstance(node, _ast.RangeList):
                assert isinstance(lst_const, z3.SeqRef)
                constraint_body = lst_const[iterator - start] == iterator
            elif isinstance(node, _ast.RangeSet):
                expr_ty = node.get_type()
                assert isinstance(expr_ty, _ast.SetType)
                members = self._sizedset_members(lst_const, expr_ty)
                constraint_body = z3.IsMember(iterator, members)
            else:
                raise ValueError(f"Invalid type: {type(lst_const)}")

            self._add_constraint(
                z3.ForAll(
                    [iterator],
                    z3.Implies(
                        (lower_bound & upper_bound),
                        constraint_body,
                        ctx=self._ctx,
                    ),
                )
            )

            if end is not None and isinstance(node, _ast.RangeList):
                self._add_constraint(z3.Length(lst_const) == end - start)  # type: ignore[operator]

        return lst_const

    def visit_RangeList(self, node: _ast.RangeList) -> z3.ExprRef:
        """Handle range literals."""
        return self._visit_Range(node)

    def visit_RangeSet(self, node: _ast.RangeSet) -> z3.ExprRef:
        """Handle range set literals."""
        return self._visit_Range(node)

    def _visit_Comprehension(
        self, node: _ast.ListComprehension | _ast.SetComprehension
    ) -> z3.ExprRef:
        """Handle list and set comprehensions."""
        raise NotImplementedError("Comprehensions are not supported yet")

    def visit_ListComprehension(self, node: _ast.ListComprehension) -> z3.ExprRef:
        """Handle list comprehensions."""
        return self._visit_Comprehension(node)

    def visit_SetComprehension(self, node: _ast.SetComprehension) -> z3.ExprRef:
        """Handle set comprehensions."""
        return self._visit_Comprehension(node)

    def visit_Generator(self, node: _ast.Generator) -> z3.ExprRef:
        """Handle generator expressions in comprehensions."""
        # Transform the collection/domain expression
        domain = self.transform(node.expr)

        # Create a Z3 variable for the iteration variable
        assert node.var.ty is not None
        var_sort = self._type_to_sort(node.var.get_type())
        z3_var = z3.Const(node.var.name, var_sort)
        self._bind(node.var.name, z3_var)

        # Add constraint that the variable is in the domain
        if z3.is_seq(domain):
            # For sequences, constrain the variable to be an element at some index
            idx = z3.FreshInt(ctx=self._ctx)
            domain_constraint = z3.And(
                0 <= idx,
                idx < z3.Length(domain),
                z3_var == domain[idx],  # type: ignore[operator]
            )
            exists_constraint = z3.Exists([idx], domain_constraint)
            self._add_constraint(exists_constraint)
        else:
            # For sets (SizedSet), constrain membership via members field when domain is a sized set
            # We rely on type info of node.expr to distinguish
            expr_node = cast(_ast.Expr, node.expr)
            expr_ty = expr_node.get_type()
            if isinstance(expr_ty, _ast.SetType):
                members = self._sizedset_members(domain, expr_ty)
                self._add_constraint(z3.IsMember(z3_var, members))
            else:
                # Fallback: no constraint for unknown domain types
                pass

        return z3_var

    def visit_TupleExpr(self, node: _ast.TupleExpr) -> z3.ExprRef:
        """Handle tuple expressions."""
        assert node.ty is not None
        tuple_ty = cast(_ast.TupleType, node.get_type())
        self._type_to_sort(
            tuple_ty
        )  # To guarantee that tuple type is registered in _tuple_datatypes
        _, constructor, _ = self._tuple_datatypes[str(tuple_ty)]
        elem_sorts = [self._type_to_sort(elem_ty) for elem_ty in tuple_ty.elem_types]
        exprs = [
            self._coerce_expr_to_sort(self.transform(elem), sort)
            for elem, sort in zip(node.elements, elem_sorts)
        ]
        return constructor(*exprs)

    # ------------------------------------------------------------------
    # Function calls and higher-order operations
    # ------------------------------------------------------------------

    def visit_FuncCall(self, node: _ast.FuncCall) -> z3.ExprRef:
        """Handle function calls including built-ins and lambda calls."""

        # Handle direct lambda calls first
        if isinstance(node.func, _ast.LambdaExpr):
            lambda_func = self.transform(node.func)
            args: list[z3.ExprRef] = [self.transform(arg) for arg in node.args]
            # For Z3 Lambda objects, we need to use substitute_vars to apply them
            if isinstance(lambda_func, z3.QuantifierRef) and lambda_func.is_lambda():
                # Check argument count
                if len(args) != lambda_func.num_vars():
                    raise ValueError(
                        f"Lambda expects {lambda_func.num_vars()} arguments, got {len(args)}"
                    )

                # Apply substitution using substitute_vars (args in reverse order for de Bruijn indices)
                return z3.substitute_vars(lambda_func.body(), *reversed(args))
            else:
                raise NotImplementedError(
                    f"Unsupported lambda function type: {type(lambda_func)}"
                )

        # Get function name if it's an identifier
        func_name = None
        if isinstance(node.func, _ast.Identifier):
            func_name = node.func.name

        # Handle built-in functions (only for identifiers)
        if func_name == "len":
            if len(node.args) != 1:
                raise ValueError("len() takes exactly one argument")
            arg_ast = node.args[0]
            arg_ty = arg_ast.get_type()
            arg_expr = self.transform(arg_ast)
            return z3.Length(arg_expr)

        if func_name == "cardinality":
            if len(node.args) != 1:
                raise ValueError("cardinality() takes exactly one argument")
            arg_ast = node.args[0]
            arg_ty = arg_ast.get_type()
            arg_expr = self.transform(arg_ast)
            assert isinstance(arg_ty, _ast.SetType)
            return self._sizedset_size(arg_expr, arg_ty)

        # Handle math functions
        if func_name in {"abs", "abs_real"}:
            if len(node.args) != 1:
                raise ValueError(f"{func_name}() takes exactly one argument")
            val = self.transform(node.args[0])
            assert isinstance(val, z3.ExprRef)
            if self._real_encoding == RealEncodingMode.FLOATING_POINT and z3.is_fp(val):
                return z3.fpAbs(cast(z3.FPRef, val), ctx=self._ctx)
            return z3.Abs(val)  # type: ignore[return-value]

        if func_name in {"is_infinite", "is_nan"}:
            if len(node.args) != 1:
                raise ValueError(f"{func_name}() takes exactly one argument")
            arg_expr = self.transform(node.args[0])
            if (
                self._real_encoding == RealEncodingMode.FLOATING_POINT
                and self._fp_enabled()
            ):
                fp_expr = self._to_fp(arg_expr)
                if func_name == "is_infinite":
                    return cast(
                        z3.ExprRef,
                        z3.fpIsInf(fp_expr, ctx=self._ctx),
                    )
                return cast(
                    z3.ExprRef,
                    z3.fpIsNaN(fp_expr, ctx=self._ctx),
                )
            return cast(z3.ExprRef, z3.BoolVal(False, self._ctx))

        # Handle map/record functions
        if func_name in {"keys", "values", "items", "has_key"}:
            return self._handle_map_record_functions(node, func_name)

        # Handle list higher-order functions
        if func_name in {"map", "filter", "fold", "all", "any", "map_i", "fold_i"}:
            return self._handle_higher_order_func(func_name, node.args)

        # Option helpers
        if func_name in {"is_some", "is_none", "unwrap"}:
            if len(node.args) != 1:
                raise ValueError(f"{func_name}() takes exactly one argument")
            arg_ast = node.args[0]
            arg_ty = arg_ast.get_type()
            if not isinstance(arg_ty, _ast.OptionType):
                raise ValueError(f"{func_name}() expects option[T], got {arg_ty}")
            arg_expr = self.transform(arg_ast)
            is_some_expr = self._option_is_some(arg_expr, arg_ty)
            if func_name == "is_some":
                return is_some_expr
            if func_name == "is_none":
                return cast(z3.ExprRef, z3.Not(is_some_expr))
            # unwrap
            return self._option_val(arg_expr, arg_ty)

        # some constructor: T -> option[T]
        if func_name == "some":
            if len(node.args) != 1:
                raise ValueError("some() takes exactly one argument")
            arg_ast = node.args[0]
            arg_ty = arg_ast.get_type()
            result_ty = node.get_type()
            if not isinstance(result_ty, _ast.OptionType):
                raise ValueError(f"some() result must be option[T], got {result_ty}")
            arg_expr = self.transform(arg_ast)
            _, ctor, _ = self._get_option_info(result_ty)
            return ctor(z3.BoolVal(True, self._ctx), arg_expr)

        # Handle aggregation functions
        if func_name in {"sum", "product", "max", "min", "average", "mean"}:
            return self._handle_aggregation_func(func_name, node.args)

        # Handle set operations
        if func_name in {
            "set_add",
            "set_del",
            "set_union",
            "set_intersect",
            "set_difference",
            "set_complement",
            "set_is_subset",
            "set_is_member",
            "set_is_empty",
        }:
            return self._handle_set_operation(func_name, node.args)

        # Handle string operations
        if func_name in {
            "concat",
            "contains",
            "substr",
            "indexof",
            "replace",
            "prefixof",
            "suffixof",
            "uppercase",
            "lowercase",
            "int2str",
            "str2int",
        }:
            return self._handle_string_operation(func_name, node.args)

        # Handling type conversions
        if func_name in {
            "int2real",
            "real2int",
        }:
            return self._handle_type_conversion(func_name, node.args)

        # Handle multiset conversions
        if func_name in {"list2multiset"}:
            if len(node.args) != 1:
                raise ValueError("list2multiset() takes exactly one argument")
            seq = self.transform(node.args[0])
            assert isinstance(seq, (z3.SeqRef,))
            # Represent multiset as map elem -> count
            elem_sort = seq.sort().basis()
            arr_sort = z3.ArraySort(elem_sort, z3.IntSort(self._ctx))
            zero = z3.IntVal(0, self._ctx)
            init = z3.K(elem_sort, zero)
            acc = z3.Const("acc", arr_sort)
            e = z3.Const("e", elem_sort)
            fold = z3.Lambda([acc, e], z3.Store(acc, e, z3.Select(acc, e) + 1))  # type: ignore[operator]
            return z3.SeqFoldLeft(fold, init, seq)

        # Handle list2set conversion only
        if func_name == "list2set":
            if len(node.args) != 1:
                raise ValueError("list2set() takes exactly one argument")
            seq_ast = node.args[0]
            seq = self.transform(seq_ast)
            assert isinstance(seq, z3.SeqRef)
            # Result type depends on list element type
            lt = seq_ast.get_type()
            if not isinstance(lt, _ast.ListType):
                raise ValueError("list2set() argument must be a list")
            set_ty = _ast.SetType(lt.elem)
            elem_sort = seq.sort().basis()
            dt_sort, ctor, accessors = self._get_sizedset_info(set_ty)
            members_acc = accessors[0]
            size_acc = accessors[1]
            acc = z3.Const("acc", dt_sort)
            e = z3.Const("e", elem_sort)
            old_members = members_acc(acc)
            old_size = size_acc(acc)
            new_members = z3.SetAdd(old_members, e)
            incr = z3.If(
                z3.IsMember(e, old_members),
                z3.IntVal(0, self._ctx),
                z3.IntVal(1, self._ctx),
            )
            new_size = old_size + incr  # type: ignore[operator]
            fold = z3.Lambda([acc, e], ctor(new_members, new_size))
            init = ctor(z3.EmptySet(elem_sort), z3.IntVal(0, self._ctx))
            return z3.SeqFoldLeft(fold, init, seq)

        # Handle user-defined functions (only for identifiers)
        if func_name:
            func = self._lookup(func_name, node.get_type())
            args = [self.transform(arg) for arg in node.args]
            ast_def = self._func_ast_nodes.get(func_name)

            # Fallback: if no definition exists, or both implicit and explicit
            # definitions are missing, treat it as an uninterpreted application.
            if ast_def is None:
                if isinstance(func, z3.FuncDeclRef):
                    return func(*args) if len(args) > 0 else func  # type: ignore[return-value]
                if isinstance(func, z3.ExprRef):
                    return func
                raise ValueError(
                    f"Invalid function reference for '{func_name}': {type(func)}"
                )

            # FunctionDef with neither body nor ensures: leave uninterpreted
            if (
                isinstance(ast_def, _ast.FunctionDef)
                and ast_def.body is None
                and len(ast_def.ensures) == 0
                and len(ast_def.requires) == 0
            ):
                if isinstance(func, z3.FuncDeclRef):
                    return func(*args) if len(args) > 0 else func  # type: ignore[return-value]
                if isinstance(func, z3.ExprRef):
                    return func
                raise ValueError(
                    f"Invalid function reference for '{func_name}': {type(func)}"
                )

            # Try callsite inlining with fuel; fallback to UF call when fuel is 0
            return self._evaluate_function_call(func_name, func, ast_def, args)

        raise NotImplementedError(f"Function call not supported: {func_name}")

    def _handle_higher_order_func(
        self, func_name: str, args: Sequence[_ast.ASTNode]
    ) -> z3.ExprRef:
        """Handle higher-order list functions."""
        if func_name == "any":
            if len(args) != 2:
                raise ValueError("any() takes exactly two arguments")
            z3_func = self.transform(args[0])
            seq = self.transform(args[1])
            assert isinstance(seq, z3.SeqRef)
            assert isinstance(z3_func, (z3.FuncDeclRef, z3.ArrayRef, z3.QuantifierRef))
            idx = z3.FreshInt(ctx=self._ctx)
            f_call = (
                z3_func(seq[idx])
                if isinstance(z3_func, z3.FuncDeclRef)
                else z3_func[seq[idx]]
            )
            return z3.Exists(
                idx,
                z3.And(
                    0 <= idx,
                    idx < z3.Length(seq),
                    f_call,
                ),
            )

        if func_name == "all":
            if len(args) != 2:
                raise ValueError("all() takes exactly two arguments")
            z3_func = self.transform(args[0])
            seq = self.transform(args[1])
            assert isinstance(seq, z3.SeqRef)
            assert isinstance(z3_func, (z3.FuncDeclRef, z3.ArrayRef))
            idx = z3.FreshInt(ctx=self._ctx)
            f_call = (
                z3_func(seq[idx])
                if isinstance(z3_func, z3.FuncDeclRef)
                else z3_func[seq[idx]]
            )
            return z3.ForAll(
                idx,
                z3.Implies(z3.And(0 <= idx, idx < z3.Length(seq)), f_call),
            )

        if func_name == "map":
            if len(args) != 2:
                raise ValueError("map() takes exactly two arguments")
            z3_func = self.transform(args[0])
            seq = self.transform(args[1])
            return z3.SeqMap(z3_func, seq)

        if func_name == "map_i":
            if len(args) != 2:
                raise ValueError("map_i() takes exactly two arguments")
            z3_func = self.transform(args[0])
            seq = self.transform(args[1])
            return z3.SeqMapI(z3_func, z3.IntVal(0, self._ctx), seq)

        if func_name == "filter":
            if len(args) != 2:
                raise ValueError("filter() takes exactly two arguments")
            z3_func = self.transform(args[0])
            seq = self.transform(args[1])
            acc = z3.Empty(seq.sort())
            elem = z3.FreshConst(seq.sort().basis())  # type: ignore[attr-defined]
            fold_func = z3.Lambda(
                [acc, elem],
                z3.If(z3_func[elem], z3.Concat(acc, z3.Unit(elem)), acc),  # type: ignore[operator]
            )
            new_seq = z3.SeqFoldLeft(
                fold_func,
                z3.Empty(seq.sort()),
                seq,
            )
            return new_seq

        if func_name == "fold":
            if len(args) != 3:
                raise ValueError("fold() takes exactly three arguments")
            z3_func = self.transform(args[0])
            acc = self.transform(args[1])
            seq = self.transform(args[2])
            return z3.SeqFoldLeft(z3_func, acc, seq)

        if func_name == "fold_i":
            if len(args) != 3:
                raise ValueError("fold_i() takes exactly three arguments")
            z3_func = self.transform(args[0])
            acc = self.transform(args[1])
            collection = self.transform(args[2])
            return z3.SeqFoldLeftI(z3_func, z3.IntVal(0, self._ctx), acc, collection)

        # Add other higher-order functions as needed
        raise ValueError(f"Higher-order function {func_name} not implemented")

    def _handle_aggregation_func(
        self, func_name: str, args: Sequence[_ast.ASTNode]
    ) -> z3.ExprRef:
        """Handle aggregation functions on collections."""
        if len(args) != 1:
            raise ValueError(f"{func_name}() takes exactly one argument")

        seq = self.transform(args[0])

        if func_name == "sum":
            # Use fold to implement sum
            elem_var = z3.Int("elem", ctx=self._ctx)
            acc_var = z3.Int("acc", ctx=self._ctx)
            fold_func = z3.Lambda([elem_var, acc_var], acc_var + elem_var)
            return z3.SeqFoldLeft(fold_func, z3.IntVal(0, self._ctx), seq)

        elif func_name == "product":
            elem_var = z3.Int("elem", ctx=self._ctx)
            acc_var = z3.Int("acc", ctx=self._ctx)
            fold_func = z3.Lambda([elem_var, acc_var], acc_var * elem_var)
            return z3.SeqFoldLeft(fold_func, z3.IntVal(1, self._ctx), seq)

        elif func_name in {"average", "mean"}:
            # Calculate sum and divide by length
            elem_var = z3.Int("elem", ctx=self._ctx)
            acc_var = z3.Int("acc", ctx=self._ctx)
            fold_func = z3.Lambda([elem_var, acc_var], acc_var + elem_var)
            total = z3.SeqFoldLeft(fold_func, z3.IntVal(0, self._ctx), seq)
            length = z3.Length(seq)
            assert z3.is_arith(total)
            assert z3.is_arith(length)
            denom = z3.If(length == 0, z3.IntVal(1, self._ctx), length)
            if (
                self._real_encoding == RealEncodingMode.FLOATING_POINT
                and self._fp_enabled()
            ):
                total_fp = self._to_fp(cast(z3.ExprRef, total))
                denom_fp = self._to_fp(cast(z3.ExprRef, denom))
                assert self._fp_rounding is not None
                return z3.fpDiv(self._fp_rounding, total_fp, denom_fp, ctx=self._ctx)
            return z3.ToReal(total) / z3.ToReal(denom)  # type: ignore[operator]

        # Add max, min implementations
        elif func_name == "max":
            assert isinstance(seq, z3.SeqRef)
            x, y = z3.Ints("x y", ctx=self._ctx)
            comparator = z3.Lambda(
                [x, y],
                z3.If(x < y, y, x),
            )
            return z3.SeqFoldLeft(comparator, seq[0], seq)
        elif func_name == "min":
            assert isinstance(seq, z3.SeqRef)
            x, y = z3.Ints("x y", ctx=self._ctx)
            comparator = z3.Lambda(
                [x, y],
                z3.If(x < y, x, y),
            )
            return z3.SeqFoldLeft(comparator, seq[0], seq)
        else:
            raise NotImplementedError(
                f"Aggregation function {func_name} not implemented"
            )

    def _handle_set_operation(
        self, func_name: str, args: Sequence[_ast.ASTNode]
    ) -> z3.ExprRef:
        """Handle set operations."""
        z3_args = [self.transform(arg) for arg in args]

        def set_ty(i: int) -> _ast.SetType:
            arg_expr = cast(_ast.Expr, args[i])
            ty = arg_expr.get_type()
            assert isinstance(ty, _ast.SetType)
            return ty

        if func_name == "set_is_empty":
            ty0 = set_ty(0)
            members = self._sizedset_members(z3_args[0], ty0)
            size0 = self._sizedset_size(z3_args[0], ty0)
            return cast(
                z3.ExprRef,
                z3.And(
                    size0 == 0, members == z3.EmptySet(self._type_to_sort(ty0.elem))
                ),
            )

        if func_name == "set_is_subset":
            ty0 = set_ty(0)
            ty1 = set_ty(1)
            return z3.IsSubset(
                self._sizedset_members(z3_args[0], ty0),
                self._sizedset_members(z3_args[1], ty1),
            )

        if func_name == "set_add":
            ty0 = set_ty(0)
            members = self._sizedset_members(z3_args[0], ty0)
            size0 = self._sizedset_size(z3_args[0], ty0)
            elem_sort = self._type_to_sort(ty0.elem)
            elem = self._coerce_expr_to_sort(z3_args[1], elem_sort)
            new_members = z3.SetAdd(members, elem)
            new_size = size0 + z3.If(
                z3.IsMember(elem, members),
                z3.IntVal(0, self._ctx),
                z3.IntVal(1, self._ctx),
            )  # type: ignore[operator]
            return self._mk_sizedset(new_members, new_size, ty0)

        if func_name == "set_del":
            ty0 = set_ty(0)
            members = self._sizedset_members(z3_args[0], ty0)
            size0 = self._sizedset_size(z3_args[0], ty0)
            elem_sort = self._type_to_sort(ty0.elem)
            elem = self._coerce_expr_to_sort(z3_args[1], elem_sort)
            new_members = z3.SetDel(members, elem)
            new_size = size0 - z3.If(
                z3.IsMember(elem, members),
                z3.IntVal(1, self._ctx),
                z3.IntVal(0, self._ctx),
            )  # type: ignore[operator]
            self._add_constraint(new_size >= 0)
            return self._mk_sizedset(new_members, new_size, ty0)

        if func_name == "set_union":
            ty0 = set_ty(0)
            ty1 = set_ty(1)
            m0 = self._sizedset_members(z3_args[0], ty0)
            m1 = self._sizedset_members(z3_args[1], ty1)
            new_members = z3.SetUnion(m0, m1)
            s0 = self._sizedset_size(z3_args[0], ty0)
            s1 = self._sizedset_size(z3_args[1], ty1)
            new_size = z3.FreshInt(ctx=self._ctx)
            self._bind(str(new_size), new_size)
            self._add_constraint(new_size >= 0)
            self._add_constraint(new_size <= s0 + s1)  # type: ignore[operator]
            return self._mk_sizedset(new_members, new_size, ty0)

        if func_name == "set_intersect":
            ty0 = set_ty(0)
            ty1 = set_ty(1)
            m0 = self._sizedset_members(z3_args[0], ty0)
            m1 = self._sizedset_members(z3_args[1], ty1)
            new_members = z3.SetIntersect(m0, m1)
            s0 = self._sizedset_size(z3_args[0], ty0)
            s1 = self._sizedset_size(z3_args[1], ty1)
            new_size = z3.FreshInt(ctx=self._ctx)
            self._bind(str(new_size), new_size)
            self._add_constraint(new_size >= 0)
            self._add_constraint(
                new_size
                <= z3.If(cast(z3.ArithRef, s0) <= cast(z3.ArithRef, s1), s0, s1)
            )
            return self._mk_sizedset(new_members, new_size, ty0)

        if func_name == "set_difference":
            ty0 = set_ty(0)
            ty1 = set_ty(1)
            m0 = self._sizedset_members(z3_args[0], ty0)
            m1 = self._sizedset_members(z3_args[1], ty1)
            new_members = z3.SetDifference(m0, m1)
            s0 = self._sizedset_size(z3_args[0], ty0)
            new_size = z3.FreshInt(ctx=self._ctx)
            self._bind(str(new_size), new_size)
            self._add_constraint(new_size >= 0)
            self._add_constraint(new_size <= s0)
            return self._mk_sizedset(new_members, new_size, ty0)

        if func_name == "set_complement":
            ty0 = set_ty(0)
            m0 = self._sizedset_members(z3_args[0], ty0)
            new_members = z3.SetComplement(m0)
            new_size = z3.FreshInt(ctx=self._ctx)
            self._bind(str(new_size), new_size)
            self._add_constraint(new_size >= 0)
            return self._mk_sizedset(new_members, new_size, ty0)

        raise NotImplementedError(f"Set operation {func_name} not implemented")

    def _handle_string_operation(
        self, func_name: str, args: Sequence[_ast.ASTNode]
    ) -> z3.ExprRef:
        """Handle string operations."""
        z3_args = [self.transform(arg) for arg in args]

        if func_name == "concat":
            return z3.Concat(*z3_args)
        elif func_name == "contains":
            return z3.Contains(*z3_args)
        elif func_name == "substr":
            s, begin, end = z3_args
            return z3.SubString(s, begin, end)
        elif func_name == "indexof":
            s, substr, start = z3_args
            return z3.IndexOf(s, substr, start)
        elif func_name == "replace":
            return z3.Replace(*z3_args)
        elif func_name == "prefixof":
            return z3.PrefixOf(*z3_args)
        elif func_name == "suffixof":
            return z3.SuffixOf(*z3_args)
        elif func_name == "uppercase":
            if len(z3_args) != 1:
                raise ValueError("uppercase() takes exactly one argument")
            # Leave as uninterpreted
            uf = z3.Function("uppercase", z3_args[0].sort(), z3_args[0].sort())
            return uf(z3_args[0])
        elif func_name == "lowercase":
            if len(z3_args) != 1:
                raise ValueError("lowercase() takes exactly one argument")
            # Leave as uninterpreted
            uf = z3.Function("lowercase", z3_args[0].sort(), z3_args[0].sort())
            return uf(z3_args[0])
        elif func_name == "int2str":
            return z3.IntToStr(z3_args[0])
        elif func_name == "str2int":
            return z3.StrToInt(z3_args[0])

        raise NotImplementedError(f"String operation {func_name} not implemented")

    def _handle_type_conversion(
        self, func_name: str, args: Sequence[_ast.ASTNode]
    ) -> z3.ExprRef:
        """Handle type conversions."""
        z3_args = [self.transform(arg) for arg in args]
        if func_name == "int2real":
            assert len(args) == 1
            if (
                self._real_encoding == RealEncodingMode.FLOATING_POINT
                and self._fp_enabled()
            ):
                return self._to_fp(z3_args[0])
            casted = z3.ToReal(z3_args[0])
            assert isinstance(casted, z3.ExprRef)
            return casted
        elif func_name == "real2int":
            if (
                self._real_encoding == RealEncodingMode.FLOATING_POINT
                and self._fp_enabled()
            ):
                fp_expr = self._to_fp(z3_args[0])
                real_expr = z3.fpToReal(fp_expr, ctx=self._ctx)
                casted = z3.ToInt(real_expr)
                assert isinstance(casted, z3.ExprRef)
                return casted
            casted = z3.ToInt(z3_args[0])
            assert isinstance(casted, z3.ExprRef)
            return casted
        raise NotImplementedError(f"Type conversion {func_name} not implemented")

    def _handle_map_record_functions(
        self, node: _ast.FuncCall, func_name: str
    ) -> z3.ExprRef:
        """Handle map and record iteration functions."""
        if func_name == "keys":
            if len(node.args) != 1:
                raise ValueError("keys() takes exactly one argument")
            map_ty = node.args[0].get_type()

            if isinstance(map_ty, _ast.RecordType):
                # For records, return a constant list of field names
                field_names = list(map_ty.fields.keys())
                string_lits = [_ast.StringLiteral(value=name) for name in field_names]
                return self.transform(_ast.ExplicitList(elements=string_lits))
            else:
                raise ValueError(f"keys() not supported for type {map_ty}")

        elif func_name == "values":
            if len(node.args) != 1:
                raise ValueError("values() takes exactly one argument")
            map_ty = node.args[0].get_type()

            if isinstance(map_ty, _ast.RecordType):
                # For records, return a list of field values
                field_values = []
                for field_name in map_ty.fields.keys():
                    field_access = _ast.ListAccess(
                        seq=node.args[0], index=_ast.StringLiteral(value=field_name)
                    )
                    field_values.append(field_access)
                return self.transform(_ast.ExplicitList(elements=field_values))
            else:
                raise ValueError(f"values() not supported for type {map_ty}")

        elif func_name == "items":
            if len(node.args) != 1:
                raise ValueError("items() takes exactly one argument")
            map_ty = node.args[0].get_type()

            if isinstance(map_ty, _ast.RecordType):
                # For records, return tuples of (field_name, field_value)
                item_tuples = []
                for field_name in map_ty.fields.keys():
                    field_access = _ast.ListAccess(
                        seq=node.args[0], index=_ast.StringLiteral(value=field_name)
                    )
                    tuple_expr = _ast.TupleExpr(
                        elements=[_ast.StringLiteral(value=field_name), field_access]
                    )
                    item_tuples.append(tuple_expr)
                return self.transform(_ast.ExplicitList(elements=item_tuples))
            else:
                raise ValueError(f"items() not supported for type {map_ty}")

        elif func_name == "has_key":
            if len(node.args) != 2:
                raise ValueError("has_key() takes exactly two arguments")
            key_expr = self.transform(node.args[1])
            map_ty = node.args[0].get_type()

            if isinstance(map_ty, _ast.RecordType):
                # For records, check if key is a valid field name
                if isinstance(node.args[1], _ast.StringLiteral):
                    field_name = node.args[1].value
                    return cast(
                        z3.ExprRef, z3.BoolVal(field_name in map_ty.fields, self._ctx)
                    )
                else:
                    # Dynamic check - would need to enumerate all field names
                    field_names = list(map_ty.fields.keys())
                    conditions = [
                        key_expr == z3.StringVal(name, self._ctx)
                        for name in field_names
                    ]
                    if conditions:
                        return cast(z3.ExprRef, z3.Or(*conditions))
                    else:
                        return cast(z3.ExprRef, z3.BoolVal(False, self._ctx))
            else:
                raise ValueError(f"has_key() not supported for type {map_ty}")

        raise NotImplementedError(f"Map/record function {func_name} not implemented")

    # ------------------------------------------------------------------
    # Lambda expressions
    # ------------------------------------------------------------------

    def visit_LambdaExpr(self, node: _ast.LambdaExpr) -> z3.ExprRef:
        """Handle lambda expressions."""
        z3_args = []

        self._push_scope()
        # Create Z3 variables for lambda arguments
        for arg in node.args:
            sort = self._type_to_sort(arg.get_type())
            z3_arg = z3.Const(arg.name, sort)
            z3_args.append(z3_arg)
            self._bind(arg.name, z3_arg)

        # Transform lambda body
        body = self.transform(node.body)

        self._pop_scope()

        return z3.Lambda(z3_args, body)

    # ------------------------------------------------------------------
    # Helper methods for function/predicate definitions
    # ------------------------------------------------------------------

    def _id_to_var(self, id: _ast.Identifier) -> z3.ExprRef:
        """Convert an identifier to a Z3 variable."""
        sort = self._type_to_sort(id.get_type())
        var = z3.Const(id.name, sort)
        self._bind(id.name, var)
        return var

    def _bind_args(self, args: Sequence[_ast.Identifier]) -> list[z3.ExprRef]:
        """Bind arguments to Z3 variables."""
        z3_args = []
        for arg in args:
            z3_args.append(self._id_to_var(arg))
        return z3_args

    def _compile_entry_func(
        self, node: _ast.FunctionDef | _ast.PredicateDef
    ) -> z3.ExprRef:
        if node.body is None:
            return z3.BoolVal(True)
        self._bind_args(node.args)
        var_decls = [self.visit_VarDecl(stmt) for stmt in node.var_decls]
        body_expr = self.transform(node.body)
        subs = [(var_decl[0], var_decl[1]) for var_decl in var_decls]
        body_expr = self._substitute_fixed_point(body_expr, *subs)
        return body_expr

    def _define_constant(
        self,
        name: str,
        sort: z3.SortRef,
        body_expr: Optional[z3.ExprRef],
    ) -> z3.ExprRef:
        """Define a zero-argument function/predicate as a Z3 constant."""
        # Create the constant
        const = z3.Const(name, sort)
        self._bind(name, const)

        if body_expr is None:
            return const

        constraint = const == body_expr
        assert isinstance(constraint, z3.BoolRef)
        self._add_constraint(constraint)

        return const

    def _check_not_in_non_local_vars(self, var, non_local_vars):
        return all(var is not arg for arg in non_local_vars)

    def _compile_explicit_function_def(
        self, node: _ast.PredicateDef | _ast.FunctionDef
    ):
        if node.body is None:
            return
        self._push_scope()
        self._push_local_constraints()
        args = self._bind_args(node.args)
        var_decls = [self.visit_VarDecl(stmt) for stmt in node.var_decls]
        body_expr = self.transform(node.body)
        subs = [(var_decl[0], var_decl[1]) for var_decl in var_decls]
        body_expr = self._substitute_fixed_point(body_expr, *subs)
        variables = self._pop_scope()
        constraints = self._pop_local_constraints()
        non_local_vars = args + [var_decl[0] for var_decl in var_decls]
        local_variables = [
            var
            for var in variables
            if self._check_not_in_non_local_vars(var, non_local_vars)
        ]
        f = self._lookup(node.name)

        if isinstance(node, _ast.PredicateDef) or (
            isinstance(node, _ast.FunctionDef)
            and node.return_val.get_type() == _ast.Boolean()
        ):
            body = z3.And(body_expr, *constraints)
            if local_variables:
                body = z3.Exists(local_variables, body)

        assert isinstance(f, z3.FuncDeclRef)
        if isinstance(node, _ast.PredicateDef) or (
            isinstance(node, _ast.FunctionDef)
            and node.return_val.get_type() == _ast.Boolean()
        ):
            # For predicates and boolean-returning functions, include local constraints
            z3.RecAddDefinition(f, args, body)
        else:
            # For non-boolean functions, assert side constraints separately
            if constraints:
                side: z3.ExprRef = cast(z3.ExprRef, z3.And(*constraints))
                if local_variables:
                    side = z3.Exists(local_variables, side)
                if args:
                    side = z3.ForAll(list(args), side)
                assert isinstance(side, z3.BoolRef)
                self._add_constraint(side)
            z3.RecAddDefinition(f, args, body_expr)

    # ------------------------------------------------------------------
    # Statements (requires and ensures)
    # ------------------------------------------------------------------

    def visit_VarDecl(self, node: _ast.VarDecl) -> tuple[z3.ExprRef, z3.ExprRef]:
        """Handle variable declarations."""
        z3_expr = self.transform(node.expr)
        var = self._id_to_var(node.var)
        return var, z3_expr

    def visit_Require(self, node: _ast.Require) -> z3.ExprRef:
        """Handle require statements."""
        return self.transform(node.expr)

    def visit_Ensure(self, node: _ast.Ensure) -> z3.ExprRef:
        """Handle ensure statements."""
        return self.transform(node.expr)

    # ------------------------------------------------------------------
    # Declarations (predicates and functions)
    # ------------------------------------------------------------------

    def visit_PredicateDef(self, node: _ast.PredicateDef) -> z3.ExprRef:
        """Handle predicate definitions."""
        if len(node.args) == 0:
            body = None
            if node.body is not None:
                # Support local var declarations inside zero-arg predicates
                var_decls = [self.visit_VarDecl(stmt) for stmt in node.var_decls]
                body = self.transform(node.body)
                subs = [(var_decl[0], var_decl[1]) for var_decl in var_decls]
                body = self._substitute_fixed_point(body, *subs)
            constant = self._define_constant(
                node.name,
                z3.BoolSort(self._ctx),
                body,
            )
            return constant

        if node.body is not None:
            self._compile_explicit_function_def(node)

        return z3.BoolVal(True, self._ctx)

    def visit_FunctionDef(self, node: _ast.FunctionDef) -> z3.ExprRef:
        """Handle function definitions."""

        # No arguments
        if len(node.args) == 0:
            body = None
            if node.body is not None:
                # Support local var declarations inside zero-arg explicit functions
                var_decls = [self.visit_VarDecl(stmt) for stmt in node.var_decls]
                body = self.transform(node.body)
                subs = [(var_decl[0], var_decl[1]) for var_decl in var_decls]
                body = self._substitute_fixed_point(body, *subs)
            constant = self._define_constant(
                node.name,
                self._type_to_sort(node.return_val.get_type()),
                body,
            )
            return constant

        if node.body is not None:
            self._compile_explicit_function_def(node)

        assert node.return_val is not None
        assert node.return_val.ty is not None

        return z3.BoolVal(True, self._ctx)

    # ------------------------------------------------------------------
    # Quantifiers
    # ------------------------------------------------------------------

    def _create_quantifier_expression(
        self,
        quantifier_type: str,  # "forall" or "exists"
        quantified_vars: Sequence[z3.ExprRef],
        local_vars: Sequence[z3.ExprRef],
        satisfies_expr: z3.ExprRef,
        local_constraints: Sequence[z3.BoolRef],
    ) -> z3.ExprRef:
        """Create quantifier expression with proper logical structure."""
        if quantifier_type == "forall":
            # The body of the quantifier is the implication
            if len(local_constraints) == 0:
                body = satisfies_expr
            else:
                body = z3.And(satisfies_expr, *local_constraints)

            if local_vars:
                # If there are local existential variables, wrap the body
                inner_quantifier = z3.Exists(list(local_vars), body)
                return z3.ForAll(quantified_vars, inner_quantifier)
            else:
                # No local variables
                return z3.ForAll(quantified_vars, body)

        elif quantifier_type == "exists":
            # We generally don't add patterns to existential quantifiers
            body = z3.And(*local_constraints, satisfies_expr)
            if local_vars:
                # Combine all existential variables into one quantifier
                return z3.Exists(list(quantified_vars) + list(local_vars), body)
            else:
                return z3.Exists(list(quantified_vars), body)
        else:
            raise ValueError(
                f"Unknown quantifier type: {quantifier_type}"
            )  # pragma: no cover

    def _visit_Quantifier(self, node: _ast.ForallExpr | _ast.ExistsExpr) -> z3.ExprRef:
        """Handle quantifier expressions."""
        self._push_scope()
        self._push_local_constraints()
        quantified_vars = self._bind_args(node.vars)
        satisfies_expr = self.transform(node.satisfies_expr)
        local_constraints = self._pop_local_constraints()
        z3_vars = self._pop_scope()
        local_vars = [
            var
            for var in z3_vars
            if self._check_not_in_non_local_vars(var, quantified_vars)
            and isinstance(var, z3.ExprRef)
        ]
        if isinstance(node, _ast.ForallExpr):
            quantifier_type = "forall"
        else:
            quantifier_type = "exists"
        return self._create_quantifier_expression(
            quantifier_type,
            quantified_vars,
            local_vars,
            satisfies_expr,
            local_constraints,
        )

    def visit_ForallExpr(self, node: _ast.ForallExpr) -> z3.ExprRef:
        """Handle universal quantification."""
        return self._visit_Quantifier(node)

    def visit_ExistsExpr(self, node: _ast.ExistsExpr) -> z3.ExprRef:
        """Handle existential quantification."""
        return self._visit_Quantifier(node)

    # ------------------------------------------------------------------
    # Top-level specification
    # ------------------------------------------------------------------

    def visit_Specification(self, node: _ast.Specification) -> z3.ExprRef:
        """Handle top-level specification."""

        # Pass 1: Register all function and predicate signatures
        for decl in node.declarations:
            if isinstance(decl, (_ast.FunctionDef, _ast.PredicateDef)):
                self._register_signature(decl)
                # Store AST for callsite inlining
                self._func_ast_nodes[decl.name] = decl

        # Pass 2: Process all declarations
        results = []
        for decl in node.declarations:
            result = self.transform(decl)
            results.append(result)

        # Combine all constraints
        if self._constraints:
            combined = (
                z3.And(*self._constraints)
                if len(self._constraints) > 1
                else self._constraints[0]
            )
            if self._negate:
                combined = z3.Not(combined)
            assert isinstance(combined, z3.BoolRef)
            return combined
        else:
            # If no constraints, return true (or false if negated)
            return z3.BoolVal(not self._negate, self._ctx)

    def _register_signature(self, node: _ast.FunctionDef | _ast.PredicateDef):
        """Register function or predicate signature in environment."""
        if len(node.args) == 0:
            return

        # Determine return sort
        if isinstance(node, _ast.PredicateDef):
            return_sort = z3.BoolSort(self._ctx)
        else:
            # For FunctionDef
            if node.body is not None:
                assert node.body.ty is not None
                return_sort = self._type_to_sort(node.body.get_type())
            else:
                # Implicit function with return_val
                assert node.return_val is not None
                assert node.return_val.ty is not None
                return_sort = self._type_to_sort(node.return_val.get_type())

        # Create function declaration
        arg_sorts = []
        for arg in node.args:
            assert arg.ty is not None
            arg_sorts.append(self._type_to_sort(arg.get_type()))

        if node.body is not None:
            func_decl = z3.RecFunction(node.name, *arg_sorts, return_sort)
        else:
            func_decl = z3.Function(node.name, *arg_sorts, return_sort)
        self._bind(node.name, func_decl)

    # ------------------------------------------------------------------
    # Inlining helpers and fuel management
    # ------------------------------------------------------------------

    def set_default_fuel(self, fuel: int) -> None:
        """Set the default fuel for inlining recursive function calls."""
        if fuel < 0:
            raise ValueError("Fuel must be non-negative")
        self._default_fuel = fuel

    def _get_fuel(self, func_name: str) -> int:
        for frame in reversed(self._fuel_env_stack):
            if func_name in frame:
                return frame[func_name]
        return self._default_fuel

    def _push_fuel_frame(self, func_name: str) -> None:
        remaining = self._get_fuel(func_name)
        self._fuel_env_stack.append({func_name: remaining - 1})

    def _pop_fuel_frame(self) -> None:
        if not self._fuel_env_stack:
            return
        self._fuel_env_stack.pop()

    def _evaluate_function_call(
        self,
        func_name: str,
        func_decl: z3.FuncDeclRef | z3.ExprRef,
        ast_def: _ast.FunctionDef | _ast.PredicateDef,
        args: list[z3.ExprRef],
    ) -> z3.ExprRef:
        """Inline function body with fuel; fallback to uninterpreted application when fuel is 0."""

        def call() -> z3.ExprRef:
            if len(args) > 0 and isinstance(func_decl, z3.FuncDeclRef):
                return func_decl(*args)
            elif len(args) == 0 and isinstance(func_decl, z3.ExprRef):
                return func_decl
            else:
                raise ValueError(f"Invalid function call: {func_decl} with args {args}")

        if isinstance(ast_def, _ast.FunctionDef) and ast_def.body is not None:
            return call()

        if self._get_fuel(func_name) <= 0:
            return call()

        self._push_fuel_frame(func_name)
        if isinstance(ast_def, _ast.FunctionDef):
            assert ast_def.return_val is not None
            return_sort = self._type_to_sort(ast_def.return_val.get_type())

            self._push_scope()
            self._push_local_constraints()
            for arg_id, arg_val in zip(ast_def.args, args):
                assert arg_id.ty is not None
                self._bind(arg_id.name, arg_val)

            ret_name = ast_def.return_val.name
            ret_sym = self._declare_const(ret_name, return_sort)
            self._bind(ret_name, ret_sym)
            return_expr = ret_sym

            var_decls = [self.visit_VarDecl(stmt) for stmt in ast_def.var_decls]
            requires_list = [self.transform(stmt) for stmt in ast_def.requires]
            ensures_list = [self.transform(stmt) for stmt in ast_def.ensures]

            local_constraints = self._pop_local_constraints()
            variables = self._pop_scope()

            # Substitute ret_sym -> ret_fresh, and var decl variables -> expressions
            subs_tuples: list[tuple[z3.ExprRef, z3.ExprRef]] = var_decls
            if len(args) > 0:
                ret_fresh = z3.FreshConst(return_sort)
                self._bind(str(ret_fresh), ret_fresh)
                subs_tuples.append((ret_sym, ret_fresh))
                return_expr = ret_fresh

            substituted_requires = [
                self._substitute_fixed_point(require, *subs_tuples)
                for require in requires_list
            ]
            substituted_ensures = [
                self._substitute_fixed_point(ensure, *subs_tuples)
                for ensure in ensures_list
            ]

            # Build implication body
            constraint_body = z3.And(
                *substituted_requires, *substituted_ensures, *local_constraints
            )

            # Existentially quantify any remaining local variables introduced during transformation
            non_local_vars = (
                list(args) + [ret_sym] + [var_decl[0] for var_decl in var_decls]
            )
            local_vars = [
                var
                for var in variables
                if self._check_not_in_non_local_vars(var, non_local_vars)
            ]
            callsite_constraint = (
                z3.Exists(local_vars, constraint_body)
                if local_vars
                else constraint_body
            )
            assert isinstance(callsite_constraint, z3.BoolRef)
            self._add_constraint(callsite_constraint)
            self._add_constraint(call() == return_expr)  # type: ignore
            self._pop_fuel_frame()
            return return_expr

        # PredicateDef: inline body directly
        assert isinstance(ast_def, _ast.PredicateDef)
        if ast_def.body is None:
            self._pop_fuel_frame()
            # No body: treat predicate as uninterpreted application
            return call()
        try:
            result = self._inline_body(ast_def, args)
        finally:
            self._pop_fuel_frame()
        return result

    def _inline_body(
        self, ast_def: _ast.FunctionDef | _ast.PredicateDef, args: list[z3.ExprRef]
    ) -> z3.ExprRef:
        """Inline explicit body by binding params to actual args and substituting var decls."""
        self._push_scope()
        try:
            # Bind formal args to actual z3 expressions
            for arg_id, arg_val in zip(ast_def.args, args):
                assert arg_id.ty is not None
                self._bind(arg_id.name, arg_val)

            var_decls = [self.visit_VarDecl(stmt) for stmt in ast_def.var_decls]
            if ast_def.body is None:
                body_expr = z3.BoolVal(True, self._ctx)
            else:
                body_expr = self.transform(ast_def.body)
            subs = [(var_decl[0], var_decl[1]) for var_decl in var_decls]
            body_expr = self._substitute_fixed_point(body_expr, *subs)
            return body_expr
        finally:
            self._pop_scope()

    def _inline_expr_with_var_decls(
        self,
        ast_def: _ast.FunctionDef | _ast.PredicateDef,
        expr_ast: _ast.Expr,
        args: list[z3.ExprRef],
    ) -> z3.ExprRef:
        """Inline an arbitrary expression with var declarations and bound args."""
        self._push_scope()
        try:
            for arg_id, arg_val in zip(ast_def.args, args):
                assert arg_id.ty is not None
                self._bind(arg_id.name, arg_val)
            var_decls = [self.visit_VarDecl(stmt) for stmt in ast_def.var_decls]
            expr = self.transform(expr_ast)
            subs = [(var_decl[0], var_decl[1]) for var_decl in var_decls]
            expr = self._substitute_fixed_point(expr, *subs)
            return expr
        finally:
            self._pop_scope()

    def _extract_definitional_ensure_expr(
        self, node: _ast.FunctionDef
    ) -> Optional[_ast.Expr]:
        """Extract expression from ensures of the form res == expr or expr == res."""
        if node.return_val is None:
            return None
        for ens in node.ensures:
            if isinstance(ens.expr, _ast.BinaryOp) and ens.expr.op == "==":
                left = ens.expr.left
                right = ens.expr.right
                if (
                    isinstance(left, _ast.Identifier)
                    and left.name == node.return_val.name
                ):
                    return right
                if (
                    isinstance(right, _ast.Identifier)
                    and right.name == node.return_val.name
                ):
                    return left
        return None

    def _combine_requires(
        self, node: _ast.FunctionDef, args: list[z3.ExprRef]
    ) -> Optional[z3.BoolRef]:
        """Transform and combine requires into a single guard expression, if any."""
        if not node.requires:
            return None
        self._push_scope()
        try:
            for arg_id, arg_val in zip(node.args, args):
                assert arg_id.ty is not None
                self._bind(arg_id.name, arg_val)
            req_exprs = [self.transform(req) for req in node.requires]
            guard = z3.And(*req_exprs) if len(req_exprs) > 1 else req_exprs[0]
            assert isinstance(guard, z3.BoolRef)
            return guard
        finally:
            self._pop_scope()

    # ------------------------------------------------------------------
    # Utility methods for type integration
    # ------------------------------------------------------------------

    def set_type_info(self, type_checker: TypeChecker):
        """Set type checker instance for type inference."""
        self._type_checker = type_checker

    def get_constraints(self) -> List[z3.BoolRef]:
        """Get collected constraints."""
        return self._constraints.copy()

    # ------------------------------------------------------------------
    # Substitution
    # ------------------------------------------------------------------

    def _substitute_fixed_point(
        self,
        expr: z3.ExprRef,
        *substitutions: tuple[z3.ExprRef, z3.ExprRef],
    ) -> z3.ExprRef:
        """Substitute variables in an expression until fixed point."""
        prev_expr = expr
        new_expr = z3.substitute(expr, *substitutions)
        assert isinstance(new_expr, z3.ExprRef)
        max_depth = len(substitutions)
        cnt = 0
        while new_expr.sexpr() != prev_expr.sexpr():
            if cnt == max_depth:
                raise ValueError("substitution has cycle")
            prev_expr, new_expr = new_expr, z3.substitute(new_expr, *substitutions)
            cnt += 1
        return new_expr

    # ------------------------------------------------------------------
    # Type to sort
    # ------------------------------------------------------------------

    def _type_to_sort(self, ty: _ast.DSLType) -> z3.SortRef:
        """Convert a DSL type to a Z3 sort."""
        if ty == _ast.Integer():
            return z3.IntSort(self._ctx)
        elif ty == _ast.Boolean():
            return z3.BoolSort(self._ctx)
        elif ty == _ast.Real():
            if (
                self._real_encoding == RealEncodingMode.FLOATING_POINT
                and self._fp_sort is not None
            ):
                return self._fp_sort
            return z3.RealSort(self._ctx)
        elif ty == _ast.Char():
            return z3.CharSort(self._ctx)
        elif ty == _ast.ListType(_ast.Char()):
            return z3.StringSort(self._ctx)
        elif isinstance(ty, _ast.ListType):
            return z3.SeqSort(self._type_to_sort(ty.elem))
        elif isinstance(ty, _ast.SetType):
            # Map Set[T] to a sized set datatype with (members:Set[T], size:Int)
            return self._sizedset_datatype_generator(ty)
        elif isinstance(ty, _ast.MultisetType):
            return z3.ArraySort(self._type_to_sort(ty.elem), z3.IntSort(self._ctx))
        elif isinstance(ty, _ast.MapType):
            return z3.ArraySort(
                self._type_to_sort(ty.key), self._type_to_sort(ty.value)
            )
        elif isinstance(ty, _ast.OptionType):
            return self._option_datatype_generator(ty)
        elif isinstance(ty, _ast.FuncType):
            raise ValueError("Function types should be handled specially")
        elif isinstance(ty, _ast.TypeVar):
            return z3.IntSort(self._ctx)
        elif isinstance(ty, _ast.TupleType):
            return self._tuple_datatype_generator(ty)
        elif isinstance(ty, _ast.RecordType):
            return self._record_datatype_generator(ty)
        elif isinstance(ty, _ast.DSLNoneType):
            none_sort, _ = self._get_dsl_none_info()
            return none_sort
        else:
            raise ValueError(f"Unknown type: {ty}")

    def _coerce_expr_to_sort(
        self, expr: z3.ExprRef, target_sort: z3.SortRef
    ) -> z3.ExprRef:
        """Coerce an expression to the given sort when supported."""
        if expr.sort().eq(target_sort):
            return expr

        if target_sort.eq(z3.RealSort(self._ctx)) and z3.is_int(expr):
            coerced = z3.ToReal(expr)
            assert isinstance(coerced, z3.ExprRef)
            return coerced

        if (
            self._real_encoding == RealEncodingMode.FLOATING_POINT
            and self._fp_sort is not None
            and target_sort.eq(self._fp_sort)
        ):
            return self._to_fp(expr)

        raise TypeError(
            "Cannot coerce expression of sort "
            f"{expr.sort()} to target sort {target_sort}"
        )

    def _tuple_datatype_generator(self, ty: _ast.TupleType) -> z3.DatatypeSortRef:
        """Generate a Z3 datatype for a tuple type."""
        key = str(ty)
        if key in self._tuple_datatypes:
            return self._tuple_datatypes[key][0]
        else:
            tuple_sort, tuple_constructor, accessors = z3.TupleSort(
                key,
                [self._type_to_sort(elem) for elem in ty.elem_types],
                self._ctx,
            )
        self._tuple_datatypes[key] = (tuple_sort, tuple_constructor, accessors)
        return tuple_sort

    def _record_datatype_generator(self, ty: _ast.RecordType) -> z3.DatatypeSortRef:
        """Generate a Z3 datatype for a record type."""
        # Create a normalized key based on sorted field names for consistency
        sorted_fields = sorted(ty.fields.items())
        normalized_key = f"record[{', '.join(f'{name}: {field_ty}' for name, field_ty in sorted_fields)}]"

        if normalized_key in self._record_datatypes:
            return self._record_datatypes[normalized_key][0]

        # Build a dedicated datatype with a single constructor and named accessors
        dt = z3.Datatype(normalized_key, ctx=self._ctx)
        ctor_args = [
            (field_name, self._type_to_sort(field_ty))
            for field_name, field_ty in sorted_fields
        ]
        dt.declare("MkRecord", *ctor_args)
        dt_sort = dt.create()
        ctor = dt_sort.constructor(0)
        accessor_map: Dict[str, z3.FuncDeclRef] = {
            field_name: dt_sort.accessor(0, idx)
            for idx, (field_name, _field_ty) in enumerate(sorted_fields)
        }
        self._record_datatypes[normalized_key] = (dt_sort, ctor, accessor_map)
        return dt_sort

    # ------------------------------------------------------------------
    # None helpers
    # ------------------------------------------------------------------

    def _get_dsl_none_info(self) -> tuple[z3.DatatypeSortRef, z3.ExprRef]:
        if self._dsl_none_sort is None or self._dsl_none_value is None:
            none_sort, values = z3.EnumSort(
                "DSLNoneType",
                ["dsl_none"],
                ctx=self._ctx,
            )
            self._dsl_none_sort = none_sort
            self._dsl_none_value = values[0]
        return self._dsl_none_sort, self._dsl_none_value

    # ------------------------------------------------------------------
    # Option type helpers
    # ------------------------------------------------------------------

    def _option_key(self, ty: _ast.OptionType) -> str:
        val_sort = self._type_to_sort(ty.elem)
        return f"Option[{val_sort.sexpr()}]"

    def _option_datatype_generator(self, ty: _ast.OptionType) -> z3.DatatypeSortRef:
        key = self._option_key(ty)
        if key in self._option_datatypes:
            return self._option_datatypes[key][0]
        val_sort = self._type_to_sort(ty.elem)
        opt_sort, ctor, accessors = z3.TupleSort(
            key,
            [z3.BoolSort(self._ctx), val_sort],
            self._ctx,
        )
        self._option_datatypes[key] = (opt_sort, ctor, accessors)
        return opt_sort

    def _get_option_info(
        self, ty: _ast.OptionType
    ) -> tuple[z3.DatatypeSortRef, z3.FuncDeclRef, List[z3.FuncDeclRef]]:
        key = self._option_key(ty)
        if key not in self._option_datatypes:
            _ = self._option_datatype_generator(ty)
        return self._option_datatypes[key]

    def _option_is_some(self, expr: z3.ExprRef, ty: _ast.OptionType) -> z3.ExprRef:
        dt_sort, ctor, accessors = self._get_option_info(ty)
        _ = (dt_sort, ctor)
        is_some_acc = accessors[0]
        return is_some_acc(expr)

    def _option_val(self, expr: z3.ExprRef, ty: _ast.OptionType) -> z3.ExprRef:
        dt_sort, ctor, accessors = self._get_option_info(ty)
        _ = (dt_sort, ctor)
        val_acc = accessors[1]
        return val_acc(expr)

    # ------------------------------------------------------------------
    # Sized set helpers
    # ------------------------------------------------------------------

    def _sizedset_key(self, ty: _ast.SetType) -> str:
        elem_sort = self._type_to_sort(ty.elem)
        return f"SizedSet[{elem_sort.sexpr()}]"

    def _sizedset_datatype_generator(self, ty: _ast.SetType) -> z3.DatatypeSortRef:
        """Generate a Z3 datatype for a sized set of element type ty.elem.

        The datatype is a tuple with two fields:
          - members: Set(elem_sort)
          - size: Int
        """
        key = self._sizedset_key(ty)
        if key in self._sized_set_datatypes:
            return self._sized_set_datatypes[key][0]
        elem_sort = self._type_to_sort(ty.elem)
        sized_sort, ctor, accessors = z3.TupleSort(
            key,
            [z3.ArraySort(elem_sort, z3.BoolSort(self._ctx)), z3.IntSort(self._ctx)],
            self._ctx,
        )
        self._sized_set_datatypes[key] = (sized_sort, ctor, accessors)
        return sized_sort

    def _get_sizedset_info(
        self, ty: _ast.SetType
    ) -> tuple[z3.DatatypeSortRef, z3.FuncDeclRef, List[z3.FuncDeclRef]]:
        key = self._sizedset_key(ty)
        if key not in self._sized_set_datatypes:
            _ = self._sizedset_datatype_generator(ty)
        return self._sized_set_datatypes[key]

    def _sizedset_members(self, expr: z3.ExprRef, ty: _ast.SetType) -> z3.ExprRef:
        dt_sort, ctor, accessors = self._get_sizedset_info(ty)
        _ = (dt_sort, ctor)  # silence unused
        members_acc = accessors[0]
        return members_acc(expr)

    def _sizedset_size(self, expr: z3.ExprRef, ty: _ast.SetType) -> z3.ExprRef:
        dt_sort, ctor, accessors = self._get_sizedset_info(ty)
        _ = (dt_sort, ctor)
        size_acc = accessors[1]
        return size_acc(expr)

    def _mk_sizedset(
        self, members: z3.ExprRef, size: z3.ExprRef, ty: _ast.SetType
    ) -> z3.ExprRef:
        dt_sort, ctor, _ = self._get_sizedset_info(ty)
        _ = dt_sort
        return ctor(members, size)

    def _dsl_type_from_sort(self, sort: z3.SortRef) -> _ast.DSLType:
        none_sort, _ = self._get_dsl_none_info()
        if sort.eq(none_sort):
            return _ast.DSLNoneType()
        if sort.eq(z3.IntSort(self._ctx)):
            return _ast.Integer()
        if self._fp_sort is not None and sort.eq(self._fp_sort):
            return _ast.Real()
        if sort.eq(z3.RealSort(self._ctx)):
            return _ast.Real()
        if sort.eq(z3.BoolSort(self._ctx)):
            return _ast.Boolean()
        if sort.eq(z3.CharSort(self._ctx)):
            return _ast.Char()
        # Strings represent list[char], not a set element; default to int
        return _ast.Integer()

    def transform(self, node: _ast.ASTNode) -> z3.ExprRef:
        expr = super().transform(node)
        if isinstance(expr, z3.ExprRef):
            return z3.simplify(expr)
        return expr
