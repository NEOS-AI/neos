# Deep Analysis — Skill Discovery 통합 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `deep_analysis` loop의 `dig` 워커가 스킬(arxiv·pubmed 등)을 LLM tool-calling으로 호출해 discovery 소스를 넓힌다.

**Architecture:** 스킬은 **discovery 전용**(URL 발견)으로만 들어가고 retrieval은 `fetch.py`가 독점한다(D6 확장). 워커의 LLM이 tool-calling으로 도구를 고르되, 후보군은 결정론적 셀렉터가 좁힌다. 모든 LLM 호출과 스킬 실행은 cassette로 녹화되어 replay 결정성과 D19 golden 게이트를 유지한다.

**Tech Stack:** Python 3.12, `anthropic` AsyncAnthropic SDK (수동 tool-calling 루프), pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-loop-architecture-consolidation-design.md` §3

## Global Constraints

- **P1 — 워커는 순수 함수:** 워커는 DB를 읽지도 쓰지도 않는다. `search_fn`/`fetch_fn` 주입 계약을 유지한다.
- **P3 — 무결성 자유도 제거:** 스킬은 discovery만. **retrieval은 `fetch.py` 독점.** 모든 클레임은 `DeterministicGrader`의 `fetch`된 blob 원문 대조를 통과해야 한다.
- **외부 프레임워크 금지:** LangChain/LangGraph 사용 금지. 표준 라이브러리 + `anthropic` SDK + `httpx`만.
- **cassette 결정성:** 모든 LLM 호출과 스킬 실행은 `cassette.remember(...)`를 통과해야 한다. **SDK의 `client.beta.messages.tool_runner`는 이 경로를 우회하므로 사용 금지** — 수동 루프로 구현한다.
- **기존 golden cassette 호환:** `LLMResponse`에 필드를 추가할 때 **반드시 기본값**을 준다. `LLMResponse(**recorded)`가 옛 레코드(신규 키 없음)로도 로드돼야 한다.
- **effort 게이팅:** 스킬은 `dig`(token_cap 12000)에서만. `scout`(2000)은 현행 `web_search` 단독 유지.
- **모델:** `deep_analysis`는 `claude-haiku-4-5-20251001`(scout) / `claude-opus-4-6`(dig·synth) / `claude-sonnet-4-6`(judge)를 쓴다. 이 모델들은 `temperature`를 허용한다(Opus 4.7+에서만 400). 모델 ID를 바꾸지 말 것.
- **테스트 관례:** `pytestmark = pytest.mark.no_db`, Fake 클라이언트를 `client=`로 주입.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `neos/workflow/deep_analysis/llm.py` (수정) | tool-calling 지원 추가 (`call_messages`). 기존 `call_llm`/`call_json` 시그니처 불변 |
| `neos/workflow/deep_analysis/skills_adapter.py` (신규) | `BaseSkill` → `[{url,title,snippet}]` 정규화. cassette `"skill"` 종류 |
| `neos/workflow/deep_analysis/skill_selector.py` (신규) | 후보 스킬 결정론적 선정 (allowlist + 가용성 + 상한) |
| `neos/workflow/deep_analysis/discovery.py` (신규) | 도구 스키마 생성 + tool-calling 루프 + 디스패치 |
| `neos/workflow/deep_analysis/worker.py` (수정) | `dig`에서 `_discover()` 사용, `scout`은 `_search()` 유지 |
| `neos/workflow/deep_analysis/service.py` (수정) | 셀렉터 주입 배선 |
| `neos/config/schema.py` (수정) | `discovery_skills`, `max_discovery_skills` 설정 |

---

### Task 1: LLMResponse가 content 블록과 stop_reason을 싣는다

**Files:**
- Modify: `neos/workflow/deep_analysis/llm.py:17-22`
- Test: `tests/workflow/deep_analysis/test_llm.py`

**Interfaces:**
- Consumes: 없음
- Produces: `LLMResponse(text, input_tokens, output_tokens, model, content=[], stop_reason="")` — `content`는 `[{"type": ..., ...}]` dict 리스트, `stop_reason`은 `"end_turn"|"tool_use"|"max_tokens"|...`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_llm.py` 끝에 추가:

```python
def test_llm_response_defaults_keep_old_cassette_records_loadable():
    # 기존 golden cassette 레코드에는 content/stop_reason 키가 없다.
    old_record = {
        "text": "hello",
        "input_tokens": 10,
        "output_tokens": 5,
        "model": "claude-opus-4-6",
    }
    response = LLMResponse(**old_record)
    assert response.content == []
    assert response.stop_reason == ""


def test_llm_response_carries_content_blocks_and_stop_reason():
    response = LLMResponse(
        text="",
        input_tokens=1,
        output_tokens=2,
        model="claude-opus-4-6",
        content=[{"type": "tool_use", "id": "toolu_1", "name": "search_arxiv", "input": {"query": "moe"}}],
        stop_reason="tool_use",
    )
    assert response.stop_reason == "tool_use"
    assert response.content[0]["name"] == "search_arxiv"
```

같은 파일 상단 import에 `LLMResponse`를 추가:

```python
from neos.workflow.deep_analysis.llm import (
    JSONParseError,
    LLMResponse,
    call_json,
    call_llm,
    parse_json,
)
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_llm.py::test_llm_response_carries_content_blocks_and_stop_reason -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'content'`

- [ ] **Step 3: 최소 구현**

`neos/workflow/deep_analysis/llm.py`에서 `dataclass` import에 `field`를 추가하고 `LLMResponse`를 교체:

```python
from dataclasses import asdict, dataclass, field
```

```python
@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    # 아래 두 필드는 기본값이 필수다: 기존 golden cassette 레코드에는 이 키가 없고,
    # 재생 시 LLMResponse(**recorded)로 복원되기 때문이다(D19 golden 게이트 유지).
    content: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_llm.py -v`
Expected: PASS (신규 2개 포함 전부)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/llm.py tests/workflow/deep_analysis/test_llm.py
git commit -m "feat(deep-analysis): carry content blocks and stop_reason on LLMResponse

Defaults keep existing golden cassette records loadable."
```

---

### Task 2: call_messages — tools를 실은 단일 턴 호출

**Files:**
- Modify: `neos/workflow/deep_analysis/llm.py:62-133`
- Test: `tests/workflow/deep_analysis/test_llm_tools.py` (신규)

**Interfaces:**
- Consumes: Task 1의 `LLMResponse(content=..., stop_reason=...)`
- Produces:
  - `async def call_messages(model: str, messages: list[dict], *, tools: list[dict] | None = None, max_tokens: int, temperature: float = 0.0, client=None, cassette=None) -> LLMResponse`
  - cassette 페이로드: `{"model", "messages", "tools", "max_tokens", "temperature"}` — `call_llm`의 `{"model","prompt",...}`와 키가 달라 기존 레코드와 충돌하지 않는다

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_llm_tools.py` 신규 작성:

```python
import pytest

from neos.workflow.deep_analysis.llm import call_messages


pytestmark = pytest.mark.no_db


class FakeBlock:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeToolAnthropic:
    """stop_reason='tool_use' 응답을 1회 낸 뒤 'end_turn'을 내는 Fake."""

    def __init__(self):
        self.messages = self
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)

        class Usage:
            input_tokens = 7
            output_tokens = 3

        if len(self.calls) == 1:
            content = [
                FakeBlock(type="text", text="검색하겠습니다"),
                FakeBlock(
                    type="tool_use",
                    id="toolu_1",
                    name="search_arxiv",
                    input={"query": "moe routing"},
                ),
            ]
            stop_reason = "tool_use"
        else:
            content = [FakeBlock(type="text", text="완료")]
            stop_reason = "end_turn"

        return FakeBlock(
            content=content,
            usage=Usage(),
            model="claude-opus-4-6",
            stop_reason=stop_reason,
        )


@pytest.mark.asyncio
async def test_call_messages_passes_tools_and_returns_tool_use_blocks():
    client = FakeToolAnthropic()
    tools = [
        {
            "name": "search_arxiv",
            "description": "Search arXiv",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]
    response = await call_messages(
        "claude-opus-4-6",
        [{"role": "user", "content": "MoE 라우팅 조사"}],
        tools=tools,
        max_tokens=1000,
        client=client,
    )

    assert client.calls[0]["tools"] == tools
    assert response.stop_reason == "tool_use"
    tool_uses = [b for b in response.content if b["type"] == "tool_use"]
    assert tool_uses[0]["name"] == "search_arxiv"
    assert tool_uses[0]["input"] == {"query": "moe routing"}
    assert tool_uses[0]["id"] == "toolu_1"
    assert response.text == "검색하겠습니다"
    assert response.input_tokens == 7


@pytest.mark.asyncio
async def test_call_messages_omits_tools_key_when_none():
    client = FakeToolAnthropic()
    await call_messages(
        "claude-opus-4-6",
        [{"role": "user", "content": "hi"}],
        max_tokens=100,
        client=client,
    )
    assert "tools" not in client.calls[0]
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_llm_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'call_messages'`

- [ ] **Step 3: 최소 구현**

`neos/workflow/deep_analysis/llm.py`의 `_call_provider`를 messages/tools 기반으로 교체한다. **OpenAI 경로는 tools를 지원하지 않으므로 명시적으로 거절한다** (deep_analysis 모델은 전부 Claude다):

```python
def _blocks_to_dicts(content) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for block in content:
        kind = getattr(block, "type", "")
        if kind == "text":
            blocks.append({"type": "text", "text": block.text})
        elif kind == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
    return blocks


async def _call_provider(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    client,
    tools: list[dict[str, Any]] | None = None,
) -> LLMResponse:
    if model.startswith("claude"):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        response = await client.messages.create(**kwargs)
        blocks = _blocks_to_dicts(response.content)
        output = "".join(b["text"] for b in blocks if b["type"] == "text")
        return LLMResponse(
            text=output,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=getattr(response, "model", model),
            content=blocks,
            stop_reason=getattr(response, "stop_reason", "") or "",
        )

    if tools:
        raise ValueError(f"tool calling is only supported on claude models, got {model}")

    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=messages,
    )
    text = response.choices[0].message.content or ""
    return LLMResponse(
        text=text,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        model=getattr(response, "model", model),
        content=[{"type": "text", "text": text}],
        stop_reason="end_turn",
    )
```

이어서 `call_messages`를 추가하고 `call_llm`을 그 위의 얇은 래퍼로 바꾼다 (기존 시그니처와 cassette 페이로드는 불변):

```python
async def call_messages(
    model: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int,
    temperature: float = 0.0,
    client=None,
    cassette=None,
) -> LLMResponse:
    async def produce() -> dict[str, Any]:
        resolved_client = client or _default_client(model)
        response = await _call_provider(
            model,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            client=resolved_client,
            tools=tools,
        )
        return asdict(response)

    if cassette is None:
        return LLMResponse(**(await produce()))

    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    recorded = await cassette.remember("llm", payload, produce)
    return LLMResponse(**recorded)


async def call_llm(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float = 0.0,
    client=None,
    cassette=None,
) -> LLMResponse:
    async def produce() -> dict[str, Any]:
        resolved_client = client or _default_client(model)
        response = await _call_provider(
            model,
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            client=resolved_client,
        )
        return asdict(response)

    if cassette is None:
        return LLMResponse(**(await produce()))

    # 페이로드 형태를 그대로 유지한다 — 기존 golden cassette 키가 바뀌면 안 된다.
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    recorded = await cassette.remember("llm", payload, produce)
    return LLMResponse(**recorded)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_llm_tools.py tests/workflow/deep_analysis/test_llm.py tests/workflow/deep_analysis/test_golden_gate.py -v`
Expected: PASS — 특히 `test_golden_gate.py`가 통과해야 한다(기존 cassette 키 불변 확인)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/llm.py tests/workflow/deep_analysis/test_llm_tools.py
git commit -m "feat(deep-analysis): add call_messages with tool-calling support

call_llm keeps its signature and cassette payload shape so existing
golden cassettes stay valid."
```

---

### Task 3: 스킬 discovery 어댑터

**Files:**
- Create: `neos/workflow/deep_analysis/skills_adapter.py`
- Test: `tests/workflow/deep_analysis/test_skills_adapter.py` (신규)

**Interfaces:**
- Consumes: `neos.skills.base.skill.BaseSkill` (`initialize()`/`execute(params)`/`cleanup()`), `neos.skills.base.result.SkillResult` (`.success`, `.data`)
- Produces:
  - `def normalize_discovery_items(data: Any) -> list[dict]` — `[{"url","title","snippet"}]`, URL 없는 항목은 제외
  - `async def skill_search(skill, query: str, k: int, *, cassette=None) -> list[dict]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_skills_adapter.py` 신규 작성:

```python
import pytest

from neos.workflow.deep_analysis.skills_adapter import (
    normalize_discovery_items,
    skill_search,
)


pytestmark = pytest.mark.no_db


class FakeSkillResult:
    def __init__(self, success, data):
        self.success = success
        self.data = data


class FakeSkill:
    def __init__(self, name="arxiv", result=None, init_ok=True):
        self.name = name
        self._result = result
        self._init_ok = init_ok
        self.cleaned_up = False
        self.executed_with = None

    async def initialize(self):
        return self._init_ok

    async def execute(self, params):
        self.executed_with = params
        return self._result

    async def cleanup(self):
        self.cleaned_up = True


def test_normalize_picks_url_title_snippet_from_varied_shapes():
    items = normalize_discovery_items(
        [
            {"url": "https://a.example/1", "title": "A", "summary": "sa"},
            {"link": "https://b.example/2", "name": "B", "abstract": "sb"},
            {"pdf_url": "https://c.example/3", "title": "C", "content": "sc"},
        ]
    )
    assert items == [
        {"url": "https://a.example/1", "title": "A", "snippet": "sa"},
        {"url": "https://b.example/2", "title": "B", "snippet": "sb"},
        {"url": "https://c.example/3", "title": "C", "snippet": "sc"},
    ]


def test_normalize_drops_items_without_url():
    # URL이 없으면 fetch.py가 blob을 만들 수 없고, DeterministicGrader가
    # E_SOURCE_DEAD로 거절한다. 검증 사슬에 못 들어가므로 여기서 버린다.
    items = normalize_discovery_items(
        [
            {"title": "no url", "summary": "x"},
            {"url": "", "title": "empty url"},
            {"url": "https://ok.example/1", "title": "ok"},
        ]
    )
    assert items == [{"url": "https://ok.example/1", "title": "ok", "snippet": ""}]


def test_normalize_handles_non_list_data():
    assert normalize_discovery_items(None) == []
    assert normalize_discovery_items({"url": "https://x.example"}) == []
    assert normalize_discovery_items("string") == []


@pytest.mark.asyncio
async def test_skill_search_runs_lifecycle_and_normalizes():
    skill = FakeSkill(
        result=FakeSkillResult(True, [{"url": "https://a.example/1", "title": "A", "summary": "s"}])
    )
    items = await skill_search(skill, "moe routing", 5)

    assert items == [{"url": "https://a.example/1", "title": "A", "snippet": "s"}]
    assert skill.executed_with == {"query": "moe routing", "action": "search", "max_results": 5}
    assert skill.cleaned_up is True


@pytest.mark.asyncio
async def test_skill_search_returns_empty_when_init_fails_and_still_cleans_up():
    skill = FakeSkill(init_ok=False)
    assert await skill_search(skill, "q", 3) == []


@pytest.mark.asyncio
async def test_skill_search_returns_empty_on_unsuccessful_result():
    skill = FakeSkill(result=FakeSkillResult(False, None))
    assert await skill_search(skill, "q", 3) == []
    assert skill.cleaned_up is True


@pytest.mark.asyncio
async def test_skill_search_swallows_skill_exception():
    class ExplodingSkill(FakeSkill):
        async def execute(self, params):
            raise RuntimeError("upstream 503")

    skill = ExplodingSkill()
    assert await skill_search(skill, "q", 3) == []
    assert skill.cleaned_up is True


@pytest.mark.asyncio
async def test_skill_search_records_through_cassette():
    class FakeCassette:
        def __init__(self):
            self.keys = []

        async def remember(self, kind, payload, produce):
            self.keys.append((kind, payload))
            return await produce()

    cassette = FakeCassette()
    skill = FakeSkill(
        result=FakeSkillResult(True, [{"url": "https://a.example/1", "title": "A"}])
    )
    await skill_search(skill, "q", 3, cassette=cassette)

    assert cassette.keys == [("skill", {"skill": "arxiv", "query": "q", "limit": 3})]
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_skills_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.deep_analysis.skills_adapter'`

- [ ] **Step 3: 최소 구현**

`neos/workflow/deep_analysis/skills_adapter.py` 신규 작성:

```python
"""Skills as discovery sources: (skill, query) -> [{url, title, snippet}].

D6 확장 — 탐색(discovery)만 담당한다. 검색(retrieval)은 fetch.py 독점이며,
여기서 반환한 URL은 반드시 fetch를 거쳐 원문 대조로 검증된다(P3).
URL을 주지 못하는 항목은 검증 사슬에 들어갈 수 없으므로 버린다.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_URL_KEYS = ("url", "link", "pdf_url", "html_url", "href")
_TITLE_KEYS = ("title", "name", "headline")
_SNIPPET_KEYS = ("snippet", "summary", "abstract", "content", "description", "text")


def _first_str(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def normalize_discovery_items(data: Any) -> list[dict[str, str]]:
    if not isinstance(data, list):
        return []

    items: list[dict[str, str]] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        url = _first_str(raw, _URL_KEYS)
        if not url:
            continue
        items.append(
            {
                "url": url,
                "title": _first_str(raw, _TITLE_KEYS),
                "snippet": _first_str(raw, _SNIPPET_KEYS),
            }
        )
    return items


async def skill_search(
    skill,
    query: str,
    k: int,
    *,
    cassette=None,
) -> list[dict[str, str]]:
    async def produce() -> list[dict[str, str]]:
        try:
            if not await skill.initialize():
                logger.warning("[deep_analysis] skill %s failed to initialize", skill.name)
                return []
            result = await skill.execute(
                {"query": query, "action": "search", "max_results": k}
            )
            if not getattr(result, "success", False):
                return []
            return normalize_discovery_items(getattr(result, "data", None))
        except Exception as exc:  # noqa: BLE001 — 스킬 장애가 워커를 죽이면 안 된다
            logger.warning("[deep_analysis] skill %s raised: %s", skill.name, exc)
            return []
        finally:
            try:
                await skill.cleanup()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[deep_analysis] skill %s cleanup failed: %s", skill.name, exc)

    if cassette is None:
        return await produce()
    return await cassette.remember(
        "skill",
        {"skill": skill.name, "query": query, "limit": k},
        produce,
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_skills_adapter.py -v`
Expected: PASS (8개)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/skills_adapter.py tests/workflow/deep_analysis/test_skills_adapter.py
git commit -m "feat(deep-analysis): add skill discovery adapter

Skills join as discovery sources only; items without a fetchable URL are
dropped because they cannot clear the deterministic grader."
```

---

### Task 4: 결정론적 스킬 셀렉터

**Files:**
- Create: `neos/workflow/deep_analysis/skill_selector.py`
- Modify: `neos/config/schema.py:614` 근방 (`DeepAnalysisConfig`)
- Test: `tests/workflow/deep_analysis/test_skill_selector.py` (신규)

**Interfaces:**
- Consumes: `neos.skills.manager.skill_registry.SkillRegistry` (`get_skill(name)`)
- Produces:
  - `class SkillSelector: def __init__(self, registry=None, *, allowlist: list[str] | None = None, cap: int | None = None)`
  - `def candidates(self, effort: Effort) -> list` — `dig`에서만 비어있지 않다. 최대 `cap`개.
- 설정: `DeepAnalysisConfig.discovery_skills: list[str]`, `DeepAnalysisConfig.max_discovery_skills: int = 3`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_skill_selector.py` 신규 작성:

```python
import pytest

from neos.workflow.deep_analysis.models import Effort
from neos.workflow.deep_analysis.skill_selector import SkillSelector


pytestmark = pytest.mark.no_db


class FakeSkill:
    def __init__(self, name):
        self.name = name


class FakeRegistry:
    def __init__(self, names):
        self._skills = {n: FakeSkill(n) for n in names}

    def get_skill(self, name):
        return self._skills.get(name)


def test_scout_gets_no_skills():
    # scout의 token_cap은 2000이라 도구 스키마 + 멀티턴이 들어가지 않는다.
    selector = SkillSelector(
        FakeRegistry(["arxiv", "pubmed"]), allowlist=["arxiv", "pubmed"], cap=3
    )
    assert selector.candidates(Effort.SCOUT) == []


def test_dig_gets_allowlisted_skills_in_allowlist_order():
    selector = SkillSelector(
        FakeRegistry(["arxiv", "pubmed", "openalex"]),
        allowlist=["pubmed", "arxiv"],
        cap=3,
    )
    names = [s.name for s in selector.candidates(Effort.DIG)]
    assert names == ["pubmed", "arxiv"]


def test_unregistered_allowlist_entries_are_skipped():
    selector = SkillSelector(
        FakeRegistry(["arxiv"]), allowlist=["arxiv", "nonexistent"], cap=3
    )
    assert [s.name for s in selector.candidates(Effort.DIG)] == ["arxiv"]


def test_cap_bounds_the_candidate_set():
    # dig의 token_cap(12000)을 도구 스키마가 잠식하지 않도록 상한을 둔다.
    selector = SkillSelector(
        FakeRegistry(["a", "b", "c", "d"]), allowlist=["a", "b", "c", "d"], cap=2
    )
    assert [s.name for s in selector.candidates(Effort.DIG)] == ["a", "b"]


def test_no_registry_yields_no_candidates():
    selector = SkillSelector(None, allowlist=["arxiv"], cap=3)
    assert selector.candidates(Effort.DIG) == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_skill_selector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.deep_analysis.skill_selector'`

- [ ] **Step 3: 최소 구현**

먼저 `neos/config/schema.py`의 `DeepAnalysisConfig`에 두 필드를 추가한다. `max_depth: int = 4` 줄 **바로 아래**에 삽입:

```python
    # discovery 소스로 쓸 스킬 allowlist. URL을 반환해 fetch/원문대조가 가능한
    # 것만 넣는다 — URL 없는 스킬 결과는 E_SOURCE_DEAD로 거절된다.
    discovery_skills: list[str] = Field(
        default_factory=lambda: [
            "arxiv",
            "pubmed",
            "openalex",
            "semantic_scholar",
            "google_scholar",
            "sec_edgar",
            "news_api",
            "wikipedia",
        ]
    )
    # dig의 token_cap(12000)을 도구 스키마가 잠식하지 않도록 하는 상한.
    max_discovery_skills: int = 3
```

`neos/workflow/deep_analysis/skill_selector.py` 신규 작성:

```python
"""Deterministic candidate selection for worker discovery tools.

셀렉터는 '무엇을 제공할지'만 정한다(결정론적). '무엇을 쓸지'는 워커의 LLM이
tool-calling으로 고른다 — 도구 선택은 무결성 레버가 아니라 품질 레버이므로
DeterministicGrader(출처 무관)가 그 자유도를 안전하게 만든다.
"""

from __future__ import annotations

from neos.config.settings import settings

from .models import Effort


class SkillSelector:
    def __init__(self, registry=None, *, allowlist: list[str] | None = None, cap: int | None = None) -> None:
        config = settings.config.deep_analysis
        self.registry = registry
        self.allowlist = allowlist if allowlist is not None else list(config.discovery_skills)
        self.cap = cap if cap is not None else config.max_discovery_skills

    def candidates(self, effort: Effort) -> list:
        if effort is not Effort.DIG or self.registry is None:
            return []

        selected = []
        for name in self.allowlist:
            if len(selected) >= self.cap:
                break
            skill = self.registry.get_skill(name)
            if skill is not None:
                selected.append(skill)
        return selected
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_skill_selector.py tests/workflow/deep_analysis/test_config_defaults.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/skill_selector.py neos/config/schema.py tests/workflow/deep_analysis/test_skill_selector.py
git commit -m "feat(deep-analysis): add deterministic discovery skill selector

Selector decides what is offered; the worker LLM decides what is used."
```

---

### Task 5: 도구 스키마 + tool-calling discovery 루프

**Files:**
- Create: `neos/workflow/deep_analysis/discovery.py`
- Test: `tests/workflow/deep_analysis/test_discovery.py` (신규)

**Interfaces:**
- Consumes: Task 2의 `call_messages`, Task 3의 `skill_search`
- Produces:
  - `def build_tool_defs(skills: list) -> list[dict]` — `search_web` + 스킬별 `search_<name>`
  - `async def run_discovery(brief, skills, *, search_fn, model, max_tokens, limit, client=None, cassette=None, max_turns=3) -> tuple[list[dict], int]` — `([{url,title,snippet}...], tokens_spent)`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_discovery.py` 신규 작성:

```python
import pytest

from neos.workflow.deep_analysis.discovery import build_tool_defs, run_discovery


pytestmark = pytest.mark.no_db


class FakeSkill:
    def __init__(self, name, items=None):
        self.name = name
        self.description = f"{name} search"
        self.items = items or []
        self.cleaned_up = False

    async def initialize(self):
        return True

    async def execute(self, params):
        class Result:
            success = True
            data = self.items

        return Result()

    async def cleanup(self):
        self.cleaned_up = True


class FakeBlock:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ScriptedAnthropic:
    """turns: 각 턴이 (content_blocks, stop_reason)."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.messages = self
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        content, stop_reason = self._turns.pop(0)

        class Usage:
            input_tokens = 10
            output_tokens = 4

        return FakeBlock(
            content=content,
            usage=Usage(),
            model="claude-opus-4-6",
            stop_reason=stop_reason,
        )


async def fake_search_fn(query, k):
    return [{"url": "https://web.example/1", "title": "web", "snippet": "w"}]


def test_build_tool_defs_always_includes_web_search():
    defs = build_tool_defs([])
    assert [d["name"] for d in defs] == ["search_web"]
    assert defs[0]["input_schema"]["required"] == ["query"]


def test_build_tool_defs_adds_one_tool_per_skill():
    defs = build_tool_defs([FakeSkill("arxiv"), FakeSkill("pubmed")])
    assert [d["name"] for d in defs] == ["search_web", "search_arxiv", "search_pubmed"]


@pytest.mark.asyncio
async def test_run_discovery_executes_tool_calls_and_collects_results():
    skill = FakeSkill("arxiv", [{"url": "https://arxiv.example/1", "title": "paper", "summary": "s"}])
    client = ScriptedAnthropic(
        [
            (
                [
                    FakeBlock(
                        type="tool_use", id="t1", name="search_arxiv", input={"query": "moe"}
                    )
                ],
                "tool_use",
            ),
            ([FakeBlock(type="text", text="done")], "end_turn"),
        ]
    )

    items, tokens = await run_discovery(
        "MoE 라우팅 조사",
        [skill],
        search_fn=fake_search_fn,
        model="claude-opus-4-6",
        max_tokens=2000,
        limit=5,
        client=client,
    )

    assert items == [{"url": "https://arxiv.example/1", "title": "paper", "snippet": "s"}]
    assert tokens == 28  # 2턴 x (10 + 4)


@pytest.mark.asyncio
async def test_run_discovery_records_web_search_through_cassette():
    # search_fn을 직접 부르면 이 경로만 녹화에서 빠져 replay가 깨진다.
    # 키 형태는 Worker._search와 같아야 한다.
    class FakeCassette:
        def __init__(self):
            self.keys = []

        async def remember(self, kind, payload, produce):
            self.keys.append((kind, payload))
            return await produce()

    cassette = FakeCassette()
    client = ScriptedAnthropic(
        [
            ([FakeBlock(type="tool_use", id="t1", name="search_web", input={"query": "a"})], "tool_use"),
            ([FakeBlock(type="text", text="done")], "end_turn"),
        ]
    )
    await run_discovery(
        "q", [], search_fn=fake_search_fn, model="claude-opus-4-6",
        max_tokens=2000, limit=5, client=client, cassette=cassette,
    )

    assert ("search", {"query": "a", "limit": 5}) in cassette.keys


@pytest.mark.asyncio
async def test_run_discovery_returns_all_tool_results_in_one_user_message():
    # 병렬 도구 호출 결과를 여러 user 메시지로 쪼개면 모델이 병렬 호출을 멈춘다.
    client = ScriptedAnthropic(
        [
            (
                [
                    FakeBlock(type="tool_use", id="t1", name="search_web", input={"query": "a"}),
                    FakeBlock(type="tool_use", id="t2", name="search_arxiv", input={"query": "b"}),
                ],
                "tool_use",
            ),
            ([FakeBlock(type="text", text="done")], "end_turn"),
        ]
    )
    await run_discovery(
        "q",
        [FakeSkill("arxiv", [{"url": "https://arxiv.example/1", "title": "p"}])],
        search_fn=fake_search_fn,
        model="claude-opus-4-6",
        max_tokens=2000,
        limit=5,
        client=client,
    )

    second_turn_messages = client.calls[1]["messages"]
    tool_result_messages = [
        m for m in second_turn_messages
        if m["role"] == "user" and isinstance(m["content"], list)
        and any(b.get("type") == "tool_result" for b in m["content"])
    ]
    assert len(tool_result_messages) == 1
    assert len(tool_result_messages[0]["content"]) == 2


@pytest.mark.asyncio
async def test_run_discovery_dedups_urls_across_tools():
    skill = FakeSkill("arxiv", [{"url": "https://web.example/1", "title": "dup"}])
    client = ScriptedAnthropic(
        [
            (
                [
                    FakeBlock(type="tool_use", id="t1", name="search_web", input={"query": "a"}),
                    FakeBlock(type="tool_use", id="t2", name="search_arxiv", input={"query": "b"}),
                ],
                "tool_use",
            ),
            ([FakeBlock(type="text", text="done")], "end_turn"),
        ]
    )
    items, _ = await run_discovery(
        "q", [skill], search_fn=fake_search_fn, model="claude-opus-4-6",
        max_tokens=2000, limit=5, client=client,
    )
    assert [i["url"] for i in items] == ["https://web.example/1"]


@pytest.mark.asyncio
async def test_run_discovery_reports_unknown_tool_as_error_result():
    client = ScriptedAnthropic(
        [
            ([FakeBlock(type="tool_use", id="t1", name="search_bogus", input={"query": "a"})], "tool_use"),
            ([FakeBlock(type="text", text="done")], "end_turn"),
        ]
    )
    items, _ = await run_discovery(
        "q", [], search_fn=fake_search_fn, model="claude-opus-4-6",
        max_tokens=2000, limit=5, client=client,
    )
    assert items == []
    results = client.calls[1]["messages"][-1]["content"]
    assert results[0]["is_error"] is True


@pytest.mark.asyncio
async def test_run_discovery_stops_at_max_turns():
    always_tool_use = (
        [FakeBlock(type="tool_use", id="t1", name="search_web", input={"query": "a"})],
        "tool_use",
    )
    client = ScriptedAnthropic([always_tool_use] * 10)
    items, _ = await run_discovery(
        "q", [], search_fn=fake_search_fn, model="claude-opus-4-6",
        max_tokens=2000, limit=5, client=client, max_turns=2,
    )
    assert len(client.calls) == 2
    assert [i["url"] for i in items] == ["https://web.example/1"]
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_discovery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.deep_analysis.discovery'`

- [ ] **Step 3: 최소 구현**

`neos/workflow/deep_analysis/discovery.py` 신규 작성:

```python
"""Worker discovery phase: LLM tool-calling over web_search + selected skills.

수동 tool-calling 루프다. SDK의 client.beta.messages.tool_runner를 쓰지 않는 이유:
tool_runner는 llm.py의 cassette 래핑을 우회해 record/replay 결정성과 D19 golden
게이트를 깨뜨린다.

이 단계는 URL을 모으기만 한다. 수집된 URL은 워커가 fetch.py로 retrieval하고,
DeterministicGrader가 원문 대조로 검증한다(P3).
"""

from __future__ import annotations

import json
from typing import Any

from .llm import call_messages
from .skills_adapter import skill_search

_WEB_TOOL = "search_web"

_DISCOVERY_PROMPT = """You are gathering candidate sources for a research question.

Question:
{brief}

Use the available search tools to find relevant sources. Prefer authoritative,
primary sources. You may call several tools in one turn. When you have enough
candidate sources, stop calling tools and reply with a single word: done.

Do not answer the question itself — only gather sources."""


def _tool_schema(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query.",
                }
            },
            "required": ["query"],
        },
    }


def build_tool_defs(skills: list) -> list[dict[str, Any]]:
    defs: list[dict[str, Any]] = [
        {"name": _WEB_TOOL, **_tool_schema("General web search. Use for broad or non-academic sources.")}
    ]
    for skill in skills:
        defs.append(
            {
                "name": f"search_{skill.name}",
                **_tool_schema(
                    f"Search {skill.name}. {getattr(skill, 'description', '')} "
                    f"Call this when the question is within this source's domain."
                ),
            }
        )
    return defs


async def _dispatch(name, query, limit, skills_by_tool, search_fn, cassette):
    if name == _WEB_TOOL:
        # Worker._search와 동일한 cassette 키 형태를 쓴다 — search_fn을 직접
        # 부르면 이 경로만 녹화에서 빠져 replay 결정성에 구멍이 난다.
        async def produce():
            return await search_fn(query, k=limit)

        if cassette is None:
            return await produce()
        return await cassette.remember(
            "search", {"query": query, "limit": limit}, produce
        )

    skill = skills_by_tool.get(name)
    if skill is None:
        return None
    return await skill_search(skill, query, limit, cassette=cassette)


async def run_discovery(
    brief: str,
    skills: list,
    *,
    search_fn,
    model: str,
    max_tokens: int,
    limit: int,
    client=None,
    cassette=None,
    max_turns: int = 3,
) -> tuple[list[dict[str, str]], int]:
    tools = build_tool_defs(skills)
    skills_by_tool = {f"search_{s.name}": s for s in skills}
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _DISCOVERY_PROMPT.format(brief=brief)}
    ]

    collected: dict[str, dict[str, str]] = {}
    tokens = 0

    for _turn in range(max_turns):
        response = await call_messages(
            model,
            messages,
            tools=tools,
            max_tokens=max_tokens,
            client=client,
            cassette=cassette,
        )
        tokens += response.input_tokens + response.output_tokens

        tool_uses = [b for b in response.content if b["type"] == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            break

        messages.append({"role": "assistant", "content": response.content})

        # 모든 tool_result는 단일 user 메시지에 담아야 한다 — 쪼개면 모델이
        # 병렬 도구 호출을 그만두도록 학습된다.
        tool_results: list[dict[str, Any]] = []
        for block in tool_uses:
            query = str(block["input"].get("query", ""))
            items = await _dispatch(
                block["name"], query, limit, skills_by_tool, search_fn, cassette
            )
            if items is None:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": f"unknown tool: {block['name']}",
                        "is_error": True,
                    }
                )
                continue
            for item in items:
                collected.setdefault(item["url"], item)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": json.dumps(
                        [{"url": i["url"], "title": i["title"]} for i in items],
                        ensure_ascii=False,
                    ),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return list(collected.values()), tokens
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_discovery.py -v`
Expected: PASS (8개)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/discovery.py tests/workflow/deep_analysis/test_discovery.py
git commit -m "feat(deep-analysis): add tool-calling discovery loop

Manual loop rather than the SDK tool_runner, which would bypass the
cassette wrapping and break replay determinism."
```

---

### Task 6: 워커가 dig에서 discovery를 쓴다

**Files:**
- Modify: `neos/workflow/deep_analysis/worker.py:24-42` (`__init__`), `:97-100` (검색 호출부)
- Test: `tests/workflow/deep_analysis/test_worker_discovery.py` (신규)

**Interfaces:**
- Consumes: Task 5의 `run_discovery`, Task 4의 `SkillSelector`
- Produces: `Worker(search_fn, *, skill_selector=None, ...)` — `skill_selector=None`이면 현행 동작 그대로

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_worker_discovery.py` 신규 작성:

```python
import pytest

from neos.workflow.deep_analysis.models import Effort
from neos.workflow.deep_analysis.worker import Worker


pytestmark = pytest.mark.no_db


class FakeSelector:
    def __init__(self, skills):
        self._skills = skills
        self.asked_efforts = []

    def candidates(self, effort):
        self.asked_efforts.append(effort)
        return self._skills


async def fake_search_fn(query, k):
    return [{"url": "https://web.example/1", "title": "w", "snippet": "s"}]


@pytest.mark.asyncio
async def test_worker_without_selector_uses_plain_search(monkeypatch):
    called = {"discovery": False}

    async def spy_run_discovery(*args, **kwargs):
        called["discovery"] = True
        return [], 0

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.worker.run_discovery", spy_run_discovery
    )
    worker = Worker(fake_search_fn)
    urls = await worker._collect_candidates("brief", Effort.DIG, 5)

    assert called["discovery"] is False
    assert [u["url"] for u in urls] == ["https://web.example/1"]


@pytest.mark.asyncio
async def test_worker_scout_never_uses_discovery(monkeypatch):
    # scout은 token_cap 2000이라 도구 스키마 + 멀티턴이 안 들어간다.
    async def boom(*args, **kwargs):
        raise AssertionError("discovery must not run at scout effort")

    monkeypatch.setattr("neos.workflow.deep_analysis.worker.run_discovery", boom)
    selector = FakeSelector([])
    worker = Worker(fake_search_fn, skill_selector=selector)
    urls = await worker._collect_candidates("brief", Effort.SCOUT, 5)

    assert [u["url"] for u in urls] == ["https://web.example/1"]


@pytest.mark.asyncio
async def test_worker_dig_with_candidates_uses_discovery_and_counts_tokens(monkeypatch):
    async def fake_run_discovery(*args, **kwargs):
        return [{"url": "https://arxiv.example/1", "title": "p", "snippet": "x"}], 42

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.worker.run_discovery", fake_run_discovery
    )

    class FakeSkill:
        name = "arxiv"

    worker = Worker(fake_search_fn, skill_selector=FakeSelector([FakeSkill()]))
    urls = await worker._collect_candidates("brief", Effort.DIG, 5)

    assert [u["url"] for u in urls] == ["https://arxiv.example/1"]
    assert worker._tokens == 42


@pytest.mark.asyncio
async def test_worker_dig_falls_back_to_plain_search_when_no_candidates(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("discovery must not run without candidates")

    monkeypatch.setattr("neos.workflow.deep_analysis.worker.run_discovery", boom)
    worker = Worker(fake_search_fn, skill_selector=FakeSelector([]))
    urls = await worker._collect_candidates("brief", Effort.DIG, 5)

    assert [u["url"] for u in urls] == ["https://web.example/1"]
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_worker_discovery.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'skill_selector'`

- [ ] **Step 3: 최소 구현**

`neos/workflow/deep_analysis/worker.py` 상단 import에 추가:

```python
from .discovery import run_discovery
```

`Worker.__init__`에 `skill_selector` 파라미터를 추가 (기존 파라미터는 그대로):

```python
    def __init__(
        self,
        search_fn: Callable,
        *,
        fetch_fn=fetch_url,
        llm_client=None,
        http_client=None,
        cassette=None,
        skill_selector=None,
    ) -> None:
        self.search_fn = search_fn
        self.fetch_fn = fetch_fn
        self.llm_client = llm_client
        self.http_client = http_client
        self.cassette = cassette
        self.skill_selector = skill_selector
        self._claims: list[ProposedClaim] = []
        self._blobs: list[ProposedBlob] = []
        self._tokens = 0
        self._model = ""
```

`_search` 아래에 `_collect_candidates`를 추가:

```python
    async def _collect_candidates(
        self, brief: str, effort: Effort, limit: int
    ) -> list[dict]:
        """Discovery 단계 — URL 후보만 모은다. retrieval은 fetch_fn 독점(P3)."""
        if self.skill_selector is None:
            return await self._search(brief, limit)

        skills = self.skill_selector.candidates(effort)
        if not skills:
            return await self._search(brief, limit)

        config = settings.config.deep_analysis
        effort_config = config.effort[effort.value]
        items, tokens = await run_discovery(
            brief,
            skills,
            search_fn=self.search_fn,
            model=self._model,
            max_tokens=min(effort_config.token_cap, config.worker_max_output_tokens),
            limit=limit,
            client=self.llm_client,
            cassette=self.cassette,
        )
        self._tokens += tokens
        if not items:
            # 스킬이 전부 실패했으면 web_search 단독 경로로 degrade한다.
            return await self._search(brief, limit)
        return items
```

`investigate` 안의 검색 호출부를 교체한다. **기존:**

```python
        search_results = await self._search(
            brief,
            config.search_result_limit,
        )
```

**변경 후:**

```python
        search_results = await self._collect_candidates(
            brief,
            effort,
            config.search_result_limit,
        )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_worker_discovery.py tests/workflow/deep_analysis/test_worker.py -v`
Expected: PASS — 기존 `test_worker.py`도 전부 통과해야 한다 (`skill_selector=None` 기본값 → 현행 동작)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/worker.py tests/workflow/deep_analysis/test_worker_discovery.py
git commit -m "feat(deep-analysis): use skill discovery at dig effort

Worker keeps its search_fn contract (P1); scout stays on plain web search
because its 2000-token cap cannot fit tool schemas."
```

---

### Task 7: service 배선 + 통합 검증

**Files:**
- Modify: `neos/workflow/deep_analysis/service.py:44-90` (`build_orchestrator`)
- Test: `tests/workflow/deep_analysis/test_service_discovery.py` (신규)

**Interfaces:**
- Consumes: Task 4의 `SkillSelector`, Task 6의 `Worker(skill_selector=...)`
- Produces: `build_orchestrator(..., skill_registry=None)` — `None`이면 스킬 없이 현행 동작

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_service_discovery.py` 신규 작성:

```python
import pytest

from neos.workflow.deep_analysis.models import Effort
from neos.workflow.deep_analysis.skill_selector import SkillSelector


pytestmark = pytest.mark.no_db


class FakeSkill:
    def __init__(self, name):
        self.name = name


class FakeRegistry:
    def __init__(self, names):
        self._skills = {n: FakeSkill(n) for n in names}

    def get_skill(self, name):
        return self._skills.get(name)


def test_selector_reads_allowlist_and_cap_from_settings():
    # 기본 설정만으로 구성해도 dig에서 후보가 나온다.
    selector = SkillSelector(FakeRegistry(["arxiv", "pubmed", "openalex", "wikipedia"]))
    names = [s.name for s in selector.candidates(Effort.DIG)]

    assert len(names) <= 3  # max_discovery_skills 기본값
    assert "arxiv" in names


def test_selector_without_registry_is_inert():
    selector = SkillSelector(None)
    assert selector.candidates(Effort.DIG) == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_service_discovery.py -v`
Expected: PASS 또는 FAIL — Task 4가 이미 `SkillSelector`를 제공하므로 통과할 수 있다. 통과하면 Step 3의 배선만 하고 넘어간다.

- [ ] **Step 3: service 배선**

`neos/workflow/deep_analysis/service.py` 상단 import에 추가:

```python
from .skill_selector import SkillSelector
```

`build_orchestrator` 시그니처에 `skill_registry=None`을 추가:

```python
async def build_orchestrator(
    session,
    run_id: str,
    *,
    profile: str = "dev",
    cassette=None,
    event_sink=None,
    checkpoint=None,
    search_fn=web_search,
    fetch_fn=None,
    llm_client=None,
    http_client=None,
    skill_registry=None,
) -> Orchestrator:
```

`worker_factory`를 교체:

```python
    skill_selector = (
        SkillSelector(skill_registry) if skill_registry is not None else None
    )

    def worker_factory():
        options = {
            "llm_client": llm_client,
            "http_client": http_client,
            "cassette": cassette,
            "skill_selector": skill_selector,
        }
        if fetch_fn is not None:
            options["fetch_fn"] = fetch_fn
        return Worker(search_fn, **options)
```

- [ ] **Step 4: 전체 회귀 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/ -v`
Expected: PASS — 전부. 특히:
- `test_golden_gate.py` (D19 게이트 — cassette 키 불변)
- `test_golden_integration.py`
- `test_worker.py` (기본값 경로 무회귀)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/service.py tests/workflow/deep_analysis/test_service_discovery.py
git commit -m "feat(deep-analysis): wire skill registry into orchestrator build

skill_registry=None keeps the existing no-skill behaviour."
```

---

## 수용 기준 대조 (스펙 §3.7)

| AC | 검증 |
|---|---|
| AC1. `search_fn` 계약 불변 (P1) | Task 6 — `Worker(search_fn, ...)` 첫 인자 그대로; `test_worker.py` 무회귀 |
| AC2. dig 워커가 스킬을 tool-call | Task 5·6 — `test_run_discovery_executes_tool_calls_and_collects_results` |
| AC3. scout 도구 집합 현행 유지 | Task 6 — `test_worker_scout_never_uses_discovery` |
| AC4. URL 미반환 스킬 제외 | Task 3 — `test_normalize_drops_items_without_url` (런타임 강제) + Task 4 allowlist (사전 큐레이션) |
| AC5. cassette `"skill"` 결정적 재생 | Task 3 — `test_skill_search_records_through_cassette` |
| AC6. golden 게이트 통과 | Task 7 Step 4 — `test_golden_gate.py` |
| AC7. 스킬 실패 시 graceful degradation | Task 3 — `test_skill_search_swallows_skill_exception`; Task 6 — `test_worker_dig_falls_back_to_plain_search_when_no_candidates` |
| AC8. 검증 사슬 무결성 | 구조적 — discovery는 URL만 반환하고 `investigate`가 `self.fetch_fn`으로 retrieval(불변). `DeterministicGrader` 경로 무수정 |

## 남은 실측 항목

- `max_discovery_skills` 기본 3이 dig의 12,000 토큰 예산을 압박하는지 — 실측 후 조정 (스펙 K1)
- 스킬 정규화 실패를 이벤트로 남길지 — P4 고려. 구현 중 판단해 `DECISIONS.md`에 기록 (스펙 §9)
