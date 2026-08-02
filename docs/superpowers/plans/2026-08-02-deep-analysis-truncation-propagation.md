# Deep Analysis truncation 신호 전파 구현 플랜 (A2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM 응답이 잘렸다는 사실(`stop_reason == "max_tokens"`)을 `call_json` 호출부까지 전파해, 세 개의 fail-open 지점이 "잘린 판정"과 "쓰레기 응답"을 구분해 처리하게 한다.

**Architecture:** `_budgeted_dispatch`가 이미 아는 두 값(응답의 `stop_reason`, 예약의 `max_output_tokens`)을 `LLMResponse`에 실어 `call_json`까지 올린다. `call_json`은 파싱 실패를 세 원인으로 나눠 상한에 걸린 경우만 확장 재시도하고, 실패하면 `JSONParseError`의 서브클래스인 `TruncatedResponseError`를 올린다. 서브클래스이므로 예외를 전파하던 5개 호출부는 변경 없이 확장 재시도 이득만 받고, fail-open 하던 2개만 명시적으로 새 동작을 택한다.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio, Pydantic (`StrictConfigModel`), 기존 deep_analysis 카세트/예산 인프라.

**설계 문서:** `docs/superpowers/specs/2026-08-02-deep-analysis-truncation-propagation-design.md`

## Global Constraints

- **매직넘버 금지** — 모든 상수는 `neos/config/schema.py`의 설정으로 들어간다.
- **테스트에서 실 LLM/네트워크 금지** — 카세트 재생 또는 fake 클라이언트 주입만 쓴다.
- **`deep_analysis_events`는 append-only (D8 §11.3)** — 새 kind를 추가할 뿐 기존 kind의 페이로드를 바꾸지 않는다.
- **이벤트 페이로드에 응답 텍스트 금지** — 카운트와 식별자만 싣는다.
- **P2 단일 작성자** — grader와 worker는 ledger에 쓰지 않는다. 이벤트는 `TokenBudget` 또는 오케스트레이터가 쓴다.
- **judge ≠ worker** — 이 플랜은 모델을 바꾸지 않는다.
- **골든 카세트 하위호환** — `LLMResponse`에 추가하는 필드는 반드시 기본값을 갖는다. 기존 레코드에 키가 없고 `LLMResponse(**recorded)`로 복원되기 때문이다 (D19 골든 게이트).
- **테스트 명령:** `HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest` — bare `pytest`는 asyncio 마커 수집에 실패한다.
- **커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다.**

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `neos/workflow/deep_analysis/llm.py` | truncation 감지·분류·확장 재시도, `TruncatedResponseError` 정의 | 수정 |
| `neos/workflow/deep_analysis/token_budget.py` | `truncation_handled` 이벤트 작성 | 수정 |
| `neos/config/schema.py` | `truncation_retry_multiplier` 설정 | 수정 |
| `neos/workflow/deep_analysis/graders/agentic.py` | judge 종단 — 반려 | 수정 |
| `neos/workflow/deep_analysis/graders/report.py` | report 종단 — 결정론적 판정 복귀 | 수정 |
| `neos/workflow/deep_analysis/worker.py` | entailment를 `call_json`으로 이전, 스킵 플래그 | 수정 |
| `neos/workflow/deep_analysis/models.py` | `WorkerResult.entailment_skipped` 플래그 | 수정 |
| `neos/workflow/deep_analysis/orchestrator.py` | `entailment_filter_skipped` 이벤트 작성 | 수정 |
| `neos/workflow/deep_analysis/DECISIONS.md` | D24 기록 | 수정 |
| `tests/workflow/deep_analysis/test_llm.py` | Task 1–3 테스트 | 수정 |
| `tests/workflow/deep_analysis/test_agentic_grader.py` | Task 4 테스트 | 수정 |
| `tests/workflow/deep_analysis/test_report_grader.py` | Task 5 테스트 | 수정 또는 생성 |
| `tests/workflow/deep_analysis/test_worker_entailment.py` | Task 6 테스트 (기존 2건 수정 포함) | 수정 |
| `tests/workflow/deep_analysis/test_orchestrator_discard_events.py` | Task 7 테스트 | 수정 |

Task 1–3이 기반(신호 + 재시도 + 이벤트)을 만들고, Task 4–7이 각 종단을 붙인다. Task 8은 문서와 전체 회귀다.

---

## Task 1: `LLMResponse`에 허용 상한을 싣는다

`call_json`이 "상한에 걸림"과 "예산에 걸림"을 구분하려면 실제로 허용된 출력 상한을 알아야 한다. 이 값은 `_budgeted_dispatch`의 `reservation.max_output_tokens`에만 있다.

**Files:**
- Modify: `neos/workflow/deep_analysis/llm.py:24-34` (`LLMResponse`), `llm.py:182-221` (`_budgeted_dispatch`)
- Test: `tests/workflow/deep_analysis/test_llm.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: `LLMResponse.granted_max_output_tokens: int` — 이 호출에 실제로 허용된 출력 상한. `0`은 "미상"(레거시 카세트 레코드)을 뜻하며, `_budgeted_dispatch`를 거친 응답에서는 항상 양수다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_llm.py` 끝에 추가한다. 파일 상단 import에 `TokenBudget`, `token_budget_scope`가 이미 있다(`test_llm.py:15`).

```python
@pytest.mark.asyncio
async def test_granted_max_output_tokens_reports_the_requested_ceiling():
    """예산이 넉넉하면 허용 상한 == 요청 상한이다."""
    budget = TokenBudget(100_000)

    with token_budget_scope(budget):
        response = await call_llm(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=500,
            client=FakeAnthropic(["answer"]),
        )

    assert response.granted_max_output_tokens == 500


@pytest.mark.asyncio
async def test_granted_max_output_tokens_reports_the_budget_clamp():
    """예산이 모자라면 허용 상한이 요청 상한보다 작다 — 이 차이가 재시도 판정의 근거다."""
    # conservative_input_bound가 요청 크기에 64를 더하므로 정확한 값 대신
    # "요청보다 작고 양수"만 단언한다.
    budget = TokenBudget(400)

    with token_budget_scope(budget):
        response = await call_llm(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=5000,
            client=FakeAnthropic(["answer"]),
        )

    assert 0 < response.granted_max_output_tokens < 5000


@pytest.mark.asyncio
async def test_granted_max_output_tokens_without_a_budget_is_the_ceiling():
    """예산 스코프 밖에서는 깎을 것이 없으므로 항상 상한 그대로다."""
    response = await call_llm(
        "claude-haiku-4-5-20251001",
        "prompt",
        max_tokens=300,
        client=FakeAnthropic(["answer"]),
    )

    assert response.granted_max_output_tokens == 300
```

- [ ] **Step 2: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_llm.py -k granted_max_output_tokens -q
```

Expected: FAIL — `AttributeError: 'LLMResponse' object has no attribute 'granted_max_output_tokens'`

- [ ] **Step 3: 필드를 추가한다**

`llm.py:24-34`의 `LLMResponse`에 마지막 필드로 추가한다. 기존 주석 바로 아래다.

```python
@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    # 기본값이 필수다: 기존 golden cassette 레코드에는 이 키들이 없고,
    # 재생 시 LLMResponse(**recorded)로 복원된다(D19 golden 게이트 유지).
    content: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    # 이 호출에 실제로 허용된 출력 상한. 0은 "미상"(레거시 레코드)이다.
    # _budgeted_dispatch가 카세트 계층 이후에 채운다 — 허용 상한은 기록 시점이
    # 아니라 이번 run의 예산 속성이므로, 재생 시에도 덮어써야 한다.
    granted_max_output_tokens: int = 0
```

- [ ] **Step 4: `_budgeted_dispatch`가 값을 채우게 한다**

`llm.py:182-221`을 교체한다. `dataclasses`에서 `replace`를 import해야 한다 — 파일 상단 `from dataclasses import asdict, dataclass, field`를 `from dataclasses import asdict, dataclass, field, replace`로 바꾼다.

```python
async def _budgeted_dispatch(
    *,
    model: str,
    request: dict[str, Any],
    max_tokens: int,
    stage: str,
    invoke: Callable[[int, _DispatchState], Awaitable[LLMResponse]],
) -> LLMResponse:
    budget = active_token_budget()
    if budget is None:
        response = await invoke(max_tokens, _DispatchState())
        return replace(response, granted_max_output_tokens=max_tokens)

    reservation = await budget.reserve(
        request,
        max_tokens,
        stage=stage,
        model=model,
    )
    dispatch = _DispatchState()
    try:
        response = await invoke(reservation.max_output_tokens, dispatch)
    except BaseException:
        if dispatch.started:
            await budget.abandon(reservation)
        else:
            await budget.release(reservation)
        raise

    await budget.settle(
        reservation,
        response.input_tokens + response.output_tokens,
    )
    if response.stop_reason == "max_tokens":
        await budget.record_truncation(
            stage=reservation.stage,
            model=reservation.model,
            max_output_tokens=reservation.max_output_tokens,
            output_tokens=response.output_tokens,
        )
    return replace(
        response,
        granted_max_output_tokens=reservation.max_output_tokens,
    )
```

- [ ] **Step 5: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_llm.py -q
```

Expected: PASS (신규 3건 포함 전량)

- [ ] **Step 6: 골든 게이트 회귀를 확인한다**

레거시 카세트 레코드에 새 키가 없어도 복원되는지가 이 태스크의 핵심 위험이다.

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_golden_gate.py \
  tests/workflow/deep_analysis/test_golden_integration.py \
  tests/workflow/deep_analysis/test_cassette.py -q
```

Expected: PASS

- [ ] **Step 7: 커밋한다**

```bash
git add neos/workflow/deep_analysis/llm.py tests/workflow/deep_analysis/test_llm.py
git commit -m "feat(deep-analysis): carry the granted output ceiling on every response

call_json cannot tell a call cut at its configured ceiling from one cut by
the budget clamp, because reserve() silently lowers the ceiling and only
_budgeted_dispatch sees the result. Attaching that value to the response
makes the two distinguishable at the call site.

The field defaults to 0 so legacy cassette records still restore, and
_budgeted_dispatch overwrites it after the cassette layer -- the granted
ceiling belongs to this run's budget, not to the recording."
```

---

## Task 2: `call_json`이 truncation을 분류해 확장 재시도한다

**Files:**
- Modify: `neos/config/schema.py:664-` (`DeepAnalysisConfig`), `neos/workflow/deep_analysis/llm.py:16-21` (예외), `llm.py:318-347` (`call_json`)
- Test: `tests/workflow/deep_analysis/test_llm.py`, `tests/workflow/deep_analysis/test_config_defaults.py`

**Interfaces:**
- Consumes: `LLMResponse.granted_max_output_tokens` (Task 1)
- Produces:
  - `TruncatedResponseError(JSONParseError)` — `neos/workflow/deep_analysis/llm.py`에서 export. 확장 재시도까지 실패했거나 예산에 걸려 재시도가 무의미할 때 `call_json`이 올린다.
  - `settings.config.deep_analysis.truncation_retry_multiplier: float` — 기본 `2.0`

- [ ] **Step 1: 설정값 테스트를 쓴다**

`tests/workflow/deep_analysis/test_config_defaults.py` 끝에 추가한다.

```python
def test_truncation_retry_multiplier_default():
    from neos.config.settings import settings

    assert settings.config.deep_analysis.truncation_retry_multiplier == 2.0
```

- [ ] **Step 2: 재시도 매트릭스 테스트를 쓴다**

`tests/workflow/deep_analysis/test_llm.py` 끝에 추가한다. import에 `TruncatedResponseError`를 더한다.

```python
@pytest.mark.asyncio
async def test_ceiling_bound_truncation_retries_at_a_larger_ceiling():
    """상한에 걸려 잘렸으면 2배로 한 번 더 부른다."""
    client = FakeAnthropic(
        ['{"partial": tru', '{"ok": true}'],
        stop_reasons=["max_tokens", "end_turn"],
    )

    data, _response = await call_json(
        "claude-haiku-4-5-20251001",
        "prompt",
        max_tokens=400,
        client=client,
    )

    assert data == {"ok": True}
    assert client.calls == 2
    assert [kw["max_tokens"] for kw in client.kwargs] == [400, 800]


@pytest.mark.asyncio
async def test_budget_bound_truncation_does_not_retry():
    """예산에 깎여 잘렸으면 재시도해도 같거나 더 적은 여유를 받는다 — 부르지 않는다."""
    client = FakeAnthropic(
        ['{"partial": tru'],
        stop_reasons=["max_tokens"],
    )
    budget = TokenBudget(400)

    with token_budget_scope(budget):
        with pytest.raises(TruncatedResponseError):
            await call_json(
                "claude-haiku-4-5-20251001",
                "prompt",
                max_tokens=5000,
                client=client,
            )

    assert client.calls == 1


@pytest.mark.asyncio
async def test_exhausted_expansion_raises_truncated_response_error():
    """확장 재시도도 잘리면 종단이다 — 더 늘리지 않는다."""
    client = FakeAnthropic(
        ['{"partial": tru', '{"still cu'],
        stop_reasons=["max_tokens", "max_tokens"],
    )

    with pytest.raises(TruncatedResponseError):
        await call_json(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=400,
            client=client,
        )

    assert client.calls == 2


@pytest.mark.asyncio
async def test_garbage_response_still_retries_at_the_same_ceiling():
    """잘리지 않은 쓰레기 응답의 기존 동작은 그대로다."""
    client = FakeAnthropic(["garbage", "still garbage"])

    with pytest.raises(JSONParseError) as excinfo:
        await call_json(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=400,
            client=client,
        )

    assert not isinstance(excinfo.value, TruncatedResponseError)
    assert client.calls == 2
    assert [kw["max_tokens"] for kw in client.kwargs] == [400, 400]


@pytest.mark.asyncio
async def test_truncated_response_error_is_a_json_parse_error():
    """예외를 전파하던 호출부가 변경 없이 계속 잡을 수 있어야 한다."""
    assert issubclass(TruncatedResponseError, JSONParseError)
```

- [ ] **Step 3: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_llm.py \
  tests/workflow/deep_analysis/test_config_defaults.py \
  -k "truncat or garbage_response" -q
```

Expected: FAIL — `ImportError: cannot import name 'TruncatedResponseError'`

- [ ] **Step 4: 설정값을 추가한다**

`neos/config/schema.py`의 `DeepAnalysisConfig` 안, `entailment_max_output_tokens`(747행 부근) 바로 다음 줄에 넣는다.

```python
    # A truncated response is a *different failure* from a malformed one: the
    # judgement is unfinished, not wrong. When a call is cut at its configured
    # ceiling (not by the budget clamp), call_json retries once at this
    # multiple of the ceiling.
    #
    # 2.0 is a compromise, not a measured sufficiency. The judge was cut at
    # both 300 and 800, so doubling is not guaranteed to be enough — when it
    # is not, the call site fails closed. The alternative, requesting all
    # remaining headroom, lets one worker monopolise the dev profile's
    # global_token_cap of 20000 across parallel_workers=2 and starve its peer.
    truncation_retry_multiplier: float = 2.0
```

- [ ] **Step 5: 예외를 정의한다**

`llm.py:16-18`의 `JSONParseError` 바로 아래에 추가한다.

```python
class JSONParseError(ValueError):
    """Raised when an LLM response does not contain one valid JSON object."""


class TruncatedResponseError(JSONParseError):
    """Raised when the response failed to parse *because it was cut off*.

    A subclass of JSONParseError on purpose: the five call sites that already
    let a parse failure propagate keep working untouched, while the two that
    fail open on D14 can opt into the distinction by catching this first.
    """
```

- [ ] **Step 6: `call_json`을 교체한다**

`llm.py:318-347`을 통째로 바꾼다.

```python
async def call_json(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float = 0.0,
    client=None,
    cassette=None,
    retries: int = 1,
    stage: str = "llm",
) -> tuple[dict[str, Any], LLMResponse]:
    """Call the model and parse one JSON object out of its response.

    `retries` counts tolerance for *malformed* responses. Truncation is a
    separate axis: a call cut at its ceiling earns one extra attempt at a
    larger ceiling regardless of `retries`, because the two failures have
    different causes and different cures.
    """

    from neos.config.settings import settings

    multiplier = settings.config.deep_analysis.truncation_retry_multiplier
    limit = max_tokens
    expanded = False
    last_error: JSONParseError | None = None
    attempts_left = retries + 1

    while attempts_left > 0:
        response = await call_llm(
            model,
            prompt,
            max_tokens=limit,
            temperature=temperature,
            client=client,
            cassette=cassette,
            stage=stage,
        )
        try:
            return parse_json(response.text), response
        except JSONParseError as exc:
            last_error = exc

        if response.stop_reason != "max_tokens":
            attempts_left -= 1
            continue

        # Cut off. Retrying only helps if the ceiling -- not the budget --
        # was the binding constraint: settling this call already shrank
        # `remaining`, so a budget-clamped retry gets *less* room, not more.
        budget_bound = response.granted_max_output_tokens < limit
        if budget_bound or expanded:
            raise TruncatedResponseError(str(last_error))

        # The expansion is a separate axis from `retries`: it answers a
        # different failure, so it does not consume a malformed-response
        # attempt. It is available at most once, and the `expanded` guard
        # above makes a second truncation terminal -- so the loop always ends.
        expanded = True
        limit = int(limit * multiplier)

    if last_error is None:
        raise JSONParseError("JSON parsing failed without a response")
    raise last_error
```

⚠️ **루프 종료 조건에 주의한다.** 초기 구상은 `while attempts_left > 0 or not expanded`였는데, 이는 `retries=0` + 비-truncation 실패에서 **무한 루프**가 된다(`attempts_left`가 음수로 내려가도 `not expanded`가 계속 참). 위 형태는 매 반복이 `attempts_left`를 줄이거나 `expanded`를 세우고, `expanded`가 선 상태의 두 번째 truncation은 즉시 종단이므로 반드시 끝난다.

**이 태스크는 관측(이벤트)을 다루지 않는다.** truncation을 *어떻게 처리하는가*가 여기까지고, *무엇을 했는지 기록하는가*는 Task 3이다. 두 관심사를 나눠야 각 커밋이 독립적으로 리뷰 가능하다. Task 3이 원래 상한을 기록하려고 `original_limit`을 도입하는데, 그 변수를 여기서 미리 잡아두면 미사용 지역변수가 되어 Ruff에 걸린다 — 도입은 Task 3에서 한다.

- [ ] **Step 7: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_llm.py \
  tests/workflow/deep_analysis/test_config_defaults.py -q
```

Expected: PASS

- [ ] **Step 9: 커밋한다**

```bash
git add neos/config/schema.py neos/workflow/deep_analysis/llm.py \
  tests/workflow/deep_analysis/test_llm.py \
  tests/workflow/deep_analysis/test_config_defaults.py
git commit -m "feat(deep-analysis): retry a truncated JSON call at a larger ceiling

A parse failure had one cause as far as call_json was concerned, so a cut
judgement and a malformed one earned the same same-ceiling retry -- which
for a cut response is a second charge for a deterministic failure.

Split the two. A response cut at its ceiling retries once at
truncation_retry_multiplier times that ceiling; one cut by the budget clamp
does not retry at all, since settling the first call shrinks remaining and
the retry would get less room. Both terminal paths raise
TruncatedResponseError, which subclasses JSONParseError so the callers that
propagate stay untouched."
```

---

## Task 3: `truncation_handled` 이벤트

**Files:**
- Modify: `neos/workflow/deep_analysis/token_budget.py:171-197` 부근, `neos/workflow/deep_analysis/llm.py` (헬퍼 추가 + Task 2의 `call_json`에 기록 지점 삽입)
- Test: `tests/workflow/deep_analysis/test_llm.py`

**Interfaces:**
- Consumes: `TruncatedResponseError`와 Task 2가 만든 `call_json` 재시도 루프 (`limit` / `expanded` / `budget_bound` 지역변수를 그대로 쓴다)
- Produces:
  - `TokenBudget.record_truncation_handled(*, stage: str, model: str, requested: int, granted: int, action: str) -> None` — `action`은 `"retried_ok"` | `"retried_failed"` | `"budget_bound"`
  - `llm.py`의 모듈 수준 헬퍼 `_record_truncation_handled(...)` — 같은 시그니처, 활성 예산이 없으면 조용히 넘어간다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_llm.py` 끝에 추가한다.

```python
def _event_recorder():
    events: list[tuple[str, dict]] = []

    async def persist(kind, payload):
        events.append((kind, payload))

    return events, persist


@pytest.mark.asyncio
async def test_successful_expansion_records_retried_ok():
    events, persist = _event_recorder()
    budget = TokenBudget(100_000, persist=persist)
    client = FakeAnthropic(
        ['{"partial": tru', '{"ok": true}'],
        stop_reasons=["max_tokens", "end_turn"],
    )

    with token_budget_scope(budget):
        await call_json(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=400,
            client=client,
            stage="claim_grading",
        )

    handled = [p for kind, p in events if kind == "truncation_handled"]
    assert len(handled) == 1
    assert handled[0]["action"] == "retried_ok"
    assert handled[0]["stage"] == "claim_grading"
    assert handled[0]["requested"] == 400


@pytest.mark.asyncio
async def test_budget_bound_truncation_records_budget_bound():
    events, persist = _event_recorder()
    budget = TokenBudget(400, persist=persist)
    client = FakeAnthropic(['{"partial": tru'], stop_reasons=["max_tokens"])

    with token_budget_scope(budget):
        with pytest.raises(TruncatedResponseError):
            await call_json(
                "claude-haiku-4-5-20251001",
                "prompt",
                max_tokens=5000,
                client=client,
                stage="claim_grading",
            )

    handled = [p for kind, p in events if kind == "truncation_handled"]
    assert len(handled) == 1
    assert handled[0]["action"] == "budget_bound"
    assert handled[0]["granted"] < handled[0]["requested"]


@pytest.mark.asyncio
async def test_untruncated_call_records_no_truncation_event():
    """정상 경로 전체가 이벤트가 되면 로그를 압도한다 — 잘렸을 때만 쓴다."""
    events, persist = _event_recorder()
    budget = TokenBudget(100_000, persist=persist)

    with token_budget_scope(budget):
        await call_json(
            "claude-haiku-4-5-20251001",
            "prompt",
            max_tokens=400,
            client=FakeAnthropic(['{"ok": true}']),
        )

    assert [kind for kind, _ in events if kind == "truncation_handled"] == []


@pytest.mark.asyncio
async def test_truncation_events_are_skipped_without_an_active_budget():
    """TokenBudget이 작성자이므로 예산 밖에서는 기록할 곳이 없다 — 터지면 안 된다."""
    client = FakeAnthropic(
        ['{"partial": tru', '{"ok": true}'],
        stop_reasons=["max_tokens", "end_turn"],
    )

    data, _ = await call_json(
        "claude-haiku-4-5-20251001",
        "prompt",
        max_tokens=400,
        client=client,
    )

    assert data == {"ok": True}
```

- [ ] **Step 2: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_llm.py -k "retried_ok or budget_bound or no_truncation_event or without_an_active_budget" -q
```

Expected: FAIL — `assert len(handled) == 1` 이 `0`으로 실패

- [ ] **Step 3: `TokenBudget`에 작성자를 추가한다**

`token_budget.py`의 `record_truncation`(171행 부근) 바로 아래에 넣는다.

```python
    async def record_truncation_handled(
        self,
        *,
        stage: str,
        model: str,
        requested: int,
        granted: int,
        action: str,
    ) -> None:
        """Record what was done about a truncated response.

        `llm_truncated` says a response was cut; this says whether the cut
        was recoverable. Without it, a run that produced no discards cannot
        be told apart from one whose filter never ran -- which is exactly
        what left the discard-recall measurement inconclusive twice.

        Written only when a truncation actually occurred, so one
        `llm_truncated` corresponds to one of these.

        Payload carries counts and identifiers only — never response text.
        """
        async with self._lock:
            await self._persist_event(
                "truncation_handled",
                {
                    "stage": stage,
                    "model": model,
                    "requested": requested,
                    "granted": granted,
                    "action": action,
                },
            )
```

- [ ] **Step 4: `llm.py`에 모듈 헬퍼를 추가한다**

`call_json` 정의 **위**에 넣는다.

```python
async def _record_truncation_handled(
    *,
    stage: str,
    model: str,
    requested: int,
    granted: int,
    action: str,
) -> None:
    # TokenBudget is the writer (P2). Outside a budget scope there is nowhere
    # to write, and that is not an error -- tests and ad-hoc calls run there.
    budget = active_token_budget()
    if budget is None:
        return
    await budget.record_truncation_handled(
        stage=stage,
        model=model,
        requested=requested,
        granted=granted,
        action=action,
    )
```

- [ ] **Step 5: `call_json`에 기록 지점 두 곳을 넣는다**

Task 2가 만든 루프에 세 가지를 더한다.

**(a) 원래 상한을 잡아둔다.** `limit = max_tokens` 바로 위에 넣는다. `limit`은 확장 시 덮어써지므로 원래 값이 따로 필요하다.

```python
    original_limit = max_tokens
```

**(b) 성공 경로** — `return parse_json(response.text), response` 줄을 바꾼다. 확장 재시도로 살아난 경우에만 기록하므로 `expanded`를 본다.

```python
        try:
            parsed = parse_json(response.text)
        except JSONParseError as exc:
            last_error = exc
        else:
            if expanded:
                await _record_truncation_handled(
                    stage=stage,
                    model=model,
                    requested=original_limit,
                    granted=response.granted_max_output_tokens,
                    action="retried_ok",
                )
            return parsed, response
```

**(c) 종단 경로** — Task 2가 남긴 `raise TruncatedResponseError(str(last_error))` 앞에 기록을 넣는다.

```python
        budget_bound = response.granted_max_output_tokens < limit
        if budget_bound or expanded:
            await _record_truncation_handled(
                stage=stage,
                model=model,
                requested=original_limit,
                granted=response.granted_max_output_tokens,
                action="budget_bound" if budget_bound else "retried_failed",
            )
            raise TruncatedResponseError(str(last_error))
```

세 기록 모두 `requested`에 **원래 상한**을 쓴다 — 사후 집계에서 "얼마로 요청했다가 잘렸나"가 호출부의 설정값과 대응해야 하기 때문이다.

- [ ] **Step 6: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_llm.py \
  tests/workflow/deep_analysis/test_budgeter.py -q
```

Expected: PASS

- [ ] **Step 7: 커밋한다**

```bash
git add neos/workflow/deep_analysis/token_budget.py neos/workflow/deep_analysis/llm.py \
  tests/workflow/deep_analysis/test_llm.py
git commit -m "feat(deep-analysis): record what was done about each truncation

llm_truncated says a response was cut. It does not say whether the cut was
recovered, and that gap is why two discard-recall samples in a row could not
distinguish 'nothing to discard' from 'the filter never ran'.

truncation_handled carries the outcome -- retried_ok, retried_failed, or
budget_bound -- alongside the requested and granted ceilings, so the two
prescriptions stay separable after the fact. Written only when a truncation
occurred, so it pairs one-to-one with llm_truncated, and skipped outside a
budget scope where TokenBudget has nowhere to write."
```

---

## Task 4: judge 종단 — truncation은 반려한다 (D24)

**Files:**
- Modify: `neos/workflow/deep_analysis/graders/agentic.py:6` (import), `agentic.py:84-94`
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (D24 추가)
- Test: `tests/workflow/deep_analysis/test_agentic_grader.py`

**Interfaces:**
- Consumes: `TruncatedResponseError` (Task 2)
- Produces: `Verdict(ok=False, code="E_UNSUPPORTED", detail="judge_truncated")` — mandatory 여부와 무관하다. `diagnostics`는 `{"agentic": "attempted_rejected", "agentic_label": None}`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_agentic_grader.py` 끝에 추가한다. 이 파일의 기존 헬퍼 `_claim(conf=...)`와 `judge_model="j"` 관례를 그대로 쓴다. import에 `JSONParseError`와 `TruncatedResponseError`를 더한다.

```python
@pytest.mark.asyncio
async def test_truncated_judge_rejects_a_mandatory_claim(monkeypatch):
    async def truncated(*args, **kwargs):
        raise TruncatedResponseError("cut off")

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.graders.agentic.call_json", truncated
    )
    g = AgenticGrader(
        judge_model="j", threshold=0.35, sample_rate=0.0, max_output_tokens=800
    )

    verdict = await g.grade(_claim(conf=0.9), value_est=0.9)  # 0.81 >= 0.35

    assert verdict.ok is False
    assert verdict.code == "E_UNSUPPORTED"
    assert verdict.detail == "judge_truncated"


@pytest.mark.asyncio
async def test_truncated_judge_also_rejects_a_sampled_claim(monkeypatch):
    """D24: truncation은 mandatory 여부와 무관하게 반려다.

    측정된 사례가 정확히 이 경로에서 나왔다 — 잘린 응답이 이미
    "label": "CONTRADICTS"를 내뱉었는데 D14 fail-open이 승인으로 뒤집었다.
    저가치 샘플이라 D14의 mandatory 예외로도 막히지 않았다.
    """

    async def truncated(*args, **kwargs):
        raise TruncatedResponseError("cut off")

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.graders.agentic.call_json", truncated
    )
    g = AgenticGrader(
        judge_model="j",
        threshold=0.35,
        sample_rate=1.0,
        max_output_tokens=800,
        sampler=lambda: 0.0,
    )

    verdict = await g.grade(_claim(conf=0.1), value_est=0.1)  # 0.01 < 0.35

    assert verdict.ok is False
    assert verdict.code == "E_UNSUPPORTED"
    assert verdict.detail == "judge_truncated"
    assert verdict.diagnostics["agentic"] == "attempted_rejected"


@pytest.mark.asyncio
async def test_malformed_judge_still_fails_open_for_a_sampled_claim(monkeypatch):
    """D14 원결정은 그대로다 — 쓰레기 응답은 여전히 미심사 통과다."""

    async def malformed(*args, **kwargs):
        raise JSONParseError("not json")

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.graders.agentic.call_json", malformed
    )
    g = AgenticGrader(
        judge_model="j",
        threshold=0.35,
        sample_rate=1.0,
        max_output_tokens=800,
        sampler=lambda: 0.0,
    )

    verdict = await g.grade(_claim(conf=0.1), value_est=0.1)

    assert verdict.ok is True
    assert verdict.detail == "judge_unparseable"
```

- [ ] **Step 2: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_agentic_grader.py -k truncated -q
```

Expected: FAIL — `judge_unparseable`가 나오거나 `verdict.ok is True`

- [ ] **Step 3: 구현한다**

`agentic.py:6`의 import를 바꾼다.

```python
from ..llm import call_json, JSONParseError, TruncatedResponseError
```

`agentic.py:84-94`의 `try/except`를 바꾼다. `except TruncatedResponseError`가 `except JSONParseError`보다 **먼저** 와야 한다 — 서브클래스이므로 순서가 뒤바뀌면 새 분기가 죽는다.

```python
        try:
            data, _ = await call_json(
                self.judge_model,
                prompt,
                max_tokens=self.max_output_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="claim_grading",
            )
        except TruncatedResponseError:
            # D24: a cut judgement is unfinished, not absent. D14's fail-open
            # answers "the judge produced garbage"; it does not answer "the
            # judge was interrupted mid-verdict". One measured response had
            # already emitted "label": "CONTRADICTS" before the cut, and the
            # fail-open turned that rejection into an acceptance. Mandatory or
            # sampled, a truncated judgement is rejected.
            return Verdict(
                ok=False,
                code="E_UNSUPPORTED",
                label=None,
                detail="judge_truncated",
                diagnostics={
                    "agentic": "attempted_rejected",
                    "agentic_label": None,
                },
            )
        except JSONParseError:
            return self._judge_failed(mandatory, "judge_unparseable")
```

- [ ] **Step 4: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_agentic_grader.py -q
```

Expected: PASS

- [ ] **Step 5: D24를 기록한다**

`neos/workflow/deep_analysis/DECISIONS.md` 끝에 추가한다. D23 다음 번호다.

```markdown
## D24. truncation은 D14 fail-open의 사유가 아니다 — judge 반려

**결정:** `AgenticGrader.grade`가 `TruncatedResponseError`를 받으면 **mandatory 여부와
무관하게** `Verdict(ok=False, code="E_UNSUPPORTED", detail="judge_truncated")`로 반려한다.
`JSONParseError`(비-truncation)에 대한 D14의 미심사 통과는 그대로 유지된다.

**근거:** D14는 "judge가 판정 불가한 응답을 냈다"를 전제로 한 결정이다. truncation은 다르다 —
판정이 *미완성*일 뿐 부재가 아니다. `20260802T052306Z` 표본에서 잘린 judge 응답 하나는 이미
`"label": "CONTRADICTS"`를 내뱉은 뒤 잘렸고, 파싱 실패가 D14 fail-open을 발동시켜 **거절이
승인으로 뒤집혔다.** 저가치 샘플 경로였으므로 D14의 mandatory 예외로도 막히지 않았다.

**이탈:** D14 원결정 중 `judge_unparseable`의 저가치 샘플 fail-open을, 원인이 truncation인
경우에 한해 철회한다.

**영향:** 반려된 claim은 기존 경로대로 재조사되고 `claim_retry_cap` 소진 시 `unverified`로
보고서 「한계」 절에 남는다(빈손 종료 없음). **claim funnel 수치가 이동하므로 이전 표본과
직접 비교할 수 없다** — `docs/TODO_260729.md` E1의 baseline 단절이 한 번 더 발생한다.
discard recall 재측정(C1)은 이 변경 이후 표본으로 수행해야 두 효과가 섞이지 않는다.
```

- [ ] **Step 6: 커밋한다**

```bash
git add neos/workflow/deep_analysis/graders/agentic.py \
  neos/workflow/deep_analysis/DECISIONS.md \
  tests/workflow/deep_analysis/test_agentic_grader.py
git commit -m "fix(deep-analysis): reject a claim whose judgement was cut off

D14 lets an unparseable judge response pass a sampled claim unreviewed, on
the reasoning that a garbled response is not evidence against the claim.
That reasoning does not extend to a truncated one, where the verdict exists
but is unfinished. A response in sample 20260802T052306Z had already emitted
CONTRADICTS when it was cut, and the fail-open turned that rejection into an
acceptance -- on the sampled path, so D14's mandatory carve-out never
applied.

Truncated judgements now reject regardless of mandatory status, recorded as
D24. Malformed ones keep D14's fail-open. Note this moves the claim funnel,
so it breaks comparability with earlier samples again."
```

---

## Task 5: report 종단 — 결정론적 판정으로 복귀한다

**Files:**
- Modify: `neos/workflow/deep_analysis/graders/report.py:14` (import), `report.py:130-168`
- Test: `tests/workflow/deep_analysis/test_report_grader.py` (기존 파일)

**Interfaces:**
- Consumes: `TruncatedResponseError` (Task 2)
- Produces: `ReportGrader.grade_agentic`가 `TruncatedResponseError` 시 `Verdict(ok=True, detail="judge_truncated")`를 반환한다. `grade`는 그 값을 그대로 돌려준다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_report_grader.py` 끝에 추가한다. 이 파일의 기존 헬퍼 `_grader(ledger, json_call=...)`, `_clean_report()`, `FakeLedger`, `Question`, `CHILD1`, `CHILD2`를 그대로 쓴다. import에 `TruncatedResponseError`를 더한다.

바로 위 `test_grade_keeps_deterministic_pass_when_agentic_budget_exhausts`(212행)가 이 태스크가 따라가는 선례다 — 나란히 두면 두 경로가 같은 이유로 같은 결말을 갖는다는 게 읽힌다.

```python
@pytest.mark.asyncio
async def test_grade_keeps_deterministic_pass_when_agentic_judge_is_truncated():
    """재조립은 잘린 judge를 고치지 못한다 — 초안 품질과 무관하기 때문이다.

    반려하면 orchestrator가 초안을 다시 조립하는데, 같은 judge가 같은 상한에서
    또 잘린다. report_retry_cap + 1회의 synthesizer 호출을 태우고 제자리다.
    """
    calls = 0

    async def truncated_json_call(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise TruncatedResponseError("cut off mid-rationale")

    root = Question("root0001", "루트 질문")
    grader = _grader(
        FakeLedger(children=[CHILD1, CHILD2], root=root),
        json_call=truncated_json_call,
    )

    verdict = await grader.grade(_clean_report(), root.id)

    assert verdict.ok is True
    assert verdict.detail == "judge_truncated"
    assert calls == 1


@pytest.mark.asyncio
async def test_truncated_report_judge_does_not_mask_a_deterministic_failure():
    """결정론적 게이트가 먼저 막았으면 judge는 불리지도 않는다."""
    calls = 0

    async def truncated_json_call(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise TruncatedResponseError("cut off mid-rationale")

    grader = _grader(FakeLedger(), json_call=truncated_json_call)

    verdict = await grader.grade("한계 절이 없는 본문.", "root0001")

    assert verdict.ok is False
    assert verdict.code == "E_REPORT_NO_LIMITS"
    assert calls == 0
```

- [ ] **Step 2: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_report_grader.py -q
```

Expected: FAIL — 첫 테스트가 `detail == "judge_unparseable"`로 실패

- [ ] **Step 3: 구현한다**

`report.py:14`의 import를 바꾼다.

```python
from ..llm import JSONParseError, TruncatedResponseError, call_json
```

`report.py:130-145`의 `grade_agentic` 앞부분을 바꾼다. 여기서도 `TruncatedResponseError`가 `JSONParseError`보다 먼저다.

```python
    async def grade_agentic(self, report: str, root_text: str) -> Verdict:
        prompt = render("report_judge", report=report, root_text=root_text)
        try:
            data, _ = await self.json_call(
                self.judge_model,
                prompt,
                max_tokens=400,
                client=self.llm_client,
                cassette=self.cassette,
                stage="report_grading",
            )
        except TruncatedResponseError:
            # Rejecting here sends the orchestrator back to re-assemble the
            # draft (orchestrator.py:833-868), but a truncated judge has
            # nothing to do with draft quality -- the same judge cuts at the
            # same ceiling on every retry, burning report_retry_cap + 1
            # synthesizer calls to reach the same place. Treat it the way a
            # budget-exhausted judge is already treated below: fall back to
            # the deterministic verdict, and say why.
            return Verdict(ok=True, detail="judge_truncated")
        except JSONParseError:
            # Degrade to pass rather than halting the run (mirrors D14 in
            # AgenticGrader): an unparseable judge response is not evidence
            # of a bad report.
            return Verdict(ok=True, detail="judge_unparseable")
```

`grade`(155-168행)는 변경하지 않는다 — 결정론적 게이트가 이미 먼저 돌고, 실패 시 조기 반환한다.

- [ ] **Step 4: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_report_grader.py -q
```

Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add neos/workflow/deep_analysis/graders/report.py \
  tests/workflow/deep_analysis/test_report_grader.py
git commit -m "fix(deep-analysis): stop a cut report judge from forcing re-assembly

Rejecting a report sends the orchestrator back to re-assemble the draft. That
is the right response to a bad draft and the wrong one to a truncated judge,
whose failure has nothing to do with draft quality -- the same judge cuts at
the same ceiling on every attempt, so the loop spends report_retry_cap + 1
synthesizer calls arriving where it started.

Truncation now falls back to the deterministic verdict, the path a
budget-exhausted judge already takes, with the reason recorded in detail."
```

---

## Task 6: entailment를 `call_json`으로 옮기고 스킵을 기록 가능하게 한다

**Files:**
- Modify: `neos/workflow/deep_analysis/worker.py:15-21` (import), `worker.py:357-388`, `worker.py:73`/`173`/`84`/`317`
- Modify: `neos/workflow/deep_analysis/models.py:71-88` (`WorkerResult`)
- Test: `tests/workflow/deep_analysis/test_worker_entailment.py`

**Interfaces:**
- Consumes: `TruncatedResponseError` (Task 2)
- Produces: `WorkerResult.entailment_skipped: bool = False` — entailment 배치가 필터를 적용하지 못하고 원본 claim을 그대로 통과시켰을 때 `True`.

⚠️ **이 태스크는 기존 테스트 2건을 깨뜨릴 수 있다.** Step 4와 Step 5에서 함께 다룬다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_worker_entailment.py` 끝에 추가한다. 이 파일의 `ScriptedLLM`은 `stop_reason`을 세팅하지 않으므로(`_response`가 그 속성을 안 만든다) truncation 전용 스크립트 LLM을 새로 만든다. import에 `TruncatedResponseError`를 더한다.

```python
class TruncatedEntailmentLLM:
    """생성은 정상, entailment 호출만 max_tokens에서 잘린다."""

    def __init__(self):
        self.messages = self
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _response(_generation(["keep", "broad", "drop"]))
        response = _response('{"results":[{"index":0,"acti')
        response.stop_reason = "max_tokens"
        return response


@pytest.mark.asyncio
async def test_truncated_entailment_passes_claims_through_and_flags_the_skip():
    """entailment은 게이트가 아니라 필터다 — 통과분은 어차피 grader를 다시 거친다.

    다만 필터가 안 돌았다는 사실은 남아야 한다. 이게 없으면 discard 0건이
    '버릴 게 없었다'인지 '필터가 안 돌았다'인지 구분되지 않는다.
    """
    llm = TruncatedEntailmentLLM()

    result = await Worker(
        Search(), fetch_fn=Fetch(), llm_client=llm
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert [claim.text for claim in result.claims] == ["keep", "broad", "drop"]
    assert result.discarded_claims == []
    assert result.entailment_skipped is True
    # 생성 1회 + entailment 1회 + 확장 재시도 1회
    assert llm.calls == 3


@pytest.mark.asyncio
async def test_successful_entailment_does_not_flag_a_skip():
    llm = ScriptedLLM(
        json.dumps(
            {
                "results": [
                    {"index": 0, "action": "keep"},
                    {"index": 1, "action": "keep"},
                    {"index": 2, "action": "discard"},
                ]
            }
        )
    )

    result = await Worker(
        Search(), fetch_fn=Fetch(), llm_client=llm
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert result.entailment_skipped is False


@pytest.mark.asyncio
async def test_malformed_entailment_flags_the_skip_without_retrying():
    """쓰레기 응답의 기존 동작(1회 호출, fail-open)은 그대로다."""
    llm = ScriptedLLM("not json")

    result = await Worker(
        Search(), fetch_fn=Fetch(), llm_client=llm
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert [claim.text for claim in result.claims] == ["keep", "broad", "drop"]
    assert result.entailment_skipped is True
    assert len(llm.prompts) == 2   # 생성 1 + entailment 1, 재시도 없음
```

- [ ] **Step 2: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_worker_entailment.py -q
```

Expected: FAIL — `AttributeError: 'WorkerResult' object has no attribute 'entailment_skipped'`

- [ ] **Step 3: `WorkerResult`에 플래그를 추가한다**

`models.py`의 `WorkerResult`(71-88행)에 `confidence_clamped_by_source_count` 다음 줄로 넣는다.

```python
    # entailment 배치가 필터를 적용하지 못하고 원본 claim을 그대로 통과시켰는가.
    # discard 0건의 두 원인("버릴 게 없었다" / "필터가 안 돌았다")을 가른다.
    entailment_skipped: bool = False
```

- [ ] **Step 4: 워커를 `call_json`으로 옮기고 플래그를 세운다**

`worker.py:15-21`의 import에서 `call_llm`과 `parse_json`을 빼고 `TruncatedResponseError`를 넣는다. entailment가 두 함수의 **유일한 사용처**이므로 남겨두면 Ruff가 미사용으로 잡는다.

```python
from .llm import (
    JSONParseError,
    LLMProviderError,
    TruncatedResponseError,
    call_json,
)
```

`worker.py:73` 근처의 `self._discarded_claims` 초기화 옆에 추가한다.

```python
        self._entailment_skipped = False
```

`worker.py:173`의 `self._discarded_claims = []` 옆에도 리셋을 넣는다.

```python
        self._entailment_skipped = False
```

`worker.py:357-388`의 entailment 호출부를 바꾼다.

```python
        prompt = render("claim_entailment", claims_json=claims_json)
        try:
            payload, response = await call_json(
                self._model,
                prompt,
                max_tokens=config.entailment_max_output_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="claim_entailment",
                # This call never retried a malformed response and must not
                # start: a second batch costs the same tokens for a response
                # the first attempt already showed the model will not format.
                # The truncation expansion is a separate axis and still runs.
                retries=0,
            )
        except TokenBudgetExhausted:
            raise
        except LLMProviderError as exc:
            logger.warning(
                "Claim entailment provider failed: error_type=%s",
                type(exc).__name__,
            )
            self._entailment_skipped = True
            return claims
        except TruncatedResponseError:
            # A filter, not a gate: these claims still face the deterministic
            # and agentic graders. Dropping or rejecting the batch would
            # manufacture the very recall loss the discard measurement exists
            # to detect. Pass them through, but record that the filter never
            # ran on them.
            logger.warning("Claim entailment response was cut off")
            self._entailment_skipped = True
            return claims
        except JSONParseError:
            logger.warning("Claim entailment response was not valid JSON")
            self._entailment_skipped = True
            return claims

        self._tokens += response.input_tokens + response.output_tokens

        outcome = apply_entailment_results(claims, payload)
        if outcome is None:
            logger.warning("Claim entailment response failed validation")
            self._entailment_skipped = True
            return claims
        self._discarded_claims = list(outcome.discarded)
        return outcome.refined
```

⚠️ **`retries=0`이 없으면 기존 테스트가 깨진다.** `call_json`의 기본값 `retries=1`은 쓰레기 응답에 재호출을 건다. `ScriptedLLM`은 응답을 정확히 2개만 들고 있어(`responses.pop(0)`) 세 번째 호출에서 `IndexError`가 난다. 더 근본적으로는, 지금 이 호출은 쓰레기 응답을 재시도하지 **않으며** 그 동작을 바꾸는 것은 이 플랜의 범위가 아니다.

⚠️ **`LLMProviderError` 분기는 토큰을 더하지 않는다.** 기존 동작이 그렇고(`test_worker_entailment_provider_failure_keeps_original_batch`가 `tokens_spent == 15`를 단언한다), 유지해야 한다.

- [ ] **Step 5: 예산 소진 테스트의 monkeypatch 대상을 고친다**

`test_entailment_token_exhaustion_returns_buffered_partial`(243-263행)이
`neos.workflow.deep_analysis.worker.call_llm`을 패치하는데, 워커가 더 이상 그 이름을 쓰지
않으므로 패치가 아무것도 가로채지 못한다. `call_json`으로 바꾼다.

```python
@pytest.mark.asyncio
async def test_entailment_token_exhaustion_returns_buffered_partial(monkeypatch):
    from neos.workflow.deep_analysis.llm import call_json as real_call_json

    async def exhausted(model, prompt, **kwargs):
        if kwargs["stage"] == "claim_entailment":
            raise TokenBudgetExhausted("cap")
        return await real_call_json(model, prompt, **kwargs)

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.worker.call_json",
        exhausted,
    )
    result = await Worker(
        Search(),
        fetch_fn=Fetch(),
        llm_client=ScriptedLLM(
            '{"results":[{"index":0,"action":"keep"}]}'
        ),
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert result.status == "partial"
    assert [claim.text for claim in result.claims] == ["keep", "broad", "drop"]
    assert result.tokens_spent == 15
```

⚠️ 워커의 **다른** `call_json` 사용처(`worker.py:242` analysis, `worker.py:459` repair)도 이 패치를 지나가므로 `stage` 분기와 실 `call_json` 위임이 둘 다 필요하다. 위 코드가 그렇게 되어 있다. 파일 상단 import에서 `call_llm`이 더 이상 안 쓰이면 함께 제거한다.

- [ ] **Step 6: 결과 객체에 플래그를 싣는다**

`worker.py:84`와 `worker.py:317`의 `WorkerResult(...)` 생성 두 곳 모두에 추가한다.

```python
            entailment_skipped=self._entailment_skipped,
```

- [ ] **Step 7: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_worker_entailment.py \
  tests/workflow/deep_analysis/test_claim_entailment.py \
  tests/workflow/deep_analysis/test_worker_discovery.py -q
```

Expected: PASS 전량. 특히 기존 `test_worker_entailment_fail_open_is_atomic`(3 파라미터)과 `test_worker_entailment_provider_failure_keeps_original_batch`가 여전히 통과해야 한다.

- [ ] **Step 8: 커밋한다**

```bash
git add neos/workflow/deep_analysis/worker.py neos/workflow/deep_analysis/models.py \
  tests/workflow/deep_analysis/test_claim_entailment.py
git commit -m "feat(deep-analysis): record when entailment never filtered a batch

Entailment is a filter, not a gate -- claims that slip past it still face the
deterministic and agentic graders -- so failing open on a truncated batch is
the right call. Dropping or rejecting the batch would manufacture the recall
loss the discard measurement exists to detect.

What was missing is the record. Two samples in a row reported zero discards
and neither could be told apart from a run whose filter never executed.
WorkerResult now carries entailment_skipped, and the call moves to call_json
so it shares the truncation handling rather than reimplementing it."
```

---

## Task 7: 오케스트레이터가 `entailment_filter_skipped`를 쓴다

P2에 따라 worker는 ledger에 쓰지 않는다. `discarded_claims`가 이미 쓰는 경로를 그대로 따른다.

**Files:**
- Modify: `neos/workflow/deep_analysis/orchestrator.py:655-677` 부근
- Test: `tests/workflow/deep_analysis/test_orchestrator_discard_events.py`

**Interfaces:**
- Consumes: `WorkerResult.entailment_skipped` (Task 6)
- Produces: ledger 이벤트 `entailment_filter_skipped`, 페이로드 `{"claim_count": int, "reason": "entailment_unavailable"}`, question_id는 `result.question_id`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_orchestrator_discard_events.py` 끝에 추가한다. 이 파일의 `DiscardWorker`, `_make_orchestrator`, `_discard_events` 패턴을 그대로 따른다. 이벤트는 실 DB의 `DAEvent` 행으로 읽는다.

먼저 `DiscardWorker`(95-122행)에 스킵 플래그를 실을 수 있게 인자를 하나 더한다.

```python
class DiscardWorker:
    """One completed pass: one surviving claim, two discarded."""

    def __init__(self, discarded=2, entailment_skipped=False):
        self.discarded = discarded
        self.entailment_skipped = entailment_skipped

    async def investigate(
        self, brief, effort, qid, repairs=None, question_text=""
    ):
        return WorkerResult(
            question_id=qid,
            status="completed",
            blobs=[
                ProposedBlob(
                    "a" * 16, "https://example.com/source", 200, "A body"
                )
            ],
            claims=[ProposedClaim("kept claim", 0.6, _evidence())],
            discarded_claims=[
                ProposedClaim(f"discarded {index}", 0.6, _evidence())
                for index in range(self.discarded)
            ],
            tokens_spent=100,
            self_assessment=0.9,
            entailment_skipped=self.entailment_skipped,
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")
```

그리고 파일 끝에 다음을 추가한다.

```python
async def _skip_events(session, run_id):
    rows = await session.execute(
        select(DAEvent.qid, DAEvent.payload).where(
            DAEvent.run_id == run_id,
            DAEvent.kind == "entailment_filter_skipped",
        )
    )
    return rows.all()


@pytest.mark.asyncio
async def test_orchestrator_logs_one_event_when_entailment_was_skipped():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        orch = _make_orchestrator(
            session,
            run_id,
            ledger,
            lambda: DiscardWorker(discarded=0, entailment_skipped=True),
        )
        await orch.run("root?")

        events = await _skip_events(session, run_id)

    assert len(events) == 1
    qid, payload = events[0]
    assert qid
    assert json.loads(payload) == {
        "claim_count": 1,
        "reason": "entailment_unavailable",
    }


@pytest.mark.asyncio
async def test_orchestrator_logs_no_skip_event_on_a_normal_pass():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        orch = _make_orchestrator(
            session,
            run_id,
            ledger,
            lambda: DiscardWorker(discarded=2, entailment_skipped=False),
        )
        await orch.run("root?")

        events = await _skip_events(session, run_id)

    assert events == []
```

`claim_count`가 1인 이유: `DiscardWorker`는 `claims`에 `"kept claim"` 하나만 싣는다.

- [ ] **Step 2: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_orchestrator_discard_events.py -q
```

Expected: FAIL — `assert len(skipped) == 1` 이 `0`으로 실패

- [ ] **Step 3: 구현한다**

`orchestrator.py:658`의 `for discarded in result.discarded_claims:` 루프 **바로 앞**에 넣는다. `await self.ledger.commit_blobs(result.blobs)` 다음 자리다.

```python
            # P2: the worker has no ledger, so it flags the skip on its result
            # and the single writer records it here -- the same shape the
            # discarded-claim loop below already uses.
            if result.entailment_skipped:
                await self.ledger.log(
                    "entailment_filter_skipped",
                    result.question_id,
                    {
                        "claim_count": len(result.claims),
                        "reason": "entailment_unavailable",
                    },
                )
```

- [ ] **Step 4: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_orchestrator_discard_events.py -q
```

Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add neos/workflow/deep_analysis/orchestrator.py \
  tests/workflow/deep_analysis/test_orchestrator_discard_events.py
git commit -m "feat(deep-analysis): log batches that bypassed the entailment filter

The worker holds no ledger under P2, so it flags the skip on its result and
the orchestrator writes the event -- the same shape the discarded-claim loop
beside it already uses.

This is what makes a zero-discard sample interpretable. Two measurements in a
row reported no discards, and until now that was indistinguishable from a run
where the filter never executed."
```

---

## Task 8: 전체 회귀와 문서 갱신

**Files:**
- Modify: `docs/TODO_260729.md` (A2 항목 상태)
- Test: deep_analysis 전량 + Ruff

**Interfaces:**
- Consumes: Task 1–7 전부
- Produces: 없음 (종결 태스크)

- [ ] **Step 1: deep_analysis 전량을 돌린다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/ -q --disable-warnings
```

Expected: PASS 전량. 기준선은 직전 작업의 344 passed이며, 이 플랜이 추가한 테스트만큼 늘어난다.

- [ ] **Step 2: 라우팅·노드 회귀를 돌린다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/routing/test_deep_analysis_routing.py \
  tests/workflow/test_deep_analysis_node.py -q
```

Expected: PASS

- [ ] **Step 3: Ruff를 돌린다**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/ tests/workflow/deep_analysis/
```

Expected: 통과. 실패하면 고치고 Step 1을 다시 돌린다.

- [ ] **Step 4: `docs/TODO_260729.md`를 갱신한다**

「남은 할 일 — 상세」의 A2 절에 완료 표시를 하고, 「권장 순서」 1번을 해소 처리한다. **A1·A3·A4·A5는 그대로 남긴다** — 이 플랜의 범위 밖이다.

A2 절 머리에 다음을 넣는다.

```markdown
**상태: 해소됨 (2026-08-02).** `TruncatedResponseError`가 `JSONParseError`를 상속하므로
예외를 전파하던 5개 호출부는 무변경으로 확장 재시도 이득을 받는다 — A3와 A4의 truncation
빈도도 이로써 낮아지나, 두 항목의 상한 재보정 자체는 여전히 미해결이다.
`truncation_handled` 이벤트로 재시도 성패와 예산 clamp 여부를 사후 집계할 수 있다.
```

C1 절에는 순서 의존을 적는다.

```markdown
⚠️ **선행 조건 추가 (2026-08-02):** D24가 claim funnel을 이동시키므로, 재측정 표본은
반드시 A2 병합 **이후**여야 한다. 또한 `entailment_filter_skipped` 이벤트가 생겼으므로
discard 0건이 관측되면 "버릴 게 없었다"와 "필터가 안 돌았다"를 이제 구분할 수 있다.
```

- [ ] **Step 5: 커밋한다**

```bash
git add docs/TODO_260729.md
git commit -m "docs: record the truncation propagation work and its effect on C1

A2 is closed. The subclass relationship means the five call sites that
propagate parse failures pick up the expanded retry without being touched,
which lowers how often A3 and A4 truncate -- their ceilings are still
uncalibrated, so both stay open.

C1 gains a precondition and a tool. D24 moves the claim funnel, so the
re-measurement sample has to come after this merge or the two effects mix.
And entailment_filter_skipped means a zero-discard result can finally be told
apart from a filter that never ran."
```

---

## 완료 기준

1. 세 fail-open 지점이 truncation과 쓰레기 응답을 구분해 다르게 처리한다 (Task 4·5·6).
2. 예산 clamp로 잘린 호출에서 확장 재시도가 발생하지 않는다 (Task 2, `test_budget_bound_truncation_does_not_retry`).
3. `truncation_handled`로 3가지 action이 사후 집계 가능하다 (Task 3).
4. `entailment_filter_skipped`로 C1의 n=0이 해석 가능하다 (Task 6·7).
5. D19 골든 게이트와 deep_analysis 테스트 전량이 green이다 (Task 1 Step 6, Task 8).
6. D24가 `DECISIONS.md`에 기록되어 있다 (Task 4 Step 5).
