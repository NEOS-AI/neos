"""`/evidence` 한도 회계를 원장에 잇는다 (계약 §3.1 · §9 결정 4).

`decide_fetch_admission` 은 **무엇을 얼마나 청구하는가**만 정하는 순수
함수다(그래서 DB 없이 검사된다). 그 판단을 실제 원장에 적용하는 층이 여기다:

- 쓴 바이트는 `DAQuestion.evidence_bytes` 에서 읽는다. 메모리가 아니라 행에
  두는 이유는 run 이 재개돼도 한도를 잊지 않아야 하기 때문이다.
- blob 은 **건별로** 커밋한다. 배치로 모았다가 끝에 쓰면 워커가 지금 읽는
  파일이 아직 원장에 없다.
- 청구는 커밋 **뒤**다. 순서가 뒤집히면 커밋이 실패했을 때 바이트만 깎인다.

이 어댑터는 **오케스트레이터 쪽**이라 원장을 들고 있어도 된다 -- 그것이
워커 쪽 포트(`ResearchToolPort`)가 원장을 모르게 하는 방법이다(I2).

원장 경로는 Postgres 를 요구해 이 기계에서 돌지 않으므로, 여기서는 원장
자리에 가짜를 넣고 **어댑터가 무엇을 어떤 순서로 부르는지**를 고정한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.no_db


@dataclass
class _Blob:
    content_hash: str
    source_url: str = "https://example.com/doc"
    http_status: int = 200
    raw_text: str = "hello"


class _FakeQuestion:
    def __init__(self, evidence_bytes: int = 0) -> None:
        self.evidence_bytes = evidence_bytes


class _FakeDb:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def flush(self) -> None:
        self._calls.append("flush")


class _FakeLedger:
    """`Ledger` 중 어댑터가 쓰는 표면만."""

    def __init__(
        self, *, question: _FakeQuestion, stored: frozenset[str] = frozenset()
    ) -> None:
        self.calls: list[str] = []
        self.db = _FakeDb(self.calls)
        self.question = question
        self._stored = set(stored)
        self.committed: list[_Blob] = []

    async def get_question(self, question_id: str):
        self.calls.append(f"get_question:{question_id}")
        return self.question

    async def get_blob(self, content_hash: str):
        return object() if content_hash in self._stored else None

    async def commit_blobs(self, blobs) -> None:
        self.calls.append("commit_blobs")
        self.committed.extend(blobs)
        for blob in blobs:
            self._stored.add(blob.content_hash)


def _store(ledger, question_id: str = "q_1"):
    from neos.workflow.deep_analysis.evidence_store import LedgerEvidenceStore

    return LedgerEvidenceStore(ledger, question_id=question_id)


@pytest.mark.asyncio
async def test_spent_bytes_comes_from_the_question_row() -> None:
    ledger = _FakeLedger(question=_FakeQuestion(evidence_bytes=1234))

    assert await _store(ledger).spent_bytes() == 1234


@pytest.mark.asyncio
async def test_a_question_that_has_not_fetched_yet_has_spent_nothing() -> None:
    ledger = _FakeLedger(question=_FakeQuestion())

    assert await _store(ledger).spent_bytes() == 0


@pytest.mark.asyncio
async def test_is_stored_asks_the_ledger_for_the_blob() -> None:
    ledger = _FakeLedger(
        question=_FakeQuestion(), stored=frozenset({"abc123def456ffff"})
    )
    store = _store(ledger)

    assert await store.is_stored("abc123def456ffff") is True
    assert await store.is_stored("0000000000000000") is False


@pytest.mark.asyncio
async def test_commit_stores_the_blob_then_charges_the_bytes() -> None:
    """순서가 뒤집히면 커밋이 실패했을 때 바이트만 깎인다."""
    ledger = _FakeLedger(question=_FakeQuestion())

    await _store(ledger).commit(_Blob("abc123def456ffff"), bytes_charged=40)

    assert [call for call in ledger.calls if call != "get_question:q_1"] == [
        "commit_blobs",
        "flush",
    ]
    assert [blob.content_hash for blob in ledger.committed] == ["abc123def456ffff"]
    assert ledger.question.evidence_bytes == 40


@pytest.mark.asyncio
async def test_each_fetch_is_its_own_commit() -> None:
    """건별 커밋 -- 워커가 읽는 파일은 이미 원장에 있어야 한다."""
    ledger = _FakeLedger(question=_FakeQuestion())
    store = _store(ledger)

    await store.commit(_Blob("aaaaaaaaaaaaaaaa"), bytes_charged=10)
    await store.commit(_Blob("bbbbbbbbbbbbbbbb"), bytes_charged=25)

    assert ledger.calls.count("commit_blobs") == 2
    assert ledger.question.evidence_bytes == 35


@pytest.mark.asyncio
async def test_a_blob_already_stored_is_committed_but_charged_nothing() -> None:
    """dedup 된 blob 은 새 공간을 쓰지 않는다.

    그래도 `commit_blobs` 를 부른다 -- 원장의 `_store_blob` 이
    `(run_id, content_hash)` 로 일찍 돌아가므로 두 번 넣지 않고, 어댑터가
    "이미 있으니 건너뛰자" 를 스스로 판단하면 그 규칙이 두 곳에 생긴다.
    """
    ledger = _FakeLedger(
        question=_FakeQuestion(evidence_bytes=999),
        stored=frozenset({"abc123def456ffff"}),
    )

    await _store(ledger).commit(_Blob("abc123def456ffff"), bytes_charged=0)

    assert ledger.calls.count("commit_blobs") == 1
    assert ledger.question.evidence_bytes == 999


@pytest.mark.asyncio
async def test_a_missing_question_is_an_error_not_a_silent_zero() -> None:
    """질문이 없으면 한도를 셀 수 없다. 0 으로 읽으면 한도가 사라진다."""
    ledger = _FakeLedger(question=_FakeQuestion())
    ledger.question = None  # type: ignore[assignment]

    with pytest.raises(KeyError):
        await _store(ledger).spent_bytes()
