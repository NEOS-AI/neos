"""Run-scoped, single-writer ledger for the Deep Analysis Harness."""

from __future__ import annotations

import json
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

from .models import ProposedBlob, ProposedClaim, Verdict, WorkerResult
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
    ) -> None:
        self.db = session
        self.run_id = run_id
        self.resolve_threshold = (
            settings.DEEP_ANALYSIS_RESOLVE_THRESHOLD
            if resolve_threshold is None
            else resolve_threshold
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

        grade = "ok" if verdict.ok else verdict.code
        for evidence in evidence_rows:
            evidence.det_grade = grade

        if verdict.ok:
            claim.status = "verified"
            await self.log(
                "claim_verified",
                question_id,
                {"claim_id": claim_id},
            )
            return True

        claim.status = "rejected"
        self.db.add(
            DAFeedback(
                run_id=self.run_id,
                claim_id=claim_id,
                code=verdict.code,
                detail=verdict.detail[:200],
                salvage=verdict.salvage,
                attempt=1,
            )
        )
        await self.log(
            "claim_rejected",
            question_id,
            {"claim_id": claim_id, "code": verdict.code},
        )
        return False

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

        verified_any = False
        for proposed_claim in result.claims:
            claim_id, evidence_rows = await self._upsert_claim(
                question_id,
                proposed_claim,
            )
            verdict = verdicts.get(claim_id) or verdicts.get(
                proposed_claim.text
            )
            verified_any = (
                await self._record_verdict(
                    question_id,
                    claim_id,
                    evidence_rows,
                    verdict,
                )
                or verified_any
            )

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
            await self._transition(question_id, "resolved")
        else:
            await self._transition(question_id, "open")

        await self.log(
            "pass_completed",
            question_id,
            {
                "status": result.status,
                "new_claims": len(result.claims),
                "tokens": result.tokens_spent,
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
