"""P-05 -- 컴팩션 요약에 공식 보존 지시를 쓴다 (로드맵 K7 잔여 · 스펙 P-05).

예전 요약 지시는 `facts only. <= 200 words` 에 출력 512 였다. 공식 문서는 정반대를
요구한다 -- 여섯 항목은 **길어지더라도 완전하게**, 사용자 발화는 **원래 표현에
가깝게**. 200 단어 안에서는 요청 원문 · 결정 · 제약이 눌려 사라진다.

켜는 것은 코딩 에이전트 지표의 표본 경계다(§8 행 11). 그래서 이 파일의 첫
절은 **꺼져 있으면 요청이 예전과 같다** 를 고정한다.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from neos.coding.loop.anthropic import AnthropicLoopConfig
from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelUsage,
    TextContent,
    TextDelta,
)
from neos.coding.prompts.official import COMPACTION_SUMMARY_INSTRUCTION
from tests.coding.loop.test_anthropic_loop import INPUT, harness

pytestmark = pytest.mark.no_db

_LEGACY_SYSTEM = "Summarize prior coding context as facts only. <= 200 words."


def _state(h):
    prefix = tuple(
        CanonicalMessage("user", (TextContent(f"note {index} " + "x" * 20),))
        for index in range(4)
    )
    return replace(
        h.loop._restore(INPUT, None),
        transcript=(CanonicalMessage("user", (TextContent("Fix it"),)),) + prefix,
        llm_compact_attempts=0,
        instructions_loaded=True,
    )


def _reply(text: str, stop: str = "end_turn"):
    return [[TextDelta(text), ModelCompleted(stop, ModelUsage(1, 1))]]


# -- 꺼져 있으면 예전과 같다 ----------------------------------------------------


@pytest.mark.asyncio
async def test_off_sends_the_legacy_request() -> None:
    config = AnthropicLoopConfig(model="claude-test", system="code", timeout_sec=120)
    h = harness(_reply("old style facts"), config=config)

    after = await h.loop._compact_after_prompt_too_long(_state(h))

    request = h.model.requests[0]
    assert request.system == _LEGACY_SYSTEM
    assert request.limits.max_output_tokens == 512
    assert request.limits.timeout_sec == 30
    # 꺼져 있으면 응답을 가공하지 않는다 -- 태그 추출은 켜졌을 때만이다.
    assert after.summary == "old style facts"


def test_the_flag_is_off_by_default() -> None:
    from neos.config.schema import CodingModelConfig

    assert CodingModelConfig().compaction_preserving_summary is False
    assert AnthropicLoopConfig(model="m", system="s").compaction_preserving_summary is False


# -- 켜면 공식 지시 · 넉넉한 상한 -------------------------------------------------


@pytest.mark.asyncio
async def test_on_sends_the_official_instruction_and_the_configured_ceiling() -> None:
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        timeout_sec=120,
        compaction_preserving_summary=True,
        compaction_summary_max_tokens=3000,
    )
    h = harness(_reply("<summary>kept</summary>"), config=config)

    await h.loop._compact_after_prompt_too_long(_state(h))

    request = h.model.requests[0]
    assert request.system == COMPACTION_SUMMARY_INSTRUCTION
    assert request.limits.max_output_tokens == 3000
    assert request.limits.timeout_sec == 120


@pytest.mark.asyncio
async def test_on_stores_what_is_inside_the_summary_tags() -> None:
    config = AnthropicLoopConfig(
        model="claude-test", system="code", compaction_preserving_summary=True
    )
    h = harness(
        _reply("Here it is.\n<summary>\nuser asked: keep the API stable\n</summary>"),
        config=config,
    )

    after = await h.loop._compact_after_prompt_too_long(_state(h))

    assert after.summary == "user asked: keep the API stable"


# -- 공식 문구의 출처 ---------------------------------------------------------------


def test_the_instruction_is_the_one_in_the_spec_file() -> None:
    """§10.5: 문서가 갱신되면 스펙 파일을 먼저 고친다. 코드는 스펙 파일을 따른다.

    한 글자가 달라도 실패한다 -- 공식 문서가 측정한 효과는 그 문구에 붙어 있다.
    """
    spec = (
        Path(__file__).resolve().parents[3] / "docs/fable-5-1-multiagent-spec.md"
    ).read_text(encoding="utf-8")

    assert COMPACTION_SUMMARY_INSTRUCTION in spec


# -- 추출 정책: 위험은 형식이 아니라 불완전성이다 ---------------------------------


@pytest.mark.asyncio
async def test_a_summary_cut_at_its_ceiling_is_discarded() -> None:
    """잘린 요약은 뒤쪽 항목(미해결·구체값)을 잃은 채 매 턴 실린다 -- 받지 않는다."""
    config = AnthropicLoopConfig(
        model="claude-test", system="code", compaction_preserving_summary=True
    )
    h = harness(_reply("<summary>(1) problems ... (4) sta", "max_tokens"), config=config)
    state = _state(h)

    after = await h.loop._compact_after_prompt_too_long(state)

    assert after.summary == ""
    assert after.llm_compact_attempts == 1


def test_extraction_policy() -> None:
    from neos.coding.loop._durable.compaction import extract_preserved_summary

    # 닫는 태그 뒤에서 잘렸다 -- 요약은 온전하다.
    assert extract_preserved_summary("<summary>a</summary> tra", "max_tokens") == "a"
    # 태그 없이 끝까지 썼다 -- 형식을 어겼을 뿐 내용은 완전하다.
    assert extract_preserved_summary(" plain facts ", "end_turn") == "plain facts"
    # 태그 없이 잘렸다.
    assert extract_preserved_summary("plain fac", "max_tokens") is None
