# FSI + Univer Final Attach Wave Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the merge-status next-wave gaps so FSI and Univer are attached as deep-harness parents with skill catalogs, binding execute, parent spawn sessions, Mode B xlsx staging, and a typed handoff bus — still no HTTP/UI and no Node `@univerjs` pin.

**Architecture:** Keep kebab leaves and `run_leaf`. Add coding-spawn denials, FSI execute-path binding, `fsi_catalog()` plus vendored SKILL.md, parent-only `stage_xlsx.v1` / `handoff.py` / screening stub, `FsiSessionPort` (Univer mirror), and parent `spawn_agent.v1` drivers in `loop.py`. Univer SKILL.md matches the in-memory double; parent `office-session` loads the profile.

**Tech Stack:** Python 3.12, pytest, jsonschema, openpyxl, MarkdownSkillCatalog, SubagentRuntime, existing `tests/fsi/fakes.py` / `tests/univer`.

**Spec:** `docs/financial-services/spec/FSI_NEOS_MIGRATION_SPEC.md` + `00`/`01`/`02` + `agents/kyc-screener.md`; `docs/univer/spec/UNIVER_NEOS_MIGRATION_SPEC.md` + `00`/`01`/`02` + `agents/office-session.md`. Status notes: `docs/financial-services/10-merge-status.md`, `docs/univer/15-merge-status.md`. Locked kernel/completeness plans remain in force.

## Global Constraints

- Work in place on `dev`. Conventional commits (`feat(fsi):` / `feat(univer):` / `feat(coding):` / `test(univer):` / `docs(fsi):`) with a short body. One commit per task.
- TDD: failing test first, watch RED, minimal GREEN, then commit. Do not dispatch nested subagents or reviewers.
- Do not start HTTP `/api/v1/fsi` or `/api/v1/univer`, MS365, or a real Node `@univerjs` sidecar.
- `neos/subagent` ↛ `neos.fsi` ↛ DurableCodingLoop / DA. `neos/subagent` ↛ `neos.univer` ↛ DurableCodingLoop / DA / `neos.fsi`.
- Five kebab FSI specs and four kebab Univer specs stay in module `_SPECS`. Aliases live on session `SpecRegistry` overlay only.
- Flags `FsiConfig.enabled` / `UniverConfig.enabled` default off. Child flags require master.
- Do not add FSI or Univer packs to `default_skill_roots()`. Do not patch `neos/coding/tools/executor.py` for FSI/Univer `load_skill.v1` — session ports only (Univer completeness ruling).
- Do not add `execute.v1` to `FSI_WRITER` (FSI-2 stays unresolved). Mode A writer sandbox stamp `WORKTREE` already exists; this wave binds parent glob + session, not bash-on-writer.
- Partner LSEG/S&P skill trees and wealth-management restore stay out (KD7 / PR15). Copy 48 Anthropic vertical skills excluding `skill-creator`.
- `quoted_json_is_handoff` stays `False`. Success artifact status is `staged_for_signoff`.
- Completeness lock: Univer live engine remains `InMemorySidecar`. Do not add `neos/univer/sidecar/index.js`.
- Do not mutate module `_SPECS`. Do not import `neos.fsi` from `neos/univer`.
- Tests use `pytestmark = pytest.mark.no_db` in FSI/Univer files. Local `Settings()` teardown ERROR is pre-existing — do not “fix” it in this wave.

## Review Focus

- Coding `spawn_agent.v1` with `spec=fsi-writer` / `univer-writer` must not mint a `ParentKind.CODING` ticket even when flags are on.
- FSI parent execute of `approve_onboarding` returns `policy_binding_denied`, never a silent `tool_not_allowed` that looks like an unknown tool.
- `fsi_catalog()` must index nested verticals and stay invisible to `default_catalog()`.
- Parent `stage_xlsx.v1` writes `./out/*.xlsx` while every leaf `write_file.v1` of `*.xlsx` stays `xlsx_forbidden`.
- Univer SKILL.md must describe the in-memory double tools, not `FUniver.save()` / Node presets as the live path.

---

### Task 1: Coding spawn denies FSI and Univer kebabs

**Files:**
- Modify: `neos/coding/loop/_durable/spawn.py` (around the `lookup_spec` block ~792–797)
- Test: `tests/coding/loop/test_spawn_subagent.py`

**Interfaces:**
- Consumes: existing `test_unknown_spawn_spec_is_policy_unknown_spec`, `harness`, `tool_call`, `_flag_on`, `lookup_spec`
- Produces: coding `spawn_agent.v1` with `spec` in `{fsi-reader,fsi-writer,fsi-critic,fsi-puller,fsi-modeler,univer-reader,univer-writer,univer-critic,univer-formula}` returns `policy_unknown_spec` and creates zero subagent runs. `explore` still works. Prefix check is on the raw spec name **before** `lookup_spec`, so flags are irrelevant.

- [ ] **Step 1: Write the failing tests**

Append to `tests/coding/loop/test_spawn_subagent.py`:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "spec_name",
    [
        "fsi-reader",
        "fsi-writer",
        "fsi-critic",
        "fsi-puller",
        "fsi-modeler",
        "univer-reader",
        "univer-writer",
        "univer-critic",
        "univer-formula",
    ],
)
async def test_coding_spawn_refuses_fsi_and_univer_kebabs(spec_name: str) -> None:
    runtime, _child = _make_runtime([_child_tool()])
    h = harness(
        [
            [
                tool_call(
                    "s1",
                    "spawn_agent.v1",
                    {"prompt": "look around", "max_turns": 4, "spec": spec_name},
                ),
                completed(),
            ]
        ],
        config=_flag_on(),
        subagents=runtime,
    )
    events = await collect(h)
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    result = completed_events[-1].payload["result"]
    assert result["status"] == "error"
    assert result["reason_code"] == "policy_unknown_spec"
    assert len(_subagent_store(runtime)._runs) == 0
```

Copy helpers already used by `test_unknown_spawn_spec_is_policy_unknown_spec` (`_make_runtime`, `_child_tool`, `_subagent_store`). Do not add a new test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/coding/loop/test_spawn_subagent.py::test_coding_spawn_refuses_fsi_and_univer_kebabs -v`
Expected: FAIL because `lookup_spec("fsi-reader")` succeeds and a CODING ticket is minted.

- [ ] **Step 3: Write minimal implementation**

In `spawn.py`, after `spec_name = str(raw.get("spec") or "explore")` and **before** `lookup_spec`:

```python
if spec_name.startswith("fsi-") or spec_name.startswith("univer-"):
    return self._spawn_tool_error(bound, "policy_unknown_spec")
```

Do not import `neos.fsi` or `neos.univer`. Do not change stepper prompt routing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/coding/loop/test_spawn_subagent.py::test_coding_spawn_refuses_fsi_and_univer_kebabs tests/coding/loop/test_spawn_subagent.py::test_unknown_spawn_spec_is_policy_unknown_spec -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add neos/coding/loop/_durable/spawn.py tests/coding/loop/test_spawn_subagent.py
git commit -m "$(cat <<'EOF'
feat(coding): refuse FSI and Univer kebabs on coding spawn

Coding spawn_agent.v1 must not mint ParentKind.CODING tickets for
fsi-* or univer-* catalog names. Flags are not a kill switch here.
EOF
)"
```

---

### Task 2: FSI execute-path binding denylist

**Files:**
- Modify: `neos/fsi/ports.py`
- Test: `tests/fsi/test_ports.py` (or new `tests/fsi/test_binding_execute.py` if ports file is already large — prefer extending `test_ports.py`)

**Interfaces:**
- Consumes: `neos.fsi.safety.policy_binding_denied`, `binding_error`, `BINDING_ACTIONS`
- Produces: `FsiParentWorkspacePort.execute` (and later `FsiSessionPort`) returns `{"ok": False, "error": "policy_binding_denied", "action": <name>}` when `name` is in `BINDING_ACTIONS`. Unknown non-binding names stay `tool_not_allowed`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_approve_onboarding_is_policy_binding_denied(tmp_path: Path) -> None:
    from neos.fsi.ports import FsiParentWorkspacePort
    port = FsiParentWorkspacePort(tmp_path, write=False)
    result = await port.execute("approve_onboarding", {})
    assert result["ok"] is False
    assert result["error"] == "policy_binding_denied"
    assert result["action"] == "approve_onboarding"


@pytest.mark.asyncio
async def test_unknown_tool_stays_tool_not_allowed(tmp_path: Path) -> None:
    from neos.fsi.ports import FsiParentWorkspacePort
    port = FsiParentWorkspacePort(tmp_path, write=False)
    result = await port.execute("not_a_tool.v1", {})
    assert result == {"ok": False, "error": "tool_not_allowed"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fsi/test_ports.py::test_approve_onboarding_is_policy_binding_denied -v`
Expected: FAIL (`tool_not_allowed` today)

- [ ] **Step 3: Write minimal implementation**

Mirror Univer `_binding_denied`: at the top of `FsiParentWorkspacePort.execute`, if `policy_binding_denied(name)` return `{**binding_error(name), "ok": False}`. Import from `neos.fsi.safety`. Check binding **before** the definitions membership test.

- [ ] **Step 4: GREEN + existing port tests**

Run: `python -m pytest tests/fsi/test_ports.py tests/fsi/test_safety_policy.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add neos/fsi/ports.py tests/fsi/test_ports.py
git commit -m "$(cat <<'EOF'
feat(fsi): deny binding actions on the execute path

Approve-onboarding and other BINDING_ACTIONS return
policy_binding_denied instead of a generic tool_not_allowed.
EOF
)"
```

---

### Task 3: Univer SKILL.md matches the in-memory double

**Files:**
- Modify: `skills/univer/univer-sheets-headless/SKILL.md`
- Modify: `skills/univer/univer-docs-headless/SKILL.md`
- Modify: `skills/univer/univer-formula-audit/SKILL.md`
- Modify: `skills/univer/univer-qc/SKILL.md`
- Test: `tests/univer/test_skills.py` (create if missing; else extend)

**Interfaces:**
- Consumes: `univer_catalog()`, `InMemorySidecar` tool names
- Produces: each SKILL.md states live runtime is Python `InMemorySidecar`; structured tools `univer.inspect.v1` / `range_get` / `range_set` / `execute_command` / `formula_wait` / `save`; Node `@univerjs` presets are deferred. Docs skill describes `doc.command.insert-text` with `{text}` splice, not `FDocument.insertText` as the live path. Formula skill lists SUM/IF/arithmetic and `#NAME?` for other functions.

- [ ] **Step 1: Write failing tests** that `univer_catalog().load_markdown(name)` contains `InMemorySidecar` and `univer.save.v1`, and does **not** tell the agent to call `FUniver.newAPI` or `preset-sheets-node-core` as the live boot path. Pin `univer-docs-headless` mentions `doc.command.insert-text`. Pin `univer-formula-audit` mentions `SUM` and `#NAME?`.

- [ ] **Step 2: RED** — current Facade-oriented SKILL.md fails those assertions.

- [ ] **Step 3: Rewrite the four SKILL.md bodies.** Keep YAML `name` + `description` frontmatter. Do not add `## When to Use` / `## Boundaries`. Do not put the pack on the coding catalog.

- [ ] **Step 4: GREEN** `python -m pytest tests/univer/test_skills.py tests/univer/test_catalog.py -v` (skip missing catalog file if it does not exist; run whatever skill/catalog tests are present plus the new file).

- [ ] **Step 5: Commit** `docs(univer): teach skills the in-memory sidecar contract`

---

### Task 4: Univer double limitation tests

**Files:**
- Modify: `neos/univer/sidecar.py` and/or `neos/univer/ports.py` only if a test proves a harness bug (glob nested matching `draft/nested/foo.json` for `draft/*.json` is a GAP — fix glob to match one path segment for `*` so `draft/*.json` does not match nested files)
- Test: `tests/univer/test_sidecar_tools.py` and `tests/univer/test_ports.py` (extend)

**Interfaces:**
- Consumes: `InMemorySidecar`, `UniverParentWorkspacePort._glob`, `UniverSessionPort`
- Produces: tests that lock current double behavior **and** fix glob nested (jail, not engine completeness):
  1. `SUM` of a `#DIV/0!` cell — document current behavior with an assertion (if it skips/zeros, assert that; do not secretly change the engine unless the test you wrote first required ErrorType propagation — **Ruling:** do not change SUM/IF engine in this task; pin current behavior).
  2. lowercase `if` → `#NAME?`
  3. `unit_kind_mismatch` when a sheet command runs on a doc unit
  4. glob `draft/*.json` does **not** match `draft/nested/foo.json` (this one **is** a fix)
  5. insert-row shifts `mergeData` start row
  6. `UniverSessionPort` with `flags=UniverConfig(enabled=False)` (or pass flags into SessionPort if missing — **Ruling:** SessionPort must forward flags to `UniverToolPort`; add the constructor kwarg)

- [ ] **Step 1–5:** TDD each case. Commit `test(univer): pin sidecar limits and one-level glob`

If SessionPort currently has no `flags=` parameter, adding it is in scope for this task.

---

### Task 5: `fsi_catalog()` and `references/` load

**Files:**
- Modify: `neos/skills/markdown_catalog.py`
- Test: `tests/skills/test_markdown_catalog.py` and/or `tests/fsi/test_skill_catalog.py`

**Interfaces:**
- Consumes: existing `univer_catalog()` / `univer_skill_roots()` pattern
- Produces:

```python
FSI_PACK = _REPO_ROOT / "skills" / "financial-services"
FSI_ANTHROPIC_VERTICALS = (
    "financial-analysis", "equity-research", "investment-banking",
    "private-equity", "fund-admin", "operations", "wealth-management",
)
def fsi_skill_roots() -> tuple[tuple[SkillSource, Path], ...]: ...
def fsi_catalog() -> MarkdownSkillCatalog: ...
def fsi_partner_skill_roots(vendor: Literal["lseg", "spglobal"]) -> ...
def fsi_lseg_catalog() / fsi_spglobal_catalog()
```

`_load_reference` tries `reference/` then `references/`. First existing file wins. Jail unchanged.

Tests (use tmp_path monkeypatch or repo fixtures):
- `fsi_catalog().get("kyc-doc-parse")` is None until Task 6 copies files — so in **this** task, create a tiny fixture under `tests/fsi/fixtures/skills/operations/kyc-doc-parse/SKILL.md` **or** point roots at tmp_path. Prefer unit-testing the functions by constructing `MarkdownSkillCatalog(roots=(("repo", tmp_vertical),))` plus a test that `fsi_skill_roots()` paths end with the seven verticals.
- `default_catalog().get("xlsx-author") is None` still.
- `default_skill_roots()` unchanged.
- Reference load: skill with only `references/foo.md` returns that body.

Do not copy the 48 skills in this task.

- [ ] **Step 5: Commit** `feat(skills): add fsi_catalog roots and references alias`

---

### Task 6: Vendor 48 Anthropic vertical skills

**Files:**
- Create: `skills/financial-services/<vertical>/<skill>/` copied from `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/<vertical>/skills/<skill>/`
- Create empty: `skills/financial-services/wealth-management/.gitkeep` so the catalog root exists
- Test: `tests/fsi/test_skill_pack.py`

**Interfaces:**
- Consumes: `fsi_catalog()` from Task 5
- Produces: 48 SKILL.md trees excluding `skill-creator`. Copy whole skill directories (`SKILL.md`, `reference/`/`references/`, `scripts/`, `assets/`, `TROUBLESHOOTING.md`, `requirements.txt`). Do not copy agent-plugin trees, `.claude-plugin/`, empty hooks, partner-built, or `skill-creator`.

Tests:
- `len([s for s in fsi_catalog()._ensure_index().values()]) == 48` (or `== 48` names)
- `fsi_catalog().get("kyc-doc-parse")` is not None
- `fsi_catalog().get("xlsx-author")` is not None
- `fsi_catalog().get("skill-creator") is None`
- `default_catalog().get("kyc-doc-parse") is None`
- `fsi_lseg_catalog().get("equity-research") is None` (partner tree not copied)

- [ ] **Step 5: Commit** `feat(fsi): vendor the Anthropic vertical skill pack`

---

### Task 7: `FsiSessionPort` with allowlisted `load_skill.v1`

**Files:**
- Modify: `neos/fsi/ports.py`
- Test: `tests/fsi/test_session_port.py`

**Interfaces:**
- Consumes: `FsiParentWorkspacePort`, `fsi_catalog()`, skill allowlist
- Produces: `FsiSessionPort(workspace, *, write: bool, skill_allowlist: frozenset[str] = frozenset())` mirroring `UniverSessionPort` minus sidecar:
  - `definitions()` = file port defs; add `load_skill.v1` only when allowlist non-empty
  - `execute` runs binding denylist first, then load_skill / files
  - unknown or not-permitted skill → `{"ok": False, "error": "unknown_skill"}`
  - permitted `kyc-doc-parse` → `{"ok": True, "name": ..., "markdown": ...}`
  - empty allowlist: `load_skill.v1` → `tool_not_allowed`
  - writer `write=True` still jails to `out/_spec/*.json`

Do not patch coding executor.

- [ ] **Step 5: Commit** `feat(fsi): load allowlisted skills on the session port`

---

### Task 8: Screening MCP stub attach

**Files:**
- Create: `neos/fsi/mcp_attach.py`
- Modify: `neos/fsi/ports.py` (`FsiSessionPort` composes stub tools when `mcp_allowlist` contains `screening`)
- Test: `tests/fsi/test_mcp_attach.py`

**Interfaces:**
- Consumes: `SCREENING_STUB_TOOLS = frozenset({"mcp.screening.search"})` already in `profile.py`
- Produces:

```python
# neos/fsi/mcp_attach.py
SCREENING_SEARCH = "mcp.screening.search"

def screening_search(params: Mapping[str, object]) -> Mapping[str, object]:
    # read-only stub: no HTTP. Always ok with hits=[] unless query missing.
    return {"ok": True, "hits": []}
```

`FsiSessionPort(..., mcp_allowlist: frozenset[str] = frozenset())`:
- if `"screening" in mcp_allowlist`, `definitions()` includes `mcp.screening.search`
- execute that name returns the stub
- reader/writer ports must not grow this tool (only session port with allowlist)
- no live HTTP

- [ ] **Step 5: Commit** `feat(fsi): stub mcp.screening.search without HTTP`

---

### Task 9: Parent-only `stage_xlsx.v1`

**Files:**
- Create: `neos/fsi/stage_xlsx.py`
- Modify: `neos/fsi/ports.py` (parent/session `write=False` definitions include `stage_xlsx.v1`; leaf writer does not)
- Test: `tests/fsi/test_stage_xlsx.py`

**Interfaces:**
- Consumes: openpyxl (already a project dependency if present; if missing, add nothing new — write a minimal xlsx via openpyxl, skip-if only if import fails **Ruling:** openpyxl is required, fail the test if missing)
- Produces: `stage_xlsx(workspace: Path, *, path: str, rows: Sequence[Sequence[object]]) -> Mapping`
  - confined to `workspace/out/*.xlsx` (parent of file is `out/`, suffix `.xlsx`)
  - `../` / `out/_spec/` / `draft/` → `path_denied`
  - success writes workbook and returns `{"ok": True, "path": "out/escalation-PKT.xlsx", "status": "staged_for_signoff"}`
  - `FsiParentWorkspacePort(write=False).definitions()` grows `glob_files.v1` **and** `stage_xlsx.v1` (**Ruling:** parent port is the orchestrator workspace: read + search + glob + stage_xlsx; no write_file)
  - `FsiParentWorkspacePort(write=True)` does **not** list `stage_xlsx.v1`; execute of it is `tool_not_allowed` (binding check does not apply)
  - Existing reader definitions test `== ("read_file.v1", "search_text.v1")` **must be updated** in this task to include glob + stage_xlsx. Update `test_reader_cannot_write` accordingly.

- [ ] **Step 5: Commit** `feat(fsi): stage xlsx on the parent workspace only`

---

### Task 10: Typed `handoff.v1` bus

**Files:**
- Create: `neos/fsi/handoff.py`
- Modify: `neos/fsi/ports.py` — `FsiSessionPort` execute `handoff.v1` when `handoff_allowlist` non-empty
- Test: `tests/fsi/test_handoff.py`

**Interfaces:**
- Consumes: spec `01-safety-handoff.md` `ALLOWED_TARGETS`, `ALLOWED_EDGES`, `HANDOFF_INPUT_SCHEMA`
- Produces: `validate_handoff(from_slug, payload) -> HandoffCommand` or error dict `{"ok": False, "error": "policy_handoff_denied"}`
  - unknown target denied
  - edge not in `ALLOWED_EDGES` denied
  - extra keys / bad charset → `policy_schema_invalid` (validate locally with jsonschema; do not wire coding registry this wave)
  - `("gl-reconciler", "month-end-closer")` allowed
  - `("kyc-screener", "pitch-agent")` denied
  - quoted JSON is not a handoff (`quoted_json_is_handoff` remains False; add a test that a file body containing `handoff_request` does not call validate)

Do not add HTTP. Do not put `handoff.v1` on leaves (`REFUSED_TOOLS` already has it).

- [ ] **Step 5: Commit** `feat(fsi): add typed handoff allowlist bus`

---

### Task 11: FSI parent `spawn_agent` session (KYC)

**Files:**
- Modify: `neos/fsi/loop.py`
- Modify: `neos/fsi/profile.py` if a helper `overlay_for(profile) -> SpecRegistry` is cleaner — allowed
- Test: `tests/fsi/test_parent_session.py`

**Interfaces:**
- Consumes: `run_leaf`, `compile_leaf_spec`, `load_profile`, `FsiSessionPort`, `ScriptedCodingModel`, KYC fixture
- Produces:

```python
def overlay_catalog(profile: Mapping[str, object]) -> SpecRegistry:
    """Register every compiled leaf on a fresh overlay. Do not touch module _SPECS."""

async def run_parent_spawn(
    *,
    runtime: SubagentRuntime,
    profile: Mapping[str, object],
    spec: str,
    briefing: ParentBriefing,
    parent_id: str,
    parent_run_id: str,
    parent_tool_call_id: str,
    model: ModelPin,
    enabled: bool,
) -> FoldedResult:
```

Behavior:
- `enabled is False` → do not advance; raise no HTTP; return a folded-like error **Ruling:** raise `FlagDisabled` (new small class in `loop.py`) or return without calling `advance`. Test: store stays empty.
- `spec` not in overlay → `UnknownSpec`
- happy path: KYC profile, `spec="kyc-doc-reader"`, scripted child text is valid schema JSON, fold validates, `parent_kind is ParentKind.FSI`
- live children cap 1: a second `run_parent_spawn` while the first has not folded is **not** required this wave if `run_parent_spawn` is sequential `run_leaf`. Pin that `nested_spawn is None`.
- `lookup_spec("kyc-doc-reader")` at module still `UnknownSpec`

Also add `cancel_fsi_children(runtime, parent_id, *, enabled: bool)` mirroring Univer.

- [ ] **Step 5: Commit** `feat(fsi): spawn KYC leaves from the parent loop`

---

### Task 12: Univer parent `office-session` spawn

**Files:**
- Modify: `neos/univer/loop.py`
- Test: `tests/univer/test_parent_session.py`

**Interfaces:**
- Consumes: office-session YAML at `skills/univer/profiles/office-session.yaml`, `compile_leaf_spec` / Univer profile loader, `run_leaf`
- Produces: `overlay_catalog(profile)` + `run_parent_spawn(...)` with `ParentKind.UNIVER`, `enabled` gate, unknown spec fail-closed. Happy path: spawn `univer-reader` with scripted outline JSON matching schema 00 (`unit_id`, `kind`, `sheets`).

Do not boot Node. Do not add HTTP.

- [ ] **Step 5: Commit** `feat(univer): spawn office-session leaves from the parent loop`

---

### Task 13: Remaining nine named-agent profile YAMLs (compile-only)

**Files:**
- Create: `skills/financial-services/profiles/<slug>.yaml` for the nine slugs besides KYC (KYC production profile may copy the fixture into this directory too)
- Test: `tests/fsi/test_named_profiles.py`

**Interfaces:**
- Consumes: `load_profile`, `compile_tool_policy`, `compile_leaf_spec`, `READER_SCHEMAS`
- Produces: YAML for `gl-reconciler`, `month-end-closer`, `statement-auditor`, `valuation-reviewer`, `model-builder`, `pitch-agent`, `market-researcher`, `earnings-reviewer`, `meeting-prep-agent` plus `kyc-screener`. Each: `isolation_surface: cma_leaves`, `tools.default: deny`, exactly one `write: true` leaf, Mode A/B per spec, `output_schema_ref` on schema leaves matching `READER_SCHEMAS` keys from `docs/financial-services/spec/00-harness-and-profile.md` / agent specs.

**Ruling:** meeting-prep ships compile-only without wealth-management skill restore. `model-builder` writer does **not** list `execute.v1` (compiler would refuse). Mode A writers stamp `WORKTREE`.

Keep prompts out of YAML (`system_prompt_path` optional). Do not invent critic schemas.

- [ ] **Step 5: Commit** `feat(fsi): compile all ten named-agent profiles`

---

### Task 14: Update merge-status docs

**Files:**
- Modify: `docs/financial-services/10-merge-status.md`
- Modify: `docs/univer/15-merge-status.md`

**Interfaces:**
- Produces: retitle remaining gaps (HTTP/UI, Node pin, partner skills, WM restore, FSI-2 execute.v1, live MCP HTTP) and mark Tasks 1–13 items MERGED with paths. Do not replace inventory `00–09` / `00–14` or `spec/`.

- [ ] **Step 5: Commit** `docs: record the final attach wave against merge-status`
