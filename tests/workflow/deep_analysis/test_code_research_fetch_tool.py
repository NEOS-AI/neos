"""`fetch.v1` — retrieval 의 유일한 입구 (계약 §3.1).

도구는 **얇은 어댑터**다. 구현은 `neos/workflow/deep_analysis/fetch.py`
하나이고, 여기서 HTTP 를 다시 부르면 검색 경로가 둘이 된다 -- 재시도 정책도
blob 해시도 갈라지고, 그러면 원장의 blob 과 워커가 읽은 본문이 달라질 수 있다.

네 가지를 고정한다:

1. **본문은 결과에 없다.** 경로만 준다 (점진 공개, CE ③). R-06 이 막는 것은
   base64 지만 계약 §3.1 이 막는 것은 **본문 그 자체**다. `raw_text` 를 그냥
   실어 보내면 base64 를 떼어낸 K6 의 이유가 그대로 되살아난다.

2. **순서가 계약이다.** blob 이 원장에 들어간 **뒤에** `/evidence` 에
   나타난다. 뒤집히면 워커가 원장에 없는 증거를 인용할 수 있고, 그 클레임은
   제출될 때는 멀쩡하다가 채점에서 `E_COMPUTE_INPUT_UNFETCHED` 로 **나중에**
   죽는다 -- 이 저장소가 반복해서 피해 온 "조용히 뒤늦게" 모양이다.

3. **거절은 아무것도 남기지 않는다.** 한도에 닿은 fetch 는 커밋도
   materialize 도 하지 않는다. 반쯤 들어간 증거가 제일 나쁘다.

4. **커밋은 건별이다.** 배치로 모았다가 끝에 쓰면, 워커가 지금 읽는 파일이
   아직 원장에 없다. 2 번과 같은 이유다.

임포트를 함수 안에 두는 이유는 `test_evidence_cap.py` 와 같다 -- 모듈이 아직
없을 때 파일 전체가 **수집 실패**로 죽으면 판정 여럿이 한 번에 가려진다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.no_db


@dataclass
class _Blob:
    """`ProposedBlob` 과 같은 모양. 여기서 만드는 것은 fetch 결과뿐이다."""

    content_hash: str
    source_url: str
    http_status: int
    raw_text: str


class _RecordingStore:
    """한도 회계 + 건별 커밋. 원장 자리를 대신한다 (Postgres 없이)."""

    def __init__(self, *, spent: int = 0, stored: frozenset[str] = frozenset()):
        self._spent = spent
        self._stored = set(stored)
        self.commits: list[tuple[str, int]] = []
        self.recorded: list[tuple[str, str]] = []
        self.calls: list[str] = []

    async def spent_bytes(self) -> int:
        return self._spent

    async def is_stored(self, content_hash: str) -> bool:
        return content_hash in self._stored

    async def commit(self, blob, *, bytes_charged: int) -> None:
        self.calls.append("commit")
        self.commits.append((blob.content_hash, bytes_charged))
        self._stored.add(blob.content_hash)
        self._spent += bytes_charged

    async def record_fetched(self, raw_ref: str, path: str) -> None:
        self.calls.append("record")
        self.recorded.append((raw_ref, path))


class _RecordingSandbox:
    """`QuestionSandbox` 자리. 경로 규약은 계약 §3.1 의 절대 경로다."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.written: list[tuple[str, str]] = []

    async def materialize_evidence(self, raw_ref: str, text: str) -> str:
        self.calls.append("materialize")
        self.written.append((raw_ref, text))
        return f"/evidence/{raw_ref}.txt"


def _port(
    *,
    blob: _Blob,
    store: _RecordingStore | None = None,
    cap_bytes: int = 1000,
):
    from neos.workflow.deep_analysis.research_tools import ResearchToolPort

    resolved_store = store or _RecordingStore()
    calls = resolved_store.calls
    sandbox = _RecordingSandbox(calls)
    fetched: list[str] = []

    async def fetch_fn(url: str):
        fetched.append(url)
        return blob

    port = ResearchToolPort(
        fetch_fn=fetch_fn,
        store=resolved_store,
        sandbox=sandbox,
        cap_bytes=cap_bytes,
    )
    return port, resolved_store, sandbox, fetched


def _blob(text: str = "hello evidence", status: int = 200) -> _Blob:
    return _Blob(
        content_hash="abc123def456ffff",
        source_url="https://example.com/doc",
        http_status=status,
        raw_text=text,
    )


@pytest.mark.asyncio
async def test_the_tool_offers_fetch_v1_under_the_contract_name() -> None:
    """`_RESEARCH_TOOLS` 가 부르는 이름과 같아야 한다.

    `CodingToolPort.definitions()` 가 `allowed_tools` 로 **교집합**을 뜨므로,
    이름이 어긋나면 도구는 오류 없이 **조용히 사라진다**.
    """
    port, _, _, _ = _port(blob=_blob())

    names = [getattr(item, "name", None) for item in port.definitions()]

    assert "fetch.v1" in names


@pytest.mark.asyncio
async def test_the_result_carries_a_path_and_never_the_body() -> None:
    port, _, _, _ = _port(blob=_blob(text="the quick brown fox"))

    result = await port.execute("fetch.v1", {"url": "https://example.com/doc"})

    assert result["raw_ref"] == "abc123def456ffff"
    assert result["status"] == 200
    assert result["path"] == "/evidence/abc123def456ffff.txt"
    assert result["bytes"] == len(b"the quick brown fox")
    # blob 은 통째로 있거나 없다 (I5). 잘린 본문은 재실행에서 같은 digest 를
    # 내지 못하므로 증거가 될 수 없고, 그래서 여기는 늘 False 다.
    assert result["truncated"] is False
    # 본문은 어떤 키로도 새 나가지 않는다.
    assert "raw_text" not in result
    assert "the quick brown fox" not in str(result)


@pytest.mark.asyncio
async def test_the_blob_reaches_the_ledger_before_the_path_exists() -> None:
    """순서가 계약이다 (계약 §3.1). 뒤집히면 뒤늦게 조용히 죽는다."""
    port, store, sandbox, _ = _port(blob=_blob())

    await port.execute("fetch.v1", {"url": "https://example.com/doc"})

    # 원장 기록은 경로가 생긴 **뒤**다 -- 원장이 가리키는 자리는 워커가
    # 실제로 열 수 있어야 한다.
    assert store.calls == ["commit", "materialize", "record"]
    assert sandbox.written == [("abc123def456ffff", "hello evidence")]
    assert store.recorded == [("abc123def456ffff", "/evidence/abc123def456ffff.txt")]


@pytest.mark.asyncio
async def test_each_fetch_commits_on_its_own() -> None:
    """건별 커밋 -- 배치로 미루면 워커가 읽는 파일이 아직 원장에 없다."""
    first = _blob(text="one")
    port, store, _, _ = _port(blob=first, cap_bytes=1000)

    await port.execute("fetch.v1", {"url": "https://example.com/a"})

    assert store.commits == [("abc123def456ffff", len(b"one"))]


@pytest.mark.asyncio
async def test_a_fetch_that_would_cross_the_cap_is_refused_and_writes_nothing() -> None:
    store = _RecordingStore(spent=995)
    port, store, sandbox, _ = _port(
        blob=_blob(text="0123456789"), store=store, cap_bytes=1000
    )

    result = await port.execute("fetch.v1", {"url": "https://example.com/doc"})

    from neos.workflow.deep_analysis.evidence_store import CAP_REACHED

    assert result["error"] == CAP_REACHED
    assert "path" not in result
    # 거절은 반쯤 들어가지 않는다.
    assert store.commits == []
    assert sandbox.written == []


@pytest.mark.asyncio
async def test_a_blob_already_in_the_ledger_is_charged_nothing() -> None:
    """미러 URL 의 dedup 은 드문 경로가 아니다 (`fetch.py` 의 `_blob_hash`).

    이미 있는 것을 다시 읽는 데에는 새 공간이 들지 않으므로, 한도가 이미
    찼더라도 거절하지 않는다 -- `decide_fetch_admission` 과 같은 방향이다.
    """
    store = _RecordingStore(spent=1000, stored=frozenset({"abc123def456ffff"}))
    port, store, sandbox, _ = _port(blob=_blob(), store=store, cap_bytes=1000)

    result = await port.execute("fetch.v1", {"url": "https://example.com/doc"})

    assert result["path"] == "/evidence/abc123def456ffff.txt"
    assert store.commits == [("abc123def456ffff", 0)]
    # 한도가 찼어도 경로는 나온다.
    assert sandbox.written != []


@pytest.mark.asyncio
async def test_a_dead_source_is_still_recorded_with_its_status() -> None:
    """404 도 blob 이다. `E_SOURCE_DEAD` 는 원장에 기록이 있어야 붙는다."""
    port, store, _, _ = _port(blob=_blob(text="", status=404))

    result = await port.execute("fetch.v1", {"url": "https://example.com/gone"})

    assert result["status"] == 404
    assert result["bytes"] == 0
    assert store.commits == [("abc123def456ffff", 0)]


@pytest.mark.asyncio
async def test_the_only_retrieval_entrance_refuses_other_names() -> None:
    port, _, _, fetched = _port(blob=_blob())

    result = await port.execute("web_fetch.v1", {"url": "https://example.com"})

    assert result["error"] == "tool_not_allowed"
    assert fetched == []
