# Univer Kernel Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the v0 kernel holes found in the Univer completeness audit so the in-memory sidecar actually mutates, formulas report ErrorType, draft can merge to trunk, and flags/binding/glob/load_skill run on the execute path — still no HTTP/UI and no real Node `@univerjs` pin.

**Architecture:** Keep `InMemorySidecar` as the v0 double. Add load/health/busy, make allowlisted COMMANDs mutate cells/docs/resources, expand formula eval to SUM/IF/ranges/ErrorType, wire glob + binding + runtime flags + merge.v1 + load_skill on Univer ports. Do not add `neos/univer/sidecar/index.js`.

**Tech Stack:** Python 3, pytest (`pytest.mark.no_db`), existing `neos/univer/*`, `SubagentRuntime`.

**Spec:** `docs/univer/spec/UNIVER_NEOS_MIGRATION_SPEC.md`, `00-harness-and-profile.md`, `01-tools-and-runtime.md`, `02-skills-safety.md`. Completeness audit (chat, 2026-09-25).

## Global Constraints

- Work in place on `dev`. Do not push. Do not commit `docs/univer/` inventory unless a task names those files.
- No HTTP/UI. No real Node `@univerjs` pin. No `slides_enabled`. No `mcp.univer.*`. No Facade JS. No `WORKTREE` on Univer leaves.
- Writer has `write_file.v1` + `univer.save.v1` + `univer.formula_wait.v1`. Critic has no write. All leaves `SandboxMode.NONE`.
- Import law: `neos/subagent` ↛ `neos.univer`; `neos.univer` ↛ DurableCodingLoop / DA / `neos.fsi`.
- Empty sheet defaults stay 1000×20, height 24, width 88. `appVersion` `"1.0.2"`.
- Success status `staged_for_signoff`. Binding denylist: publish/send/email/merge_trunk/merge_worktree/xlsx_export/mcp_univer_ai/register_pro_license.
- Writer jail: `draft/` direct-child `*.json`. `univer.save.v1` only `draft/workbook.json` or `draft/document.json`.
- COMMAND allowlist stays the existing 12 ids. MUTATION/OPERATION still `mutation_forbidden`.
- TDD: write the failing test, watch it fail, then implement. pytest via `.venv/bin/pytest`. Local autouse `Settings()` teardown ERROR is pre-existing — do not "fix" it.
- Commit style: conventional prefix (`feat(univer):`, `fix(univer):`) English subject + short body. One commit per task.
- Do not edit `064_allow_fsi_subagent_parent.sql`. Do not mutate catalog `_SPECS` in place.

## Review Focus

- `glob_files.v1` on a writer port must stay `tool_not_allowed` (orchestrator/reader only).
- Leaf `univer.merge.v1` must return `policy_binding_denied` / `merge_trunk`; only `merge_draft_to_trunk` parent helper copies files.
- `formula_wait` with `formula_enabled=False` must fail even if sheets are on.
- Insert-row must shift existing `cellData` down; a dirty-flag-only pass is a miss.
- `=SUM(A1:A2)` after wait must set numeric `v`, not leave empty `v`.

## Spec conflict rulings (binding)

| Conflict | Ruling |
|---|---|
| 01 writer has no `write_file.v1` | Writer **has** `write_file.v1` (locked kernel) |
| Real Node sidecar vs in-memory double | This wave improves the **double**. Node pin stays later |
| Parent live `spawn_agent` session | Out of this plan (loop.py stays `run_leaf`) |
| `load_skill.v1` patch of coding executor | Implement on `UniverSessionPort` only; do not change `neos/coding/tools/executor.py` |
| Error code for disabled flags | `flag_disabled` with `"flag": "<name>"` |
| `univer.merge.v1` as a leaf tool | Not in leaf `allowed_tools`. Parent helper `merge_draft_to_trunk`. Executing the tool name on a leaf port is `policy_binding_denied` action `merge_trunk` |

---

### Task 1: glob_files.v1 on the read-only workspace port

**Files:**
- Modify: `tests/univer/test_ports.py`
- Modify: `neos/univer/ports.py`

**Interfaces:**
- Consumes: `UniverParentWorkspacePort(workspace, write=False|True)`
- Produces: write=False `definitions()` = `("read_file.v1", "search_text.v1", "glob_files.v1")`; write=True unchanged `("read_file.v1", "write_file.v1")`. `glob_files.v1` input `pattern` (string glob, default `"**/*"`). Success `{"ok": True, "matches": [{"path": "<posix relative>"}]}`. Paths confined to workspace. `..` / absolute / NUL → `path_denied`. Writer execute of glob → `tool_not_allowed`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_reader_glob_lists_draft_json(tmp_path: Path) -> None:
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "workbook.json").write_text("{}", encoding="utf-8")
    (tmp_path / "trunk").mkdir()
    (tmp_path / "trunk" / "workbook.json").write_text("{}", encoding="utf-8")
    port = _reader(tmp_path)
    assert port.definitions() == ("read_file.v1", "search_text.v1", "glob_files.v1")
    result = await port.execute("glob_files.v1", {"pattern": "draft/*.json"})
    assert result["ok"] is True
    assert {"path": "draft/workbook.json"} in result["matches"]
    assert {"path": "trunk/workbook.json"} not in result["matches"]


@pytest.mark.asyncio
async def test_writer_glob_is_tool_not_allowed(tmp_path: Path) -> None:
    port = _writer(tmp_path)
    result = await port.execute("glob_files.v1", {"pattern": "**/*"})
    assert result == {"ok": False, "error": "tool_not_allowed"}
```

Update `test_reader_cannot_write` expected definitions to include `glob_files.v1`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/univer/test_ports.py::test_reader_glob_lists_draft_json tests/univer/test_ports.py::test_writer_glob_is_tool_not_allowed -q`
Expected: FAIL (definitions tuple mismatch / tool_not_allowed missing glob)

- [ ] **Step 3: Write minimal implementation**

In `UniverParentWorkspacePort.definitions`, when `not self._write` return `(_READ, _SEARCH, "glob_files.v1")`. In `execute`, dispatch glob: `rglob` under workspace, `path.match(pattern)` or `fnmatch` on posix relative, skip non-files, confine with `_confine`. Empty pattern treated as `"**/*"`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/univer/test_ports.py -q`
Expected: PASS (ignore pre-existing Settings teardown ERROR)

- [ ] **Step 5: Commit**

```bash
git add tests/univer/test_ports.py neos/univer/ports.py
git commit -m "feat(univer): add glob_files.v1 on the read-only workspace port"
```

---

### Task 2: Enforce BINDING_ACTIONS on the execute path

**Files:**
- Modify: `tests/univer/test_ports.py`
- Modify: `neos/univer/ports.py`

**Interfaces:**
- Consumes: `neos.univer.safety.policy_binding_denied`, `binding_error`
- Produces: `UniverSessionPort.execute` and `UniverToolPort.execute` consult the denylist before dispatch. Tool name `publish`/`send`/`email`/`merge_trunk`/`merge_worktree`/`xlsx_export`/`mcp_univer_ai`/`register_pro_license` OR `univer.merge.v1` returns `{"ok": False, "error": "policy_binding_denied", "action": <action>}`. `univer.merge.v1` maps to action `merge_trunk`. Legitimate `univer.inspect.v1` is unchanged.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_session_port_denies_binding_actions(tmp_path: Path) -> None:
    port = _session(tmp_path, write=True)
    denied = await port.execute("publish", {})
    assert denied["error"] == "policy_binding_denied"
    assert denied["action"] == "publish"
    merge = await port.execute("univer.merge.v1", {})
    assert merge == {
        "ok": False,
        "error": "policy_binding_denied",
        "action": "merge_trunk",
    }
    inspect = await port.execute("univer.inspect.v1", {})
    assert inspect["ok"] is True
```

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/univer/test_ports.py::test_session_port_denies_binding_actions -q`
Expected: FAIL (`tool_not_allowed` or inspect-only)

- [ ] **Step 3: Minimal implementation**

At the top of `UniverSessionPort.execute` and `UniverToolPort.execute`, map name `univer.merge.v1` → `merge_trunk`. If `policy_binding_denied(action)` return `{**binding_error(action), "ok": False}`.

- [ ] **Step 4: Run** `.venv/bin/pytest tests/univer/test_ports.py tests/univer/test_safety_policy.py -q`
- [ ] **Step 5: Commit** `fix(univer): deny binding actions on the session execute path`

---

### Task 3: Runtime surface flags on UniverToolPort

**Files:**
- Create: `tests/univer/test_runtime_flags.py`
- Modify: `neos/univer/ports.py`
- Modify: `neos/univer/sidecar.py` only if constructor needs `kind` already present

**Interfaces:**
- Consumes: `UniverConfig` fields as a simple namespace or the model itself
- Produces: `UniverToolPort(sidecar, flags=None)`. `flags` object with `enabled`, `sheets_enabled`, `docs_enabled`, `formula_enabled` (default all True in tests that omit flags so existing tests stay green). When `enabled` is False every univer tool returns `{"ok": False, "error": "flag_disabled", "flag": "enabled"}`. Sheet tools (`inspect` on sheet sidecar, `range_get/set`, sheet commands, save of workbook) require `sheets_enabled`. Doc kind requires `docs_enabled`. `univer.formula_wait.v1` requires `formula_enabled`.

- [ ] **Step 1: Failing tests**

```python
# tests/univer/test_runtime_flags.py
from types import SimpleNamespace
from pathlib import Path
import pytest
from neos.univer.ports import UniverToolPort
from neos.univer.sidecar import InMemorySidecar

pytestmark = pytest.mark.no_db

def _flags(**kwargs):
    base = dict(enabled=True, sheets_enabled=True, docs_enabled=True, formula_enabled=True)
    base.update(kwargs)
    return SimpleNamespace(**base)

@pytest.mark.asyncio
async def test_master_off_disables_inspect(tmp_path: Path) -> None:
    port = UniverToolPort(InMemorySidecar(session_dir=tmp_path), flags=_flags(enabled=False))
    result = await port.execute("univer.inspect.v1", {})
    assert result == {"ok": False, "error": "flag_disabled", "flag": "enabled"}

@pytest.mark.asyncio
async def test_formula_wait_requires_formula_flag(tmp_path: Path) -> None:
    port = UniverToolPort(
        InMemorySidecar(session_dir=tmp_path),
        flags=_flags(formula_enabled=False),
    )
    result = await port.execute("univer.formula_wait.v1", {})
    assert result == {"ok": False, "error": "flag_disabled", "flag": "formula_enabled"}

@pytest.mark.asyncio
async def test_doc_kind_requires_docs_flag(tmp_path: Path) -> None:
    port = UniverToolPort(
        InMemorySidecar(session_dir=tmp_path, kind="doc"),
        flags=_flags(docs_enabled=False),
    )
    result = await port.execute("univer.inspect.v1", {})
    assert result == {"ok": False, "error": "flag_disabled", "flag": "docs_enabled"}
```

Existing tests construct `UniverToolPort(sidecar)` with no flags — treat missing flags as all-on so they stay green.

- [ ] **Step 2: RED** `.venv/bin/pytest tests/univer/test_runtime_flags.py -q`
- [ ] **Step 3: Implement `_check_flags(name)` in `UniverToolPort._execute`**
- [ ] **Step 4: GREEN** `.venv/bin/pytest tests/univer/test_runtime_flags.py tests/univer/test_sidecar_tools.py tests/univer/test_ports.py -q`
- [ ] **Step 5: Commit** `feat(univer): gate sidecar tools on runtime UniverConfig flags`

---

### Task 4: Sidecar health, load, unit_busy, one_unit_limit

**Files:**
- Modify: `tests/univer/test_sidecar_tools.py`
- Modify: `neos/univer/sidecar.py`
- Modify: `neos/univer/ports.py` (`_RPC_METHODS` add `health`/`load`/`dispose` only if exposed — parent RPC, not leaf tools)

**Interfaces:**
- Consumes: `InMemorySidecar.call(method, params)`
- Produces:
  - `health` → `{ok, pid: 0, kind, lifecycle: "Steady", unit_id, formula_dirty, in_flight, app_version: "1.0.2"}`
  - `load` `{path}` reads session-relative JSON; missing file keeps empty unit; invalid JSON → `snapshot_invalid`; path outside session → `path_denied`
  - overlapping `call` while `_in_flight` → `unit_busy`
  - `create` when a unit already exists → `one_unit_limit`. `load` is the replace path (allowed).
  - `dispose` clears cells and allows a later `create`

Do **not** add health/load/dispose to `_SIDECAR_TOOLS` leaf definitions. Tests call `sidecar.call(...)` directly.

- [ ] **Step 1: Failing tests**

```python
def test_health_reports_steady_empty_sheet(tmp_path: Path) -> None:
    sidecar = InMemorySidecar(session_dir=tmp_path)
    result = sidecar.call("health", {})
    assert result["ok"] is True
    assert result["kind"] == "sheet"
    assert result["lifecycle"] == "Steady"
    assert result["unit_id"] == "workbook-01"
    assert result["formula_dirty"] is False
    assert result["in_flight"] is False
    assert result["app_version"] == "1.0.2"

def test_load_invalid_json_is_snapshot_invalid(tmp_path: Path) -> None:
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "workbook.json").write_text("{", encoding="utf-8")
    sidecar = InMemorySidecar(session_dir=tmp_path)
    result = sidecar.call("load", {"path": "draft/workbook.json"})
    assert result == {"ok": False, "error": "snapshot_invalid"}

def test_create_second_unit_is_one_unit_limit(tmp_path: Path) -> None:
    sidecar = InMemorySidecar(session_dir=tmp_path)
    first = sidecar.call("create", {})
    assert first["ok"] is True
    second = sidecar.call("create", {})
    assert second == {"ok": False, "error": "one_unit_limit"}

def test_in_flight_call_is_unit_busy(tmp_path: Path) -> None:
    sidecar = InMemorySidecar(session_dir=tmp_path)
    sidecar._in_flight = True
    result = sidecar.call("inspect", {})
    assert result == {"ok": False, "error": "unit_busy"}
```

`call` must set `_in_flight` around the handler. Constructor may set `_created=True` for the implicit empty unit so first `create` already hits `one_unit_limit` unless `dispose` ran — **Ruling:** implicit boot counts as the one unit; `create` without `dispose` is `one_unit_limit`; `load` replaces.

- [ ] **Step 2: RED**
- [ ] **Step 3: Implement health/load/create/dispose + in-flight guard in `call`**
- [ ] **Step 4: GREEN** including existing sidecar tests
- [ ] **Step 5: Commit** `feat(univer): add sidecar health, load, and one-unit guards`

---

### Task 5: Inspect formula_errors and ErrorType cell values

**Files:**
- Modify: `tests/univer/test_sidecar_tools.py`
- Modify: `neos/univer/sidecar.py`

**Interfaces:**
- Consumes: existing `_apply_formulas` / `_eval_formula`
- Produces: `univer.inspect.v1` with `include_formula_errors` default True adds `formula_errors: [{code, a1, sheet}]` from cells whose `v` is one of the 12 ErrorType literals. Division by zero in `_eval_formula` stores `v="#DIV/0!"` (does not swallow). Unsupported formula stores `v="#NAME?"`. Inspect of dirty book with `include_values` still `formula_dirty`.

This task may land a **minimal** error-writing path (`1/0` and unknown names). SUM/IF ranges are Task 6.

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_inspect_formula_errors_after_wait(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "A1", "value": 0})
    await port.execute("univer.range_set.v1", {"a1": "B1", "formula": "=1/A1"})
    await port.execute("univer.formula_wait.v1", {})
    inspect = await port.execute("univer.inspect.v1", {"include_values": True})
    assert inspect["ok"] is True
    codes = {item["code"] for item in inspect["formula_errors"]}
    assert "#DIV/0!" in codes
    assert any(item["a1"] == "B1" for item in inspect["formula_errors"])
```

- [ ] **Step 2–5:** RED, implement (stop swallowing ZeroDivisionError; write ErrorType into `v`), GREEN, commit `feat(univer): report formula_errors on inspect`

---

### Task 6: Formula SUM, IF, ranges

**Files:**
- Modify: `tests/univer/test_sidecar_tools.py`
- Modify: `neos/univer/sidecar.py` (`_eval_formula`)

**Interfaces:**
- Produces: `_eval_formula` supports `SUM(A1:A2)`, `IF(A1>0,1,0)`, single-cell refs, `+ - * /`. `=SUM(A1:A2)` with A1=1,A2=2 waits to `v=3`. Unknown function → `#NAME?`. Range with no values sums as 0.

- [ ] **Step 1:**

```python
@pytest.mark.asyncio
async def test_sum_range_and_if_after_wait(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "A1", "value": 1})
    await port.execute("univer.range_set.v1", {"a1": "A2", "value": 2})
    await port.execute("univer.range_set.v1", {"a1": "B1", "formula": "=SUM(A1:A2)"})
    await port.execute("univer.range_set.v1", {"a1": "C1", "formula": "=IF(A1>0,1,0)"})
    await port.execute("univer.formula_wait.v1", {})
    b1 = await port.execute("univer.range_get.v1", {"a1": "B1"})
    c1 = await port.execute("univer.range_get.v1", {"a1": "C1"})
    assert b1["cells"][0]["v"] == 3
    assert c1["cells"][0]["v"] == 1
    await port.execute("univer.range_set.v1", {"a1": "D1", "formula": "=FOO()"})
    await port.execute("univer.formula_wait.v1", {})
    inspect = await port.execute("univer.inspect.v1", {"include_values": True})
    assert any(item["code"] == "#NAME?" and item["a1"] == "D1" for item in inspect["formula_errors"])
```

Keep `=A1+1` still working (existing test).

- [ ] **Step 2–5:** RED, implement a small formula parser (do not import Excel engines), GREEN including `test_wait_then_save_computed_v`, commit `feat(univer): evaluate SUM, IF, and ranges in formula_wait`

---

### Task 7: Allowlisted sheet COMMANDs mutate the model

**Files:**
- Modify: `tests/univer/test_sidecar_tools.py`
- Modify: `neos/univer/sidecar.py`

**Interfaces:**
- `sheet.command.insert-row` with params `{startRow: 0, count: 1}` shifts existing cells down by 1 and increments `row_count`.
- `sheet.command.remove-row` shifts up and decrements `row_count` (floor 1).
- `sheet.command.insert-col` / `remove-col` analog on columns (floor 1).
- `sheet.command.add-worksheet-merge` stores merge in snapshot `sheets[id].mergeData`.
- `sheet.command.sort-range` sorts the A1 range by first column ascending (numeric then string).
- `sheet.command.addDataValidation` / `add-conditional-rule` / `add-table` append `{name, data}` to snapshot `resources` (name strings `SHEET_DATA_VALIDATION_PLUGIN`, `SHEET_CONDITIONAL_FORMATTING_PLUGIN`, `SHEET_TABLE_PLUGIN`; `data` is `json.dumps(params)`).

- [ ] **Step 1:** tests that set A1=1, insert-row at 0, then A2 (was A1) is 1 and A1 is empty; merge appears in save JSON; DV appears in `resources`.

```python
@pytest.mark.asyncio
async def test_insert_row_shifts_cells(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "A1", "value": 1})
    result = await port.execute(
        "univer.execute_command.v1",
        {"id": "sheet.command.insert-row", "params": {"startRow": 0, "count": 1}},
    )
    assert result["ok"] is True
    a1 = await port.execute("univer.range_get.v1", {"a1": "A1"})
    a2 = await port.execute("univer.range_get.v1", {"a1": "A2"})
    assert a1.get("cells") == [] or a1["cells"][0].get("v") in (None, [])
    assert a2["cells"][0]["v"] == 1

@pytest.mark.asyncio
async def test_add_validation_lands_in_resources(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute(
        "univer.execute_command.v1",
        {"id": "sheet.command.addDataValidation", "params": {"ranges": ["A1"]}},
    )
    await port.execute("univer.save.v1", {})
    snapshot = json.loads((tmp_path / "draft" / "workbook.json").read_text(encoding="utf-8"))
    names = [item["name"] for item in snapshot["resources"]]
    assert "SHEET_DATA_VALIDATION_PLUGIN" in names
```

- [ ] **Step 2–5:** RED, implement handlers (replace dirty-only branch), GREEN, commit `feat(univer): mutate cells and resources for allowlisted sheet commands`

---

### Task 8: Docs insert-text / update-text mutate dataStream

**Files:**
- Modify: `tests/univer/test_sidecar_tools.py`
- Modify: `neos/univer/sidecar.py`

**Interfaces:**
- `kind="doc"` `doc.command.insert-text` params `{text: "Hello"}` inserts into `body.dataStream` before the trailing `\n` (keep `\r\n` terminator: `"Hello\r\n"`).
- `doc.command.update-text` with `{text: "Hi"}` replaces current paragraph text.
- `_inspect_doc` reflects `data_stream_length` and paragraph text.
- `save` writes the mutated body. Missing `documentStyle: {}` may be added so JSON is closer to IDocumentData.

- [ ] **Step 1:**

```python
@pytest.mark.asyncio
async def test_doc_insert_text_round_trip(tmp_path: Path) -> None:
    port = UniverToolPort(InMemorySidecar(session_dir=tmp_path, kind="doc"))
    inserted = await port.execute(
        "univer.execute_command.v1",
        {"id": "doc.command.insert-text", "params": {"text": "Hello"}},
    )
    assert inserted["ok"] is True
    inspect = await port.execute("univer.inspect.v1", {})
    assert inspect["ok"] is True
    assert inspect["paragraphs"][0]["text"] == "Hello"
    saved = await port.execute("univer.save.v1", {})
    assert saved["ok"] is True
    snapshot = json.loads((tmp_path / "draft" / "document.json").read_text(encoding="utf-8"))
    assert "Hello" in snapshot["body"]["dataStream"]
```

- [ ] **Step 2–5:** RED, implement, GREEN, commit `feat(univer): apply doc insert-text to the in-memory dataStream`

---

### Task 9: Parent merge_draft_to_trunk and session load_skill

**Files:**
- Modify: `tests/univer/test_ports.py`
- Modify: `neos/univer/ports.py`
- Create function in `neos/univer/loop.py` or `ports.py`: `merge_draft_to_trunk(workspace: Path) -> Mapping`

**Interfaces:**
- `merge_draft_to_trunk(workspace)` copies `draft/workbook.json` → `trunk/workbook.json` and/or `draft/document.json` → `trunk/document.json` if present. Missing draft → `{"ok": False, "error": "not_found"}`. Success `{"ok": True, "status": "staged_for_signoff", "copied": [...]}`. This is **not** a leaf tool.
- `UniverSessionPort(..., skill_allowlist: frozenset[str] = frozenset())`. If `load_skill.v1` in execute: empty allowlist or unknown name → `{"ok": False, "error": "unknown_skill"}`. Allowed name from `univer_catalog()` returns `{"ok": True, "name": ..., "markdown": ...}`. `definitions()` for write=False includes `glob_files.v1` (from Task 1) but **not** `load_skill.v1` unless allowlist non-empty — **Ruling:** add `load_skill.v1` to session `definitions()` only when `skill_allowlist` is non-empty, so writer catalog listing the tool still needs the parent to pass the four-name allowlist. Writer leaf with empty YAML allowlist still cannot load.

- [ ] **Step 1:** tests for merge copy + load_skill unknown vs permitted `univer-qc`

- [ ] **Step 2–5:** RED, implement, GREEN, commit `feat(univer): add parent merge helper and session load_skill catalog`

---

### Task 10: cancel_for_parent helper when flags drop

**Files:**
- Modify: `tests/univer/test_loop.py`
- Modify: `neos/univer/loop.py`

**Interfaces:**
- Produces: `async def cancel_univer_children(runtime: SubagentRuntime, parent_id: str, *, enabled: bool) -> list`. When `enabled` is False, call `runtime.cancel_for_parent(ParentKind.UNIVER, parent_id, "flag_disabled")` and return the snapshots. When True, return `[]` and do not cancel.
- `run_leaf` on writer completed fold attaches nothing to FoldedResult (type may not have artifact status). Helper `artifact_status_for(folded: FoldedResult) -> str | None` returns `staged_for_signoff` when `folded.exit_reason == "completed"` and spec is `univer-writer`, else None.

- [ ] **Step 1:**

```python
@pytest.mark.asyncio
async def test_cancel_univer_children_when_disabled() -> None:
    runtime = make_univer_runtime(
        model=ScriptedCodingModel([]),
        tools=_EmptyPort(),
        catalog=_overlay("univer-reader"),
    )
    ticket = SubagentTicket(
        spec="univer-reader",
        parent_kind=ParentKind.UNIVER,
        parent_id="office-1",
        briefing=ParentBriefing(question="q", success_condition="s", already_tried=()),
        model=ModelPin(provider="p", model="m"),
    )
    # start a run by advancing once if needed — or insert via store
    from neos.univer.loop import cancel_univer_children
    snaps = await cancel_univer_children(runtime, "office-1", enabled=False)
    # With no active children, result is empty list (not an error)
    assert snaps == []
    snaps_on = await cancel_univer_children(runtime, "office-1", enabled=True)
    assert snaps_on == []
```

If constructing an in-flight child is awkward, open a run through `runtime.advance` with a model that returns CONTINUING, then cancel and assert status cancelled. Follow existing `tests/subagent/test_runtime.py` cancel_for_parent pattern.

Also test `artifact_status_for` on a completed writer fold.

- [ ] **Step 2–5:** RED, implement, GREEN `tests/univer/test_loop.py`, commit `feat(univer): cancel children on flag-off and expose staged_for_signoff`

---

## Out of this plan

- Real Node `@univerjs` 1.0.2 sidecar / JSON-RPC TCP
- HTTP `/api/v1/univer` and UI
- Parent `office-session` spawn_agent live graph
- Patching `neos/coding/tools/executor.py`
- 516-function engine, VLOOKUP, slides, Pro, MCP
