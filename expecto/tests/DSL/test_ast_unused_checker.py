"""
Test suite for ast_unused_checker.find_unused_defs
"""

import sys
from pathlib import Path

# Add project root to path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from src.DSL.ast_unused_checker import find_unused_defs
from src.DSL.dsl_ast import (
    Ensure,
    FuncCall,
    FunctionDef,
    Identifier,
    PredicateDef,
    Require,
    Specification,
    VarDecl,
)


def test_no_definitions():
    spec = Specification(declarations=[])
    assert find_unused_defs(spec) == []


def test_all_unused():
    p1 = PredicateDef(name="p1", args=[], description=None, var_decls=[], body=None)
    f1 = FunctionDef(
        name="f1",
        args=[],
        description=None,
        var_decls=[],
        requires=[],
        ensures=[],
        body=None,
    )
    spec = Specification(declarations=[p1, f1])
    unused = find_unused_defs(spec)
    assert set(d.name for d in unused) == {"p1", "f1"}


def test_some_used():
    p1 = PredicateDef(name="p1", args=[], description=None, var_decls=[], body=None)
    f1 = FunctionDef(
        name="f1",
        args=[],
        description=None,
        var_decls=[],
        requires=[],
        ensures=[],
        body=None,
    )
    call_p1 = FuncCall(func=Identifier(name="p1"), args=[])
    call_f1 = FuncCall(func=Identifier(name="f1"), args=[])
    p2 = PredicateDef(name="p2", args=[], description=None, var_decls=[], body=call_f1)
    f2 = FunctionDef(
        name="f2",
        args=[],
        description=None,
        var_decls=[VarDecl(var=Identifier(name="x"), expr=call_p1)],
        requires=[],
        ensures=[],
        body=None,
    )
    spec = Specification(declarations=[p1, f1, p2, f2])
    unused = find_unused_defs(spec)
    # p1 and f1 are used by f2 and p2, so only p2 and f2 are unused
    assert set(d.name for d in unused) == {"p2", "f2"}


def test_calls_in_require_and_ensure():
    f1 = FunctionDef(
        name="f1",
        args=[],
        description=None,
        var_decls=[],
        requires=[Require(expr=FuncCall(func=Identifier(name="f2"), args=[]))],
        ensures=[Ensure(expr=FuncCall(func=Identifier(name="f3"), args=[]))],
        body=None,
    )
    f2 = FunctionDef(
        name="f2",
        args=[],
        description=None,
        var_decls=[],
        requires=[],
        ensures=[],
        body=None,
    )
    f3 = FunctionDef(
        name="f3",
        args=[],
        description=None,
        var_decls=[],
        requires=[],
        ensures=[],
        body=None,
    )
    spec = Specification(declarations=[f1, f2, f3])
    unused = find_unused_defs(spec)
    # f2 and f3 are called in f1's requires/ensures, so only f1 is unused
    assert [d.name for d in unused] == ["f1"]


def test_nested_calls():
    g = FunctionDef(
        name="g",
        args=[],
        description=None,
        var_decls=[],
        requires=[],
        ensures=[],
        body=None,
    )
    nested_call = FuncCall(
        func=FuncCall(func=Identifier(name="g"), args=[]),
        args=[],
    )
    f = FunctionDef(
        name="f",
        args=[],
        description=None,
        var_decls=[],
        requires=[],
        ensures=[],
        body=nested_call,
    )
    spec = Specification(declarations=[g, f])
    unused = find_unused_defs(spec)
    assert set(d.name for d in unused) == {"f"}
