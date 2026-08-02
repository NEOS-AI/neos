# Deep Analysis Fetch User-Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send a descriptive, identifiable `User-Agent` when the deep-analysis fetcher creates its own HTTP client, so sites that block unidentified clients become reachable.

**Architecture:** A configurable UA string in `neos/config/schema.py`, applied as a default header only on the client `fetch_url` constructs itself. An injected client is left alone. The header is also recorded in the sample-run config fingerprint, since it changes which pages are reachable.

**Tech Stack:** Python 3.12, httpx, pytest, Ruff.

## Background

The 07-31 run's cassette shows **23 of 204 fetches returned HTTP 403** (plus 2 rate limits). `fetch.py` sets no `User-Agent`, so httpx's default (`python-httpx/x.y`) is sent and widely blocked. Non-2xx becomes an empty `raw_text`, so the worker sees "empty content" and blames the source.

Retrying six of the blocked URLs with only the UA changed:

| URL | current (no UA) | browser-like | descriptive bot |
|---|---|---|---|
| en.wikipedia.org ×2 | 403 | 403 | **200** |
| europeanmovement.eu | 403 | **200** | **200** |
| financialfragrance.com | 403 | **200** | 500 |
| main.un.org | 403 | **200** | 403 |
| medium.com | 403 | 403 | 403 |

The current configuration is the worst case — all six blocked.

## Global Constraints

- **Use a descriptive bot User-Agent that identifies the client and gives a contact URL. Do NOT use a browser-like string.** A site blocking bots is expressing a preference; a Chrome string circumvents it rather than satisfying it. Wikipedia — the most valuable source in this set — explicitly requires honest identification and rejects browser strings, and returns 200 for a descriptive UA. Sites that still decline (medium.com declines everything tried) are respected. Do not add cookies, referrer spoofing, proxy rotation, or any other block-evasion technique.
- **Change exactly one variable.** Do not alter extraction, `quote_match_threshold`, any grader threshold, prompt, model, sampling rate, cap, or retry behaviour. The next sample must attribute any 403 reduction to the UA alone.
- **Do not change the non-2xx handling.** `raw_text = ""` for non-2xx stays as it is. Making blocking visible to the worker was considered and deliberately deferred — it would change the text workers see and confound the measurement.
- **No magic strings.** The UA lives in `neos/config/schema.py`, not inline in `fetch.py`.
- **Only the client `fetch_url` creates.** When a caller injects a `client`, leave it untouched — tests and other callers own their own configuration.
- **No new dependencies. No network in tests.**
- No `Co-Authored-By` trailer.
- Test command: `HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest ... -q -o log_cli=false --disable-warnings`. Bare `pytest` fails asyncio marker collection.

## Out of Scope

- Retry/backoff for the 2 observed HTTP 429s. Worth watching once more sites become reachable, but it is a second variable.
- Recording search/fetch outcomes in the ledger. Real gap — this diagnosis was only possible because a cassette existed — but separate work.
- Any live run. Measuring the effect needs a new sample and is a separate, explicitly authorised step.

## File Structure

| File | Responsibility |
|---|---|
| `neos/config/schema.py` | `fetch_user_agent` setting on `DeepAnalysisConfig` |
| `neos/workflow/deep_analysis/fetch.py` | Apply it as a default header on the self-constructed client |
| `scripts/deep_analysis_funnel_sample.py` | Record it in the config fingerprint |
| `tests/workflow/deep_analysis/test_fetch.py` | Prove the header is set, and that an injected client is untouched |

---

### Task 1: Configurable descriptive User-Agent on the self-constructed client

**Files:**
- Modify: `neos/config/schema.py` (`DeepAnalysisConfig`)
- Modify: `neos/workflow/deep_analysis/fetch.py` (the `owns_client` branch, around line 131-139)
- Modify: `scripts/deep_analysis_funnel_sample.py` (`_fingerprint`)
- Test: `tests/workflow/deep_analysis/test_fetch.py`

**Interfaces:**
- Produces: `settings.config.deep_analysis.fetch_user_agent: str`
- Produces: `_build_fetch_client()` in `neos.workflow.deep_analysis.fetch` — returns the configured `httpx.AsyncClient`. Extracted so the header is testable without a network call.

- [ ] **Step 1: Add the setting**

In `neos/config/schema.py`, add to `DeepAnalysisConfig` beside the other fetch settings (`fetch_timeout_seconds`):

```python
    # Identifies this client to the sites it fetches. Deliberately a
    # descriptive bot string, not a browser string: sites that block bots are
    # expressing a preference, and impersonating a browser circumvents it.
    # Wikipedia requires an identifiable UA and returns 403 for browser-like
    # strings; it returns 200 for this one. Deployments should point the
    # contact URL at something they actually monitor.
    fetch_user_agent: str = (
        "NEOS-DeepAnalysis/0.23 (+https://github.com/NEOS-AI/neos)"
    )
```

Verify the field name does not already exist, and that `DeepAnalysisConfig` is the right model (it is the one carrying `fetch_timeout_seconds`).

- [ ] **Step 2: Write the failing tests**

Add to `tests/workflow/deep_analysis/test_fetch.py`:

```python
def test_build_fetch_client_sends_a_descriptive_user_agent():
    client = _build_fetch_client()
    try:
        ua = client.headers.get("user-agent", "")
    finally:
        pass  # client is not used for I/O here; closing is the caller's job

    assert ua == settings.config.deep_analysis.fetch_user_agent
    assert ua  # must not be empty
    # A descriptive bot string, not a browser impersonation.
    assert "Mozilla" not in ua
    assert "Chrome" not in ua
    assert "Safari" not in ua
    # Identifiable, with a contact URL.
    assert "NEOS" in ua
    assert "http" in ua


@pytest.mark.asyncio
async def test_fetch_url_does_not_override_an_injected_client():
    # An injected client owns its own configuration; fetch_url must not
    # rewrite its headers.
    client = FakeHttpClient(200, "<html><body><article><p>Body text here that "
                                 "is long enough to extract.</p></article></body></html>")

    blob = await fetch_url("https://example.com/a", client=client)

    assert blob.http_status == 200
    # FakeHttpClient has no headers attribute mutation; the call simply works.
    assert client.calls == 1
```

Import `_build_fetch_client` and `settings` at the top of the test file. Use whatever `settings` import path the rest of the codebase uses (`from neos.config.settings import settings`).

If `client.headers` is not accessible the way the first test assumes, inspect `httpx.AsyncClient`'s actual API and adjust the *retrieval*, not the assertion — the property being tested is that the configured UA is on the client.

- [ ] **Step 3: Run tests to verify they fail**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_fetch.py -q -o log_cli=false --disable-warnings
```
Expected: FAIL with `ImportError: cannot import name '_build_fetch_client'`.

- [ ] **Step 4: Extract the client builder and apply the header**

In `neos/workflow/deep_analysis/fetch.py`, move the `httpx` import to module top with the others, and add above `fetch_url`:

```python
def _build_fetch_client():
    """The HTTP client ``fetch_url`` uses when the caller supplies none.

    The User-Agent is descriptive rather than browser-like on purpose — see
    ``DeepAnalysisConfig.fetch_user_agent``.
    """
    config = settings.config.deep_analysis
    return httpx.AsyncClient(
        timeout=config.fetch_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": config.fetch_user_agent},
    )
```

Then replace the `owns_client` branch inside `produce()` (currently lines 133-139):

```python
        if owns_client:
            resolved_client = _build_fetch_client()
```

Leave everything else in `produce()` alone — the `try`/`finally`, the status handling, the PDF branch, and the extraction call are unchanged.

- [ ] **Step 5: Run tests to verify they pass**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_fetch.py -q -o log_cli=false --disable-warnings
```
Expected: PASS, including the file's pre-existing tests.

- [ ] **Step 6: Prove the test bites**

Temporarily remove the `headers=` argument from `_build_fetch_client`, re-run
`test_build_fetch_client_sends_a_descriptive_user_agent`, and confirm it FAILS. Then restore and re-run.

Record this break-check in your report. On this project two tests have already shipped that passed for the wrong reason, and a break-check is what caught both.

- [ ] **Step 7: Record the UA in the sample fingerprint**

In `scripts/deep_analysis_funnel_sample.py`'s `_fingerprint()`, beside `decompose_max_tokens`:

```python
        "fetch_user_agent": config.fetch_user_agent,
```

It belongs there for the same reason `decompose_max_tokens` does: it changes what a run can reach, so an artifact should record which value produced it.

- [ ] **Step 8: Full suite and lint**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/ -q -o log_cli=false --disable-warnings

/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  neos/workflow/deep_analysis/ neos/config/schema.py \
  scripts/deep_analysis_funnel_sample.py tests/workflow/deep_analysis/
```

Expected: 417 passed plus the new tests, zero failures. Ruff clean — the 12 pre-existing `F541` errors in `scripts/test_document_upload.py` are unrelated; do not fix them.

**If a pre-existing test fails, do not adjust it.** Report it — a test that depended on the client having no headers is telling you something.

- [ ] **Step 9: Commit**

```bash
git add neos/config/schema.py neos/workflow/deep_analysis/fetch.py \
        scripts/deep_analysis_funnel_sample.py tests/workflow/deep_analysis/test_fetch.py
git commit -m "feat(deep-analysis): identify the fetcher with a descriptive user agent"
```

---

## Done When

- `fetch_url`'s self-constructed client sends the configured descriptive UA; an injected client is untouched.
- The UA is a config value, is not browser-like, and carries an identifier and contact URL.
- The sample fingerprint records it.
- The new test provably fails without the header.
- Full deep-analysis suite green, Ruff clean, and nothing else changed.

## Verifying The Effect

Out of scope for this plan, and it needs an explicitly authorised live run. When one happens, the comparison against the 07-31 baseline is: **403 count among fetches** (was 23/204) and **dead-end count** (was 28). Because this plan changes one variable and does not touch extraction or any threshold, a drop in 403s is attributable to the UA. Do not expect all of them to clear — medium.com declined every UA tested, and that is a legitimate answer from the site.
