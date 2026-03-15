from typing import Any, Callable, Coroutine, Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E")
U = TypeVar("U")
F = TypeVar("F")


class Result(Generic[T, E]):
    """Result monad representing a success (Ok) or failure (Err)."""

    def is_ok(self) -> bool:
        raise NotImplementedError

    def is_err(self) -> bool:
        raise NotImplementedError

    def ok(self) -> T:
        raise NotImplementedError

    def err(self) -> E:
        raise NotImplementedError

    def map(self, func: Callable[[T], U]) -> "Result[U, E]":
        raise NotImplementedError

    def map_err(self, func: Callable[[E], F]) -> "Result[T, F]":
        raise NotImplementedError

    def and_then(self, func: Callable[[T], "Result[U, E]"]) -> "Result[U, E]":
        raise NotImplementedError

    async def async_map(
        self, func: Callable[[T], Coroutine[Any, Any, U]]
    ) -> "Result[U, E]":
        raise NotImplementedError

    async def async_and_then(
        self, func: Callable[[T], Coroutine[Any, Any, "Result[U, E]"]]
    ) -> "Result[U, E]":
        raise NotImplementedError


class Ok(Result[T, E]):
    """Represents a successful result."""

    def __init__(self, value: T):
        self._value = value

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False

    def ok(self) -> T:
        return self._value

    def err(self):
        raise ValueError("This is not an Err")

    def map(self, func: Callable[[T], U]) -> "Result[U, E]":
        return Ok(func(self._value))

    def map_err(self, func: Callable[[E], F]) -> "Result[T, F]":
        return Ok(self._value)

    def and_then(self, func: Callable[[T], "Result[U, E]"]) -> "Result[U, E]":
        return func(self._value)

    async def async_map(
        self, func: Callable[[T], Coroutine[Any, Any, U]]
    ) -> "Result[U, E]":
        return Ok(await func(self._value))

    async def async_and_then(
        self, func: Callable[[T], Coroutine[Any, Any, "Result[U, E]"]]
    ) -> "Result[U, E]":
        return await func(self._value)

    def __repr__(self) -> str:
        return f"Ok({self._value!r})"

    def __str__(self) -> str:
        return f"Ok({self._value!s})"


class Err(Result[T, E]):
    """Represents a failed result."""

    def __init__(self, error: E):
        self._error = error

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True

    def ok(self):
        raise ValueError("This is not an Ok")

    def err(self) -> E:
        return self._error

    def map(self, func: Callable[[T], U]) -> "Result[U, E]":
        return Err(self._error)

    def map_err(self, func: Callable[[E], F]) -> "Result[T, F]":
        return Err(func(self._error))

    def and_then(self, func: Callable[[T], "Result[U, E]"]) -> "Result[U, E]":
        return Err(self._error)

    async def async_map(
        self, func: Callable[[T], Coroutine[Any, Any, U]]
    ) -> "Result[U, E]":
        return Err(self._error)

    async def async_and_then(
        self, func: Callable[[T], Coroutine[Any, Any, "Result[U, E]"]]
    ) -> "Result[U, E]":
        return Err(self._error)

    def __repr__(self) -> str:
        return f"Err({self._error!r})"

    def __str__(self) -> str:
        return f"Err({self._error!s})"
