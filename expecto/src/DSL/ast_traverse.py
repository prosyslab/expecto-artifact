from __future__ import annotations

"""Generic visitor/transformer for the DSL AST.

This module provides a small, pythonic visitor that operates **after** the
`ast_builder` stage.  Each concrete AST node has a dedicated `visit_*` method
(e.g. `visit_NumberLiteral`) which makes writing subsequent passes (pretty
printer, interpreter, Z3 encoder, …) straightforward.

To implement a new pass simply subclass `ASTTransformer` and override the
methods you care about.  For any node that isn't overridden the transformer
will recursively visit its children and return the (potentially updated)
node unchanged.
"""

from typing import Callable, Generic, TypeVar

from . import dsl_ast as _ast

R = TypeVar("R")  # return type of visitor


class ASTTransformer(Generic[R]):
    """Recursive transformer base class for the DSL AST."""

    def transform(self, node: _ast.ASTNode) -> R:
        """Visit `node` and return the result of the corresponding `visit_*`."""

        method_name = f"visit_{type(node).__name__}"
        visitor: Callable[[_ast.ASTNode], R] | None = getattr(self, method_name, None)
        if visitor is None:
            # Default behavior: recursively transform fields and return node unchanged
            for field_name, value in vars(node).items():
                if field_name == "pos":
                    continue
                if isinstance(value, _ast.ASTNode):
                    setattr(node, field_name, self.transform(value))
                elif isinstance(value, list):
                    new_list = []
                    for item in value:
                        if isinstance(item, _ast.ASTNode):
                            new_list.append(self.transform(item))
                        else:
                            new_list.append(item)
                    setattr(node, field_name, new_list)
                elif isinstance(value, dict):
                    new_dict = {}
                    for key, item in value.items():
                        if isinstance(item, _ast.ASTNode):
                            new_dict[key] = self.transform(item)
                        else:
                            new_dict[key] = item
                    setattr(node, field_name, new_dict)
            return node  # type: ignore
        return visitor(node)
