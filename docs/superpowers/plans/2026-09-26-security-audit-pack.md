# security-audit Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the Cloudflare security-audit skill on Neos as one markdown pack plus two read-only subagent leaves, so the coding agent can load the workflow and spawn hunter/verifier children.

**Architecture:** Univer-shaped pack at `skills/security-audit/security-audit/SKILL.md` indexed by `security_audit_catalog()`. Coding catalog lists one index skill `security-audit`. `load_skill.v1` prefers the pack body for that name. Specs `security-audit-research` and `security-audit-general` are RO leaves. No ParentKind.

**Tech Stack:** Python 3, pytest (`pytest.mark.no_db`), existing `MarkdownSkillCatalog` and `SubagentRuntime`.

**Spec:** `docs/security-audit/spec/SECURITY_AUDIT_NEOS_MIGRATION_SPEC.md` and `docs/security-audit/spec/02-skills.md`.

## Global Constraints

- Port set is one skill: `security-audit`. Companion `.md` files are references, not catalog names.
- `default_skill_roots()` stays coding-only. `research_skill_roots()` does not gain `skills/security-audit` as a root.
- Do not wrap as `BaseSkill`. No `neos.security_audit` package.
- Coding `_load_skill` may resolve the pack name. It must still deny `pdf`, `xlsx-author`, `univer-sheets-headless`, `k-skill-setup`.
- `list_skills()` includes `security-audit` and does not include `HUNTING` or `RECONNAISSANCE`.
- Source clone is `/Users/yeonwoosung/Desktop/security-audit-skill`. Copy files; do not submodule.
- pytest via `.venv/bin/pytest`. TDD. Commit on `dev` with conventional English subject + short body. Do not push.
- Local autouse `Settings()` teardown ERROR is pre-existing.

## Review Focus

- Coding prompt must not grow by companion leaf names.
- FSI `xlsx-author` and Univer names stay `unknown_skill` on coding `load_skill.v1`.
- SOURCE.md sibling path, never `/Users/`.
- Directory name equals YAML `name`.
- `explore` is not used as a hunter (`can_spawn` stays a reason we added kebabs).
- Stepper must not send FSI system prompts to `security-audit-*`.

---

### Task 1: Catalog constructors

**Files:**
- Create: `tests/security_audit/test_skill_catalog.py`
- Modify: `neos/skills/markdown_catalog.py`

- [ ] Write failing tests for roots, isolation, empty catalog until vendor
- [ ] Run to verify fail
- [ ] Add constructors next to `k_skill_catalog()`
- [ ] Tests pass
- [ ] Commit `feat(skills): add security_audit_catalog roots`

### Task 2: Vendor the pack

**Files:**
- Create: `scripts/vendor_security_audit.py`
- Create: `skills/security-audit/**`

- [ ] Vendor script copies nested child, `references/`, LICENSE, SOURCE.md
- [ ] Run the script against `../security-audit-skill`
- [ ] Commit `feat(security-audit): vendor markdown skill pack`

### Task 3: Pack tests

**Files:**
- Create: `tests/security_audit/test_skill_pack.py`

- [ ] Pin count 1, dir=name, SOURCE.md, references, no `/Users/`
- [ ] Commit `test(security-audit): pin vendored pack`

### Task 4: Coding index

**Files:**
- Create: `neos/coding/skills/security-audit.md`
- Modify: `tests/security_audit/test_skill_catalog.py`

- [ ] Index with exact ATX sections
- [ ] Prompt lists `- security-audit:` and not `- HUNTING:`
- [ ] Commit `feat(coding): add security-audit index skill`

### Task 5: load_skill fallback

**Files:**
- Modify: `neos/coding/tools/executor.py`
- Create: `tests/security_audit/test_load_skill.py`

- [ ] Pack body for `security-audit`; `reference=RECONNAISSANCE.md`; deny foreign names
- [ ] Commit `feat(coding): load security-audit pack body`

### Task 6: Subagent specs

**Files:**
- Modify: `neos/subagent/catalog.py`, `neos/subagent/metrics.py`, `neos/subagent/stepper.py`, `neos/subagent/prompts.py` (or adjacent)
- Create: `tests/security_audit/test_subagent_specs.py`

- [ ] Two kebabs, can_spawn False, RO tools, stepper JSON prompt, metrics labels
- [ ] Commit `feat(subagent): add security-audit leaves`

### Task 7: Coding spawn allow

**Files:**
- Modify: `neos/coding/loop/_durable/spawn.py`
- Create or extend spawn tests

- [ ] Allow the two kebabs; still deny `fsi-*` / `univer-*`
- [ ] Commit `feat(coding): spawn security-audit specs`
