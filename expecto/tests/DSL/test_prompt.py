import sys
from pathlib import Path

import pytest
import z3

# Add root directory to Python path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.compiler import DSLCompiler


class TestPrompt:
    """Test prompt generation."""

    base_path = root_dir / "src" / "prompts"

    @pytest.fixture
    def compiler(self):
        return DSLCompiler()

    def _run_test(self, code: str, tests: list[str], compiler: DSLCompiler):
        for idx, test in enumerate(tests):
            tc_code = code + "\n" + test
            compiled = compiler.compile(tc_code, entry_func="check_spec")
            ctx = compiler.get_ctx()
            solver = z3.Solver(ctx=ctx)
            solver.set("timeout", 5000)
            solver.add(compiled)
            checked = solver.check()
            assert checked == z3.sat, (
                f"Test {idx} failed.\n\n{compiled}\n\nReason: {solver.reason_unknown()}"
            )

    def test_prompt_1(self, compiler):
        code_path = self.base_path / "dsl_model_1.dsl"
        code = code_path.read_text()
        correct_testcase_1 = """
        predicate check_spec() {
            spec(1, 1, 1, 1, [(1, 1)], [1], 1)
        }
        """

        correct_testcase_2 = """
        predicate check_spec() {
            spec(3, 1, 8, 10, [(10, 8), (5, 7), (11, 9)], [3], 10)
        }
        """

        correct_testcase_3 = """
        predicate check_spec() {
            spec(2, 2, 10, 18, [(10, 4), (20, 6), (5, 3)], [3], 20)
        }
        """

        wrong_testcase1 = """
        predicate check_spec() {
            not (spec(1, 1, 1, 1, [(1, 2), (1, 2)], [1, 2], 1))
        }
        """
        wrong_testcase2 = """
        predicate check_spec() {
            not (spec(3, 1, 8, 10, [(10, 8), (5, 7), (11, 9)], [3], 5))
        }
        """
        wrong_testcase3 = """
        predicate check_spec() {
            not (spec(2, 2, 10, 18, [(10, 4), (20, 6), (5, 3)], [5, 3], 10))
        }
        """

        tests = [
            correct_testcase_1,
            correct_testcase_2,
            correct_testcase_3,
            wrong_testcase1,
            wrong_testcase2,
            wrong_testcase3,
        ]
        self._run_test(code, tests, compiler)

    def test_prompt_2(self, compiler):
        code_path = self.base_path / "dsl_model_2.dsl"
        correct_testcase_1 = """
        predicate check_spec() {
            spec("BACFAB", "YES")
        }
        """
        correct_testcase_2 = """
        predicate check_spec() {
            spec("ABBA", "YES")
        }
        """
        wrong_testcase_1 = """
        predicate check_spec() {
            not (spec("BACFAB", "NO"))
        }
        """
        code = code_path.read_text()
        tests = [correct_testcase_1, correct_testcase_2, wrong_testcase_1]
        self._run_test(code, tests, compiler)

    def test_prompt_3(self, compiler):
        code_path = self.base_path / "dsl_model_3.dsl"
        code = code_path.read_text()
        correct_testcase_1 = """
        predicate check_spec() {
            spec(3, [1, 2, 3], 3)
        }
        """
        tests = [correct_testcase_1]
        self._run_test(code, tests, compiler)
