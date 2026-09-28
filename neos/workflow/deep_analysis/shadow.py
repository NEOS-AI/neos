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

from sqlalchemy import select

from neos.database.deep_analysis_models import DABlob, DAClaim

from .fetch import FetchUnavailable
from .models import ProposedBlob
from .research_worker import run_research_worker
from .text_norm import claim_hash

__all__ = [
    "BlobArchive",
    "RecordedClaim",
    "ShadowComparison",
    "build_shadow_worker",
    "compare_claims",
    "load_blob_archive",
    "load_recorded_claims",
    "run_offline_shadow",
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

    # 조사 briefing 과 증거 복원이 읽는다 (J1.5). 섀도의 자식이 프로덕션의
    # 자식과 **같은 briefing** 을 받아야 비교가 워커를 잰다 -- 없으면
    # `getattr(.., None)` 이 조용히 빈 briefing 을 만든다.

    async def verified_claims(self, question_id: str):
        return await self.ledger.verified_claims(question_id)

    async def unverified_and_deadends(self, question_id: str) -> list[str]:
        return await self.ledger.unverified_and_deadends(question_id)

    async def sandbox_evidence_refs(self, question_id: str) -> list[str]:
        return await self.ledger.sandbox_evidence_refs(question_id)

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


@dataclass(frozen=True, slots=True)
class RecordedClaim:
    """기록된 run 이 남긴 클레임 하나. 상태를 **그대로** 들고 다닌다."""

    text: str
    status: str


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    """섀도 제안 대 기록된 run (로드맵 J3: "제안만 비교").

    판정이 아니라 **세 갈래와 그것을 해석할 사실**이다. 조사 워커가 옛 워커와
    다르게 탐색하는 것이 이 비교의 요점이므로, 다름 자체는 실패가 아니다.
    """

    shared: tuple[str, ...]
    only_recorded: tuple[RecordedClaim, ...]
    only_shadow: tuple[str, ...]
    served_urls: tuple[str, ...]
    missed_urls: tuple[str, ...]

    @property
    def evidence_was_complete(self) -> bool:
        """섀도가 요구한 증거를 보관소가 전부 줬는가.

        거짓이면 갈래만 보고 워커를 판단할 수 없다 -- 제안이 빈약한 이유가
        증거가 없어서일 수 있다. 참이면 비교는 증거 차이가 아니라 **판단
        차이**를 말한다. 그 구별이 J3 의 전부다.
        """
        return not self.missed_urls


def compare_claims(
    recorded: list[RecordedClaim],
    proposed: list[Any],
    *,
    served_urls: list[str],
    missed_urls: list[str],
) -> ShadowComparison:
    """같음의 정의를 **원장에서 빌려 온다**.

    `claim_hash` 는 `_upsert_claim` 이 클레임을 병합할 때 쓰는 바로 그
    함수다. 섀도가 자기만의 동일성 규칙을 쓰면 원장이 한 클레임으로 세는
    둘을 여기서는 둘로 세고, 그 차이가 "조사 워커가 새 클레임을 냈다" 로
    보고된다.

    상태를 미리 거르지 않는다. verified 만 비교하면 놓친 것이 좁아 보이고,
    전부 뭉치면 놓친 것의 무게를 알 수 없다 -- 거르는 것은 보고서를 읽는
    쪽의 몫이다.
    """
    recorded_by_hash: dict[str, RecordedClaim] = {}
    for claim in recorded:
        recorded_by_hash.setdefault(claim_hash(claim.text), claim)

    # 제안도 원장과 같은 규칙으로 뭉친다 -- 둘로 세면 "더 많이 냈다" 는
    # 거짓 신호가 생긴다. 첫 등장의 표기를 남긴다.
    proposed_by_hash: dict[str, str] = {}
    for claim in proposed:
        proposed_by_hash.setdefault(claim_hash(claim.text), claim.text)

    shared = tuple(
        text
        for digest, text in proposed_by_hash.items()
        if digest in recorded_by_hash
    )
    return ShadowComparison(
        shared=shared,
        only_recorded=tuple(
            claim
            for digest, claim in recorded_by_hash.items()
            if digest not in proposed_by_hash
        ),
        only_shadow=tuple(
            text
            for digest, text in proposed_by_hash.items()
            if digest not in recorded_by_hash
        ),
        served_urls=tuple(served_urls),
        missed_urls=tuple(missed_urls),
    )


async def load_blob_archive(ledger: Any) -> BlobArchive:
    """기록된 run 의 blob 을 URL 로 색인해 보관소를 만든다.

    URL 로 색인하는 이유는 워커가 URL 로 묻기 때문이다(`fetch.v1`). 한 URL 이
    여러 blob 을 가질 수는 없다 -- 같은 본문은 같은 주소로 dedup 되고, 다른
    본문이면 마지막에 가져온 것이 그 URL 의 현재 모습이다.
    """
    rows = await ledger.db.execute(
        select(DABlob)
        .where(DABlob.run_id == ledger.run_id)
        .order_by(DABlob.fetched_at)
    )
    pages: dict[str, ProposedBlob] = {}
    for row in rows.scalars():
        pages[row.url] = ProposedBlob(
            content_hash=row.content_hash,
            source_url=row.url,
            http_status=int(row.http_status),
            raw_text=row.raw_text or "",
        )
    return BlobArchive(pages)


async def load_recorded_claims(ledger: Any, question_id: str) -> list[RecordedClaim]:
    """그 질문에 대해 기록된 run 이 남긴 클레임들. 상태를 그대로 싣는다."""
    rows = await ledger.db.execute(
        select(DAClaim.text, DAClaim.status).where(
            DAClaim.run_id == ledger.run_id,
            DAClaim.question_id == question_id,
        )
    )
    return [RecordedClaim(text=text, status=status) for text, status in rows]


async def run_offline_shadow(
    ledger: Any,
    assignment: Any,
    *,
    worker: Any,
) -> ShadowComparison:
    """기록된 run 위에서 조사 워커를 돌리고 제안을 맞대 본다 (로드맵 J3).

    `assignment` 를 **인자로 받는다.** 끝난 run 에서 brief 를 되짚는 것은 그
    자체로 추측이고, 추측한 brief 를 주면 워커가 본 것이 프로덕션과 달라진다
    -- 그러면 비교한 것은 두 워커가 아니라 두 프롬프트다.

    `worker` 도 주입이다. 여기서 `run_research_worker` 를 직접 부르면 이
    함수가 샌드박스 provider·런타임 팩토리·채점기까지 알아야 하고, 그것들은
    전부 서비스가 조립하는 것들이다 -- 섀도의 일은 **격리와 재생과 비교**이지
    조사 경로를 다시 조립하는 것이 아니다.

    워커에게 가는 원장은 `ShadowLedger` 다. 진짜 원장을 주면 섀도 실행이
    기록된 run 을 바꾸고, 그러면 그 run 은 더 이상 비교 **대상**이 아니다.
    """
    archive = await load_blob_archive(ledger)
    recorded = await load_recorded_claims(ledger, assignment.question_id)

    result = await worker(
        assignment,
        ledger=ShadowLedger(ledger),
        fetch_fn=archive.fetch,
    )

    return compare_claims(
        recorded,
        list(getattr(result, "claims", []) or []),
        served_urls=archive.served,
        missed_urls=archive.missed,
    )


def build_shadow_worker(
    *,
    provider: Any,
    grader: Any,
    runtime_factory: Any,
    cap_bytes: int,
    limits: Any,
    parent_id: str,
    command_limits: Any,
) -> Any:
    """`run_offline_shadow` 의 `worker` 자리에 **진짜 조사 워커**를 꽂는다.

    `command_limits` 는 오케스트레이터가 넘기는 것과 같은 값이어야 한다
    (J1.5) -- 빠지면 섀도의 자식은 코드를 돌리지 못하고, 비교는 J 가 아니라
    "샌드박스를 가진 fetch 자식" 을 잰다.

    주입 지점만 있고 진짜를 꽂는 어댑터가 없으면 J3 는 테스트에서만 도는
    기계로 남는다 -- 이 저장소가 K2b 에서 배운 그 모양이다.

    `ledger` 와 `fetch_fn` 은 **러너가 준다.** 여기서 만들지 않는 이유는 그
    둘이 섀도의 안전장치이기 때문이다: 진짜 원장이 가면 섀도 실행이 기록된
    run 을 바꾸고, 라이브 `fetch_url` 이 가면 오프라인이 아니라 또 한 번의
    라이브 실행이 된다. 만들 수 있는 자리를 주지 않으면 잘못 만들 수도 없다.
    """

    async def worker(assignment: Any, *, ledger: Any, fetch_fn: Any) -> Any:
        return await run_research_worker(
            assignment,
            ledger=ledger,
            provider=provider,
            grader=grader,
            cap_bytes=cap_bytes,
            limits=limits,
            fetch_fn=fetch_fn,
            runtime_factory=runtime_factory,
            parent_id=parent_id,
            command_limits=command_limits,
        )

    return worker
