import sys
from pathlib import Path

# Add project root to Python path (so `src.*` imports work in tests)
ROOT = Path(__file__).parent.parent.parent
sys.path.append(str(ROOT))

from src.DSL.compiler import DSLCompiler
from src.DSL.dsl_ast import Specification
from src.solvers.tree_search import Memo, rename_pair


def _parse_defs(code: str):
    """Parse DSL code and return list of top-level declarations (Defs)."""
    spec = DSLCompiler().parse(code)
    assert isinstance(spec, Specification)
    return list(spec.declarations)


def test_memo_store_and_lookup_returns_original_name():
    # The cached result was created with a formal def named "Sorted"
    results_code = """
    function Sorted(x: int) -> (res: int) : "asc sort" {
        ensure res == x;
    }

    function use(x: int) -> (res: int) {
        var y := Sorted(x);
        ensure res == y;
    }
    """
    results_defs = _parse_defs(results_code)

    # The current target has the same type and description but a different name
    target_code = """
    function sorted(x: int) -> (res: int) : "asc sort" {
        ensure res == x;
    }
    """
    target_def = _parse_defs(target_code)[0]

    memo = Memo(similarity_threshold=0.0)  # force acceptance by description equality

    # Store one memo entry: the results are (formals, placeholders)
    memo.add(target_def, results=[(results_defs, [])], description="asc sort")

    looked_up = memo.lookup(target_def)
    assert looked_up is not None

    # Lookup should return the original name for the target def ("Sorted")
    orig_name, (formals, placeholders) = looked_up[0]
    assert orig_name == "Sorted"
    assert any(d.name == "Sorted" for d in formals)
    assert placeholders == []


def test_rename_pair_changes_def_name_and_references():
    # Original memoized defs use name "Sorted", with a reference in another def
    results_code = """
    function Sorted(x: int) -> (res: int) {
        ensure res == x;
    }

    function use(x: int) -> (res: int) {
        var y := Sorted(x);
        ensure res == y;
    }
    """
    results_defs = _parse_defs(results_code)

    # Apply renaming as would happen on memo reuse (Sorted -> sorted)
    renamed_formals, renamed_placeholders = rename_pair(
        (results_defs, []), "Sorted", "sorted"
    )

    # Verify the def name is updated
    assert any(d.name == "sorted" for d in renamed_formals)
    assert all(d.name != "Sorted" for d in renamed_formals)
    assert renamed_placeholders == []

    # Verify references were updated (string check via unparse is sufficient here)
    spec = Specification(declarations=renamed_formals)
    text = DSLCompiler().unparse(spec, pretty_print=False)
    assert "function sorted(" in text
    assert "Sorted(" not in text  # no stale references


def test_complex_rename_across_lambda_quantifier_and_shadowing():
    results_code = """
    function Sorted(x: int) -> (res: int) {
        ensure res == x;
    }

    predicate uses_in_pred(a: int) {
        var y := Sorted(a);
        y == a
    }

    function uses_in_lambda(a: int) -> (res: int) {
        ensure (lambda (t: int) = Sorted(t))(a) == a;
    }

    predicate uses_in_quant(a: int) {
        ∀ (i: int) :: (i == Sorted(a)) ==> true
    }

    function shadowed(Sorted: int) -> (res: int) {
        var Sorted := Sorted;
        ensure res == Sorted;
    }
    """

    results_defs = _parse_defs(results_code)

    renamed_formals, renamed_placeholders = rename_pair(
        (results_defs, []), "Sorted", "sorted"
    )
    assert renamed_placeholders == []

    spec = Specification(declarations=renamed_formals)
    text = DSLCompiler().unparse(spec, pretty_print=False)

    # Def was renamed
    assert "function sorted(" in text
    # All references updated
    assert "Sorted(" not in text
    assert "sorted(t)" in text
    assert "sorted(a)" in text
    # Shadowed variable name remains (unparser uses '=' for var init)
    assert "var Sorted =" in text
