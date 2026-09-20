"""질문 하나 분량의 조립 (계약 §3.1 · §3.2).

지금까지 J1 의 조각들은 각자 초록이었지만 **아무도 서로를 부르지 않았다** --
`fetch.v1` 도, `decide_fetch_admission` 도, `open_question_sandbox` 도
프로덕션 호출부가 0 이었다. 이 파일이 고정하는 것은 그 조각들이 한 줄로
꿰이는 지점이다: fetch 하나가 **원장에 들어가고, 그 다음에** 샌드박스의
`/evidence` 에 나타나고, 바이트가 질문 행에 청구된다.

조립이 `research_tools.py` 가 아니라 여기 있는 이유는 I2 다. 조립은 원장을
인자로 받아야 하는데, 워커 쪽 포트가 사는 모듈이 원장을 받으면 "워커는 원장
쓰기 경로를 갖지 않는다" 가 모양만 남는다. 조립은 **오케스트레이터 쪽**이다.

샌드박스는 `MemorySandboxProvider` 로 돈다 -- 계약 §3.2 가 금지하는 것은
프로파일 체계를 따로 만드는 것이지, 테스트가 메모리 provider 를 쓰는 것이
아니다. 원장 자리에는 가짜를 넣는다(Postgres 가 이 기계에서 돌지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from neos.coding.sandbox.base import SandboxLimits, SandboxNotFound
from neos.coding.sandbox.memory import MemorySandboxProvider

pytestmark = pytest.mark.no_db


@dataclass
class _Blob:
    content_hash: str
    source_url: str
    http_status: int
    raw_text: str


class _FakeQuestion:
    def __init__(self, evidence_bytes: int = 0) -> None:
        self.evidence_bytes = evidence_bytes


class _FakeDb:
    async def flush(self) -> None:
        return None


class _FakeLedger:
    def __init__(self, question: _FakeQuestion) -> None:
        self.db = _FakeDb()
        self.question = question
        self.committed: list[_Blob] = []
        self.events: list[tuple[str, str, dict]] = []
        self._stored: set[str] = set()

    async def log(self, kind: str, qid: str, payload: dict) -> None:
        self.events.append((kind, qid, payload))

    async def get_question(self, question_id: str):
        return self.question

    async def get_blob(self, content_hash: str):
        return object() if content_hash in self._stored else None

    async def commit_blobs(self, blobs) -> None:
        self.committed.extend(blobs)
        for blob in blobs:
            self._stored.add(blob.content_hash)


def _blob(text: str = "hello evidence") -> _Blob:
    return _Blob(
        content_hash="abc123def456ffff",
        source_url="https://example.com/doc",
        http_status=200,
        raw_text=text,
    )


async def _open(
    tmp_path: Path,
    *,
    ledger: _FakeLedger,
    blob: _Blob | None = None,
    cap_bytes: int = 1000,
    grader=None,
):
    from neos.workflow.deep_analysis.research_session import open_research_session

    resolved = blob if blob is not None else _blob()

    async def fetch_fn(url: str):
        return resolved

    provider = MemorySandboxProvider(root=tmp_path / "da-sandboxes")
    session = await open_research_session(
        ledger=ledger,
        provider=provider,
        question_id="q_1",
        cap_bytes=cap_bytes,
        fetch_fn=fetch_fn,
        limits=SandboxLimits.safe_defaults(),
        grader=grader,
    )
    return session, provider


@pytest.mark.asyncio
async def test_the_assembled_port_offers_both_tools(tmp_path) -> None:
    ledger = _FakeLedger(_FakeQuestion())
    session, _ = await _open(tmp_path, ledger=ledger)

    try:
        names = {item.name for item in session.port.definitions()}
        assert names == {"fetch.v1", "submit.v1"}
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_a_fetch_reaches_the_ledger_and_then_the_sandbox(tmp_path) -> None:
    """이 파일의 이유. 조각 셋이 처음으로 서로를 부른다."""
    ledger = _FakeLedger(_FakeQuestion())
    session, _ = await _open(tmp_path, ledger=ledger)

    try:
        result = await session.port.execute(
            "fetch.v1", {"url": "https://example.com/doc"}
        )

        # 도구는 경로만 돌려준다 (§3.1).
        assert result["path"] == "/evidence/abc123def456ffff.txt"
        assert "raw_text" not in result

        # 원장에 blob 이 있다.
        assert [b.content_hash for b in ledger.committed] == ["abc123def456ffff"]

        # 그리고 워커가 읽을 수 있는 자리에 바이트가 있다.
        stored = await session.sandbox.session.read_file(
            "evidence/abc123def456ffff.txt"
        )
        assert stored.decode("utf-8") == "hello evidence"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_the_bytes_are_charged_to_the_question_row(tmp_path) -> None:
    question = _FakeQuestion()
    ledger = _FakeLedger(question)
    session, _ = await _open(tmp_path, ledger=ledger)

    try:
        await session.port.execute("fetch.v1", {"url": "https://example.com/doc"})

        assert question.evidence_bytes == len(b"hello evidence")
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_a_fetch_over_the_cap_leaves_nothing_behind(tmp_path) -> None:
    """거절은 반쯤 들어가지 않는다 -- 원장에도, 샌드박스에도."""
    from neos.workflow.deep_analysis.evidence_store import CAP_REACHED

    question = _FakeQuestion(evidence_bytes=995)
    ledger = _FakeLedger(question)
    session, _ = await _open(tmp_path, ledger=ledger, cap_bytes=1000)

    try:
        result = await session.port.execute(
            "fetch.v1", {"url": "https://example.com/doc"}
        )

        assert result["error"] == CAP_REACHED
        assert ledger.committed == []
        assert question.evidence_bytes == 995
        # `evidence` 디렉터리 자체가 없다. 없는 경로를 `list_tree` 하면
        # `workspace_path_not_resolvable` 로 터지므로(확인함), 빈 목록을
        # 기대하는 대신 **워크스페이스가 통째로 비어 있음**을 본다 -- 거절이
        # 아무것도 남기지 않았다는 말의 더 강한 판이기도 하다.
        assert await session.sandbox.session.list_tree(".") == ()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_closing_destroys_the_question_sandbox(tmp_path) -> None:
    """질문이 끝나면 샌드박스도 끝난다. 리스가 없어 회수해 줄 층이 없다."""
    ledger = _FakeLedger(_FakeQuestion())
    session, provider = await _open(tmp_path, ledger=ledger)
    sandbox_id = session.sandbox.sandbox_id

    await session.close()

    with pytest.raises(SandboxNotFound):
        await provider.get(sandbox_id)


@pytest.mark.asyncio
async def test_without_a_grader_the_assembled_port_omits_check_claims(
    tmp_path,
) -> None:
    """채점기는 선택이다 -- 없으면 도구도 없다.

    오케스트레이터가 채점기를 갖고 있으므로 프로덕션에서는 늘 있지만,
    없을 때 조용히 부를 수 없는 도구를 내미는 쪽으로 기울지 않는다.
    """
    ledger = _FakeLedger(_FakeQuestion())
    session, _ = await _open(tmp_path, ledger=ledger)

    try:
        names = {item.name for item in session.port.definitions()}
        assert "check_claims.v1" not in names
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_a_grader_reaches_the_assembled_port(tmp_path) -> None:
    """조립이 채점기를 통과시켜야 `check_claims.v1` 이 열린다."""

    class _Grader:
        async def grade(self, claim):  # pragma: no cover - 호출되지 않는다
            raise AssertionError("이 테스트는 채점기를 부르지 않는다")

    ledger = _FakeLedger(_FakeQuestion())
    session, _ = await _open(tmp_path, ledger=ledger, grader=_Grader())

    try:
        names = {item.name for item in session.port.definitions()}
        assert names == {"fetch.v1", "submit.v1", "check_claims.v1"}
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_the_sandbox_is_owned_by_the_question(tmp_path) -> None:
    ledger = _FakeLedger(_FakeQuestion())
    session, provider = await _open(tmp_path, ledger=ledger)

    try:
        sandbox = await provider.get(session.sandbox.sandbox_id)
        assert sandbox.owner_id == "q_1"
    finally:
        await session.close()
