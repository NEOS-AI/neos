# Deep Analysis PDF and Test Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** deep-analysis가 PDF 소스를 정상 텍스트로 검증하고, workflow/API 전체 테스트의 telemetry 순서 오염과 PostgreSQL 실행환경 실패를 정확히 분리·수정하게 한다.

**Architecture:** PyMuPDF 기반의 작은 `pdf_text` 어댑터가 PDF bytes를 정규화 텍스트로 변환하고 `fetch_url`이 content-type/magic bytes로 HTML과 PDF를 분기한다. 테스트 안정성은 전역 telemetry module stub을 제거하고, PostgreSQL 테스트는 CI와 같은 DB 접근 조건에서 재검증해 실제 실패만 수정한다.

**Tech Stack:** Python 3.12, PyMuPDF 1.26+, httpx response protocol, pytest/pytest-asyncio, PostgreSQL 16 + pgvector, Ruff

## Global Constraints

- PDF 감지는 `application/pdf` media type 또는 공백 뒤 `%PDF-` magic bytes를 사용한다.
- non-2xx 응답은 기존처럼 빈 `raw_text`를 반환한다.
- PDF는 텍스트만 추출하며 표·이미지·OCR·메타데이터는 처리하지 않는다.
- PyMuPDF는 lazy import하고 새 의존성을 추가하지 않는다.
- PDF 오류만 소스 단위로 격리하며 네트워크 및 다른 프로그래밍 오류는 전파한다.
- PostgreSQL 의존 테스트를 skip하거나 unit test로 약화하지 않는다.
- 사용자 소유 dirty/untracked 파일을 수정하거나 staging하지 않는다.

---

### Task 1: Remove Telemetry Collection Pollution

**Files:**
- Modify: `tests/workflow/test_harness_graph_repair.py:1-50`
- Modify: `tests/workflow/test_harness_graph_routing.py:1-48`
- Modify: `tests/workflow/test_thinking_engine_finalization.py:1-48`

**Interfaces:**
- Consumes: 실제 `neos.workflow.telemetry` module
- Produces: workflow routing tests that do not mutate `sys.modules["neos.workflow.telemetry"]`

- [ ] **Step 1: Reproduce the order-dependent failure**

Run the polluting modules before the production app authorization tests in one process:

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/workflow/test_harness_graph_repair.py \
  tests/workflow/test_harness_graph_routing.py \
  tests/workflow/test_thinking_engine_finalization.py \
  tests/api/handlers/test_query_authorization.py \
  -q -o log_cli=false
```

Expected: FAIL with `ImportError: cannot import name 'setup_telemetry' from 'neos.workflow.telemetry'`.

- [ ] **Step 2: Remove only the telemetry stubs**

Delete the `_noop_trace` context managers, the `telemetry_module` construction, and the `sys.modules` assignment/setdefault from all three files. Remove now-unused `contextmanager` imports. Keep optional YouTube/Google/isodate stubs unchanged.

- [ ] **Step 3: Verify the same ordered test command passes**

Run the Step 1 command unchanged.

Expected: all selected tests PASS with no telemetry import failure.

- [ ] **Step 4: Run static checks and commit**

```bash
uv run --frozen ruff check \
  tests/workflow/test_harness_graph_repair.py \
  tests/workflow/test_harness_graph_routing.py \
  tests/workflow/test_thinking_engine_finalization.py
git add \
  tests/workflow/test_harness_graph_repair.py \
  tests/workflow/test_harness_graph_routing.py \
  tests/workflow/test_thinking_engine_finalization.py
git commit -m "test: isolate workflow telemetry stubs"
```

Expected: Ruff reports `All checks passed!`; commit contains only the three tests.

---

### Task 2: Revalidate PostgreSQL Failures Under CI Conditions

**Files:**
- Modify only if an assertion/schema/cleanup defect remains after DB connectivity succeeds
- Potential tests: `tests/workflow/deep_analysis/test_deep_analysis_analytics.py`, `test_ledger*.py`, `test_orchestrator*_integration.py`, `test_deep_analysis_report*.py`

**Interfaces:**
- Consumes: `DATABASE_URL=postgresql+asyncpg://neos:neos_password@localhost:5432/neos_db`
- Produces: evidence separating sandbox connectivity failures from real test failures

- [ ] **Step 1: Verify PostgreSQL availability outside the filesystem/network sandbox**

Run:

```bash
DATABASE_URL=postgresql+asyncpg://neos:neos_password@localhost:5432/neos_db \
  .venv/bin/python -c \
  "import asyncio, asyncpg; asyncio.run(asyncpg.connect('postgresql://neos:neos_password@localhost:5432/neos_db'))"
```

Expected: exit 0. If connection is refused or authentication fails, stop and report the missing external prerequisite; do not alter tests to hide it.

- [ ] **Step 2: Run the previously failing deep-analysis DB set with access enabled**

```bash
HOME=/tmp/neos-test-home \
DATABASE_URL=postgresql+asyncpg://neos:neos_password@localhost:5432/neos_db \
.venv/bin/pytest \
  tests/workflow/deep_analysis/test_deep_analysis_analytics.py \
  tests/workflow/deep_analysis/test_deep_analysis_report_model.py \
  tests/workflow/deep_analysis/test_deep_analysis_report_task.py \
  tests/workflow/deep_analysis/test_ledger.py \
  tests/workflow/deep_analysis/test_ledger_m2.py \
  tests/workflow/deep_analysis/test_ledger_m3.py \
  tests/workflow/deep_analysis/test_orchestrator_checkpoint_granularity.py \
  tests/workflow/deep_analysis/test_orchestrator_contract.py \
  tests/workflow/deep_analysis/test_orchestrator_m2.py \
  tests/workflow/deep_analysis/test_orchestrator_m2_split.py \
  tests/workflow/deep_analysis/test_orchestrator_m3.py \
  tests/workflow/deep_analysis/test_orchestrator_m3_integration.py \
  tests/workflow/deep_analysis/test_orchestrator_m4_integration.py \
  tests/workflow/deep_analysis/test_orchestrator_m4_reinvest.py \
  -q -o log_cli=false
```

Expected: the 44 previously blocked tests PASS. If any test reaches PostgreSQL but fails an assertion, use systematic debugging and a separate RED/GREEN cycle for that exact defect before proceeding.

- [ ] **Step 3: Record a no-change outcome or commit an actual fix**

If all tests pass, create no code commit and record the command/result for Task 5. If real defects were fixed, run their focused tests and Ruff, then commit only those files with a defect-specific message.

---

### Task 3: PDF Text Extraction Adapter

**Files:**
- Create: `neos/workflow/deep_analysis/pdf_text.py`
- Create: `tests/workflow/deep_analysis/test_pdf_text.py`

**Interfaces:**
- Produces: `class PDFExtractionError(Exception)`, `pdf_bytes_to_text(content: bytes) -> str`
- Consumes: PyMuPDF `fitz.open(stream=content, filetype="pdf")`

- [ ] **Step 1: Write failing adapter tests**

Use a fake `fitz` module injected through `sys.modules` so document close behavior is observable:

```python
def test_pdf_bytes_to_text_normalizes_pages_and_closes(monkeypatch):
    document = FakeDocument(["  First\npage  ", "cafe\u0301\tsecond"])
    monkeypatch.setitem(sys.modules, "fitz", FakeFitz(document))
    assert pdf_bytes_to_text(b"%PDF-fake") == "First page café second"
    assert document.closed is True

def test_pdf_bytes_to_text_wraps_parser_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "fitz", FailingFitz(ValueError("secret")))
    with pytest.raises(PDFExtractionError, match="Unable to extract PDF text"):
        pdf_bytes_to_text(b"%PDF-broken")
```

Add import-failure and empty-document tests. Assert error text does not include parser payload.

- [ ] **Step 2: Run tests and confirm RED**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_pdf_text.py -q -o log_cli=false`

Expected: collection fails with `ModuleNotFoundError: neos.workflow.deep_analysis.pdf_text`.

- [ ] **Step 3: Implement the minimal adapter**

```python
class PDFExtractionError(Exception):
    pass

def _normalize_text(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    return unicodedata.normalize("NFC", collapsed)

def pdf_bytes_to_text(content: bytes) -> str:
    try:
        import fitz
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise PDFExtractionError("Unable to extract PDF text") from exc
    try:
        return _normalize_text("\n".join(page.get_text() for page in document))
    except Exception as exc:
        raise PDFExtractionError("Unable to extract PDF text") from exc
    finally:
        document.close()
```

Catch import failure through the same stable public error. Do not log content or underlying exception text.

- [ ] **Step 4: Verify adapter and lint**

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_pdf_text.py -q -o log_cli=false
uv run --frozen ruff check \
  neos/workflow/deep_analysis/pdf_text.py \
  tests/workflow/deep_analysis/test_pdf_text.py
```

Expected: all adapter tests PASS; Ruff passes.

- [ ] **Step 5: Commit the adapter**

```bash
git add neos/workflow/deep_analysis/pdf_text.py tests/workflow/deep_analysis/test_pdf_text.py
git commit -m "feat: extract normalized text from PDF sources"
```

---

### Task 4: Fetch PDF Dispatch and Worker Isolation

**Files:**
- Modify: `neos/workflow/deep_analysis/fetch.py:1-100`
- Modify: `neos/workflow/deep_analysis/worker.py:1-180`
- Modify: `tests/workflow/deep_analysis/test_fetch.py`
- Modify: `tests/workflow/deep_analysis/test_worker.py`

**Interfaces:**
- Consumes: Task 3 `pdf_bytes_to_text(content)`, `PDFExtractionError`
- Produces: `_is_pdf_response(response) -> bool`; PDF-aware `fetch_url`; worker source-level PDF error isolation

- [ ] **Step 1: Write failing fetch dispatch tests**

Extend `FakeHttpClient` responses with optional `content` and `headers`. Add:

```python
async def test_fetch_uses_pdf_parser_for_pdf_content_type(monkeypatch):
    parse = Mock(return_value="PDF evidence text")
    monkeypatch.setattr(fetch_module, "pdf_bytes_to_text", parse)
    client = FakeHttpClient(200, b"%PDF-body", {"content-type": "application/pdf; charset=binary"})
    blob = await fetch_url("https://example.com/paper", client=client)
    assert blob.raw_text == "PDF evidence text"
    parse.assert_called_once_with(b"%PDF-body")

async def test_fetch_detects_pdf_magic_when_header_is_wrong(monkeypatch):
    parse = Mock(return_value="Magic PDF")
    monkeypatch.setattr(fetch_module, "pdf_bytes_to_text", parse)
    client = FakeHttpClient(200, b"  \n%PDF-body", {"content-type": "application/octet-stream"})
    assert (await fetch_url("https://example.com/paper", client=client)).raw_text == "Magic PDF"
```

Add regression cases for HTML responses, non-2xx PDF bodies, and a legacy fake with only `.text`.

- [ ] **Step 2: Write failing worker isolation test**

Configure two search URLs. Make the first fetch raise `PDFExtractionError` and the second return a valid `ProposedBlob`. Assert the worker completes, includes only the valid blob, and logs the failed URL without exception payload.

- [ ] **Step 3: Run focused tests and confirm RED**

Run:

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/workflow/deep_analysis/test_fetch.py \
  tests/workflow/deep_analysis/test_worker.py \
  -q -o log_cli=false
```

Expected: PDF dispatch and source isolation assertions FAIL because fetch is still HTML-only and the worker propagates `PDFExtractionError`.

- [ ] **Step 4: Implement response dispatch**

In `fetch.py`, inspect headers case-insensitively and use `response.content` when available. Preserve compatibility:

```python
def _is_pdf_response(response) -> bool:
    headers = getattr(response, "headers", {}) or {}
    media_type = str(headers.get("content-type", "")).split(";", 1)[0].strip().lower()
    content = getattr(response, "content", b"") or b""
    return media_type == "application/pdf" or bytes(content).lstrip().startswith(b"%PDF-")
```

For 2xx responses, call `pdf_bytes_to_text(bytes(response.content))` when PDF; otherwise keep `html_to_text(response.text)`. Never parse a non-2xx body.

- [ ] **Step 5: Isolate PDF failures in the worker**

Wrap only the `await self.fetch_fn()` call:

```python
try:
    blob = await self.fetch_fn(
        url,
        client=self.http_client,
        cassette=self.cassette,
    )
except PDFExtractionError as exc:
    logger.warning(
        "Skipping unreadable PDF source: url=%s error_type=%s",
        url,
        type(exc).__name__,
    )
    continue
```

Add a module logger. Do not catch `Exception` broadly.

- [ ] **Step 6: Verify focused and neighboring regressions**

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/workflow/deep_analysis/test_pdf_text.py \
  tests/workflow/deep_analysis/test_fetch.py \
  tests/workflow/deep_analysis/test_worker.py \
  tests/workflow/deep_analysis/test_deterministic_grader.py \
  -q -o log_cli=false
uv run --frozen ruff check \
  neos/workflow/deep_analysis/pdf_text.py \
  neos/workflow/deep_analysis/fetch.py \
  neos/workflow/deep_analysis/worker.py \
  tests/workflow/deep_analysis/test_pdf_text.py \
  tests/workflow/deep_analysis/test_fetch.py \
  tests/workflow/deep_analysis/test_worker.py
```

Expected: all tests and Ruff PASS.

- [ ] **Step 7: Commit fetch integration**

```bash
git add \
  neos/workflow/deep_analysis/fetch.py \
  neos/workflow/deep_analysis/worker.py \
  tests/workflow/deep_analysis/test_fetch.py \
  tests/workflow/deep_analysis/test_worker.py
git commit -m "fix: fetch PDF evidence for deep analysis"
```

---

### Task 5: Full Regression and TODO Completion

**Files:**
- Modify: `docs/TODO_260729.md:136-153, summary table`

**Interfaces:**
- Consumes: Tasks 1-4 behavior and verification evidence
- Produces: completed §6 record and next implementation priority

- [ ] **Step 1: Run telemetry order regression**

Run the Task 1 Step 1 command.

Expected: all selected tests PASS.

- [ ] **Step 2: Run workflow and API handler suites with PostgreSQL access**

```bash
HOME=/tmp/neos-test-home \
DATABASE_URL=postgresql+asyncpg://neos:neos_password@localhost:5432/neos_db \
.venv/bin/pytest tests/workflow tests/api/handlers -q -o log_cli=false
```

Expected: all tests PASS. If PostgreSQL is unavailable, report that external blocker separately and still run all `no_db` and focused suites; do not claim the DB suite passed.

- [ ] **Step 3: Run final static checks**

Run Ruff on every changed Python file and `git diff --check`.

Expected: Ruff says `All checks passed!`; diff check has no output.

- [ ] **Step 4: Update TODO with precise evidence**

Mark §6 complete. Record content-type/magic detection, PyMuPDF text-only adapter, worker isolation, test counts, DB availability/result, and implementation commit hashes. Promote §8 observation to the next listed priority without inventing a code change.

- [ ] **Step 5: Commit documentation**

```bash
git add docs/TODO_260729.md
git commit -m "docs: mark deep analysis PDF fetch complete"
```

- [ ] **Step 6: Verify branch state**

Run `git status --short` and `git log --oneline -6`.

Expected: feature work is committed; only pre-existing user-owned files remain.
