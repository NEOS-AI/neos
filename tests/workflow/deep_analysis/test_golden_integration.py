from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis.cassette import Cassette
from neos.workflow.deep_analysis.citation import CitationRenderer
from neos.workflow.deep_analysis.fetch import fetch_url
from neos.workflow.deep_analysis.graders.deterministic import (
    DeterministicGrader,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.synthesizer import Synthesizer
from neos.workflow.deep_analysis.worker import Worker


pytestmark = pytest.mark.no_db


@dataclass
class MemoryQuestion:
    id: str
    text: str
    parent_id: str | None
    depth: int
    status: str = "open"
    spent_tokens: int = 0
    value_est: float = 1.0
    confidence: float = 0.0
    cap_tokens: int = 999_999
    fail_streak: int = 0


class MemoryLedger:
    def __init__(self):
        self.questions_by_id = {}
        self.blobs = {}
        self.claims = {}
        self.evidence = {}
        self.events = []
        self.completed = False

    async def recover(self):
        recovered = 0
        for question in self.questions_by_id.values():
            if question.status == "investigating":
                question.status = "open"
                recovered += 1
        return recovered

    async def root_question(self):
        return next(
            (
                question
                for question in self.questions_by_id.values()
                if question.parent_id is None
            ),
            None,
        )

    async def open_question(
        self,
        text,
        parent_id,
        value_est,
        cap_tokens,
        depth,
    ):
        question_id = f"{len(self.questions_by_id) + 1:08x}"
        self.questions_by_id[question_id] = MemoryQuestion(
            question_id,
            text,
            parent_id,
            depth,
            value_est=value_est,
            cap_tokens=cap_tokens,
        )
        return question_id

    async def record_split(self, question_id, child_ids):
        await self._transition(question_id, "split")
        await self.log("split", question_id, {"children": child_ids})

    async def open_questions(self):
        return [
            question
            for question in self.questions_by_id.values()
            if question.status == "open"
        ]

    async def children(self, question_id):
        return [
            question
            for question in self.questions_by_id.values()
            if question.parent_id == question_id
        ]

    async def total_spent(self):
        return sum(
            question.spent_tokens
            for question in self.questions_by_id.values()
        )

    async def gain_history(self, question_id, last_n=3):
        return []

    async def _transition(self, question_id, status):
        self.questions_by_id[question_id].status = status

    async def commit_blobs(self, blobs):
        for blob in blobs:
            self.blobs[blob.content_hash] = blob

    async def get_blob(self, content_hash):
        return self.blobs.get(content_hash)

    async def commit_pass(self, question_id, result, verdicts):
        for proposed in result.claims:
            claim_id = "c1a1c1a1"
            verdict = verdicts[proposed.text]
            claim = SimpleNamespace(
                id=claim_id,
                question_id=question_id,
                text=proposed.text,
                confidence=proposed.confidence,
                status="verified" if verdict.ok else "rejected",
            )
            self.claims[claim_id] = claim
            self.evidence[claim_id] = [
                SimpleNamespace(
                    excerpt=item.excerpt,
                    source_url=item.source_url,
                )
                for item in proposed.evidence
            ]
        question = self.questions_by_id[question_id]
        question.spent_tokens += result.tokens_spent
        question.status = "resolved"
        await self.log(
            "pass_completed",
            question_id,
            {"tokens": result.tokens_spent},
        )

    async def verified_claims(self, question_id):
        return [
            (claim, self.evidence[claim.id])
            for claim in self.claims.values()
            if claim.question_id == question_id
            and claim.status == "verified"
        ]

    async def get_claim(self, claim_id):
        return self.claims.get(claim_id)

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))

    async def complete_run(self):
        self.completed = True

    async def fail_run(self):
        raise AssertionError("golden run failed")


class ScriptedAnthropic:
    def __init__(self):
        self.messages = self
        self.responses = [
            '{"subquestions":[{"text":"How does routing affect cost?",'
            '"value_est":0.8}]}',
            '{"status":"completed","claims":[{"text":"MoE routing lowers '
            'inference cost","confidence":0.6,"evidence":[{"source_url":'
            '"https://example.com/source","excerpt":"MoE routing lowers '
            'inference cost","raw_ref":"ignored"}]}],"self_assessment":0.8,'
            '"proposed_subquestions":[],"dead_ends":[]}',
            "## 요약\nMoE routing lowers inference cost [C:c1a1c1a1]\n\n"
            "## 본문\nMoE routing lowers inference cost [C:c1a1c1a1]\n\n"
            "## 한계와 미확인 사항\n단일 출처\n\n## 출처",
        ]

    async def create(self, **kwargs):
        response_text = self.responses.pop(0)

        class Usage:
            input_tokens = 10
            output_tokens = 10

        class Block:
            type = "text"
            text = response_text

        class Response:
            content = [Block()]
            usage = Usage()
            model = kwargs["model"]

        return Response()


class Search:
    async def __call__(self, query, k):
        return [
            {
                "url": "https://example.com/source",
                "title": "Source",
                "snippet": "MoE",
            }
        ]


class Http:
    async def get(self, url):
        class Response:
            status_code = 200
            text = "<p>MoE routing lowers inference cost</p>"

        return Response()


class Forbidden:
    async def __call__(self, *args, **kwargs):
        raise AssertionError("external producer used during replay")

    async def get(self, *args, **kwargs):
        raise AssertionError("HTTP used during replay")

    @property
    def messages(self):
        return self

    async def create(self, **kwargs):
        raise AssertionError("LLM used during replay")


def _orchestrator(ledger, cassette, llm_client, search, http):
    grader = DeterministicGrader(
        ledger,
        quote_threshold=0.92,
        confidence_cap={1: 0.6, 2: 0.8, 3: 0.95},
    )

    def worker_factory():
        return Worker(
            search,
            fetch_fn=fetch_url,
            llm_client=llm_client,
            http_client=http,
            cassette=cassette,
        )

    return Orchestrator(
        object(),
        "run00001",
        worker_factory,
        grader,
        ledger=ledger,
        synthesizer=Synthesizer(
            ledger,
            llm_client=llm_client,
            cassette=cassette,
        ),
        citation_renderer=CitationRenderer(ledger),
        llm_client=llm_client,
        cassette=cassette,
        global_token_cap=1000,
    )


@pytest.mark.asyncio
async def test_recorded_run_replays_to_identical_fully_resolved_report(
    tmp_path,
):
    cassette_path = tmp_path / "golden.json"
    record = Cassette(cassette_path, "record")
    recorded = await _orchestrator(
        MemoryLedger(),
        record,
        ScriptedAnthropic(),
        Search(),
        Http(),
    ).run("What is MoE routing?")
    record.save()

    replay = Cassette(cassette_path, "replay")
    forbidden = Forbidden()
    replayed = await _orchestrator(
        MemoryLedger(),
        replay,
        forbidden,
        forbidden,
        forbidden,
    ).run("What is MoE routing?")

    assert replayed["report_markdown"] == recorded["report_markdown"]
    assert "[C:" not in replayed["report_markdown"]
    assert "[미검증]" not in replayed["report_markdown"]
    assert "https://example.com/source" in replayed["report_markdown"]
