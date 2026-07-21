# Deep-analysis NUL Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Canonicalize fetched HTML and PDF evidence by removing NUL before hashing, prompting, and PostgreSQL persistence.

**Architecture:** Add one shared evidence-text normalization helper beside the existing claim/match normalization functions. Route HTML extraction and PDF extraction through it so every downstream consumer sees exactly the same database-safe canonical text.

**Tech Stack:** Python 3.12, stdlib Unicode/regex normalization, pytest, Ruff, PostgreSQL-backed deep-analysis evaluation.

## Global Constraints

- Remove only `U+0000`; do not broadly delete other Unicode control characters.
- Preserve whitespace collapse, trim, NFC normalization, script/style exclusion, PDF error wrapping, and empty-body hashing.
- Canonical text must be established before content hashing, LLM evidence context construction, and database persistence.
- Do not change prompts, graders, thresholds, sampling, discovery, models, token caps, or wall-clock caps.
- Never log fetched text or the persisted database error payload.
- Treat artifact `20260721T043212Z` as incomplete diagnostic evidence, not a five-case quality comparison.

---

### Task 1: Canonicalize HTML and PDF Evidence Text

**Files:**
- Modify: `neos/workflow/deep_analysis/text_norm.py`
- Modify: `neos/workflow/deep_analysis/fetch.py`
- Modify: `neos/workflow/deep_analysis/pdf_text.py`
- Test: `tests/workflow/deep_analysis/test_fetch.py`
- Test: `tests/workflow/deep_analysis/test_pdf_text.py`

**Interfaces:**
- Produces: `normalize_evidence_text(value: str) -> str`.
- Consumes: raw text extracted by `_TextExtractor` and PyMuPDF pages.

- [ ] **Step 1: Write failing HTML and hash regressions**

Add these tests to `test_fetch.py`:

```python
def test_html_to_text_removes_nul_before_normalizing():
    text = html_to_text("<p>A\x00B cafe\u0301</p>")

    assert text == "AB café"
    assert "\x00" not in text


@pytest.mark.asyncio
async def test_nul_and_sanitized_html_share_canonical_hash():
    nul = await fetch_url(
        "https://nul.example", client=FakeHttpClient(200, "<p>A\x00B</p>")
    )
    clean = await fetch_url(
        "https://clean.example", client=FakeHttpClient(200, "<p>AB</p>")
    )

    assert nul.raw_text == clean.raw_text == "AB"
    assert nul.content_hash == clean.content_hash
```

- [ ] **Step 2: Write the failing PDF regression**

Extend the existing PDF normalization test input to include NUL:

```python
document = FakeDocument(["  First\npage\x00  ", "cafe\u0301\tsecond"])
```

Keep the expected result `"First page café second"` and document-close
assertion unchanged.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
.venv/bin/pytest \
  tests/workflow/deep_analysis/test_fetch.py::test_html_to_text_removes_nul_before_normalizing \
  tests/workflow/deep_analysis/test_fetch.py::test_nul_and_sanitized_html_share_canonical_hash \
  tests/workflow/deep_analysis/test_pdf_text.py::test_pdf_bytes_to_text_normalizes_pages_and_closes \
  -q
```

Expected: HTML/PDF text retains `\x00`, and NUL/clean content hashes differ.

- [ ] **Step 4: Add the shared normalization helper**

In `text_norm.py` add:

```python
def normalize_evidence_text(value: str) -> str:
    """Return database-safe canonical source text."""

    without_nul = value.replace("\x00", "")
    normalized = unicodedata.normalize("NFC", without_nul)
    return _WHITESPACE.sub(" ", normalized).strip()
```

- [ ] **Step 5: Route both extraction paths through the helper**

In `fetch.py`, import `normalize_evidence_text`, replace the local
whitespace/NFC operations in `html_to_text()`, and remove now-unused imports.

In `pdf_text.py`, import `normalize_evidence_text`, call it on joined page
text, delete `_normalize_text()`, and remove now-unused imports. Preserve the
existing `try`/`except`/`finally` boundaries exactly.

- [ ] **Step 6: Verify GREEN and adjacent regressions**

Run:

```bash
.venv/bin/pytest \
  tests/workflow/deep_analysis/test_fetch.py \
  tests/workflow/deep_analysis/test_pdf_text.py \
  tests/workflow/deep_analysis/test_worker.py \
  tests/workflow/deep_analysis/test_deterministic_grader.py \
  -q -o log_cli=false --disable-warnings
```

Expected: 33 tests pass.

Run:

```bash
.venv/bin/ruff check \
  neos/workflow/deep_analysis/text_norm.py \
  neos/workflow/deep_analysis/fetch.py \
  neos/workflow/deep_analysis/pdf_text.py \
  tests/workflow/deep_analysis/test_fetch.py \
  tests/workflow/deep_analysis/test_pdf_text.py
```

Expected: Ruff reports no errors.

- [ ] **Step 7: Commit**

```bash
git add \
  neos/workflow/deep_analysis/text_norm.py \
  neos/workflow/deep_analysis/fetch.py \
  neos/workflow/deep_analysis/pdf_text.py \
  tests/workflow/deep_analysis/test_fetch.py \
  tests/workflow/deep_analysis/test_pdf_text.py
git commit -m "fix(deep-analysis): remove NUL from fetched evidence"
```

---

### Task 2: Integrate and Obtain a Complete Repeat Sample

**Files:**
- Modify after a complete measurement: `docs/TODO_260729.md`
- Generate: `artifacts/deep-analysis-funnel/<timestamp>/manifest.json`
- Generate: `artifacts/deep-analysis-funnel/<timestamp>/funnel.json`
- Generate: `artifacts/deep-analysis-funnel/<timestamp>/report.md`

**Interfaces:**
- Consumes: the existing bounded `scripts/deep_analysis_funnel_sample.py` runner.
- Produces: five completed `dev` runs plus one completed selected `default` run.

- [ ] **Step 1: Verify and merge into latest local `dev`**

Re-run Task 1 Step 6, merge `codex/deep-analysis-nul-normalization` into local
`dev` without staging unrelated user files, then repeat Task 1 Step 6 from the
main checkout.

- [ ] **Step 2: Run a fresh bounded sample locally**

Because the agent environment cannot transmit prompts to external providers,
the user runs:

```bash
cd /Users/ywsung/Desktop/neos
.venv/bin/python scripts/deep_analysis_funnel_sample.py \
  --output-root artifacts/deep-analysis-funnel
```

- [ ] **Step 3: Validate completeness and safety**

Require all of the following before comparison:

```text
question_set_version == mixed-v1
five dev_runs have status == completed
default_run.status == completed
every confidence_clamped_count equals its four-bucket sum
no disallowed content or secret key appears in manifest/funnel artifacts
```

If any run fails, retain the artifact as diagnostic evidence and do not compare
its aggregate funnel as a full five-case observation.

- [ ] **Step 4: Compare and document**

For a complete artifact only, compare it with `20260720T142912Z` and
`20260720T180738Z`: completed status, verified/rejected/unverified ratios,
confidence clamp buckets, reject-code counts, evidence missing/source dead
rates, and matched per-case dev behavior. State provider variability and avoid
causal claims from two post-change observations.

- [ ] **Step 5: Commit documentation only**

```bash
git add docs/TODO_260729.md
git commit -m "docs: record repeated calibration sample"
```

Do not commit generated artifacts unless repository tracking policy changes.
