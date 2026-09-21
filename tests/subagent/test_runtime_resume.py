"""부모가 티켓을 들고 있지 않은 자식을 한 스텝 돌린다 (로드맵 K3).

## 왜 `advance` 로는 안 되는가

`advance` 는 `SubagentTicket` 을 받고, 티켓은 `briefing` 을 **필수**로 요구한다.
park 모드에서는 그게 맞다 -- 부모의 `spawn_agent.v1` 호출이 아직 pending 이라
`call.input` 에서 brief 를 매번 다시 짓는다.

비동기 spawn(K3)에서는 도구 결과가 **이미** 쓰였다. 부모에게는 pending 호출이
없고, 따라서 brief 도 없다. 부모가 brief 를 체크포인트에 복제해 들고 다니게
하면 같은 사실이 두 곳에 살고, 둘이 갈라지는 날이 온다 -- store 의 `RunRecord`
가 이미 brief 를 갖고 있다.

## brief 가 쓰이는 자리는 하나뿐이고, 그래서 놓치기 쉽다

`ChildStepper._restore` 는 `restore_state` 가 있으면 brief 를 **쓰지 않는다**.
그래서 이미 한 스텝 돈 자식에게는 brief 가 뭐든 티가 안 난다. 티가 나는 것은
run 은 만들어졌는데 첫 스텝이 커밋되지 않은 경우뿐이다(CAS 불일치·중단).
`test_a_run_that_never_took_a_step_still_gets_its_original_brief` 가 그 한
자리를 잡는다 -- brief 를 흘리는 배선이 끊겨도 나머지 테스트는 전부 초록이다.

`ParentBriefing` 이 빈 goal 을 거부하므로 "빈 지시로 조용히 출발"하지는
**않는다.** 대신 부모가 brief 사본을 못 만들면 그 자식은 아예 **재개 불가**가
된다. 어느 쪽이든 사본을 들고 다니는 설계가 진다.
"""

from __future__ import annotations

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.types import StepKind, SubagentStatus

from tests.subagent.test_runtime import _runtime, _ticket, _tool

pytestmark = pytest.mark.no_db


def _text(text: str = "report"):
    return (TextDelta(text), ModelCompleted("end_turn", ModelUsage(3, 2)))


def _user_text(request) -> str:
    """자식이 읽은 **모든** user 메시지. 조종은 뒤쪽 턴에 붙는다."""
    return "\n".join(
        str(getattr(item, "text", ""))
        for message in request.messages
        if message.role == "user"
        for item in message.content
    )


async def test_resume_advances_a_run_without_a_ticket() -> None:
    """한 스텝이 곧 한 모델 턴은 아니다 -- pending 도구가 있으면 그 스텝은
    도구 실행이다. 그래서 진전은 모델 호출 수가 아니라 **체크포인트**로 본다."""
    store = InMemorySubagentStore()
    runtime, _, _, model, _ = _runtime(
        [_tool(), _text("second")], store=store
    )
    first = await runtime.advance(_ticket(max_turns=2))

    outcome = await runtime.resume(
        first.run_id, expected_checkpoint_id=first.checkpoint_id
    )

    assert outcome.run_id == first.run_id
    assert outcome.checkpoint_id != first.checkpoint_id


async def test_a_run_that_never_took_a_step_still_gets_its_original_brief() -> None:
    """**이 테스트가 이 모듈의 이유다.**

    run 은 있고 체크포인트는 없다 -- brief 가 실제로 읽히는 유일한 상태다.
    다른 다섯 테스트는 brief 배선이 끊겨도 초록이다.
    """
    store = InMemorySubagentStore()
    runtime, _, _, model, _ = _runtime([_text("report")], store=store)
    record = await store.resolve_or_create(
        _ticket(briefing=_ticket().briefing)
    )

    await runtime.resume(record.run_id, expected_checkpoint_id=None)

    assert "Find the login handler" in _user_text(model.requests[0])


async def test_resume_keeps_the_spawn_depth_the_parent_granted() -> None:
    """깊이는 **부모의 예산**이지 run 의 속성이 아니다 -- store 에 없다.

    잃어버리면 depth 1 자식이 다시 낳을 수 있게 된다(fail-closed 위반).
    """
    store = InMemorySubagentStore()
    runtime, _, _, model, _ = _runtime([_tool(), _text("b")], store=store)
    first = await runtime.advance(_ticket(max_turns=2, spawn_depth=1))
    drained = await runtime.resume(
        first.run_id, expected_checkpoint_id=first.checkpoint_id, spawn_depth=1
    )

    await runtime.resume(
        first.run_id, expected_checkpoint_id=drained.checkpoint_id, spawn_depth=1
    )

    # 두 번째 모델 턴이 실제로 있었는지 먼저 본다 -- 없으면 아래 단언이
    # 첫 요청을 다시 보며 공허하게 통과한다.
    assert len(model.requests) == 2
    offered = {tool.name for tool in model.requests[-1].tools}
    assert "spawn_agent.v1" not in offered


async def test_resume_carries_a_pending_steer() -> None:
    """조종은 도구를 도는 중에도 들어온다 -- 다음 **모델 턴**까지 살아남아야 한다.

    park 경로와 같은 계약이다: 부모는 자식이 **적용할 때까지 매 스텝 다시
    보낸다**. 중복은 `_steer_remainder` 가 `steer_applied` 로 걸러낸다. 빈 값을
    보내면 아직 적용 안 된 조종이 지워지므로, 호출부는 `ref.pending_steer` 를
    계속 실어야 한다.
    """
    store = InMemorySubagentStore()
    runtime, _, _, model, _ = _runtime([_tool(), _text("b")], store=store)
    first = await runtime.advance(_ticket(max_turns=2))
    drained = await runtime.resume(
        first.run_id,
        expected_checkpoint_id=first.checkpoint_id,
        pending_steer="look at the router too",
    )

    await runtime.resume(
        first.run_id,
        expected_checkpoint_id=drained.checkpoint_id,
        pending_steer="look at the router too",
    )

    assert len(model.requests) == 2
    assert "look at the router too" in _user_text(model.requests[-1])


async def test_a_stale_checkpoint_does_not_step_the_child() -> None:
    """CAS 는 park 경로와 같은 규칙이다 -- 부모의 관점이 낡았으면 돌리지 않는다."""
    store = InMemorySubagentStore()
    runtime, _, _, model, events = _runtime(
        [_tool(), _text("b")], store=store
    )
    first = await runtime.advance(_ticket(max_turns=2))

    await runtime.resume(first.run_id, expected_checkpoint_id="ckpt_stale")

    assert len(model.requests) == 1
    assert any(kind == "subagent.cas_mismatch" for kind, _ in events.events)


async def test_resuming_a_finished_run_does_not_call_the_model() -> None:
    store = InMemorySubagentStore()
    runtime, _, _, model, _ = _runtime([_text("done")], store=store)
    first = await runtime.advance(_ticket(max_turns=1))
    assert first.kind is not StepKind.CONTINUING

    outcome = await runtime.resume(
        first.run_id, expected_checkpoint_id=first.checkpoint_id
    )

    assert len(model.requests) == 1
    assert outcome.status is SubagentStatus.COMPLETED
