# Deep Analysis Discard Recall Measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every claim that entailment discards, then score those claims offline through the existing graders to measure how often entailment removes output the pipeline would have accepted.

**Architecture:** Two phases that never share a process. Phase 1 threads discarded claims up from the pure entailment module through `WorkerResult` to the orchestrator, which writes one append-only `claim_discarded` event per discard at zero token cost. Phase 2 is a separate script that reads those events, rebuilds each `ProposedClaim` from evidence blobs still in the ledger, grades them exhaustively, and writes an ignored artifact with a false-discard rate and Wilson interval.

**Tech Stack:** Python 3.12, pytest, Ruff, SQLAlchemy async, PostgreSQL, existing deep-analysis grader/ledger/cassette infrastructure.

**Design spec:** `docs/superpowers/specs/2026-07-27-deep-analysis-discard-recall-design.md` (written in Korean; this plan is self-contained and does not require reading it).

## Global Constraints

- **Measurement only.** Do not change entailment behaviour, grader thresholds, sampling, discovery width, prompts, models, token limits, worker/depth/wall-clock caps, or repair behaviour.
- **`deep_analysis_events` is append-only** (D8, §11.3). Only ever add new event rows. Never update or delete.
- **No magic numbers.** Every threshold lives in `neos/config/schema.py`. This includes the Wilson `z` value and both stopping-rule bounds.
- **No live LLM or network in tests.** Use fakes or cassette replay only.
- **`judge != worker`.** Phase 2 uses the configured judge model via the existing `AgenticGrader`; do not point it at the worker model.
- **Fail-open semantics of `apply_entailment_results` must not change.** Returning `None` still means "validation failed, keep the original batch" — and in that case **no discard is recorded**, because nothing was discarded.
- **`narrow` is not `discard`.** A narrowed claim survives and must never appear in the discarded list.
- Artifacts go to `artifacts/deep-analysis-discard-recall/<UTC timestamp>/` and are **never committed**. Add the directory to `.gitignore`.
- Never print, persist, or commit credential values. Boolean presence only.
- Test command: `HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest ... -q -o log_cli=false --disable-warnings`. Bare `pytest` fails asyncio marker collection.

## Out of Scope

Executing the live measurement run and interpreting its numbers. That gets its own plan after this one lands, following the pattern of `2026-07-25-deep-analysis-entailment-evaluation.md`. This plan delivers only the instrumentation and the scoring tool.

## File Structure

| File | Responsibility |
|---|---|
| `neos/workflow/deep_analysis/models.py` | Add `EntailmentOutcome` dataclass; add `discarded_claims` to `WorkerResult` |
| `neos/workflow/deep_analysis/claim_entailment.py` | Collect discards instead of dropping them |
| `neos/workflow/deep_analysis/worker.py` | Carry discards from `_refine_claims` onto both `WorkerResult` exits |
| `neos/workflow/deep_analysis/orchestrator.py` | Emit one `claim_discarded` event per discard |
| `neos/config/schema.py` | `DeepAnalysisDiscardRecallConfig` — Wilson z and stopping bounds |
| `neos/workflow/deep_analysis/discard_recall.py` | **New.** Pure: event→claim reconstruction, Wilson interval, rate, stopping verdict |
| `scripts/deep_analysis_discard_recall.py` | **New.** Phase 2 CLI: query events, grade, write artifact |
| `neos/workflow/deep_analysis/funnel_sample_runner.py` | Cassette recording + manifest execution receipt and config fingerprint |

---

### Task 1: Return discarded claims from the pure entailment module

**Files:**
- Modify: `neos/workflow/deep_analysis/models.py`
- Modify: `neos/workflow/deep_analysis/claim_entailment.py:58-73`
- Test: `tests/workflow/deep_analysis/test_claim_entailment.py`

**Interfaces:**
- Produces: `EntailmentOutcome(refined: list[ProposedClaim], discarded: list[ProposedClaim])` in `neos.workflow.deep_analysis.models`.
- Produces: `apply_entailment_results(claims, payload) -> EntailmentOutcome | None`. `None` keeps its existing meaning (validation failure, caller falls back to the original batch).

- [ ] **Step 1: Write the failing test**

Add to `tests/workflow/deep_analysis/test_claim_entailment.py`:

```python
def test_apply_entailment_results_reports_discarded_claims():
    claims = _claims()

    result = apply_entailment_results(
        claims,
        {
            "results": [
                {"index": 0, "action": "keep"},
                {
                    "index": 1,
                    "action": "narrow",
                    "new_text": "supported qualifier",
                },
                {"index": 2, "action": "discard"},
            ]
        },
    )

    assert result is not None
    assert [claim.text for claim in result.refined] == [
        "keep me",
        "supported qualifier",
    ]
    # narrow survives and must never be reported as discarded
    assert [claim.text for claim in result.discarded] == ["discard me"]
    assert result.discarded[0] is claims[2]


def test_apply_entailment_results_discards_nothing_when_validation_fails():
    claims = _claims()

    result = apply_entailment_results(claims, {"results": []})

    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_claim_entailment.py -q \
  -o log_cli=false --disable-warnings
```
Expected: FAIL — `AttributeError: 'list' object has no attribute 'refined'`.

- [ ] **Step 3: Add the `EntailmentOutcome` dataclass**

In `neos/workflow/deep_analysis/models.py`, immediately after the `ProposedClaim` definition (which ends at line 47):

```python
@dataclass
class EntailmentOutcome:
    """Result of applying one entailment batch.

    ``discarded`` carries the claims the batch dropped so the orchestrator can
    record them. A ``narrow`` action is not a discard — the narrowed claim
    appears in ``refined``.
    """

    refined: list[ProposedClaim] = field(default_factory=list)
    discarded: list[ProposedClaim] = field(default_factory=list)
```

- [ ] **Step 4: Collect discards instead of dropping them**

In `neos/workflow/deep_analysis/claim_entailment.py`, change the import on line 7 and replace the final block (lines 58-73):

```python
from .models import EntailmentOutcome, ProposedClaim
```

```python
    refined: list[ProposedClaim] = []
    discarded: list[ProposedClaim] = []
    for index, claim in enumerate(claims):
        action, new_text = by_index[index]
        if action == "discard":
            discarded.append(claim)
            continue
        if action == "keep":
            refined.append(claim)
            continue
        refined.append(
            ProposedClaim(
                text=new_text or "",
                confidence=claim.confidence,
                evidence=claim.evidence,
            )
        )
    return EntailmentOutcome(refined=refined, discarded=discarded)
```

Also update the return annotation on line 15 to `-> EntailmentOutcome | None`.

- [ ] **Step 5: Update the pre-existing test that indexes the return value**

`test_apply_entailment_results_keeps_narrows_and_discards_atomically` currently treats the result as a list. Change its three assertions (lines 49-55) to read from `.refined`:

```python
    assert [claim.text for claim in result.refined] == [
        "keep me",
        "supported qualifier",
    ]
    assert result.refined[0] is claims[0]
    assert result.refined[1].confidence == claims[1].confidence
    assert result.refined[1].evidence is claims[1].evidence
```

The two `rejects_*` tests assert `result is None` and need no change.

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_claim_entailment.py -q \
  -o log_cli=false --disable-warnings
```
Expected: PASS, all tests in the file.

- [ ] **Step 7: Commit**

```bash
git add neos/workflow/deep_analysis/models.py \
        neos/workflow/deep_analysis/claim_entailment.py \
        tests/workflow/deep_analysis/test_claim_entailment.py
git commit -m "feat(deep-analysis): report entailment-discarded claims"
```

---

### Task 2: Carry discarded claims onto `WorkerResult`

**Files:**
- Modify: `neos/workflow/deep_analysis/models.py` (`WorkerResult`, line 59)
- Modify: `neos/workflow/deep_analysis/worker.py:73-77, 79-85, 171-172, 308, 330-380`
- Test: `tests/workflow/deep_analysis/test_worker_entailment.py`

**Interfaces:**
- Consumes: `EntailmentOutcome` from Task 1.
- Produces: `WorkerResult.discarded_claims: list[ProposedClaim]`, defaulting to `[]`. Populated on both the completed path and the `flush_partial` path.

- [ ] **Step 1: Write the failing test**

Add to `tests/workflow/deep_analysis/test_worker_entailment.py`. The file already
defines every helper these tests need: `Search`, `Fetch`, and `ScriptedLLM`
(whose first scripted response proposes exactly three claims — `"keep"`,
`"broad"`, `"drop"`). The worker entry point is `investigate`, not `run`.

```python
@pytest.mark.asyncio
async def test_worker_result_carries_discarded_claims():
    llm = ScriptedLLM(
        json.dumps(
            {
                "results": [
                    {"index": 0, "action": "keep"},
                    {
                        "index": 1,
                        "action": "narrow",
                        "new_text": "narrow",
                    },
                    {"index": 2, "action": "discard"},
                ]
            }
        )
    )

    result = await Worker(
        Search(), fetch_fn=Fetch(), llm_client=llm
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    # narrow survives in claims and must not be reported as discarded
    assert [claim.text for claim in result.claims] == ["keep", "narrow"]
    assert [claim.text for claim in result.discarded_claims] == ["drop"]
    # evidence must survive so phase 2 can re-grade the claim
    assert result.discarded_claims[0].evidence[0].raw_ref == "0123456789abcdef"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entailment",
    [
        "not json",
        '{"results":[{"index":0,"action":"keep"}]}',
    ],
)
async def test_worker_records_no_discards_when_entailment_fails_open(
    entailment,
):
    result = await Worker(
        Search(),
        fetch_fn=Fetch(),
        llm_client=ScriptedLLM(entailment),
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    assert [claim.text for claim in result.claims] == ["keep", "broad", "drop"]
    assert result.discarded_claims == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_worker_entailment.py -q \
  -o log_cli=false --disable-warnings
```
Expected: FAIL — `AttributeError: 'WorkerResult' object has no attribute 'discarded_claims'`.

- [ ] **Step 3: Add the field to `WorkerResult`**

In `neos/workflow/deep_analysis/models.py`, add to `WorkerResult` after `claims` (line 62):

```python
    discarded_claims: list[ProposedClaim] = field(default_factory=list)
```

- [ ] **Step 4: Track discards as worker instance state**

In `neos/workflow/deep_analysis/worker.py`, add beside `self._claims` in `__init__` (line 73):

```python
        self._discarded_claims: list[ProposedClaim] = []
```

And reset it beside the per-run reset at line 171:

```python
        self._claims = []
        self._discarded_claims = []
        self._blobs = []
```

- [ ] **Step 5: Populate discards in `_refine_claims`**

Replace lines 376-380 of `neos/workflow/deep_analysis/worker.py`:

```python
        outcome = apply_entailment_results(claims, payload)
        if outcome is None:
            logger.warning("Claim entailment response failed validation")
            return claims
        self._discarded_claims = list(outcome.discarded)
        return outcome.refined
```

Every earlier `return claims` in this method is a fail-open path and must leave `self._discarded_claims` empty — do not touch those branches.

- [ ] **Step 6: Emit discards on both `WorkerResult` exits**

Add to the completed-path `WorkerResult` (line 308) and to `flush_partial` (line 79):

```python
            discarded_claims=list(self._discarded_claims),
```

Leave the third `WorkerResult` construction (line 480) alone — it is a failure path that never ran entailment, and the default `[]` is correct.

- [ ] **Step 7: Run tests to verify they pass**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_worker_entailment.py \
  tests/workflow/deep_analysis/test_claim_entailment.py -q \
  -o log_cli=false --disable-warnings
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add neos/workflow/deep_analysis/models.py \
        neos/workflow/deep_analysis/worker.py \
        tests/workflow/deep_analysis/test_worker_entailment.py
git commit -m "feat(deep-analysis): carry discarded claims on worker result"
```

---

### Task 3: Emit `claim_discarded` events from the orchestrator

**Files:**
- Modify: `neos/workflow/deep_analysis/orchestrator.py:647-661`
- Test: `tests/workflow/deep_analysis/test_orchestrator_discard_events.py` (create)

**Interfaces:**
- Consumes: `WorkerResult.discarded_claims` from Task 2.
- Produces: `deep_analysis_events` rows with `kind="claim_discarded"`, `qid=<question_id>`, and this payload shape, which Task 4 parses:

```json
{
  "text": "...",
  "confidence": 0.7,
  "value_est": 1.0,
  "evidence": [{"source_url": "...", "excerpt": "...", "raw_ref": "..."}]
}
```

- [ ] **Step 1: Write the failing test**

Create `tests/workflow/deep_analysis/test_orchestrator_discard_events.py`.

This test needs a real `Ledger` on a DB session, a fake worker, and the small
grader/synthesizer stubs. `tests/workflow/deep_analysis/test_orchestrator_m4_integration.py`
already defines a working set of those stubs (`OkDet`, `OkReportGrader`,
`_decompose_one`, `SimpleWorker`) against the same `Orchestrator(...)`
constructor. **Copy those stubs verbatim into the new file** rather than
importing across test modules, then add the fake worker and assertions below.

A fake worker is any object with `investigate` and `flush_partial`; it returns
a `WorkerResult` directly, so it can populate `discarded_claims` without going
near entailment.

```python
import json

import pytest
from sqlalchemy import select

import neos.database.models  # noqa: F401 - register Base metadata / FK targets
from neos.database.connection import db_manager
from neos.database.deep_analysis_models import DAEvent
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import (
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    WorkerResult,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator


def _evidence():
    return [
        ProposedEvidence(
            "https://example.com/source",
            "Direct evidence.",
            "a" * 16,
        )
    ]


class DiscardWorker:
    """One completed pass: one surviving claim, two discarded."""

    def __init__(self, discarded=2):
        self.discarded = discarded

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
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


async def _discard_events(session, run_id):
    rows = await session.execute(
        select(DAEvent.qid, DAEvent.payload).where(
            DAEvent.run_id == run_id,
            DAEvent.kind == "claim_discarded",
        )
    )
    return rows.all()


@pytest.mark.asyncio
async def test_orchestrator_logs_one_event_per_discarded_claim():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        orch = Orchestrator(
            session,
            run_id,
            lambda: DiscardWorker(discarded=2),
            OkDet(),
            ledger=ledger,
            report_grader=OkReportGrader(),
            decompose_fn=_decompose_one,
            global_token_cap=5000,
        )
        await orch.run()

        events = await _discard_events(session, run_id)

    assert len(events) == 2
    payloads = sorted(json.loads(payload) for _, payload in events)
    assert [item["text"] for item in payloads] == [
        "discarded 0",
        "discarded 1",
    ]
    assert payloads[0]["confidence"] == 0.6
    assert payloads[0]["value_est"] == 1.0
    assert payloads[0]["evidence"] == [
        {
            "source_url": "https://example.com/source",
            "excerpt": "Direct evidence.",
            "raw_ref": "a" * 16,
        }
    ]
    assert all(qid for qid, _ in events)


@pytest.mark.asyncio
async def test_orchestrator_logs_no_event_when_nothing_discarded():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        orch = Orchestrator(
            session,
            run_id,
            lambda: DiscardWorker(discarded=0),
            OkDet(),
            ledger=ledger,
            report_grader=OkReportGrader(),
            decompose_fn=_decompose_one,
            global_token_cap=5000,
        )
        await orch.run()

        events = await _discard_events(session, run_id)

    assert events == []
```

If the copied stub set needs a synthesizer to complete a `run()`, copy the
`Synthesizer(...)` construction from the same source file as well — the
assertions above only care about `claim_discarded` rows, so any stub that lets
the run finish is acceptable.

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_orchestrator_discard_events.py -q \
  -o log_cli=false --disable-warnings
```
Expected: FAIL — zero `claim_discarded` events found.

- [ ] **Step 3: Log the events**

In `neos/workflow/deep_analysis/orchestrator.py`, insert immediately after `await self.ledger.commit_blobs(result.blobs)` (line 656) and before the `verdicts = {}` block. `value_est` is already in scope from line 647.

```python
            # Recall measurement: entailment drops claims before grading, so
            # they never reach the claims table. Record them here — blobs are
            # already committed above, so phase 2 can re-grade offline.
            for discarded in result.discarded_claims:
                await self.ledger.log(
                    "claim_discarded",
                    result.question_id,
                    {
                        "text": discarded.text,
                        "confidence": discarded.confidence,
                        "value_est": value_est,
                        "evidence": [
                            {
                                "source_url": evidence.source_url,
                                "excerpt": evidence.excerpt,
                                "raw_ref": evidence.raw_ref,
                            }
                            for evidence in discarded.evidence
                        ],
                    },
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_orchestrator_discard_events.py -q \
  -o log_cli=false --disable-warnings
```
Expected: PASS.

- [ ] **Step 5: Run the full deep-analysis suite for regressions**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/ -q -o log_cli=false --disable-warnings
```
Expected: PASS. Baseline before this plan was **353 passed**; expect that plus the new tests.

- [ ] **Step 6: Commit**

```bash
git add neos/workflow/deep_analysis/orchestrator.py \
        tests/workflow/deep_analysis/test_orchestrator_discard_events.py
git commit -m "feat(deep-analysis): record discarded claims as ledger events"
```

---

### Task 4: Pure discard-recall metrics module

**Files:**
- Modify: `neos/config/schema.py:633-639`
- Create: `neos/workflow/deep_analysis/discard_recall.py`
- Test: `tests/workflow/deep_analysis/test_discard_recall.py` (create)

**Interfaces:**
- Consumes: the `claim_discarded` payload shape from Task 3.
- Produces, all pure and DB-free:
  - `claim_from_event(payload: dict) -> ProposedClaim | None`
  - `value_est_from_event(payload: dict) -> float | None`
  - `wilson_interval(successes: int, total: int, z: float) -> tuple[float, float]`
  - `false_discard_rate(verified: int, total: int) -> float`
  - `stopping_verdict(low: float, high: float, *, safe_upper: float, over_discard_lower: float) -> str` returning `"safe"`, `"over_discarding"`, or `"inconclusive"`
- Produces: `settings.config.deep_analysis.discard_recall` with `wilson_z`, `safe_upper_bound`, `over_discard_lower_bound`.

- [ ] **Step 1: Write the failing test**

Create `tests/workflow/deep_analysis/test_discard_recall.py`:

```python
import pytest

from neos.workflow.deep_analysis.discard_recall import (
    claim_from_event,
    false_discard_rate,
    stopping_verdict,
    value_est_from_event,
    wilson_interval,
)


pytestmark = pytest.mark.no_db


def _payload():
    return {
        "text": "discarded claim",
        "confidence": 0.6,
        "value_est": 1.0,
        "evidence": [
            {
                "source_url": "https://example.com/source",
                "excerpt": "Direct evidence.",
                "raw_ref": "0123456789abcdef",
            }
        ],
    }


def test_claim_from_event_rebuilds_claim_with_evidence():
    claim = claim_from_event(_payload())

    assert claim is not None
    assert claim.text == "discarded claim"
    assert claim.confidence == 0.6
    assert len(claim.evidence) == 1
    assert claim.evidence[0].raw_ref == "0123456789abcdef"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("text"),
        lambda p: p.update({"text": "   "}),
        lambda p: p.update({"confidence": "high"}),
        lambda p: p.update({"evidence": "not-a-list"}),
        lambda p: p.update({"evidence": [{"source_url": "u"}]}),
    ],
)
def test_claim_from_event_rejects_malformed_payload(mutate):
    payload = _payload()
    mutate(payload)

    assert claim_from_event(payload) is None


def test_value_est_from_event():
    assert value_est_from_event(_payload()) == 1.0
    assert value_est_from_event({"value_est": "x"}) is None


def test_wilson_interval_matches_known_values():
    low, high = wilson_interval(19, 38, 1.96)

    assert round(low * 100, 1) == 34.8
    assert round(high * 100, 1) == 65.2


def test_wilson_interval_handles_empty_denominator():
    assert wilson_interval(0, 0, 1.96) == (0.0, 0.0)


def test_false_discard_rate():
    assert false_discard_rate(3, 12) == 0.25
    assert false_discard_rate(0, 0) == 0.0


def test_stopping_verdict_applies_preregistered_rule():
    assert (
        stopping_verdict(0.0, 0.08, safe_upper=0.10, over_discard_lower=0.40)
        == "safe"
    )
    assert (
        stopping_verdict(0.45, 0.80, safe_upper=0.10, over_discard_lower=0.40)
        == "over_discarding"
    )
    assert (
        stopping_verdict(0.05, 0.60, safe_upper=0.10, over_discard_lower=0.40)
        == "inconclusive"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_discard_recall.py -q \
  -o log_cli=false --disable-warnings
```
Expected: FAIL — `ModuleNotFoundError: neos.workflow.deep_analysis.discard_recall`.

- [ ] **Step 3: Add the config block**

In `neos/config/schema.py`, add before `class DeepAnalysisConfig` (line 639):

```python
class DeepAnalysisDiscardRecallConfig(StrictConfigModel):
    """Thresholds for the entailment discard-recall measurement.

    ``safe_upper_bound`` and ``over_discard_lower_bound`` are the
    pre-registered stopping rule. They are fixed before data is collected and
    must not be tuned after seeing a result.
    """

    wilson_z: float = 1.96
    safe_upper_bound: float = 0.10
    over_discard_lower_bound: float = 0.40
```

And add this field to `DeepAnalysisConfig`, beside the other nested configs:

```python
    discard_recall: DeepAnalysisDiscardRecallConfig = Field(
        default_factory=DeepAnalysisDiscardRecallConfig
    )
```

- [ ] **Step 4: Write the module**

Create `neos/workflow/deep_analysis/discard_recall.py`:

```python
"""Pure metrics for the entailment discard-recall measurement.

No database, no network, no LLM. The caller supplies decoded event payloads
and grading outcomes; this module only reconstructs claims and does
arithmetic.
"""

from __future__ import annotations

import math
from typing import Any

from .models import ProposedClaim, ProposedEvidence

_EVIDENCE_FIELDS = ("source_url", "excerpt", "raw_ref")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def claim_from_event(payload: Any) -> ProposedClaim | None:
    """Rebuild a claim from a ``claim_discarded`` payload, or None if malformed."""
    if not isinstance(payload, dict):
        return None

    text = payload.get("text")
    confidence = payload.get("confidence")
    raw_evidence = payload.get("evidence")
    if not isinstance(text, str) or not text.strip():
        return None
    if not _is_number(confidence):
        return None
    if not isinstance(raw_evidence, list):
        return None

    evidence: list[ProposedEvidence] = []
    for item in raw_evidence:
        if not isinstance(item, dict):
            return None
        if any(not isinstance(item.get(f), str) for f in _EVIDENCE_FIELDS):
            return None
        evidence.append(
            ProposedEvidence(
                source_url=item["source_url"],
                excerpt=item["excerpt"],
                raw_ref=item["raw_ref"],
            )
        )

    return ProposedClaim(
        text=text,
        confidence=float(confidence),
        evidence=evidence,
    )


def value_est_from_event(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    value_est = payload.get("value_est")
    return float(value_est) if _is_number(value_est) else None


def wilson_interval(
    successes: int,
    total: int,
    z: float,
) -> tuple[float, float]:
    """Wilson score interval, clamped to [0, 1]. Empty denominator -> (0, 0)."""
    if total <= 0:
        return (0.0, 0.0)
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def false_discard_rate(verified: int, total: int) -> float:
    """Share of discarded claims the graders would have verified."""
    return verified / total if total else 0.0


def stopping_verdict(
    low: float,
    high: float,
    *,
    safe_upper: float,
    over_discard_lower: float,
) -> str:
    """Apply the pre-registered stopping rule to a Wilson interval.

    Fixed before data collection. Do not tune after seeing a result.
    """
    if high < safe_upper:
        return "safe"
    if low > over_discard_lower:
        return "over_discarding"
    return "inconclusive"
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_discard_recall.py -q \
  -o log_cli=false --disable-warnings
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add neos/config/schema.py \
        neos/workflow/deep_analysis/discard_recall.py \
        tests/workflow/deep_analysis/test_discard_recall.py
git commit -m "feat(deep-analysis): add discard-recall metrics and thresholds"
```

---

### Task 5: Phase 2 scoring script

**Files:**
- Create: `scripts/deep_analysis_discard_recall.py`
- Modify: `.gitignore`
- Test: `tests/workflow/deep_analysis/test_discard_recall_scoring.py` (create)

**Interfaces:**
- Consumes: everything from Task 4, plus `DeterministicGrader` and `AgenticGrader` from `neos.workflow.deep_analysis.graders`.
- Produces: `score_discards(events, grade_fn) -> dict` — a pure-ish async aggregator taking already-loaded events and an injectable grading callable, so it is testable without a database or an LLM.

Put `score_discards` in `neos/workflow/deep_analysis/discard_recall.py` (extending Task 4's module). The script stays thin: argument parsing, DB query, grader construction, artifact writing.

- [ ] **Step 1: Write the failing test**

Create `tests/workflow/deep_analysis/test_discard_recall_scoring.py`:

```python
import pytest

from neos.workflow.deep_analysis.discard_recall import score_discards


pytestmark = pytest.mark.no_db


def _event(text, verified):
    return {
        "text": text,
        "confidence": 0.6,
        "value_est": 1.0,
        "evidence": [
            {
                "source_url": "https://example.com/source",
                "excerpt": "Direct evidence.",
                "raw_ref": "0123456789abcdef",
            }
        ],
        "_verified": verified,
    }


async def _grade_fn(claim, value_est, verified_lookup):
    return verified_lookup[claim.text]


async def test_score_discards_counts_verified_and_reports_interval():
    events = [_event("a", True), _event("b", False), _event("c", False)]
    lookup = {"a": True, "b": False, "c": False}

    result = await score_discards(
        events,
        grade_fn=lambda claim, value_est: _grade_fn(claim, value_est, lookup),
        wilson_z=1.96,
        safe_upper=0.10,
        over_discard_lower=0.40,
    )

    assert result["total_discarded"] == 3
    assert result["verified"] == 1
    assert result["false_discard_rate"] == pytest.approx(1 / 3)
    assert result["verdict"] == "inconclusive"
    assert result["malformed"] == 0


async def test_score_discards_counts_malformed_events_without_grading():
    result = await score_discards(
        [{"text": "", "confidence": 0.6, "evidence": []}],
        grade_fn=lambda claim, value_est: _grade_fn(claim, value_est, {}),
        wilson_z=1.96,
        safe_upper=0.10,
        over_discard_lower=0.40,
    )

    assert result["total_discarded"] == 0
    assert result["malformed"] == 1


async def test_score_discards_empty_input_is_inconclusive():
    result = await score_discards(
        [],
        grade_fn=lambda claim, value_est: _grade_fn(claim, value_est, {}),
        wilson_z=1.96,
        safe_upper=0.10,
        over_discard_lower=0.40,
    )

    assert result["total_discarded"] == 0
    assert result["verdict"] == "inconclusive"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_discard_recall_scoring.py -q \
  -o log_cli=false --disable-warnings
```
Expected: FAIL — `ImportError: cannot import name 'score_discards'`.

- [ ] **Step 3: Add `score_discards` to the metrics module**

Append to `neos/workflow/deep_analysis/discard_recall.py`:

```python
async def score_discards(
    events: list[Any],
    *,
    grade_fn,
    wilson_z: float,
    safe_upper: float,
    over_discard_lower: float,
) -> dict[str, Any]:
    """Grade every discarded claim and summarise the recall loss.

    ``grade_fn(claim, value_est)`` must return True when the graders would
    have verified the claim. Every claim is graded — the agentic sampling
    gate is deliberately bypassed so the denominator stays exact.
    """
    verified = 0
    total = 0
    malformed = 0
    for payload in events:
        claim = claim_from_event(payload)
        value_est = value_est_from_event(payload)
        if claim is None or value_est is None:
            malformed += 1
            continue
        total += 1
        if await grade_fn(claim, value_est):
            verified += 1

    low, high = wilson_interval(verified, total, wilson_z)
    return {
        "total_discarded": total,
        "verified": verified,
        "malformed": malformed,
        "false_discard_rate": false_discard_rate(verified, total),
        "wilson_low": low,
        "wilson_high": high,
        "verdict": stopping_verdict(
            low,
            high,
            safe_upper=safe_upper,
            over_discard_lower=over_discard_lower,
        ),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_discard_recall_scoring.py -q \
  -o log_cli=false --disable-warnings
```
Expected: PASS.

- [ ] **Step 5: Write the CLI script**

Create `scripts/deep_analysis_discard_recall.py`. Mirror the argument-parsing and `sys.path` preamble of `scripts/deep_analysis_funnel_sample.py`.

```python
"""Score entailment-discarded claims to measure claim recall loss."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select

from neos.config.settings import settings
from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import DAEvent
from neos.workflow.deep_analysis.discard_recall import (
    false_discard_rate,
    score_discards,
    stopping_verdict,
    wilson_interval,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure entailment discard recall loss"
    )
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/deep-analysis-discard-recall"),
    )
    return parser.parse_args()


async def _load_events(session, run_ids: list[str]) -> list[dict]:
    stmt = select(DAEvent.payload).where(
        DAEvent.kind == "claim_discarded",
        DAEvent.run_id.in_(run_ids),
    )
    rows = (await session.execute(stmt)).all()
    payloads = []
    for (raw,) in rows:
        try:
            payloads.append(json.loads(raw))
        except (ValueError, TypeError):
            payloads.append(None)
    return payloads


def _write_artifact(output_root: Path, run_ids: list[str], result: dict) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = output_root / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=False)
    config = settings.config.deep_analysis.discard_recall
    manifest = {
        "run_ids": run_ids,
        "thresholds": {
            "wilson_z": config.wilson_z,
            "safe_upper_bound": config.safe_upper_bound,
            "over_discard_lower_bound": config.over_discard_lower_bound,
        },
    }
    options = {"ensure_ascii": False, "indent": 2, "sort_keys": True}
    (artifact_dir / "manifest.json").write_text(
        json.dumps(manifest, **options) + "\n"
    )
    (artifact_dir / "recall.json").write_text(
        json.dumps(result, **options) + "\n"
    )
    (artifact_dir / "report.md").write_text(
        "# Entailment discard recall\n\n"
        f"- Discarded claims graded: {result['total_discarded']}\n"
        f"- Would have been verified: {result['verified']}\n"
        f"- Malformed events skipped: {result['malformed']}\n"
        f"- False-discard rate: {result['false_discard_rate']:.1%}\n"
        f"- Wilson 95% CI: "
        f"[{result['wilson_low']:.1%}, {result['wilson_high']:.1%}]\n"
        f"- Pre-registered verdict: **{result['verdict']}**\n\n"
        "The grader is not ground truth, so this rate is a lower bound on "
        "recall loss.\n"
    )
    return artifact_dir
```

Then add the `_main` coroutine and entry point:

```python
async def _main(run_ids: list[str], output_root: Path) -> Path:
    config = settings.config.deep_analysis.discard_recall
    totals = {"total_discarded": 0, "verified": 0, "malformed": 0}

    async with get_session_ctx() as session:
        for run_id in run_ids:
            events = await _load_events(session, [run_id])
            deterministic, agentic = _graders(session, run_id)

            async def grade_fn(claim, value_est) -> bool:
                verdict = await deterministic.grade(claim)
                if not verdict.ok:
                    return False
                # Exhaustive by design: bypass should_grade() so the
                # sampling gate cannot blur the denominator.
                agentic_verdict = await agentic.grade(claim, value_est)
                return bool(agentic_verdict.ok)

            partial = await score_discards(
                events,
                grade_fn=grade_fn,
                wilson_z=config.wilson_z,
                safe_upper=config.safe_upper_bound,
                over_discard_lower=config.over_discard_lower_bound,
            )
            for key in totals:
                totals[key] += partial[key]

    # Interval and verdict are computed once, on the pooled totals.
    low, high = wilson_interval(
        totals["verified"], totals["total_discarded"], config.wilson_z
    )
    result = {
        **totals,
        "false_discard_rate": false_discard_rate(
            totals["verified"], totals["total_discarded"]
        ),
        "wilson_low": low,
        "wilson_high": high,
        "verdict": stopping_verdict(
            low,
            high,
            safe_upper=config.safe_upper_bound,
            over_discard_lower=config.over_discard_lower_bound,
        ),
    }
    return _write_artifact(output_root, run_ids, result)


if __name__ == "__main__":
    args = _parse_args()
    artifact = asyncio.run(_main(args.run_id, args.output_root))
    print(artifact)
```

The one remaining helper builds the graders. `neos/workflow/deep_analysis/service.py:59-76`
is the canonical construction — copy its exact config keys, including the
judge-model resolution, so this script cannot drift from the pipeline:

```python
from neos.config.model_routing import resolve_model
from neos.workflow.deep_analysis.graders.agentic import AgenticGrader
from neos.workflow.deep_analysis.graders.deterministic import (
    DeterministicGrader,
)
from neos.workflow.deep_analysis.ledger import Ledger


def _graders(session, run_id: str):
    config = settings.config.deep_analysis
    judge_model = resolve_model(
        config=settings.config.model_routing,
        provider="anthropic",
        role="everyday",
        feature_override=config.models.judge,
    ).model
    ledger = Ledger(session, run_id)
    deterministic = DeterministicGrader(
        ledger,
        quote_threshold=config.quote_match_threshold,
        confidence_cap=config.confidence_cap,
    )
    agentic = AgenticGrader(
        judge_model=judge_model,
        threshold=config.agentic_threshold,
        sample_rate=config.agentic_sample_rate,
    )
    return deterministic, agentic
```

**Per-run scoping is mandatory.** `DeterministicGrader` resolves evidence via
`ledger.get_blob(evidence.raw_ref)`, and a `Ledger` is bound to one `run_id`.
So `_main` must loop over `run_ids`, building a fresh ledger and grader pair
per run and scoring that run's events alone, then sum `total_discarded`,
`verified`, and `malformed` across runs and compute the Wilson interval and
verdict **once** on the summed totals. Pointing one ledger at another run's
blobs would silently mark every claim as evidence-missing.

- [ ] **Step 6: Ignore the artifact directory**

Add to `.gitignore`, beside the existing `/artifacts/deep-analysis-funnel/` entry:

```
/artifacts/deep-analysis-discard-recall/
```

- [ ] **Step 7: Verify the script imports and shows help**

Run:
```bash
/Users/ywsung/Desktop/neos/.venv/bin/python \
  scripts/deep_analysis_discard_recall.py --help
```
Expected: usage text listing `--run-id` and `--output-root`, no import errors.

- [ ] **Step 8: Confirm the artifact directory is ignored**

Run:
```bash
git check-ignore -v artifacts/deep-analysis-discard-recall
```
Expected: a line naming the new `.gitignore` rule.

- [ ] **Step 9: Commit**

```bash
git add scripts/deep_analysis_discard_recall.py \
        neos/workflow/deep_analysis/discard_recall.py \
        tests/workflow/deep_analysis/test_discard_recall_scoring.py \
        .gitignore
git commit -m "feat(deep-analysis): add discard recall scoring script"
```

---

### Task 6: Cassette recording and manifest provenance for sample runs

**Files:**
- Modify: `neos/workflow/deep_analysis/funnel_sample_runner.py:272-320`
- Test: `tests/workflow/deep_analysis/test_funnel_sample_runner.py`

**Interfaces:**
- Produces: `manifest.json` gains `execution_receipt` and `config_fingerprint` objects.

This task pays down the instrumentation debt the entailment evaluation identified: that artifact could not prove its own exit status or that runtime configuration was unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/workflow/deep_analysis/test_funnel_sample_runner.py`, following the file's existing `write_artifacts` test style:

```python
def test_write_artifacts_records_execution_receipt(tmp_path):
    artifact_dir = write_artifacts(
        _result(),
        tmp_path,
        receipt={
            "pid": 4242,
            "started_at": "2026-07-27T00:00:00Z",
            "finished_at": "2026-07-27T00:10:00Z",
            "exit_status": 0,
            "tests_passed": True,
            "ruff_passed": True,
            "preflight_passed": True,
        },
        fingerprint={"global_token_cap": 20000, "quote_threshold": 0.85},
    )

    manifest = json.loads((artifact_dir / "manifest.json").read_text())

    assert manifest["execution_receipt"]["pid"] == 4242
    assert manifest["execution_receipt"]["exit_status"] == 0
    assert manifest["config_fingerprint"]["global_token_cap"] == 20000


def test_write_artifacts_omits_provenance_when_not_supplied(tmp_path):
    artifact_dir = write_artifacts(_result(), tmp_path)

    manifest = json.loads((artifact_dir / "manifest.json").read_text())

    assert manifest["execution_receipt"] is None
    assert manifest["config_fingerprint"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_funnel_sample_runner.py -q \
  -o log_cli=false --disable-warnings
```
Expected: FAIL — `write_artifacts() got an unexpected keyword argument 'receipt'`.

- [ ] **Step 3: Accept and serialise the provenance**

In `neos/workflow/deep_analysis/funnel_sample_runner.py`, extend the `write_artifacts` signature (line 272) with two keyword-only parameters defaulting to `None`, and add both to the `manifest` dict (line 283):

```python
def write_artifacts(
    result: dict[str, Any],
    output_root: Path,
    now: datetime | None = None,
    *,
    receipt: dict[str, Any] | None = None,
    fingerprint: dict[str, Any] | None = None,
) -> Path:
```

```python
        "execution_receipt": receipt,
        "config_fingerprint": fingerprint,
```

Both values are caller-supplied plain data. Do not read credentials into either — the fingerprint carries caps and thresholds only, never API keys.

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_funnel_sample_runner.py -q \
  -o log_cli=false --disable-warnings
```
Expected: PASS.

- [ ] **Step 5: Populate provenance and enable cassette recording in the sample script**

In `scripts/deep_analysis_funnel_sample.py`, build both dicts and pass them to
`write_artifacts`:

```python
def _fingerprint() -> dict:
    config = settings.config.deep_analysis
    return {
        "global_token_cap": config.global_token_cap,
        "max_depth": config.max_depth,
        "quote_threshold": config.quote_threshold,
        "models": {
            "scout": config.models.scout,
            "dig": config.models.dig,
            "synth": config.models.synth,
            "judge": config.models.judge,
        },
        "effort": {
            name: {
                "token_cap": effort.token_cap,
                "wall_clock_cap": effort.wall_clock_cap,
            }
            for name, effort in config.effort.items()
        },
    }


def _receipt(started_at, finished_at, exit_status) -> dict:
    return {
        "pid": os.getpid(),
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        "exit_status": exit_status,
    }
```

Capture `started_at = datetime.now(timezone.utc)` before `run_sample` and
`finished_at` after it. `exit_status` is `0` on the success path; on an
exception, record the failure and re-raise **after** writing the artifact so
the receipt survives — the entailment evaluation lost its exit status
precisely because nothing persisted it.

Attribute names above must match `neos/config/schema.py`. If
`quote_threshold` lives elsewhere in the config tree, use its real path — do
not invent a literal.

For the cassette, construct `Cassette(path=<artifact_dir>/cassette.json,
mode="record")` and thread it through `run_sample` into `execute_run`, which
already accepts a `cassette` argument (`service.py:51`). Because the artifact
directory is created by `write_artifacts` *after* the run, write the cassette
to a temporary path first and move it into the artifact directory once the
path is known.

Neither dict may contain a credential: both are built from caps, model IDs,
thresholds, and process metadata only. Model IDs are configuration, not
secrets.

- [ ] **Step 6: Run the full deep-analysis suite**

Run:
```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/ -q -o log_cli=false --disable-warnings
```
Expected: PASS.

- [ ] **Step 7: Lint everything this plan touched**

Run:
```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  neos/workflow/deep_analysis/ neos/config/schema.py \
  scripts/deep_analysis_discard_recall.py \
  scripts/deep_analysis_funnel_sample.py \
  tests/workflow/deep_analysis/
```
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add neos/workflow/deep_analysis/funnel_sample_runner.py \
        scripts/deep_analysis_funnel_sample.py \
        tests/workflow/deep_analysis/test_funnel_sample_runner.py
git commit -m "feat(deep-analysis): record run provenance and cassette for samples"
```

---

## Done When

- `apply_entailment_results` returns `EntailmentOutcome | None`, and `None` still means fail-open with no discards recorded.
- A discarded claim produces exactly one `claim_discarded` event carrying its text, confidence, `value_est`, and full evidence.
- `scripts/deep_analysis_discard_recall.py --run-id <id>` writes an ignored artifact with a false-discard rate, Wilson interval, and pre-registered verdict.
- Sample-run manifests carry an execution receipt and a config fingerprint, and a cassette is recorded.
- Full `tests/workflow/deep_analysis/` suite passes and Ruff is clean.
