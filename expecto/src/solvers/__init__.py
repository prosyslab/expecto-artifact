from typing import Callable, Dict

from inspect_ai.agent import Agent
from inspect_ai.solver import Solver

from .defects4j_tree_search import defects4j_tree_search
from .non_agentic import (
    monolithic,
)
from .tree_search import tree_search

solver_map: Dict[str, Callable[..., Solver | Agent]] = {
    "monolithic": monolithic,
    "tree_search": tree_search,
    "defects4j_tree_search": defects4j_tree_search,
}
