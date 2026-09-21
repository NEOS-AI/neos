"""섀도 원장: 읽기는 통과, 쓰기는 수집 (로드맵 J3).

J3 는 "저장된 blob·카세트로 코딩 워커를 돌려 **제안만 비교**한다. 원장에
쓰지 않는다" 이다. 그런데 조사 경로는 네 군데에서 원장에 쓴다 --
`commit_blobs`, `question.evidence_bytes += n`, `db.flush()`, `log()`.
그 넷을 막지 않으면 섀도가 **비교 대상을 오염시킨다**: 같은 run 을 두 번
섀도로 돌리면 두 번째는 첫 번째가 남긴 blob 과 바이트 위에서 돈다.

**버리지 않고 수집한다.** 섀도의 값은 하지 않은 쓰기에 있다 -- 무엇을 썼을
것인가가 곧 비교 재료다. 조용히 버리면 "아무 일도 없었다" 와 "이런 일이
있었을 것이다" 가 구별되지 않는다.

**한도는 그대로 건다.** 섀도에서 `/evidence` 한도를 풀면 프로덕션이 허용하지
않았을 증거 위에서 제안이 나온다 -- 그 비교는 프로덕션에 대한 말을 해주지
못한다. 그래서 바이트 회계는 메모리에서 **진짜로** 돈다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

pytestmark = pytest.mark.no_db


@dataclass
class _Question:
    id: str = "q_1"
    evidence_bytes: int = 0
    spent_tokens: int = 0


@dataclass
class _Blob:
    content_hash: str
    raw_text: str = "본문"
    http_status: int = 200


@dataclass
class _Db:
    flushes: int = 0

    async def flush(self) -> None:
        self.flushes += 1


@dataclass
class _RealLedger:
    """섀도가 감쌀 대상. 쓰기가 닿으면 여기 흔적이 남는다."""

    question: _Question = field(default_factory=_Question)
    blobs: dict[str, _Blob] = field(default_factory=dict)
    claims: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, list[str]] = field(default_factory=dict)
    committed: list[Any] = field(default_factory=list)
    events: list[tuple] = field(default_factory=list)
    db: _Db = field(default_factory=_Db)
    run_id: str = "run00001"

    async def get_question(self, question_id: str):
        return self.question if question_id == self.question.id else None

    async def get_blob(self, content_hash: str):
        return self.blobs.get(content_hash)

    async def get_claim(self, claim_id: str):
        return self.claims.get(claim_id)

    async def claim_source_urls(self, claim_id: str) -> list[str]:
        return list(self.sources.get(claim_id, []))

    async def commit_blobs(self, blobs) -> None:
        self.committed.extend(blobs)

    async def log(self, kind: str, qid, payload) -> None:
        self.events.append((kind, qid, payload))


def _shadow(real=None):
    from neos.workflow.deep_analysis.shadow import ShadowLedger

    return ShadowLedger(real or _RealLedger())


# ---- 읽기는 통과한다 ------------------------------------------------------------


@pytest.mark.asyncio
async def test_reads_reach_the_real_ledger() -> None:
    """섀도의 요점은 **진짜 데이터**로 도는 것이다 (J3: "저장된 blob")."""
    real = _RealLedger(
        blobs={"aaaa": _Blob("aaaa")},
        claims={"c1": object()},
        sources={"c1": ["https://a"]},
    )
    shadow = _shadow(real)

    assert (await shadow.get_blob("aaaa")).content_hash == "aaaa"
    assert await shadow.get_claim("c1") is real.claims["c1"]
    assert await shadow.claim_source_urls("c1") == ["https://a"]
    assert shadow.run_id == "run00001"


@pytest.mark.asyncio
async def test_a_missing_question_stays_missing() -> None:
    """없는 질문을 지어내지 않는다 -- `LedgerEvidenceStore` 는 셀 수 없으면
    멈추도록(KeyError) 돼 있고, 섀도가 그것을 무력화하면 안 된다."""
    assert await _shadow().get_question("없는질문") is None


# ---- 쓰기는 수집된다 ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_committed_blob_never_reaches_the_real_ledger() -> None:
    real = _RealLedger()
    shadow = _shadow(real)

    await shadow.commit_blobs([_Blob("bbbb")])

    assert real.committed == []
    assert [blob.content_hash for blob in shadow.committed_blobs] == ["bbbb"]


@pytest.mark.asyncio
async def test_an_event_never_reaches_the_real_ledger() -> None:
    real = _RealLedger()
    shadow = _shadow(real)

    await shadow.log("evidence_fetched_for_sandbox", "q_1", {"raw_ref": "bbbb"})

    assert real.events == []
    assert shadow.logged_events == [
        ("evidence_fetched_for_sandbox", "q_1", {"raw_ref": "bbbb"})
    ]


@pytest.mark.asyncio
async def test_a_flush_is_not_a_flush() -> None:
    """`LedgerEvidenceStore.commit` 이 `ledger.db.flush()` 를 부른다.

    진짜 세션의 flush 는 그때까지 더럽혀진 **모든** 객체를 내보낸다 -- 섀도가
    만진 것뿐 아니라 그 세션에 매달린 다른 무엇이든.
    """
    real = _RealLedger()
    shadow = _shadow(real)

    await shadow.db.flush()

    assert real.db.flushes == 0


# ---- 질문 행은 복사본이다 --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_question_handed_out_is_not_the_real_row() -> None:
    """`get_question` 은 세션에 붙은 ORM 행을 돌려준다.

    `LedgerEvidenceStore.commit` 이 그 객체의 `evidence_bytes` 를 **직접
    올린다.** 진짜 행을 넘겨주면 flush 를 막아도 소용없다 -- 그 세션의 다음
    커밋이 실어 보낸다.
    """
    real = _RealLedger()
    shadow = _shadow(real)

    question = await shadow.get_question("q_1")
    question.evidence_bytes = 4096

    assert real.question.evidence_bytes == 0


@pytest.mark.asyncio
async def test_the_copy_starts_from_what_the_real_row_says() -> None:
    """이미 쓴 바이트를 잊으면 섀도가 프로덕션보다 **너그러워진다.**"""
    real = _RealLedger(question=_Question(evidence_bytes=1024))

    question = await _shadow(real).get_question("q_1")

    assert question.evidence_bytes == 1024


@pytest.mark.asyncio
async def test_the_byte_accounting_accumulates_inside_the_shadow() -> None:
    """한도는 섀도 안에서 **진짜로** 돈다.

    매번 새 복사본을 주면 `evidence_bytes` 가 영원히 0 이고, 그러면 섀도는
    프로덕션이 거절했을 증거 위에서 제안을 만든다.
    """
    shadow = _shadow()

    first = await shadow.get_question("q_1")
    first.evidence_bytes += 2048
    second = await shadow.get_question("q_1")

    assert second.evidence_bytes == 2048
    assert second is first


# ---- 새는 곳이 없다 -------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unclassified_method_fails_loudly() -> None:
    """이것이 이 클래스의 설계 전부다.

    통과시키는 목록을 **명시**하고 나머지는 터뜨린다. 반대로 하면(모르는
    것은 통과) 원장에 쓰기 메서드가 하나 늘 때마다 섀도가 조용히 새고,
    그 사실은 섀도 실행이 프로덕션 데이터를 바꾼 **뒤에** 드러난다.
    """
    from neos.workflow.deep_analysis.shadow import ShadowLedgerEscape

    shadow = _shadow()

    with pytest.raises(ShadowLedgerEscape, match="commit_pass"):
        shadow.commit_pass


@pytest.mark.asyncio
async def test_the_escape_names_the_method_it_refused() -> None:
    """이름이 없으면 다음 사람은 무엇을 분류해야 하는지 모른다."""
    from neos.workflow.deep_analysis.shadow import ShadowLedgerEscape

    with pytest.raises(ShadowLedgerEscape) as caught:
        _shadow().regrade_claim

    assert "regrade_claim" in str(caught.value)
