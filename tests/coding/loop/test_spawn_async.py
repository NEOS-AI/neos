"""비동기 spawn: 즉시 반환 + safe point append (로드맵 K3, 스펙 R-03).

## park 과 무엇이 다른가

park(지금, 기본값): `spawn_agent.v1` 의 도구 결과는 자식이 **접힐 때까지**
쓰이지 않는다. 부모의 매 durable 스텝은 자식을 한 칸 밀 뿐이고, 부모는 자기
턴을 못 돈다.

비동기(K3, 플래그): 도구 결과가 **즉시** 쓰인다. 부모는 다음 턴을 돈다. 자식은
부모의 lease 아래에서 계속 돌고, 끝나면 보고서가 다음 safe point 에 **user
메시지로 append** 된다.

## 왜 append 여야 하는가

K1 의 thinking 가드(`_guard_thinking_prefix`)는 직전 요청과 system·tools·
messages 를 비교해 **비-append 편집**이 있으면 그 경계의 thinking 을 전부
뗀다. 보고서를 도구 결과로 되돌려 끼우거나 기존 메시지를 고쳐 쓰면 그게 곧
비-append 편집이고, 자식을 하나 띄울 때마다 부모의 사고 이력이 날아간다.

## 금지선은 그대로다

가져온 것은 **즉시 반환 + safe point append + 명시적 `await_subagent.v1`**
뿐이다. CC 식 `while(true)` 부모 루프·notification drain·mailbox·coordinator
는 여전히 금지다(PLAN_260913 §2.1, 2026-09-15 개정). 자식을 미는 것은 부모의
durable 스텝이지 별도 루프가 아니다.
"""

from __future__ import annotations

import pytest

from neos.coding.loop.anthropic import AnthropicLoopConfig

from tests.coding.loop.test_anthropic_loop import collect, completed, harness, tool_call
from tests.coding.loop.test_spawn_subagent import (
    _child_tool,
    _make_runtime,
    _text,
    _tool_results,
    _user_texts,
)

pytestmark = pytest.mark.no_db


def _async_on(**kwargs):
    return AnthropicLoopConfig(
        model="claude-test",
        system="code",
        subagent_enabled=True,
        subagent_async_spawn=True,
        **kwargs,
    )


def _spawn_then_talk(prompt: str = "look around", call_id: str = "s1"):
    """부모의 첫 턴은 spawn, 그 다음 턴들은 그냥 말한다.

    park 에서는 두 번째 턴이 **오지 않는다** -- 부모가 자식에 묶여 있으므로.
    """
    return [
        [tool_call(call_id, "spawn_agent.v1", {"prompt": prompt, "max_turns": 4}), completed()],
        [*_text("parent turn two")],
        [*_text("parent turn three")],
        [*_text("parent turn four")],
    ]


def _children(state) -> list[dict]:
    return list(state.get("active_children") or ())


async def test_the_default_is_still_park() -> None:
    """K3 를 켜는 커밋은 코딩 에이전트 지표의 **표본 경계**다(로드맵 §5.3).

    기본값이 조용히 뒤집히면 그 경계가 사라진다.
    """
    assert AnthropicLoopConfig(model="m", system="s").subagent_async_spawn is False


async def test_spawn_returns_a_run_id_without_waiting() -> None:
    runtime, _ = _make_runtime([_child_tool(), _text("child report")])
    h = harness(_spawn_then_talk(), config=_async_on(), subagents=runtime)

    events = await collect(h)

    state = h.repository.checkpoints[-1].loop_state
    results = _tool_results(state)
    assert [item["tool_call_id"] for item in results] == ["s1"]
    assert results[0]["content"]["reason_code"] == "spawned"
    assert str(results[0]["content"]["run_id"]).startswith("sa_")
    assert any(event.type == "tool.completed" for event in events)


async def test_the_child_survives_the_tool_result_that_did_not_fold_it() -> None:
    """park 경로는 spawn 결과를 쓴 뒤 자식을 `active_children` 에서 **지운다**
    -- 결과가 곧 fold 였기 때문이다. 비동기에서는 결과가 fold 가 아니다."""
    runtime, _ = _make_runtime([_child_tool(), _text("child report")])
    h = harness(_spawn_then_talk(), config=_async_on(), subagents=runtime)

    await collect(h)

    children = _children(h.repository.checkpoints[-1].loop_state)
    assert [child["tool_call_id"] for child in children] == ["s1"]
    assert children[0]["delivery"] == "user_message"


async def test_the_parent_takes_its_own_turn_while_the_child_runs() -> None:
    """park 이라면 부모의 두 번째 턴은 오지 않는다."""
    runtime, _ = _make_runtime([_child_tool(), _text("child report")])
    h = harness(_spawn_then_talk(), config=_async_on(), subagents=runtime)
    await collect(h)

    await collect(h, h.repository.checkpoints[-1])

    assert any(
        "parent turn two" in text
        for text in _assistant_texts(h.repository.checkpoints[-1].loop_state)
    )


def _assistant_texts(state) -> list[str]:
    return [
        item["text"]
        for message in state["transcript"]
        if message["role"] == "assistant"
        for item in message["content"]
        if item.get("type") == "text"
    ]


async def test_the_report_arrives_as_a_user_message_not_a_second_tool_result() -> None:
    runtime, _ = _make_runtime([_child_tool(), _text("handler lives in login.py")])
    h = harness(_spawn_then_talk(), config=_async_on(), subagents=runtime)

    state = await _run_until_child_reports(h)

    assert any("login.py" in text for text in _user_texts(state))
    assert [item["tool_call_id"] for item in _tool_results(state)] == ["s1"]


async def test_the_finished_child_leaves_the_checkpoint() -> None:
    runtime, _ = _make_runtime([_child_tool(), _text("handler lives in login.py")])
    h = harness(_spawn_then_talk(), config=_async_on(), subagents=runtime)

    state = await _run_until_child_reports(h)

    assert _children(state) == []


async def test_the_report_is_appended_exactly_once() -> None:
    """부모 턴은 계속 돈다. 보고서가 턴마다 다시 붙으면 이력이 부풀고
    `_guard_thinking_prefix` 가 보는 prefix 가 매번 달라진다."""
    runtime, _ = _make_runtime([_child_tool(), _text("handler lives in login.py")])
    h = harness(_spawn_then_talk(), config=_async_on(), subagents=runtime)
    state = await _run_until_child_reports(h)

    await collect(h, h.repository.checkpoints[-1])

    after = h.repository.checkpoints[-1].loop_state
    assert sum("login.py" in text for text in _user_texts(after)) == 1
    assert sum("login.py" in text for text in _user_texts(state)) == 1


async def test_the_parent_cannot_finish_while_its_child_still_runs() -> None:
    """park 은 이 상태에 닿을 수 없었다 -- 부모가 자식에 묶여 있었으므로.

    비동기에서는 닿는다: 모델이 "끝났다"고 말하는데 자기가 띄운 자식이 아직
    돈다. 그냥 끝내면 보고서는 **아무도 읽지 않는 이력**에 떨어진다.
    """
    runtime, _ = _make_runtime([_child_tool(), _text("handler lives in login.py")])
    h = harness(_spawn_then_talk(), config=_async_on(), subagents=runtime)
    await collect(h)

    await collect(h, h.repository.checkpoints[-1])

    state = h.repository.checkpoints[-1].loop_state
    assert state["terminal_pending"] is False
    assert any("Still running" in text for text in _user_texts(state))


async def test_the_hold_lets_go_once_the_report_arrives() -> None:
    """붙잡기는 카운터가 아니라 **자식의 남은 턴**이 한계다. 영원하면 그것이
    금지된 드레인 루프다."""
    runtime, _ = _make_runtime([_child_tool(), _text("handler lives in login.py")])
    h = harness(_spawn_then_talk(), config=_async_on(), subagents=runtime)

    state = await _run_until_child_reports(h)

    assert _children(state) == []
    final = await collect(h, h.repository.checkpoints[-1])
    assert h.repository.checkpoints[-1].loop_state["terminal_pending"] is True
    assert final is not None


# ---- await_subagent.v1 — 명시적 park -------------------------------------------


def _spawn_then_await(call_id: str = "s1", await_id: str = "w1"):
    """부모가 자식을 띄우고, 같은 턴이 아니라 **다음 턴에** 기다린다.

    run_id 를 알아야 기다릴 수 있고, run_id 는 spawn 의 도구 결과에 있다.
    """
    return [
        [tool_call(call_id, "spawn_agent.v1", {"prompt": "look", "max_turns": 4}), completed()],
        [tool_call(await_id, "await_subagent.v1", {"run_id": "__spawned__"}), completed()],
        [*_text("parent done")],
    ]


async def _await_the_spawned_child(h, *, limit: int = 8):
    """`__spawned__` 자리표를 실제 run_id 로 바꿔 넣고 fold 까지 민다."""
    await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    run_id = _tool_results(state)[0]["content"]["run_id"]
    for turn in h.model.turns:
        for event in turn:
            if getattr(event, "name", "") == "await_subagent.v1":
                event.input["run_id"] = run_id
    checkpoint = h.repository.checkpoints[-1]
    for _ in range(limit):
        await collect(h, checkpoint)
        checkpoint = h.repository.checkpoints[-1]
        results = {item["tool_call_id"] for item in _tool_results(checkpoint.loop_state)}
        if "w1" in results:
            return checkpoint.loop_state, run_id
    raise AssertionError("await 가 끝나지 않았다")


async def test_await_delivers_the_report_as_its_own_tool_result() -> None:
    """이것이 append 와 다른 **명시적** 경로다 -- 모델이 기다리겠다고 말했으니
    보고서는 그 호출의 답이 된다."""
    runtime, _ = _make_runtime([_child_tool(), _text("handler lives in login.py")])
    h = harness(_spawn_then_await(), config=_async_on(), subagents=runtime)

    state, _ = await _await_the_spawned_child(h)

    result = next(
        item["content"] for item in _tool_results(state) if item["tool_call_id"] == "w1"
    )
    assert "login.py" in str(result.get("summary") or "")
    assert result["child_status"] == "completed"


async def test_an_awaited_child_leaves_by_exactly_one_door() -> None:
    """보고서는 도구 결과로만 간다 -- user 메시지로 또 붙지 않는다.

    그리고 ref 가 남으면 안 된다. 남으면 `_hold_for_detached_children` 이
    이미 끝난 자식을 기다리며 부모를 영원히 붙잡는다.
    """
    runtime, _ = _make_runtime([_child_tool(), _text("handler lives in login.py")])
    h = harness(_spawn_then_await(), config=_async_on(), subagents=runtime)

    state, _ = await _await_the_spawned_child(h)

    assert not any("login.py" in text for text in _user_texts(state))
    assert _children(state) == []


async def test_awaiting_keeps_one_ref_for_one_run() -> None:
    """park 경로는 ref 를 **호출 id**로 꽂는다. await 의 호출 id 는 spawn 의 것과
    다르므로, 그대로 두면 같은 run 에 ref 가 둘 생긴다."""
    runtime, _ = _make_runtime(
        [_child_tool(), _child_tool("b.py"), _text("handler lives in login.py")]
    )
    h = harness(_spawn_then_await(), config=_async_on(), subagents=runtime)
    await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    run_id = _tool_results(state)[0]["content"]["run_id"]
    for turn in h.model.turns:
        for event in turn:
            if getattr(event, "name", "") == "await_subagent.v1":
                event.input["run_id"] = run_id

    await collect(h, h.repository.checkpoints[-1])

    children = _children(h.repository.checkpoints[-1].loop_state)
    assert [child["run_id"] for child in children] == [run_id]


async def test_awaiting_a_child_that_already_reported_says_so() -> None:
    """safe point 가 먼저 배달했을 수 있다. 그때 조용한 실패는 모델에게
    '그런 자식 없음'처럼 보인다."""
    runtime, _ = _make_runtime([_child_tool(), _text("handler lives in login.py")])
    h = harness(
        [
            [tool_call("s1", "spawn_agent.v1", {"prompt": "look", "max_turns": 4}), completed()],
            [*_text("thinking")],
            [tool_call("w1", "await_subagent.v1", {"run_id": "sa_gone"}), completed()],
            [*_text("parent done")],
        ],
        config=_async_on(),
        subagents=runtime,
    )

    await _run_until_child_reports(h)
    checkpoint = h.repository.checkpoints[-1]
    for _ in range(4):
        await collect(h, checkpoint)
        checkpoint = h.repository.checkpoints[-1]
        results = {
            item["tool_call_id"]: item["content"]
            for item in _tool_results(checkpoint.loop_state)
        }
        if "w1" in results:
            assert results["w1"]["reason_code"] == "policy_not_live"
            return
    raise AssertionError("await 가 답을 내지 않았다")


async def _run_until_child_reports(h, *, limit: int = 6):
    checkpoint = h.repository.checkpoints[-1] if h.repository.checkpoints else None
    for _ in range(limit):
        await collect(h, checkpoint)
        checkpoint = h.repository.checkpoints[-1]
        if any("login.py" in text for text in _user_texts(checkpoint.loop_state)):
            return checkpoint.loop_state
    raise AssertionError("자식 보고서가 부모 이력에 도착하지 않았다")
