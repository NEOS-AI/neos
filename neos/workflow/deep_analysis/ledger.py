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
        """
        claim = await self.get_claim(claim_id)
        if claim is None or claim.question_id != question_id:
            return False
        await self._lock()
        evidence_rows = await self._evidence_for_claim(claim_id)
        result = await self._apply_verdict(question_id, claim, evidence_rows, verdict)
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
    ) -> None:
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

        question.spent_tokens += result.tokens_spent
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
                "confidence_clamped_count": sum(clamp_counts.values()),
                "confidence_clamped_by_source_count": clamp_counts,
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
