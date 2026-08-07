# 강등 표면화 (FE4) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** deep_analysis 리포트를 깎은 강등 사건을 챗 UI에 그리고, 새로고침 후에도 남게 한다.

**Architecture:** 백엔드는 run 종료 시 원장(`deep_analysis_events`)에서 강등을 집계해 어시스턴트 메시지 메타데이터에 싣는다(읽기만 — P2 단일 작성자 유지). 프론트엔드는 라이브 스트림에서 같은 규칙으로 누적한 상태를 쓰되, 새로고침 후에는 메타데이터를 출처로 삼는다. 표시 문구는 `web/lib/`의 순수 함수에 두고 컴포넌트는 `.map()`만 한다 — `test:source`에 DOM이 없어 컴포넌트 안의 로직은 테스트할 수 없기 때문이다.

**Tech Stack:** Python 3.12 / SQLAlchemy 2.0 async / pytest-asyncio · TypeScript / React 19 / `tsx --test` (node:test)

## Global Constraints

- **설계 정본:** `docs/superpowers/specs/2026-08-07-deep-analysis-degradation-surface-design.md`
- **커밋 메시지에 `Co-Authored-By` 트레일러 금지** (사용자 지시. 하네스 기본 지침보다 우선)
- **문서·주석은 한국어.** 커밋 메시지 본문은 기존 관례대로 영문
- **P2 단일 작성자:** 원장 쓰기는 오케스트레이터 한 곳. 이 계획의 백엔드 변경은 **전부 읽기**다
- **append-only 이벤트 로그:** `deep_analysis_events`에 UPDATE/DELETE 금지
- **강등 kind 어휘 (양쪽 동일해야 함):**
  - `report_assembly_degraded` — 무조건
  - `node_reduction_degraded` — 무조건
  - `finalization_prompt_clamped` — `payload.exhausted`가 `true`일 때만
  - `report_graded` — `payload.judge`가 비지 않은 문자열일 때 `judge_unreviewed:<judge>`
- **DB 있는 테스트 실행:** `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q`
- **프론트 검증:** `pnpm --dir web test:source && pnpm --dir web exec tsc --noEmit`
- 현재 기준선: 프론트 `test:source` **147 passed**

---

### Task 1: `Ledger.degradations()` — 원장에서 강등을 집계한다

W2가 만든 `Ledger.report_markdown()`(`ledger.py:891`)과 같은 모양의 **이름 있는 조회 경로**를 하나 더 판다.

**Files:**
- Modify: `neos/workflow/deep_analysis/ledger.py` (모듈 레벨 헬퍼 2개 추가 + `Ledger`에 메서드 1개)
- Test: `tests/workflow/deep_analysis/test_ledger_degradations.py` (신규)

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `neos.workflow.deep_analysis.ledger._DEGRADATION_KINDS: tuple[str, ...]`
  - `neos.workflow.deep_analysis.ledger._payload_dict(raw: object) -> dict[str, Any]`
  - `neos.workflow.deep_analysis.ledger._degradation_kind(kind: str, payload: dict[str, Any]) -> str | None`
  - `Ledger.degradations(self) -> list[dict[str, Any]]` — `[{"kind": str, "count": int}]`, 최초 발생 순서 보존

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_ledger_degradations.py` 신규 생성:

```python
"""강등 집계는 원장에서 읽는다 -- 새로고침 후 복원의 유일한 출처다.

test_ledger_report_body.py 와 같은 규율을 따른다: 실제 DB에 쓰고 각 테스트
끝에서 롤백한다. 남는 쓰기가 있으면 안 된다.

⚠️ 🟡 이 파일의 CANONICAL_FIXTURE 는 **정본 fixture 목록**이다. 같은 목록이
`web/tests/source/deep-analysis-degradation.test.ts` 에도 있다. 강등 어휘를
바꾸면 **반드시 양쪽을 함께** 고칠 것 -- 규칙이 두 언어로 구현돼 있기 때문이다
(설계 §3.3, 로드맵 §7 FE6).
"""

import pytest

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run

# (kind, payload, 기대 결과 kind 또는 None)
CANONICAL_FIXTURE = [
    ("report_assembly_degraded", {"reason": "token_budget_exhausted"},
     "report_assembly_degraded"),
    ("node_reduction_degraded", {"reason": "token_budget_exhausted"},
     "node_reduction_degraded"),
    ("finalization_prompt_clamped", {"exhausted": True, "stage": "report_assembly"},
     "finalization_prompt_clamped"),
    ("finalization_prompt_clamped", {"exhausted": False, "stage": "report_assembly"},
     None),
    ("report_graded", {"ok": True, "judge": "budget_exhausted"},
     "judge_unreviewed:budget_exhausted"),
    ("report_graded", {"ok": True, "judge": "truncated"},
     "judge_unreviewed:truncated"),
    ("report_graded", {"ok": True, "judge": "unparseable"},
     "judge_unreviewed:unparseable"),
    ("report_graded", {"ok": True, "uncited_ratio": 0.1}, None),
    ("investigation_stopped_at_floor", {"floor_tokens": 41040}, None),
    ("claim_discarded", {}, None),
    ("llm_truncated", {"stage": "worker_analysis"}, None),
]


@pytest.mark.asyncio
async def test_degradations_counts_the_canonical_fixture():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        ledger = Ledger(s, run_id)
        for kind, payload, _ in CANONICAL_FIXTURE:
            await ledger.log(kind, None, payload)

        expected: list[dict[str, object]] = []
        for _, _, resolved in CANONICAL_FIXTURE:
            if resolved is None:
                continue
            existing = next(
                (e for e in expected if e["kind"] == resolved), None
            )
            if existing is None:
                expected.append({"kind": resolved, "count": 1})
            else:
                existing["count"] = int(existing["count"]) + 1

        assert await ledger.degradations() == expected
        await s.rollback()


@pytest.mark.asyncio
async def test_degradations_sums_repeats_and_keeps_first_seen_order():
    """3회와 1회는 다른 이야기다. 순서는 최초 발생 순."""
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        ledger = Ledger(s, run_id)
        await ledger.log("node_reduction_degraded", None, {})
        await ledger.log("report_assembly_degraded", None, {})
        await ledger.log("node_reduction_degraded", None, {})

        assert await ledger.degradations() == [
            {"kind": "node_reduction_degraded", "count": 2},
            {"kind": "report_assembly_degraded", "count": 1},
        ]
        await s.rollback()


@pytest.mark.asyncio
async def test_degradations_is_empty_when_nothing_was_degraded():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        await Ledger(s, run_id).log("job_started", None, {"profile": "dev"})

        assert await Ledger(s, run_id).degradations() == []
        await s.rollback()


@pytest.mark.asyncio
async def test_degradations_ignores_other_runs():
    """집계는 run 단위다. 다른 run의 강등이 새면 사용자에게 남의 경고가 뜬다."""
    async with await db_manager.get_session() as s:
        mine = await create_run(s, "내 질문", "dev")
        theirs = await create_run(s, "남 질문", "dev")
        await Ledger(s, theirs).log("report_assembly_degraded", None, {})

        assert await Ledger(s, mine).degradations() == []
        await s.rollback()


@pytest.mark.asyncio
async def test_degradations_survives_a_malformed_payload():
    """방어적으로 읽는다 -- 페이로드 모양이 바뀌어도 예외를 내지 않는다."""
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        ledger = Ledger(s, run_id)
        await ledger.log("report_graded", None, {"judge": 42})
        await ledger.log("report_graded", None, {"judge": ""})
        await ledger.log("finalization_prompt_clamped", None, {"exhausted": "yes"})

        assert await ledger.degradations() == []
        await s.rollback()
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_ledger_degradations.py -q`
Expected: FAIL — `AttributeError: 'Ledger' object has no attribute 'degradations'`

- [ ] **Step 3: 모듈 레벨 헬퍼를 추가한다**

`neos/workflow/deep_analysis/ledger.py`의 `_safe_clamp_counts` 함수 **바로 뒤**(43~53행 근처)에 삽입:

```python
# 강등으로 세는 이벤트 kind. 조회를 좁히는 용도이며, 실제 판정은
# `_degradation_kind()` 가 payload 까지 보고 내린다.
_DEGRADATION_KINDS = (
    "report_assembly_degraded",
    "node_reduction_degraded",
    "finalization_prompt_clamped",
    "report_graded",
)


def _payload_dict(raw: object) -> dict[str, Any]:
    """`DAEvent.payload` 를 dict 로 읽는다 -- 어떤 모양으로 와도 던지지 않는다.

    컬럼은 Text 라 보통 str 로 오지만 드라이버·테스트에 따라 dict 로도 온다.
    `report_markdown()` 과 같은 방어적 읽기다.
    """
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _degradation_kind(kind: str, payload: dict[str, Any]) -> str | None:
    """이 이벤트가 리포트를 깎았는가 -- 깎았다면 어떤 이름으로 셀 것인가.

    ⚠️ 🟡 **알려진 중복.** 같은 규칙이 프론트엔드에도 있다:
    `web/lib/deep-analysis/progress.ts` 의 `degradationKind()`.
    이쪽은 새로고침 후 복원을, 저쪽은 라이브 스트림을 담당한다. 어휘를 바꿀
    때 **반드시 양쪽을 함께** 고칠 것. 정본 fixture 목록은
    `tests/workflow/deep_analysis/test_ledger_degradations.py` 의
    `CANONICAL_FIXTURE` 와 `web/tests/source/deep-analysis-degradation.test.ts`
    의 `CANONICAL_FIXTURE` 에 같은 내용으로 들어 있다.
    통합 검토는 로드맵 §7 FE6.

    조사 범위나 검증 강도를 깎은 것(`investigation_stopped_at_floor`,
    `claim_discarded` 등)은 여기 들지 않는다 -- 리포트 자체는 주어진 재료로
    낼 수 있는 최선이기 때문이다(D26).

    `report_graded` 는 kind 가 아니라 **payload 가** 강등을 결정하는 유일한
    경우다. 굶은/잘린/해석 실패 판정자는 전부 `ok=True` 로 재조립 루프를
    끝내므로(`graders/report.py`) `judge` 키가 달린 이벤트는 run 당 최대 1건이고
    항상 최종 판정이다 -- 중간 시도가 오탐으로 잡히지 않는다.
    """
    if kind in ("report_assembly_degraded", "node_reduction_degraded"):
        return kind
    if kind == "finalization_prompt_clamped":
        return kind if payload.get("exhausted") is True else None
    if kind == "report_graded":
        judge = payload.get("judge")
        if isinstance(judge, str) and judge:
            return f"judge_unreviewed:{judge}"
        return None
    return None
```

- [ ] **Step 4: `Ledger.degradations()`를 추가한다**

`neos/workflow/deep_analysis/ledger.py`의 `report_markdown()` 메서드 **바로 뒤**(923행 `return body if isinstance(body, str) else None` 다음, `complete_run` 앞)에 삽입:

```python
    async def degradations(self) -> list[dict[str, Any]]:
        """이 run 이 리포트 품질을 깎은 사건들 -- kind 별 합산, 최초 발생 순서 보존.

        새로고침 후 챗 UI 가 강등을 다시 그릴 수 있는 **유일한 출처**다. 라이브
        스트림은 프론트가 이벤트를 직접 접어 만들지만(`progress.ts`), 종결된 run 은
        다시 구독하지 않으므로 그 상태가 남지 않는다. `jobs.execute_run` 이 이
        값을 어시스턴트 메시지 메타데이터로 넘긴다.

        판정 규칙과 그 중복에 대해서는 `_degradation_kind()` 주석을 볼 것.

        3회와 1회는 다른 이야기이므로 집합이 아니라 카운트로 돌려준다(D26).
        """
        rows = (
            await self.db.execute(
                select(DAEvent.kind, DAEvent.payload)
                .where(
                    DAEvent.run_id == self.run_id,
                    DAEvent.kind.in_(_DEGRADATION_KINDS),
                )
                .order_by(DAEvent.seq)
            )
        ).all()

        # dict 는 삽입 순서를 보존한다 -- 최초 발생 순서가 그대로 결과 순서다.
        counts: dict[str, int] = {}
        for kind, raw in rows:
            resolved = _degradation_kind(kind, _payload_dict(raw))
            if resolved is None:
                continue
            counts[resolved] = counts.get(resolved, 0) + 1
        return [{"kind": kind, "count": count} for kind, count in counts.items()]
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_ledger_degradations.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: 원장 전체 회귀를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_ledger.py tests/workflow/deep_analysis/test_ledger_m2.py tests/workflow/deep_analysis/test_ledger_m3.py tests/workflow/deep_analysis/test_ledger_report_body.py -q`
Expected: PASS, 0 failed

- [ ] **Step 7: 커밋**

```bash
git add neos/workflow/deep_analysis/ledger.py tests/workflow/deep_analysis/test_ledger_degradations.py
git commit -m "feat(deep-analysis): give degradations a named read path

The chat UI has to redraw degradation warnings after a reload, and a
settled run is never resubscribed -- so the live reducer's state is gone.
The ledger is the only thing left that knows.

Follows report_markdown()'s shape: read the events, do not touch the
runs table. Counts rather than a set, because three template fallbacks
and one are different stories."
```

---

### Task 2: `execute_run`이 강등을 결과에 싣는다

**Files:**
- Modify: `neos/workflow/deep_analysis/jobs.py` (`execute_run` 반환값 + 애너테이션)
- Test: `tests/workflow/deep_analysis/test_jobs.py` (`FakeSession`에 `execute` 추가 + 테스트 2개)

**Interfaces:**
- Consumes: `Ledger.degradations()` (Task 1)
- Produces: `jobs.execute_run(...) -> dict[str, object]` — 결과 dict에 `"degradations": list[dict[str, object]]` 키 추가. `resume_run`은 `execute_run`에 위임하므로 자동으로 같은 모양

- [ ] **Step 1: `FakeSession`에 조회를 흉내내는 메서드를 추가한다**

`tests/workflow/deep_analysis/test_jobs.py`의 `FakeSession` 클래스(16~37행)에서 docstring과 메서드를 아래로 교체:

```python
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
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_jobs.py`의 `test_execute_run_carries_the_report_in_the_completion_event` 함수 **뒤**에 추가:

```python
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
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_jobs.py -q -k degradations`
Expected: FAIL — `KeyError: 'degradations'`

- [ ] **Step 4: `execute_run`이 집계해서 결과에 싣게 한다**

`neos/workflow/deep_analysis/jobs.py`의 `execute_run`에서, 반환 애너테이션을 넓히고(133행) 완료 이벤트 로깅 앞에 집계를 넣는다. 171~179행을 아래로 교체:

```python
        # 강등 집계는 run 이 끝난 뒤에 읽는다 -- 원장 쓰기가 전부 끝난 시점이다.
        # 읽기 전용이므로 P2(원장 단일 작성자)를 건드리지 않는다. 이 값은
        # `_persist_assistant_message` 를 거쳐 어시스턴트 메시지 메타데이터로
        # 들어가고, 새로고침 후 UI 가 강등을 다시 그리는 유일한 출처가 된다.
        result["degradations"] = await Ledger(session, run_id).degradations()
        # AC6: 늦게 접속한 구독자가 이벤트 재생만으로 리포트를 받도록
        # 완료 이벤트가 리포트 본문을 싣는다.
        await _log_lifecycle(
            session,
            run_id,
            JOB_COMPLETED,
            {"report_markdown": result["report_markdown"]},
        )
        return result
```

애너테이션 변경 — 133행:

```python
) -> dict[str, object]:
```

`Ledger`는 `jobs.py:48`에 `from .ledger import Ledger`로 **이미 import돼 있다.**
import 추가는 필요 없다.

- [ ] **Step 5: `resume_run` 애너테이션도 넓힌다**

`neos/workflow/deep_analysis/jobs.py` 188행:

```python
) -> dict[str, object]:
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_jobs.py -q`
Expected: PASS, 0 failed

- [ ] **Step 7: 커밋**

```bash
git add neos/workflow/deep_analysis/jobs.py tests/workflow/deep_analysis/test_jobs.py
git commit -m "feat(deep-analysis): carry the degradation summary out of the run

Read once the orchestrator is done, so every degradation event is already
on the log. Read-only, so the single-writer rule still holds.

Empty list rather than None for a clean run: consumers get one shape to
branch on, not two."
```

---

### Task 3: 강등을 어시스턴트 메시지 메타데이터에 영속화한다

**Files:**
- Modify: `neos/tasks/deep_analysis_job_task.py` (`_persist_assistant_message` 시그니처 + 호출부)
- Test: `tests/workflow/deep_analysis/test_deep_analysis_job_task.py` (테스트 2개 추가)

**Interfaces:**
- Consumes: `execute_run` 결과의 `"degradations"` 키 (Task 2)
- Produces: 메시지 메타데이터 키 `deep_analysis_degradations: list[dict]` — Task 6의 프론트 브리지가 읽는다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_deep_analysis_job_task.py` 끝에 추가:

```python
@pytest.mark.asyncio
async def test_execute_passes_degradations_to_the_message_persister(monkeypatch):
    """강등이 메시지까지 가지 않으면 새로고침 후 UI가 다시 침묵한다."""
    from neos.workflow.deep_analysis import jobs

    seen = {}

    async def run(*args, **kwargs):
        return {
            "run_id": "run00001",
            "report_markdown": "## 요약\n본문",
            "degradations": [{"kind": "report_assembly_degraded", "count": 3}],
        }

    async def persist(run_id, report_markdown, degradations):
        seen["run_id"] = run_id
        seen["degradations"] = degradations

    monkeypatch.setattr(jobs, "execute_run", run)
    monkeypatch.setattr(task_module, "_persist_assistant_message", persist)

    await task_module._execute("run00001", "질문", "dev", False)

    assert seen["run_id"] == "run00001"
    assert seen["degradations"] == [
        {"kind": "report_assembly_degraded", "count": 3}
    ]


@pytest.mark.asyncio
async def test_persisted_message_metadata_carries_the_degradations(monkeypatch):
    """FE 브리지가 읽는 키 이름을 고정한다 -- 이름이 어긋나면 카드가 침묵한다."""
    from contextlib import asynccontextmanager

    import neos.api.services.chat_service as chat_service_module
    import neos.database.connection as connection_module

    captured = {}

    class FakeChatService:
        @staticmethod
        async def add_message(**kwargs):
            captured.update(kwargs)

    class FakeRun:
        conversation_id = "conv-1"
        assistant_message_id = "msg-1"

    class FakeSession:
        async def get(self, model, key):
            return FakeRun()

    @asynccontextmanager
    async def fake_session_ctx():
        yield FakeSession()

    # `_persist_assistant_message` 는 함수 안에서 import 하므로 모듈 속성을
    # 갈아끼우면 그 import 가 Fake 를 집어온다.
    monkeypatch.setattr(chat_service_module, "ChatService", FakeChatService)
    monkeypatch.setattr(connection_module, "get_session_ctx", fake_session_ctx)

    await task_module._persist_assistant_message(
        "run00001",
        "## 요약\n본문",
        [{"kind": "judge_unreviewed:budget_exhausted", "count": 1}],
    )

    assert captured["metadata"]["deep_analysis_degradations"] == [
        {"kind": "judge_unreviewed:budget_exhausted", "count": 1}
    ]
    assert captured["metadata"]["deep_analysis_run_id"] == "run00001"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_deep_analysis_job_task.py -q -k degradation`
Expected: FAIL — `TypeError: _persist_assistant_message() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: `_persist_assistant_message`가 강등을 받아 싣게 한다**

`neos/tasks/deep_analysis_job_task.py` 49~86행을 아래로 교체:

```python
async def _persist_assistant_message(
    run_id: str,
    report_markdown: str,
    degradations: list[dict[str, object]] | None = None,
) -> None:
    """리포트를 대화 메시지로 저장한다(대화에 묶인 run만).

    인라인 SSE 시절 핸들러가 하던 일이다. 실행이 요청 밖으로 나갔으므로
    job 쪽으로 옮긴다. 실패해도 run 자체는 성공이므로 삼킨다 -- 리포트는
    이미 job_completed 이벤트에 실려 있다.

    ⚠️ 다만 **강등은 이 경로에만 있다.** 여기서 예외가 나면 새로고침 후 UI가
    다시 침묵한다 -- 로드맵 §7 P1 #8(예외를 삼키는 영속화)의 새 피해자다.
    삼키는 동작 자체는 이번 범위 밖이라 유지하되, 로그에 강등 건수를 남겨
    사라진 사실이 흔적을 갖게 한다.
    """
    from neos.api.services.chat_service import ChatService
    from neos.database.connection import get_session_ctx
    from neos.database.deep_analysis_models import DARun

    try:
        async with get_session_ctx() as session:
            run = await session.get(DARun, run_id)
            conversation_id = getattr(run, "conversation_id", None)
            message_id = getattr(run, "assistant_message_id", None)

        if not conversation_id or not message_id:
            return

        await ChatService.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=report_markdown,
            message_id=message_id,
            model_name="deep-analysis-harness",
            metadata={
                "deep_analysis_run_id": run_id,
                "research_status": "completed",
                # 프론트 브리지(`web/lib/deep-analysis/metadata.ts`)가 읽는 키다.
                # 이름을 바꾸면 새로고침 후 강등 경고가 조용히 사라진다.
                "deep_analysis_degradations": degradations or [],
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "failed to persist deep_analysis report message: "
            "run=%s error_type=%s degradations_lost=%d",
            run_id,
            type(exc).__name__,
            len(degradations or []),
        )
```

- [ ] **Step 4: 호출부가 강등을 넘기게 한다**

`neos/tasks/deep_analysis_job_task.py` 116행을 교체:

```python
    await _persist_assistant_message(
        run_id,
        result["report_markdown"],
        result.get("degradations"),
    )
```

`_execute` 반환 애너테이션(96행)도 넓힌다:

```python
) -> dict[str, object]:
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_deep_analysis_job_task.py -q`
Expected: PASS, 0 failed

- [ ] **Step 6: 백엔드 하네스 전체 회귀를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q`
Expected: PASS, 0 failed

- [ ] **Step 7: 커밋**

```bash
git add neos/tasks/deep_analysis_job_task.py tests/workflow/deep_analysis/test_deep_analysis_job_task.py
git commit -m "feat(deep-analysis): persist degradations onto the report message

This is the only path that carries them past the run, so the swallowed
exception here now costs something it did not before. Keeping the swallow
(out of scope), but the log line names how many degradations went with it.

Pins the metadata key the frontend bridge reads. Renaming it silently
re-mutes the warning."
```

---

### Task 4: 프론트 리듀서가 굶은 판정자를 강등으로 센다

**Files:**
- Modify: `web/lib/deep-analysis/progress.ts` (`degradedReport` → `degradationKind`, 리듀서 1줄)
- Test: `web/tests/source/deep-analysis-progress.test.ts` (테스트 3개 추가)

**Interfaces:**
- Consumes: 없음 (프론트 첫 태스크)
- Produces: `DeepAnalysisProgress.degradations`가 `judge_unreviewed:<judge>` 항목을 포함할 수 있다. 타입은 기존 `DegradationEntry = { kind: string; count: number }` 그대로

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`web/tests/source/deep-analysis-progress.test.ts`의 "클램프가 허용량 안에 들어갔으면 강등이 아니다" 테스트 **뒤**에 추가:

```ts
test("굶은 판정자는 강등으로 센다 — 심사 없이 통과한 리포트다", () => {
  const state = applyAll([
    event(1, "report_graded", { ok: true, judge: "budget_exhausted" }),
  ]);

  assert.deepEqual(state.degradations, [
    { kind: "judge_unreviewed:budget_exhausted", count: 1 },
  ]);
});

test("실제로 심사한 판정자의 통과는 강등이 아니다", () => {
  const state = applyAll([
    event(1, "report_graded", { ok: true, uncited_ratio: 0.1 }),
    event(2, "report_graded", { ok: false, code: "E_REPORT_AGENTIC" }),
  ]);

  assert.deepEqual(state.degradations, []);
  assert.equal(state.gradeAttempts, 2);
});

test("판정자 강등 3종이 각각 다른 항목으로 남는다", () => {
  const state = applyAll([
    event(1, "report_graded", { ok: true, judge: "truncated" }),
    event(2, "report_graded", { ok: true, judge: "unparseable" }),
  ]);

  assert.deepEqual(state.degradations, [
    { kind: "judge_unreviewed:truncated", count: 1 },
    { kind: "judge_unreviewed:unparseable", count: 1 },
  ]);
});

test("재생된 이벤트는 강등을 두 번 세지 않는다", () => {
  // `after=0` 재구독은 전체 이력을 다시 흘려보낸다. 커서 가드가 없으면
  // 재연결 한 번에 "3회"가 "6회"가 된다.
  const replayed = [
    event(1, "report_assembly_degraded", {}),
    event(2, "report_graded", { ok: true, judge: "budget_exhausted" }),
  ];
  const state = [...replayed, ...replayed].reduce(
    reduceDeepAnalysisEvent,
    initialDeepAnalysisProgress()
  );

  assert.deepEqual(state.degradations, [
    { kind: "report_assembly_degraded", count: 1 },
    { kind: "judge_unreviewed:budget_exhausted", count: 1 },
  ]);
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `pnpm --dir web test:source 2>&1 | grep -A3 "굶은 판정자는 강등으로"`
Expected: FAIL — `degradations`가 `[]`로 나온다

- [ ] **Step 3: `degradedReport`를 `degradationKind`로 교체한다**

`web/lib/deep-analysis/progress.ts` 209~224행(`degradedReport` 함수 전체와 그 docstring)을 아래로 교체:

```ts
/**
 * 이 이벤트가 리포트를 사용자가 받았어야 할 것보다 못하게 만들었는가 —
 * 만들었다면 어떤 이름으로 셀 것인가.
 *
 * ⚠️ 🟡 **알려진 중복.** 같은 규칙이 백엔드에도 있다:
 * `neos/workflow/deep_analysis/ledger.py`의 `_degradation_kind()`.
 * 이쪽은 라이브 스트림을, 저쪽은 새로고침 후 복원을 담당한다. 어휘를 바꿀 때
 * **반드시 양쪽을 함께** 고칠 것 — 정본 fixture 목록이
 * `web/tests/source/deep-analysis-degradation.test.ts`와
 * `tests/workflow/deep_analysis/test_ledger_degradations.py`에 같은 내용으로
 * 들어 있다. 통합 검토는 로드맵 §7 FE6.
 *
 * 조사 범위나 검증 강도를 깎은 것(`investigation_stopped_at_floor`,
 * `claim_discarded` 등)은 여기 들지 않는다 — 리포트 자체는 주어진 재료로
 * 낼 수 있는 최선이기 때문이다. `llm_truncated`도 마찬가지다: 확장 재시도가
 * 성공하면 산출물에 영향이 없고, 실패한 경우만 가르려면 `truncation_handled`와
 * 상관시켜야 한다. 잘못된 경고보다 과소 보고를 택한다.
 *
 * `report_graded`는 kind가 아니라 **payload가** 강등을 결정하는 유일한 경우다.
 * 굶은/잘린/해석 실패 판정자는 전부 `ok=true`로 재조립 루프를 끝내므로
 * (`graders/report.py`) `judge` 키가 달린 이벤트는 run당 최대 1건이고 항상
 * 최종 판정이다 — 중간 시도가 오탐으로 잡히지 않는다.
 */
function degradationKind(event: DeepAnalysisJobEvent): string | null {
  const { kind, payload } = event;
  if (kind === "report_assembly_degraded") return kind;
  if (kind === "node_reduction_degraded") return kind;
  if (kind === "finalization_prompt_clamped") {
    return payload.exhausted === true ? kind : null;
  }
  if (kind === "report_graded") {
    const judge = asString(payload.judge);
    return judge ? `judge_unreviewed:${judge}` : null;
  }
  return null;
}
```

- [ ] **Step 4: 리듀서가 새 함수를 쓰게 한다**

`web/lib/deep-analysis/progress.ts`의 `reduceDeepAnalysisEvent` 안, 263~272행의 `next` 생성 부분을 아래로 교체:

```ts
  const degradation = degradationKind(event);
  const next: DeepAnalysisProgress = {
    ...state,
    cursor: event.seq,
    lastKind: event.kind,
    lastActivity: activityLabel(event) ?? state.lastActivity,
    degradations: degradation
      ? withDegradation(state.degradations, degradation)
      : state.degradations,
    idleTimedOut: false,
  };
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `pnpm --dir web test:source && pnpm --dir web exec tsc --noEmit`
Expected: PASS — 147 + 4 = **151 passed**, tsc 무출력

- [ ] **Step 6: 커밋**

```bash
git add web/lib/deep-analysis/progress.ts web/tests/source/deep-analysis-progress.test.ts
git commit -m "feat(web): count an unreviewed judge as a degradation

A report that cleared the gate without the judge actually running is not
degraded in content -- it is missing its assurance. Different axis, same
thing the user needs told.

Safe to count exactly once: all three starved-judge modes return ok=true
and end the reassembly loop, so at most one such event exists per run."
```

---

### Task 5: 강등 문구를 만드는 순수 함수

**Files:**
- Create: `web/lib/deep-analysis/degradation.ts`
- Test: `web/tests/source/deep-analysis-degradation.test.ts` (신규)

**Interfaces:**
- Consumes: `DegradationEntry` (`web/lib/deep-analysis/progress.ts`에서 이미 export 중)
- Produces:
  - `degradationLabel(kind: string): string`
  - `type DegradationNotice = { kind: string; text: string }`
  - `degradationNotices(entries: readonly DegradationEntry[]): DegradationNotice[]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`web/tests/source/deep-analysis-degradation.test.ts` 신규 생성:

```ts
/**
 * 강등 → 문구. 컴포넌트가 아니라 여기서 테스트하는 이유는 `test:source`가
 * `tsx --test`라 DOM이 없기 때문이다(설계 §2).
 *
 * ⚠️ 🟡 CANONICAL_FIXTURE 는 **정본 fixture 목록**이다. 같은 목록이
 * `tests/workflow/deep_analysis/test_ledger_degradations.py` 에도 있다.
 * 강등 어휘를 바꾸면 **반드시 양쪽을 함께** 고칠 것 — 규칙이 두 언어로
 * 구현돼 있기 때문이다(설계 §3.3, 로드맵 §7 FE6).
 */

import assert from "node:assert/strict";
import test from "node:test";
import {
  degradationLabel,
  degradationNotices,
} from "../../lib/deep-analysis/degradation";
import {
  initialDeepAnalysisProgress,
  reduceDeepAnalysisEvent,
} from "../../lib/deep-analysis/progress";

// [kind, payload, 기대 결과 kind 또는 null]
// test_ledger_degradations.py 의 CANONICAL_FIXTURE 와 같은 내용이어야 한다.
const CANONICAL_FIXTURE: [string, Record<string, unknown>, string | null][] = [
  ["report_assembly_degraded", { reason: "token_budget_exhausted" },
    "report_assembly_degraded"],
  ["node_reduction_degraded", { reason: "token_budget_exhausted" },
    "node_reduction_degraded"],
  ["finalization_prompt_clamped", { exhausted: true, stage: "report_assembly" },
    "finalization_prompt_clamped"],
  ["finalization_prompt_clamped", { exhausted: false, stage: "report_assembly" },
    null],
  ["report_graded", { ok: true, judge: "budget_exhausted" },
    "judge_unreviewed:budget_exhausted"],
  ["report_graded", { ok: true, judge: "truncated" },
    "judge_unreviewed:truncated"],
  ["report_graded", { ok: true, judge: "unparseable" },
    "judge_unreviewed:unparseable"],
  ["report_graded", { ok: true, uncited_ratio: 0.1 }, null],
  ["investigation_stopped_at_floor", { floor_tokens: 41040 }, null],
  ["claim_discarded", {}, null],
  ["llm_truncated", { stage: "worker_analysis" }, null],
];

test("정본 fixture가 백엔드와 같은 kind 집합을 만든다", () => {
  const state = CANONICAL_FIXTURE.reduce(
    (acc, [kind, payload], index) =>
      reduceDeepAnalysisEvent(acc, { seq: index + 1, kind, payload }),
    initialDeepAnalysisProgress()
  );

  const expected: { kind: string; count: number }[] = [];
  for (const [, , resolved] of CANONICAL_FIXTURE) {
    if (resolved === null) continue;
    const existing = expected.find((entry) => entry.kind === resolved);
    if (existing) {
      existing.count += 1;
    } else {
      expected.push({ kind: resolved, count: 1 });
    }
  }

  assert.deepEqual(state.degradations, expected);
});

test("알려진 kind는 저마다 다른 문구를 낸다", () => {
  const kinds = [
    "report_assembly_degraded",
    "node_reduction_degraded",
    "finalization_prompt_clamped",
    "judge_unreviewed:budget_exhausted",
    "judge_unreviewed:truncated",
    "judge_unreviewed:unparseable",
  ];
  const labels = kinds.map(degradationLabel);

  assert.equal(new Set(labels).size, kinds.length);
  for (const label of labels) {
    assert.ok(label.length > 0);
    assert.ok(!label.includes("_"), `원시 kind가 문구에 샜다: ${label}`);
  }
});

test("모르는 kind도 버리지 않고 문구에 싣는다", () => {
  const label = degradationLabel("some_future_degradation");

  assert.ok(label.includes("some_future_degradation"));
});

test("모르는 judge 사유도 문구에 남는다", () => {
  const label = degradationLabel("judge_unreviewed:some_new_mode");

  assert.ok(label.includes("some_new_mode"));
});

test("2회 이상이면 횟수가 문구에 실린다", () => {
  const notices = degradationNotices([
    { kind: "report_assembly_degraded", count: 3 },
    { kind: "judge_unreviewed:truncated", count: 1 },
  ]);

  assert.equal(notices.length, 2);
  assert.ok(notices[0].text.includes("3회"));
  assert.equal(notices[0].kind, "report_assembly_degraded");
  assert.ok(!notices[1].text.includes("회)"));
});

test("빈 입력은 빈 배열을 낸다", () => {
  assert.deepEqual(degradationNotices([]), []);
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `pnpm --dir web test:source 2>&1 | grep -i "degradation.test"`
Expected: FAIL — 모듈을 찾을 수 없음 (`lib/deep-analysis/degradation`)

- [ ] **Step 3: `degradation.ts`를 만든다**

`web/lib/deep-analysis/degradation.ts` 신규 생성:

```ts
/**
 * 강등 상태 → 사람이 읽는 경고 (순수 함수)
 *
 * `progress.ts`가 원장의 어휘(`kind`)만 상태에 싣고 문구는 싣지 않는 이유가
 * 이 파일의 존재 이유다: 문구를 상태에 넣으면 재생된 옛 이벤트가 옛 문구를
 * 고착시킨다. 문구는 렌더 시점에 만든다.
 *
 * 컴포넌트가 아니라 여기 있는 이유: `web/package.json`의 `test:source`는
 * `tsx --test`라 DOM이 없다. 표시 로직이 컴포넌트로 들어가면 회귀 가드가 0이 된다.
 *
 * `progress.ts`와 나눈 이유: 저쪽의 일은 *원장 → 상태*이고 이쪽은
 * *완성된 상태 → 문구*다. 생애주기가 다르다.
 */

import type { DegradationEntry } from "./progress";

/** `degradationKind()`가 판정자 강등에 붙이는 접두사 (progress.ts와 짝). */
const JUDGE_PREFIX = "judge_unreviewed:";

const LABELS: Record<string, string> = {
  report_assembly_degraded:
    "리포트가 LLM 조립 없이 템플릿으로 작성됐습니다",
  node_reduction_degraded:
    "하위 요약이 강등돼 자식 답변을 그대로 이어붙였습니다",
  finalization_prompt_clamped:
    "마무리 입력이 허용량을 넘어 일부 내용이 잘렸습니다",
};

const JUDGE_LABELS: Record<string, string> = {
  budget_exhausted: "심사 없이 통과됐습니다 — 판정자 예산 소진",
  truncated: "심사 없이 통과됐습니다 — 판정자 응답이 잘림",
  unparseable: "심사 없이 통과됐습니다 — 판정자 응답을 해석하지 못함",
};

/**
 * kind 하나를 문구로 만든다.
 *
 * 모르는 kind를 조용히 떨구지 않는다 — 조용한 누락은 이 파일이 없애려는 바로
 * 그 죄다. `progress.ts`가 모르는 이벤트에도 커서를 전진시키는 것과 같은 판단.
 */
export function degradationLabel(kind: string): string {
  const known = LABELS[kind];
  if (known) {
    return known;
  }
  if (kind.startsWith(JUDGE_PREFIX)) {
    const reason = kind.slice(JUDGE_PREFIX.length);
    return JUDGE_LABELS[reason] ?? `심사 없이 통과됐습니다 — ${reason}`;
  }
  return `리포트 품질이 저하됐습니다 · ${kind}`;
}

export type DegradationNotice = { kind: string; text: string };

/**
 * 강등 항목들을 화면에 그릴 문구로 바꾼다.
 *
 * 상태(`DeepAnalysisProgress`)가 아니라 항목 배열을 받는 이유: 출처가 둘이다.
 * 라이브 스트림은 `progress.degradations`, 새로고침 후는 메시지 메타데이터.
 * 둘 다 같은 모양이므로 이 함수는 출처를 몰라도 된다.
 */
export function degradationNotices(
  entries: readonly DegradationEntry[]
): DegradationNotice[] {
  return entries.map((entry) => {
    const label = degradationLabel(entry.kind);
    return {
      kind: entry.kind,
      // 3회와 1회는 다른 이야기다(D26). 1회일 때 "(1회)"는 소음이므로 뺀다.
      text: entry.count > 1 ? `${label} (${entry.count}회)` : label,
    };
  });
}
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `pnpm --dir web test:source && pnpm --dir web exec tsc --noEmit`
Expected: PASS — 151 + 6 = **157 passed**, tsc 무출력

- [ ] **Step 5: 커밋**

```bash
git add web/lib/deep-analysis/degradation.ts web/tests/source/deep-analysis-degradation.test.ts
git commit -m "feat(web): turn degradation kinds into sentences a user can read

Kept out of the component on purpose: test:source runs tsx --test with no
DOM, so anything that lives in JSX has no regression guard.

An unknown kind keeps its raw name in the sentence rather than being
dropped -- silently swallowing the unfamiliar is the exact failure this
whole line of work exists to end."
```

---

### Task 6: 메시지 메타데이터 브리지 — 새로고침 후 카드를 되살린다

**Files:**
- Create: `web/lib/deep-analysis/metadata.ts`
- Modify: `web/lib/types.ts:72-78` (스키마에 `degradations` 추가)
- Modify: `web/lib/utils.ts:111-152` (`convertBackendMessagesToUI`가 브리지 호출)
- Test: `web/tests/source/deep-analysis-metadata.test.ts` (신규)

**Interfaces:**
- Consumes: 백엔드 메타데이터 키 `deep_analysis_run_id` · `research_status` · `deep_analysis_degradations` (Task 3)
- Produces: `deepAnalysisFromMessageMetadata(metadata: Record<string, unknown> | undefined | null): DeepAnalysisMetadata | undefined`. `DeepAnalysisMetadata`에 `degradations?: DegradationEntry[]` 필드 추가

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`web/tests/source/deep-analysis-metadata.test.ts` 신규 생성:

```ts
/**
 * 백엔드 키 → 프론트 모양 브리지.
 *
 * 이 브리지가 없으면 새로고침 후 진행 카드가 **통째로** 사라진다 — 백엔드는
 * `deep_analysis_run_id`를 심는데 컴포넌트는 `deep_analysis`를 읽기 때문이다
 * (설계 §1.2).
 */

import assert from "node:assert/strict";
import test from "node:test";
import { deepAnalysisFromMessageMetadata } from "../../lib/deep-analysis/metadata";

test("백엔드 키를 프론트 모양으로 옮긴다", () => {
  const result = deepAnalysisFromMessageMetadata({
    deep_analysis_run_id: "a1b2c3d4",
    research_status: "completed",
    deep_analysis_degradations: [
      { kind: "report_assembly_degraded", count: 3 },
    ],
  });

  assert.deepEqual(result, {
    run_id: "a1b2c3d4",
    status: "completed",
    degradations: [{ kind: "report_assembly_degraded", count: 3 }],
  });
});

test("run_id가 없으면 undefined — 심층분석 메시지가 아니다", () => {
  assert.equal(deepAnalysisFromMessageMetadata({ createdAt: "x" }), undefined);
  assert.equal(deepAnalysisFromMessageMetadata({}), undefined);
  assert.equal(deepAnalysisFromMessageMetadata(undefined), undefined);
  assert.equal(deepAnalysisFromMessageMetadata(null), undefined);
  assert.equal(
    deepAnalysisFromMessageMetadata({ deep_analysis_run_id: "" }),
    undefined
  );
});

test("강등 키가 없으면 status만 복원한다", () => {
  const result = deepAnalysisFromMessageMetadata({
    deep_analysis_run_id: "a1b2c3d4",
    research_status: "completed",
  });

  assert.equal(result?.run_id, "a1b2c3d4");
  assert.equal(result?.status, "completed");
  assert.equal(result?.degradations, undefined);
});

test("run_id가 있는데 status가 없으면 completed로 본다", () => {
  // 백엔드는 완료된 run 만 메시지로 영속화한다 (deep_analysis_job_task.py).
  const result = deepAnalysisFromMessageMetadata({
    deep_analysis_run_id: "a1b2c3d4",
  });

  assert.equal(result?.status, "completed");
});

test("깨진 강등 값에 던지지 않는다", () => {
  const result = deepAnalysisFromMessageMetadata({
    deep_analysis_run_id: "a1b2c3d4",
    deep_analysis_degradations: [
      null,
      "쓰레기",
      { count: 2 },
      { kind: "", count: 1 },
      { kind: "report_assembly_degraded" },
      { kind: "node_reduction_degraded", count: "셋" },
      { kind: "judge_unreviewed:truncated", count: 2 },
    ],
  });

  assert.deepEqual(result?.degradations, [
    { kind: "report_assembly_degraded", count: 1 },
    { kind: "node_reduction_degraded", count: 1 },
    { kind: "judge_unreviewed:truncated", count: 2 },
  ]);
});

test("강등 배열이 배열이 아니면 무시한다", () => {
  const result = deepAnalysisFromMessageMetadata({
    deep_analysis_run_id: "a1b2c3d4",
    deep_analysis_degradations: "report_assembly_degraded",
  });

  assert.equal(result?.degradations, undefined);
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `pnpm --dir web test:source 2>&1 | grep -i "metadata.test"`
Expected: FAIL — 모듈을 찾을 수 없음 (`lib/deep-analysis/metadata`)

- [ ] **Step 3: 스키마에 `degradations`를 추가한다**

`web/lib/types.ts` 72~76행을 아래로 교체:

```ts
export const deepAnalysisDegradationSchema = z.object({
  kind: z.string(),
  count: z.number(),
});

export const deepAnalysisMetadataSchema = z.object({
  run_id: z.string(),
  events_url: z.string().optional(),
  status: z.enum(["pending", "running", "completed", "failed"]).optional(),
  /**
   * 리포트 품질을 깎은 사건들. 백엔드가 run 종료 시 원장에서 집계해 메시지
   * 메타데이터에 실은 값이며(`deep_analysis_job_task.py`), 새로고침 후에는
   * **이것이 유일한 출처**다 — 종결된 run 은 다시 구독하지 않으므로 라이브
   * 리듀서의 상태가 남지 않는다.
   */
  degradations: z.array(deepAnalysisDegradationSchema).optional(),
});
```

- [ ] **Step 4: `metadata.ts`를 만든다**

`web/lib/deep-analysis/metadata.ts` 신규 생성:

```ts
/**
 * 백엔드 메시지 메타데이터 → `DeepAnalysisMetadata` 브리지
 *
 * ## 왜 필요한가 — 키 이름이 양쪽에서 달랐다
 *
 * 백엔드는 완료된 리포트를 메시지로 저장하면서 메타데이터에
 * `deep_analysis_run_id` / `research_status` / `deep_analysis_degradations`를
 * 심는다(`neos/tasks/deep_analysis_job_task.py`의 `_persist_assistant_message`).
 * 프론트 컴포넌트가 읽는 키는 `deep_analysis` = `{run_id, status, degradations}`다
 * (`components/message.tsx`).
 *
 * 이 불일치 때문에 **새로고침하면 진행 카드가 통째로 사라졌다** — 강등 경고만이
 * 아니라 카드 자체가. `sessionStorage`의 run 포인터도 종결 시
 * `forgetActiveRun()`으로 지워지므로 그 경로로도 복구되지 않았다.
 *
 * 이력 로드 경로(`lib/utils.ts`의 `convertBackendMessagesToUI`)가 백엔드
 * 메타데이터 키를 그대로 통과시키므로, 이 함수가 원본 키를 읽어 프론트 모양으로
 * 옮긴다. 방어적으로 읽는다 — 이력 로드 전체를 깨뜨리면 안 되므로 어떤 입력에도
 * 던지지 않는다.
 */

import type { DeepAnalysisMetadata } from "../types";
import type { DegradationEntry } from "./progress";

const RUN_ID_KEY = "deep_analysis_run_id";
const STATUS_KEY = "research_status";
const DEGRADATIONS_KEY = "deep_analysis_degradations";

const STATUSES = ["pending", "running", "completed", "failed"] as const;
type DeepAnalysisStatus = (typeof STATUSES)[number];

function asStatus(value: unknown): DeepAnalysisStatus | undefined {
  return typeof value === "string" &&
    (STATUSES as readonly string[]).includes(value)
    ? (value as DeepAnalysisStatus)
    : undefined;
}

function asDegradations(value: unknown): DegradationEntry[] | undefined {
  if (!Array.isArray(value)) {
    return;
  }
  const entries: DegradationEntry[] = [];
  for (const raw of value) {
    if (typeof raw !== "object" || raw === null) {
      continue;
    }
    const { kind, count } = raw as { kind?: unknown; count?: unknown };
    if (typeof kind !== "string" || kind.length === 0) {
      continue;
    }
    // 횟수가 깨졌으면 1로 본다 — 사건이 있었다는 사실이 횟수보다 중요하다.
    const valid =
      typeof count === "number" && Number.isFinite(count) && count > 0;
    entries.push({ kind, count: valid ? count : 1 });
  }
  return entries.length > 0 ? entries : undefined;
}

export function deepAnalysisFromMessageMetadata(
  metadata: Record<string, unknown> | undefined | null
): DeepAnalysisMetadata | undefined {
  if (!metadata) {
    return;
  }
  const runId = metadata[RUN_ID_KEY];
  if (typeof runId !== "string" || runId.length === 0) {
    return;
  }
  return {
    run_id: runId,
    // 백엔드는 **완료된** run 만 메시지로 영속화하므로, run_id 가 있는데
    // 상태가 없으면 완료로 본다.
    status: asStatus(metadata[STATUS_KEY]) ?? "completed",
    degradations: asDegradations(metadata[DEGRADATIONS_KEY]),
  };
}
```

- [ ] **Step 5: 이력 로드가 브리지를 거치게 한다**

`web/lib/utils.ts` 상단 import 블록에 추가:

```ts
import { deepAnalysisFromMessageMetadata } from './deep-analysis/metadata';
```

`convertBackendMessagesToUI` 안, "나머지 metadata 필드도 포함" 루프(131~138행) **뒤**에 삽입:

```ts
    // 백엔드 키(`deep_analysis_run_id`)를 프론트 모양(`deep_analysis`)으로 옮긴다.
    // 이 브리지가 없으면 새로고침 후 진행 카드가 통째로 사라진다 — 강등 경고만이
    // 아니라 카드 자체가. 자세한 근거는 `lib/deep-analysis/metadata.ts` 주석 참조.
    const deepAnalysis = deepAnalysisFromMessageMetadata(msg.metadata);
    if (deepAnalysis) {
      metadata.deep_analysis = deepAnalysis;
    }
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `pnpm --dir web test:source && pnpm --dir web exec tsc --noEmit`
Expected: PASS — 157 + 6 = **163 passed**, tsc 무출력

- [ ] **Step 7: 커밋**

```bash
git add web/lib/deep-analysis/metadata.ts web/lib/types.ts web/lib/utils.ts web/tests/source/deep-analysis-metadata.test.ts
git commit -m "fix(web): restore the deep-analysis card after a reload

The backend writes deep_analysis_run_id onto the message; the component
reads deep_analysis. Two names for one contract, so a refresh dropped the
whole status card -- not just its contents.

Nobody noticed because the only thing worth showing afterwards was the
report body, and that lives in the message text. Degradations are the
first state that has to outlive the stream, which is what makes the
mismatch cost something now."
```

---

### Task 7: 컴포넌트가 강등을 그린다

**Files:**
- Modify: `web/components/deep-analysis-status.tsx`

**Interfaces:**
- Consumes: `degradationNotices` (Task 5) · `DeepAnalysisMetadata.degradations` (Task 6) · `progress.degradations` (Task 4)
- Produces: `data-testid="deep-analysis-degradations"` — 향후 Playwright e2e 훅

- [ ] **Step 1: import를 추가한다**

`web/components/deep-analysis-status.tsx` 22행 `import type { DeepAnalysisProgress }` **앞**에 삽입:

```tsx
import { degradationNotices } from "@/lib/deep-analysis/degradation";
```

- [ ] **Step 2: 출처를 고르고 문구를 만든다**

`web/components/deep-analysis-status.tsx` 100~104행(`const phase = ...`부터 `const connectionNote = ...`까지)을 아래로 교체:

```tsx
  const phase = alreadySettled
    ? (deepAnalysis.status as DeepAnalysisProgress["phase"])
    : progress.phase;
  // 우선순위 판단이 아니라 "둘 중 채워진 쪽을 고른다"는 뜻이다. 라이브 세션에서는
  // 구독이 상태를 채우고, 새로고침 후에는 `alreadySettled`라 구독하지 않으므로
  // `progress.degradations`가 항상 비어 있다 — 둘 다 값을 갖는 경우는 없다.
  const notices = degradationNotices(
    progress.degradations.length > 0
      ? progress.degradations
      : (deepAnalysis.degradations ?? [])
  );
  const visibleStats = stats(progress);
  const connectionNote = connectionLabel[connection];
```

- [ ] **Step 3: 강등이 있으면 카드를 펼친 채로 연다**

`web/components/deep-analysis-status.tsx` 109행을 교체:

```tsx
      defaultOpen={
        phase === "running" || phase === "pending" || notices.length > 0
      }
```

- [ ] **Step 4: 경고 블록을 그린다**

`web/components/deep-analysis-status.tsx`의 `lastActivity` 블록(139~143행) **뒤**, `visibleStats` 블록 **앞**에 삽입:

```tsx
          {notices.length > 0 && (
            <ul
              className="space-y-1 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-amber-800 text-xs dark:border-amber-500/20 dark:bg-amber-950/30 dark:text-amber-200"
              data-testid="deep-analysis-degradations"
            >
              {notices.map((notice) => (
                <li className="flex items-start gap-1.5" key={notice.kind}>
                  <AlertTriangleIcon className="mt-0.5 size-3 shrink-0" />
                  <span>{notice.text}</span>
                </li>
              ))}
            </ul>
          )}
```

`AlertTriangleIcon`은 11~17행에서 이미 import 중이므로 추가 import는 없다.

- [ ] **Step 5: `lastActivity` 게이트에 이유를 적는다**

게이트를 **유지**하되 왜 결함이 아닌지 남긴다. `web/components/deep-analysis-status.tsx`의 `{progress.lastActivity && phase !== "completed" && (` 줄 **앞**에 삽입:

```tsx
          {/*
            완료 후 활동 줄을 감추는 것은 의도다. 이 줄은 "지금 무슨 일이
            일어나는가"이고 완료 후엔 의미가 없다. 강등은 위 경고 블록이
            영구히 맡으므로 이 게이트가 강등을 숨기지 않는다 — 게이트를
            없애면 같은 사실이 두 줄로 중복된다.
          */}
```

- [ ] **Step 6: 타입 검사와 전체 프론트 스위트를 확인한다**

Run: `pnpm --dir web exec tsc --noEmit && pnpm --dir web test:source`
Expected: tsc 무출력, **163 passed** (컴포넌트는 test:source 범위 밖이라 건수 불변)

- [ ] **Step 7: 커밋**

```bash
git add web/components/deep-analysis-status.tsx
git commit -m "feat(web): draw the degradations the reducer has been collecting

W2 stopped at state on purpose. This is the render half: an amber block
that survives completion, and a card that opens itself when there is
something to warn about -- a collapsed warning is the silent failure
again, one layer up.

The completed-phase gate on the activity line stays. It hid degradations
only while that line was the sole channel for them; now it just keeps the
same fact from being printed twice."
```

---

### Task 8: 문서 — 로드맵과 결정 원장을 갱신한다

**Files:**
- Modify: `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` (§1 · §2.2 · §5.2 · §7)
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (D27 추가)

**Interfaces:**
- Consumes: Task 1–7의 커밋 해시
- Produces: 없음 (문서만)

- [ ] **Step 1: 커밋 해시를 모은다**

Run: `git log --oneline -8`
Expected: Task 1–7의 커밋 7개가 보인다. 아래 단계에서 `<T1>`…`<T7>`로 참조한다.

- [ ] **Step 2: `DECISIONS.md`에 D27을 추가한다**

`neos/workflow/deep_analysis/DECISIONS.md` 맨 끝에 추가:

```markdown
## D27. 강등은 화면까지 간다. 새로고침 후 출처는 메시지 메타데이터다.

**맥락:** D26이 강등을 상태(`progress.degradations`)까지 밀어냈으나 소비자가 0곳이었고,
종결된 run 은 다시 구독하지 않으므로 새로고침하면 그 상태가 사라졌다. 추적해보니 더
근본적인 문제가 있었다 — 백엔드는 메시지에 `deep_analysis_run_id` 를 심는데 프론트는
`deep_analysis` 를 읽어서, 새로고침하면 **진행 카드가 통째로** 사라졌다.

**결정:** (1) `Ledger.degradations()` 로 원장에서 강등을 집계하고 `execute_run` 을 거쳐
어시스턴트 메시지 메타데이터(`deep_analysis_degradations`)에 영속화한다. (2) 프론트는
라이브 스트림에서 같은 규칙으로 누적하되 새로고침 후에는 메타데이터를 출처로 쓴다.
(3) 굶은 판정자(`report_graded.judge`)를 강등 넷째 항목으로 추가한다. (4) 표시 문구는
`web/lib/deep-analysis/degradation.ts` 순수 함수에 두고 컴포넌트는 map 만 한다.

**근거 — 굶은 판정자:** D26은 강등을 "리포트 내용을 깎았는가"로 정의했다. 판정자는
내용을 바꾸지 않지만 **보증이 부재**한다 — 리포트가 실제 심사 없이 게이트를 통과했다.
축이 다를 뿐 사용자가 알아야 하는 사실은 같다. `graders/report.py` 의 세 강등 모드가
전부 `ok=True` 로 재조립 루프를 끝내므로 `judge` 키가 달린 이벤트는 run 당 최대 1건이고
항상 최종 판정이다 — 중간 시도가 오탐으로 잡히지 않는다.

**근거 — 표시 문구를 lib 에 두는 이유:** `web/package.json` 의 `test:source` 는
`tsx --test` 라 DOM 이 없다. 표시 로직이 컴포넌트로 들어가면 회귀 가드가 0 이 된다.

**기각한 대안:** 종결된 run 도 카드를 펼치면 `after=0` 으로 이력 재생 — 규칙 중복이 0
이고 충실도가 100% 이지만 **펼치지 않으면 영영 모른다.** 접힌 카드에 경고를 띄우려면
먼저 재생해야 하고 재생하려면 펼쳐야 하는 순환이 생긴다.

**남긴 부채:** "어떤 이벤트가 강등인가" 규칙이 두 언어로 구현돼 있다
(`ledger.py._degradation_kind()` / `progress.ts.degradationKind()`). 문구는 프론트 한
곳뿐이라 중복되지 않는다. 상호 참조 주석 · 양쪽 테스트의 동일 fixture · 로드맵 §7 FE6
으로 표시했다. 갈라져도 **과소 보고** 쪽으로 기운다.
```

- [ ] **Step 3: 로드맵 §2.2의 S6을 갱신한다**

`docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md`의 S6 행(97행)을 교체:

```markdown
| S6 | 실패가 사용자에게도 보인다 (원장뿐 아니라 UI에서) | ✅ (2026-08-07, FE4) | `progress.ts`의 `activityLabel()` 커버리지 **그리고** `degradations`를 실제로 그리는 화면 컴포넌트의 존재 |
```

- [ ] **Step 4: 로드맵 §1의 트랙 C 행과 요약을 갱신한다**

33행(트랙 C 행)을 교체:

```markdown
| **C. 프론트엔드** | ✅ job 마이그레이션 완료, ✅ 가시성 갭 해소(FE1·FE4) | §5.3의 저위험 잔여(FE2·FE3)와 신규 FE5·FE6 |
```

47~56행의 "트랙 C 한 줄 요약" 문단 중 마지막 세 문장(“당시 남았던 갭 …” 이후)을 교체:

```markdown
당시 남았던 갭 — 08-02~04에 추가한 실패 이벤트 8종에 FE 라벨이 없던 것(FE1) — 은
W2가 **상태 계층**을(`a9dbcfe3`), FE4가 **화면 계층**을 해소했다: 강등 경고 블록 +
새로고침 복원(백엔드 메타데이터 경유) + 굶은 판정자를 강등 넷째로 추가. 그 과정에서
원래부터 있던 키 이름 불일치도 잡았다 — 백엔드는 `deep_analysis_run_id`를, 프론트는
`deep_analysis`를 읽어서 **새로고침하면 진행 카드가 통째로 사라졌다.**
```

- [ ] **Step 5: 로드맵 §5.2의 마무리 문단을 갱신한다**

339~344행의 "상태 계층만 해소" 문단 중 마지막 문장(“✅ 표시는 …”)을 교체:

```markdown
✅ 표시는 `activityLabel()`이 문자열을 낸다는 뜻이었고, 그 문자열이 화면에 그려지는
문제는 FE4가 해소했다 — `degradations`는 이제 `deep-analysis-status.tsx`의 앰버 경고
블록으로 그려지고, 강등이 있으면 카드가 펼쳐진 채로 열린다.
```

353~356행의 마지막 인용 블록도 갱신:

```markdown
> ⚠️ FE는 `synth_pass`와 `report_graded`는 **이미 인식했다**(`progress.ts:133,136`).
> 즉 W1이 성공하면 그 성과는 FE에 자동으로 나타난다. W2 이전에는 **실패 경로만
> 보이지 않았다** — 성공만 보이고 실패는 침묵하는 비대칭이었다. W2가 `degradations`
> 상태를, FE4가 그 렌더와 새로고침 복원을 붙여 비대칭이 사라졌다.
```

- [ ] **Step 6: 로드맵 §7에서 FE4를 지우고 FE5·FE6을 넣는다**

426행의 FE4 행을 아래 두 행으로 교체:

```markdown
| 🟢 | **FE5** | 실패한 run의 강등은 메시지에 남지 않는다 — `_persist_assistant_message`가 완료 시에만 호출되므로 실패 run은 메시지 자체가 없다. `job_failed` 경로에 같은 영속화를 붙일지 미결 | C |
| 🟢 | **FE6** | 강등 판정 규칙이 두 언어로 구현돼 있다 (`ledger.py._degradation_kind()` / `progress.ts.degradationKind()`). 문구는 FE 한 곳뿐이라 중복 없음. 갈라지면 과소 보고 쪽으로 기운다. 통합하려면 BE가 어휘를 API로 노출하거나 공유 스키마가 필요 — 별도 판단 | C×A |
```

419행 P1 #8 행의 내용을 교체(강등이 새 피해자임을 명시):

```markdown
| 🟡 | P1 #8 | `_persist_assistant_message`가 예외를 삼킴 — FE4 이후 **강등 요약이 이 경로에만 있으므로** 삼킴의 대가가 커졌다. 로그에 `degradations_lost` 건수는 남긴다 | — |
```

- [ ] **Step 7: 문서 링크가 깨지지 않았는지 확인한다**

Run: `grep -n "FE4" docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md`
Expected: §8 W2 문단의 과거 서술만 남고 §1·§7의 미해결 항목으로서의 FE4는 없다. 남아 있는 언급이 전부 "FE4가 해소했다" 맥락인지 눈으로 확인한다.

- [ ] **Step 8: 전체 검증 후 커밋**

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q
pnpm --dir web test:source && pnpm --dir web exec tsc --noEmit
```
Expected: 백엔드 0 failed, 프론트 **163 passed**, tsc 무출력

```bash
git add docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md neos/workflow/deep_analysis/DECISIONS.md
git commit -m "docs(deep-analysis): record FE4 and the debt it deliberately took on

S6 flips to met: degradations now reach a screen and survive a reload.

FE4 leaves the roadmap; FE5 (failed runs persist no message, so no
degradations) and FE6 (the rule is implemented in two languages) take its
place. Naming the debt beats discovering it -- FE3 in this same document
is what happens when a backlog entry points at something that is no
longer true."
```

---

## 최종 검증

전 태스크 완료 후:

```bash
# 백엔드 전체 (로드맵 §10.4 — 현재 참 기준선 2,386 passed / 16 skipped / 0 failed)
.venv/bin/python -m pytest

# 하네스 결정론 베이스라인
HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q

# 프론트
pnpm --dir web test:source && pnpm --dir web exec tsc --noEmit
```

> ⚠️ 회귀 비교 시 `grep '^FAILED tests/'`로 걸러야 한다 — `'^FAILED'`만 쓰면
> 진행 표시(`FAILED  [ 7%]`)까지 걸린다(로드맵 §10.4).

**이 계획은 라이브 표본을 실행하지 않는다.** §10.2의 "정확히 1회" 원칙에 걸리는
W1 표본과 무관하며, LLM 호출 계층을 건드리지 않으므로 "측정 중 변경" 금지에도
해당하지 않는다.
