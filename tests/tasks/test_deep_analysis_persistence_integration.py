"""리포트 영속화를 실제 DB로 검증한다.

`tests/tasks/test_deep_analysis_job_task.py`는 `ChatService`를 목으로 두므로
어떤 인자든 통과한다. 그런데 `_persist_assistant_message`는 **예외를 삼킨다**
(실패해도 run 자체는 성공이라는 판단). 두 성질이 겹치면 실제 DB에서만 터지는
오류가 조용히 리포트를 잃게 만든다 -- 목 테스트로는 영원히 안 잡힌다.

여기서는 LLM을 호출하지 않고(오케스트레이터를 스텁), 디스패치 이후의
`job -> 리포트 영속화` 사슬만 실제 Postgres에 대고 확인한다.
"""

import pathlib
import uuid

import pytest

from neos.tasks.deep_analysis_job_task import _execute, _persist_assistant_message


_SCHEMA_SQL = pathlib.Path("db/chat_system.sql")
_FUNCTION = "CREATE OR REPLACE FUNCTION create_conversation("


def _create_conversation_ddl() -> str | None:
    """`db/chat_system.sql` 에서 `create_conversation` 함수 정의만 떼어낸다."""
    if not _SCHEMA_SQL.exists():
        return None
    text = _SCHEMA_SQL.read_text(encoding="utf-8")
    start = text.find(_FUNCTION)
    if start < 0:
        return None
    end = text.find("$$ LANGUAGE plpgsql;", start)
    if end < 0:
        return None
    return text[start : end + len("$$ LANGUAGE plpgsql;")]


@pytest.fixture(autouse=True)
async def create_conversation_function():
    """이 파일이 필요로 하는 저장 함수를 **직접 만든다**.

    `db_manager.initialize()` 는 `Base.metadata.create_all` 로 ORM 테이블만
    만든다. `create_conversation` 은 `db/chat_system.sql` 의 저장 함수이고
    테스트 부트스트랩은 그 파일을 적용하지 않는다 -- 그러니 이 테스트들은
    **개발 기계에 그 함수가 수동으로 적용돼 있을 때만** 통과했다.

    2026-08-13 에 CI 범위를 넓히자마자 드러났다:
    `UndefinedFunctionError: function create_conversation(...) does not exist`.
    `.env` 의 실제 API 키에 기대던 테스트들과 같은 부류다 -- 테스트가 환경을
    **정하지 않고 읽는다**.
    """
    from sqlalchemy import text as sql_text

    from neos.database.connection import get_session_ctx

    ddl = _create_conversation_ddl()
    if ddl is None:
        pytest.skip(f"{_SCHEMA_SQL} 에서 create_conversation 정의를 못 찾았다")
    async with get_session_ctx() as session:
        await session.execute(sql_text(ddl))
        await session.commit()


REPORT = "# 심층 분석 보고서\n\n검증된 클레임 기반 본문."


async def _seed_conversation() -> tuple[str, str]:
    """실제 DB에 사용자와 대화를 만들고 (conversation_id, user_id)를 반환한다.

    이메일은 conftest의 autouse 정리 픽스처가 지우는 패턴을 따른다.
    """
    from neos.api.services.chat_service import ChatService
    from neos.database.connection import get_session_ctx
    from neos.database.models import User

    suffix = uuid.uuid4().hex[:8]
    user_id = f"fixture-da-{suffix}"
    async with get_session_ctx() as session:
        session.add(
            User(
                user_id=user_id,
                email=f"fixture+{suffix}@example.com",
                username=user_id,
                password_hash="x",
            )
        )
        await session.commit()

    conversation = await ChatService.create_conversation(
        user_id=user_id,
        title="deep analysis persistence integration",
    )
    return conversation["conversation_id"], user_id


async def _seed_run(conversation_id: str, assistant_message_id: str) -> str:
    from neos.database.connection import get_session_ctx
    from neos.workflow.deep_analysis.ledger import create_run

    async with get_session_ctx() as session:
        run_id = await create_run(
            session,
            "이 주장이 사실인가?",
            "dev",
            conversation_id=conversation_id,
            assistant_message_id=assistant_message_id,
        )
        await session.commit()
    return run_id


async def _message_content(conversation_id: str, message_id: str) -> str | None:
    """messages는 ORM 모델이 아니라 리포지토리 dataclass로 다뤄지므로 원시 SQL로 읽는다."""
    from sqlalchemy import text

    from neos.database.connection import get_session_ctx

    async with get_session_ctx() as session:
        result = await session.execute(
            text("SELECT content FROM messages WHERE message_id = :mid"),
            {"mid": message_id},
        )
        row = result.first()
        return None if row is None else row[0]


async def _message_metadata(message_id: str) -> dict | None:
    """`ChatService.get_message`로 영속화된 metadata 를 읽는다(기존 서비스 경로 재사용)."""
    from neos.api.services.chat_service import ChatService

    message = await ChatService.get_message(message_id)
    return None if message is None else message["metadata"]


@pytest.mark.asyncio
async def test_persist_assistant_message_writes_report_to_the_real_conversation():
    """목이 아닌 실제 ChatService/DB에 리포트가 실제로 남는가."""
    conversation_id, _ = await _seed_conversation()
    message_id = str(uuid.uuid4())
    run_id = await _seed_run(conversation_id, message_id)

    await _persist_assistant_message(run_id, REPORT)

    assert await _message_content(conversation_id, message_id) == REPORT


@pytest.mark.asyncio
async def test_execute_chain_persists_report_without_calling_an_llm(monkeypatch):
    """디스패치 이후 사슬 전체: execute_run -> 영속화. 오케스트레이터는 스텁."""
    conversation_id, _ = await _seed_conversation()
    message_id = str(uuid.uuid4())
    run_id = await _seed_run(conversation_id, message_id)

    async def fake_execute_run(
        session_ctx,
        rid,
        question,
        profile,
        *,
        timeout_seconds=None,
    ):
        assert timeout_seconds is None
        return {"run_id": rid, "report_markdown": REPORT}

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.jobs.execute_run", fake_execute_run
    )

    result = await _execute(run_id, "이 주장이 사실인가?", "dev", False)

    assert result["report_markdown"] == REPORT
    assert await _message_content(conversation_id, message_id) == REPORT


@pytest.mark.asyncio
async def test_execute_chain_persists_degradations_to_the_real_database(monkeypatch):
    """degradations 도 report_markdown 과 같은 사슬을 타고 실제 DB에 남는가.

    목 테스트(`test_deep_analysis_job_task.py`)는 ChatService 전체를 목으로
    두므로 `deep_analysis_degradations` 키가 실제로 살아 돌아오는지 증명하지
    못한다 -- 이 파일의 존재 이유 그대로다.
    """
    conversation_id, _ = await _seed_conversation()
    message_id = str(uuid.uuid4())
    run_id = await _seed_run(conversation_id, message_id)

    degradations = [
        {"kind": "report_assembly_degraded", "count": 3},
        {"kind": "judge_unreviewed:budget_exhausted", "count": 1},
    ]

    async def fake_execute_run(
        session_ctx,
        rid,
        question,
        profile,
        *,
        timeout_seconds=None,
    ):
        assert timeout_seconds is None
        return {
            "run_id": rid,
            "report_markdown": REPORT,
            "degradations": degradations,
        }

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.jobs.execute_run", fake_execute_run
    )

    result = await _execute(run_id, "이 주장이 사실인가?", "dev", False)

    assert result["report_markdown"] == REPORT
    assert await _message_content(conversation_id, message_id) == REPORT

    metadata = await _message_metadata(message_id)
    assert metadata is not None
    assert metadata["deep_analysis_degradations"] == degradations


@pytest.mark.asyncio
async def test_persist_is_a_noop_for_a_run_with_no_conversation():
    """대화 밖에서 시작된 run(전용 API 등)은 영속화 대상이 아니다."""
    from neos.database.connection import get_session_ctx
    from neos.workflow.deep_analysis.ledger import create_run

    async with get_session_ctx() as session:
        run_id = await create_run(session, "질문", "dev")
        await session.commit()

    # 예외 없이 조용히 반환해야 한다.
    await _persist_assistant_message(run_id, REPORT)
