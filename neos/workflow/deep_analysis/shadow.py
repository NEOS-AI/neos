"""오프라인 섀도의 원장 (로드맵 J3).

J3 는 "저장된 blob·카세트로 코딩 워커를 돌려 **제안만 비교**한다. 원장에
쓰지 않는다" 이다. 그런데 조사 경로는 네 군데에서 원장에 쓴다:

1. `LedgerEvidenceStore.commit` → `ledger.commit_blobs([blob])`
2. 같은 곳 → `question.evidence_bytes = ... + bytes_charged`
3. 같은 곳 → `ledger.db.flush()`
4. `LedgerEvidenceStore.record_fetched` → `ledger.log(...)`

넷을 막지 않으면 섀도가 **비교 대상을 오염시킨다.** 같은 run 을 두 번 돌리면
두 번째는 첫 번째가 남긴 blob 과 바이트 위에서 돈다.

## 버리지 않고 수집한다

섀도의 값은 **하지 않은 쓰기**에 있다 -- 무엇을 썼을 것인가가 곧 비교
재료다. 조용히 버리면 "아무 일도 없었다" 와 "이런 일이 있었을 것이다" 가
구별되지 않는다.

## 통과 목록을 명시한다

`__getattr__` 이 분류되지 않은 이름을 **터뜨린다.** 반대로 하면(모르는 것은
통과) 원장에 쓰기 메서드가 하나 늘 때마다 섀도가 조용히 새고, 그 사실은
섀도 실행이 프로덕션 데이터를 바꾼 **뒤에** 드러난다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .fetch import FetchUnavailable

__all__ = [
    "BlobArchive",
    "FetchUnavailable",
    "ShadowLedger",
    "ShadowLedgerEscape",
    "ShadowQuestion",
]


class ShadowLedgerEscape(AttributeError):
    """섀도가 분류하지 않은 원장 표면에 손이 닿았다.

    `AttributeError` 를 상속하는 이유는 `hasattr`·`getattr(.., default)` 같은
    탐색이 이것을 정상적인 "없음" 으로 읽어야 하기 때문이다. 조사 경로가
    실제로 **부르는** 자리에서는 그대로 터진다.
    """


@dataclass
class ShadowQuestion:
    """질문 행의 **복사본**. 섀도 안에서만 자란다.

    진짜 행을 넘겨주면 `db.flush()` 를 막아도 소용없다 -- `commit` 이 그
    객체의 `evidence_bytes` 를 직접 올리고, 그 세션의 다음 커밋이 실어
    보낸다.
    """

    id: str
    evidence_bytes: int = 0
    spent_tokens: int = 0


class _ShadowDb:
    """`ledger.db` 자리. flush 는 아무 일도 하지 않는다.

    진짜 세션의 flush 는 그때까지 더럽혀진 **모든** 객체를 내보낸다 -- 섀도가
    만진 것뿐 아니라 그 세션에 매달린 다른 무엇이든.
    """

    def __init__(self) -> None:
        self.flushes = 0

    async def flush(self) -> None:
        self.flushes += 1


@dataclass
class ShadowLedger:
    """읽기는 진짜 원장으로, 쓰기는 이 객체 안으로.

    조사 경로가 원장에서 실제로 쓰는 표면만 갖는다. 나머지는 `__getattr__`
    이 `ShadowLedgerEscape` 로 막는다.
    """

    ledger: Any
    committed_blobs: list[Any] = field(default_factory=list)
    logged_events: list[tuple] = field(default_factory=list)
    _questions: dict[str, ShadowQuestion] = field(default_factory=dict)
    db: _ShadowDb = field(default_factory=_ShadowDb)

    @property
    def run_id(self) -> str:
        return self.ledger.run_id

    # ---- 읽기 -----------------------------------------------------------

    async def get_blob(self, content_hash: str):
        return await self.ledger.get_blob(content_hash)

    async def get_claim(self, claim_id: str):
        return await self.ledger.get_claim(claim_id)

    async def claim_source_urls(self, claim_id: str) -> list[str]:
        return await self.ledger.claim_source_urls(claim_id)

    async def get_question(self, question_id: str) -> ShadowQuestion | None:
        """복사본을 돌려주되 **같은 복사본**을 계속 돌려준다.

        매번 새로 뜨면 `evidence_bytes` 가 영원히 0 이고, 그러면 섀도는
        프로덕션이 거절했을 증거 위에서 제안을 만든다 -- 그 비교는
        프로덕션에 대해 아무 말도 해주지 못한다.
        """
        existing = self._questions.get(question_id)
        if existing is not None:
            return existing
        row = await self.ledger.get_question(question_id)
        if row is None:
            # 없는 질문을 지어내지 않는다. `LedgerEvidenceStore` 는 셀 수
            # 없으면 멈추도록 돼 있고, 섀도가 그것을 무력화하면 안 된다.
            return None
        copy = ShadowQuestion(
            id=question_id,
            evidence_bytes=int(getattr(row, "evidence_bytes", 0) or 0),
            spent_tokens=int(getattr(row, "spent_tokens", 0) or 0),
        )
        self._questions[question_id] = copy
        return copy

    # ---- 쓰기 (수집) -----------------------------------------------------

    async def commit_blobs(self, blobs: list[Any]) -> None:
        self.committed_blobs.extend(blobs)

    async def log(self, kind: str, qid: str | None, payload: dict) -> None:
        self.logged_events.append((kind, qid, payload))

    # ---- 나머지 ---------------------------------------------------------

    def __getattr__(self, name: str):
        raise ShadowLedgerEscape(
            f"{name!r} 은 섀도 원장이 분류하지 않은 표면이다 -- 읽기면 "
            f"위임하고 쓰기면 수집하도록 `ShadowLedger` 에 추가할 것. "
            "모르는 것을 통과시키면 섀도가 프로덕션 데이터를 바꾼다."
        )


class BlobArchive:
    """기록된 run 이 가져온 blob 들. 섀도의 `fetch_fn` 자리에 들어간다.

    **원장이 저장한 blob 그대로**를 담는다. 본문에서 주소를 다시 계산하지
    않는 이유는 빈 본문 때문이다 -- `fetch._blob_hash` 는 그때 상태와 URL 을
    섞어 주소를 만든다(같은 `sha256("")` 로 뭉치면 죽은 404 하나가 다른
    출처들의 상태를 물려받는다). 본문만으로 되짚으면 그 구별이 사라진다.

    `served` 와 `missed` 는 비교 보고서의 재료다. 섀도가 프로덕션보다 적은
    증거로 돌았다면 제안이 빈약한 것은 워커 탓이 아니고, 그 사실이 남지
    않으면 비교가 워커를 잘못 나무란다.
    """

    def __init__(self, pages: dict[str, Any]) -> None:
        self._pages = dict(pages)
        self.served: list[str] = []
        self.missed: list[str] = []

    async def fetch(self, url: str, **_ignored: Any) -> Any:
        """`fetch_url` 과 같은 자리. 네트워크에 닿지 않는다.

        `fetch_url` 의 나머지 인자(`client`·`cassette`·`on_attempt`)는 받되
        쓰지 않는다 -- 재생된 fetch 는 HTTP 요청을 한 적이 없으므로 시도
        보고는 거짓말이 된다(`fetch_url` 이 카세트 경로에서 `on_attempt` 를
        부르지 않는 것과 같은 이유다).
        """
        blob = self._pages.get(url)
        if blob is None:
            self.missed.append(url)
            raise FetchUnavailable(f"{url} is not in the shadow archive")
        self.served.append(url)
        return blob
