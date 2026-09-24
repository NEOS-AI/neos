"""LLM 을 카세트로 재생한다 (로드맵 J3: "저장된 blob·**카세트**").

`CodingModel` 은 `stream(request)` 하나짜리 프로토콜이라 포트를 갈아끼우는
값이 싸다 -- `ToolPort` 와 같은 이유다. `build_research_runtime(port, *,
session_factory, model=None)` 의 `model` 이 그 자리다.

## 키에서 무엇을 빼는가가 이 모듈의 전부다

`ChildStepper._run_model` 이 짓는 `ModelRequest` 에는 **매번 달라지는 것**이
셋 있다: `turn_id` 는 `f"sat_{uuid4().hex}"` 이고 `task_id`·`run_id` 는 그
실행의 것이다. 이 셋을 키에 넣으면 재생은 **모든 호출에서 빗나간다** --
그리고 그 실패는 "카세트가 비었나?" 처럼 보여서 원인을 엉뚱한 데서 찾게
된다.

넣는 것은 **모델이 본 것**이다: system · messages · 도구 목록 · 모델 이름 ·
출력 상한. 도구 설명을 고치면 빗나가는 것이 맞다 -- 그 녹음은 더 이상 지금
모델이 무슨 말을 할지에 대한 증거가 아니다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelLimits,
    ModelRequest,
    ModelUsage,
    TextDelta,
    ThinkingCompleted,
    ToolCallCompleted,
    ToolDefinition,
    ToolInputDelta,
)
from neos.workflow.deep_analysis.cassette import Cassette

pytestmark = pytest.mark.no_db


def _tool(description: str = "Fetch one http(s) URL as evidence.") -> ToolDefinition:
    return ToolDefinition(
        name="fetch.v1",
        description=description,
        input_schema={"type": "object", "properties": {"url": {"type": "string"}}},
    )


def _text(role: str, body: str) -> CanonicalMessage:
    from neos.coding.model.base import TextContent

    return CanonicalMessage(role=role, content=(TextContent(text=body),))


def _request(
    *,
    body: str = "질문",
    turn_id: str = "sat_aaaa",
    run_id: str = "run_a",
    task_id: str = "task_a",
    tool_description: str = "Fetch one http(s) URL as evidence.",
    model: str = "claude-opus-5-5",
) -> ModelRequest:
    return ModelRequest(
        system="당신은 조사 워커다",
        messages=(_text("user", body),),
        tools=(_tool(tool_description),),
        model=model,
        limits=ModelLimits(max_output_tokens=4096, timeout_sec=120),
        task_id=task_id,
        run_id=run_id,
        turn_id=turn_id,
    )


class _LiveModel:
    """녹음할 진짜 모델 자리."""

    def __init__(self, events) -> None:
        self._events = list(events)
        self.calls = 0

    async def stream(self, request):
        self.calls += 1
        for event in self._events:
            yield event


def _events():
    return [
        ThinkingCompleted(thinking="생각", signature="sig"),
        TextDelta(text="답"),
        ToolInputDelta(tool_call_id="t1", name="fetch.v1", partial_json='{"url"'),
        ToolCallCompleted(
            tool_call_id="t1", name="fetch.v1", input={"url": "https://a"}
        ),
        ModelCompleted(
            stop_reason="tool_use",
            usage=ModelUsage(input_tokens=10, output_tokens=5),
        ),
    ]


async def _drain(model, request):
    return [event async for event in model.stream(request)]


def _model(cassette, inner=None):
    from neos.workflow.deep_analysis.cassette_model import CassetteModel

    return CassetteModel(cassette, inner=inner)


# ---- 녹음과 재생 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_event_kind_survives_a_round_trip(tmp_path: Path) -> None:
    """다섯 종 전부다. 하나라도 빠지면 재생된 턴이 원본과 다른 턴이 된다."""
    path = tmp_path / "c.json"
    live = _LiveModel(_events())
    recorder = Cassette(path, mode="record")

    recorded = await _drain(_model(recorder, live), _request())
    recorder.save()
    replayed = await _drain(_model(Cassette(path, mode="replay")), _request())

    assert recorded == _events()
    assert replayed == _events()


@pytest.mark.asyncio
async def test_replay_never_touches_the_live_model(tmp_path: Path) -> None:
    """오프라인이라는 말의 뜻이다."""
    path = tmp_path / "c.json"
    live = _LiveModel(_events())
    recorder = Cassette(path, mode="record")
    await _drain(_model(recorder, live), _request())
    recorder.save()

    await _drain(_model(Cassette(path, mode="replay")), _request())

    assert live.calls == 1


# ---- 키 (이 모듈의 전부) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_ids_that_change_every_call_are_not_in_the_key(
    tmp_path: Path,
) -> None:
    """`turn_id` 는 `uuid4()` 다. 키에 넣으면 재생이 **항상** 빗나간다."""
    path = tmp_path / "c.json"
    recorder = Cassette(path, mode="record")
    await _drain(_model(recorder, _LiveModel(_events())), _request())
    recorder.save()

    replayed = await _drain(
        _model(Cassette(path, mode="replay")),
        _request(turn_id="sat_zzzz", run_id="run_b", task_id="task_b"),
    )

    assert replayed == _events()


@pytest.mark.asyncio
async def test_a_different_conversation_misses(tmp_path: Path) -> None:
    """messages 가 키에 있어야 카세트가 대화를 재생한다.

    없으면 어떤 질문을 해도 녹음된 답 하나가 돌아온다 -- 그것은 재생이
    아니라 상수다.
    """
    path = tmp_path / "c.json"
    recorder = Cassette(path, mode="record")
    await _drain(_model(recorder, _LiveModel(_events())), _request())
    recorder.save()

    with pytest.raises(KeyError):
        await _drain(_model(Cassette(path, mode="replay")), _request(body="다른 질문"))


@pytest.mark.asyncio
async def test_an_edited_tool_description_misses(tmp_path: Path) -> None:
    """도구 문구를 고치면 그 녹음은 더 이상 증거가 아니다 (I1 과 같은 이유).

    빗나감이 맞는 답이다 -- 옛 답을 새 프롬프트의 답인 양 돌려주면 섀도
    비교가 **존재하지 않는 실행**을 비교한다.
    """
    path = tmp_path / "c.json"
    recorder = Cassette(path, mode="record")
    await _drain(_model(recorder, _LiveModel(_events())), _request())
    recorder.save()

    with pytest.raises(KeyError):
        await _drain(
            _model(Cassette(path, mode="replay")),
            _request(tool_description="Fetch a URL. Also, be brief."),
        )


@pytest.mark.asyncio
async def test_a_different_model_misses(tmp_path: Path) -> None:
    """모델을 바꾸면 답도 바뀐다. 옛 모델의 답을 새 모델 것으로 싣지 않는다."""
    path = tmp_path / "c.json"
    recorder = Cassette(path, mode="record")
    await _drain(_model(recorder, _LiveModel(_events())), _request())
    recorder.save()

    with pytest.raises(KeyError):
        await _drain(
            _model(Cassette(path, mode="replay")), _request(model="claude-sonnet-5")
        )


# ---- 배선 사고 -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_without_a_live_model_is_a_wiring_error(
    tmp_path: Path,
) -> None:
    """조용히 빈 턴을 내지 않는다 -- 빈 턴은 모델이 아무 말도 안 한 것이고,
    그것은 카세트가 비어 있다는 사실을 녹음해 버린다."""
    with pytest.raises(ValueError, match="inner"):
        await _drain(
            _model(Cassette(tmp_path / "c.json", mode="record")), _request()
        )


@pytest.mark.asyncio
async def test_an_off_cassette_is_a_pass_through(tmp_path: Path) -> None:
    """같은 래퍼가 라이브에서도 쓰인다 -- 경로가 둘이면 한쪽만 고쳐진다."""
    live = _LiveModel(_events())

    result = await _drain(
        _model(Cassette(tmp_path / "c.json", mode="off"), live), _request()
    )

    assert result == _events()
    assert live.calls == 1


def test_the_codec_covers_the_whole_event_union() -> None:
    """종류가 늘면 여기서 걸린다.

    `_encode_event` 는 모르는 종류에 `TypeError` 를 던지지만, **아무도 그
    종류를 만들지 않으면 아무 테스트도 빨개지지 않는다** -- 새 이벤트를 내는
    프로바이더가 붙는 날 녹음이 조용히 죽는다. 그래서 목록을 손으로 적지 않고
    유니온에서 유도한다(`submission.REPAIR_ACTIONS` 와 같은 규율).
    """
    from typing import get_args

    from neos.coding.model.base import ModelEvent
    from neos.workflow.deep_analysis.cassette_model import _encode_event

    members = {member.__name__ for member in get_args(ModelEvent)}
    # 대조 테스트가 덜 검사할 수 있다 -- 유니온을 못 읽으면 루프가 0회 돈다.
    assert len(members) >= 5

    encoded = {
        "TextDelta": TextDelta(text="a"),
        "ToolInputDelta": ToolInputDelta(
            tool_call_id="t", name="n", partial_json="{"
        ),
        "ToolCallCompleted": ToolCallCompleted(
            tool_call_id="t", name="n", input={}
        ),
        "ThinkingCompleted": ThinkingCompleted(thinking="t", signature="s"),
        "ModelCompleted": ModelCompleted(stop_reason="end_turn"),
    }
    assert set(encoded) == members, (
        "ModelEvent 유니온이 바뀌었다 -- `_encode_event`/`_decode_event` 와 "
        "이 표본을 같이 고칠 것. 빠뜨리면 녹음이 그 종류를 조용히 잃는다."
    )
    for event in encoded.values():
        assert _encode_event(event)["type"] == type(event).__name__
