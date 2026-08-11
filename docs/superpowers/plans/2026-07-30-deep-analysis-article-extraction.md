# Deep Analysis Article Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract article body text instead of whole-page text in the deep-analysis fetch path, so workers stop receiving navigation menus as evidence.

**Architecture:** One new function in `fetch.py` tries `trafilatura.extract` and falls back to the existing `html_to_text` when it yields nothing. Both paths pass through the same `normalize_evidence_text` the current code already applies, so content hashing and quote matching keep their existing contract. The PDF and non-2xx branches are untouched.

**Tech Stack:** Python 3.12, trafilatura (already a declared dependency), pytest, Ruff.

**Design spec:** `docs/superpowers/specs/2026-07-30-deep-analysis-article-extraction-design.md` (Korean; this plan is self-contained).

## Global Constraints

- **Do not change `quote_match_threshold`** (0.92) or any other grader threshold, sampling rate, prompt, model, or cap. Changing extraction and a threshold together makes the effect unattributable.
- **Both extraction paths must pass through `normalize_evidence_text`.** It feeds `_content_hash` and quote matching. Returning un-normalized text silently changes hashing behaviour.
- **The fallback must never make a page worse than today.** When trafilatura returns nothing, the result must be exactly what `html_to_text` returns now.
- **`html_to_text` stays.** It is the fallback. Do not delete it, do not weaken its existing tests.
- **Do not touch** the PDF branch, the non-2xx branch, `neos/agents/analysis_agents.py`, or any grader.
- **No network and no LLM in tests.** Fixture HTML strings only.
- **No live run.** Executing a sample is explicitly out of scope for this plan.
- **No new dependencies.** `trafilatura>=2.0.0` is already in `pyproject.toml`.
- Test command: `HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest ... -q -o log_cli=false --disable-warnings`. Bare `pytest` fails asyncio marker collection.

## Out of Scope

Establishing a new baseline and re-measuring discard recall. Both need live runs and get handled after this lands, in the order recorded in the spec: extraction change → new 5+1 baseline → discard-recall re-measurement.

## File Structure

| File | Responsibility |
|---|---|
| `neos/workflow/deep_analysis/fetch.py` | Add `extract_article_text`; call it from `produce()`'s HTML branch |
| `tests/workflow/deep_analysis/test_fetch.py` | Cover the trafilatura path, the fallback path, and normalization on both |
| `docs/TODO_260729.md` | Record the baseline break and the required follow-up order |

---

### Task 1: Add `extract_article_text` with a fallback

**Files:**
- Modify: `neos/workflow/deep_analysis/fetch.py`
- Test: `tests/workflow/deep_analysis/test_fetch.py`

**Interfaces:**
- Produces: `extract_article_text(html: str) -> str` in `neos.workflow.deep_analysis.fetch`. Returns normalized article text, or normalized whole-page text when trafilatura yields nothing.

- [ ] **Step 1: Write the failing tests**

Add to `tests/workflow/deep_analysis/test_fetch.py`. Match the file's existing import and fixture style.

```python
_NAV_PAGE = """
<html><body>
  <nav><ul><li>Home</li><li>About</li><li>Contact</li><li>Privacy Policy</li></ul></nav>
  <header>Cookie banner: we value your privacy</header>
  <article>
    <h1>Article 55: Obligations of providers</h1>
    <p>Providers of general-purpose AI models with systemic risk shall perform
    model evaluation in accordance with standardised protocols and document the
    results, and shall assess and mitigate possible systemic risks at Union level.</p>
  </article>
  <footer>Copyright 2026. All rights reserved. Terms of service.</footer>
</body></html>
"""


def test_extract_article_text_drops_navigation_and_keeps_body():
    text = extract_article_text(_NAV_PAGE)

    assert "systemic risk" in text
    assert "Obligations of providers" in text
    # boilerplate must not survive into evidence
    assert "Privacy Policy" not in text
    assert "Terms of service" not in text
    assert "Cookie banner" not in text


def test_extract_article_text_falls_back_when_trafilatura_finds_nothing():
    # No article structure for trafilatura to latch onto.
    html = "<html><body><nav>Home About</nav></body></html>"

    text = extract_article_text(html)

    # Fallback is html_to_text, so its output is what we must get.
    assert text == html_to_text(html)


def test_extract_article_text_normalizes_both_paths():
    spaced = """
    <html><body><article><p>Alpha    beta
    gamma</p></article></body></html>
    """

    text = extract_article_text(spaced)

    # normalize_evidence_text collapses runs of whitespace; no raw newlines
    # or double spaces may reach the content hash.
    assert "  " not in text
    assert "\n" not in text
```

Import `extract_article_text` and `html_to_text` at the top of the test file.

- [ ] **Step 2: Run tests to verify they fail**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_fetch.py -q -o log_cli=false --disable-warnings
```
Expected: FAIL with `ImportError: cannot import name 'extract_article_text'`.

- [ ] **Step 3: Implement the function**

In `neos/workflow/deep_analysis/fetch.py`, add after `html_to_text` (which ends at line 39). Put the `trafilatura` import at module top with the other imports.

```python
def extract_article_text(html: str) -> str:
    """Article body text, falling back to whole-page text.

    ``html_to_text`` concatenates every text node, so navigation, headers,
    footers and cookie banners arrive as evidence next to the article. That
    buried real article text deeply enough that workers reported pages as
    containing only navigation. trafilatura strips the boilerplate.

    It returns nothing on roughly 3% of pages, so those fall back to
    ``html_to_text`` — the result is then exactly today's behaviour, which
    keeps this change from making any page worse.
    """
    try:
        extracted = trafilatura.extract(html)
    except Exception:  # noqa: BLE001 - extractor must never break a fetch
        extracted = None
    if extracted and extracted.strip():
        return normalize_evidence_text(extracted)
    return html_to_text(html)
```

`fetch.py` currently has **no module logger** (verified). Do not add one for this — the fallback behaviour is what matters, and the 3% rate is already measured in the spec. Keep the module's dependency surface as small as it is.

Note that `html_to_text` already applies `normalize_evidence_text` (`fetch.py:39`), so the fallback path is normalized by construction; the trafilatura path needs the explicit call shown above.

- [ ] **Step 4: Run tests to verify they pass**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_fetch.py -q -o log_cli=false --disable-warnings
```
Expected: PASS, including the file's pre-existing tests.

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/deep_analysis/fetch.py tests/workflow/deep_analysis/test_fetch.py
git commit -m "feat(deep-analysis): extract article text instead of whole-page text"
```

---

### Task 2: Route the fetch path through it, and record the baseline break

**Files:**
- Modify: `neos/workflow/deep_analysis/fetch.py` (the `produce()` HTML branch)
- Modify: `docs/TODO_260729.md`
- Test: `tests/workflow/deep_analysis/test_fetch.py`

**Interfaces:**
- Consumes: `extract_article_text` from Task 1.

- [ ] **Step 1: Write the failing test**

`fetch_url` accepts an injected `client`, so this needs no network. `test_fetch.py:36` already defines `FakeHttpClient(status_code, body, headers=None)` — reuse it, do not write a second fake.

```python
@pytest.mark.asyncio
async def test_fetch_url_stores_article_text_not_navigation():
    client = FakeHttpClient(200, _NAV_PAGE)

    blob = await fetch_url("https://example.com/article-55", client=client)

    assert "systemic risk" in blob.raw_text
    assert "Privacy Policy" not in blob.raw_text
    assert "Terms of service" not in blob.raw_text
    assert blob.http_status == 200
```

`FakeHttpClient` defaults `headers` to `{}`, so `_is_pdf_response` sees no
`content-type` and the HTML branch is taken — which is the branch under test.

Also assert the PDF branch is untouched: if `test_fetch.py` has a PDF test, confirm it still passes unchanged. Do not modify it.

- [ ] **Step 2: Run tests to verify the new one fails**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_fetch.py -q -o log_cli=false --disable-warnings
```
Expected: the new test FAILS because `raw_text` still contains `Privacy Policy`.

- [ ] **Step 3: Switch the HTML branch**

In `produce()` inside `fetch_url` (`fetch.py:~103`), change only the HTML line:

```python
            else:
                raw_text = extract_article_text(response.text)
```

Leave the `not 200 <= status < 300` branch and the `_is_pdf_response` branch exactly as they are.

- [ ] **Step 4: Run the full deep-analysis suite**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/ -q -o log_cli=false --disable-warnings
```
Expected: all pass. The baseline before this plan is **411 passed**; expect 411 plus the new tests.

**If a pre-existing test now fails**, do not adjust it to fit. Report it — a test that depended on whole-page text is telling you something about what else consumed that text, and I need to know before it is silenced.

- [ ] **Step 5: Record the baseline break**

Append to the §7 discard-recall section of `docs/TODO_260729.md`, in Korean to match the document:

- extraction switched to trafilatura with an `html_to_text` fallback, on this date, with the commit SHA;
- **`20260723T124006Z` (prompt v3), `20260725T081707Z` (entailment), and `20260729T131543Z` are all pre-change and are not comparable to anything produced afterwards**;
- restored baseline figures remain in `docs/deep_analysis_funnel_baselines.json`;
- the required order from here: new `mixed-v1` 5+1 → new baseline → only then re-measure discard recall using `docs/superpowers/plans/2026-07-28-deep-analysis-discard-recall-measurement.md`;
- `quote_match_threshold` was deliberately left at 0.92, so any change in quote-mismatch rates in the next sample is attributable to extraction alone.

- [ ] **Step 6: Lint and commit**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  neos/workflow/deep_analysis/ tests/workflow/deep_analysis/

git add neos/workflow/deep_analysis/fetch.py \
        tests/workflow/deep_analysis/test_fetch.py docs/TODO_260729.md
git commit -m "feat(deep-analysis): fetch article text and record the baseline break"
```

Expected: Ruff clean. 12 pre-existing `F541` errors in `scripts/test_document_upload.py` are unrelated — do not fix them.

Do not add a `Co-Authored-By` trailer to either commit.

---

## Done When

- `fetch_url` stores article body text for HTML pages, with navigation and footers absent.
- A page trafilatura cannot parse yields exactly what `html_to_text` returns today.
- Both paths are normalized through `normalize_evidence_text`.
- The PDF and non-2xx branches are unchanged, and `html_to_text` keeps its own tests.
- `docs/TODO_260729.md` records the baseline break and the follow-up order.
- Full deep-analysis suite green, Ruff clean, `quote_match_threshold` untouched.
