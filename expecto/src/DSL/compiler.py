import re
from typing import List, Optional

import z3
from lark import Lark, ParseError, Token
from lark.exceptions import UnexpectedInput, UnexpectedToken

from .ast_builder import ASTBuilder
from .ast_to_z3 import ASTToZ3
from .ast_unparse import unparse
from .constants import DEFAULT_REAL_ENCODING, RealEncodingMode
from .dsl_ast import ASTNode, Specification
from .dsl_optimizer import DSLOptimizer
from .grammar import grammar
from .type_checker import TypeChecker
from .type_checker import TypeError as DSLTypeError


class DSLCompiler:
    def __init__(
        self,
        ignore_undefineds: bool = False,
        real_encoding: RealEncodingMode | str = DEFAULT_REAL_ENCODING,
    ):
        self.parser = Lark(
            grammar, parser="lalr", start="specification", propagate_positions=True
        )
        self.transformer = ASTBuilder()
        self.optimizer = DSLOptimizer()
        self._real_encoding = (
            real_encoding
            if isinstance(real_encoding, RealEncodingMode)
            else RealEncodingMode(real_encoding)
        )
        self.ast_to_z3 = ASTToZ3(real_encoding=self._real_encoding)
        self.type_checker = TypeChecker(ignore_undefineds=ignore_undefineds)
        self.last_code = ""
        z3.set_option("sat.random_seed", 42)

    def reset(self):
        z3.set_option("sat.random_seed", 42)
        self.ast_to_z3 = ASTToZ3(real_encoding=self._real_encoding)
        self.type_checker = TypeChecker(
            ignore_undefineds=self.type_checker.ignore_undefineds
        )

    def unparse(self, ast: ASTNode, pretty_print: bool = True) -> str:
        return unparse(ast, pretty_print=pretty_print)

    def parse(self, dsl_code: str, do_ppx: bool = True) -> Specification:
        if do_ppx:
            double_dot_list_pattern = r"(\[[^\"\n\[]*)\.\.([^\"\n\]]*\])"
            double_dot_set_pattern = r"(\{[^\"\n\{]*)\.\.([^\"\n\}]*\})"

            def repl(match):
                g1, g2 = match.groups()
                return f"{g1} .. {g2}"

            spaced_double_dot_code = re.sub(
                double_dot_list_pattern, repl, dsl_code, flags=re.MULTILINE
            )
            spaced_double_dot_code = re.sub(
                double_dot_set_pattern, repl, spaced_double_dot_code, flags=re.MULTILINE
            )

            comment_pattern = r"\/\/.*"
            comment_removed_code = re.sub(comment_pattern, "", spaced_double_dot_code)
            self.last_code = comment_removed_code
        else:
            self.last_code = dsl_code

        try:
            lark_tree = self.parser.parse(self.last_code)
        except UnexpectedInput as e:
            msg = ""
            if isinstance(e, UnexpectedToken) and e.token_history:
                last_tok = e.token_history[-1]
                assert isinstance(last_tok, Token)
                if last_tok.type == "CNAME" and last_tok.value in [
                    "var",
                    "ensure",
                    "require",
                ]:
                    msg = "You cannot use statements in predicates or explicit function definitions."
                if last_tok.type in ["SEMICOLON"]:
                    msg = "Please use stmt in implicit function definitions (VarDecl, Ensure, Require)."
            context = e.get_context(self.last_code, span=60)
            raise ParseError(
                f"{msg}\nUnexpected input: {e}\n\nContext:\n{context}"
            ) from e

        result = self.transformer.transform(lark_tree)
        assert isinstance(result, Specification)
        return result

    def type_check(
        self,
        ast: Specification,
    ) -> List[DSLTypeError]:
        return self.type_checker.check(ast)

    def to_z3(
        self, ast: Specification, entry_func: Optional[str] = None
    ) -> list[z3.ExprRef]:
        return self.ast_to_z3.to_z3(ast, entry_func)

    def optimize(self, ast: Specification, entry_func: str = "spec") -> Specification:
        return self.optimizer.optimize(ast, entry_func)

    def get_ctx(self) -> z3.Context:
        return self.ast_to_z3._ctx

    def compile(
        self,
        dsl_code: str,
        optimize: bool = True,
        do_ppx: bool = True,
        entry_func: str = "spec",
    ) -> list[z3.ExprRef]:
        self.reset()
        formatted = self.unparse(
            self.parse(dsl_code, do_ppx=do_ppx), pretty_print=False
        )
        ast = self.parse(formatted, do_ppx=do_ppx)
        assert isinstance(ast, Specification)
        self.type_checker.source_code = formatted
        errors = self.type_check(ast)
        if optimize:
            ast = self.optimize(ast, entry_func)
        if errors:
            raise TypeError("\n\n".join(str(err) for err in errors))
        exprs = self.to_z3(ast, entry_func)
        # Pre-simplify to reduce solver workload
        return [z3.simplify(e) for e in exprs]


def make_solver(ctx: z3.Context) -> z3.Solver:
    """Create a Z3 solver with a tactic pipeline tuned for DSL queries.

    The pipeline applies lightweight QE (when available), value propagation, simplification,
    equation solving, and elimination of unconstrained vars before invoking SMT.
    """
    try:
        tactic = z3.Then(
            z3.OrElse(z3.Tactic(ctx, "qe-light"), z3.Tactic(ctx, "skip")),
            z3.Tactic(ctx, "propagate-values"),
            z3.Tactic(ctx, "simplify"),
            z3.Tactic(ctx, "solve-eqs"),
            z3.Tactic(ctx, "elim-uncnstr"),
            z3.Tactic(ctx, "smt"),
        )
        return tactic.solver()
    except Exception:
        # Fallback to default solver if any tactic is unavailable
        return z3.Solver(ctx=ctx)
