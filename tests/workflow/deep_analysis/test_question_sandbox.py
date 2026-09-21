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
