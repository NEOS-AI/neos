"""job 러너 단위 테스트 — Fake 세션/오케스트레이터만 쓴다(Postgres 불필요)."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis import jobs


pytestmark = pytest.mark.no_db


class FakeSession:
    """Ledger.log()가 쓰는 add/flush와 commit/get만 흉내낸다."""

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
