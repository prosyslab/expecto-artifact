from __future__ import annotations

"""Reference collector pass for the DSL AST.

This pass traverses a given AST node and collects names of functions/predicates
that are referenced in call positions. It can be used to analyze dependencies
between declarations.
"""

from . import dsl_ast as _ast
from .ast_traverse import ASTTransformer


class ReferenceCollector(ASTTransformer[_ast.ASTNode]):
    """Collect names referenced via function/predicate calls.

    Usage:
        rc = ReferenceCollector(defined_functions)
        names = rc.collect(node)
    """

    def __init__(self, defined_functions: set[str]) -> None:
        self.defined_functions: set[str] = defined_functions
        self.referenced_functions: set[str] = set()

    def collect(self, node: _ast.ASTNode) -> set[str]:
        """Collect and return reference names from `node`."""
        self.referenced_functions.clear()
        self.transform(node)
        return self.referenced_functions

    def visit_Identifier(self, node: _ast.Identifier):
        name = node.name
        if name in self.defined_functions:
            self.referenced_functions.add(name)
        return node
