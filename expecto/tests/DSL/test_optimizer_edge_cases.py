import sys
from pathlib import Path

import z3

# Add project root
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.compiler import DSLCompiler, make_solver
from src.DSL.constants import RealEncodingMode


def _check(
    code: str,
    entry: str = "spec",
    *,
    real_encoding: RealEncodingMode = RealEncodingMode.REAL,
) -> z3.CheckSatResult:
    compiler = DSLCompiler(
        ignore_undefineds=True,
        real_encoding=real_encoding,
    )
    compiled = compiler.compile(code, entry_func=entry)
    ctx = compiler.get_ctx()
    solver = make_solver(ctx)
    solver.set("timeout", 5000)
    solver.add(compiled)
    return solver.check()


class TestOptimizerEdgeCases:
    def test_boolean_complements_and_identities(self):
        # (a ∧ ¬a) ==> (0 == 1) simplifies antecedent to false, whole imp is true
        code = """
        predicate spec(x: int) {
            (((x == 1) ∧ ¬(x == 1)) ==> (0 == 1))
        }
        """
        assert _check(code) == z3.sat

    def test_boolean_double_negation(self):
        code = """
        predicate spec() {
            ¬(¬(1 == 1))
        }
        """
        assert _check(code) == z3.sat

    def test_boolean_implication_tautology(self):
        code = """
        predicate spec(x: int) {
            ((x == x) ==> (x == x))
        }
        """
        assert _check(code) == z3.sat

    def test_drop_unused_quantifiers_trivial_bodies(self):
        code_forall = """
        predicate spec() {
            (∀(y: int) :: true)
        }
        """
        assert _check(code_forall) == z3.sat

        code_exists = """
        predicate spec() {
            (∃(y: int) :: false)
        }
        """
        # Pure existential false is unsat
        assert _check(code_exists) == z3.unsat

    def test_quantifier_shadowing_is_preserved(self):
        # Outer x is unused; inner x is used — should not be dropped incorrectly
        code = """
        predicate spec() {
            (∀(x: int) :: (∃(x: int) :: (x == 0)))
        }
        """
        assert _check(code) == z3.sat

    def test_empty_membership_domains(self):
        # Forall with empty list domain via reversed range -> vacuously true
        code_forall = """
        predicate spec() {
            (∀(x: int) :: ((x in [1..0]) ==> (x == x)))
        }
        """
        assert _check(code_forall) == z3.sat

        # Exists with empty list domain -> false
        code_exists = """
        predicate spec() {
            (∃(x: int) :: ((x in [1..0]) ∧ (x == x)))
        }
        """
        assert _check(code_exists) == z3.unsat

    def test_char_range_membership_unrolling(self):
        code = """
        predicate spec() {
            (∀(c: char) :: ((c in ['a'..'c']) ==> ((c == 'a') ∨ (c == 'b') ∨ (c == 'c'))))
        }
        """
        assert _check(code) == z3.sat

    def test_set_subset_threshold_not_unrolled_large(self):
        # 2^7 = 128 > default threshold 64, elimination should be skipped; still sat
        code = """
        predicate spec() {
            (∀(s: set[int]) :: (set_is_subset(s, {1,2,3,4,5,6,7}) ==> true))
        }
        """
        assert _check(code) == z3.sat

    def test_contains_unrolling_for_lists(self):
        # Enumerates all contiguous sublists of [1,2,3]; len(l) >= 0 is trivially true
        code = """
        predicate spec() {
            (∀(l: list[int]) :: (contains([1,2,3], l) ==> (len(l) == len(l))))
        }
        """
        assert _check(code) == z3.sat

    def test_multi_var_bounds_propagation(self):
        # i < j and j < 3 implies i < 3; helps derive finite enumeration for i
        code = """
        predicate spec() {
            (∀(i: int, j: int) :: (((i < j) ∧ (j < 3)) ==> (i < 3)))
        }
        """
        assert _check(code) == z3.sat

    def test_fp_quantifier_elimination_keeps_semantic_comparison(self):
        code = """
        predicate spec(numbers: list[real], threshold: real, result: bool) {
            (result <==> HasClosePair(numbers, threshold))
        }

        predicate HasClosePair(numbers: list[real], threshold: real) {
            (∃(i: int, j: int) ::
                ((((0 <= i < len(numbers)) ∧
                    (0 <= j < len(numbers))) ∧
                    (i != j)) ∧
                    (abs_real((numbers[i] - numbers[j])) < threshold)))
        }

        predicate check_spec() {
            spec([1.0, 2.0, 3.0, 4.0, 5.0], 1.0, false)
        }
        """
        assert (
            _check(
                code,
                entry="check_spec",
                real_encoding=RealEncodingMode.FLOATING_POINT,
            )
            == z3.sat
        )

    def test_fp_quantifier_elimination_preserves_unsat_comparison(self):
        code = """
        predicate helper(xs: list[real]) {
            ∃(i: int, j: int) ::
                (0 <= i) ∧ (i < len(xs)) ∧
                (0 <= j) ∧ (j < len(xs)) ∧
                ((i + 1) == j) ∧
                (abs_real(xs[i] - xs[j]) < -1.0)
        }

        predicate check_spec() {
            helper([1.0, 2.0, 3.0])
        }
        """
        assert (
            _check(
                code,
                entry="check_spec",
                real_encoding=RealEncodingMode.FLOATING_POINT,
            )
            == z3.unsat
        )
