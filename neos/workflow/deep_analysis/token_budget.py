"""Run-scoped hard token budgeting for deep-analysis LLM calls."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


PersistEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


class TokenBudgetExhausted(RuntimeError):
    """Raised when no output token can be reserved within the hard cap."""


class TokenBudgetContractError(RuntimeError):
    """Raised when a caller violates the reservation contract."""


@dataclass(frozen=True, slots=True)
class TokenReservation:
    id: str
    reserved_tokens: int
    input_bound: int
    max_output_tokens: int
    stage: str
    model: str


def conservative_input_bound(request: Any) -> int:
    """Return a stable, conservative token bound for a serializable request."""

    encoded = json.dumps(
        request,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return len(encoded) + 64


class TokenBudget:
    """Atomically reserves a run's finite token capacity before dispatch."""

    def __init__(
        self,
        cap_tokens: int,
        *,
        consumed_tokens: int = 0,
        outstanding: Mapping[str, int] | None = None,
        persist: PersistEvent | None = None,
    ) -> None:
        if cap_tokens < 0 or consumed_tokens < 0:
            raise ValueError("token counts must be non-negative")
        recovered = dict(outstanding or {})
        if any(amount < 0 for amount in recovered.values()):
            raise ValueError("outstanding token counts must be non-negative")
        self.cap_tokens = cap_tokens
        self._consumed_tokens = consumed_tokens
        self._outstanding = recovered
        self._persist = persist
        self._lock = asyncio.Lock()

    @property
    def consumed_tokens(self) -> int:
        return self._consumed_tokens

    @property
    def reserved_tokens(self) -> int:
        return sum(self._outstanding.values())

    @property
    def remaining_tokens(self) -> int:
        return self.cap_tokens - self.consumed_tokens - self.reserved_tokens

    @property
    def exhausted(self) -> bool:
        return self.remaining_tokens <= 0

    async def reserve(
        self,
        request: Any,
        max_output_tokens: int,
        *,
        stage: str,
        model: str,
    ) -> TokenReservation:
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")

        input_bound = conservative_input_bound(request)
        async with self._lock:
            output_tokens = min(
                max_output_tokens,
                self.remaining_tokens - input_bound,
            )
            if output_tokens < 1:
                raise TokenBudgetExhausted("deep-analysis token budget exhausted")

            reservation = TokenReservation(
                id=uuid4().hex,
                reserved_tokens=input_bound + output_tokens,
                input_bound=input_bound,
                max_output_tokens=output_tokens,
                stage=stage,
                model=model,
            )
            await self._persist_event(
                "token_budget_reserved",
                {
                    "reservation_id": reservation.id,
                    "reserved_tokens": reservation.reserved_tokens,
                    "input_bound": reservation.input_bound,
                    "max_output_tokens": reservation.max_output_tokens,
                    "stage": reservation.stage,
                    "model": reservation.model,
                },
            )
            self._outstanding[reservation.id] = reservation.reserved_tokens
            return reservation

    async def settle(
        self,
        reservation: TokenReservation,
        actual_tokens: int,
    ) -> None:
        async with self._lock:
            reserved = self._require_active(reservation)
            if actual_tokens < 0 or actual_tokens > reserved:
                raise TokenBudgetContractError(
                    "actual token usage must be within the reservation"
                )
            await self._persist_event(
                "token_budget_settled",
                {
                    "reservation_id": reservation.id,
                    "reserved_tokens": reserved,
                    "actual_tokens": actual_tokens,
                },
            )
            del self._outstanding[reservation.id]
            self._consumed_tokens += actual_tokens

    async def release(self, reservation: TokenReservation) -> None:
        """Release a reservation only when provider dispatch never occurred."""

        async with self._lock:
            reserved = self._require_active(reservation)
            await self._persist_event(
                "token_budget_released",
                {
                    "reservation_id": reservation.id,
                    "reserved_tokens": reserved,
                },
            )
            del self._outstanding[reservation.id]

    async def abandon(self, reservation: TokenReservation) -> None:
        """Keep an ambiguous post-dispatch reservation fully accounted."""

        async with self._lock:
            self._require_active(reservation)

    async def record_truncation(
        self,
        *,
        stage: str,
        model: str,
        max_output_tokens: int,
        output_tokens: int,
    ) -> None:
        """Record that a response was cut off at its output ceiling.

        A truncated response fails JSON parsing and yields nothing, so the
        work it represents is lost silently. Nothing read ``stop_reason``
        before this; a whole baseline run was spent before the loss was
        noticed, and only because a cassette happened to exist.

        Payload carries counts and identifiers only — never response text.
        """
        async with self._lock:
            await self._persist_event(
                "llm_truncated",
                {
                    "stage": stage,
                    "model": model,
                    "max_output_tokens": max_output_tokens,
                    "output_tokens": output_tokens,
                },
            )

    def _require_active(self, reservation: TokenReservation) -> int:
        try:
            reserved = self._outstanding[reservation.id]
        except KeyError as error:
            raise TokenBudgetContractError("reservation is not active") from error
        if reserved != reservation.reserved_tokens:
            raise TokenBudgetContractError("reservation amount does not match")
        return reserved

    async def _persist_event(self, kind: str, payload: dict[str, Any]) -> None:
        if self._persist is not None:
            await self._persist(kind, payload)


_ACTIVE_TOKEN_BUDGET: ContextVar[TokenBudget | None] = ContextVar(
    "deep_analysis_token_budget",
    default=None,
)


def active_token_budget() -> TokenBudget | None:
    return _ACTIVE_TOKEN_BUDGET.get()


@contextmanager
def token_budget_scope(budget: TokenBudget) -> Iterator[None]:
    token = _ACTIVE_TOKEN_BUDGET.set(budget)
    try:
        yield
    finally:
        _ACTIVE_TOKEN_BUDGET.reset(token)
