import sys
from pathlib import Path

import z3

# Add project root
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.compiler import DSLCompiler, make_solver


def _check_sat(code: str, entry: str = "spec") -> z3.CheckSatResult:
    compiler = DSLCompiler(ignore_undefineds=True)
    compiled = compiler.compile(code, entry_func=entry)
    ctx = compiler.get_ctx()
    solver = make_solver(ctx)
    solver.set("timeout", 5000)
    solver.add(compiled)
    return solver.check()


def test_boolean_simplify_self_eq():
    code = """
    predicate spec(x: int) {
        (x == x) ==> (x == x)
    }
    """
    assert _check_sat(code) == z3.sat


def test_drop_unused_quantifier():
    code = """
    predicate spec(x: int) {
        (∀(y: int) :: true)
    }
    """
    assert _check_sat(code) == z3.sat


def test_finite_membership_unrolling():
    code = """
    predicate spec() {
        (∀(x: int) :: ((x in {1, 2}) ==> ((x == 1) ∨ (x == 2))))
    }
    """
    assert _check_sat(code) == z3.sat
