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

# The report is the run's only user-visible product. `node_reduction`
# improving a summary that will never be assembled is worthless, yet it
# drew first from the shared floor and starved assembly in every recorded
# run -- `reduce_tree` calls `reduce_node` once per node and nothing caps
# that count. `REPORT_STAGES` is the inner tier reduction cannot reach.
REPORT_STAGES = frozenset({
    "report_assembly",
    "report_grading",
})

# Stages that run after investigation is over: hierarchical reduction plus
# everything in REPORT_STAGES. They are the only callers allowed to draw on
# the reserved floor.
#
# The budget layer knowing stage names is a deliberate coupling. Threading an
# `is_finalization` flag from each call site through call_llm / call_json /
# call_messages / _budgeted_dispatch would touch every caller; one constant is
# explicit, testable, and lives in a single place.
FINALIZATION_STAGES = frozenset({
    "node_reduction",
    *REPORT_STAGES,
})


class TokenBudgetExhausted(RuntimeError):
    """Raised when no output token can be reserved within the hard cap.

    Carries *why*. `reserve` refuses for two different reasons and used to
    throw the same bare exception for both, so every consumer had to guess:
    `_mark_stop_reason` guessed "neither" and logged nothing at all (G10),
    and the synthesizer guessed "token_budget_exhausted" and wrote it into
    the ledger even when the budget had headroom left. The refusal site is
    the only place that knows which of the two happened -- the budget's own
    state afterwards looks identical for the second case. This is how it
    says so.

    Every field defaults, so `TokenBudgetExhausted("cap")` stays valid; the
    default `cause` is the reading the bare exception always carried.
    """

    def __init__(
        self,
        message: str = "deep-analysis token budget exhausted",
        *,
        cause: str = "tier_floor",
        stage: str = "",
        model: str = "",
        input_bound: int = 0,
        ceiling: int = 0,
        requested: int = 0,
        granted: int = 0,
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.stage = stage
        self.model = model
        self.input_bound = input_bound
        self.ceiling = ceiling
        self.requested = requested
        self.granted = granted


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
        floor_tokens: int = 0,
        report_floor_tokens: int = 0,
        min_viable_output_tokens: int = 1,
    ) -> None:
        if cap_tokens < 0 or consumed_tokens < 0:
            raise ValueError("token counts must be non-negative")
        if floor_tokens < 0:
            raise ValueError("floor_tokens must be non-negative")
        if report_floor_tokens < 0:
            raise ValueError("report_floor_tokens must be non-negative")
        if report_floor_tokens > floor_tokens:
            raise ValueError(
                "report_floor_tokens must not exceed floor_tokens"
            )
        if min_viable_output_tokens < 1:
            raise ValueError("min_viable_output_tokens must be positive")
        recovered = dict(outstanding or {})
        if any(amount < 0 for amount in recovered.values()):
            raise ValueError("outstanding token counts must be non-negative")
        self.cap_tokens = cap_tokens
        self._consumed_tokens = consumed_tokens
        self._outstanding = recovered
        self._persist = persist
        self.floor_tokens = floor_tokens
        self.report_floor_tokens = report_floor_tokens
        self.min_viable_output_tokens = min_viable_output_tokens
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
    def available_for_investigation(self) -> int:
        """Remaining tokens that non-finalization stages may reserve.

        The floor is what stops the investigation loop from consuming the
        whole cap and leaving report assembly and grading to fail open --
        which is what every recorded run did before this existed.
        """
        return max(0, self.remaining_tokens - self.floor_tokens)

    @property
    def available_for_reduction(self) -> int:
        """Remaining tokens `node_reduction` may reserve.

        Isolating the report's tier enforces the reduction allowance
        without a call counter. `finalization_reduction_allowance` sizes
        the floor but never limited how many times `reduce_node` runs;
        reductions past the allowance now degrade through the path they
        already have (synthesizer.py) instead of eating the assembly's
        reservation.
        """
        return max(0, self.remaining_tokens - self.report_floor_tokens)

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
            if stage in REPORT_STAGES:
                ceiling = self.remaining_tokens
            elif stage in FINALIZATION_STAGES:
                ceiling = self.available_for_reduction
            else:
                ceiling = self.available_for_investigation
            output_tokens = min(max_output_tokens, ceiling - input_bound)
            # A grant of >= 1 token used to count as a successful reservation.
            # It is not: a 25-token grant for a JSON prompt truncates with
            # certainty, and (since truncation became a hard error) takes the
            # whole run down with it -- 5 of 5 dev runs died this way on
            # 2026-08-04. Refuse the doomed call instead. `run` already
            # catches TokenBudgetExhausted around the investigation loop and
            # falls through to `_finalize`, so refusing here ends the
            # investigation cleanly and lets the floor be spent on the report.
            #
            # Clamped by the caller's own request so a deliberately small
            # `max_output_tokens` stays legal: the threshold exists to catch
            # budget-starved grants, not modest ones.
            viability = min(max_output_tokens, self.min_viable_output_tokens)
            if output_tokens < viability:
                # `ceiling > 0` separates the two refusals: the tier is
                # empty, or the tier has room and this prompt does not fit
                # in it. Nothing downstream can recover the distinction --
                # both raise from here, and for the second case the budget
                # still reads as having headroom, which is exactly why that
                # stop went unrecorded (G10).
                raise TokenBudgetExhausted(
                    "deep-analysis token budget exhausted",
                    cause="input_bound" if ceiling > 0 else "tier_floor",
                    stage=stage,
                    model=model,
                    input_bound=input_bound,
                    ceiling=ceiling,
                    requested=max_output_tokens,
                    granted=output_tokens,
                )

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

    async def record_truncation_handled(
        self,
        *,
        stage: str,
        model: str,
        requested: int,
        granted: int,
        action: str,
    ) -> None:
        """Record what was done about a truncated response.

        `llm_truncated` says a response was cut; this says whether the cut
        was recoverable. Without it, a run that produced no discards cannot
        be told apart from one whose filter never ran -- which is exactly
        what left the discard-recall measurement inconclusive twice.

        This is written once per truncated `call_json` invocation, not once
        per truncated provider response -- `llm_truncated` fires on every
        attempt that hits its ceiling, but a "retried_failed" outcome means
        *two* attempts truncated (the original and the expanded retry) for
        one of these. Only "retried_ok" and "budget_bound" are 1:1 with
        `llm_truncated`. After-the-fact aggregation must join on `action` to
        get the count right, not assume a flat 1:1 pairing.

        `requested` is always the original ceiling of the call; `granted` is
        the allowance of the *final* attempt (the expanded one, if a retry
        ran). On a "retried_failed" outcome `granted` can therefore exceed
        `requested` -- that reflects the expanded ceiling, not a bug.

        Payload carries counts and identifiers only — never response text.
        """
        async with self._lock:
            await self._persist_event(
                "truncation_handled",
                {
                    "stage": stage,
                    "model": model,
                    "requested": requested,
                    "granted": granted,
                    "action": action,
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
