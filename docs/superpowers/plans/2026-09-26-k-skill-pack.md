# k-skill Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the NomaDamas k-skill locale pack on Neos as 125 markdown skills plus a coding index, so coding `load_skill.v1` can open Korean public-data recipes.

**Architecture:** Univer-shaped pack at `skills/k-skill/<name>/SKILL.md` indexed by `k_skill_catalog()`. Coding catalog lists one index skill `k-skill`. Coding executor falls back to `k_skill_catalog()` after `default_catalog()` misses. No ParentKind, no proxy port, no BaseSkill.

**Tech Stack:** Python 3, pytest (`pytest.mark.no_db`), existing `MarkdownSkillCatalog`.

**Spec:** `docs/k-skill/spec/K_SKILL_NEOS_MIGRATION_SPEC.md` and `docs/k-skill/spec/02-skills.md`.

## Global Constraints

- Port set is the 125 names in `docs/k-skill/spec/02-skills.md` §4. Exclude `k-skill-setup` and `k-skill-cleaner`.
- `default_skill_roots()` stays coding-only. `research_skill_roots()` does not gain `skills/k-skill` as a root.
- Do not wrap as `BaseSkill`. Do not add a `neos.kskill` package. Constructors live in `neos/skills/markdown_catalog.py`.
- Composed `SKILL.md` = `skill.json` frontmatter + `instruction.md` body. Not the generated CLI stub (`k-skill:cli-stub`).
- Coding `_load_skill` may resolve k-skill pack names. It must still deny `pdf`, `xlsx-author`, `univer-sheets-headless`, `k-skill-setup`.
- `list_skills()` includes `k-skill` and does not include `korea-weather`.
- Source clone is `/Users/yeonwoosung/Desktop/k-skill`. Copy files into this repo; do not submodule.
- pytest via `.venv/bin/pytest`. TDD. Commit on `dev` with conventional English subject + short body. Do not push.
- Local autouse `Settings()` teardown ERROR is pre-existing.

## Review Focus

- Coding prompt must not grow by 125 skill lines.
- FSI `xlsx-author` and Univer `univer-sheets-headless` stay `unknown_skill` on coding `load_skill.v1`.
- Pack SKILL.md must contain instruction workflow text (e.g. `k-skill-proxy` or site steps), not only `npx ... instruct`.
- Directory name equals YAML `name` for every vendored skill.
- `consumer-price-safety-search` is included even though phase is draft.

---

### Task 1: Catalog constructors

**Files:**
- Create: `tests/k_skill/test_skill_catalog.py`
- Modify: `neos/skills/markdown_catalog.py`

**Interfaces:**
- Consumes: `MarkdownSkillCatalog`, `default_skill_roots`, `research_skill_roots`, `FSI_PACK`, `UNIVER_PACK`
- Produces: `K_SKILL_PACK`, `K_SKILL_EXCLUDED`, `k_skill_roots()`, `k_skill_catalog()`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
import pytest
from neos.skills.markdown_catalog import (
    default_catalog,
    default_skill_roots,
    research_skill_roots,
)
pytestmark = pytest.mark.no_db
REPO_ROOT = Path(__file__).resolve().parents[2]

def test_k_skill_roots_are_the_pack_directory() -> None:
    from neos.skills.markdown_catalog import K_SKILL_PACK, k_skill_roots
    roots = k_skill_roots()
    assert roots == (("repo", K_SKILL_PACK),)
    assert K_SKILL_PACK == REPO_ROOT / "skills" / "k-skill"

def test_default_and_research_roots_do_not_include_k_skill_pack() -> None:
    from neos.skills.markdown_catalog import K_SKILL_PACK
    pack = K_SKILL_PACK.resolve()
    for _source, path in default_skill_roots():
        assert path.resolve() != pack
    for _source, path in research_skill_roots():
        assert path.resolve() != pack

def test_coding_catalog_does_not_index_korea_weather() -> None:
    assert default_catalog().get("korea-weather") is None
```

- [ ] **Step 2: Run to verify fail** — `.venv/bin/pytest tests/k_skill/test_skill_catalog.py -q` ImportError
- [ ] **Step 3: Add constructors** next to `univer_catalog()`
- [ ] **Step 4: Tests pass**
- [ ] **Step 5: Commit** `feat(skills): add k_skill_catalog roots`

---

### Task 2: Vendor 125 skills

**Files:**
- Create: `skills/k-skill/LICENSE`, `skills/k-skill/SOURCE.md`, `skills/k-skill/<name>/...`
- Create: `scripts/vendor_k_skill.py` (one-shot composer; keep it — CI/humans re-run against `../k-skill`)

**Interfaces:**
- Consumes: sibling `../k-skill/<name>/{skill.json,instruction.md,...}`
- Produces: 125 child dirs, composed SKILL.md, no setup/cleaner dirs

- [ ] **Step 1: Write failing pack tests** in `tests/k_skill/test_skill_pack.py` asserting `len(k_skill_catalog().list_skills()) == 125` and `korea-weather` body contains instruction text and not `k-skill:cli-stub`
- [ ] **Step 2: Watch fail** (catalog empty)
- [ ] **Step 3: Run vendor script** composing SKILL.md from frontmatter + instruction.md; copy sidecar files; write LICENSE + SOURCE.md
- [ ] **Step 4: Tests pass**
- [ ] **Step 5: Commit** `feat(k-skill): vendor 125 markdown skills`

---

### Task 3: Coding index skill

**Files:**
- Create: `neos/coding/skills/k-skill.md`
- Modify: `tests/k_skill/test_skill_catalog.py` (coding list includes `k-skill`, excludes `korea-weather`)

- [ ] **Step 1: Failing test** `assert default_catalog().get("k-skill") is not None` and `korea-weather` still None
- [ ] **Step 2: Watch fail**
- [ ] **Step 3: Write `k-skill.md` with `## When to Use` / `## Boundaries`**
- [ ] **Step 4: Tests pass**
- [ ] **Step 5: Commit** `feat(coding): add k-skill index skill`

---

### Task 4: Coding load_skill fallback

**Files:**
- Create: `tests/coding/tools/test_k_skill_load.py`
- Modify: `neos/coding/tools/executor.py` `_load_skill`

**Interfaces:**
- Consumes: `default_catalog()`, `k_skill_catalog()`
- Produces: ok markdown for `korea-weather`; denied for `pdf`, `xlsx-author`, `univer-sheets-headless`, `k-skill-setup`

- [ ] **Step 1: Write failing tests** calling `SandboxToolExecutor.execute` like `test_load_skill_verify_returns_bundled_markdown`
- [ ] **Step 2: Watch `korea-weather` fail with unknown_skill**
- [ ] **Step 3: Fallback in `_load_skill`**
- [ ] **Step 4: Tests pass including existing executor load_skill tests**
- [ ] **Step 5: Commit** `feat(coding): load k-skill pack names`

---

### Task 5: Docs already written

Inventory + spec live under `docs/k-skill/`. If any path drifted during implementation, update `02-skills.md` in the same commit as the drift. Do not commit a separate docs-only fix unless the spec is wrong.
