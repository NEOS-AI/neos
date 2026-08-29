"""Run-scoped, single-writer ledger for the Deep Analysis Harness."""

from __future__ import annotations

import json
import math
import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from neos.config.settings import settings
from neos.database.deep_analysis_models import (
    DABlob,
    DAClaim,
    DAEvidence,
    DAEvent,
    DAFeedback,
    DAQuestion,
    DARun,
)

from .models import ProposedBlob, ProposedClaim, RepairResult, Verdict, WorkerResult
from .text_norm import claim_hash


class IllegalTransition(Exception):
    """Raised when a question tries to leave the canonical state machine."""


_LEGAL_TRANSITIONS = {
    ("open", "investigating"),
    ("open", "split"),
    ("open", "abandoned"),
    ("investigating", "open"),
    ("investigating", "resolved"),
}
_TERMINAL_STATUSES = {"resolved", "split", "abandoned"}
_CONFIDENCE_CLAMP_BUCKETS = ("0", "1", "2", "3_plus")


def _safe_clamp_counts(raw: object) -> dict[str, int]:
    values = raw if isinstance(raw, dict) else {}
    return {
        key: value
        if isinstance((value := values.get(key, 0)), int)
        and not isinstance(value, bool)
        and value >= 0
        else 0
        for key in _CONFIDENCE_CLAMP_BUCKETS
    }


# 강등으로 세는 이벤트 kind. 조회를 좁히는 용도이며, 실제 판정은
# `_degradation_kind()` 가 payload 까지 보고 내린다.
_DEGRADATION_KINDS = (
    "report_assembly_degraded",
    "node_reduction_degraded",
    "finalization_prompt_clamped",
    "report_graded",
)


def _payload_dict(raw: object) -> dict[str, Any]:
    """`DAEvent.payload` 를 dict 로 읽는다 -- 어떤 모양으로 와도 던지지 않는다.

    컬럼은 Text 라 보통 str 로 오지만 드라이버·테스트에 따라 dict 로도 온다.
    `report_markdown()` 과 같은 방어적 읽기다.
    """
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _degradation_kind(kind: str, payload: dict[str, Any]) -> str | None:
    """이 이벤트가 리포트를 깎았는가 -- 깎았다면 어떤 이름으로 셀 것인가.

    ⚠️ 🟡 **알려진 중복.** 같은 규칙이 프론트엔드에도 있다:
    `web/lib/deep-analysis/progress.ts` 의 `degradationKind()`.
    이쪽은 새로고침 후 복원을, 저쪽은 라이브 스트림을 담당한다. 어휘를 바꿀
    때 **반드시 양쪽을 함께** 고칠 것. 정본 fixture 목록은
    `tests/workflow/deep_analysis/test_ledger_degradations.py` 의
    `CANONICAL_FIXTURE` 와 `web/tests/source/deep-analysis-degradation.test.ts`
    의 `CANONICAL_FIXTURE` 에 같은 내용으로 들어 있다.
    통합 검토는 로드맵 §7 FE6.

    조사 범위나 검증 강도를 깎은 것(`investigation_stopped_at_floor`,
    `claim_discarded` 등)은 여기 들지 않는다 -- 리포트 자체는 주어진 재료로
    낼 수 있는 최선이기 때문이다(D26).

    `report_graded` 는 kind 가 아니라 **payload 가** 강등을 결정하는 유일한
    경우다. 굶은/잘린/해석 실패 판정자는 전부 `ok=True` 로 재조립 루프를
    끝내므로(`graders/report.py`) `judge` 키가 달린 이벤트는 run 당 최대 1건이고
    항상 최종 판정이다 -- 중간 시도가 오탐으로 잡히지 않는다.
    """
    if kind in ("report_assembly_degraded", "node_reduction_degraded"):
        return kind
    if kind == "finalization_prompt_clamped":
        return kind if payload.get("exhausted") is True else None
    if kind == "report_graded":
        judge = payload.get("judge")
        if isinstance(judge, str) and judge:
            return f"judge_unreviewed:{judge}"
        return None
    return None


def _hex_id() -> str:
    return uuid.uuid4().hex[:8]


async def create_run(
    session: AsyncSession,
    root_text: str,
    profile: str,
    *,
    user_id: str | None = None,
    conversation_id: str | None = None,
    assistant_message_id: str | None = None,
) -> str:
    run_id = _hex_id()
    session.add(
        DARun(
            id=run_id,
            root_question=root_text,
            profile=profile,
            status="running",
            user_id=user_id,
            conversation_id=conversation_id,
            assistant_message_id=assistant_message_id,
        )
    )
    await session.flush()
    return run_id


class Ledger:
    """The only component allowed to mutate run ledger state."""

    def __init__(
        self,
        session: AsyncSession,
        run_id: str,
        *,
        resolve_threshold: float | None = None,
        claim_retry_cap: int | None = None,
    ) -> None:
        self.db = session
        self.run_id = run_id
        self.resolve_threshold = (
            settings.DEEP_ANALYSIS_RESOLVE_THRESHOLD
            if resolve_threshold is None
            else resolve_threshold
        )
        self.claim_retry_cap = (
            settings.config.deep_analysis.claim_retry_cap
            if claim_retry_cap is None
            else claim_retry_cap
        )

    async def _lock(self) -> None:
        await self.db.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(:run_id, 0))"
            ),
            {"run_id": self.run_id},
        )

    async def log(
        self,
        kind: str,
        qid: str | None,
        payload: dict[str, Any],
    ) -> None:
        self.db.add(
            DAEvent(
                run_id=self.run_id,
                kind=kind,
                qid=qid,
                payload=json.dumps(payload, ensure_ascii=False),
            )
        )
        await self.db.flush()

    async def has_event(self, kind: str) -> bool:
        """True iff at least one event of ``kind`` exists for this run.

        The orchestrator uses this to make the global conflict-reinvestigation
        cap durable across crash-recovery: the in-memory counter resets on
        resume, but the event log does not, so a resumed run cannot spend a
        second reinvestigation round.
        """
        value = await self.db.scalar(
            select(func.count(DAEvent.seq)).where(
                DAEvent.run_id == self.run_id,
                DAEvent.kind == kind,
            )
        )
        return int(value or 0) > 0

    async def token_budget_state(self) -> tuple[int, dict[str, int]]:
        """Replay durable budget events into consumed and outstanding usage."""

        result = await self.db.execute(
            select(DAEvent.kind, DAEvent.payload).where(
                DAEvent.run_id == self.run_id,
                DAEvent.kind.in_(
                    (
                        "token_budget_reserved",
                        "token_budget_settled",
                        "token_budget_released",
                    )
                ),
            ).order_by(DAEvent.seq)
        )
        consumed = 0
        outstanding: dict[str, int] = {}
        terminal: set[str] = set()

        for kind, raw_payload in result:
            try:
                payload = (
                    raw_payload
                    if isinstance(raw_payload, dict)
                    else json.loads(raw_payload)
                )
                if not isinstance(payload, dict):
                    continue
                reservation_id = payload.get("reservation_id")
                if not isinstance(reservation_id, str) or not reservation_id:
                    continue

                if kind == "token_budget_reserved":
                    reserved = payload.get("reserved_tokens")
                    if (
                        reservation_id in terminal
                        or reservation_id in outstanding
                        or not isinstance(reserved, int)
                        or isinstance(reserved, bool)
                        or reserved < 1
                    ):
                        continue
                    outstanding[reservation_id] = reserved
                    continue

                if reservation_id not in outstanding:
                    continue
                reserved = outstanding[reservation_id]
                if kind == "token_budget_settled":
                    actual = payload.get("actual_tokens")
                    if (
                        not isinstance(actual, int)
                        or isinstance(actual, bool)
                        or actual < 0
                        or actual > reserved
                    ):
                        continue
                    consumed += actual

                del outstanding[reservation_id]
                terminal.add(reservation_id)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

        return consumed, outstanding

    async def open_question(
        self,
        question_text: str,
        parent_id: str | None,
        value_est: float,
        cap_tokens: int,
        depth: int,
    ) -> str:
        question_id = _hex_id()
        self.db.add(
            DAQuestion(
                id=question_id,
                run_id=self.run_id,
                parent_id=parent_id,
                text=question_text,
                status="open",
                depth=depth,
                value_est=value_est,
                cap_tokens=cap_tokens,
            )
        )
        await self.db.flush()
        await self.log(
            "question_opened",
            question_id,
            {"depth": depth, "value_est": value_est},
        )
        return question_id

    async def get_question(self, question_id: str) -> DAQuestion | None:
        return await self.db.get(DAQuestion, (question_id, self.run_id))

    async def _transition(self, question_id: str, to_status: str) -> None:
        question = await self.get_question(question_id)
        if question is None:
            raise KeyError(
                f"question {question_id!r} not found in run {self.run_id!r}"
            )
        current = question.status
        if (
            current in _TERMINAL_STATUSES
            or (current, to_status) not in _LEGAL_TRANSITIONS
        ):
            raise IllegalTransition(
                f"{current} -> {to_status} (qid={question_id})"
            )
        question.status = to_status
        await self.db.flush()

    async def recover(self) -> int:
        result = await self.db.execute(
            select(DAQuestion.id).where(
                DAQuestion.run_id == self.run_id,
                DAQuestion.status == "investigating",
            )
        )
        question_ids = list(result.scalars())
        for question_id in question_ids:
            await self._transition(question_id, "open")
        return len(question_ids)

    async def reopen_for_reinvestigation(self, question_id: str) -> None:
        """Move a question back to ``open`` for conflict reinvestigation.

        §4.1 treats ``resolved`` (and ``split``/``abandoned``) as terminal, so
        ``_transition`` forbids ``resolved -> open``. §6.7 mandates exactly one
        sanctioned exception: when a high-value equal-tier conflict survives the
        reduce, the owning (already ``resolved``) question must be reopened so
        the budgeter can re-select and re-investigate it. This is the single,
        named, run-scoped place that bypasses the legal-transition set on
        purpose; it sets the status directly and logs ``question_reopened`` so
        the exception is explicit and auditable.
        """
        question = await self.get_question(question_id)
        if question is None:
            raise KeyError(
                f"question {question_id!r} not found in run {self.run_id!r}"
            )
        previous = question.status
        if previous == "open":
            return
        question.status = "open"
        await self.db.flush()
        await self.log(
            "question_reopened",
            question_id,
            {"from": previous, "reason": "conflict_reinvestigation"},
        )

    async def _store_blob(self, blob: ProposedBlob) -> None:
        existing = await self.db.get(
            DABlob,
            (self.run_id, blob.content_hash),
        )
        if existing is not None:
            return
        self.db.add(
            DABlob(
                run_id=self.run_id,
                content_hash=blob.content_hash,
                url=blob.source_url,
                http_status=blob.http_status,
                raw_text=blob.raw_text,
            )
        )
        await self.db.flush()

    async def commit_blobs(self, blobs: list[ProposedBlob]) -> None:
        await self._lock()
        for blob in blobs:
            await self._store_blob(blob)

    async def record_split(
        self,
        question_id: str,
        child_ids: list[str],
    ) -> None:
        await self._transition(question_id, "split")
        await self.log(
            "split",
            question_id,
            {"children": child_ids},
        )

    async def _upsert_claim(
        self,
        question_id: str,
        claim: ProposedClaim,
    ) -> tuple[str, list[DAEvidence]]:
        normalized_hash = claim_hash(claim.text)
        result = await self.db.execute(
            select(DAClaim).where(
                DAClaim.run_id == self.run_id,
                DAClaim.hash == normalized_hash,
            )
        )
        stored = result.scalar_one_or_none()
        if stored is None:
            stored = DAClaim(
                id=_hex_id(),
                run_id=self.run_id,
                question_id=question_id,
                text=claim.text,
                hash=normalized_hash,
                status="pending",
                confidence=claim.confidence,
            )
            self.db.add(stored)
            await self.db.flush()
        else:
            stored.confidence = min(0.95, stored.confidence + 0.15)
            await self.db.flush()

        evidence_rows: list[DAEvidence] = []
        for proposed in claim.evidence:
            evidence = DAEvidence(
                id=_hex_id(),
                run_id=self.run_id,
                claim_id=stored.id,
                source_url=proposed.source_url,
                excerpt=proposed.excerpt[
                    : settings.config.deep_analysis.excerpt_max_chars
                ],
                raw_ref=proposed.raw_ref,
            )
            self.db.add(evidence)
            evidence_rows.append(evidence)
        await self.db.flush()
        return stored.id, evidence_rows

    async def pending_feedback(self, question_id: str) -> list[DAFeedback]:
        result = await self.db.execute(
            select(DAFeedback).join(
                DAClaim,
                (DAFeedback.claim_id == DAClaim.id)
                & (DAFeedback.run_id == DAClaim.run_id),
            ).where(
                DAFeedback.run_id == self.run_id,
                DAClaim.question_id == question_id,
                DAFeedback.resolved == 0,
            ).order_by(DAFeedback.attempt.desc())
        )
        return list(result.scalars())

    async def feedback_count(self, question_id: str) -> int:
        """Total feedback rows (resolved or not) for a question's claims.

        Used by the orchestrator's stall safety valve (D15) to detect whether
        a pass produced any new rejection feedback -- a no-progress signal
        must see this count stay flat."""
        value = await self.db.scalar(
            select(func.count(DAFeedback.id)).join(
                DAClaim,
                (DAFeedback.claim_id == DAClaim.id)
                & (DAFeedback.run_id == DAClaim.run_id),
            ).where(
                DAFeedback.run_id == self.run_id,
                DAClaim.question_id == question_id,
            )
        )
        return int(value or 0)

    async def _max_attempt(self, claim_id: str) -> int:
        value = await self.db.scalar(
            select(func.coalesce(func.max(DAFeedback.attempt), 0)).where(
                DAFeedback.run_id == self.run_id,
                DAFeedback.claim_id == claim_id,
            )
        )
        return int(value or 0)

    async def _evidence_for_claim(self, claim_id: str) -> list[DAEvidence]:
        result = await self.db.execute(
            select(DAEvidence).where(
                DAEvidence.run_id == self.run_id,
                DAEvidence.claim_id == claim_id,
            )
        )
        return list(result.scalars())

    @staticmethod
    def _claim_graded_payload(
        claim_id: str,
        outcome: str,
        verdict: Verdict,
    ) -> dict[str, Any]:
        """Build the privacy-bounded diagnostic event payload."""

        diagnostics = (
            verdict.diagnostics
            if isinstance(verdict.diagnostics, dict)
            else {}
        )

        def non_negative_int(key: str) -> int:
            value = diagnostics.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return max(0, value)
            return 0

        def finite_float(key: str, *, bounded: bool = False):
            value = diagnostics.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return None
            number = float(value)
            if not math.isfinite(number):
                return None
            if bounded:
                return min(1.0, max(0.0, number))
            return max(0.0, number)

        deterministic = diagnostics.get("deterministic")
        if deterministic not in {"passed", "rejected"}:
            deterministic = "passed" if verdict.ok else "rejected"
        agentic = diagnostics.get("agentic")
        if agentic not in {
            "not_configured",
            "skipped",
            "attempted_passed",
            "attempted_rejected",
            "exhausted",
        }:
            agentic = "not_configured"
        agentic_label = diagnostics.get("agentic_label")
        if not isinstance(agentic_label, str):
            agentic_label = None
        deterministic_code = diagnostics.get("deterministic_code")
        if not isinstance(deterministic_code, str):
            deterministic_code = "" if deterministic == "passed" else verdict.code

        return {
            "claim_id": claim_id,
            "outcome": outcome,
            "code": verdict.code if isinstance(verdict.code, str) else "",
            "deterministic": deterministic,
            "deterministic_code": deterministic_code,
            "agentic": agentic,
            "agentic_label": agentic_label,
            "evidence_count": non_negative_int("evidence_count"),
            "source_count": non_negative_int("source_count"),
            "fetched_source_count": non_negative_int(
                "fetched_source_count"
            ),
            "dead_source_count": non_negative_int("dead_source_count"),
            "excerpt_chars": non_negative_int("excerpt_chars"),
            "best_quote_score": finite_float(
                "best_quote_score", bounded=True
            ),
            "quote_threshold": finite_float("quote_threshold", bounded=True),
        }

    async def _log_claim_graded(
        self,
        question_id: str,
        claim_id: str,
        outcome: str,
        verdict: Verdict,
    ) -> None:
        await self.log(
            "claim_graded",
            question_id,
            self._claim_graded_payload(claim_id, outcome, verdict),
        )

    async def _apply_verdict(
        self,
        question_id: str,
        claim: DAClaim,
        evidence_rows: list[DAEvidence],
        verdict: Verdict,
    ) -> bool:
        """Shared verdict-application logic used by both `_record_verdict`
        (fresh claims during `commit_pass`) and `regrade_claim` (repaired
        claims re-graded outside a pass). Retry-cap and label handling must
        stay identical between the two call sites.
        """
        grade = "ok" if verdict.ok else verdict.code
        for evidence in evidence_rows:
            evidence.det_grade = grade
        if verdict.label is not None:
            for evidence in evidence_rows:
                evidence.agent_grade = verdict.label

        if verdict.ok:
            claim.status = "verified"
            await self._log_claim_graded(
                question_id, claim.id, "verified", verdict
            )
            await self.log(
                "claim_verified",
                question_id,
                {"claim_id": claim.id, "label": verdict.label},
            )
            return True

        # 재시도 캡(§6.1 rule4): 이번이 몇 번째 거절인가
        prior = await self._max_attempt(claim.id)
        if prior >= self.claim_retry_cap:
            claim.status = "unverified"
            await self._resolve_feedback(claim.id)
            await self._log_claim_graded(
                question_id, claim.id, "unverified", verdict
            )
            await self.log(
                "claim_unverified",
                question_id,
                {"claim_id": claim.id, "code": verdict.code, "label": verdict.label},
            )
            return False

        claim.status = "rejected"
        self.db.add(
            DAFeedback(
                run_id=self.run_id,
                claim_id=claim.id,
                code=verdict.code,
                detail=verdict.detail[:200],
                salvage=verdict.salvage,
                attempt=prior + 1,
            )
        )
        await self._log_claim_graded(
            question_id, claim.id, "rejected", verdict
        )
        await self.log(
            "claim_rejected",
            question_id,
            {
                "claim_id": claim.id,
                "code": verdict.code,
                "attempt": prior + 1,
                "label": verdict.label,
            },
        )
        return False

    async def _record_verdict(
        self,
        question_id: str,
        claim_id: str,
        evidence_rows: list[DAEvidence],
        verdict: Verdict | None,
    ) -> bool:
        if verdict is None:
            return False

        claim = await self.get_claim(claim_id)
        if claim is None:
            raise KeyError(claim_id)

        return await self._apply_verdict(question_id, claim, evidence_rows, verdict)

    async def regrade_claim(
        self,
        question_id: str,
        claim_id: str,
        verdict: Verdict,
    ) -> bool:
        """Re-grade an existing (repaired, `pending`) claim outside a pass.

        Reuses `_apply_verdict` so retry-cap + label handling stay identical
        to the fresh-claim path in `_record_verdict`. No new evidence is
        created here -- only existing evidence rows are updated.

        C3-m1 Finding 3: this path also dispatches the agentic judge (a
        weakened/negated claim pushed back to `pending` gets a fresh
        `_grade()` in `Orchestrator._regrade_pending`, which runs *after*
        `commit_pass` and so is not part of that call's `judge_tokens_spent`
        total). Billing goes here, not in `_apply_verdict`, because
        `_apply_verdict` is shared with `_record_verdict` -- the fresh-claim
        path already billed through `commit_pass`'s aggregate, and adding it
        again in the shared code would double-count that path.
        """
        claim = await self.get_claim(claim_id)
        if claim is None or claim.question_id != question_id:
            return False
        await self._lock()
        evidence_rows = await self._evidence_for_claim(claim_id)
        result = await self._apply_verdict(question_id, claim, evidence_rows, verdict)
        if verdict.tokens_spent:
            question = await self.get_question(question_id)
            if question is not None:
                question.spent_tokens += verdict.tokens_spent
        await self.db.flush()
        return result

    async def pending_claims(
        self,
        question_id: str,
    ) -> list[tuple[DAClaim, list[DAEvidence]]]:
        result = await self.db.execute(
            select(DAClaim).where(
                DAClaim.run_id == self.run_id,
                DAClaim.question_id == question_id,
                DAClaim.status == "pending",
            )
        )
        output: list[tuple[DAClaim, list[DAEvidence]]] = []
        for claim in result.scalars():
            output.append((claim, await self._evidence_for_claim(claim.id)))
        return output

    async def _resolve_feedback(self, claim_id: str) -> None:
        rows = await self.db.execute(
            select(DAFeedback).where(
                DAFeedback.run_id == self.run_id,
                DAFeedback.claim_id == claim_id,
                DAFeedback.resolved == 0,
            )
        )
        for feedback in rows.scalars():
            feedback.resolved = 1

    async def _claim_hash_taken(self, normalized_hash: str, *, exclude_id: str) -> bool:
        """run 안의 다른 클레임이 이미 이 hash를 갖고 있는가.

        삽입 경로(`propose_claim`)는 같은 검사를 먼저 하고 병합한다. 수리 경로에
        이 검사가 없어 실제 run이 죽었다.
        """
        result = await self.db.execute(
            select(DAClaim.id).where(
                DAClaim.run_id == self.run_id,
                DAClaim.hash == normalized_hash,
                DAClaim.id != exclude_id,
            )
        )
        return result.first() is not None

    async def _apply_repairs(
        self,
        question_id: str,
        repairs: list[RepairResult],
    ) -> None:
        for repair in repairs:
            claim = await self.get_claim(repair.claim_id)
            if claim is None:
                continue
            if repair.action in ("fixed", "weakened"):
                if repair.new_text:
                    normalized_hash = claim_hash(repair.new_text)
                    if normalized_hash != claim.hash and await self._claim_hash_taken(
                        normalized_hash, exclude_id=claim.id
                    ):
                        # 수리가 run 안의 다른 클레임과 같은 문장으로 수렴했다.
                        # weaken은 문장을 일반화하므로 실제로 자주 일어난다.
                        # 그대로 쓰면 uq_deep_analysis_claims_run_hash를 위반해
                        # 라운드 전체 트랜잭션이 죽는다. 내용은 이미 다른 행에
                        # 있으므로 중복을 재검증하지 않고 abandoned와 같이 처리한다.
                        claim.status = "unverified"
                        await self._resolve_feedback(repair.claim_id)
                        continue
                    claim.text = repair.new_text
                    claim.hash = normalized_hash
                claim.status = "pending"
                for proposed in repair.new_evidence:
                    self.db.add(
                        DAEvidence(
                            id=_hex_id(),
                            run_id=self.run_id,
                            claim_id=claim.id,
                            source_url=proposed.source_url,
                            excerpt=proposed.excerpt[
                                : settings.config.deep_analysis.excerpt_max_chars
                            ],
                            raw_ref=proposed.raw_ref,
                        )
                    )
            elif repair.action == "abandoned":
                claim.status = "unverified"
            await self._resolve_feedback(repair.claim_id)
        await self.db.flush()

    async def commit_pass(
        self,
        question_id: str,
        result: WorkerResult,
        verdicts: dict[str, Verdict],
        *,
        judge_tokens_spent: int,
    ) -> None:
        """`judge_tokens_spent`: 이번 패스에서 판정자가 실제로 쓴 토큰의 총합.

        `verdicts.values()` 를 여기서 다시 더하지 않는다 -- `verdicts` 는
        클레임 텍스트로 키잉되어 있어(§6.1.3/D3 Ledger의 해시 병합과
        맞추려는 것) **조회용**이지 **집계용**이 아니다. 한 패스 안에서
        같은 텍스트 클레임이 두 번 나오면(`_upsert_claim`이 해시로 병합하는
        바로 그 경우) `_grade()` 는 두 번 다 돌고 판정자도 두 번 다
        디스패치될 수 있는데, dict에는 두 번째 판정만 남는다. 그래서 호출부
        (오케스트레이터의 채점 루프)가 `_grade()` 를 호출할 때마다 실제로
        쓴 토큰을 직접 누적해 여기로 넘긴다 -- dict를 다시 훑지 않으므로
        두 번째가 첫 번째를 덮어써도 유실되지 않는다 (C3-m1 Finding 2).

        **기본값이 없고 keyword-only 다 (C3-m2).** 회계 인자에 기본값 0을 두면
        빠뜨린 호출자가 에러 없이 **덜 청구**한다 -- C3-m1 이 닫은 침묵 과소
        계상과 같은 모양이다. 판정자가 없어 참값이 0인 호출부도 `0` 을 직접
        적는다: "판정자가 안 돌았다" 와 "넘기는 것을 잊었다" 는 원장에서
        구별되지 않으므로, 구별을 호출부에 남긴다.
        """
        if result.question_id != question_id:
            raise ValueError(
                "worker result question does not match commit target"
            )

        question = await self.get_question(question_id)
        if question is None:
            raise KeyError(question_id)
        if question.status != "investigating":
            raise IllegalTransition(
                f"commit requires investigating, got {question.status}"
            )

        await self._lock()

        for blob in result.blobs:
            await self._store_blob(blob)

        verified_count = 0
        for proposed_claim in result.claims:
            claim_id, evidence_rows = await self._upsert_claim(
                question_id,
                proposed_claim,
            )
            verdict = verdicts.get(claim_id) or verdicts.get(
                proposed_claim.text
            )
            if await self._record_verdict(
                question_id,
                claim_id,
                evidence_rows,
                verdict,
            ):
                verified_count += 1
        verified_any = verified_count > 0

        await self._apply_repairs(question_id, result.repairs)

        for dead_end in result.dead_ends:
            await self.log("dead_end", question_id, {"text": dead_end})

        # C3-m1: `result.tokens_spent` 는 워커 자신의 지출(검색·entailment·
        # repair 호출)일 뿐, 워커가 낸 클레임을 심사하는 판정자의 지출은
        # 들어 있지 않았다. `judge_tokens_spent` 는 호출부가 누적해 넘긴
        # 값이다 -- 왜 여기서 `verdicts.values()` 를 다시 더하지 않는지는
        # 위 독스트링 참고 (dict는 조회용이라 중복 텍스트에서 유실된다).
        # 워커 지출과 판정자 지출은 서로 다른 LLM 호출의 합계라 겹칠 수
        # 없다 -- 워커는 심사하지 않고 판정자는 검색하지 않는다.
        #
        # 이 변경으로 `DAQuestion.spent_tokens`(그리고 `total_spent()`,
        # `budgeter.should_stop()`)가 이전보다 커진다: 판정자의 토큰은
        # 원래도 전역 `TokenBudget`에서 실제로 빠져나간 지출이었고, 질문별
        # 원장에만 안 잡혔을 뿐이다. 조사가 같은 예산으로 조금 더 일찍
        # 멈추는 것은 의도된 보정이지 되돌려야 할 회귀가 아니다.
        question.spent_tokens += result.tokens_spent + judge_tokens_spent
        question.confidence = max(
            question.confidence,
            result.self_assessment,
        )

        if result.status == "failed":
            question.fail_streak += 1
            await self._transition(question_id, "open")
        elif (
            result.status == "completed"
            and verified_any
            and question.confidence >= self.resolve_threshold
        ):
            question.fail_streak = 0
            await self._transition(question_id, "resolved")
        else:
            await self._transition(question_id, "open")

        clamp_counts = _safe_clamp_counts(
            result.confidence_clamped_by_source_count
        )
        await self.log(
            "pass_completed",
            question_id,
            {
                "status": result.status,
                "new_claims": len(result.claims),
                "verified": verified_count,
                "tokens": result.tokens_spent,
                # 질문이 닫히는지를 결정하는 유일한 수인데 여태 원장에 없었다.
                # 해결 조건은 `verified_any AND max(self_assessment) >=
                # resolve_threshold` 이고, 표본 #16~#19 에서 645개 질문 중 9개만
                # 그 문턱을 넘었다. 그런데 이 값이 패스마다 얼마였는지는 어디에도
                # 남지 않아, "워커가 낮게 매긴다" 와 "높게 매긴 패스가 있었는데
                # 다른 조건에 걸렸다" 를 구분할 수 없었다.
                #
                # `resolved_gate` 는 그 판정을 그대로 적는다 -- 세 갈래(문턱 미달 /
                # 검증 클레임 0 / 실패 상태) 중 무엇이 막았는지 사후에 세려면
                # 계산된 결과가 필요하다. 사유를 나중에 재구성하려 들면 D59 처럼
                # 지표가 틀린다.
                "self_assessment": result.self_assessment,
                "question_confidence": question.confidence,
                "resolve_threshold": self.resolve_threshold,
                "resolved_gate": (
                    "resolved"
                    if question.status == "resolved"
                    else "failed_status"
                    if result.status == "failed"
                    else "no_verified_claim"
                    if not verified_any
                    else "below_threshold"
                ),
                "confidence_clamped_count": sum(clamp_counts.values()),
                "confidence_clamped_by_source_count": clamp_counts,
                **{
                    f"search_{key}": value
                    for key, value in sorted(
                        result.search_augmentation.items()
                    )
                    if isinstance(value, int)
                },
            },
        )
        await self.db.flush()

    async def open_questions(self) -> list[DAQuestion]:
        result = await self.db.execute(
            select(DAQuestion)
            .where(
                DAQuestion.run_id == self.run_id,
                DAQuestion.status == "open",
            )
            .order_by(DAQuestion.depth, DAQuestion.id)
        )
        return list(result.scalars())

    async def questions(self) -> list[DAQuestion]:
        result = await self.db.execute(
            select(DAQuestion)
            .where(DAQuestion.run_id == self.run_id)
            .order_by(DAQuestion.depth, DAQuestion.id)
        )
        return list(result.scalars())

    async def children(self, question_id: str) -> list[DAQuestion]:
        result = await self.db.execute(
            select(DAQuestion)
            .where(
                DAQuestion.run_id == self.run_id,
                DAQuestion.parent_id == question_id,
            )
            .order_by(DAQuestion.id)
        )
        return list(result.scalars())

    async def get_claim(self, claim_id: str) -> DAClaim | None:
        return await self.db.get(DAClaim, (claim_id, self.run_id))

    async def claim_source_urls(self, claim_id: str) -> list[str]:
        """Source URLs of a claim's evidence, run-scoped (dedup, ordered).

        Used by conflict resolution (M4 §6.7) to compare the source-domain
        tier of two conflicting claims without pulling in full evidence
        rows.
        """
        result = await self.db.execute(
            select(DAEvidence.source_url).where(
                DAEvidence.run_id == self.run_id,
                DAEvidence.claim_id == claim_id,
            )
        )
        urls: list[str] = []
        for url in result.scalars():
            if url not in urls:
                urls.append(url)
        return urls

    async def get_blob(self, content_hash: str) -> DABlob | None:
        return await self.db.get(DABlob, (self.run_id, content_hash))

    async def verified_claims(
        self,
        question_id: str,
    ) -> list[tuple[DAClaim, list[DAEvidence]]]:
        result = await self.db.execute(
            select(DAClaim).where(
                DAClaim.run_id == self.run_id,
                DAClaim.question_id == question_id,
                DAClaim.status == "verified",
            )
        )
        output: list[tuple[DAClaim, list[DAEvidence]]] = []
        for claim in result.scalars():
            evidence_result = await self.db.execute(
                select(DAEvidence).where(
                    DAEvidence.run_id == self.run_id,
                    DAEvidence.claim_id == claim.id,
                )
            )
            output.append((claim, list(evidence_result.scalars())))
        return output

    async def root_question(self) -> DAQuestion | None:
        result = await self.db.execute(
            select(DAQuestion).where(
                DAQuestion.run_id == self.run_id,
                DAQuestion.parent_id.is_(None),
            )
        )
        return result.scalars().first()

    async def total_spent(self) -> int:
        value = await self.db.scalar(
            select(func.coalesce(func.sum(DAQuestion.spent_tokens), 0)).where(
                DAQuestion.run_id == self.run_id
            )
        )
        return int(value or 0)

    async def report_markdown(self) -> str | None:
        """This run's final report body, or ``None`` if there isn't one yet.

        Read from the `job_completed` event payload -- NOT from the
        `deep_analysis_runs.report_path` column, which is always NULL. The
        body has been persisted since the job service landed: `jobs.py`
        puts it in that payload so a late subscriber replaying the event
        stream receives the report without a second request (AC6). The
        column is a missing pointer, not a missing body.

        Returns ``None`` for a run that failed or has not finished, and for
        a payload that carries no `report_markdown` key -- callers get one
        answer for "no report", not an exception to distinguish.
        """
        raw = await self.db.scalar(
            select(DAEvent.payload)
            .where(
                DAEvent.run_id == self.run_id,
                DAEvent.kind == "job_completed",
            )
            .order_by(DAEvent.seq.desc())
            .limit(1)
        )
        if raw is None:
            return None
        try:
            payload = raw if isinstance(raw, dict) else json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        body = payload.get("report_markdown")
        return body if isinstance(body, str) else None

    async def degradations(self) -> list[dict[str, Any]]:
        """이 run 이 리포트 품질을 깎은 사건들 -- kind 별 합산, 최초 발생 순서 보존.

        새로고침 후 챗 UI 가 강등을 다시 그릴 수 있는 **유일한 출처**다. 라이브
        스트림은 프론트가 이벤트를 직접 접어 만들지만(`progress.ts`), 종결된 run 은
        다시 구독하지 않으므로 그 상태가 남지 않는다. `jobs.execute_run` 이 이
        값을 어시스턴트 메시지 메타데이터로 넘긴다.

        판정 규칙과 그 중복에 대해서는 `_degradation_kind()` 주석을 볼 것.

        3회와 1회는 다른 이야기이므로 집합이 아니라 카운트로 돌려준다(D26).
        """
        rows = (
            await self.db.execute(
                select(DAEvent.kind, DAEvent.payload)
                .where(
                    DAEvent.run_id == self.run_id,
                    DAEvent.kind.in_(_DEGRADATION_KINDS),
                )
                .order_by(DAEvent.seq)
            )
        ).all()

        # dict 는 삽입 순서를 보존한다 -- 최초 발생 순서가 그대로 결과 순서다.
        counts: dict[str, int] = {}
        for kind, raw in rows:
            resolved = _degradation_kind(kind, _payload_dict(raw))
            if resolved is None:
                continue
            counts[resolved] = counts.get(resolved, 0) + 1
        return [{"kind": kind, "count": count} for kind, count in counts.items()]

    async def complete_run(self, report_path: str | None = None) -> None:
        run = await self.db.get(DARun, self.run_id)
        if run is None:
            raise KeyError(self.run_id)
        run.status = "completed"
        run.report_path = report_path
        await self.db.flush()

    async def fail_run(self) -> None:
        run = await self.db.get(DARun, self.run_id)
        if run is None:
            raise KeyError(self.run_id)
        run.status = "failed"
        await self.db.flush()

    async def gain_history(self, question_id: str, last_n: int = 3) -> list[int]:
        result = await self.db.execute(
            select(DAEvent.payload)
            .where(
                DAEvent.run_id == self.run_id,
                DAEvent.qid == question_id,
                DAEvent.kind == "pass_completed",
            )
            .order_by(DAEvent.seq.desc())
            .limit(last_n)
        )
        counts: list[int] = []
        for payload in result.scalars():
            try:
                counts.append(int(json.loads(payload).get("verified", 0)))
            except (ValueError, TypeError):
                counts.append(0)
        return counts

    async def verified_summaries(self, question_id: str) -> str:
        pairs = await self.verified_claims(question_id)
        if not pairs:
            return "(없음)"
        return "\n".join(f"- {claim.text}" for claim, _ in pairs)

    async def unverified_and_deadends(self, question_id: str) -> list[str]:
        out: list[str] = []
        events = await self.db.execute(
            select(DAEvent.payload).where(
                DAEvent.run_id == self.run_id,
                DAEvent.qid == question_id,
                DAEvent.kind == "dead_end",
            )
        )
        for payload in events.scalars():
            try:
                out.append(str(json.loads(payload).get("text", "")))
            except (ValueError, TypeError):
                continue
        claims = await self.db.execute(
            select(DAClaim.text).where(
                DAClaim.run_id == self.run_id,
                DAClaim.question_id == question_id,
                DAClaim.status == "unverified",
            )
        )
        out.extend(str(t) for t in claims.scalars())
        return out

    async def record_abandon(self, question_id: str) -> None:
        await self._transition(question_id, "abandoned")
        await self.log("abandoned", question_id, {})

    async def remaining_budget(self, question_id: str) -> int:
        question = await self.get_question(question_id)
        if question is None:
            raise KeyError(question_id)
        return max(0, question.cap_tokens - question.spent_tokens)


async def purge_run(db: AsyncSession, run_id: str) -> int:
    """run 하나와 그에 딸린 모든 행을 지운다. 지워진 run 수(0 또는 1).

    **왜 모듈 함수인가.** `Ledger` 는 run 하나에 바인딩된 단일 작성자이고
    (설계 §1 P2), purge 는 그 run 의 *생애 밖에서* 일어나는 관리 작업이다.
    인스턴스 메서드로 두면 "자기 자신을 지운 원장" 이라는 쓸 수 없는 객체가
    남는다.

    **왜 플래그가 필요한가.** `deep_analysis_events` 에는 UPDATE/DELETE 를
    거부하는 트리거가 있고(036), `runs → events` FK 는 `ON DELETE CASCADE` 다.
    겹치면 이벤트가 하나라도 있는 run 은 삭제할 수 없다 -- 마이그레이션 048 이
    그 트리거를 "이 세션 변수가 켜져 있을 때만 통과" 로 바꿨다.

    ⚠️ **`SET LOCAL` 이어야 한다.** 그냥 `SET` 이면 플래그가 커넥션에 남고,
    그 커넥션이 풀로 돌아간 뒤 **다음 요청이 append-only 없이 돈다.** 커넥션
    풀에서는 조용하고 재현이 어려운 종류의 사고다. `SET LOCAL` 은 트랜잭션과
    함께 끝난다 -- 그래서 이 함수는 호출자의 트랜잭션 안에서 돌아야 하며,
    커밋은 호출자가 한다.

    ⚠️ **이 함수를 부르는 프로덕션 경로는 아직 없다.** 로드맵 §7 SCHEMA2 가
    말한 것은 "구조적으로 불가능" 이었고, 이 함수가 그것을 "정책이 정하면
    가능" 으로 바꾼다. 무엇을 언제 지울지는 별개 결정이다 -- §10.1 이
    `deep_analysis_events` 를 "지우면 재현 불가" 로 못박았으므로 가볍게 부르지
    말 것.
    """
    await db.execute(text("SET LOCAL deep_analysis.allow_purge = 'on'"))
    result = await db.execute(
        text("DELETE FROM deep_analysis_runs WHERE id = :run_id"),
        {"run_id": run_id},
    )
    return result.rowcount or 0
