"""상시 에이전트의 예산 봉투 -- 트랙 Q10a (docs/Q4_Q10_TRIGGER_BUDGET_DESIGN_261001.md §3).

봉투는 **에이전트 × 달력 월(UTC)** 이다. 질문 단위 예산(`TokenBudget`, 코딩
태스크의 `max_cost_micros`) 위에 하나 더 얹힌다 -- 태스크 하나가 자기 예산 안에
있어도 에이전트가 이번 달에 쓴 합이 넘으면 봉투는 넘은 것이다.

- **지출은 따로 세지 않는다.** 루프는 매 단계 태스크의 최신 체크포인트에서 이어
  가므로 그 체크포인트의 `cost_micros` 는 태스크 전 생애의 누적이다(자식 비용도 접혀
  있다, `spawn.py`). 봉투 지출 = 이번 달에 연 에이전트 태스크들의 최신 체크포인트
  `cost_micros` 합. 카운터가 없으니 이중 계상도, 재시도 때 빠지는 것도 없다.
- 태스크는 **연 달**에 속한다. 달을 넘겨 도는 태스크의 지출은 연 달에 남는다.
- background 는 봉투의 고정 몫(`background_share`)만 쓴다. 사용자가 맡긴 autonomous
  일은 봉투 전부를 쓴다 -- `reserve_background_share` 를 켜면 그 몫을 뺀 나머지만.
  background 지출도 전체에 들어간다.
- 두 자리에서 읽는다: 새 태스크를 열 때(`open_agent_task` -- **막는다**), 진행 중
  태스크의 모델 턴 safe point(**섀도** -- `budget.judged` 만 남기고 멈추지 않는다).
  `PAUSED` 로 보내는 길은 Q5 와 함께 쓰는 별도 단계다(분석 §6 결정 3).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text

from neos.coding.domain.models import CodingTaskMode

#: 봉투를 넘었다는 사유 코드. `AgentTaskRefused.reason` 과 `budget.judged` 가 같은 값을 쓴다.
OVER_ENVELOPE = "budget_envelope_exhausted"
OVER_BACKGROUND_SHARE = "budget_background_share_exhausted"
#: background 몫을 예약했을 때(`reserve_background_share`), 사용자가 맡긴 일이 나머지를 다 썼다.
OVER_HANDED_OVER_SHARE = "budget_handed_over_share_exhausted"


@dataclass(frozen=True, slots=True)
class AgentSpend:
    """한 에이전트가 한 기간에 쓴 것(마이크로달러)."""

    total_micros: int = 0
    background_micros: int = 0


@dataclass(frozen=True, slots=True)
class EnvelopeVerdict:
    over: bool
    reason: str | None
    spent_micros: int
    limit_micros: int
    background_spent_micros: int
    background_limit_micros: int
    period_start: datetime
    reserve_background_share: bool = False

    def payload(self, *, mode: str) -> dict[str, Any]:
        """`budget.judged` 의 payload. 판정을 다시 계산할 수 있는 값을 전부 싣는다."""
        return {
            "would_pause": self.over,
            "reason": self.reason,
            "spent_micros": self.spent_micros,
            "limit_micros": self.limit_micros,
            "background_spent_micros": self.background_spent_micros,
            "background_limit_micros": self.background_limit_micros,
            "period_start": self.period_start.isoformat(),
            "reserve_background_share": self.reserve_background_share,
            "mode": mode,
            "enforced": False,
        }


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """`now` 가 속한 달력 월(UTC)의 [시작, 끝)."""
    current = now.astimezone(UTC)
    start = datetime(current.year, current.month, 1, tzinfo=UTC)
    if current.month == 12:
        return start, datetime(current.year + 1, 1, 1, tzinfo=UTC)
    return start, datetime(current.year, current.month + 1, 1, tzinfo=UTC)


def background_limit(limit_micros: int, share: float) -> int:
    """background 가 쓸 수 있는 몫. 내림이다 -- 몫이 봉투를 넘지 않게."""
    return int(limit_micros * share)


def envelope_verdict(
    spend: AgentSpend,
    *,
    limit_micros: int,
    background_share: float,
    mode: CodingTaskMode | str,
    period_start: datetime,
    reserve_background_share: bool = False,
) -> EnvelopeVerdict:
    """이 모드의 일을 더 해도 되는가. 경계에 **닿으면** 넘은 것이다 -- 남은 것이
    0 인 봉투로 여는 태스크는 첫 턴에서 넘는다.

    `reserve_background_share` 가 켜지면 background 몫은 예약이다: background 가 아닌
    일은 봉투에서 그 몫을 뺀 나머지까지만 쓴다. 꺼져 있으면 그 일은 봉투 전부를 쓴다.
    """
    share_limit = background_limit(limit_micros, background_share)
    background = CodingTaskMode(mode) is CodingTaskMode.BACKGROUND
    reason = None
    if spend.total_micros >= limit_micros:
        reason = OVER_ENVELOPE
    elif background and spend.background_micros >= share_limit:
        reason = OVER_BACKGROUND_SHARE
    elif (
        not background
        and reserve_background_share
        and spend.total_micros - spend.background_micros >= limit_micros - share_limit
    ):
        reason = OVER_HANDED_OVER_SHARE
    return EnvelopeVerdict(
        over=reason is not None,
        reason=reason,
        spent_micros=spend.total_micros,
        limit_micros=limit_micros,
        background_spent_micros=spend.background_micros,
        background_limit_micros=share_limit,
        period_start=period_start,
        reserve_background_share=reserve_background_share,
    )


class AgentSpendSource(Protocol):
    async def spent(self, agent_id: str, start: datetime, end: datetime) -> AgentSpend: ...


class AgentBudgetEnvelope:
    """설정 하나와 지출 원천 하나. 판정만 한다 -- 막을지 기록할지는 부르는 쪽이 정한다."""

    def __init__(
        self,
        source: AgentSpendSource,
        *,
        limit_micros: int,
        background_share: float,
        reserve_background_share: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._source = source
        self._limit = limit_micros
        self._share = background_share
        self._reserve = reserve_background_share
        self._clock = clock

    async def judge(self, agent_id: str, mode: CodingTaskMode | str) -> EnvelopeVerdict:
        start, end = month_bounds(self._clock())
        spend = await self._source.spent(agent_id, start, end)
        return envelope_verdict(
            spend,
            limit_micros=self._limit,
            background_share=self._share,
            mode=mode,
            period_start=start,
            reserve_background_share=self._reserve,
        )


class InMemoryAgentSpendSource:
    """테스트용. 태스크마다 (agent_id, mode, 연 시각, 누적 비용)을 직접 적는다 --
    Postgres 원천이 체크포인트에서 읽는 것과 같은 모양이다."""

    def __init__(self) -> None:
        self._tasks: dict[str, tuple[str, str, datetime, int]] = {}

    def record(
        self,
        task_id: str,
        *,
        agent_id: str,
        mode: CodingTaskMode | str,
        created_at: datetime,
        cost_micros: int,
    ) -> None:
        self._tasks[task_id] = (agent_id, CodingTaskMode(mode).value, created_at, cost_micros)

    async def spent(self, agent_id: str, start: datetime, end: datetime) -> AgentSpend:
        rows = [
            (mode, cost)
            for owner, mode, created_at, cost in self._tasks.values()
            if owner == agent_id and start <= created_at < end
        ]
        return AgentSpend(
            total_micros=sum(cost for _, cost in rows),
            background_micros=sum(
                cost for mode, cost in rows if mode == CodingTaskMode.BACKGROUND.value
            ),
        )


class PostgresAgentSpendSource:
    """태스크마다 **최신** 체크포인트 하나의 `cost_micros` 를 더한다.

    체크포인트가 없는 태스크(아직 첫 단계 전)는 0 이다. 보관된 태스크도 센다 --
    보관해도 쓴 돈은 그대로다.
    """

    def __init__(self, session_factory: Callable[[], Awaitable[Any]]) -> None:
        self._session_factory = session_factory

    async def spent(self, agent_id: str, start: datetime, end: datetime) -> AgentSpend:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        COALESCE(SUM(cost), 0) AS total,
                        COALESCE(SUM(cost) FILTER (WHERE t.mode = 'background'), 0)
                            AS background
                    FROM coding_tasks t
                    CROSS JOIN LATERAL (
                        SELECT COALESCE((c.loop_state_json->>'cost_micros')::bigint, 0) AS cost
                        FROM coding_checkpoints c
                        WHERE c.task_id = t.task_id
                        ORDER BY c.seq DESC
                        LIMIT 1
                    ) latest
                    WHERE t.agent_id = :agent_id
                      AND t.created_at >= :start AND t.created_at < :end
                    """
                ),
                {"agent_id": agent_id, "start": start, "end": end},
            )
            row = result.one()
        return AgentSpend(total_micros=int(row.total), background_micros=int(row.background))


def build_agent_envelope(
    standing: Any, session_factory: Callable[[], Awaitable[Any]]
) -> AgentBudgetEnvelope | None:
    """`None` 이 off 다. 켜졌는지 판단하는 자리는 이 팩토리 하나다."""
    budget = getattr(standing, "budget", None)
    if budget is None or not budget.enabled:
        return None
    return AgentBudgetEnvelope(
        PostgresAgentSpendSource(session_factory),
        limit_micros=budget.monthly_limit_micros,
        background_share=budget.background_share,
        reserve_background_share=budget.reserve_background_share,
    )

