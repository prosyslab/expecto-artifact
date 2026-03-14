import sys
from pathlib import Path
from typing import cast

import z3

# Add root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.z3_list import (
    all_k,
    any_k,
    average_k,
    filter_k,
    fold_left_k,
    get_list_datatype,
    list_array,
    list_length,
    map_i_k,
    map_k,
    max_k,
    mean_k,
    min_k,
    mk_list_const,
    mk_list_from_components,
    product_k,
    sum_k,
)


def _array_with_prefix(values):
    int_sort = z3.IntSort()
    arr = z3.K(int_sort, z3.IntVal(0))
    for i, v in enumerate(values):
        arr = z3.Store(arr, z3.IntVal(i), z3.IntVal(v))
    return arr


def test_mk_const_list():
    lst = mk_list_const("lst", z3.IntSort())
    lst2 = mk_list_from_components(
        _array_with_prefix([1, 2, 3]), z3.IntVal(3), z3.IntSort()
    )
    solver = z3.Solver()
    solver.add(lst == lst2)
    assert solver.check() == z3.sat
    assert solver.model().eval(list_length(lst)).py_value() == 3


def test_fold_left_exact_sum_len_eq_K():
    K = 3
    values = [1, 2, 3]
    arr = _array_with_prefix(values)
    length = z3.Int("len")

    s = z3.Solver()
    s.add(length == K, length >= 0)

    lst = mk_list_from_components(arr, length, z3.IntSort())

    acc_v = z3.Int("acc")
    el_v = z3.Int("el")
    step = z3.Lambda([acc_v, el_v], acc_v + el_v)

    res, accK, cs = fold_left_k(step, z3.IntVal(0), lst, K, overapprox=True)
    s.add(cs)

    expected = sum(values)
    s.add(res != z3.IntVal(expected))

    assert s.check() == z3.unsat


def test_fold_left_monotone_tail_overapprox():
    K = 2
    values = [5, 7]
    arr = _array_with_prefix(values)
    length = z3.Int("len2")

    s = z3.Solver()
    s.add(length > K, length >= 0)

    lst = mk_list_from_components(arr, length, z3.IntSort())

    acc_v = z3.Int("acc2")
    el_v = z3.Int("el2")
    step = z3.Lambda([acc_v, el_v], acc_v + z3.If(el_v >= 0, el_v, z3.IntVal(0)))

    res, accK, cs = fold_left_k(
        step,
        z3.IntVal(0),
        lst,
        K,
        overapprox=True,
        tail_monotone_ge=True,
    )
    s.add(cs)

    # Under monotone increasing tail summary, res < accK is impossible
    res_ar = cast(z3.ArithRef, res)
    accK_ar = cast(z3.ArithRef, accK)
    s.add(res_ar < accK_ar)
    assert s.check() == z3.unsat


def test_map_exact_len_eq_K_square_prefix():
    K = 3
    values = [1, 2, 3]
    in_arr = _array_with_prefix(values)
    length = z3.Int("len3")

    s = z3.Solver()
    s.add(length == K, length >= 0)

    in_list = mk_list_from_components(in_arr, length, z3.IntSort())

    x = z3.Int("x")
    mf = z3.Lambda(x, x * x)

    out_list, cs = map_k(mf, in_list, z3.IntSort(), K, overapprox=True)
    s.add(cs)

    # Check mapped prefix elements equal squares
    out_sort, _mk, _is, arr_sel, len_sel = get_list_datatype(z3.IntSort())
    out_arr = arr_sel(out_list)
    for i, v in enumerate(values):
        s.push()
        s.add(z3.Select(out_arr, z3.IntVal(i)) != z3.IntVal(v * v))
        assert s.check() == z3.unsat
        s.pop()
        # Accumulate equality for the next iterations
        s.add(z3.Select(out_arr, z3.IntVal(i)) == z3.IntVal(v * v))


def test_map_preserves_length_even_with_tail_overapprox():
    K = 2
    in_arr = z3.Const("in_arr_any", z3.ArraySort(z3.IntSort(), z3.IntSort()))
    length = z3.Int("len4")

    s = z3.Solver()
    s.add(length >= 0)

    in_list = mk_list_from_components(in_arr, length, z3.IntSort())

    y = z3.Int("y")
    mf = z3.Lambda(y, y + 1)

    out_list, cs = map_k(mf, in_list, z3.IntSort(), K, overapprox=True)
    s.add(cs)

    out_sort, _mk, _is, arr_sel, len_sel = get_list_datatype(z3.IntSort())

    # Prove lengths are equal for all models
    s.push()
    s.add(len_sel(out_list) != length)
    assert s.check() == z3.unsat
    s.pop()


def _arr(values):
    return _array_with_prefix(values)


def test_map_i_basic_exact():
    K = 3
    arr = _arr([1, 2, 3])
    length = z3.Int("len_mi")
    s = z3.Solver()
    s.add(length == K, length >= 0)
    lst = mk_list_from_components(arr, length, z3.IntSort())

    i = z3.Int("i")
    el = z3.Int("el")
    fn = z3.Lambda([i, el], i + el)
    out_list, cs = map_i_k(fn, lst, z3.IntSort(), K)
    s.add(cs)
    _, _, _, arr_sel, len_sel = get_list_datatype(z3.IntSort())
    out_arr = arr_sel(out_list)
    s.add(z3.Select(out_arr, z3.IntVal(0)) != z3.IntVal(0 + 1))
    assert s.check() == z3.unsat
    s.pop() if s.num_scopes() > 0 else None
    s.add(z3.Select(out_arr, z3.IntVal(1)) != z3.IntVal(1 + 2))
    assert s.check() == z3.unsat


def test_filter_basic_exact():
    K = 4
    arr = _arr([1, 2, 3, 4])
    length = z3.Int("len_f")
    s = z3.Solver()
    s.add(length == K, length >= 0)
    lst = mk_list_from_components(arr, length, z3.IntSort())
    x = z3.Int("x")
    pred = z3.Lambda(x, x % 2 == 0)
    out_list, cs = filter_k(pred, lst, K)
    s.add(cs)
    _, _, _, arr_sel, len_sel = get_list_datatype(z3.IntSort())
    out_len = len_sel(out_list)
    s.add(out_len != z3.IntVal(2))  # [2,4]
    assert s.check() == z3.unsat


def test_all_any_exact():
    K = 3
    arr = _arr([2, 4, 6])
    length = z3.Int("len_aa")
    s = z3.Solver()
    s.add(length == K, length >= 0)
    lst = mk_list_from_components(arr, length, z3.IntSort())
    x = z3.Int("x")
    pred = z3.Lambda(x, x % 2 == 0)
    all_res, cs1 = all_k(pred, lst, K)
    any_res, cs2 = any_k(pred, lst, K)
    s.add(cs1 + cs2)
    s.add(z3.Not(all_res))
    assert s.check() == z3.unsat
    s.pop() if s.num_scopes() > 0 else None
    s.add(z3.Not(any_res))
    assert s.check() == z3.unsat


def test_sum_product_max_min_exact():
    K = 3
    values = [1, 2, 3]
    arr = _arr(values)
    length = z3.Int("len_spmm")
    s = z3.Solver()
    s.add(length == K, length >= 0)
    lst = mk_list_from_components(arr, length, z3.IntSort())

    sum_res, cs1 = sum_k(lst, K)
    prod_res, cs2 = product_k(lst, K)
    max_res, cs3 = max_k(lst, K, z3.IntVal(-100))
    min_res, cs4 = min_k(lst, K, z3.IntVal(100))
    s.add(cs1 + cs2 + cs3 + cs4)
    s.add(sum_res != z3.IntVal(sum(values)))
    assert s.check() == z3.unsat
    s.pop() if s.num_scopes() > 0 else None
    s.add(prod_res != z3.IntVal(1 * 2 * 3))
    assert s.check() == z3.unsat
    s.pop() if s.num_scopes() > 0 else None
    s.add(max_res != z3.IntVal(3))
    assert s.check() == z3.unsat
    s.pop() if s.num_scopes() > 0 else None
    s.add(min_res != z3.IntVal(1))
    assert s.check() == z3.unsat


def test_average_mean_exact():
    K = 3
    values = [1, 2, 3]
    arr = _arr(values)
    length = z3.Int("len_avg")
    s = z3.Solver()
    s.add(length == K, length > 0)
    lst = mk_list_from_components(arr, length, z3.IntSort())

    avg_res, cs1 = average_k(lst, K)
    mean_res, cs2 = mean_k(lst, K)
    s.add(cs1 + cs2)
    expected = (1 + 2 + 3) / 3
    s.add(avg_res == z3.RealVal(expected))
    assert s.check() == z3.sat
    s.pop() if s.num_scopes() > 0 else None
    s.add(mean_res == z3.RealVal(expected))
    assert s.check() == z3.sat


def complex_fold_and_filter():
    K = 10
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    arr = _arr(values)
    length = z3.Int("len_cf")
    s = z3.Solver()
    s.add(length == K, length >= 0)
    lst = mk_list_from_components(arr, length, z3.IntSort())

    x = z3.Int("x")
    y = z3.Int("y")
    pred = z3.Lambda(x, x % 2 == 0)
    step = z3.Lambda([x, y], x + y)
    res, accK, cs = fold_left_k(step, z3.IntVal(0), lst, K)
    s.add(cs)
    s.add(res == z3.IntVal(sum(values)))
    assert s.check() == z3.sat
    s.pop() if s.num_scopes() > 0 else None
    s.add(accK == z3.IntVal(sum(values)))
    assert s.check() == z3.sat
    s.pop() if s.num_scopes() > 0 else None
    out_list, cs2 = filter_k(pred, lst, K)
    s.add(cs2)
    s.add(res == z3.IntVal(sum(values)))
    assert s.check() == z3.sat


def test_quantified_on_list_constructor_selector_identity():
    # ForAll lst: mk(arr(lst), len(lst)) == lst
    list_sort, mk, _is, arr_sel, len_sel = get_list_datatype(z3.IntSort())
    lst = z3.Const("lst_q_list", list_sort)
    phi = z3.ForAll([lst], mk(arr_sel(lst), len_sel(lst)) == lst)
    s = z3.Solver()
    s.add(z3.Not(phi))
    assert s.check() == z3.unsat


def test_quantified_map_exact_semantics_len_eq_K():
    # ForAll i in [0, len): out[i] == in[i] + 1 when len == K
    K = 4
    values = [1, 2, 3, 4]
    in_arr_prefix = _arr(values)
    length = z3.Int("len_q")
    s = z3.Solver()
    s.add(length == K, length >= 0)
    in_list = mk_list_from_components(in_arr_prefix, length, z3.IntSort())

    x = z3.Int("x_q")
    mf = z3.Lambda(x, x + 1)

    out_list, cs = map_k(mf, in_list, z3.IntSort(), K, overapprox=True)
    s.add(cs)

    # Quantified property over valid indices
    in_arr = list_array(in_list)
    out_arr = list_array(out_list)
    i = z3.Int("i_q")
    within = z3.And(z3.IntVal(0) <= i, i < length)
    body = z3.Implies(within, z3.Select(out_arr, i) == z3.Select(in_arr, i) + 1)

    # Negate the ForAll and prove UNSAT
    s.add(z3.Not(z3.ForAll([i], body)))
    assert s.check() == z3.unsat
