"""상시 질문 -- 트랙 Q3 (docs/Q10B_Q3_PAUSE_STANDING_QUESTIONS_DESIGN_261002.md §5).

에이전트가 같은 질문을 주기적으로 심층분석(DA)에 다시 묻고, 직전 런과 **verified
클레임 집합이 달라졌을 때만** 소유자에게 알린다.

- **제출과 정산을 나눈다(SQ3).** 폴러가 매 분 ① 끝난 DA 런을 정산하고(차이 → 알림)
  ② 때가 된 질문을 제출한다. DA 런은 사용자가 여는 것과 같은 제출 계약으로 연다(SQ2) --
  실행자(인라인·Celery)와 재시도·재개는 DA 의 것이다. 질문마다 진행 중 런은 하나다.
- **차이의 단위는 클레임이다**(분석 §6 결정 4). 1차 짝짓기 키는 런 안에서 이미 쓰는
  `DAClaim.hash`(= `claim_hash(text)`), 보조 키는 인용 증거의 blob 해시 집합(결정 8).
  새 해시 정의를 만들지 않는다.
- **알림은 새로 검증 또는 반증이 있을 때만**(SQ6). 사라짐·재표현 후보는 수만 싣는다.
  첫 정산은 기준선이라 알리지 않는다. 실패한 런은 기준선이 되지 않는다(SQ7).
- 제출 문(SQ8): 에이전트 `active` · 봉투(Q10a)의 background 판정. 📌 DA 지출은 봉투에
  들어가지 않는다 -- 주기 하한(SQ9)과 개수 상한이 비용의 상한이다.

메모리 구현과 Postgres 구현이 같은 계약을 지킨다(`tests/standing/test_standing_questions.py`).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from croniter import croniter
from sqlalchemy import text

from neos.coding.domain.models import CodingTaskMode
from neos.standing.notifications import KIND_QUESTION_CHANGED, StandingNotice

logger = logging.getLogger(__name__)

#: 제출이 막힌 사유. 봉투의 사유 코드는 그대로 싣는다(`budget.py`).
SKIP_AGENT_NOT_ACTIVE = "agent_not_active"
#: cron 의 최소 간격을 볼 때 내다보는 회차 수. 하루에 몇 번 도는 표현까지 잡는다.
_INTERVAL_PROBES = 48


class QuestionRefused(Exception):
    """만들 수 없다. `reason` 은 안정된 코드다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# -- cron ----------------------------------------------------------------------


def next_run(cron_expression: str, after: datetime) -> datetime:
    """UTC cron 의 다음 회차. 상시 질문은 UTC 만 쓴다."""
    return croniter(cron_expression, after.astimezone(UTC)).get_next(datetime).astimezone(UTC)


def validate_cron(cron_expression: str, *, min_interval_minutes: int, now: datetime) -> None:
    """모양이 맞고, 가장 짧은 간격이 하한 이상이어야 한다(SQ9).

    다음 `_INTERVAL_PROBES` 회차의 간격을 본다 -- `0 9,10 * * *` 처럼 하루에 한 번은
    촘촘한 표현도 잡는다.
    """
    expression = (cron_expression or "").strip()
    if not expression or not croniter.is_valid(expression):
        raise QuestionRefused("invalid_cron")
    minimum = timedelta(minutes=min_interval_minutes)
    iterator = croniter(expression, now.astimezone(UTC))
    previous = iterator.get_next(datetime)
    for _ in range(_INTERVAL_PROBES):
        current = iterator.get_next(datetime)
        if current - previous < minimum:
            raise QuestionRefused("cron_too_frequent")
        previous = current


# -- the diff ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    """DA 런의 클레임 하나. `evidence` 는 인용한 blob 해시(`DAEvidence.raw_ref`) 집합이다."""

    hash: str
    text: str
    status: str
    evidence: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ClaimDiff:
    newly_verified: tuple[ClaimRecord, ...] = ()
    refuted: tuple[ClaimRecord, ...] = ()
    dropped: tuple[ClaimRecord, ...] = ()
    #: (지금의 클레임, 그와 증거가 겹친 직전의 클레임들)
    rephrased: tuple[tuple[ClaimRecord, tuple[ClaimRecord, ...]], ...] = ()

    @property
    def changed(self) -> bool:
        """알릴 것인가 -- 새로 검증 또는 반증(SQ6)."""
        return bool(self.newly_verified or self.refuted)

    def summary(self) -> dict[str, Any]:
        """`standing_question_runs.diff` 에 싣는 것. 문장이 아니라 해시와 수다."""
        return {
            "baseline": False,
            "newly_verified": sorted(claim.hash for claim in self.newly_verified),
            "refuted": sorted(claim.hash for claim in self.refuted),
            "dropped": sorted(claim.hash for claim in self.dropped),
            "rephrased": sorted(claim.hash for claim, _ in self.rephrased),
        }


def diff_claims(previous: Iterable[ClaimRecord], current: Iterable[ClaimRecord]) -> ClaimDiff:
    """직전 런과 이번 런의 verified 클레임 차이(SQ5).

    - **새로 검증** -- 지금 verified, 직전엔 같은 해시가 verified 가 아니었다, 재표현 후보 아님
    - **반증** -- 직전 verified, 같은 해시가 지금 rejected
    - **재표현 후보** -- 짝 없는 지금의 verified 중, 짝 없는 직전 verified 와 증거가 겹치는 것
    - **사라짐** -- 직전 verified, 지금 verified 도 rejected 도 아니고 재표현으로도 설명되지 않는다
    """
    previous_by_hash = {claim.hash: claim for claim in previous}
    current_by_hash = {claim.hash: claim for claim in current}
    previous_verified = {h: c for h, c in previous_by_hash.items() if c.status == "verified"}
    current_verified = {h: c for h, c in current_by_hash.items() if c.status == "verified"}

    unmatched_now = [c for h, c in current_verified.items() if h not in previous_verified]
    gone = {h: c for h, c in previous_verified.items() if h not in current_verified}
    refuted = [
        c for h, c in gone.items()
        if h in current_by_hash and current_by_hash[h].status == "rejected"
    ]
    refuted_hashes = {claim.hash for claim in refuted}
    unmatched_before = [c for h, c in gone.items() if h not in refuted_hashes]

    rephrased: list[tuple[ClaimRecord, tuple[ClaimRecord, ...]]] = []
    explained: set[str] = set()
    newly: list[ClaimRecord] = []
    for claim in unmatched_now:
        partners = tuple(
            before for before in unmatched_before
            if claim.evidence and claim.evidence & before.evidence
        )
        if partners:
            rephrased.append((claim, partners))
            explained.update(before.hash for before in partners)
        else:
            newly.append(claim)
    dropped = [claim for claim in unmatched_before if claim.hash not in explained]

    def ordered(claims: Iterable[ClaimRecord]) -> tuple[ClaimRecord, ...]:
        return tuple(sorted(claims, key=lambda claim: claim.hash))

    return ClaimDiff(
        newly_verified=ordered(newly),
        refuted=ordered(refuted),
        dropped=ordered(dropped),
        rephrased=tuple(sorted(rephrased, key=lambda pair: pair[0].hash)),
    )


def render_notice(
    question: str, diff: ClaimDiff, *, da_run_id: str, max_claims: int
) -> str:
    """사람에게 가는 평문(SQ10). 클레임 문장은 분류마다 `max_claims` 까지."""

    def section(title: str, claims: Sequence[ClaimRecord]) -> list[str]:
        if not claims:
            return []
        lines = [f"{title} {len(claims)}:"]
        lines += [f"- {_one_line(claim.text)}" for claim in claims[:max_claims]]
        if len(claims) > max_claims:
            lines.append(f"- …외 {len(claims) - max_claims}")
        return lines

    lines = [f"[NEOS] 상시 질문의 답이 달라졌습니다: {_one_line(question)}"]
    lines += section("새로 검증", diff.newly_verified)
    lines += section("반증", diff.refuted)
    lines.append(
        f"(사라짐 {len(diff.dropped)} · 재표현 후보 {len(diff.rephrased)} -- 수만 적는다)"
    )
    lines.append(f"DA 런: {da_run_id}")
    return "\n".join(lines)


def _one_line(value: str, limit: int = 300) -> str:
    flat = " ".join((value or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


# -- the store -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StandingQuestion:
    question_id: str
    agent_id: str
    question: str
    cron_expression: str
    enabled: bool
    next_run_at: datetime
    created_at: datetime
    last_skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DueQuestion:
    """제출할 때가 된 질문과, 제출 문이 볼 에이전트의 사실."""

    question: StandingQuestion
    owner_id: str
    agent_active: bool


@dataclass(frozen=True, slots=True)
class QuestionRun:
    question_id: str
    da_run_id: str
    status: str
    created_at: datetime
    diff: dict[str, Any] | None = None
    notified: bool = False
    settled_at: datetime | None = None


class QuestionStore(Protocol):
    async def create(
        self,
        owner_id: str,
        agent_id: str,
        *,
        question: str,
        cron_expression: str,
        next_run_at: datetime,
        max_per_agent: int,
        now: datetime,
    ) -> StandingQuestion | None: ...

    async def list_for_agent(self, owner_id: str, agent_id: str) -> list[StandingQuestion]: ...

    async def get(self, owner_id: str, question_id: str) -> StandingQuestion | None: ...

    async def set_enabled(
        self, owner_id: str, question_id: str, enabled: bool, *, now: datetime
    ) -> StandingQuestion | None: ...

    async def delete(self, owner_id: str, question_id: str, *, now: datetime) -> bool: ...

    async def runs(self, owner_id: str, question_id: str, *, limit: int) -> list[QuestionRun]: ...

    async def question_by_id(self, question_id: str) -> StandingQuestion | None:
        """폴러 전용 -- 소유자 없이 읽는다. 지운 질문은 `None` 이다: 그 질문의 진행 중
        런은 정산은 하되(다음 회차를 막지 않게) 알리지 않는다."""
        ...

    async def claim_due(self, *, now: datetime, limit: int) -> list[DueQuestion]: ...

    async def record_dispatch(
        self, question_id: str, da_run_id: str, *, next_run_at: datetime, now: datetime
    ) -> None: ...

    async def record_skip(
        self, question_id: str, reason: str, *, next_run_at: datetime, now: datetime
    ) -> None: ...

    async def in_flight(self) -> list[QuestionRun]: ...

    async def baseline_run(self, question_id: str) -> str | None: ...

    async def settle(
        self,
        question_id: str,
        da_run_id: str,
        *,
        status: str,
        diff: dict[str, Any] | None,
        notified: bool,
        now: datetime,
    ) -> None: ...


def new_question_id() -> str:
    return f"sq_{uuid4().hex}"


class InMemoryQuestionStore:
    """테스트용. 에이전트는 `agents`(agent_id -> (owner_id, active))로 직접 적는다."""

    def __init__(self, agents: dict[str, tuple[str, bool]] | None = None) -> None:
        self.agents = dict(agents or {})
        self.questions: dict[str, StandingQuestion] = {}
        self.deleted: set[str] = set()
        self.question_runs: dict[tuple[str, str], QuestionRun] = {}

    def _owned(self, owner_id: str, question_id: str) -> StandingQuestion | None:
        question = self.questions.get(question_id)
        if question is None or question_id in self.deleted:
            return None
        agent = self.agents.get(question.agent_id)
        if agent is None or agent[0] != owner_id:
            return None
        return question

    async def create(self, owner_id, agent_id, *, question, cron_expression, next_run_at,
                     max_per_agent, now):
        agent = self.agents.get(agent_id)
        if agent is None or agent[0] != owner_id:
            return None
        live = [
            q for q in self.questions.values()
            if q.agent_id == agent_id and q.question_id not in self.deleted
        ]
        if len(live) >= max_per_agent:
            raise QuestionRefused("too_many_questions")
        stored = StandingQuestion(
            question_id=new_question_id(),
            agent_id=agent_id,
            question=question,
            cron_expression=cron_expression,
            enabled=True,
            next_run_at=next_run_at,
            created_at=now,
        )
        self.questions[stored.question_id] = stored
        return stored

    async def list_for_agent(self, owner_id, agent_id):
        return sorted(
            (
                q for q in self.questions.values()
                if q.agent_id == agent_id and self._owned(owner_id, q.question_id) is not None
            ),
            key=lambda q: (q.created_at, q.question_id),
        )

    async def get(self, owner_id, question_id):
        return self._owned(owner_id, question_id)

    async def set_enabled(self, owner_id, question_id, enabled, *, now):
        question = self._owned(owner_id, question_id)
        if question is None:
            return None
        self.questions[question_id] = replace(question, enabled=enabled)
        return self.questions[question_id]

    async def delete(self, owner_id, question_id, *, now):
        if self._owned(owner_id, question_id) is None:
            return False
        self.deleted.add(question_id)
        return True

    async def runs(self, owner_id, question_id, *, limit):
        if self._owned(owner_id, question_id) is None:
            return []
        rows = [r for (qid, _), r in self.question_runs.items() if qid == question_id]
        return sorted(rows, key=lambda r: (r.created_at, r.da_run_id), reverse=True)[:limit]

    async def question_by_id(self, question_id):
        if question_id in self.deleted:
            return None
        return self.questions.get(question_id)

    async def claim_due(self, *, now, limit):
        due = []
        for question in sorted(self.questions.values(), key=lambda q: q.next_run_at):
            if question.question_id in self.deleted or not question.enabled:
                continue
            if question.next_run_at > now:
                continue
            if any(
                r.status == "dispatched"
                for (qid, _), r in self.question_runs.items()
                if qid == question.question_id
            ):
                continue
            owner_id, active = self.agents.get(question.agent_id, ("", False))
            due.append(DueQuestion(question, owner_id, active))
        return due[:limit]

    async def record_dispatch(self, question_id, da_run_id, *, next_run_at, now):
        self.question_runs[(question_id, da_run_id)] = QuestionRun(
            question_id, da_run_id, "dispatched", now
        )
        self.questions[question_id] = replace(
            self.questions[question_id], next_run_at=next_run_at, last_skip_reason=None
        )

    async def record_skip(self, question_id, reason, *, next_run_at, now):
        self.questions[question_id] = replace(
            self.questions[question_id], next_run_at=next_run_at, last_skip_reason=reason
        )

    async def in_flight(self):
        return [r for r in self.question_runs.values() if r.status == "dispatched"]

    async def baseline_run(self, question_id):
        settled = [
            r for (qid, _), r in self.question_runs.items()
            if qid == question_id and r.status == "settled"
        ]
        if not settled:
            return None
        return max(settled, key=lambda r: (r.created_at, r.da_run_id)).da_run_id

    async def settle(self, question_id, da_run_id, *, status, diff, notified, now):
        key = (question_id, da_run_id)
        current = self.question_runs.get(key)
        if current is None or current.status != "dispatched":
            return
        self.question_runs[key] = replace(
            current, status=status, diff=diff, notified=notified, settled_at=now
        )


_QUESTION_COLUMNS = """
    q.question_id, q.agent_id, q.question, q.cron_expression, q.enabled,
    q.next_run_at, q.created_at, q.last_skip_reason
"""


def _question(row) -> StandingQuestion:
    return StandingQuestion(*row[:8])


class PostgresQuestionStore:
    def __init__(self, session_factory: Callable[[], Awaitable[Any]]) -> None:
        self._session_factory = session_factory

    async def create(self, owner_id, agent_id, *, question, cron_expression, next_run_at,
                     max_per_agent, now):
        async with await self._session_factory() as session:
            async with session.begin():
                # 에이전트 행을 잠가 개수 검사와 삽입 사이에 다른 생성이 끼지 못하게 한다.
                agent = (
                    await session.execute(
                        text(
                            """
                            SELECT agent_id FROM standing_agents
                            WHERE agent_id = :agent_id AND owner_id = :owner_id
                              AND deleted_at IS NULL
                            FOR UPDATE
                            """
                        ),
                        {"agent_id": agent_id, "owner_id": owner_id},
                    )
                ).first()
                if agent is None:
                    return None
                count = (
                    await session.execute(
                        text(
                            """
                            SELECT count(*) FROM standing_questions
                            WHERE agent_id = :agent_id AND deleted_at IS NULL
                            """
                        ),
                        {"agent_id": agent_id},
                    )
                ).scalar_one()
                if count >= max_per_agent:
                    raise QuestionRefused("too_many_questions")
                stored = StandingQuestion(
                    question_id=new_question_id(),
                    agent_id=agent_id,
                    question=question,
                    cron_expression=cron_expression,
                    enabled=True,
                    next_run_at=next_run_at,
                    created_at=now,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO standing_questions
                            (question_id, agent_id, question, cron_expression, enabled,
                             next_run_at, created_at, updated_at)
                        VALUES (:question_id, :agent_id, :question, :cron, TRUE,
                                :next_run_at, :now, :now)
                        """
                    ),
                    {
                        "question_id": stored.question_id,
                        "agent_id": agent_id,
                        "question": question,
                        "cron": cron_expression,
                        "next_run_at": next_run_at,
                        "now": now,
                    },
                )
        return stored

    async def _select(self, where: str, params: dict[str, Any]) -> list[StandingQuestion]:
        async with await self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        f"""
                        SELECT {_QUESTION_COLUMNS}
                        FROM standing_questions q
                        JOIN standing_agents a ON a.agent_id = q.agent_id
                        WHERE q.deleted_at IS NULL AND a.deleted_at IS NULL
                          AND a.owner_id = :owner_id AND {where}
                        ORDER BY q.created_at, q.question_id
                        """
                    ),
                    params,
                )
            ).all()
        return [_question(row) for row in rows]

    async def list_for_agent(self, owner_id, agent_id):
        return await self._select(
            "q.agent_id = :agent_id", {"owner_id": owner_id, "agent_id": agent_id}
        )

    async def get(self, owner_id, question_id):
        rows = await self._select(
            "q.question_id = :question_id", {"owner_id": owner_id, "question_id": question_id}
        )
        return rows[0] if rows else None

    async def set_enabled(self, owner_id, question_id, enabled, *, now):
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            f"""
                            UPDATE standing_questions q
                            SET enabled = :enabled, updated_at = :now
                            FROM standing_agents a
                            WHERE q.question_id = :question_id
                              AND a.agent_id = q.agent_id AND a.owner_id = :owner_id
                              AND q.deleted_at IS NULL AND a.deleted_at IS NULL
                            RETURNING {_QUESTION_COLUMNS}
                            """
                        ),
                        {
                            "question_id": question_id,
                            "owner_id": owner_id,
                            "enabled": enabled,
                            "now": now,
                        },
                    )
                ).first()
        return _question(row) if row is not None else None

    async def delete(self, owner_id, question_id, *, now):
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            UPDATE standing_questions q
                            SET deleted_at = :now, updated_at = :now
                            FROM standing_agents a
                            WHERE q.question_id = :question_id
                              AND a.agent_id = q.agent_id AND a.owner_id = :owner_id
                              AND q.deleted_at IS NULL
                            RETURNING q.question_id
                            """
                        ),
                        {"question_id": question_id, "owner_id": owner_id, "now": now},
                    )
                ).first()
        return row is not None

    async def runs(self, owner_id, question_id, *, limit):
        async with await self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT r.question_id, r.da_run_id, r.status, r.created_at,
                               r.diff, r.notified, r.settled_at
                        FROM standing_question_runs r
                        JOIN standing_questions q ON q.question_id = r.question_id
                        JOIN standing_agents a ON a.agent_id = q.agent_id
                        WHERE r.question_id = :question_id AND a.owner_id = :owner_id
                          AND q.deleted_at IS NULL
                        ORDER BY r.created_at DESC, r.da_run_id DESC
                        LIMIT :limit
                        """
                    ),
                    {"question_id": question_id, "owner_id": owner_id, "limit": limit},
                )
            ).all()
        return [QuestionRun(*row) for row in rows]

    async def question_by_id(self, question_id):
        async with await self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        f"""
                        SELECT {_QUESTION_COLUMNS}
                        FROM standing_questions q
                        WHERE q.question_id = :question_id AND q.deleted_at IS NULL
                        """
                    ),
                    {"question_id": question_id},
                )
            ).first()
        return _question(row) if row is not None else None

    async def claim_due(self, *, now, limit):
        """`SKIP LOCKED` -- 폴러가 둘이어도 한 질문을 둘이 제출하지 않는다. 같은
        트랜잭션에서 다음 회차를 앞당겨 적어 두고(잠금 해제 뒤 다른 폴러가 다시 집지
        않게), 제출 결과는 `record_dispatch` · `record_skip` 이 고쳐 쓴다."""
        async with await self._session_factory() as session:
            async with session.begin():
                rows = (
                    await session.execute(
                        text(
                            f"""
                            SELECT {_QUESTION_COLUMNS}, a.owner_id,
                                   (a.status = 'active') AS agent_active
                            FROM standing_questions q
                            JOIN standing_agents a ON a.agent_id = q.agent_id
                            WHERE q.enabled AND q.deleted_at IS NULL
                              AND a.deleted_at IS NULL
                              AND q.next_run_at <= :now
                              AND NOT EXISTS (
                                  SELECT 1 FROM standing_question_runs r
                                  WHERE r.question_id = q.question_id
                                    AND r.status = 'dispatched'
                              )
                            ORDER BY q.next_run_at, q.question_id
                            FOR UPDATE OF q SKIP LOCKED
                            LIMIT :limit
                            """
                        ),
                        {"now": now, "limit": limit},
                    )
                ).all()
                for row in rows:
                    await session.execute(
                        text(
                            """
                            UPDATE standing_questions SET next_run_at = :hold
                            WHERE question_id = :question_id
                            """
                        ),
                        {"question_id": row[0], "hold": now + timedelta(minutes=5)},
                    )
        return [DueQuestion(_question(row), row[8], bool(row[9])) for row in rows]

    async def record_dispatch(self, question_id, da_run_id, *, next_run_at, now):
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO standing_question_runs
                            (question_id, da_run_id, status, created_at)
                        VALUES (:question_id, :da_run_id, 'dispatched', :now)
                        """
                    ),
                    {"question_id": question_id, "da_run_id": da_run_id, "now": now},
                )
                await session.execute(
                    text(
                        """
                        UPDATE standing_questions
                        SET next_run_at = :next_run_at, last_skip_reason = NULL,
                            updated_at = :now
                        WHERE question_id = :question_id
                        """
                    ),
                    {"question_id": question_id, "next_run_at": next_run_at, "now": now},
                )

    async def record_skip(self, question_id, reason, *, next_run_at, now):
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE standing_questions
                        SET next_run_at = :next_run_at, last_skip_reason = :reason,
                            updated_at = :now
                        WHERE question_id = :question_id
                        """
                    ),
                    {
                        "question_id": question_id,
                        "next_run_at": next_run_at,
                        "reason": reason[:64],
                        "now": now,
                    },
                )

    async def in_flight(self):
        async with await self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT question_id, da_run_id, status, created_at, diff, notified,
                               settled_at
                        FROM standing_question_runs
                        WHERE status = 'dispatched'
                        ORDER BY created_at, question_id
                        """
                    )
                )
            ).all()
        return [QuestionRun(*row) for row in rows]

    async def baseline_run(self, question_id):
        async with await self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT da_run_id FROM standing_question_runs
                        WHERE question_id = :question_id AND status = 'settled'
                        ORDER BY created_at DESC, da_run_id DESC
                        LIMIT 1
                        """
                    ),
                    {"question_id": question_id},
                )
            ).first()
        return row[0] if row is not None else None

    async def settle(self, question_id, da_run_id, *, status, diff, notified, now):
        import json

        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE standing_question_runs
                        SET status = :status, diff = CAST(:diff AS JSONB),
                            notified = :notified, settled_at = :now
                        WHERE question_id = :question_id AND da_run_id = :da_run_id
                          AND status = 'dispatched'
                        """
                    ),
                    {
                        "question_id": question_id,
                        "da_run_id": da_run_id,
                        "status": status,
                        "diff": json.dumps(diff) if diff is not None else None,
                        "notified": notified,
                        "now": now,
                    },
                )


# -- the DA side ---------------------------------------------------------------


class DAReader(Protocol):
    async def status(self, da_run_id: str) -> str | None: ...

    async def claims(self, da_run_id: str) -> list[ClaimRecord]: ...


class PostgresDAReader:
    """DA 원장을 **읽기만** 한다(P2: 원장의 작성자는 하나다)."""

    def __init__(self, session_factory: Callable[[], Awaitable[Any]]) -> None:
        self._session_factory = session_factory

    async def status(self, da_run_id):
        async with await self._session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT status FROM deep_analysis_runs WHERE id = :id"),
                    {"id": da_run_id},
                )
            ).first()
        return row[0] if row is not None else None

    async def claims(self, da_run_id):
        async with await self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT c.hash, c.text, c.status,
                               COALESCE(
                                   array_agg(e.raw_ref) FILTER (WHERE e.raw_ref IS NOT NULL),
                                   ARRAY[]::varchar[]
                               )
                        FROM deep_analysis_claims c
                        LEFT JOIN deep_analysis_evidence e
                               ON e.run_id = c.run_id AND e.claim_id = c.id
                        WHERE c.run_id = :run_id
                        GROUP BY c.run_id, c.id, c.hash, c.text, c.status
                        """
                    ),
                    {"run_id": da_run_id},
                )
            ).all()
        return [ClaimRecord(row[0], row[1], row[2], frozenset(row[3])) for row in rows]


#: (owner_id, question, profile) -> da_run_id. 기존 DA 제출 계약(`create_run` + 제출)이다.
SubmitFn = Callable[[str, str, str], Awaitable[str]]


def da_submitter(session_factory: Callable[[], Awaitable[Any]]) -> SubmitFn:
    """사용자가 여는 DA 와 같은 길(SQ2) -- 런 행을 커밋한 뒤 설정된 실행자로 보낸다.
    소유자가 런의 `user_id` 이고 대화는 없다(리포트 메시지를 남길 곳이 없다)."""

    async def submit(owner_id: str, question: str, profile: str) -> str:
        from neos.tasks.deep_analysis_job_task import submit_deep_analysis_job
        from neos.workflow.deep_analysis.ledger import create_run

        async with await session_factory() as session:
            run_id = await create_run(session, question, profile, user_id=owner_id)
            await session.commit()
        await submit_deep_analysis_job(run_id, question, profile)
        return run_id

    return submit


# -- the poll ------------------------------------------------------------------


@dataclass
class PollReport:
    settled: list[str] = field(default_factory=list)
    notified: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    dispatched: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


async def settle_finished(
    store: QuestionStore,
    reader: DAReader,
    *,
    notifier: Any,
    max_claims: int,
    settle_timeout: timedelta,
    now: datetime,
    report: PollReport,
) -> None:
    """끝난 DA 런을 정산한다. 진행 중이면 그대로 두고, 시한을 넘기면 실패로 닫는다."""
    for run in await store.in_flight():
        status = await reader.status(run.da_run_id)
        if status == "running" and now - run.created_at < settle_timeout:
            continue
        if status != "completed":
            await store.settle(
                run.question_id, run.da_run_id,
                status="failed",
                diff={"reason": "timeout" if status == "running" else (status or "missing")},
                notified=False,
                now=now,
            )
            report.failed.append(run.da_run_id)
            continue
        baseline = await store.baseline_run(run.question_id)
        current = await reader.claims(run.da_run_id)
        if baseline is None:
            await store.settle(
                run.question_id, run.da_run_id,
                status="settled", diff={"baseline": True}, notified=False, now=now,
            )
            report.settled.append(run.da_run_id)
            continue
        diff = diff_claims(await reader.claims(baseline), current)
        notified = False
        if diff.changed and notifier is not None:
            question = await store.question_by_id(run.question_id)
            if question is not None:
                notified = await notifier.notify(
                    StandingNotice(
                        agent_id=question.agent_id,
                        kind=KIND_QUESTION_CHANGED,
                        dedupe_key=f"question:{run.question_id}:{run.da_run_id}",
                        body=render_notice(
                            question.question, diff,
                            da_run_id=run.da_run_id, max_claims=max_claims,
                        ),
                    )
                )
        summary = diff.summary()
        summary["baseline_run_id"] = baseline
        await store.settle(
            run.question_id, run.da_run_id,
            status="settled", diff=summary, notified=notified, now=now,
        )
        report.settled.append(run.da_run_id)
        if notified:
            report.notified.append(run.da_run_id)


async def dispatch_due(
    store: QuestionStore,
    *,
    submit: SubmitFn,
    envelope: Any,
    profile: str,
    now: datetime,
    limit: int,
    report: PollReport,
) -> None:
    """때가 된 질문을 제출한다. 문(SQ8)에 막히면 그 회차를 건너뛰고 사유를 남긴다."""
    for due in await store.claim_due(now=now, limit=limit):
        question = due.question
        following = next_run(question.cron_expression, now)
        reason = None
        if not due.agent_active:
            reason = SKIP_AGENT_NOT_ACTIVE
        elif envelope is not None:
            verdict = await envelope.judge(question.agent_id, CodingTaskMode.BACKGROUND)
            if verdict.over:
                reason = str(verdict.reason)
        if reason is not None:
            await store.record_skip(question.question_id, reason, next_run_at=following, now=now)
            report.skipped[question.question_id] = reason
            continue
        try:
            da_run_id = await submit(due.owner_id, question.question, profile)
        except Exception:  # noqa: BLE001 -- 한 질문의 제출 실패가 나머지를 막지 않는다
            logger.warning("standing question dispatch failed id=%s", question.question_id,
                           exc_info=True)
            await store.record_skip(
                question.question_id, "dispatch_failed", next_run_at=following, now=now
            )
            report.skipped[question.question_id] = "dispatch_failed"
            continue
        await store.record_dispatch(
            question.question_id, da_run_id, next_run_at=following, now=now
        )
        report.dispatched.append(da_run_id)


async def poll_once(
    store: QuestionStore,
    reader: DAReader,
    *,
    submit: SubmitFn,
    envelope: Any,
    notifier: Any,
    profile: str,
    max_claims: int,
    settle_timeout: timedelta,
    now: datetime,
    limit: int = 20,
) -> PollReport:
    """정산이 먼저다 -- 같은 폴에서 막 끝난 런의 질문이 다음 회차를 낼 수 있게."""
    report = PollReport()
    await settle_finished(
        store, reader,
        notifier=notifier, max_claims=max_claims,
        settle_timeout=settle_timeout, now=now, report=report,
    )
    await dispatch_due(
        store, submit=submit, envelope=envelope, profile=profile, now=now, limit=limit,
        report=report,
    )
    return report
