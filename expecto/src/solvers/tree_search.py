from __future__ import annotations

import asyncio
import copy
import inspect
import json
import logging
import re
from dataclasses import replace
from textwrap import dedent, indent
from typing import TYPE_CHECKING, Any, Callable, Optional

from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageUser,
    Model,
    get_model,
)
from inspect_ai.solver import Generate, Solver, TaskState, solver

from src.DSL.ast_traverse import ASTTransformer
from src.DSL.ast_unparse import unparse
from src.DSL.compiler import DSLCompiler
from src.DSL.dsl_ast import Def, Specification
from src.DSL.reference_collector import ReferenceCollector
from src.prompts.prompt import dsl_sys_prompt, refinement_prompt
from src.utils.dsl import Tree
from src.utils.dsl import template_generation as dsl_template_generation
from src.utils.embedding import Embedding
from src.utils.monad import Err, Ok, Result
from src.utils.sat_check import sat_check, sat_check_examples

if TYPE_CHECKING:
    from .multigen import LatencyBreakdown

logger = logging.getLogger(__name__)

Defs = tuple[list[Def], list[Def]]


def _log(
    result: Result[Defs, str],
    response: str,
    combined: Result[Specification, str],
):
    if result.is_ok():
        result_str = "OK"
    else:
        result_str = str(result.err())
    if combined.is_ok():
        combined_str = unparse(combined.ok())
    else:
        combined_str = "Error"
    log_str = "\n"
    log_str += "=" * 100 + "\n"
    log_str += "Result:\n" + indent(result_str, " " * 4) + "\n"
    log_str += "Response:\n" + indent(response, " " * 4) + "\n"
    log_str += "Combined:\n" + indent(combined_str, " " * 4) + "\n"
    log_str += "=" * 100 + "\n"
    logger.info(log_str)


def _extract_dsl_code(model_output: str, section_name: str) -> Result[str, str]:
    section_match = re.search(
        rf"###\s*{section_name}([\s\S]*?)(?=###|$)", model_output, re.IGNORECASE
    )

    search_space = section_match.group(1) if section_match else model_output

    fence_regex = re.compile(r"```dsl[\s\r\n]+([\s\S]+?)```", re.IGNORECASE)
    none_regex = re.compile(r"None", re.IGNORECASE)
    matches = fence_regex.findall(search_space)

    if matches:
        return Ok(matches[-1].strip())

    none_matched = none_regex.search(search_space)
    if none_matched:
        return Ok("")

    return Err(f"No dsl block is found for {section_name}")


def get_formal_def_string(model_output: str) -> Result[str, str]:
    return _extract_dsl_code(model_output, "Formal Definition")


def get_placeholder_string(model_output: str) -> Result[str, str]:
    return _extract_dsl_code(model_output, "New Placeholders").map(
        lambda s: s.replace(";", "").strip()
    )


def get_target_def(candidates: list[Def], target: Def) -> Result[Def, str]:
    for c in candidates:
        if c.name == target.name and c.get_type() == target.get_type():
            return Ok(c)
    return Err(f"Target definition {target.name} not found in candidates")


def parse(dsl_code: str) -> Result[list[Def], str]:
    if dsl_code == "None":
        return Ok([])
    try:
        ast = DSLCompiler().parse(dsl_code)
        return Ok(list(ast.declarations))
    except Exception as e:
        return Err(str(e))


def type_check(ast: Specification) -> Result[None, str]:
    errors = DSLCompiler().type_check(copy.deepcopy(ast))
    if len(errors) == 0:
        return Ok(None)
    return Err("\n".join(str(error) for error in errors))


async def _run_sat_check(
    dsl_code: str,
    *,
    ignore_timeout: bool,
) -> Result[None, str]:
    return await sat_check(dsl_code, ignore_timeout=ignore_timeout)


def remove_dup_defs(defs: list[Def]) -> list[Def]:
    signature_set = {}
    filtered = []
    for d in defs:
        if d.get_signature() not in signature_set:
            signature_set[d.get_signature()] = d
            filtered.append(d)
    return filtered


def filter_unused_defs(
    formal_defs: list[Def],
    placeholders: list[Def],
    entry_point: str = "spec",
) -> Defs:
    """
    Remove unused definitions starts from the entry point.
    """
    # Single definition per name assumption
    name_to_def: dict[str, Def] = {}
    for d in [*formal_defs, *placeholders]:
        if d.name not in name_to_def:
            name_to_def[d.name] = d

    worklist: set[str] = {entry_point}
    reachable: set[str] = {entry_point}
    defined_functions = set(name_to_def.keys())

    while worklist:
        current_name = worklist.pop()
        d = name_to_def.get(current_name)
        if d is None:
            continue
        collector = ReferenceCollector(defined_functions)
        for ref in collector.collect(d):
            if ref not in reachable:
                worklist.add(ref)
                reachable.add(ref)

    filtered_formals = [d for d in formal_defs if d.name in reachable]
    filtered_placeholders = [d for d in placeholders if d.name in reachable]

    return filtered_formals, filtered_placeholders


def remove_defined_defs(a: list[Def], b: list[Def]) -> list[Def]:
    """
    Filter out definitions in b that are already defined in a.
    """
    a_sig = {d.get_signature() for d in a}

    filtered_b = [d for d in b if d.get_signature() not in a_sig]
    return filtered_b


def get_new_defs(old_defs: Defs, expanded: Defs) -> Defs:
    old_formal_defs, old_placeholders = old_defs
    new_formal_defs, new_placeholders = expanded

    old_names = {d.name for d in old_formal_defs} | {d.name for d in old_placeholders}

    new_formal_defs = remove_dup_defs(old_formal_defs + new_formal_defs)
    new_placeholders = remove_dup_defs(new_placeholders + old_placeholders)
    new_placeholders = remove_defined_defs(new_formal_defs, new_placeholders)

    new_names = {d.name for d in new_formal_defs} | {d.name for d in new_placeholders}

    assert old_names.issubset(new_names), "Old names must be a subset of new names"

    return new_formal_defs, new_placeholders


async def check_well_formed(
    test_cases: list[tuple[str, str]] | list[dict],
    prev_formal_defs: list[Def],
    prev_placeholders: list[Def],
    target: Def,
    response: str,
    *,
    function_signature: str,
    parser_code: Optional[str],
    timing_accumulator: LatencyBreakdown | None = None,
    check_unsat: bool = True,
    **kwargs,
) -> Result[Defs, str]:
    loop = asyncio.get_event_loop()
    placeholders_str = get_placeholder_string(response)
    placeholders = placeholders_str.and_then(parse)

    formal_def_str = get_formal_def_string(response)
    formal_def = formal_def_str.and_then(parse)

    def find_target(defs: list[Def]) -> Result[list[Def], str]:
        for d in defs:
            if d.name == target.name and d.get_type() == target.get_type():
                return Ok(defs)
            elif d.name == target.name and d.get_type() != target.get_type():
                return Err(
                    f"Target definition {target.name} has different type. Original type: {target.get_type()}, New type: {d.get_type()}"
                )
        return Err(f"Target definition {target.name} not found in candidates")

    new_defs = formal_def.and_then(find_target).and_then(
        lambda defs: placeholders.map(
            lambda ph: get_new_defs((prev_formal_defs, prev_placeholders), (defs, ph))
        )
    )

    combined = new_defs.map(lambda defs: Specification(declarations=defs[0] + defs[1]))

    async def _check_examples(spec: Specification) -> Result[None, str]:
        dsl_code = unparse(spec)
        return await sat_check_examples(
            dsl_code=dsl_code,
            parser_code=parser_code,
            function_signature=function_signature,
            test_cases=test_cases,
            **kwargs,
        )

    if combined.is_ok():
        spec = combined.ok()
        start_t = loop.time()
        if len(test_cases) == 0:
            if check_unsat:
                check_result = await _run_sat_check(
                    unparse(spec),
                    ignore_timeout=True,
                )
            else:
                check_result = Ok(None)
        else:
            check_result = await _check_examples(spec)
        if timing_accumulator is not None:
            timing_accumulator.add_z3(loop.time() - start_t)
    else:
        check_result = Err(combined.err())

    result = check_result.and_then(lambda _: new_defs)
    _log(result, response, combined)
    return result


class State:
    def __init__(
        self,
        defined: list[Def],
        undefined: list[Def],
    ):
        defined, undefined = filter_unused_defs(defined, undefined)
        self.defined = defined
        self.undefined = undefined

        logger.info(f"[State]\n{self}")

    async def well_defined(self) -> Result[None, str]:
        spec = Specification(declarations=self.defined + self.undefined)
        return await _run_sat_check(
            unparse(spec),
            ignore_timeout=True,
        )

    def is_grounded(self) -> bool:
        return len(self.undefined) == 0

    def __str__(self) -> str:
        defined_unparsed = [unparse(d) for d in self.defined]
        undefined_unparsed = [unparse(d) for d in self.undefined]

        result = ""

        result += "/* Define */\n"
        for d in defined_unparsed:
            result += f"{d}\n\n"
        result += "\n\n"
        result += "/* Placeholder */\n"
        for d in undefined_unparsed:
            result += f"{d}\n\n"
        return result

    def __dict__(self):
        return {
            "defined": [unparse(d) for d in self.defined],
            "undefined": [unparse(d) for d in self.undefined],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "State":
        return cls(
            [parse(d).ok()[0] for d in data["defined"]],
            [parse(d).ok()[0] for d in data["undefined"]],
        )


class Node:
    def __init__(
        self,
        parent: Optional["Node"],
        state: State,
        *,
        function_signature: str,
        parser_code: Optional[str] = None,
        **kwargs,
    ):
        self.parent = parent
        self.state = state
        self.children = []
        self.function_signature = function_signature
        self.parser_code = parser_code
        self.kwargs = kwargs

    async def create_children(
        self,
        expand_result: Result[Defs, str],
        prev_formal_defs: list[Def],
        prev_placeholders: list[Def],
        *,
        check_well_defined=False,
    ):
        if expand_result.is_err():
            return

        new_formal_defs, new_placeholders = get_new_defs(
            (prev_formal_defs, prev_placeholders), expand_result.ok()
        )

        new_state = State(
            new_formal_defs,
            new_placeholders,
        )
        new_node = Node(
            self,
            new_state,
            function_signature=self.function_signature,
            parser_code=self.parser_code,
            **self.kwargs,
        )

        if check_well_defined:
            well_defined = await new_node.state.well_defined()
            if well_defined.is_err():
                return

        self.children.append(new_node)

    async def expand(
        self,
        target_idx: int,
        model: Model,
        patient: int,
        n_completions: int,
        test_cases: list[tuple[str, str]] | list[dict],
        root_spec: str,
        memo: "Memo",
        use_memo: bool = True,
        timing_reports: list[dict[str, Any]] | None = None,
        track_memo_hit: Optional[Callable[[], None]] = None,
        track_memo_miss: Optional[Callable[[], None]] = None,
    ):
        if not (0 <= target_idx < len(self.state.undefined)):
            return

        if len(self.state.undefined) == 0:
            return

        target = self.state.undefined[target_idx]

        if use_memo:
            memo_candidates = memo.lookup(target)
            if memo_candidates is not None:
                if track_memo_hit:
                    track_memo_hit()
                for orig_name, pair in memo_candidates:
                    if orig_name and orig_name != target.name:
                        pair = rename_pair(pair, orig_name, target.name)
                    await self.create_children(
                        Ok(pair),
                        prev_formal_defs=self.state.defined,
                        prev_placeholders=self.state.undefined,
                        check_well_defined=True,
                    )
                return

            if track_memo_miss:
                track_memo_miss()

        async def checker(
            response: str,
            *,
            timing_accumulator: LatencyBreakdown | None = None,
            **kwargs: Any,
        ) -> Result[None, str]:
            output = await check_well_formed(
                test_cases=test_cases,
                prev_formal_defs=self.state.defined,
                prev_placeholders=self.state.undefined,
                target=target,
                response=response,
                function_signature=self.function_signature,
                parser_code=self.parser_code,
                timing_accumulator=timing_accumulator,
                **self.kwargs,
                **kwargs,
            )

            return output.map(lambda _: None)

        async def postprocess(response: str) -> Result[Defs, str]:
            placeholders_str = get_placeholder_string(response)
            placeholders = placeholders_str.and_then(parse)

            formal_def_str = get_formal_def_string(response)
            formal_defs = formal_def_str.and_then(parse)
            return placeholders.and_then(
                lambda ph: formal_defs.map(lambda fd: (fd, ph))
            )

        description = target.description
        assert description is not None
        description_content = description.content
        signature = unparse(target)

        prompt = refinement_prompt.format(
            original_nl_spec=root_spec,
            existing_definitions="\n".join([unparse(d) for d in self.state.defined]),
            existing_informally_defined_predicates_functions="\n".join(
                [unparse(p) for p in self.state.undefined]
            ),
            target_informally_defined_predicate_function_signature=signature,
            target_natural_language_description=description_content,
        )

        messages: list[ChatMessage] = [
            ChatMessageSystem(content=dsl_sys_prompt),
            ChatMessageUser(
                content=prompt,
            ),
        ]

        from .multigen import MultiGen

        mg = MultiGen(
            model=model,
            n_completions=n_completions,
            n_attempts=patient,
            checkers=[checker],
            baseline_messages=messages,
            postprocess=postprocess,
        )

        outputs = await mg.generate()
        for sample_idx, (meta, output) in enumerate(outputs):
            if timing_reports is not None:
                breakdown = meta.latency_breakdown
                timing_reports.append(
                    {
                        "target_name": target.name,
                        "target_signature": signature,
                        "sample_index": sample_idx,
                        "status": meta.status.value if meta.status else None,
                        "postprocess_status": "ok" if output.is_ok() else "err",
                        "num_feedback_iterations": meta.num_feedback_iterations,
                        **breakdown.as_dict(),
                    }
                )
        tasks = [
            self.create_children(
                output,
                prev_formal_defs=self.state.defined,
                prev_placeholders=self.state.undefined,
            )
            for _, output in outputs
        ]
        await asyncio.gather(*tasks)
        if use_memo:
            for _, output in outputs:
                output.map(
                    lambda o: memo.add(target, [o], description=description_content)
                )

        # If all outputs are errors, add an empty result to memo
        # This logic prevent retry for the same target again and again.
        # if all(o.is_err() for _, o in outputs):
        #     memo.add(target, [], description=description_content)

    def is_grounded(self) -> bool:
        if self.state.is_grounded():
            return True
        return False

    def __str__(self) -> str:
        curr_state = str(self.state)
        children_str = "\n".join([indent(str(c), " " * 4) for c in self.children])
        return f"{curr_state}\n\n{children_str}"

    def __dict__(self) -> dict:
        return {
            "function_signature": self.function_signature,
            "parser_code": self.parser_code,
            "state": self.state.__dict__(),
            "children": [c.__dict__() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict, parent: Optional["Node"] = None) -> "Node":
        node = cls(
            parent,
            State.from_dict(data["state"]),
            function_signature=data["function_signature"],
            parser_code=data["parser_code"],
        )
        children = [cls.from_dict(c, node) for c in data["children"]]
        node.children = children
        return node


class Memo:
    def __init__(
        self, similarity_threshold: float = 0.95, embedding: Optional[Embedding] = None
    ):
        self.similarity_threshold = similarity_threshold
        self.embedding = embedding or Embedding()
        # Records grouped by type signature for faster lookup
        # { type_sig: [(description_text, orig_target_name, results), ...] }
        self._records_by_type: dict[str, list[tuple[str, str, list[Defs]]]] = {}

    def add(
        self,
        target: Def,
        results: list[Defs],
        *,
        description: str,
    ) -> None:
        type_sig = str(target.get_type())

        def _pick_orig_name(pairs: list[Defs]) -> str:
            # Prefer formal defs; fall back to placeholders; else use current target name
            for formals, _ in pairs:
                for d in formals:
                    try:
                        if d.get_type() == target.get_type():
                            return d.name
                    except Exception:
                        continue
            for _, placeholders in pairs:
                for d in placeholders:
                    try:
                        if d.get_type() == target.get_type():
                            return d.name
                    except Exception:
                        continue
            return target.name

        orig_name = _pick_orig_name(results)
        bucket = self._records_by_type.setdefault(type_sig, [])
        bucket.append((description, orig_name, list(results)))

    def lookup(self, target: Def) -> Optional[list[tuple[str, Defs]]]:
        type_sig = str(target.get_type())
        query_desc = (
            target.description.content if target.description is not None else ""
        )
        if not query_desc:
            return None

        candidates = self._records_by_type.get(type_sig)
        if not candidates:
            return None

        best_match: Optional[tuple[str, list[Defs]]] = None
        best_score = 0.0
        for rec_desc, rec_orig_name, rec_results in candidates:
            if query_desc.strip() == rec_desc.strip():
                score = 1.0
            else:
                try:
                    score = self.embedding.cosine_similarity(query_desc, rec_desc)
                except Exception:
                    # If embedding fails, skip memoization gracefully.
                    score = 0.0
            if score >= self.similarity_threshold and score > best_score:
                best_score = score
                best_match = (rec_orig_name, rec_results)
        if best_match is None:
            return None

        rec_orig_name, rec_results = best_match
        logger.info(
            f"Found previous definition for {target.name} with score {best_score}"
        )
        return [(rec_orig_name, pair) for pair in rec_results]


# Bound-name aware renamer for definitions and free references
class _DefRenamer(ASTTransformer):
    def __init__(self, old_name: str, new_name: str):
        self._old = old_name
        self._new = new_name
        self._stack: list[set[str]] = [set()]

    def _push(self, names: list[str]) -> None:
        current = set(self._stack[-1])
        for n in names:
            current.add(n)
        self._stack.append(current)

    def _pop(self) -> None:
        self._stack.pop()

    def _is_bound(self, name: str) -> bool:
        return name in self._stack[-1]

    def visit_Identifier(self, node):  # type: ignore[override]
        name = getattr(node, "name", None)
        if isinstance(name, str) and name == self._old and not self._is_bound(name):
            return replace(node, name=self._new)
        return node

    def visit_LambdaExpr(self, node):  # type: ignore[override]
        self._push([a.name for a in node.args])
        try:
            body = self.transform(node.body)
            return replace(node, body=body)
        finally:
            self._pop()

    def visit_ForallExpr(self, node):  # type: ignore[override]
        self._push([v.name for v in node.vars])
        try:
            body = self.transform(node.satisfies_expr)
            return replace(node, satisfies_expr=body)
        finally:
            self._pop()

    def visit_ExistsExpr(self, node):  # type: ignore[override]
        self._push([v.name for v in node.vars])
        try:
            body = self.transform(node.satisfies_expr)
            return replace(node, satisfies_expr=body)
        finally:
            self._pop()

    def visit_FunctionDef(self, node):  # type: ignore[override]
        bound = (
            [a.name for a in node.args]
            + [node.return_val.name]
            + [v.var.name for v in node.var_decls]
        )
        self._push(bound)
        try:
            var_decls = [
                replace(vd, expr=self.transform(vd.expr)) for vd in node.var_decls
            ]
            requires = [self.transform(r) for r in node.requires]
            ensures = [self.transform(e) for e in node.ensures]
            body = self.transform(node.body) if node.body is not None else None
        finally:
            self._pop()
        new_name = self._new if node.name == self._old else node.name
        return replace(
            node,
            name=new_name,
            var_decls=var_decls,
            requires=requires,
            ensures=ensures,
            body=body,
        )

    def visit_PredicateDef(self, node):  # type: ignore[override]
        bound = [a.name for a in node.args] + [v.var.name for v in node.var_decls]
        self._push(bound)
        try:
            var_decls = [
                replace(vd, expr=self.transform(vd.expr)) for vd in node.var_decls
            ]
            body = self.transform(node.body) if node.body is not None else None
        finally:
            self._pop()
        new_name = self._new if node.name == self._old else node.name
        return replace(node, name=new_name, var_decls=var_decls, body=body)


def rename_pair(pair: Defs, old_name: str, new_name: str) -> Defs:
    if old_name == new_name:
        return pair
    renamer = _DefRenamer(old_name, new_name)
    formals, placeholders = pair
    return (
        [renamer.transform(d) for d in formals],
        [renamer.transform(d) for d in placeholders],
    )


class TreeSearch:
    def __init__(
        self,
        model: Model,
        patient: int,
        n_completions: int,
        max_iteration: int,
        test_cases: list[tuple[str, str]] | list[dict],
        root_spec: str,
        root_node: "Node",
        *,
        use_memo: bool = True,
    ):
        self.model = model
        self.patient = patient
        self.n_completions = n_completions
        self.max_iteration = max_iteration
        self.test_cases = test_cases
        self.root_spec = root_spec
        self.root_node = root_node
        self.generated_history = Memo()
        self.use_memo = use_memo
        self.sample_latency_reports: list[dict[str, Any]] = []
        self.memo_hits = 0
        self.memo_misses = 0
        self.metadata = {
            "iteration": 0,
            "num_of_nodes": 1,
            "latency_reports": self.sample_latency_reports,
        }

    def track_memo_hit(self) -> None:
        self.memo_hits += 1

    def track_memo_miss(self) -> None:
        self.memo_misses += 1

    async def run(self) -> tuple[dict, Node]:
        stack = [self.root_node]
        while stack:
            if self.metadata["iteration"] >= self.max_iteration:
                break
            curr_node = stack.pop(-1)  # DFS
            self.metadata["iteration"] += 1

            if curr_node.is_grounded():
                return self.metadata, curr_node
            undef_length = len(curr_node.state.undefined)
            for target_idx in range(undef_length):
                await curr_node.expand(
                    target_idx=target_idx,
                    model=self.model,
                    patient=self.patient,
                    n_completions=self.n_completions,
                    root_spec=self.root_spec,
                    memo=self.generated_history,
                    use_memo=self.use_memo,
                    test_cases=self.test_cases,
                    timing_reports=self.sample_latency_reports,
                    track_memo_hit=self.track_memo_hit,
                    track_memo_miss=self.track_memo_miss,
                )
                if len(curr_node.children) > 0:
                    break
            stack.extend(sorted(curr_node.children, key=self.leaves_order))
            self.metadata["num_of_nodes"] += len(curr_node.children)

        return self.pick_best_leaf()

    def leaves_order(self, n: Node):
        return (len(n.state.defined), -len(n.state.undefined))

    def pick_best_leaf(self) -> tuple[dict, Node]:
        leaves: list[Node] = []
        stack: list[Node] = [self.root_node]
        while stack:
            node = stack.pop()
            if len(node.children) == 0:
                leaves.append(node)
            else:
                stack.extend(node.children)
        assert len(leaves) > 0, "Leaves cannot be empty"
        best_leaf = max(leaves, key=self.leaves_order)
        return self.metadata, best_leaf


def generate_nl_spec(input_str: str, input_parser: Optional[str]) -> str:
    prompt = input_str
    if input_parser:
        prompt = dedent(f"""
        {prompt}
        ===
        ### Parser
        This is the parser for parsing the input string and output string described at the above section.
        When it is impossible for any input to satisfy the given conditions, the parser implementation may return values such as -1 or 0.
        Please keep this in mind when writing the specification.
        ```python
        {input_parser}
        ```
        """)
    return prompt


@solver(name="tree_search")
def tree_search(
    model: str | None = None,
    max_attempts: int = 5,
    n_completions: int = 1,
    use_test_cases: bool = True,
    use_memo: bool = True,
    check_unsat: bool = True,
    *args,
    **kwargs,
) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.messages.clear()
        state.output.completion = ""
        assert isinstance(state.input, str), "Input must be a string"
        model_obj = get_model(model)
        spec_description = Tree(
            "This is the formal specification (pre/post-conditions) on input and output pair generated from the given natural language specification",
        )
        template_code = dsl_template_generation(
            state.metadata["signature"], spec_description
        )
        input_parser = state.metadata.get("parser", None)
        if not input_parser:
            input_parser = None
        root_spec = generate_nl_spec(state.input, input_parser)

        parsed_template_code = parse(template_code)
        if parsed_template_code.is_err():
            return state
        template_code = parsed_template_code.ok()[0]

        ts = TreeSearch(
            model=model_obj,
            patient=max_attempts,
            n_completions=n_completions,
            max_iteration=10,
            test_cases=state.metadata["prompt_test_list"] if use_test_cases else [],
            root_spec=root_spec,
            use_memo=use_memo,
            root_node=Node(
                None,
                State([], [template_code]),
                function_signature=state.metadata["signature"],
                parser_code=input_parser,
                check_unsat=check_unsat,
            ),
        )
        try:
            metadata, final_node = await asyncio.wait_for(
                asyncio.create_task(ts.run()), timeout=60 * 60
            )
        except asyncio.TimeoutError:
            metadata, final_node = ts.pick_best_leaf()
        root = ts.root_node

        if metadata is None:
            return state
        spec = Specification(
            declarations=final_node.state.defined + final_node.state.undefined
        )
        code = unparse(spec)
        metadata["generated_codes"] = [code]
        metadata["is_success"] = len(final_node.state.undefined) == 0
        metadata["num_of_defined"] = len(final_node.state.defined)
        metadata["num_of_undefined"] = len(final_node.state.undefined)
        metadata["tree"] = root.__dict__()
        latency_reports: list[dict[str, Any]] = metadata.get("latency_reports", [])
        if latency_reports:
            metadata["latency_summary"] = {
                "total_sec": sum(
                    entry.get("total_sec", 0.0) for entry in latency_reports
                ),
                "llm_response_latency_sec": sum(
                    entry.get("llm_response_latency_sec", 0.0)
                    for entry in latency_reports
                ),
                "z3_sat_solver_latency_sec": sum(
                    entry.get("z3_sat_solver_latency_sec", 0.0)
                    for entry in latency_reports
                ),
                "other_latency_sec": sum(
                    entry.get("other_latency_sec", 0.0) for entry in latency_reports
                ),
            }
        else:
            metadata["latency_summary"] = {
                "total_sec": 0.0,
                "llm_response_latency_sec": 0.0,
                "z3_sat_solver_latency_sec": 0.0,
                "other_latency_sec": 0.0,
            }
        total_memo_lookups = ts.memo_hits + ts.memo_misses
        metadata["memo_hits"] = ts.memo_hits
        metadata["memo_misses"] = ts.memo_misses
        metadata["memo_cache_hit_ratio"] = (
            ts.memo_hits / total_memo_lookups if total_memo_lookups > 0 else 0.0
        )
        state.output.completion = json.dumps(metadata, indent=4)
        return state

    return solve
