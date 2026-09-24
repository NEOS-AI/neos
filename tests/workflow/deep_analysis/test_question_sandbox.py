"""질문 하나에 샌드박스 하나 (계약 §3.2).

코딩 루프의 `SandboxBindingService` 를 쓰지 않는다. 그 층이 하는 일은 실행
리스를 둘러싼 펜싱과 CAS 인데, 질문에는 리스가 없다. 대신 **provider 와
프로파일 체계는 그대로 쓴다** -- 계약 §3.2 가 금지하는 "DA 전용 경로" 는
프로파일 체계를 따로 만드는 것이지, 리스 층을 건너뛰는 것이 아니다.
`SandboxProvider.create(owner_id=..., limits=...)` 는 리스를 모른다.

경로가 둘인 것에 주의한다. 계약 §3.1 의 도구 결과는 `/evidence/<raw_ref>.txt`
(절대 경로)이고, 샌드박스 세션은 **워크스페이스 상대 경로**로 파일을 다룬다.
둘을 섞으면 워커가 열 수 없는 경로를 받는다 -- 조용히 깨지는 종류다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from neos.coding.sandbox.base import SandboxLimits, SandboxNotFound
from neos.coding.sandbox.memory import MemorySandboxProvider

pytestmark = pytest.mark.no_db


async def _provider(tmp_path: Path) -> MemorySandboxProvider:
    return MemorySandboxProvider(root=tmp_path / "da-sandboxes")


@pytest.mark.asyncio
async def test_the_sandbox_is_owned_by_the_question(tmp_path) -> None:
    from neos.workflow.deep_analysis.sandbox import open_question_sandbox

    provider = await _provider(tmp_path)
    box = await open_question_sandbox(
        provider, question_id="q_1", limits=SandboxLimits.safe_defaults()
    )

    try:
        sandbox = await provider.get(box.sandbox_id)
        assert sandbox.owner_id == "q_1"
    finally:
        await box.close()


@pytest.mark.asyncio
async def test_evidence_is_written_where_the_worker_can_read_it(tmp_path) -> None:
    from neos.workflow.deep_analysis.sandbox import open_question_sandbox

    provider = await _provider(tmp_path)
    box = await open_question_sandbox(
        provider, question_id="q_1", limits=SandboxLimits.safe_defaults()
    )

    try:
        path = await box.materialize_evidence("abc123def456ffff", "hello evidence")

        # 도구 결과에 실리는 것은 계약 §3.1 의 절대 경로다.
        assert path == "/evidence/abc123def456ffff.txt"
        # 실제 바이트는 워크스페이스 상대 경로에 있다.
        read = await box.session.read_file("evidence/abc123def456ffff.txt")
        assert read.decode("utf-8") == "hello evidence"
    finally:
        await box.close()


@pytest.mark.asyncio
async def test_the_same_blob_twice_is_written_once(tmp_path) -> None:
    """한도 회계와 같은 방향이다 -- 이미 있는 것은 새 공간을 쓰지 않는다."""
    from neos.workflow.deep_analysis.sandbox import open_question_sandbox

    provider = await _provider(tmp_path)
    box = await open_question_sandbox(
        provider, question_id="q_1", limits=SandboxLimits.safe_defaults()
    )

    try:
        first = await box.materialize_evidence("abc123def456ffff", "hello")
        second = await box.materialize_evidence("abc123def456ffff", "hello")

        assert first == second
        entries = await box.session.list_tree("evidence")
        assert len(entries) == 1
    finally:
        await box.close()


@pytest.mark.asyncio
async def test_closing_destroys_the_sandbox(tmp_path) -> None:
    """질문이 끝나면 샌드박스도 끝난다. 리스가 없으므로 회수해 줄 층도 없다."""
    from neos.workflow.deep_analysis.sandbox import open_question_sandbox

    provider = await _provider(tmp_path)
    box = await open_question_sandbox(
        provider, question_id="q_1", limits=SandboxLimits.safe_defaults()
    )
    sandbox_id = box.sandbox_id

    await box.close()

    with pytest.raises(SandboxNotFound):
        await provider.get(sandbox_id)


class _ReadonlyEvidenceProvider:
    """`readonly_evidence` 를 선언한 provider(Docker)의 가짜.

    증거가 워커 세션의 `write_file` 로 쓰이면 워크스페이스에 파일이 생기고
    아래 테스트가 그것을 잡는다 -- 그 경로는 워커의 쓰기 경로다.
    """

    readonly_evidence = True

    def __init__(self, inner: MemorySandboxProvider) -> None:
        self._inner = inner
        self.create_kwargs: list[dict] = []
        self.evidence: dict[tuple[str, str], bytes] = {}

    async def create(self, **kwargs):
        self.create_kwargs.append(kwargs)
        return await self._inner.create(
            owner_id=kwargs["owner_id"], limits=kwargs["limits"]
        )

    async def open_session(self, sandbox_id: str):
        return await self._inner.open_session(sandbox_id)

    async def write_evidence(self, sandbox_id: str, name: str, data: bytes) -> None:
        self.evidence[(sandbox_id, name)] = data

    async def destroy(self, sandbox_id: str) -> None:
        await self._inner.destroy(sandbox_id)


@pytest.mark.asyncio
async def test_a_readonly_provider_is_opened_with_the_profile_and_evidence(
    tmp_path,
) -> None:
    from neos.workflow.deep_analysis.sandbox import open_question_sandbox

    provider = _ReadonlyEvidenceProvider(await _provider(tmp_path))
    box = await open_question_sandbox(
        provider,
        question_id="q_1",
        limits=SandboxLimits.safe_defaults(),
        profile="research-offline-v1",
    )

    try:
        assert box.evidence_readonly is True
        (kwargs,) = provider.create_kwargs
        assert kwargs["profile"] == "research-offline-v1"
        assert kwargs["evidence"] is True
    finally:
        await box.close()


@pytest.mark.asyncio
async def test_readonly_evidence_never_goes_through_the_worker_session(
    tmp_path,
) -> None:
    """변이: 증거가 워커 세션으로 쓰이면 워커도 같은 길로 고쳐 쓸 수 있다."""
    from neos.workflow.deep_analysis.sandbox import open_question_sandbox

    provider = _ReadonlyEvidenceProvider(await _provider(tmp_path))
    box = await open_question_sandbox(
        provider, question_id="q_1", limits=SandboxLimits.safe_defaults()
    )

    try:
        path = await box.materialize_evidence("abc123def456ffff", "hello")

        assert path == "/evidence/abc123def456ffff.txt"
        assert provider.evidence == {
            (box.sandbox_id, "abc123def456ffff.txt"): b"hello"
        }
        assert await box.session.list_tree(".") == ()
    finally:
        await box.close()


@pytest.mark.asyncio
async def test_a_provider_without_the_declaration_keeps_the_old_path(
    tmp_path,
) -> None:
    """메모리·관리형 provider 는 이전과 같다. 가짜 객체의 아무 속성이 참으로
    읽혀 새 경로로 들어가지 않도록 `is True` 로만 받는다."""
    from unittest.mock import AsyncMock, MagicMock

    from neos.workflow.deep_analysis.sandbox import open_question_sandbox

    inner = await _provider(tmp_path)
    box = await open_question_sandbox(
        inner, question_id="q_1", limits=SandboxLimits.safe_defaults()
    )
    try:
        assert box.evidence_readonly is False
    finally:
        await box.close()

    mock = MagicMock()
    mock.create = AsyncMock()
    mock.open_session = AsyncMock()
    mocked = await open_question_sandbox(
        mock, question_id="q_1", limits=SandboxLimits.safe_defaults()
    )
    assert mocked.evidence_readonly is False
    assert "profile" not in mock.create.call_args.kwargs
