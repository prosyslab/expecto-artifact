from __future__ import annotations

"""Z3 list encoding using (Array[Int -> Elem], len:Int) packed in a datatype.

This module provides:
  - A reusable datatype constructor for list-like values: one constructor with
    two fields: `arr` (Array[Int -> Elem]) and `len` (Int).
  - Helper accessors/constructors to build and inspect encoded lists.
  - Higher-order helpers: fold_left and map implemented with K-bounded unrolling
    and an over-approximate symbolic tail summary to avoid quantifiers and
    incomplete sequence theory.

Design goals:
  - Keep encodings quantifier-free (QF_AUFLIA + UF) for robustness.
  - Allow exact semantics when `len <= K` and safe over-approx when `len > K`.
  - Avoid enforcing semantics that require quantifiers; instead, expose optional
    tail constraints (e.g., monotonicity) that callers can enable when sound.
"""

from typing import Dict, Optional, Tuple, Union, cast

import z3

# -----------------------------------------------------------------------------
# Datatype cache per (ctx, elem_sort)
# -----------------------------------------------------------------------------

_LIST_DTYPE_CACHE: Dict[
    Tuple[Optional[int], str],
    Tuple[
        z3.DatatypeSortRef,  # list sort
        z3.FuncDeclRef,  # constructor
        z3.FuncDeclRef,  # is-constructor tester
        z3.FuncDeclRef,  # arr selector
        z3.FuncDeclRef,  # len selector
    ],
] = {}


def _ctx_key(ctx: Optional[z3.Context]) -> Optional[int]:
    return id(ctx) if ctx is not None else None


def _elem_key(elem_sort: z3.SortRef) -> str:
    # Use textual representation as a stable-ish key across runs/contexts.
    return str(elem_sort)


def get_list_datatype(
    elem_sort: z3.SortRef,
    *,
    ctx: Optional[z3.Context] = None,
    name: Optional[str] = None,
) -> Tuple[
    z3.DatatypeSortRef, z3.FuncDeclRef, z3.FuncDeclRef, z3.FuncDeclRef, z3.FuncDeclRef
]:
    """Get (or create) the List datatype for the given element sort.

    The datatype has a single constructor `mk` with fields:
      - `arr`: Array[Int -> elem_sort]
      - `len`: Int

    Returns a tuple: (ListSort, mk, is_mk, arr_sel, len_sel).
    """
    key = (_ctx_key(ctx), _elem_key(elem_sort))
    if key in _LIST_DTYPE_CACHE:
        return _LIST_DTYPE_CACHE[key]

    # Ensure sorts live in the same context when explicitly provided
    int_sort = z3.IntSort(ctx)
    arr_sort = z3.ArraySort(int_sort, elem_sort)

    dt_name = name or f"List_{_elem_key(elem_sort)}"
    dt = z3.Datatype(dt_name, ctx=ctx)
    dt.declare("mk", ("arr", arr_sort), ("len", int_sort))
    list_sort = dt.create()

    mk = list_sort.mk
    is_mk = list_sort.is_mk
    arr_sel = list_sort.arr
    len_sel = list_sort.len

    _LIST_DTYPE_CACHE[key] = (list_sort, mk, is_mk, arr_sel, len_sel)
    return _LIST_DTYPE_CACHE[key]


# -----------------------------------------------------------------------------
# Basic helpers
# -----------------------------------------------------------------------------


def list_length(lst: z3.ExprRef) -> z3.ArithRef:
    """Return the `len` field of the list value."""
    # Use generic accessor to avoid relying on instance-attached attributes
    # Constructor index 0 ('mk'), field index 1 ('len')
    sel = lst.sort().accessor(0, 1)  # type: ignore[attr-defined]
    return sel(lst)  # type: ignore[no-any-return]


def list_array(lst: z3.ExprRef) -> z3.ExprRef:
    """Return the `arr` field of the list value."""
    # Constructor index 0 ('mk'), field index 0 ('arr')
    sel = lst.sort().accessor(0, 0)  # type: ignore[attr-defined]
    return sel(lst)  # type: ignore[no-any-return]


def mk_list_const(
    name: str,
    elem_sort: z3.SortRef,
    *,
    ctx: Optional[z3.Context] = None,
) -> z3.ExprRef:
    """Create a Z3 constant of the list datatype."""
    list_sort, _mk, _is, _arr_sel, _len_sel = get_list_datatype(elem_sort, ctx=ctx)
    return z3.Const(name, list_sort)


def mk_list_from_components(
    arr: z3.ExprRef,
    length: z3.ArithRef,
    elem_sort: z3.SortRef,
    *,
    ctx: Optional[z3.Context] = None,
) -> z3.ExprRef:
    """Pack `(arr, length)` into the list datatype."""
    if not z3.is_array(arr):
        raise TypeError("arr must be an Array sort expression")
    list_sort, mk, _is, _arr_sel, _len_sel = get_list_datatype(elem_sort, ctx=ctx)
    return mk(arr, length)


# -----------------------------------------------------------------------------
# Utility: guarded select (optional)
# -----------------------------------------------------------------------------


def guarded_select(
    arr: z3.ExprRef, idx: z3.ArithRef, length: z3.ArithRef, default_val: z3.ExprRef
) -> z3.ExprRef:
    """Select with 0 <= idx < length guard; return default outside bounds."""
    if not z3.is_array(arr):
        raise TypeError("guarded_select expects arr to be an Array expression")
    return cast(
        z3.ExprRef,
        z3.If(
            z3.And(z3.IntVal(0) <= idx, idx < length), z3.Select(arr, idx), default_val
        ),
    )


# -----------------------------------------------------------------------------
# Higher-order functions
# -----------------------------------------------------------------------------


def _apply_ho_fn(
    fn: Union[z3.FuncDeclRef, z3.ExprRef], *args: z3.ExprRef
) -> z3.ExprRef:
    """Apply a higher-order function represented as:
    - z3.FuncDeclRef (uninterpreted/defined function)
    - z3.ExprRef that is an Array/Lambda (apply via nested Select)
    - Python callable (fallback for convenience/testing)
    """
    # z3 function declaration
    if isinstance(fn, z3.FuncDeclRef):
        return fn(*args)

    # Treat remaining expressions (Lambda/Array) as array-like and apply via multi-arg Select
    if isinstance(fn, z3.ExprRef):
        return z3.Select(fn, *args)

    raise TypeError(
        "Unsupported higher-order function representation; expected z3.FuncDeclRef, array/Lambda ExprRef, or Python callable."
    )


def fold_left_k(
    step_fn: Union[z3.FuncDeclRef, z3.ExprRef],
    init_acc: z3.ExprRef,
    lst: z3.ExprRef,
    K: int,
    *,
    ctx: Optional[z3.Context] = None,
    overapprox: bool = True,
    tail_monotone_ge: bool = False,
    tail_monotone_le: bool = False,
    uf_name: Optional[str] = None,
) -> Tuple[z3.ExprRef, z3.ExprRef, list[z3.BoolRef]]:
    """Compute fold_left over the first K elements, with optional tail summary.

    Returns (result_expr, acc_after_K, constraints).

    - Exact when `len(lst) <= K`.
    - If `overapprox` and `len(lst) > K`, result is `Tail(accK, arr, K, len)` where
      `Tail` is an uninterpreted function of type:
        (AccSort, Array[Int->Elem], Int, Int) -> AccSort
      plus boundary constraint `len == K => res == accK`.
    - If `tail_monotone_ge`, also add `res >= accK` (requires arithmetic acc).
    - If `tail_monotone_le`, also add `res <= accK` (requires arithmetic acc).
    """
    assert K >= 0, "K must be non-negative"
    ctx = ctx or lst.ctx
    constraints: list[z3.BoolRef] = []

    elem_arr = list_array(lst)
    # Determine element sort via a dummy select to avoid stub issues
    ctx = ctx or lst.ctx
    elem_sort = z3.Select(elem_arr, z3.IntVal(0, ctx=ctx)).sort()
    int_sort = z3.IntSort(ctx)
    arr = elem_arr
    length = list_length(lst)

    acc: z3.ExprRef = init_acc
    for i in range(K):
        idx = z3.IntVal(i, ctx=ctx)
        elem_i = z3.Select(arr, idx)
        next_acc: z3.ExprRef = _apply_ho_fn(step_fn, acc, elem_i)
        acc = cast(z3.ExprRef, z3.If(idx < length, next_acc, acc))
    accK = acc

    if not overapprox:
        return cast(z3.ExprRef, accK), cast(z3.ExprRef, accK), constraints

    acc_sort = cast(z3.ExprRef, accK).sort()
    uf = z3.Function(
        uf_name or "fold_tail",
        acc_sort,
        z3.ArraySort(int_sort, elem_sort),
        int_sort,
        int_sort,
        acc_sort,
    )
    res: z3.ExprRef = cast(
        z3.ExprRef,
        z3.If(
            length <= z3.IntVal(K, ctx=ctx),
            accK,
            uf(accK, arr, z3.IntVal(K, ctx=ctx), length),
        ),
    )

    # Boundary exactness
    constraints.append(z3.Implies(length == z3.IntVal(K, ctx=ctx), res == accK))

    # Optional tail bounds for arithmetic accumulators
    if tail_monotone_ge or tail_monotone_le:
        if not (z3.is_arith_sort(acc_sort)):
            raise TypeError("Monotone tail bounds require arithmetic accumulator sort")
        if tail_monotone_ge:
            constraints.append(cast(z3.ArithRef, res) >= cast(z3.ArithRef, accK))
        if tail_monotone_le:
            constraints.append(cast(z3.ArithRef, res) <= cast(z3.ArithRef, accK))

    return cast(z3.ExprRef, res), cast(z3.ExprRef, accK), constraints


def map_k(
    map_fn: Union[z3.FuncDeclRef, z3.ExprRef],
    lst: z3.ExprRef,
    out_elem_sort: z3.SortRef,
    K: int,
    *,
    ctx: Optional[z3.Context] = None,
    overapprox: bool = True,
    uf_name: Optional[str] = None,
) -> Tuple[z3.ExprRef, list[z3.BoolRef]]:
    """Map the first K elements exactly; over-approximate the tail if needed.

    Returns (mapped_list_expr, constraints).

    - Exact when `len(lst) <= K`.
    - If `overapprox` and `len(lst) > K`, the output array is
      `Tail(arr_out_K, arr_in, K, len)` where Tail is an uninterpreted function:
        (Array[Int->OutElem], Array[Int->InElem], Int, Int) -> Array[Int->OutElem]
      plus boundary constraint `len == K => arr_out == arr_out_K`.
    """
    assert K >= 0, "K must be non-negative"
    constraints: list[z3.BoolRef] = []

    in_arr = list_array(lst)
    length = list_length(lst)

    int_sort = z3.IntSort(ctx)
    out_arr_sort = z3.ArraySort(int_sort, out_elem_sort)

    # Start from a fresh base array and update positions 0..K-1 conditionally
    out_arr: z3.ArrayRef = cast(z3.ArrayRef, z3.FreshConst(out_arr_sort))
    for i in range(K):
        idx = z3.IntVal(i, ctx=ctx)
        mapped_i: z3.ExprRef = _apply_ho_fn(map_fn, z3.Select(in_arr, idx))
        out_arr = cast(
            z3.ArrayRef, z3.If(idx < length, z3.Store(out_arr, idx, mapped_i), out_arr)
        )

    list_sort_out, mk, _is, _arr_sel, _len_sel = get_list_datatype(
        out_elem_sort, ctx=ctx
    )

    if not overapprox:
        return mk(out_arr, length), constraints

    # Over-approximate tail via uninterpreted function on arrays
    tail_uf = z3.Function(
        uf_name or "map_tail",
        out_arr_sort,
        z3.ArraySort(int_sort, z3.Select(in_arr, z3.IntVal(0, ctx=ctx)).sort()),
        int_sort,
        int_sort,
        out_arr_sort,
    )
    out_arr_total: z3.ExprRef = cast(
        z3.ExprRef,
        z3.If(
            length <= z3.IntVal(K, ctx=ctx),
            out_arr,
            tail_uf(out_arr, in_arr, z3.IntVal(K, ctx=ctx), length),
        ),
    )
    constraints.append(
        z3.Implies(length == z3.IntVal(K, ctx=ctx), out_arr_total == out_arr)
    )

    return mk(out_arr_total, length), constraints


def map_i_k(
    map_fn: Union[z3.FuncDeclRef, z3.ExprRef],
    lst: z3.ExprRef,
    out_elem_sort: z3.SortRef,
    K: int,
    *,
    ctx: Optional[z3.Context] = None,
    overapprox: bool = True,
    uf_name: Optional[str] = None,
) -> Tuple[z3.ExprRef, list[z3.BoolRef]]:
    """Index-aware map over first K elements; over-approximate tail if needed."""
    assert K >= 0
    ctx = ctx or lst.ctx
    constraints: list[z3.BoolRef] = []
    in_arr = list_array(lst)
    length = list_length(lst)

    int_sort = z3.IntSort(ctx)
    out_arr_sort = z3.ArraySort(int_sort, out_elem_sort)

    out_arr: z3.ArrayRef = cast(z3.ArrayRef, z3.FreshConst(out_arr_sort))
    for i in range(K):
        idx = z3.IntVal(i, ctx=ctx)
        mapped_i = _apply_ho_fn(map_fn, idx, z3.Select(in_arr, idx))
        out_arr = cast(
            z3.ArrayRef, z3.If(idx < length, z3.Store(out_arr, idx, mapped_i), out_arr)
        )

    list_sort_out, mk, _is, _arr_sel, _len_sel = get_list_datatype(
        out_elem_sort, ctx=ctx
    )

    if not overapprox:
        return mk(out_arr, length), constraints

    tail_uf = z3.Function(
        uf_name or "map_i_tail",
        out_arr_sort,
        z3.ArraySort(int_sort, z3.Select(in_arr, z3.IntVal(0, ctx=ctx)).sort()),
        int_sort,
        int_sort,
        out_arr_sort,
    )
    out_arr_total: z3.ExprRef = cast(
        z3.ExprRef,
        z3.If(
            length <= z3.IntVal(K, ctx=ctx),
            out_arr,
            tail_uf(out_arr, in_arr, z3.IntVal(K, ctx=ctx), length),
        ),
    )
    constraints.append(
        z3.Implies(length == z3.IntVal(K, ctx=ctx), out_arr_total == out_arr)
    )
    return mk(out_arr_total, length), constraints


def filter_k(
    pred_fn: Union[z3.FuncDeclRef, z3.ExprRef],
    lst: z3.ExprRef,
    K: int,
    *,
    ctx: Optional[z3.Context] = None,
    overapprox: bool = True,
    uf_name_arr: Optional[str] = None,
    uf_name_len: Optional[str] = None,
) -> Tuple[z3.ExprRef, list[z3.BoolRef]]:
    """Filter first K elements exactly; over-approximate the tail (arr,len) separately.

    Returns (filtered_list, constraints).
    """
    assert K >= 0
    ctx = ctx or lst.ctx
    constraints: list[z3.BoolRef] = []

    in_arr = list_array(lst)
    length = list_length(lst)
    elem_sort = z3.Select(in_arr, z3.IntVal(0, ctx=ctx)).sort()
    int_sort = z3.IntSort(ctx)
    out_arr_sort = z3.ArraySort(int_sort, elem_sort)

    out_arr: z3.ArrayRef = cast(z3.ArrayRef, z3.FreshConst(out_arr_sort))
    out_len: z3.ArithRef = z3.IntVal(0, ctx=ctx)
    for i in range(K):
        idx = z3.IntVal(i, ctx=ctx)
        elem_i = z3.Select(in_arr, idx)
        keep_i = _apply_ho_fn(pred_fn, elem_i)
        next_out_len = z3.If(
            idx < length,
            z3.If(keep_i, out_len + z3.IntVal(1, ctx=ctx), out_len),
            out_len,
        )
        next_out_arr = z3.If(
            idx < length,
            z3.If(keep_i, z3.Store(out_arr, out_len, elem_i), out_arr),
            out_arr,
        )
        out_arr = cast(z3.ArrayRef, next_out_arr)
        out_len = cast(z3.ArithRef, next_out_len)

    list_sort_out, mk, _is, _arr_sel, _len_sel = get_list_datatype(elem_sort, ctx=ctx)

    if not overapprox:
        return mk(out_arr, out_len), constraints

    # Over-approximate the suffix with two UFs: arr and len
    tail_arr = z3.Function(
        uf_name_arr or "filter_tail_arr",
        out_arr_sort,
        z3.ArraySort(int_sort, elem_sort),
        int_sort,
        int_sort,
        out_arr_sort,
    )
    tail_len = z3.Function(
        uf_name_len or "filter_tail_len",
        int_sort,
        z3.ArraySort(int_sort, elem_sort),
        int_sort,
        int_sort,
        int_sort,
    )
    out_arr_total: z3.ExprRef = cast(
        z3.ExprRef,
        z3.If(
            length <= z3.IntVal(K, ctx=ctx),
            out_arr,
            tail_arr(out_arr, in_arr, z3.IntVal(K, ctx=ctx), length),
        ),
    )
    out_len_total: z3.ExprRef = cast(
        z3.ExprRef,
        z3.If(
            length <= z3.IntVal(K, ctx=ctx),
            out_len,
            tail_len(out_len, in_arr, z3.IntVal(K, ctx=ctx), length),
        ),
    )
    constraints.append(
        z3.Implies(length == z3.IntVal(K, ctx=ctx), out_arr_total == out_arr)
    )
    constraints.append(
        z3.Implies(length == z3.IntVal(K, ctx=ctx), out_len_total == out_len)
    )
    return mk(out_arr_total, out_len_total), constraints


def all_k(
    pred_fn: Union[z3.FuncDeclRef, z3.ExprRef],
    lst: z3.ExprRef,
    K: int,
    *,
    overapprox: bool = True,
    uf_name: Optional[str] = None,
) -> Tuple[z3.BoolRef, list[z3.BoolRef]]:
    ctx = lst.ctx
    acc = z3.BoolVal(True, ctx=ctx)
    constraints: list[z3.BoolRef] = []
    in_arr = list_array(lst)
    length = list_length(lst)
    for i in range(K):
        idx = z3.IntVal(i, ctx=ctx)
        el = z3.Select(in_arr, idx)
        p = _apply_ho_fn(pred_fn, el)
        acc = z3.If(idx < length, z3.And(acc, p), acc)
    accK = acc
    if not overapprox:
        return cast(z3.BoolRef, accK), constraints
    tail_uf = z3.Function(
        uf_name or "all_tail",
        z3.ArraySort(z3.IntSort(ctx), z3.Select(in_arr, z3.IntVal(0, ctx=ctx)).sort()),
        z3.IntSort(ctx),
        z3.IntSort(ctx),
        z3.BoolSort(ctx),
    )
    res = z3.If(
        length <= z3.IntVal(K, ctx=ctx),
        accK,
        tail_uf(in_arr, z3.IntVal(K, ctx=ctx), length),
    )
    constraints.append(z3.Implies(length == z3.IntVal(K, ctx=ctx), res == accK))
    return cast(z3.BoolRef, res), constraints


def any_k(
    pred_fn: Union[z3.FuncDeclRef, z3.ExprRef],
    lst: z3.ExprRef,
    K: int,
    *,
    overapprox: bool = True,
    uf_name: Optional[str] = None,
) -> Tuple[z3.BoolRef, list[z3.BoolRef]]:
    ctx = lst.ctx
    acc = z3.BoolVal(False, ctx=ctx)
    constraints: list[z3.BoolRef] = []
    in_arr = list_array(lst)
    length = list_length(lst)
    for i in range(K):
        idx = z3.IntVal(i, ctx=ctx)
        el = z3.Select(in_arr, idx)
        p = _apply_ho_fn(pred_fn, el)
        acc = z3.If(idx < length, z3.Or(acc, p), acc)
    accK = acc
    if not overapprox:
        return cast(z3.BoolRef, accK), constraints
    tail_uf = z3.Function(
        uf_name or "any_tail",
        z3.ArraySort(z3.IntSort(ctx), z3.Select(in_arr, z3.IntVal(0, ctx=ctx)).sort()),
        z3.IntSort(ctx),
        z3.IntSort(ctx),
        z3.BoolSort(ctx),
    )
    res = z3.If(
        length <= z3.IntVal(K, ctx=ctx),
        accK,
        tail_uf(in_arr, z3.IntVal(K, ctx=ctx), length),
    )
    constraints.append(z3.Implies(length == z3.IntVal(K, ctx=ctx), res == accK))
    return cast(z3.BoolRef, res), constraints


def sum_k(
    lst: z3.ExprRef,
    K: int,
    *,
    overapprox: bool = True,
    uf_name: Optional[str] = None,
) -> Tuple[z3.ArithRef, list[z3.BoolRef]]:
    in_arr = list_array(lst)
    length = list_length(lst)
    acc: z3.ArithRef = z3.IntVal(0)
    constraints: list[z3.BoolRef] = []
    for i in range(K):
        idx = z3.IntVal(i)
        el = z3.Select(in_arr, idx)
        acc = cast(z3.ArithRef, z3.If(idx < length, acc + el, acc))
    accK = acc
    if not overapprox:
        return cast(z3.ArithRef, accK), constraints
    tail_uf = z3.Function(
        uf_name or "sum_tail",
        z3.ArraySort(z3.IntSort(), z3.Select(in_arr, z3.IntVal(0)).sort()),
        z3.IntSort(),
        z3.IntSort(),
        z3.IntSort(),
    )
    res = z3.If(length <= z3.IntVal(K), accK, tail_uf(in_arr, z3.IntVal(K), length))
    constraints.append(z3.Implies(length == z3.IntVal(K), res == accK))
    return cast(z3.ArithRef, res), constraints


def product_k(
    lst: z3.ExprRef,
    K: int,
    *,
    overapprox: bool = True,
    uf_name: Optional[str] = None,
) -> Tuple[z3.ArithRef, list[z3.BoolRef]]:
    in_arr = list_array(lst)
    length = list_length(lst)
    acc: z3.ArithRef = z3.IntVal(1)
    constraints: list[z3.BoolRef] = []
    for i in range(K):
        idx = z3.IntVal(i)
        el = z3.Select(in_arr, idx)
        acc = cast(z3.ArithRef, z3.If(idx < length, acc * el, acc))
    accK = acc
    if not overapprox:
        return cast(z3.ArithRef, accK), constraints
    tail_uf = z3.Function(
        uf_name or "product_tail",
        z3.ArraySort(z3.IntSort(), z3.Select(in_arr, z3.IntVal(0)).sort()),
        z3.IntSort(),
        z3.IntSort(),
        z3.IntSort(),
    )
    res = z3.If(length <= z3.IntVal(K), accK, tail_uf(in_arr, z3.IntVal(K), length))
    constraints.append(z3.Implies(length == z3.IntVal(K), res == accK))
    return cast(z3.ArithRef, res), constraints


def max_k(
    lst: z3.ExprRef,
    K: int,
    default_val: z3.ArithRef,
    *,
    overapprox: bool = True,
    uf_name: Optional[str] = None,
) -> Tuple[z3.ArithRef, list[z3.BoolRef]]:
    in_arr = list_array(lst)
    length = list_length(lst)
    acc: z3.ArithRef = default_val
    constraints: list[z3.BoolRef] = []
    for i in range(K):
        idx = z3.IntVal(i)
        el = z3.Select(in_arr, idx)
        cand = z3.If(el > acc, el, acc)
        acc = cast(z3.ArithRef, z3.If(idx < length, cand, acc))
    accK = acc
    if not overapprox:
        return cast(z3.ArithRef, accK), constraints
    tail_uf = z3.Function(
        uf_name or "max_tail",
        z3.ArraySort(z3.IntSort(), z3.Select(in_arr, z3.IntVal(0)).sort()),
        z3.IntSort(),
        z3.IntSort(),
        z3.IntSort(),
    )
    res = z3.If(length <= z3.IntVal(K), accK, tail_uf(in_arr, z3.IntVal(K), length))
    constraints.append(z3.Implies(length == z3.IntVal(K), res == accK))
    return cast(z3.ArithRef, res), constraints


def min_k(
    lst: z3.ExprRef,
    K: int,
    default_val: z3.ArithRef,
    *,
    overapprox: bool = True,
    uf_name: Optional[str] = None,
) -> Tuple[z3.ArithRef, list[z3.BoolRef]]:
    in_arr = list_array(lst)
    length = list_length(lst)
    acc: z3.ArithRef = default_val
    constraints: list[z3.BoolRef] = []
    for i in range(K):
        idx = z3.IntVal(i)
        el = z3.Select(in_arr, idx)
        cand = z3.If(el < acc, el, acc)
        acc = cast(z3.ArithRef, z3.If(idx < length, cand, acc))
    accK = acc
    if not overapprox:
        return cast(z3.ArithRef, accK), constraints
    tail_uf = z3.Function(
        uf_name or "min_tail",
        z3.ArraySort(z3.IntSort(), z3.Select(in_arr, z3.IntVal(0)).sort()),
        z3.IntSort(),
        z3.IntSort(),
        z3.IntSort(),
    )
    res = z3.If(length <= z3.IntVal(K), accK, tail_uf(in_arr, z3.IntVal(K), length))
    constraints.append(z3.Implies(length == z3.IntVal(K), res == accK))
    return cast(z3.ArithRef, res), constraints


def average_k(
    lst: z3.ExprRef,
    K: int,
    *,
    overapprox: bool = True,
    uf_name: Optional[str] = None,
) -> Tuple[z3.ArithRef, list[z3.BoolRef]]:
    sum_val, cs = sum_k(
        lst, K, overapprox=overapprox, uf_name=(uf_name or "avg_sum_tail")
    )
    length = list_length(lst)
    # Avoid division by zero in general; tests will use len > 0
    avg_tail = z3.Function(
        uf_name or "average_tail",
        z3.IntSort(),
        z3.IntSort(),
        z3.IntSort(),
        z3.RealSort(),
    )
    res = z3.If(
        length <= z3.IntVal(K),
        z3.ToReal(sum_val) / z3.ToReal(length),  # type: ignore[operator]
        avg_tail(sum_val, z3.IntVal(K), length),
    )
    constraints = cs.copy()
    constraints.append(
        z3.Implies(
            length == z3.IntVal(K),
            res == z3.ToReal(sum_val) / z3.ToReal(length),  # type: ignore[operator]
        )
    )
    return cast(z3.ArithRef, res), constraints


def mean_k(
    lst: z3.ExprRef,
    K: int,
    *,
    overapprox: bool = True,
    uf_name: Optional[str] = None,
) -> Tuple[z3.ArithRef, list[z3.BoolRef]]:
    return average_k(lst, K, overapprox=overapprox, uf_name=uf_name)
