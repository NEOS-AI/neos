"""DA 호출이 해석된 사고량을 실제 요청에 싣는다 (로드맵 K5 ④).

K5 ①~③ 은 카탈로그 필드 · 해석 사슬 · 어댑터 번역을 세웠다. 그러나 해석
결과를 요청에 싣는 **호출부가 0개**였다 -- `resolve_harness_effort` 를 부르는
것은 테스트뿐이었다(로드맵 §14 "호출부 0개" 의 또 한 판).

이 파일이 고정하는 것:

- 값이 없으면 요청이 **예전과 바이트가 같다** (그래서 표본 경계가 아니다, §8)
- 값이 있으면 세 출구(주입 SDK · 하네스 · 카세트 키) 모두에 도착한다
- 재시도(잘림 확장)도 같은 값을 싣는다 -- 첫 시도만 고쳐지는 것이 흔한 사본이다
- DA 패키지의 모든 호출부가 `effort=` 를 **명시한다** (AST)
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta
from neos.workflow.deep_analysis.cassette import Cassette
from neos.workflow.deep_analysis.llm import call_json, call_llm, call_text

pytestmark = pytest.mark.no_db

_MODEL = "claude-opus-5-5"


class _FakeAnthropic:
    def __init__(self, texts, stop_reasons=None) -> None:
        self._texts = list(texts)
        self._stops = list(stop_reasons or ["end_turn"] * len(self._texts))
        self.messages = self
        self.kwargs: list[dict] = []

    async def create(self, **kwargs):
        self.kwargs.append(kwargs)
        text = self._texts.pop(0)
        stop = self._stops.pop(0)

        class Usage:
            input_tokens = 10
            output_tokens = 5

        class Block:
            type = "text"

        Block.text = text

        class Response:
            content = [Block()]
            usage = Usage()
            model = kwargs["model"]
            stop_reason = stop

        return Response()


class _ScriptedCodingModel:
    def __init__(self) -> None:
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        yield TextDelta("ok")
        yield ModelCompleted("end_turn", ModelUsage(4, 2))


# -- 값이 없으면 바이트가 같다 ------------------------------------------------


@pytest.mark.asyncio
async def test_no_effort_sends_no_output_config() -> None:
    client = _FakeAnthropic(["x"])

    await call_llm(_MODEL, "p", max_tokens=100, client=client, effort=None)

    assert "output_config" not in client.kwargs[0]


@pytest.mark.asyncio
async def test_explicit_none_equals_omitting_the_argument() -> None:
    """배선 전 호출(인자 없음)과 배선 후 호출(None)이 같은 요청을 만든다."""
    before, after = _FakeAnthropic(["x"]), _FakeAnthropic(["x"])

    await call_llm(_MODEL, "p", max_tokens=100, client=before)
    await call_llm(_MODEL, "p", max_tokens=100, client=after, effort=None)

    assert before.kwargs == after.kwargs


@pytest.mark.asyncio
async def test_harness_limits_carry_no_effort_when_unset() -> None:
    model = _ScriptedCodingModel()

    await call_llm(_MODEL, "p", max_tokens=100, client=model, effort=None)

    assert model.requests[0].limits.effort == ""


# -- 값이 있으면 세 출구에 도착한다 --------------------------------------------


@pytest.mark.asyncio
async def test_effort_reaches_the_injected_sdk_request() -> None:
    client = _FakeAnthropic(["x"])

    await call_llm(_MODEL, "p", max_tokens=100, client=client, effort="high")

    assert client.kwargs[0]["output_config"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_effort_reaches_the_harness_limits() -> None:
    model = _ScriptedCodingModel()

    await call_llm(_MODEL, "p", max_tokens=100, client=model, effort="high")

    assert model.requests[0].limits.effort == "high"


@pytest.mark.asyncio
async def test_cassette_key_is_unchanged_without_effort(tmp_path) -> None:
    """기존 golden 카세트는 effort 를 보내지 않던 때 녹음됐다. 그 키가 그대로여야 한다."""
    cassette = Cassette(tmp_path / "c.json", mode="record")

    await call_llm(
        _MODEL, "p", max_tokens=100, client=_FakeAnthropic(["x"]),
        cassette=cassette, effort=None,
    )

    legacy = cassette.key(
        "llm",
        {"model": _MODEL, "prompt": "p", "max_tokens": 100, "temperature": 0.0},
    )
    assert list(cassette._data) == [legacy]


@pytest.mark.asyncio
async def test_cassette_keys_differ_by_effort(tmp_path) -> None:
    """low 로 녹음한 호출이 high 요청에서 적중하면 존재하지 않는 실행을 재생한다."""
    cassette = Cassette(tmp_path / "c.json", mode="record")

    for effort in (None, "low", "high"):
        await call_llm(
            _MODEL, "p", max_tokens=100, client=_FakeAnthropic(["x"]),
            cassette=cassette, effort=effort,
        )

    assert len(cassette._data) == 3


# -- 재시도도 같은 값을 싣는다 -------------------------------------------------


@pytest.mark.asyncio
async def test_call_json_retries_carry_the_same_effort() -> None:
    """잘림 확장 재시도와 파싱 재시도 모두."""
    client = _FakeAnthropic(
        ['{"cut', "not json", '{"ok": 1}'],
        stop_reasons=["max_tokens", "end_turn", "end_turn"],
    )

    data, _ = await call_json(
        _MODEL, "p", max_tokens=100, client=client, retries=1, effort="low"
    )

    assert data == {"ok": 1}
    assert [k.get("output_config") for k in client.kwargs] == [
        {"effort": "low"}
    ] * 3


@pytest.mark.asyncio
async def test_call_text_expansion_carries_the_same_effort() -> None:
    client = _FakeAnthropic(["cut", "whole"], stop_reasons=["max_tokens", "end_turn"])

    response = await call_text(
        _MODEL, "p", max_tokens=100, client=client, effort="xhigh"
    )

    assert response.text == "whole"
    assert [k.get("output_config") for k in client.kwargs] == [
        {"effort": "xhigh"}
    ] * 2


# -- 모든 호출부가 사고량을 명시한다 --------------------------------------------

_DA_ROOT = Path(__file__).resolve().parents[3] / "neos/workflow/deep_analysis"

#: 모델을 부르는 이름. 주입된 호출자(`self.llm_call` 등)도 여기 든다 --
#: synthesizer 와 report 판정자는 `call_json` 을 직접 부르지 않는다.
_DISPATCHERS = frozenset(
    {
        "call_llm",
        "call_messages",
        "call_json",
        "call_text",
        "llm_call",
        "json_call",
        "_billed_call_json",
        "run_discovery",
    }
)


def _dispatch_calls_without_effort() -> list[str]:
    missing = []
    for path in sorted(_DA_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name not in _DISPATCHERS:
                continue
            keywords = {k.arg for k in node.keywords}
            # `*args, **kwargs` 를 그대로 넘기는 래퍼(`_billed_call_json`)는
            # 자기 호출부가 검사된다.
            if "effort" in keywords or None in keywords:
                continue
            rel = path.relative_to(_DA_ROOT)
            missing.append(f"{rel}:{node.lineno} {name}")
    return missing


def test_every_da_dispatch_states_its_effort() -> None:
    """빠진 호출부는 **조용히** 기본값(None)으로 돈다 -- 역할이 high 를 요구해도.

    `effort=None` 을 명시하는 것은 허용한다(모델 단위 preflight 처럼). 빠뜨리는
    것만 막는다: 새 단계를 더하면서 이 인자를 잊는 것이 이 검사가 막는 사고다.
    """
    assert _dispatch_calls_without_effort() == []


def test_the_guard_sees_the_call_sites() -> None:
    """가드가 무엇을 보는지 이름으로 확인한다 -- 0 곳을 훑는 가드도 초록이다."""
    seen = set()
    for path in sorted(_DA_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "stage" and isinstance(
                        keyword.value, ast.Constant
                    ):
                        seen.add(keyword.value.value)

    assert {
        "decompose",
        "split_decompose",
        "subq_review",
        "worker_analysis",
        "worker_repair",
        "claim_entailment",
        "claim_grading",
        "report_grading",
        "report_assembly",
        "node_reduction",
        "discovery",
        "preflight",
    } <= seen
