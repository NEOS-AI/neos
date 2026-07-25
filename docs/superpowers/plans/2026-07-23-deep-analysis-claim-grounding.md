# Deep Analysis Claim Scope and Quote Grounding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen the deep-analysis worker prompt so generated claims use one verifiable institutional scope and contiguous verbatim evidence excerpts.

**Architecture:** Extend only the versioned `worker_brief` output contract. Keep the JSON schema, worker parser, repair path, graders, thresholds, discovery, model selection, and execution budgets unchanged so the next funnel sample remains comparable with the prior samples.

**Tech Stack:** Markdown prompt templates, Python 3.12, pytest, Ruff

## Global Constraints

- Change `worker_brief.md` from prompt version 2 to version 3.
- Do not change worker JSON fields or Python parsing interfaces.
- Do not add Python-side claim rewriting or evidence filtering.
- Do not change `_weaken_only()`, graders, thresholds, sampling, discovery, models, token caps, or wall-clock caps.
- Treat the follow-up 5+1 funnel run as evaluation after implementation, not as part of this code change.

---

### Task 1: Lock the Version 3 Grounding Contract with a Failing Test

**Files:**
- Modify: `tests/workflow/deep_analysis/test_prompt_loader.py`

**Interfaces:**
- Consumes: `render(name: str, **values) -> str` from `neos.workflow.deep_analysis.prompt_loader`
- Produces: A regression test defining the required version 3 worker prompt contract

- [ ] **Step 1: Replace the version 2 contract test with a version 3 test**

Replace `test_worker_brief_v2_calibrates_atomic_claims_and_confidence` with:

```python
def test_worker_brief_v3_scopes_claims_and_grounds_exact_quotes():
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

    assert "<!-- version: 3 -->" in output
    assert "한 기관·한 결론·한 비교축" in output
    assert "기관별로 별도 claim" in output
    assert "비교 대상과 비교 방향을 모두 직접 명시" in output
    assert "하나의 연속된 문자열" in output
    assert "번역·의역·생략 부호·분리된 문장 결합" in output
    assert "source_url의 fetch 원문에서 그대로 검색" in output
    assert "분리하거나 지지 범위로 좁히고" in output
    assert "지지되지 않는 나머지는 버린다" in output
    assert "고유 source_url" in output
    assert "1개 0.55" in output
    assert "2개 0.75" in output
    assert "3개 이상 0.9" in output
```

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/workflow/deep_analysis/test_prompt_loader.py::test_worker_brief_v3_scopes_claims_and_grounds_exact_quotes \
  -q -o log_cli=false --disable-warnings
```

Expected: FAIL because the current prompt is version 2 and does not contain the new institutional-scope and contiguous-quote rules.

---

### Task 2: Implement the Version 3 Prompt Contract

**Files:**
- Modify: `neos/workflow/deep_analysis/prompts/worker_brief.md`
- Test: `tests/workflow/deep_analysis/test_prompt_loader.py`

**Interfaces:**
- Consumes: The existing `worker_brief` placeholders rendered by the orchestrator
- Produces: The same rendered prompt and JSON output schema with stronger generation constraints

- [ ] **Step 1: Update the prompt version and grounding rules**

Change the version header to:

```markdown
<!-- version: 3 -->
```

Keep the existing rules and replace the two atomic/scope rules with the following block immediately after the `raw_ref` rule:

```markdown
- 각 claim은 독립적으로 검증 가능한 명제 하나만 담고 한 기관·한 결론·한 비교축으로 제한한다.
- 같은 주제를 다루더라도 서로 다른 기관의 결론은 기관별로 별도 claim에 쓴다.
- 비교 표현은 같은 excerpt가 비교 대상과 비교 방향을 모두 직접 명시할 때만 쓴다.
- excerpt는 해당 source_url의 fetch 원문에서 복사한 하나의 연속된 문자열이어야 한다.
  번역·의역·생략 부호·분리된 문장 결합을 하지 않는다.
- JSON 제출 전에 각 excerpt를 해당 source_url의 fetch 원문에서 그대로 검색해 일치함을 확인한다.
- 근거의 대상·시점·집단·조건·수치·비교 범위를 넓히지 않는다.
```

Replace the existing partial-support rule with:

```markdown
- 일부만 지지되는 복합 문장은 claim을 분리하거나 지지 범위로 좁히고,
  지지되지 않는 나머지는 버린다.
```

- [ ] **Step 2: Run the focused prompt tests and verify GREEN**

Run:

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/workflow/deep_analysis/test_prompt_loader.py \
  -q -o log_cli=false --disable-warnings
```

Expected: all prompt-loader tests PASS.

- [ ] **Step 3: Run prompt and worker regression tests**

Run:

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/workflow/deep_analysis/test_prompt_loader.py \
  tests/workflow/deep_analysis/test_worker.py \
  tests/workflow/deep_analysis/test_worker_repair.py \
  tests/workflow/deep_analysis/test_worker_discovery.py \
  -q -o log_cli=false --disable-warnings
```

Expected: all selected tests PASS with no failures.

- [ ] **Step 4: Run Ruff on the changed Python test**

Run:

```bash
.venv/bin/ruff check tests/workflow/deep_analysis/test_prompt_loader.py
```

Expected: `All checks passed!`

- [ ] **Step 5: Commit the prompt contract**

```bash
git add \
  neos/workflow/deep_analysis/prompts/worker_brief.md \
  tests/workflow/deep_analysis/test_prompt_loader.py
git commit -m "feat(deep-analysis): ground generated claims"
```

---

### Task 3: Verify the Deep-Analysis Regression Boundary

**Files:**
- Verify: `neos/workflow/deep_analysis/`
- Verify: `tests/workflow/deep_analysis/`

**Interfaces:**
- Consumes: The completed version 3 prompt change
- Produces: Fresh evidence that the unchanged deep-analysis interfaces still pass their regression suite

- [ ] **Step 1: Run the full deep-analysis test suite**

Run:

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/workflow/deep_analysis \
  -q -o log_cli=false --disable-warnings
```

Expected: all tests PASS. If the local PostgreSQL connection is blocked by the sandbox, rerun the identical command with local-network permission; do not treat the permission failure as a code failure.

- [ ] **Step 2: Run full deep-analysis Ruff**

Run:

```bash
.venv/bin/ruff check \
  neos/workflow/deep_analysis \
  tests/workflow/deep_analysis \
  scripts/deep_analysis_funnel_sample.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Verify scope and worktree integrity**

Run:

```bash
git diff --check
git status --short
git show --stat --oneline HEAD
```

Expected: no whitespace errors; the feature commit contains only the worker prompt and prompt-loader test; pre-existing user-owned changes remain unstaged.

---

### Task 4: Record the Implementation and Evaluation Handoff

**Files:**
- Modify: `docs/TODO_260729.md`

**Interfaces:**
- Consumes: The version 3 prompt commit and fresh regression results
- Produces: A durable record of the implementation boundary and the next 5+1 evaluation step

- [ ] **Step 1: Add the completed implementation note**

Under the current claim-grounding priority in `docs/TODO_260729.md`, record:

```markdown
**claim scope/exact-quote 생성 계약 구현 (2026-07-23):**
`worker_brief.md`를 v3로 올려 한 기관·한 결론·한 비교축, 기관별 claim 분리,
직접 지지되는 비교, 연속 verbatim excerpt, 제출 전 source_url 원문 대조,
부분 지지 복합문의 분리·축소·나머지 폐기 규칙을 추가했다.
worker JSON/parser, repair 경로, grader, threshold, sampling, discovery, 모델과
실행 상한은 변경하지 않았다. 다음 단계는 동일 `mixed-v1` 5+1 표본으로
overclaim과 quote mismatch가 줄었는지 평가하는 것이다.
```

Append the actual commit hash and test counts only after they are known.

- [ ] **Step 2: Verify the documentation diff**

Run:

```bash
git diff --check -- docs/TODO_260729.md
git diff -- docs/TODO_260729.md
```

Expected: the note accurately describes the implemented prompt-only scope and does not claim that the follow-up sample has already run.

- [ ] **Step 3: Commit the documentation**

```bash
git add docs/TODO_260729.md
git commit -m "docs: record claim grounding contract"
```

- [ ] **Step 4: Perform final verification**

Run:

```bash
git status --short
git log -3 --oneline --decorate
```

Expected: the two new commits are on `dev`; only pre-existing user-owned changes remain.
