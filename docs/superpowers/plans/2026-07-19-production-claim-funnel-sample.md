# Production Claim Funnel Sample Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a reproducible five-`dev` plus one representative-`default` real-provider evaluation that identifies the dominant verified-claim funnel loss stage without changing grading policy.

**Architecture:** Put the fixed question set and pure funnel math in a framework-free workflow module. Put database execution, preflight, and artifact writing in a separate runner module, exposed by a thin `python -m scripts...` CLI. The runner uses the production `create_run`, `execute_run`, scoped analytics service, token ledger, and existing hard limits, while tests replace paid execution with deterministic stubs.

**Tech Stack:** Python 3.12, asyncio, dataclasses, SQLAlchemy async sessions, PostgreSQL, pytest/pytest-asyncio, Ruff, JSON and Markdown artifacts.

## Global Constraints

- Execute exactly five fixed mixed questions under `dev`, sequentially.
- Execute at most one deterministically selected representative question under `default`.
- Do not change model selection, prompts, quote threshold, agentic sampling, discovery breadth, token caps, wall-clock caps, or job limits.
- Require configured Anthropic and Tavily credentials without printing their values.
- Preserve cancellation, `KeyboardInterrupt`, and process-termination signals.
- Never copy model responses, reports, claims, evidence excerpts, fetched bodies, URLs, or API keys into evaluation diagnostics.
- Store generated artifacts under gitignored `artifacts/deep-analysis-funnel/`; do not commit them.
- Execute tools and all real runs sequentially (five `dev`, then at most one `default`).

---

## File Structure

- Create `neos/workflow/deep_analysis/funnel_sample.py`: fixed question set, loss-stage derivation, weighted aggregation, representative selection, and Markdown interpretation. It has no database, provider, or filesystem dependencies.
- Create `neos/workflow/deep_analysis/funnel_sample_runner.py`: credential/database preflight, run creation/execution, scoped signal and token collection, failure isolation, redaction, and artifact serialization.
- Create `scripts/deep_analysis_funnel_sample.py`: minimal command-line parsing and `asyncio.run` entrypoint.
- Create `tests/workflow/deep_analysis/test_funnel_sample.py`: no-DB tests for pure analysis and selection rules.
- Create `tests/workflow/deep_analysis/test_funnel_sample_runner.py`: no-DB tests for preflight, execution isolation, redaction, and serialization.
- Create `tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py`: PostgreSQL test for real run creation and scoped analytics collection with a free stub executor.
- Modify `.gitignore`: ignore only `artifacts/deep-analysis-funnel/`.
- Modify `docs/TODO_260729.md`: record the measured dominant stage, run IDs, dev/default comparison, caveats, and next policy-design priority after the real execution.

---

### Task 1: Pure Funnel Analysis and Representative Selection

**Files:**
- Create: `neos/workflow/deep_analysis/funnel_sample.py`
- Create: `tests/workflow/deep_analysis/test_funnel_sample.py`

**Interfaces:**
- Produces: `QuestionCase`, `QUESTION_SET_VERSION`, `QUESTION_CASES`, `stage_metrics(funnel)`, `aggregate_funnels(funnels)`, `dominant_stage(funnel)`, and `select_representative(observations)`.
- Consumes: the existing `signals["claim_funnel"]` dictionary returned by `DeepAnalysisAnalyticsService`.

- [ ] **Step 1: Write the failing fixed-set and stage-math tests**

```python
from neos.workflow.deep_analysis.funnel_sample import (
    QUESTION_CASES,
    QUESTION_SET_VERSION,
    stage_metrics,
)


def test_question_set_is_versioned_and_mixed():
    assert QUESTION_SET_VERSION == "mixed-v1"
    assert [case.category for case in QUESTION_CASES] == [
        "fact", "fact", "technical", "technical", "causal_policy"
    ]
    assert len({case.question for case in QUESTION_CASES}) == 5


def test_stage_metrics_expose_counts_denominators_and_rates():
    funnel = {
        "proposed": 10, "graded": 8,
        "deterministic_rejected": 3,
        "agentic_rejected": 1, "agentic_exhausted": 1,
        "rejected": 2, "unverified": 1,
    }
    assert stage_metrics(funnel) == {
        "proposal_to_grade": {"count": 2, "denominator": 10, "rate": 0.2},
        "deterministic_rejection": {"count": 3, "denominator": 8, "rate": 0.375},
        "agentic_loss": {"count": 2, "denominator": 8, "rate": 0.25},
        "final_unresolved": {"count": 3, "denominator": 8, "rate": 0.375},
    }
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample.py -q`

Expected: collection fails because `funnel_sample` does not exist.

- [ ] **Step 3: Implement the fixed cases and safe stage math**

```python
from dataclasses import dataclass

QUESTION_SET_VERSION = "mixed-v1"


@dataclass(frozen=True)
class QuestionCase:
    case_id: str
    category: str
    question: str


QUESTION_CASES = (
    QuestionCase("fact-eu-ai-act", "fact", "As of 2026-07-19, which EU AI Act obligations for providers of general-purpose AI models are already applicable, and on what dates did they begin to apply? Use official EU sources."),
    QuestionCase("fact-aspartame", "fact", "Did WHO or IARC classify aspartame as carcinogenic in 2023, and how does that hazard classification differ from JECFA's risk assessment? Use primary institutional sources."),
    QuestionCase("tech-hybrid-search", "technical", "Compare PostgreSQL 17 and Elasticsearch 8.x for hybrid lexical and vector search, including native capabilities, consistency, ranking controls, and operational trade-offs. Prefer official documentation and primary sources."),
    QuestionCase("tech-free-threading", "technical", "Compare free-threaded CPython 3.13 with the standard GIL build for CPU-bound multithreaded workloads, extension compatibility, and production readiness. Use Python project documentation and primary benchmarks."),
    QuestionCase("policy-london-ulez", "causal_policy", "What measured effects did London's 2023 ULEZ expansion have on roadside air pollution and traffic by July 2026, and which findings support causal attribution rather than simple association? Use official evaluations and peer-reviewed research."),
)


def _metric(count: int, denominator: int) -> dict[str, int | float]:
    return {
        "count": max(0, int(count)),
        "denominator": max(0, int(denominator)),
        "rate": max(0, int(count)) / denominator if denominator > 0 else 0.0,
    }


def stage_metrics(funnel: dict) -> dict[str, dict[str, int | float]]:
    proposed = int(funnel.get("proposed", 0))
    graded = int(funnel.get("graded", 0))
    return {
        "proposal_to_grade": _metric(proposed - graded, proposed),
        "deterministic_rejection": _metric(funnel.get("deterministic_rejected", 0), graded),
        "agentic_loss": _metric(funnel.get("agentic_rejected", 0) + funnel.get("agentic_exhausted", 0), graded),
        "final_unresolved": _metric(funnel.get("rejected", 0) + funnel.get("unverified", 0), graded),
    }
```

- [ ] **Step 4: Add failing aggregation and selection tests**

```python
def test_aggregate_funnels_recomputes_weighted_rates_and_averages():
    combined = aggregate_funnels([FUNNEL_A, FUNNEL_B])
    assert combined["graded"] == 10
    assert combined["evidence_missing_rate"] == 0.3
    assert combined["avg_evidence_count"] == 2.6
    assert combined["quote_score_buckets"]["near_miss"] == 4


def test_representative_contains_dominant_loss_and_is_closest_to_median():
    selected = select_representative(OBSERVATIONS)
    assert selected["dominant_stage"] == "deterministic_rejection"
    assert selected["case_id"] == "middle-loss"


def test_representative_ties_follow_fixed_question_order():
    assert select_representative(TIED_OBSERVATIONS)["case_id"] == "first"
```

Use complete fixtures containing every current funnel key, including all five quote buckets. Include a no-completed-run assertion returning `None` and a completed-but-zero-graded assertion selecting the first completed observation.

- [ ] **Step 5: Run the new tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample.py -q`

Expected: fixed-set tests pass; aggregation and selection tests fail because their functions are absent.

- [ ] **Step 6: Implement aggregation and deterministic selection**

Implement `aggregate_funnels()` by summing counter fields and quote buckets, then recomputing rates and averages with `graded` as the weight. Implement `dominant_stage()` as maximum `(count, rate)` in the declared stage order. Implement `select_representative()` exactly as the design: completed runs only, dominant-stage candidates only, absolute distance from the completed-run median `graded`, then original `order`.

```python
def select_representative(observations: list[dict]) -> dict | None:
    completed = [item for item in observations if item["status"] == "completed"]
    if not completed:
        return None
    aggregate = aggregate_funnels([item["signals"]["claim_funnel"] for item in completed])
    stage = dominant_stage(aggregate)
    candidates = [item for item in completed if stage_metrics(item["signals"]["claim_funnel"])[stage]["count"] > 0]
    if not candidates:
        return min(completed, key=lambda item: item["order"])
    median_graded = statistics.median(item["signals"]["claim_funnel"]["graded"] for item in completed)
    selected = min(candidates, key=lambda item: (abs(item["signals"]["claim_funnel"]["graded"] - median_graded), item["order"]))
    return {**selected, "dominant_stage": stage}
```

- [ ] **Step 7: Verify and commit Task 1**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample.py -q`

Expected: all tests pass.

Run: `/opt/homebrew/bin/uv run --frozen ruff check neos/workflow/deep_analysis/funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample.py`

Expected: `All checks passed!`

```bash
git add neos/workflow/deep_analysis/funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample.py
git commit -m "feat(deep-analysis): define production funnel sample analysis"
```

---

### Task 2: Bounded Real-Run Execution and Scoped Collection

**Files:**
- Create: `neos/workflow/deep_analysis/funnel_sample_runner.py`
- Create: `tests/workflow/deep_analysis/test_funnel_sample_runner.py`
- Create: `tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py`

**Interfaces:**
- Consumes: `QUESTION_CASES`, `select_representative`, `create_run`, `execute_run`, `DeepAnalysisAnalyticsService.signals(run_id=...)`, `Ledger.total_spent()`, and `settings.config.deep_analysis.job_time_limit`.
- Produces: `PreflightError`, `preflight(settings_obj, session_factory)`, `sanitize_error(exc, secrets)`, `execute_case(case, profile, ...)`, and `run_sample(...)`.

- [ ] **Step 1: Write failing preflight and content-free diagnostic tests**

```python
@pytest.mark.asyncio
async def test_preflight_requires_anthropic_tavily_and_database():
    fake_settings = SimpleNamespace(ANTHROPIC_API_KEY="anthropic", TAVILY_API_KEY="tavily")
    await preflight(fake_settings, healthy_session_factory)


@pytest.mark.asyncio
async def test_preflight_lists_missing_names_without_values():
    fake_settings = SimpleNamespace(ANTHROPIC_API_KEY=None, TAVILY_API_KEY=None)
    with pytest.raises(PreflightError, match="ANTHROPIC_API_KEY, TAVILY_API_KEY"):
        await preflight(fake_settings, healthy_session_factory)


def test_sanitize_error_exposes_only_type_and_fixed_stage():
    error = RuntimeError("sk-live-secret https://private.example report model claim")
    assert sanitize_error(error, ["sk-live-secret"]) == {
        "type": "RuntimeError",
        "stage": "execution",
    }
```

Artifact-bound diagnostics never serialize exception messages. They contain
only the exception type and an allowlisted `execution` or `collection` stage.
Preflight errors may list missing configuration names but never values.

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample_runner.py -q`

Expected: collection fails because the runner module does not exist.

- [ ] **Step 3: Implement preflight and content-free error serialization**

```python
class PreflightError(RuntimeError):
    pass


async def preflight(settings_obj, session_factory) -> None:
    missing = [name for name in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY") if not getattr(settings_obj, name, None)]
    if missing:
        raise PreflightError("missing required credentials: " + ", ".join(missing))
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))


def sanitize_error(exc: Exception, secrets: list[str | None]) -> dict[str, str]:
    del secrets
    source = exc.cause if isinstance(exc, _CreatedRunError) else exc
    stage = getattr(exc, "stage", "execution")
    if stage not in {"execution", "collection"}:
        stage = "execution"
    return {"type": type(source).__name__, "stage": stage}
```

- [ ] **Step 4: Write failing execution-isolation tests**

Test three ordered cases with an injected `execute_case_fn` whose second call raises `RuntimeError`. Assert the third still runs, observations retain order, the failure contains only exception type and fixed stage code, and cancellation propagates rather than becoming an observation. Prove execution and collection failures preserve the created `run_id`, and that exception text containing secrets, URLs, report/model/claim-like content is absent. Test that `run_sample()` calls a sixth `default` execution only for the case returned by `select_representative` and never calls it when all dev runs fail.

```python
@pytest.mark.asyncio
async def test_run_sample_isolates_ordinary_failure_and_continues():
    result = await run_sample(cases=CASES, execute_case_fn=fake_execute_case, secrets=["secret"])
    assert [item["status"] for item in result["dev_runs"]] == ["completed", "failed", "completed"]
    assert calls == [("first", "dev"), ("second", "dev"), ("third", "dev"), ("first", "default")]


@pytest.mark.asyncio
async def test_run_sample_propagates_cancellation():
    with pytest.raises(asyncio.CancelledError):
        await run_sample(cases=CASES, execute_case_fn=cancelled, secrets=[])
```

- [ ] **Step 5: Implement sequential execution and collection**

`execute_case()` must create and commit the run in one session, then preserve that
`run_id` through a created-run error boundary covering every later failure. The
boundary assigns fixed stage `execution` while calling
`execute_run(..., timeout_seconds=job_time_limit)`, then fixed stage `collection`
while a fresh session reads `DARun.status`, scoped analytics, and
`Ledger.total_spent()`. Measure elapsed time with `time.monotonic()`. Do not
include `result["report_markdown"]` in the returned observation.

`run_sample()` uses a plain `for` loop and catches only `Exception`. It appends a bounded failed observation and continues. It then calls `select_representative`; if selected, it executes that case once with `default`. Returned data contains schema version, question-set version, dev observations, selection metadata, optional default observation, and aggregate dev funnel.

- [ ] **Step 6: Run unit tests and verify GREEN**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample_runner.py -q`

Expected: all tests pass.

- [ ] **Step 7: Write the failing PostgreSQL integration test**

Use the real `get_session_ctx` and a stub `execute_fn`. The stub receives the created run ID, inserts one valid `pass_completed` and one valid `claim_graded` event, marks `DARun.status="completed"`, creates a root `DAQuestion` with `spent_tokens=321`, commits, and returns a report string that must not appear in the observation.

```python
@pytest.mark.asyncio
async def test_execute_case_creates_run_and_collects_scoped_signals():
    observation = await execute_case(CASE, "dev", session_factory=get_session_ctx, execute_fn=stub_execute, timeout_seconds=3900)
    assert observation["status"] == "completed"
    assert observation["tokens_spent"] == 321
    assert observation["signals"]["claim_funnel"]["graded"] == 1
    assert "report_markdown" not in json.dumps(observation)
```

- [ ] **Step 8: Run PostgreSQL integration and verify GREEN**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py -q -o log_cli=false --disable-warnings`

Expected: all tests pass. Local PostgreSQL access is required.

- [ ] **Step 9: Verify and commit Task 2**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py -q`

Run: `/opt/homebrew/bin/uv run --frozen ruff check neos/workflow/deep_analysis/funnel_sample.py neos/workflow/deep_analysis/funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py`

Expected: all tests and Ruff pass.

```bash
git add neos/workflow/deep_analysis/funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py
git commit -m "feat(deep-analysis): run bounded funnel samples"
```

---

### Task 3: CLI and Local Evaluation Artifacts

**Files:**
- Create: `scripts/deep_analysis_funnel_sample.py`
- Modify: `.gitignore`
- Modify: `neos/workflow/deep_analysis/funnel_sample_runner.py`
- Modify: `tests/workflow/deep_analysis/test_funnel_sample_runner.py`

**Interfaces:**
- Consumes: `run_sample()` result.
- Produces: `write_artifacts(result, output_root, now) -> Path`, `render_report(result) -> str`, and CLI command `python -m scripts.deep_analysis_funnel_sample --output-root artifacts/deep-analysis-funnel`.

- [ ] **Step 1: Write failing artifact and report tests**

```python
def test_write_artifacts_creates_timestamped_contract(tmp_path):
    artifact_dir = write_artifacts(RESULT, tmp_path, now=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc))
    assert artifact_dir.name == "20260719T120000Z"
    assert json.loads((artifact_dir / "manifest.json").read_text())["schema_version"] == "1"
    assert json.loads((artifact_dir / "funnel.json").read_text())["selection"]["case_id"] == "fact-aspartame"
    report = (artifact_dir / "report.md").read_text()
    assert "Dominant loss stage" in report
    assert "deterministic_rejection" in report
    assert "report body" not in report


def test_write_artifacts_rejects_existing_directory(tmp_path):
    fixed = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    write_artifacts(RESULT, tmp_path, now=fixed)
    with pytest.raises(FileExistsError):
        write_artifacts(RESULT, tmp_path, now=fixed)
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample_runner.py -q`

Expected: artifact tests fail because `write_artifacts` and `render_report` are absent.

- [ ] **Step 3: Implement exclusive artifact writing and concise Markdown**

Create the timestamped directory with `exist_ok=False`. Write JSON with `ensure_ascii=False`, `indent=2`, `sort_keys=True`, and `default=str`. Split the result so `manifest.json` carries execution metadata/questions and `funnel.json` carries signals/selection/comparison. Render a Markdown table with case ID, profile, status, elapsed seconds, tokens, proposed, graded, verified, rejected, and unverified. Include dominant stage count/rate, quote buckets, evidence/source rates, dev/default deltas, failures, and the statement that stages overlap and no policy was changed.

- [ ] **Step 4: Add the CLI and ignore rule**

```python
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the production-like deep-analysis claim funnel sample")
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/deep-analysis-funnel"))
    return parser.parse_args()


async def _main(output_root: Path) -> tuple[Path, list[str]]:
    await preflight(settings, get_session_ctx)
    result = await run_sample(
        cases=QUESTION_CASES,
        session_factory=get_session_ctx,
        execute_fn=execute_run,
        timeout_seconds=settings.config.deep_analysis.job_time_limit,
        secrets=[settings.ANTHROPIC_API_KEY, settings.TAVILY_API_KEY],
    )
    artifact_dir = write_artifacts(result, output_root)
    run_ids = [item["run_id"] for item in result["dev_runs"] if item.get("run_id")]
    default_run = result.get("default_run")
    if default_run and default_run.get("run_id"):
        run_ids.append(default_run["run_id"])
    return artifact_dir, run_ids
```

`main()` prints only the artifact directory and run IDs, never questions, reports, provider responses, or secrets. Add `/artifacts/deep-analysis-funnel/` to `.gitignore`.

- [ ] **Step 5: Verify CLI help, tests, and Ruff**

Run: `.venv/bin/python -m scripts.deep_analysis_funnel_sample --help`

Expected: exits 0 and lists only `--output-root`.

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py -q`

Run: `/opt/homebrew/bin/uv run --frozen ruff check scripts/deep_analysis_funnel_sample.py neos/workflow/deep_analysis/funnel_sample.py neos/workflow/deep_analysis/funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py`

Expected: CLI help, tests, and Ruff pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add .gitignore scripts/deep_analysis_funnel_sample.py neos/workflow/deep_analysis/funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample_runner.py
git commit -m "feat(deep-analysis): emit funnel evaluation artifacts"
```

---

### Task 4: Real Five-plus-One Evaluation and TODO Decision

**Files:**
- Modify: `docs/TODO_260729.md`
- Generate but do not commit: `artifacts/deep-analysis-funnel/<timestamp>/manifest.json`
- Generate but do not commit: `artifacts/deep-analysis-funnel/<timestamp>/funnel.json`
- Generate but do not commit: `artifacts/deep-analysis-funnel/<timestamp>/report.md`

**Interfaces:**
- Consumes: the Task 3 CLI and configured real Anthropic, Tavily, PostgreSQL, and network access.
- Produces: one local evaluation artifact directory and an evidence-backed next policy-design priority in the TODO.

- [ ] **Step 1: Run free verification before paid calls**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py -q -o log_cli=false --disable-warnings`

Expected: all tests pass.

Run: `/opt/homebrew/bin/uv run --frozen ruff check scripts/deep_analysis_funnel_sample.py neos/workflow/deep_analysis/funnel_sample.py neos/workflow/deep_analysis/funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py`

Expected: `All checks passed!`

- [ ] **Step 2: Execute the real bounded sample**

Run: `.venv/bin/python -m scripts.deep_analysis_funnel_sample --output-root artifacts/deep-analysis-funnel`

Expected: preflight passes, five sequential dev run IDs and at most one default run ID are printed, and one artifact directory is printed. This command needs network access and can run up to the existing per-run hard limit. Do not retry failed runs automatically.

- [ ] **Step 3: Validate artifact safety and schema**

Run a read-only validator that loads both JSON files, confirms exactly five dev observations, no more than one default observation, unique run IDs, allowed profiles/statuses, non-negative counts/tokens/times, and absence of the configured secret values. Confirm `git status --short` does not list the artifact directory.

Expected: validator exits 0; artifacts remain ignored.

- [ ] **Step 4: Interpret the result without changing policy**

Read `report.md` and cross-check its dominant stage against `funnel.json`. Record:

- completed/failed run counts and failure types;
- aggregate proposed, graded, deterministic rejected, agentic outcomes, verified, rejected, and unverified;
- evidence-missing and source-dead rates;
- quote bucket distribution;
- representative dev/default token and outcome deltas;
- sample-size, provider, temporal, and question-set caveats.

If the result does not support a single policy change, explicitly recommend more sampling rather than guessing.

- [ ] **Step 5: Update the TODO with measured evidence**

Add a dated subsection below §7 with the artifact directory basename, six-or-fewer run IDs, aggregate metrics, dominant stage, dev/default comparison, and exactly one of these next decisions supported by the data: quote-threshold design, agentic-sampling design, prompt design, discovery/source-handling design, or more sampling. Do not claim that §7 ratio improvement is complete.

- [ ] **Step 6: Run final regression and documentation checks**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py tests/workflow/deep_analysis/test_deep_analysis_analytics.py -q -o log_cli=false --disable-warnings`

Run: `/opt/homebrew/bin/uv run --frozen ruff check scripts/deep_analysis_funnel_sample.py neos/workflow/deep_analysis/funnel_sample.py neos/workflow/deep_analysis/funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py`

Run: `git diff --check && git status --short`

Expected: all tests and Ruff pass; only the intended TODO edit and pre-existing user changes are visible; evaluation artifacts remain ignored.

- [ ] **Step 7: Commit the measured decision**

```bash
git add docs/TODO_260729.md
git commit -m "docs: record production claim funnel baseline"
```

Do not commit the artifact directory or modify the grading policy in this commit.
