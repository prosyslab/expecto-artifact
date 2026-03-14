from __future__ import annotations

import sys
from pathlib import Path

import pytest
import z3

root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.compiler import DSLCompiler, make_solver


def _check(
    code: str, *, entry: str = "spec", optimize: bool = True
) -> z3.CheckSatResult:
    compiler = DSLCompiler()
    compiled = compiler.compile(code, entry_func=entry, optimize=optimize)
    ctx = compiler.get_ctx()
    solver = make_solver(ctx)
    solver.set("timeout", 5000)
    solver.add(compiled)
    return solver.check()


def test_repro_implicit_to_explicit_drops_additional_ensures():
    code = """
    function f(x: int) -> (res: int) {
        ensure res == x;
        ensure res > 0;
    }

    predicate spec() { f(-1) == -1 }
    """

    assert _check(code, optimize=False) == z3.unsat
    assert _check(code, optimize=True) == z3.unsat


def test_repro_implicit_entry_function_contract_is_ignored():
    code = """
    function spec() -> (res: int) {
        ensure res == 1;
        ensure res == 2;
    }
    """

    assert _check(code, entry="spec", optimize=False) == z3.unsat


def test_repro_symbolic_range_list_singleton():
    code = """
    predicate singleton_range(x: int) {
        [x..x] == [x]
    }

    predicate spec() { singleton_range(5) }
    """

    assert _check(code, optimize=False) == z3.sat


def test_repro_symbolic_range_set_overapproximation():
    code = """
    predicate bad_membership(x: int) {
        (x + 1) in {x..x}
    }

    predicate spec() { bad_membership(5) }
    """

    assert _check(code, optimize=False) == z3.unsat


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("cardinality(set_union({1}, {1})) == 2", z3.unsat),
        ("cardinality(set_intersect({1}, {2})) == 1", z3.unsat),
        ("cardinality(set_difference({1}, {1})) == 1", z3.unsat),
    ],
)
def test_repro_set_operation_cardinality_is_underconstrained(expr: str, expected):
    code = f"""
    predicate spec() {{
        {expr}
    }}
    """

    assert _check(code, optimize=False) == expected


@pytest.mark.parametrize(
    "code",
    [
        """
        predicate spec() {
            (-3 / -2) == 2
        }
        """,
        """
        predicate spec() {
            (-3 % -2) == 1
        }
        """,
        """
        predicate spec() {
            real2int(-1.2) == -2
        }
        """,
    ],
)
def test_repro_python_numeric_constant_folding_mismatches_smt(code: str):
    assert _check(code, optimize=False) == z3.sat
    assert _check(code, optimize=True) == z3.sat


def test_repro_constant_map_access_disagrees_with_smt():
    code = """
    predicate spec() {
        map{1: 2, 1: 3}[1] == 3
    }
    """

    assert _check(code, optimize=False) == z3.sat
    assert _check(code, optimize=True) == z3.sat


def test_repro_empty_boolean_fold_identity_breaks_quantifier_rewrites():
    code = """
    predicate check_spec() {
      (∀(x: int) :: ((0 <= x <= 6) ==> (x >= 0))) ∧
      (∃(y: int) :: ((0 <= y <= 6) ∧ (y == 0)))
    }
    """

    assert _check(code, entry="check_spec", optimize=False) == z3.sat
    assert _check(code, entry="check_spec", optimize=True) == z3.sat


def test_repro_mars_weekend_counting_positive_case():
    code = r"""
    function DaysOff(n: int, start_day: int) -> int {
        var indices: list[int] = [0 .. (n - 1)];
        fold_i(lambda (i: int, acc: int, _: int) =
            (if ((((start_day + i) % 7) == 5) ∨
                 (((start_day + i) % 7) == 6))
             then (acc + 1) else acc), 0, indices)
    }

    predicate spec(n: int, min_off: int, max_off: int) {
        (0 <= min_off) ∧
        (min_off <= max_off) ∧
        (max_off <= n) ∧
        (∀(start_day: int) ::
            ((0 <= start_day <= 6) ==> (DaysOff(n, start_day) >= min_off))) ∧
        (∀(start_day: int) ::
            ((0 <= start_day <= 6) ==> (DaysOff(n, start_day) <= max_off))) ∧
        (∃(start_day_min: int) ::
            ((0 <= start_day_min <= 6) ∧
             (DaysOff(n, start_day_min) == min_off))) ∧
        (∃(start_day_max: int) ::
            ((0 <= start_day_max <= 6) ∧
             (DaysOff(n, start_day_max) == max_off)))
    }

    predicate check_spec() {
        spec(14, 4, 4)
    }
    """

    assert _check(code, entry="check_spec", optimize=True) == z3.sat
