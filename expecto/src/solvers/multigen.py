from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Callable, Coroutine, List, Optional, TypeVar

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    Model,
)
from pydantic import BaseModel, Field

from src.utils.monad import Err, Ok, Result


class LatencyBreakdown(BaseModel):
    total_sec: float = 0.0
    llm_response_latency_sec: float = 0.0
    z3_sat_solver_latency_sec: float = 0.0
    other_latency_sec: float = 0.0

    def add_llm(self, duration: float) -> None:
        if duration <= 0:
            return
        self.llm_response_latency_sec += duration
        self.total_sec += duration

    def add_z3(self, duration: float) -> None:
        if duration <= 0:
            return
        self.z3_sat_solver_latency_sec += duration
        self.total_sec += duration

    def add_other(self, duration: float) -> None:
        if duration <= 0:
            return
        self.other_latency_sec += duration
        self.total_sec += duration

    def as_dict(self) -> dict[str, float]:
        return {
            "total_sec": self.total_sec,
            "llm_response_latency_sec": self.llm_response_latency_sec,
            "z3_sat_solver_latency_sec": self.z3_sat_solver_latency_sec,
            "other_latency_sec": self.other_latency_sec,
        }


class IterationEntry(BaseModel):
    assistant_response: str
    passed: bool
    feedback: Optional[str] = None
    failed_checker: Optional[str] = None
    messages_appended: list[ChatMessage] = Field(default_factory=list)
    checker_durations_sec: dict[str, float] = Field(default_factory=dict)
    ai_response_duration_sec: Optional[float] = None


class MultiGenMetadata(BaseModel):
    baseline_messages: list[ChatMessage]
    initial_response: str
    iterations: list[IterationEntry] = Field(default_factory=list)
    num_feedback_iterations: int = 0
    checkers: list[str] = Field(default_factory=list)
    final_response: Optional[str] = None
    status: Optional["Status"] = None
    error: Optional[str] = None
    final_feedback: Optional[str] = None
    failed_checker: Optional[str] = None
    initial_ai_response_duration_sec: Optional[float] = None
    final_checker_durations_sec: dict[str, float] = Field(default_factory=dict)
    postprocess_duration_sec: Optional[float] = None
    latency_breakdown: LatencyBreakdown = Field(default_factory=LatencyBreakdown)


class Status(Enum):
    OK = "ok"
    ERR = "err"


T = TypeVar("T")


class MultiGen[T]:
    def __init__(
        self,
        model: Model,
        n_completions: int,
        n_attempts: int,
        checkers: list[Callable[..., Coroutine[Any, Any, Result[None, str]]]],
        baseline_messages: List[ChatMessage],
        postprocess: Callable[[str], Coroutine[Any, Any, Result[T, str]]],
    ):
        self.model = model
        self.n_completions = n_completions
        self.n_attempts = n_attempts
        self.checkers = checkers
        self.baseline_messages = list(baseline_messages or [])
        self.postprocess = postprocess

    async def _run_checkers(
        self,
        response: str,
        *args: Any,
        latency: LatencyBreakdown | None = None,
        **kwargs: Any,
    ) -> tuple[Result[None, str], str | None, dict[str, float]]:
        durations: dict[str, float] = {}
        loop = asyncio.get_event_loop()
        for checker in self.checkers:
            checker_name = getattr(checker, "__name__", type(checker).__name__)
            start_t = loop.time()
            checker_kwargs = dict(kwargs)
            if latency is not None:
                checker_kwargs.setdefault("timing_accumulator", latency)
            pre_z3 = latency.z3_sat_solver_latency_sec if latency is not None else 0.0
            res = await checker(response, *args, **checker_kwargs)
            elapsed = loop.time() - start_t
            durations[checker_name] = elapsed
            if latency is not None:
                z3_delta = latency.z3_sat_solver_latency_sec - pre_z3
                if z3_delta > elapsed:
                    z3_delta = elapsed
                other_delta = elapsed - max(z3_delta, 0.0)
                if other_delta > 0:
                    latency.add_other(other_delta)
            if res.is_err():
                return res, checker_name, durations
        return Ok(None), None, durations

    async def _refine_one_response(
        self,
        base_messages: List[ChatMessage],
        initial_response: str,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[Result[str, str], MultiGenMetadata]:
        current = initial_response
        messages = list(base_messages)
        meta = MultiGenMetadata(
            baseline_messages=list(base_messages),
            initial_response=initial_response,
            checkers=[getattr(c, "__name__", type(c).__name__) for c in self.checkers],
        )

        latency = meta.latency_breakdown
        loop = asyncio.get_event_loop()
        sample_start = loop.time()

        def finalize_meta() -> None:
            elapsed = loop.time() - sample_start
            accounted = latency.total_sec
            residual = elapsed - accounted
            if residual > 1e-6:
                latency.add_other(residual)

        # Duration of the generation that produced the current response (None for initial)
        prev_gen_duration: Optional[float] = None

        for i in range(self.n_attempts):
            check_res, failed_checker, durations = await self._run_checkers(
                current,
                *args,
                latency=latency,
                **kwargs,
            )
            if check_res.is_ok():
                meta.final_response = current
                meta.status = Status.OK
                meta.iterations.append(
                    IterationEntry(
                        assistant_response=current,
                        passed=True,
                        checker_durations_sec=durations,
                        ai_response_duration_sec=prev_gen_duration,
                    )
                )
                finalize_meta()
                return Ok(current), meta

            feedback = check_res.err()

            meta.iterations.append(
                IterationEntry(
                    assistant_response=current,
                    feedback=feedback,
                    failed_checker=failed_checker,
                    messages_appended=[
                        ChatMessageAssistant(content=current),
                        ChatMessageUser(content=feedback),
                    ],
                    passed=False,
                    checker_durations_sec=durations,
                    ai_response_duration_sec=prev_gen_duration,
                )
            )
            meta.num_feedback_iterations += 1

            if i > 1:
                # Remove the last two messages before generating the next response
                # one is the current response, the other is the feedback
                messages = messages[:-2]

            messages.append(ChatMessageAssistant(content=current))
            messages.append(ChatMessageUser(content=feedback))

            loop = asyncio.get_event_loop()
            start_t = loop.time()
            gen = await self.model.generate(
                input=messages, config=GenerateConfig(num_choices=1)
            )
            prev_gen_duration = loop.time() - start_t
            latency.add_llm(prev_gen_duration)

            if not gen.choices:
                meta.final_response = current
                meta.status = Status.ERR
                meta.error = "Model returned no choices during refinement"
                finalize_meta()
                return Err("Model returned no choices during refinement"), meta
            generated = gen.choices[0].message.content
            if not isinstance(generated, str):
                meta.final_response = current
                meta.status = Status.ERR
                meta.error = "Non-text completion returned by the model"
                finalize_meta()
                return Err("Non-text completion returned by the model"), meta
            current = generated

        final_check, failed_checker, durations = await self._run_checkers(
            current,
            *args,
            latency=latency,
            **kwargs,
        )
        if final_check.is_ok():
            meta.final_response = current
            meta.status = Status.OK
            meta.iterations.append(
                IterationEntry(
                    assistant_response=current,
                    passed=True,
                    checker_durations_sec=durations,
                    ai_response_duration_sec=prev_gen_duration,
                )
            )
            finalize_meta()
            return Ok(current), meta
        meta.final_response = current
        meta.status = Status.ERR
        meta.final_feedback = final_check.err()
        meta.failed_checker = failed_checker
        meta.final_checker_durations_sec = durations
        finalize_meta()
        return Err(final_check.err()), meta

    async def generate(
        self,
        messages: List[ChatMessage] = [],
        *args: Any,
        **kwargs: Any,
    ) -> list[tuple[MultiGenMetadata, Result[T, str]]]:
        initial_messages = list(self.baseline_messages) + list(messages)
        loop = asyncio.get_event_loop()
        start_t = loop.time()
        initial = await self.model.generate(
            input=initial_messages,
            config=GenerateConfig(num_choices=self.n_completions),
        )
        initial_generation_duration = loop.time() - start_t
        initial_responses: list[str] = []
        for choice in initial.choices:
            content = choice.message.content
            if isinstance(content, str):
                initial_responses.append(content)

        if not initial_responses:
            return []

        if len(initial_responses) >= 2:
            tasks = [
                self._refine_one_response(initial_messages, r, *args, **kwargs)
                for r in initial_responses
            ]
            results = await asyncio.gather(*tasks)
        else:
            results = [
                await self._refine_one_response(
                    initial_messages, initial_responses[0], *args, **kwargs
                )
            ]

        pairs: list[tuple[MultiGenMetadata, Result[T, str]]] = []
        for res, meta in results:
            meta.initial_ai_response_duration_sec = initial_generation_duration
            meta.latency_breakdown.add_llm(initial_generation_duration)

            if res.is_ok():
                value = res.ok()
                pp_start = loop.time()
                post_processed_value = await self.postprocess(value)
                meta.postprocess_duration_sec = loop.time() - pp_start
                meta.latency_breakdown.add_other(meta.postprocess_duration_sec)
                pairs.append((meta, post_processed_value))
            else:
                pairs.append((meta, Err(res.err())))

        return pairs
