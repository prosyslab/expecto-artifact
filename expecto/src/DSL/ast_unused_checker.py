"""Checker for unused function and predicate definitions in AST."""

from typing import List, Union

from .dsl_ast import (
    ASTNode,
    FuncCall,
    FunctionDef,
    Identifier,
    PredicateDef,
    Specification,
)


def find_unused_defs(spec: Specification) -> List[Union[PredicateDef, FunctionDef]]:
    """Return a list of PredicateDef or FunctionDef that are defined but never called by other definitions."""
    # Collect names of all called functions/predicates
    call_names: set[str] = set()

    def visit(node: ASTNode) -> None:
        if isinstance(node, FuncCall):
            func = node.func
            # If calling by identifier, record the name
            if isinstance(func, Identifier):
                call_names.add(func.name)
            # Continue traversal into func and args
            visit(func)
            for arg in node.args:
                visit(arg)
        else:
            # Traverse ASTNode children
            for attr in vars(node).values():
                if isinstance(attr, ASTNode):
                    visit(attr)
                elif isinstance(attr, list):
                    for item in attr:
                        if isinstance(item, ASTNode):
                            visit(item)

    # Start traversal from the root specification
    visit(spec)

    # Return definitions whose names were not called
    return [decl for decl in spec.declarations if decl.name not in call_names]
