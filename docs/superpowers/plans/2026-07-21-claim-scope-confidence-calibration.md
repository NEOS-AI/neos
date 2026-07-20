# Claim Scope and Confidence Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen deep-analysis claim prompts, clamp worker confidence to retained-source caps, and expose content-free aggregate clamp telemetry through the existing event/analytics/artifact pipeline.

**Architecture:** Render the configured confidence caps into worker prompt v2 and inject the same cap mapping into each stateless `Worker`. Normalize confidence only after unfetched evidence is discarded, carry aggregate counters on backward-compatible `WorkerResult` fields, sanitize them at the ledger event boundary, and aggregate them in `claim_funnel`. The deterministic grader remains an unchanged fail-closed backstop.

**Tech Stack:** Python 3.12, Markdown prompt templates, dataclasses, SQLAlchemy/PostgreSQL event ledger, pytest/pytest-asyncio, Ruff.

## Global Constraints

- Worker prompt version advances from `1` to `2`; all other prompt versions remain unchanged.
- Each claim is one independently verifiable, evidence-bounded proposition; association must not be promoted to causation.
- Confidence caps come from `settings.config.deep_analysis.confidence_cap`: zero sources `0.0`, one source configured key `1`, two sources key `2`, and three-plus sources key `3`.
- Clamp only after retaining evidence whose `source_url` was fetched; deduplicate source URLs before cap lookup.
- Persist only clamped confidence. Never persist or log requested confidence.
- Telemetry bucket keys are exactly `0`, `1`, `2`, and `3_plus`; counts are non-negative integers and booleans are invalid.
- Persisted and aggregated `confidence_clamped_count` is derived from sanitized bucket counts.
- Telemetry never contains claim text, source URLs, excerpts, blobs, repair text, requested confidence, or provider responses.
- Existing events and custom `WorkerResult` producers remain backward compatible with zero/default telemetry.
- Do not change deterministic/agentic grader behavior, thresholds, sampling, discovery, models, token caps, or wall-clock caps.
- Do not run the live Anthropic/Tavily evaluation as part of implementation.

---

## File Structure

- Modify `neos/workflow/deep_analysis/prompts/worker_brief.md`: prompt contract v2 and cap placeholders.
- Modify `neos/workflow/deep_analysis/orchestrator.py`: render configured caps into each worker brief.
- Modify `neos/workflow/deep_analysis/service.py`: inject configured cap mapping into each worker.
- Modify `neos/workflow/deep_analysis/worker.py`: retained-source normalization, counters, partial preservation, and weaken-only instructions.
- Modify `neos/workflow/deep_analysis/models.py`: backward-compatible `WorkerResult` telemetry fields.
- Modify `neos/workflow/deep_analysis/ledger.py`: sanitize and persist aggregate pass telemetry.
- Modify `neos/workflow/deep_analysis/analytics.py`: aggregate clamp buckets into `claim_funnel`.
- Modify `neos/workflow/deep_analysis/funnel_sample_runner.py`: recursively allowlist the new aggregate artifact fields.
- Modify focused tests under `tests/workflow/deep_analysis/` and update `docs/TODO_260729.md` after verification.

---

### Task 1: Prompt v2 and Configured Cap Rendering

**Files:**
- Modify: `neos/workflow/deep_analysis/prompts/worker_brief.md`
- Modify: `neos/workflow/deep_analysis/orchestrator.py:390-420`
- Modify: `tests/workflow/deep_analysis/test_prompt_loader.py`
- Modify: `tests/workflow/deep_analysis/test_orchestrator_unit.py`
- Modify: `tests/workflow/deep_analysis/test_golden_gate.py`

**Interfaces:**
- Consumes: `settings.config.deep_analysis.confidence_cap: dict[int, float]`.
- Produces: rendered placeholders `confidence_cap_one`, `confidence_cap_two`, and `confidence_cap_three_plus` in `worker_brief` version 2.

- [ ] **Step 1: Write failing prompt-contract tests**

Add assertions that the rendered worker brief contains atomic-claim, scope,
association-versus-causation, unique-attached-source, and configured-cap rules.

```python
def test_worker_brief_v2_calibrates_atomic_claims_and_confidence():
    output = render(
        "worker_brief",
        question_text="q",
        verified_summaries="none",
        dead_ends="none",
        repair_count=0,
        repairs="none",
        token_cap=2000,
        confidence_cap_one=0.55,
        confidence_cap_two=0.75,
        confidence_cap_three_plus=0.9,
        fetched_evidence="<evidence>source</evidence>",
    )
    assert "독립적으로 검증 가능한 명제 하나" in output
    assert "상관관계" in output and "인과" in output
    assert "고유 source_url" in output
    assert "1개 0.55" in output
    assert "2개 0.75" in output
    assert "3개 이상 0.9" in output
```

Update the golden gate expectation to `"worker_brief": 2`; before changing the
prompt, add an assertion that the current prompt version is still 1 so the RED
run proves the version/content checkpoint.

- [ ] **Step 2: Run prompt tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_prompt_loader.py tests/workflow/deep_analysis/test_golden_gate.py -q`

Expected: the new content/version assertions fail against worker prompt v1.

- [ ] **Step 3: Implement prompt v2**

Change the header to `<!-- version: 2 -->`. Keep the JSON schema unchanged.
Replace the existing confidence bullet with placeholders and add concise rules:

```markdown
- 각 claim은 독립적으로 검증 가능한 명제 하나만 담는다.
- 근거의 대상·시점·집단·조건·수치·비교 범위를 넓히지 않는다.
- 관찰·상관 근거를 인과 주장으로 바꾸지 않는다.
- 최종 evidence의 고유 source_url 수를 센 뒤 confidence를 정한다.
- confidence 상한은 0개 0.0, 1개 {confidence_cap_one},
  2개 {confidence_cap_two}, 3개 이상 {confidence_cap_three_plus}다.
- 일부만 지지되는 복합 문장은 claim을 분리하거나 지지 범위로 좁힌다.
```

- [ ] **Step 4: Render caps from orchestrator configuration**

Extend the existing `render("worker_brief", ...)` call:

```python
confidence_cap_one=config.confidence_cap[1],
confidence_cap_two=config.confidence_cap[2],
confidence_cap_three_plus=config.confidence_cap[3],
```

Add an orchestrator unit assertion using non-default caps and inspect the
assignment brief passed to the fake worker. This proves the prompt does not
silently hardcode defaults.

- [ ] **Step 5: Verify and commit Task 1**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_prompt_loader.py tests/workflow/deep_analysis/test_golden_gate.py tests/workflow/deep_analysis/test_orchestrator_unit.py -q`

Run: `/opt/homebrew/bin/uv run --frozen ruff check neos/workflow/deep_analysis/orchestrator.py tests/workflow/deep_analysis/test_prompt_loader.py tests/workflow/deep_analysis/test_orchestrator_unit.py tests/workflow/deep_analysis/test_golden_gate.py`

Expected: all tests and Ruff pass.

```bash
git add neos/workflow/deep_analysis/prompts/worker_brief.md neos/workflow/deep_analysis/orchestrator.py tests/workflow/deep_analysis/test_prompt_loader.py tests/workflow/deep_analysis/test_orchestrator_unit.py tests/workflow/deep_analysis/test_golden_gate.py
git commit -m "feat(deep-analysis): calibrate claim generation prompt"
```

---

### Task 2: Retained-Source Confidence Clamp and Worker Telemetry

**Files:**
- Modify: `neos/workflow/deep_analysis/models.py:55-72`
- Modify: `neos/workflow/deep_analysis/worker.py:25-365`
- Modify: `neos/workflow/deep_analysis/service.py:75-92`
- Modify: `tests/workflow/deep_analysis/test_worker.py`
- Modify: `tests/workflow/deep_analysis/test_service.py`

**Interfaces:**
- Consumes: `Worker(..., confidence_cap: dict[int, float] | None = None)`; default resolves from `settings.config.deep_analysis.confidence_cap`.
- Produces: `WorkerResult.confidence_clamped_count: int` and `WorkerResult.confidence_clamped_by_source_count: dict[str, int]`.

- [ ] **Step 1: Write failing cap-helper and parsing tests**

Parameterize retained unique-source counts and expected caps:

```python
@pytest.mark.parametrize(
    ("urls", "requested", "expected", "bucket"),
    [
        ([], 0.9, 0.0, "0"),
        (["a"], 0.9, 0.6, "1"),
        (["a", "b"], 0.9, 0.8, "2"),
        (["a", "b", "c"], 1.0, 0.95, "3_plus"),
        (["a", "a"], 0.7, 0.6, "1"),
    ],
)
async def test_worker_clamps_after_retained_unique_sources(
    urls, requested, expected, bucket
):
    result = await worker_result_for(urls, requested)
    assert result.claims[0].confidence == expected
    assert result.confidence_clamped_count == 1
    assert result.confidence_clamped_by_source_count[bucket] == 1
```

Add a no-clamp boundary case (`requested == cap`) and update the existing
invented-source test to expect confidence `0.0`, bucket `0`, count `1` after the
unfetched URL is removed.

- [ ] **Step 2: Run worker tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_worker.py -q`

Expected: confidence remains bounded only to `[0, 1]` and telemetry fields do
not exist.

- [ ] **Step 3: Add backward-compatible result fields and helper**

```python
@dataclass
class WorkerResult:
    # existing fields unchanged
    confidence_clamped_count: int = 0
    confidence_clamped_by_source_count: dict[str, int] = field(
        default_factory=dict
    )
```

In `worker.py`, define exact allowed buckets and a helper:

```python
_CLAMP_BUCKETS = ("0", "1", "2", "3_plus")


def _source_bucket(count: int) -> str:
    return str(count) if count < 3 else "3_plus"


def _confidence_limit(source_count: int, caps: dict[int, float]) -> float:
    if source_count == 0:
        return 0.0
    return caps[3 if source_count >= 3 else source_count]
```

The worker constructor copies the supplied/default cap mapping and initializes
private counters. Reset counters at the start of `_investigate`; after retained
evidence is built, bound requested confidence to `[0, 1]`, compute distinct
URLs, clamp to the helper limit, and increment one bucket only when requested
exceeds the cap.

- [ ] **Step 4: Preserve telemetry in completed and partial results**

Add the two fields to both `WorkerResult(...)` return sites and
`flush_partial()`. After one completed parse with a clamp, call
`flush_partial()` and assert that its counters equal the completed result.
Separately, start a new investigation and assert prior counters are reset; the
existing pre-parse `TokenBudgetExhausted` path must return zero counters.

- [ ] **Step 5: Strengthen weaken-only scope instructions**

Extend the existing inline weaken prompt with exact behavioral checks while
retaining the no-search/no-fetch path and existing JSON shape:

```text
근거가 지지하는 날짜·집단·조건·수치 범위를 유지하라.
상관 근거에는 인과 표현을 쓰지 말고, 지지되지 않는 비교를 제거하라.
근거 수준으로 약화할 수 없으면 action=abandoned로 반환하라.
```

Update `_weaken_only` parsing to accept `action` from the existing allowed
repair action set rather than forcing every item to `weakened`; default remains
`weakened`. Add tests proving the prompt text, no search/fetch, and an explicit
`abandoned` response.

- [ ] **Step 6: Inject the same caps from service wiring**

Add `"confidence_cap": config.confidence_cap` to `worker_factory()` options.
Update service tests to assert custom configured caps reach `Worker` without
changing grader construction.

- [ ] **Step 7: Verify and commit Task 2**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_worker.py tests/workflow/deep_analysis/test_service.py -q`

Run: `/opt/homebrew/bin/uv run --frozen ruff check neos/workflow/deep_analysis/models.py neos/workflow/deep_analysis/worker.py neos/workflow/deep_analysis/service.py tests/workflow/deep_analysis/test_worker.py tests/workflow/deep_analysis/test_service.py`

Expected: all tests and Ruff pass.

```bash
git add neos/workflow/deep_analysis/models.py neos/workflow/deep_analysis/worker.py neos/workflow/deep_analysis/service.py tests/workflow/deep_analysis/test_worker.py tests/workflow/deep_analysis/test_service.py
git commit -m "feat(deep-analysis): clamp worker claim confidence"
```

---

### Task 3: Safe Ledger, Analytics, and Artifact Telemetry

**Files:**
- Modify: `neos/workflow/deep_analysis/ledger.py:715-785`
- Modify: `neos/workflow/deep_analysis/analytics.py:140-280`
- Modify: `neos/workflow/deep_analysis/funnel_sample_runner.py:45-145`
- Modify: `tests/workflow/deep_analysis/test_ledger.py`
- Modify: `tests/workflow/deep_analysis/test_deep_analysis_analytics.py`
- Modify: `tests/workflow/deep_analysis/test_funnel_sample_runner.py`

**Interfaces:**
- Consumes: the two `WorkerResult` telemetry fields from Task 2.
- Produces: safe `pass_completed` payload fields and `claim_funnel.confidence_clamped_count` plus `claim_funnel.confidence_clamped_by_source_count`.

- [ ] **Step 1: Write failing ledger allowlist tests**

Construct a custom `WorkerResult` containing valid buckets plus unknown,
negative, boolean, and inconsistent total values. After `commit_pass`, read the
`pass_completed` payload and assert:

```python
assert payload["confidence_clamped_by_source_count"] == {
    "0": 1, "1": 2, "2": 0, "3_plus": 3
}
assert payload["confidence_clamped_count"] == 6
assert "unknown" not in payload["confidence_clamped_by_source_count"]
assert "requested_confidence" not in json.dumps(payload)
```

Invalid known bucket values normalize to zero. The declared custom total is
ignored and recomputed from sanitized buckets.

- [ ] **Step 2: Run ledger test and verify RED**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_ledger.py -q -o log_cli=false --disable-warnings`

Expected: pass payload lacks clamp telemetry.

- [ ] **Step 3: Implement ledger sanitization**

```python
_CONFIDENCE_CLAMP_BUCKETS = ("0", "1", "2", "3_plus")


def _safe_clamp_counts(raw: object) -> dict[str, int]:
    values = raw if isinstance(raw, dict) else {}
    return {
        key: value
        if isinstance((value := values.get(key, 0)), int)
        and not isinstance(value, bool)
        and value >= 0
        else 0
        for key in _CONFIDENCE_CLAMP_BUCKETS
    }
```

Before logging `pass_completed`, sanitize `result.confidence_clamped_by_source_count`,
derive the total with `sum()`, and add both fields. Do not read or persist the
custom total.

- [ ] **Step 4: Write failing analytics compatibility tests**

Seed valid, malformed, legacy, and unknown-key `pass_completed` events. Assert
legacy pass metrics still aggregate while clamp telemetry uses only four valid
integer buckets and derives its total:

```python
assert funnel["confidence_clamped_count"] == 7
assert funnel["confidence_clamped_by_source_count"] == {
    "0": 1, "1": 2, "2": 1, "3_plus": 3
}
```

An invalid known bucket makes only that bucket contribute zero; malformed JSON
continues to count in raw totals but contributes no payload metrics.

- [ ] **Step 5: Implement analytics aggregation**

Initialize the total and four zero buckets in `claim_funnel`. In the existing
`pass_completed` branch, parse `confidence_clamped_by_source_count` defensively,
add valid known values, and after the event loop derive
`confidence_clamped_count` from the accumulated buckets. Do not trust a payload
total or accept booleans.

- [ ] **Step 6: Extend artifact recursive allowlist**

Add `confidence_clamped_count` to `_FUNNEL_FIELDS`. Handle
`confidence_clamped_by_source_count` like quote buckets with the exact four
keys and `_is_safe_number`, but require integer/non-boolean values. Add an
adversarial artifact test containing extra keys, negative values, URLs, and
requested confidence; only safe aggregates may appear in JSON/Markdown.

- [ ] **Step 7: Verify and commit Task 3**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_ledger.py tests/workflow/deep_analysis/test_deep_analysis_analytics.py tests/workflow/deep_analysis/test_funnel_sample_runner.py -q -o log_cli=false --disable-warnings`

Run: `/opt/homebrew/bin/uv run --frozen ruff check neos/workflow/deep_analysis/ledger.py neos/workflow/deep_analysis/analytics.py neos/workflow/deep_analysis/funnel_sample_runner.py tests/workflow/deep_analysis/test_ledger.py tests/workflow/deep_analysis/test_deep_analysis_analytics.py tests/workflow/deep_analysis/test_funnel_sample_runner.py`

Expected: all tests and Ruff pass.

```bash
git add neos/workflow/deep_analysis/ledger.py neos/workflow/deep_analysis/analytics.py neos/workflow/deep_analysis/funnel_sample_runner.py tests/workflow/deep_analysis/test_ledger.py tests/workflow/deep_analysis/test_deep_analysis_analytics.py tests/workflow/deep_analysis/test_funnel_sample_runner.py
git commit -m "feat(deep-analysis): aggregate confidence clamp telemetry"
```

---

### Task 4: Focused Regression and TODO Handoff

**Files:**
- Modify: `docs/TODO_260729.md`
- Test: focused workflow files changed in Tasks 1-3

**Interfaces:**
- Consumes: completed prompt, worker, ledger, analytics, and artifact changes.
- Produces: verified implementation evidence and a documented manual rerun handoff; no live provider execution.

- [ ] **Step 1: Run the focused no-provider regression**

Run:

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/workflow/deep_analysis/test_prompt_loader.py \
  tests/workflow/deep_analysis/test_golden_gate.py \
  tests/workflow/deep_analysis/test_worker.py \
  tests/workflow/deep_analysis/test_service.py \
  tests/workflow/deep_analysis/test_orchestrator_unit.py \
  tests/workflow/deep_analysis/test_ledger.py \
  tests/workflow/deep_analysis/test_deep_analysis_analytics.py \
  tests/workflow/deep_analysis/test_funnel_sample_runner.py \
  -q -o log_cli=false --disable-warnings
```

Expected: all tests pass with no provider calls.

- [ ] **Step 2: Run adjacent deep-analysis regressions**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_deterministic_grader.py tests/workflow/deep_analysis/test_orchestrator_m3.py tests/workflow/deep_analysis/test_orchestrator_m3_integration.py tests/workflow/deep_analysis/test_golden_integration.py -q -o log_cli=false --disable-warnings`

Expected: confidence grader behavior, repairs, ledger transitions, and golden replay pass unchanged.

- [ ] **Step 3: Run Ruff and diff checks**

Run: `/opt/homebrew/bin/uv run --frozen ruff check neos/workflow/deep_analysis tests/workflow/deep_analysis scripts/deep_analysis_funnel_sample.py`

Run: `git diff --check && git status --short`

Expected: Ruff and diff checks pass; only the intended TODO edit and pre-existing user changes are visible.

- [ ] **Step 4: Update the TODO**

Below the 2026-07-20 production baseline, record:

- prompt contract v2 and configured cap rendering;
- retained-source parser clamp and safe aggregate telemetry;
- focused/adjacent test counts and implementation commit hashes;
- no threshold, grader, sampling, discovery, model, or budget change;
- the previous `mixed-v1` baseline remains the comparison point;
- the next action is a user-run manual `mixed-v1` 5+1 evaluation, after which
  clamp counts and rejection-code/verified-rate deltas should be documented.

Do not claim verified-ratio improvement until that comparison exists.

- [ ] **Step 5: Commit the documentation handoff**

```bash
git add docs/TODO_260729.md
git commit -m "docs: record confidence calibration implementation"
```

- [ ] **Step 6: Final verification**

Re-run the focused command from Step 1 and the changed-file Ruff command. Read
the complete outputs and confirm zero failures before requesting final review
or local merge.
