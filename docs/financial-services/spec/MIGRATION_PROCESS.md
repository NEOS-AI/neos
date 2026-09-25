# FSI → Neos: code-grounded migration process

| Field | Value |
|---|---|
| Date | 2026-09-25 |
| Status | Investigation (read-only against live `neos/`) |
| Complements | [FSI_NEOS_MIGRATION_SPEC.md](./FSI_NEOS_MIGRATION_SPEC.md) (locked harness). This document does **not** reopen C1 / KYC leaves / DCF SKILL.md. |
| Question | Given the actual Neos source, what is the *ideal* sequence for landing FSI so each merge is real software, not a dead library? |

Harness contracts stay in the master spec. This file answers **where to attach, what the live APIs actually are, which spec assumptions the tree contradicts, and which order the code will accept.**

---

## Verdict (one page)

Neos already has the right *kernel* for FSI: `SubagentRuntime` is a parent-driven one-step facade. Deep analysis and designed-graph workflow already call `advance` without the coding durable loop. FSI should be a **fourth parent kind** (`ParentKind.FSI`) with its own loop, ports, and HTTP surface — the same widening recipe used for `ParentKind.WORKFLOW`.

It should **not** be:

- a LangGraph specialist (`neos/workflow/graph.py`)
- a DA `Worker.investigate` (claims + `search`/`fetch` only)
- a coding `/code` task with `spec=implement` (git + `mkdir`/`rm`/`chmod`)
- a chat-classifier route (KYC packets would land in the research bag)
- a wrap of Anthropic `POST /v1/agents`

The ideal process is **kernel → catalog+prompt branch → parent port+loop smoke → schema gate → skill pack → MCP stubs → KYC as the first user-visible graph → remaining Mode B → Mode A worktree → handoff bus**. Flags stay default-off. The first thing a human can click is a KYC session that **cannot approve**.

The locked 15-PR list is still the product order. The source tree adds four constraints the PR list under-specified:

1. `ParentKind.FSI` must land as **enum + metrics + DB CHECK together**, or FSI rows fold into `"coding"` labels and the first INSERT fails the CHECK (`tests/subagent/test_workflow_parent_kind.py`).
2. Registering `fsi-*` specs without a **stepper prompt branch** feeds every non-`implement` child the explore system prompt, which tells the model it may `spawn_agent.v1` (`stepper.py:108–111`).
3. `compile_leaf_spec` returning a `dataclasses.replace`d `SubagentSpec` with extra MCP names **does not reach the child**. `advance` re-looks up the catalog singleton (`runtime.py:122`). MCP names must be on a **registered** spec *and* on the injected `ToolPort`.
4. There is **no named-agent HTTP/UI**. A KYC PR that only adds `neos/fsi/` Python with no `POST /api/v1/fsi/sessions` is a library nobody can run.

---

## 1. What exists today (live tree)

### 1.1 Four product planes, none of them FSI

| Plane | Start | Parent loop | Subagent specs |
|---|---|---|---|
| Chat / research | `POST /api/v1/chat/...`, UI `/` | LangGraph classifier | none (tools on the parent) |
| Coding | `POST /api/v1/coding/tasks`, UI `/code`, channel `/code` behind `channels.coding_invoke` default **false** | `DurableCodingLoop` | `explore`, `implement` |
| Deep analysis | `POST /api/v1/deep-analysis` | DA orchestrator | tickets `research` only; `analyze`/`compose` are catalog-only |
| Designed graph | workflow nodes | `subagent_nodes.py` | `explore` read-only |

`ParentKind` is closed: `coding | deep_analysis | workflow` (`neos/subagent/types.py:10–16`). `lookup_spec("fsi-reader")` raises `UnknownSpec`. There is no `neos/fsi/` package.

### 1.2 The kernel FSI should call

`neos/subagent` is **not** an inner drain loop. Tests freeze that (`tests/subagent/test_runtime.py:627–632`): no `run_until_done`, no `while True` in the package. Import law: this package must not import the durable coding loop, DA, channels, or agents.

Public surface an FSI parent actually uses:

| Method | Role |
|---|---|
| `SubagentRuntime.advance(ticket) -> StepOutcome` | create-or-resume **one** child step (one model turn XOR one tool batch) |
| `fold(run_id)` | budget-truncated `last_assistant_text` |
| `cancel_for_parent(parent_kind, parent_id, reason)` | flag-off path |
| `resume(run_id, expected_checkpoint_id=...)` | CAS continue |

Ticket construction is the parent's job. `SandboxMode` is stored on the ticket and **not read by the stepper**. The parent injects the `ToolPort`. That is why `FsiParentWorkspacePort` is real work and why "stamp `NONE` on the spec" is not enough by itself.

```python
# Live MUST-call shape (DA and workflow already do this).
outcome = await runtime.advance(ticket)
while outcome.kind is StepKind.CONTINUING:
    outcome = await runtime.advance(
        replace(ticket, run_id=outcome.run_id,
                expected_checkpoint_id=outcome.checkpoint_id)
    )
folded = await runtime.fold(outcome.run_id)
```

`max_turns` is clamped 1–8 (`types.py:98–99`). FSI leaves inherit that ceiling.

### 1.3 Tool permission is exact set membership

```324:331:neos/subagent/stepper.py
# _tool_permitted: name in spec.allowed_tools, else False
```

`REFUSED_TOOLS` currently includes `spawn_agent.v1`, `write_file.v1`, `execute.v1`, … but **not** `handoff.v1`. A leaked listing is denied unless the spec also contains the name; still add `handoff.v1` to `REFUSED_TOOLS` so a future glob/mistake cannot execute it on a leaf.

Visible tools = `ToolPort.definitions() ∩ spec.allowed_tools`. Extra MCP names on a compiled-but-unregistered spec are invisible.

### 1.4 Skills: two catalogs, `load_skill.v1` sees one

| Function | Roots | Depth | Used by `load_skill.v1`? |
|---|---|---|---|
| `default_skill_roots()` | `neos/coding/skills/` | one level (`<root>/<child>/SKILL.md`) | **yes** (`executor.py` `_load_skill` → `default_catalog()`) |
| `research_skill_roots()` | repo `skills/` + builtin | one level | **no** |

A pack at `skills/financial-services/<vertical>/<skill>/SKILL.md` is **invisible** if the catalog root is `skills/` (the scanner does not recurse). The smallest correct root is **one root per vertical**: `skills/financial-services/operations`, `.../fund-admin`, etc.

Coding catalog **skips** files missing exact `## When to Use` / `## Boundaries`. Research/repo catalogs warn-only and still index. FSI SKILL.md keep `name` + `description` only — they must **not** join `default_skill_roots()`.

### 1.5 MCP: three misnamed worlds, zero HTTP client

`neos/tools/mcp_integration.py` is a **process-global** Python singleton (Tavily, file processing that can **write/delete**, git, YouTube). `pyproject.toml` has no MCP SDK. There is no `ClientSession`, no `tools/list`. Coding `/mcp` is disabled. Planned coding adapter H1 (`mcp__server__tool`) is not built.

FSI `mcp.<server>.<tool>` is a **new** per-session port, not a flag on `mcp_integration.py`.

### 1.6 Office artifacts

- `write_file.v1` is UTF-8 text. It cannot be the producer of `.xlsx`.
- Default coding `execute.v1` does not ship `python`.
- Recalc lives at `skills/xlsx/scripts/recalc.py` (Mode A formulas).
- Worktree merge is ff-only + `--binary`; the coding UI has no `./out/**` collector and binary preview is "unavailable".
- Chat `createDocument kind=sheet` is CSV. `neos/exporters/` is md/html/pdf/canvas.

KYC xlsx is therefore **parent `stage_xlsx.v1` (host openpyxl)** after the child writes `./out/_spec/<packet>.json`. Do not put that tool on `CodingToolRegistry`.

---

## 2. Spec assumptions the tree contradicts (do not implement blindly)

These are **process** corrections. The locked safety thesis stays.

| Spec sentence | Live code | Ideal process fix |
|---|---|---|
| `compile_leaf_spec` returns a `SubagentSpec` with MCP names unioned | `advance` does `self._catalog.lookup_spec(ticket.spec)` (`runtime.py:122`). Ticket has no tools field. | Register **aliases** (`kyc-doc-reader` → copy of `fsi-reader` + MCP names) on a session `SpecRegistry`, **or** overlay `lookup_spec`. Port must define the same exact names. |
| Catalog `sandbox_mode` selects the workspace | Stepper never reads `SandboxMode`. Coding spawn binds `CodingToolPort` for PARENT_RO/WORKTREE; DA injects a research port for NONE. | Parent loop binds `FsiParentWorkspacePort` (Mode B NONE) or `create_worktree` + write-capable port (Mode A WORKTREE). Compiler stamps are instructions to **that** bind, not to the runtime. |
| DA Worker first / "DA already matches Mode B" | `DAToolPort` is `search`/`fetch`. `WorkerResult` is claims. `SandboxMode.NONE` in DA means "runtime attaches nothing; orchestrator owns a throwaway research box." | Keep C1. Copy `advance`/`fold`/`_tool_permitted`. Do not host leaves on `Worker`. |
| `handoff.v1` next to `spawn_agent.v1` in `_CONTROL_PLANE_TOOLS` | That set is `{subagent_list, subagent_steer, await_subagent}`. `spawn_agent.v1` is a normal `_RegisteredTool`. | Register `handoff.v1` as a normal parent tool on the **FSI** loop, not the coding registry (unless dual-listed as REFUSED on children). |
| `load_skill.v1` will see FSI after copying files | `_load_skill` is `default_catalog()` only. | Patch executor with an actor-scoped `fsi_catalog()` ∩ allowlist. Do not add FSI to `default_skill_roots()`. |
| KYC PR = profile YAML + leaves | No HTTP, no packet upload that is not RAG, no artifact download, no `/fsi` page. | KYC v0 includes `POST /api/v1/fsi/sessions`, packet upload, `./out/` download, CLI `neos fsi run`. No approve button. |
| Mode A writer = stamp WORKTREE on `fsi-writer` | Worktree open/bind lives in `neos/coding/loop/_durable/spawn.py` + `subagent_worktree.py`. FSI loop must call `create_worktree` **itself**. `CodingToolPort` refuses writes unless WORKTREE. | Mode A waits on that bind (or documented Shape B). Mode B does not. |

Silent bug if catalog PRs land first: `stepper.py:108–111` uses explore's system prompt for every spec that is not `implement`. Explore's prompt allows `spawn_agent.v1`. FSI specs must get a third prompt builder (CMA `system.text` from the profile) **in the same merge as the catalog entries**, or delay catalog until `neos/fsi` injects prompts.

---

## 3. Ideal attachment map

```
skills/financial-services/<vertical>/<skill>/SKILL.md
        │  MarkdownSkillCatalog root = that vertical (one level)
        ▼
neos/fsi/profile.py          load_profile / compile_leaf_spec
        │
        ▼
neos/fsi/loop.py             parent model + spawn_agent.v1 handled HERE
        │  SubagentTicket(parent_kind=FSI, spec="kyc-doc-reader"|…)
        │  nested_spawn=None
        ▼
neos/subagent/runtime.py     advance until terminal → fold
        │
        ├─ ChildStepper       tools = FsiParentWorkspacePort ∪ McpSessionPort
        │                     system = profile leaf prompt (NOT explore)
        ├─ fold.py            truncate only
        └─ neos/fsi/schemas.py validate_child_fold AFTER fold
                │
                ▼
        stage_xlsx.v1 → ./out/*.xlsx → artifact row staged_for_signoff
                │
                ▼
POST /api/v1/fsi/sessions + GET .../artifacts   UI /fsi
```

Do not import `neos/fsi` from `neos/subagent` (import law). DA already shows the legal direction: DA/workflow/fsi **call** the kernel.

---

## 4. Ideal sequence (what to merge, in order)

Each phase is independently testable. Flags default false. Do not enable Mode A and Mode B in the same PR.

### Phase 0 — Policy without a runtime (≈ spec PR1)

**Why first:** the WORKFLOW recipe and Jev/DA flags both land the *closed set* before behavior. KYC "never approve" is a test, not a prompt.

- `neos/config/schema.py`: nested `FsiConfig` (`enabled`, `mode_b_enabled`, `mode_a_enabled`, `partner_mcp`), all default `false`. Child-on / master-off raises (same pattern as DA).
- `neos/fsi/safety.py`: binding denylist helpers (`policy_binding_denied`).
- `tests/fsi/test_safety_policy.py`: no ledger post, never KYC-approve, `staged_for_signoff` is not harness `fail`, quoted JSON is not a handoff.
- Add `handoff.v1` to `REFUSED_TOOLS` (`stepper.py:37–51`).

No tickets yet. HTTP 404 when `fsi.enabled` is false (catalog-picker pattern).

### Phase 1 — `ParentKind.FSI` plumbing (split out of spec PR3)

**Why this is its own merge:** `tests/subagent/test_workflow_parent_kind.py` exists specifically because "enum-only" silently folds metrics into `"coding"` and the first INSERT violates CHECK.

- `types.py`: `FSI = "fsi"`.
- `neos/subagent/metrics.py`: `_PARENTS` add `"fsi"`; later `_SPECS` add `fsi-*` or FSI advances label as `explore` (`metrics.py:8, 21–23`).
- New migration after `058_allow_workflow_subagent_parent.sql` widening `subagent_runs_parent_kind_check`.
- Clone `test_workflow_parent_kind.py` → `test_fsi_parent_kind.py` (enum set, CHECK contains every `ParentKind`, metrics keep the label).
- Bootstrap order after 058.

Still no FSI tickets in production code.

### Phase 2 — Five catalog templates + prompt branch (must be one merge)

- `catalog.py`: `fsi-reader`, `fsi-writer`, `fsi-critic`, `fsi-puller`, `fsi-modeler`. All `sandbox_mode=NONE`, `can_spawn=False`, `one_shot=True`, `load_project_instructions=False`. No template lists `spawn_agent.v1` or `handoff.v1`. Writer is the only template with `write_file.v1`.
- `lookup_spec("fsi_reader")` raises `UnknownSpec`.
- **Stepper:** if `spec.name` is not `explore`/`implement`, do **not** use `build_explore_system_prompt()`. Minimal safe default: a short "report only; do not spawn" prompt, replaced in Phase 3 by the profile leaf prompt injected at ticket/briefing time (parent-owned system text). Do not overload explore/implement strings.
- Widen `metrics.py` `_SPECS`.

This is the highest-risk silent bug in the original PR3 bundling.

### Phase 3 — Parent port + loop smoke (no KYC product yet)

Prove C1 with `InMemorySubagentStore` + fake model, **no** `DurableCodingLoop`:

- `neos/fsi/ports.py`: `FsiParentWorkspacePort` (`ToolPort` two-method surface). Mode B `NONE` → parent `/workspace` for `read_file.v1` / `write_file.v1` (path-restricted on writer).
- `neos/fsi/loop.py`: construct `SubagentTicket(parent_kind=FSI, …)`, `advance` until terminal, `fold`. `nested_spawn=None`. `subagent_max_active` default 1 (do not cite the coding spy).
- `neos/fsi/profile.py`: `load_profile`, `compile_tool_policy`, `compile_leaf_spec`.
- DDL: `fsi_sessions`, `fsi_artifacts`, `fsi_handoffs` (additive).
- `handoff.py` may stub `policy_handoff_denied`.
- Tests: unknown slug refuse; writer count ≠ 1 refuse; empty `handoff_allowlist` strips the tool; Mode A non-writer copy is `PARENT_RO` **as a stamp the loop honors when binding**; Mode B writer `write_file` of `*.xlsx` denied.

`compile_leaf_spec` must either **register an alias spec** the runtime can `lookup_spec`, or the loop must pass a `SpecRegistry` overlay into `SubagentRuntime(catalog=…)`. The kernel constructor already takes `catalog: SpecRegistry` (`runtime.py:111`). Prefer a **per-session registry** that starts from `_SPECS` and `register`s aliases. Do not mutate module globals.

### Phase 4 — Schema gate + untrusted wrapper

- `neos/fsi/schemas.py`: `READER_SCHEMAS` keyed by CMA alias. Ten schemas from `01-safety-handoff.md` §2. No 11th critic schema.
- After `runtime.fold`, `validate_child_fold`. Invalid → `schema_invalid`, harness `fail`, no parent consume. **Do not edit `fold.py`.**
- `<untrusted_document>` wrapper on reader presentation.
- Add `jsonschema` to the lockfile if missing.

### Phase 5 — Skill pack + `load_skill.v1` FSI branch (parallel with 0–4 after Phase 0)

- Copy 48 Anthropic vertical skills (exclude `skill-creator`) to `skills/financial-services/<vertical>/<skill>/`.
- Restore WM trio under `wealth-management/` **before** meeting-prep is enabled; CI path-resolve fails closed until then.
- `fsi_skill_roots()` = one `("repo", pack/<vertical>)` per vertical. `fsi_catalog()`. Accept `references/` as `reference/` alias.
- Patch `executor.py` `_load_skill`: FSI actor → `fsi_catalog() ∩ skill_allowlist`. Coding `default_catalog().get("xlsx-author") is None` remains true.
- Valid `mcp/hub.json` (comma + closed `box`). Hub is a URL catalog, not auto-attach.
- Fix `validate_dcf.py` to match SKILL.md (no `Sensitivity` sheet) in this pack PR so model-builder does not inherit the bug.
- Do not `copytree` into agent trees. Do not port `sync-agent-skills.py`.

### Phase 6 — MCP attach stubs (new subsystem)

- `neos/fsi/mcp_attach.py` + `McpSessionPort` **unioned** with `FsiParentWorkspacePort` (same `ToolPort`).
- Exact names `mcp.<server>.<tool>` (golden `mcp.screening.search`). Union into the **registered alias** `allowed_tools`.
- Mode B stubs: `screening`, `internal-gl`, `subledger`, `portfolio`, `nav`, `crm` — read-only, no `post_je` / `whitelist_party`.
- Missing Mode A CapIQ/Daloopa/FactSet URL → stub + stop-and-surface. Do not import `mcp_integration.py`. Do not attach hub `lseg`/`sp-global` unless `fsi.partner_mcp`.
- Real HTTP MCP client is a **later** split (6b). Stubs make KYC/GL testable without vendors.

### Phase 7 — First user-visible graph: `kyc-screener`

This is the ideal *product* start, not the first *commit*. Phases 0–6 make it a session instead of a YAML file.

Must ship together or the graph is unrunnable:

| Piece | Why |
|---|---|
| Profile YAML + CMA leaf aliases | KD17 |
| Reader wrap + schema | injection |
| Critic = `fsi-critic`, no schema | locked |
| Escalator `write_file.v1` only `./out/_spec/<packet>.json` | one-writer + UTF-8 |
| Parent `stage_xlsx.v1` → `./out/escalation-<packet>.xlsx` | real artifact |
| `POST /api/v1/fsi/sessions` | start path (Code-plane *shape*, not its loop) |
| Packet upload that is **not** RAG ingest | untrusted |
| `GET .../artifacts` download | human sign-off |
| UI `/fsi` (sidebar sibling of `/code`) | otherwise dead |
| CLI `neos fsi run` | harness tests |
| **No** approve button, **no** Slack, **no** WS required | binding denylist |

`fsi.mode_b_enabled` stays false until these tests exist. `disposition=clear` is still `staged_for_signoff`.

### Phase 8 — Remaining Mode B (one graph per PR)

Order matches isolation strictness, not org chart:

1. `gl-reconciler` (independent critic vs counterparty path; outbound allowlist **configured**, tool still deny-stub)
2. `month-end-closer` + `statement-auditor` (verbatim `Do not post` / `don't plug it` / `No distribution`)
3. `valuation-reviewer` (publisher never opens GP packages)

Same template: `fsi-reader` / `fsi-critic` / `fsi-writer`, `SandboxMode.NONE`, parent workspace, `stage_xlsx.v1`.

### Phase 9 — Mode A worktree (after P2 bind exists)

`model-builder` first (only bash-enabled writer: `model-builder-builder` + `execute.v1`). Then `pitch-agent` (`fsi-puller` / `fsi-modeler` / `fsi-writer`). Then market + earnings (untrusted readers **and** write leaves). Meeting-prep last (WM trio already on disk from Phase 5).

Loop must call `create_worktree` / `merge_worktree` from `neos/coding/subagent_worktree.py` **directly**, not via `_durable/spawn.py`. Until that bind is proven, Shape B (coding durable loop as builder only) is the documented interim — Mode B does not wait.

`pitch-modeler` is `PARENT_RO`, `execute.v1` stdout-only, no second worktree.

### Phase 10 — `handoff.v1` bus

After source and target `fsi_sessions` exist. Parent-only tool on the FSI loop. Edge allowlist from `01-safety-handoff.md`. Quoted document JSON does not steer. `context_ref` kept and fenced. KYC/meeting-prep/statement-auditor empty allowlists never receive the tool.

### Phase 11 — Partner catalogs

Last. Isolated `fsi_lseg_catalog()` / `fsi_spglobal_catalog()`. Anthropic `fsi_catalog().get("equity-research")` is None. No vendor redistribution. `fsi.partner_mcp` default false.

MS365 stays a separate track.

---

## 5. Mapping onto the locked 15-PR plan

Keep the PR titles. Split and add only what the tree requires.

| Locked PR | Code-grounded adjustment |
|---|---|
| PR1 flags + denylist | Keep. Add `REFUSED_TOOLS` here. |
| PR2 skill pack + `load_skill.v1` | Keep, parallel after PR1. Roots = per-vertical, not `skills/`. |
| PR3 parent loop + catalog + DDL | **Split:** PR3a `ParentKind.FSI` plumbing (Phase 1); PR3b catalog **with** stepper prompt branch (Phase 2); PR3c loop+port+profile+DDL (Phase 3). Shipping catalog without 3b is unsafe. |
| PR4 schema gate | Keep. After fold, not inside `fold.py`. |
| PR5 MCP stubs | Keep as new `ToolPort`. Call out catalog overlay/alias register. HTTP client is 5b. |
| PR6 KYC | **Add** HTTP + `/fsi` + artifact download + `stage_xlsx.v1`. Otherwise skip. |
| PR7–PR9 Mode B | Keep. |
| PR10–PR13 Mode A | Keep. Gate on worktree bind, not on DA. |
| PR14 handoff | Keep after sessions exist. |
| PR15 partners | Keep last. |

---

## 6. What not to do (code-proven)

| Temptation | Why it fails in this tree |
|---|---|
| Put FSI skills on `default_skill_roots()` | Coding `load_skill.v1` would start resolving `xlsx-author` / IB names in `/code` sessions |
| Flatten pack to `skills/<skill>/` | One-level scan works, but LSEG `equity-research` collides with Anthropic vertical |
| Host Mode B writers on `CodingToolPort` without WORKTREE | Port refuses writes |
| Host Mode B on DA `NONE` research box | Throwaway sandbox; no parent `/workspace`; no MCP; no xlsx |
| Reuse `mcp_integration.py` | Process-global; `FileProcessingMCPTool` writes/deletes |
| Start KYC from chat classifier | Packets become RAG/search state |
| Start KYC from `/code` | Wrong parent kind, `implement` tool surface, coding_invoke default off |
| `lookup_spec("implement")` for model-builder | git + mkdir/rm/mv/chmod |
| Put `output_schema` on `SubagentSpec` | Frozen dataclass; fold is text; schema is a parent after-step |
| Mutate `_SPECS` at runtime for MCP | Fail-closed global; use `SubagentRuntime(catalog=overlay)` |
| Cite `test_one_delivery_advances_exactly_one_child` as FSI | That spy is the coding durable loop |

---

## 7. First vertical slice (KYC) — files that must exist

Kernel (Phases 0–4), then:

```
neos/config/schema.py                          FsiConfig
neos/subagent/types.py                         ParentKind.FSI
neos/subagent/catalog.py                       five fsi-* templates
neos/subagent/stepper.py                       prompt branch + REFUSED handoff.v1
neos/subagent/metrics.py                       _PARENTS / _SPECS
db/migrations/0xx_fsi_parent_kind.sql
db/migrations/0xx_fsi_sessions.sql
neos/fsi/loop.py
neos/fsi/profile.py
neos/fsi/ports.py                              FsiParentWorkspacePort
neos/fsi/schemas.py                            kyc-doc-reader schema
neos/fsi/stage_xlsx.py
neos/fsi/mcp_attach.py                         screening stub
neos/fsi/safety.py
neos/fsi/postgres.py
neos/api/handlers/fsi_handlers.py              sessions + artifacts
neos/api/fsi_routes.py
web/app/(fsi)/                                 /fsi page, no approve
skills/financial-services/operations/kyc-doc-parse/
skills/financial-services/operations/kyc-rules/
skills/financial-services/financial-analysis/xlsx-author/   (allowlisted)
skills/financial-services/profiles/kyc-screener.yaml
tests/fsi/kyc/
tests/subagent/test_fsi_parent_kind.py
```

Success is: an operator with `fsi.enabled` + `fsi.mode_b_enabled` can upload a packet, receive `./out/escalation-<id>.xlsx`, and **cannot** click approve. Everything after that is more graphs on the same loop.

---

## 8. References (primary)

- `neos/subagent/{runtime,stepper,fold,catalog,types,metrics,postgres}.py`
- `tests/subagent/test_runtime.py` (no inner loop), `test_workflow_parent_kind.py` (widen recipe)
- `neos/skills/markdown_catalog.py` (`default_skill_roots` vs `research_skill_roots`)
- `neos/coding/tools/executor.py` `_load_skill`
- `neos/coding/loop/_durable/spawn.py`, `neos/coding/subagent_worktree.py`
- `neos/tools/mcp_integration.py` (do not reuse)
- `neos/workflow/deep_analysis/` (analogy: `advance` without durable loop; **not** the leaf host)
- Locked spec: [FSI_NEOS_MIGRATION_SPEC.md](./FSI_NEOS_MIGRATION_SPEC.md), [00-harness-and-profile.md](./00-harness-and-profile.md), [agents/kyc-screener.md](./agents/kyc-screener.md)
