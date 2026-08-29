"""job 러너 단위 테스트 — Fake 세션/오케스트레이터만 쓴다(Postgres 불필요)."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis import jobs


pytestmark = pytest.mark.no_db


class FakeSession:
    """Ledger.log()가 쓰는 add/flush와 commit/get, 그리고 degradations()의 조회만 흉내낸다."""

    def __init__(self, run=None):
        self.added = []
        self.commits = 0
        self.run = run

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None

    async def get(self, model, key):
        return self.run

    async def execute(self, statement):
        """`Ledger.degradations()`의 SELECT를 흉내낸다.

        WHERE 절을 해석하지 않고 이 세션에 add된 것을 그대로 되돌려준다 --
        이 Fake는 run 하나만 다루므로 run_id 필터는 항상 참이고, kind 필터는
        `_degradation_kind()`가 어차피 한 번 더 거른다. 즉 이 단순화가
        테스트를 느슨하게 만들지 않는다.
        """
        rows = [(obj.kind, obj.payload) for obj in self.added]
        return SimpleNamespace(all=lambda: rows)


def make_factory(sessions):
    """호출될 때마다 sessions에서 하나씩 꺼내주는 session_factory."""
    handed = []

    @asynccontextmanager
    async def factory():
        session = sessions[len(handed)] if len(handed) < len(sessions) else sessions[-1]
        handed.append(session)
        yield session

    factory.handed = handed
    return factory


def kinds(session):
    return [obj.kind for obj in session.added]


@pytest.mark.asyncio
async def test_record_dispatch_failure_marks_run_failed_with_bounded_event():
    run = SimpleNamespace(status="running", report_path=None)
    fail_session = FakeSession(run=run)

    await jobs.record_dispatch_failure(
        make_factory([fail_session]), "run00001"
    )

    assert run.status == "failed"
    assert kinds(fail_session) == [jobs.JOB_FAILED]
    assert json.loads(fail_session.added[-1].payload) == {
        "code": "E_BROKER_DISPATCH",
        "error": "Celery broker dispatch failed",
    }
    assert fail_session.commits == 1
    assert "redis://" not in fail_session.added[-1].payload


@pytest.mark.asyncio
async def test_execute_run_brackets_the_run_with_lifecycle_events():
    session = FakeSession()
    factory = make_factory([session])
    seen = {}

    async def build(sess, run_id, *, profile, checkpoint):
        seen["run_id"] = run_id
        seen["profile"] = profile
        seen["checkpoint"] = checkpoint

        class Orchestrator:
            async def run(self, question):
                seen["question"] = question
                return {"run_id": run_id, "report_markdown": "## 요약\n리포트"}

        return Orchestrator()

    result = await jobs.execute_run(
        factory,
        "run00001",
        "질문",
        "dev",
        build_orchestrator_fn=build,
    )

    assert result["report_markdown"] == "## 요약\n리포트"
    assert seen["run_id"] == "run00001"
    assert seen["question"] == "질문"
    # 체크포인트가 세션 커밋에 묶여야 이벤트가 다른 프로세스에 보인다.
    assert seen["checkpoint"] == session.commit
    assert kinds(session) == [jobs.JOB_STARTED, jobs.JOB_COMPLETED]


@pytest.mark.asyncio
async def test_execute_run_carries_the_report_in_the_completion_event():
    """AC6: 늦게 접속한 구독자도 이벤트 재생만으로 리포트를 받아야 한다."""
    import json

    session = FakeSession()

    async def build(sess, run_id, *, profile, checkpoint):
        class Orchestrator:
            async def run(self, question):
                return {"run_id": run_id, "report_markdown": "## 요약\n본문"}

        return Orchestrator()

    await jobs.execute_run(
        make_factory([session]),
        "run00001",
        "질문",
        "dev",
        build_orchestrator_fn=build,
    )

    completed = session.added[-1]
    assert completed.kind == jobs.JOB_COMPLETED
    assert json.loads(completed.payload)["report_markdown"] == "## 요약\n본문"


@pytest.mark.asyncio
async def test_execute_run_carries_degradations_in_its_result():
    """새로고침 후 UI가 강등을 그리려면 이 값이 메시지까지 흘러가야 한다."""
    session = FakeSession()

    async def build(sess, run_id, *, profile, checkpoint):
        from neos.workflow.deep_analysis.ledger import Ledger

        class Orchestrator:
            async def run(self, question):
                ledger = Ledger(sess, run_id)
                await ledger.log("node_reduction_degraded", None, {})
                await ledger.log("node_reduction_degraded", None, {})
                await ledger.log("report_graded", None, {"ok": True, "judge": "truncated"})
                await ledger.log("claim_verified", None, {})
                return {"run_id": run_id, "report_markdown": "## 요약\n본문"}

        return Orchestrator()

    result = await jobs.execute_run(
        make_factory([session]),
        "run00001",
        "질문",
        "dev",
        build_orchestrator_fn=build,
    )

    assert result["degradations"] == [
        {"kind": "node_reduction_degraded", "count": 2},
        {"kind": "judge_unreviewed:truncated", "count": 1},
    ]


@pytest.mark.asyncio
async def test_execute_run_reports_no_degradations_for_a_clean_run():
    """강등이 없으면 빈 리스트다 -- None 이 아니다. 소비자가 분기를 하나만 갖게 한다."""
    session = FakeSession()

    async def build(sess, run_id, *, profile, checkpoint):
        class Orchestrator:
            async def run(self, question):
                return {"run_id": run_id, "report_markdown": "## 요약\n본문"}

        return Orchestrator()

    result = await jobs.execute_run(
        make_factory([session]),
        "run00001",
        "질문",
        "dev",
        build_orchestrator_fn=build,
    )

    assert result["degradations"] == []


@pytest.mark.asyncio
async def test_execute_run_records_failure_in_a_fresh_session_and_reraises():
    """D18 선결조건 #2와 같은 이유: 실패한 세션은 롤백/오류 상태일 수 있어
    재사용하지 않는다. 별도 세션에서 fail_run + job_failed를 커밋한다."""
    run_session = FakeSession()
    fail_session = FakeSession(run=SimpleNamespace(status="running", report_path=None))

    async def build(sess, run_id, *, profile, checkpoint):
        class Orchestrator:
            async def run(self, question):
                raise RuntimeError("boom")

        return Orchestrator()

    factory = make_factory([run_session, fail_session])

    with pytest.raises(RuntimeError, match="boom"):
        await jobs.execute_run(
            factory,
            "run00001",
            "질문",
            "dev",
            build_orchestrator_fn=build,
        )

    assert kinds(run_session) == [jobs.JOB_STARTED]
    assert kinds(fail_session) == [jobs.JOB_FAILED]
    assert fail_session.run.status == "failed"
    assert fail_session.commits >= 1


@pytest.mark.asyncio
async def test_execute_run_timeout_records_durable_failure():
    run_session = FakeSession()
    failed_run = SimpleNamespace(status="running", report_path=None)
    fail_session = FakeSession(run=failed_run)

    async def build(sess, run_id, *, profile, checkpoint):
        class Orchestrator:
            async def run(self, question):
                await asyncio.Event().wait()

        return Orchestrator()

    with pytest.raises(asyncio.TimeoutError):
        await jobs.execute_run(
            make_factory([run_session, fail_session]),
            "run00001",
            "질문",
            "dev",
            timeout_seconds=0.01,
            build_orchestrator_fn=build,
        )

    assert kinds(run_session) == [jobs.JOB_STARTED]
    assert kinds(fail_session) == [jobs.JOB_FAILED]
    assert failed_run.status == "failed"
    payload = json.loads(fail_session.added[-1].payload)
    assert payload["error"] == "deep_analysis job timed out after 0.01 seconds"


@pytest.mark.asyncio
async def test_resume_run_forwards_timeout_to_execution():
    stored_run = SimpleNamespace(
        status="running",
        root_question="원래 질문",
        profile="dev",
    )
    lookup_session = FakeSession(run=stored_run)
    run_session = FakeSession()
    fail_session = FakeSession(run=stored_run)

    async def build(sess, run_id, *, profile, checkpoint):
        class Orchestrator:
            async def run(self, question):
                await asyncio.Event().wait()

        return Orchestrator()

    with pytest.raises(asyncio.TimeoutError):
        await jobs.resume_run(
            make_factory([lookup_session, run_session, fail_session]),
            "run00001",
            timeout_seconds=0.01,
            build_orchestrator_fn=build,
        )

    assert kinds(run_session) == [jobs.JOB_RESUMED]
    assert kinds(fail_session) == [jobs.JOB_FAILED]
    assert stored_run.status == "failed"


@pytest.mark.asyncio
async def test_resume_run_reuses_the_stored_question_and_emits_job_resumed():
    """AC5: resume은 새 run을 만들지 않는다 -- 같은 run_id로 다시 들어간다."""
    run = SimpleNamespace(
        status="running",
        root_question="원래 질문",
        profile="default",
    )
    session = FakeSession(run=run)
    seen = {}

    async def build(sess, run_id, *, profile, checkpoint):
        seen["run_id"] = run_id
        seen["profile"] = profile

        class Orchestrator:
            async def run(self, question):
                seen["question"] = question
                return {"run_id": run_id, "report_markdown": "리포트"}

        return Orchestrator()

    await jobs.resume_run(
        make_factory([session]),
        "run00001",
        build_orchestrator_fn=build,
    )

    assert seen["run_id"] == "run00001"
    assert seen["question"] == "원래 질문"
    assert seen["profile"] == "default"
    assert kinds(session) == [jobs.JOB_RESUMED, jobs.JOB_COMPLETED]


@pytest.mark.asyncio
async def test_resume_run_reactivates_a_failed_run():
    run = SimpleNamespace(status="failed", root_question="질문", profile="dev")
    session = FakeSession(run=run)

    async def build(sess, run_id, *, profile, checkpoint):
        class Orchestrator:
            async def run(self, question):
                return {"run_id": run_id, "report_markdown": "리포트"}

        return Orchestrator()

    await jobs.resume_run(
        make_factory([session]),
        "run00001",
        build_orchestrator_fn=build,
    )

    assert run.status == "running"


@pytest.mark.asyncio
async def test_resume_run_refuses_a_completed_run():
    """완료된 run을 재개하면 리포트 조립 + 채점 비용을 다시 쓴다 -- 재과금이다."""
    run = SimpleNamespace(status="completed", root_question="질문", profile="dev")

    with pytest.raises(jobs.RunNotResumable):
        await jobs.resume_run(make_factory([FakeSession(run=run)]), "run00001")


@pytest.mark.asyncio
async def test_resume_run_refuses_a_missing_run():
    with pytest.raises(jobs.RunNotResumable):
        await jobs.resume_run(make_factory([FakeSession(run=None)]), "nope")


def test_lifecycle_kinds_cannot_collide_with_harness_event_kinds():
    """job_ 접두어가 충돌 회피의 근거다. Ledger가 쓰는 kind를 하드코딩해
    두 집합이 겹치지 않음을 고정한다."""
    harness_kinds = {
        "question_opened",
        "split",
        "dead_end",
        "claim_verified",
        "claim_rejected",
        "claim_unverified",
        "pass_completed",
        "subq_proposed",
        "worker_result_mismatch",
        "stall_terminated",
        "abandoned",
        "question_reopened",
        "conflict_reinvestigation",
        "report_graded",
    }
    lifecycle = {
        jobs.JOB_STARTED,
        jobs.JOB_RESUMED,
        jobs.JOB_COMPLETED,
        jobs.JOB_FAILED,
    }

    assert lifecycle & harness_kinds == set()
    assert all(kind.startswith("job_") for kind in lifecycle)
    assert jobs.TERMINAL_JOB_KINDS == {jobs.JOB_COMPLETED, jobs.JOB_FAILED}


# --- P1 #8: `_persist_assistant_message` 는 예외를 삼킨다(그래야 한다 -- run 은
# 성공했고 리포트는 이미 `job_completed` 에 실려 있다). 문제는 삼킨 자리에
# `logger.warning` 하나밖에 안 남는다는 것이었다. FE5 로 실패한 run 도 이
# 경로를 타게 되면서 사정거리가 넓어졌다: 여기서 예외가 나면 **실패 사실과
# 강등이 둘 다** 대화에서 사라진다. §3.2 의 규칙("새 fallback 에는 그것이
# 남기는 이벤트를 함께 정의한다")을 뒤늦게 적용해 흔적을 원장으로 올린다.


@pytest.mark.asyncio
async def test_message_persist_failure_leaves_a_queryable_event():
    session = FakeSession()

    await jobs.record_message_persist_failure(
        make_factory([session]),
        "run00001",
        status="failed",
        error_type="ValueError",
        degradations_lost=3,
    )

    assert kinds(session) == [jobs.MESSAGE_PERSIST_FAILED]
    assert json.loads(session.added[-1].payload) == {
        "status": "failed",
        "error_type": "ValueError",
        "degradations_lost": 3,
    }
    # 커밋이 필수다 -- flush 만 하면 다른 프로세스의 커서 리더가 못 본다.
    assert session.commits == 1


@pytest.mark.asyncio
async def test_message_persist_failure_never_carries_the_exception_text():
    """`error_type` 만 싣는다.

    `str(exc)` 는 접속 문자열이나 내부 경로를 실을 수 있고, 이 페이로드는
    이벤트 스트림을 타고 브라우저까지 간다 -- `_failure_body` 가 대화 본문에
    대해 내린 것과 같은 판단이다.
    """
    session = FakeSession()

    await jobs.record_message_persist_failure(
        make_factory([session]),
        "run00001",
        status="completed",
        error_type="ConnectionError",
        degradations_lost=0,
    )

    payload = session.added[-1].payload
    assert "ConnectionError" in payload
    assert "postgresql://" not in payload


@pytest.mark.asyncio
async def test_recording_the_failure_never_raises():
    """이 함수는 `except` 블록 안에서 불린다.

    여기서 예외가 올라가면 원래 예외를 가리고, 최악의 경우 job 을 죽인다 --
    run 은 성공했는데 메시지 저장 실패 때문에 실패로 뒤집히는 것이다.
    """

    @asynccontextmanager
    async def exploding_factory():
        raise ConnectionError("db is down")
        yield  # pragma: no cover

    await jobs.record_message_persist_failure(
        exploding_factory,
        "run00001",
        status="completed",
        error_type="ValueError",
        degradations_lost=0,
    )
