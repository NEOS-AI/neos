# 02. Skills pack + MCP + Office harness

Normative port of Anthropic `financial-services` skills, slash aliases, MCP hubs, and the headless Office contract into Neos. This document implements [09-neos-migration-map.md](../09-neos-migration-map.md) §3 (skill transplant) and §6 (MCP). It does not define named-agent prompts, CMA worker graphs, or the handoff bus.

Counts are from the FSI working tree on 2026-09-25: **49** canonical vertical skill directories, **3** meeting-prep orphans with no current vertical source, **11** partner-built skill directories (LSEG 8 + S&P 3). Agent-plugin copies (51 dirs) are **not** a source of truth and are not vendored into Neos.

Related notes (descriptive, not this spec): [04-skills-financial-analysis.md](../04-skills-financial-analysis.md), [04b-skill-bundling.md](../04b-skill-bundling.md), [04c-skill-bundling-wave2.md](../04c-skill-bundling-wave2.md), [05-skills-ib-er.md](../05-skills-ib-er.md), [05b-mcp-manifests.md](../05b-mcp-manifests.md), [06-skills-pe-fundadmin-ops.md](../06-skills-pe-fundadmin-ops.md), [07-partners.md](../07-partners.md), [07b-partners-wave2.md](../07b-partners-wave2.md), [skills/office-harness.md](../skills/office-harness.md).

## Decisions locked

| # | Decision |
|---|---|
| D1 | Canonical tree is `skills/financial-services/<vertical>/<skill>/SKILL.md` (repo-root research catalog). One copy. Agent profiles hold an allowlist of names, not a second tree. |
| D2 | Do not flatten to `skills/financial-services/<skill>/`. That collides LSEG `equity-research` with the Anthropic vertical folder and drops provenance. |
| D3 | Index with **one catalog root per vertical**. `MarkdownSkillCatalog._index_skill_directories` stays one-level; only the root list changes. |
| D4 | FSI skills are research-catalog markdown (warn-only on missing `## When to Use` / `## Boundaries`). They never enter `default_skill_roots()` / the coding catalog, and they are never wrapped as `BaseSkill`. |
| D5 | Anthropic FSI skills share one catalog instance (`fsi_catalog`). LSEG and S&P each get their own catalog instance. Partner skills are never merged into the Anthropic name index and never appear on named-agent allowlists. |
| D6 | Restore `wealth-management` **before** meeting-prep-agent is considered complete. Canonicalize `client-report`, `client-review`, `investment-proposal` there. Do not invent deleted WM extras. |
| D7 | Do not merge FSI `pptx-author` / `xlsx-author` into Neos `skills/{pptx,docx,xlsx}`. Split of responsibility is §5. Recalc lives only at `skills/xlsx/scripts/recalc.py`. |
| D8 | Port a **valid** MCP hub JSON (comma + closed `box` object). The hub is a **URL catalog**, not auto-attach. CMA env vars and the agent `mcp_allowlist` decide what attaches. Mode B servers are read-only stubs until a real URL is configured. |
| D9 | Keep two LSEG endpoints as named variants (`lseg` vs `lseg-lfa-cl`). Keep one S&P key (`sp-global`) with alias `spglobal`. Do not attach hub `lseg` / partner S&P unless `fsi.partner_mcp` **and** entitlement. |
| D10 | Slash commands are aliases that load one or two skills. No command runtime. |
| D11 | CI resolves paths. It does **not** `copytree`. `sync-agent-skills.py` is not ported. |
| D12 | Do not port `skill-creator`, MS365 `verify`, empty hooks, empty IB/PE `.mcp.json`, missing example workbooks, or native `c:chart` OOXML. |
| D13 | DCF layout follows `dcf-model/SKILL.md`. Three sensitivity grids stay on the **DCF** sheet. Port `validate_dcf.py` and **drop its `Sensitivity` sheet expectation**. Do not add a `Sensitivity` sheet to SKILL.md. |
| D14 | `load_skill.v1` for an FSI actor resolves `fsi_catalog()` (or the partner catalog named on the profile) ∩ `skill_allowlist`. Coding `default_catalog()` never indexes `xlsx-author`. PR2/PR3 patch `neos/coding/tools/executor.py`. |

Port set: **48** vertical skills (`skill-creator` excluded) **+ 3** restored wealth-management skills **= 51** Anthropic domain skills, plus **11** partner skills gated on entitlement (stub if the vendor MCP is absent).

---

## 1. Target layout

```
skills/financial-services/
  allowlists/<agent-slug>.yaml          # CI source; must match agent-profile skill lists
  aliases.yaml                          # thin slash → skill map
  mcp/
    hub.json                            # Mode A market-data + doc stores (valid JSON)
    internal-stubs.json                 # Mode B GL/KYC/NAV/CRM/portfolio
    lseg.json                           # partner LFA /server-cl
    spglobal.json                       # partner Kensho (alias of hub sp-global)
  financial-analysis/<skill>/SKILL.md
  equity-research/<skill>/SKILL.md
  investment-banking/<skill>/SKILL.md
  private-equity/<skill>/SKILL.md
  fund-admin/<skill>/SKILL.md
  operations/<skill>/SKILL.md
  wealth-management/<skill>/SKILL.md    # restored; see §4
  lseg/<skill>/SKILL.md                 # partner, separate catalog
  spglobal/<skill>/SKILL.md             # partner, separate catalog
  <vertical>/commands/<slash>.md        # thick wrappers only (optional body)
```

Each skill directory is copied from the FSI **vertical** (or, for the meeting-prep trio, restored into `wealth-management/` from the surviving agent copy). Copy the whole directory: `SKILL.md`, `references/` or `reference/`, `scripts/`, `assets/`, `TROUBLESHOOTING.md`, `requirements.txt`. Do not copy agent-plugin trees, `.claude-plugin/`, empty `hooks/hooks.json`, or empty IB/PE `.mcp.json`.

Frontmatter stays as in the source: `name` + `description` only (plus `license` on FSI `skill-creator`, which is not ported). Do not invent `allowed-tools`, `when_to_use`, `user_invocable`, or `disable-model-invocation`. Do not add `## When to Use` / `## Boundaries` bodies so the coding catalog would accept them; FSI `skill-creator` itself puts when-to-use in YAML `description` because the body loads after trigger.

On-disk directory name is the FSI skill directory name. Catalog lookup key is YAML `name`. Two mismatches are preserved and CI-warned, not silently rewritten:

| Directory | Frontmatter `name` | Alias that must resolve |
|---|---|---|
| `investment-banking/strip-profile` | `fsi-strip-profile` | slash `/one-pager` says `strip-profile` |
| `spglobal/earnings-preview-beta` | `earnings-preview-single` | description trigger only (no slash) |

`load_markdown` / agent allowlists use the frontmatter name. Slash aliases may use the directory name; `aliases.yaml` maps both.

### 1.1 What does not live here

| Path | Owner |
|---|---|
| `skills/{pptx,docx,xlsx,pptx-posters,skill-creator}/` | Existing Neos generic Office / skill-authoring. Unchanged location. |
| `neos/coding/skills/` | Coding catalog (`plan`, `commit`, `verify`, …). **Not Office, not FSI.** |
| `neos/skills/builtin/` | Executable `skill.py` builtins. FSI does not go here. |
| Named-agent system prompts | `docs/financial-services/spec/agents/` + runtime profiles (separate spec). |
| CMA worker YAML | Worker-graph spec. Skills are referenced by allowlist name, not vendored. |

---

## 2. Nested catalog root change

File: [`neos/skills/markdown_catalog.py`](../../../neos/skills/markdown_catalog.py).

### 2.1 Current scanner is one-level

`research_skill_roots()` today returns:

```python
("repo", _REPO_ROOT / "skills"),
("builtin", _REPO_ROOT / "neos" / "skills" / "builtin"),
```

`_index_skill_directories` walks **immediate children** of each root and looks for `<root>/<child>/SKILL.md`. It does not recurse.

If the pack is `skills/financial-services/<vertical>/<skill>/SKILL.md` and the only research root is `skills/`, the scanner looks for `skills/financial-services/SKILL.md` and finds nothing. That is the bug this spec fixes.

`default_skill_roots()` is coding-only (`neos/coding/skills/`). Coding skip (`_coding_sections_valid`) requires exact ATX `## When to Use` / `## Boundaries` with non-empty bodies. Almost none of the 49+3+11 FSI skills have both headings (observed body `## When to Use`: Anthropic `earnings-analysis` and S&P `funding-digest` only). Putting the pack on the coding catalog would drop it.

FSI stays a **research** catalog: missing headings **warn** via `_has_required_sections` and still index. `MarkdownSkill.when_to_use` is `""`. Routing uses `description`, same as Cowork.

Entries are never executed as `BaseSkill`. Scripts (`validate_dcf.py`, `extract_numbers.py`) run via Bash from the skill body, same as Cowork. Do not wrap FSI skills in `neos/skills/builtin/*/skill.py`.

### 2.2 Preferred fix: one root per vertical

Do **not** recurse. Do **not** flatten. Do **not** add a new `SkillSource`; `"repo"` is enough.

Add the following to `markdown_catalog.py` (names may match this shape; tests pin behavior, not spelling of locals):

```python
FSI_PACK = _REPO_ROOT / "skills" / "financial-services"

FSI_ANTHROPIC_VERTICALS: tuple[str, ...] = (
    "financial-analysis",
    "equity-research",
    "investment-banking",
    "private-equity",
    "fund-admin",
    "operations",
    "wealth-management",
)

FSI_PARTNER_VERTICALS: tuple[str, ...] = ("lseg", "spglobal")


def fsi_skill_roots() -> tuple[tuple[SkillSource, Path], ...]:
    """Immediate-child SKILL.md scan under each Anthropic vertical."""
    return tuple(("repo", FSI_PACK / vertical) for vertical in FSI_ANTHROPIC_VERTICALS)


def fsi_partner_skill_roots(
    vendor: Literal["lseg", "spglobal"],
) -> tuple[tuple[SkillSource, Path], ...]:
    if vendor not in FSI_PARTNER_VERTICALS:
        raise ValueError(f"unknown FSI partner vertical: {vendor}")
    return (("repo", FSI_PACK / vendor),)
```

Cached constructors:

- `fsi_catalog()` → `MarkdownSkillCatalog(roots=fsi_skill_roots())`
- `fsi_lseg_catalog()` → `MarkdownSkillCatalog(roots=fsi_partner_skill_roots("lseg"))`
- `fsi_spglobal_catalog()` → `MarkdownSkillCatalog(roots=fsi_partner_skill_roots("spglobal"))`

`research_skill_roots()` keeps `skills/` + builtin so existing research skills (`pdf`, `pptx`, `xlsx`, …) still index as today. It does **not** add `skills/financial-services` as a single root (that would look for `SKILL.md` on the pack folder). FSI named agents construct `fsi_catalog()` and pass an allowlist of names. Research chat may attach `fsi_catalog()` as an extra catalog; it must not merge partner catalogs into that instance.

`_put` still keeps the first skill of a given name and debug-logs later duplicates. CI fails on duplicate frontmatter `name` **inside one catalog**. Partner isolation (D5) is what prevents LSEG `equity-research` from colliding with anything in the Anthropic index.

Do not add `skills/financial-services` itself as a root, and do not teach `_index_skill_directories` to recurse “one extra level” unless a later change proves the per-vertical root list unmaintainable. The vertical directory **is** the provenance key.

### 2.3 `reference/` vs `references/`

`load_markdown(..., reference=leaf)` today resolves only `<skill_dir>/reference/<leaf>.md` (no `..`, no subdirs). FSI on-disk layout:

| On disk | Catalog `reference=` today |
|---|---|
| `pitch-deck/reference/*.md` (singular) | works |
| `3-statement-model/references/`, `competitive-analysis/references/`, `earnings-analysis/references/`, `ib-check-deck/references/`, `initiating-coverage/references/`, S&P `funding-digest/references/`, S&P `tear-sheet/references/` | **misses** |
| `initiating-coverage/assets/` | not a reference dir (output templates) |
| S&P `earnings-preview-beta/report-template.md` (skill root) | not under reference/ |

**Required change:** `_load_reference` tries `reference/` then `references/`. Both stay jailed (`is_relative_to(ref_dir)`, `_path_allowed`, `_safe_reference_leaf` unchanged: no `..`, no `/`, no hidden files). First existing file wins. Do not recurse into subdirectories of either folder.

`assets/` and skill-root extra markdown (S&P `report-template.md`) stay model-Read paths named in `SKILL.md`. Do not extend `reference=` to those.

### 2.4 Allowlist shape

An FSI agent profile names skills as `(catalog_id, name)`:

| `catalog_id` | Constructor | Who uses it |
|---|---|---|
| `fsi` | `fsi_catalog()` | All 10 Anthropic named agents |
| `fsi-lseg` | `fsi_lseg_catalog()` | LSEG slash / entitlement sessions only |
| `fsi-spglobal` | `fsi_spglobal_catalog()` | S&P entitlement sessions only |
| `research` | `MarkdownSkillCatalog(roots=research_skill_roots())` | Generic `pptx` / `docx` / `xlsx` / `skill-creator` when an FSI skill **delegates** |

Named-agent allowlists are `catalog_id: fsi` plus the names in §3.10. They must not include partner names. Generic Office skills are **not** copied onto the FSI allowlist; FSI Office skills name them in prose and the runtime already has the research catalog for ad-hoc “make me a pptx” outside FSI agents.

### 2.5 `load_skill.v1` must switch catalog for FSI actors

Live `load_skill.v1` (`neos/coding/tools/executor.py` `_load_skill`, ~1310–1340) always does:

```python
from neos.skills.markdown_catalog import default_catalog
catalog = default_catalog()
skill = catalog.get(name)
```

`default_catalog()` is coding-only (`default_skill_roots()` → `neos/coding/skills/`). `research_skill_roots()` is documented “Not used by load_skill.v1.” After PR2 copies `xlsx-author` onto disk, a coding or FSI caller of `load_skill.v1 name=xlsx-author` still gets `unknown_skill` unless this branch exists.

**Do not** add FSI roots to `default_skill_roots()`. **Do not** add a `catalog_id` argument to the existing `load_skill.v1` tool schema. Actor identity already sits on the coding session / FSI profile; the executor reads it.

PR2 or PR3 **must** patch `_load_skill` (same function, same tool name) to:

1. If the caller is **not** an FSI actor (no FSI profile on the session): keep today’s path — `default_catalog()` only. `xlsx-author` remains `unknown_skill`.
2. If the caller **is** an FSI actor (named-agent parent or FSI leaf compiled from a profile):
   - Resolve catalog from `profile.catalog_id` (`fsi` → `fsi_catalog()`, `fsi-lseg` → `fsi_lseg_catalog()`, `fsi-spglobal` → `fsi_spglobal_catalog()`). Default `fsi` when the profile omits it.
   - Let `allow = profile.skill_allowlist` (frozenset of frontmatter names). A missing or empty allowlist is empty, not “all skills.”
   - If `name not in allow`: return `denied` / `unknown_skill` even if `catalog.get(name)` would succeed. Untrusted readers ship `skill_allowlist: []` and therefore cannot load `kyc-doc-parse` / `xlsx-author` / anything else.
   - Else `skill = catalog.get(name)` and `load_markdown` as today (including `reference=` / `references/` from §2.3). `disable_model_invocation` still denies.
3. Partner catalogs are reachable only when the session’s `catalog_id` is `fsi-lseg` or `fsi-spglobal`. An Anthropic named agent (`catalog_id: fsi`) asking for LSEG `equity-research` is `unknown_skill`.
4. Writers and parents that list `xlsx-author` on the allowlist load it from `fsi_catalog()`. Coding `implement` / `explore` sessions never do.

Where the profile is read: the FSI parent loop / leaf `SubagentSpec` compile path (harness spec) must stash `catalog_id` + `skill_allowlist` on the `SandboxSession` (or the FSI actor context `_load_skill` already can see). This spec does not invent a second `load_skill` tool.

Tests for this branch live in `tests/coding/` next to existing `_load_skill` tests **and** are repeated in §11.3:

| Caller | `skill_allowlist` | `load_skill.v1 name=xlsx-author` |
|---|---|---|
| Coding session / `default_catalog()` | n/a | `unknown_skill` |
| FSI parent (e.g. pitch-agent, KYC) | includes `xlsx-author` | `ok`, markdown from `skills/financial-services/financial-analysis/xlsx-author/SKILL.md` |
| FSI reader / critic | `[]` | `unknown_skill` |
| FSI parent | allowlist omits `xlsx-author` | `unknown_skill` |
| FSI parent `catalog_id: fsi` | any | `name=equity-research` → `unknown_skill` (LSEG skill is not in `fsi_catalog`) |

`default_catalog().get("xlsx-author")` remains `None` after the pack lands.

---

## 3. Complete skill inventory

**FSI canonical source:** `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/<vertical>/skills/<skill>/`  
**FSI agent copies (do not port as source):** `plugins/agent-plugins/<slug>/skills/<skill>/`  
**FSI partners:** `plugins/partner-built/{lseg,spglobal}/skills/`  
**Neos target:** `skills/financial-services/<vertical>/<skill>/SKILL.md`

Agent abbreviations: PA=`pitch-agent`, MR=`market-researcher`, ER=`earnings-reviewer`, MPA=`meeting-prep-agent`, MB=`model-builder`, GL=`gl-reconciler`, KYC=`kyc-screener`, VR=`valuation-reviewer`, MEC=`month-end-closer`, SA=`statement-auditor`.

`scripts?` means a `scripts/` directory with executable Python. Inline snippets in `SKILL.md` do not count. `*` = bundled on disk in FSI but omitted from that agent's `agents/<slug>.md` “Skills this agent uses” list. Neos allowlist **is** the bundle, so those names are listed in §3.10 and the prompt Skills section must match (CI fails on divergence).

### 3.1 financial-analysis (13 dirs; port 12)

Source: `plugins/vertical-plugins/financial-analysis/skills/`

| name | vertical | FSI source | agents | scripts? | Neos target | port? |
|---|---|---|---|---|---|---|
| `3-statement-model` | financial-analysis | `…/3-statement-model/` | PA, MB | no (`references/{formatting,formulas,sec-filings}.md`) | `skills/financial-services/financial-analysis/3-statement-model/SKILL.md` | yes |
| `audit-xls` | financial-analysis | `…/audit-xls/` | PA, ER, MB, GL, MEC, SA | no | `…/financial-analysis/audit-xls/SKILL.md` | yes |
| `clean-data-xls` | financial-analysis | `…/clean-data-xls/` | — (vertical-only) | no | `…/financial-analysis/clean-data-xls/SKILL.md` | yes |
| `competitive-analysis` | financial-analysis | `…/competitive-analysis/` | MR | no (`references/{frameworks,schemas}.md`) | `…/financial-analysis/competitive-analysis/SKILL.md` | yes |
| `comps-analysis` | financial-analysis | `…/comps-analysis/` | PA, MR, MB | no (cites missing `examples/comps_example.xlsx`) | `…/financial-analysis/comps-analysis/SKILL.md` | yes |
| `dcf-model` | financial-analysis | `…/dcf-model/` | PA, MB | **yes** `scripts/validate_dcf.py` + `requirements.txt` + `TROUBLESHOOTING.md` | `…/financial-analysis/dcf-model/SKILL.md` | yes; keep SKILL.md sheet layout; fix `validate_dcf.py`; drop unused `requests` |
| `deck-refresh` | financial-analysis | `…/deck-refresh/` | PA | no | `…/financial-analysis/deck-refresh/SKILL.md` | yes |
| `ib-check-deck` | financial-analysis | `…/ib-check-deck/` | PA | **yes** `scripts/extract_numbers.py` + `references/{ib-terminology,report-format}.md` | `…/financial-analysis/ib-check-deck/SKILL.md` | yes |
| `lbo-model` | financial-analysis | `…/lbo-model/` | PA, MB | no (cites missing `examples/LBO_Model.xlsx` and `/mnt/skills/public/xlsx/recalc.py`) | `…/financial-analysis/lbo-model/SKILL.md` | yes; rewrite recalc path to `skills/xlsx/scripts/recalc.py` |
| `ppt-template-creator` | financial-analysis | `…/ppt-template-creator/` | — (meta; vertical-only) | no | `…/financial-analysis/ppt-template-creator/SKILL.md` | yes; it may call Neos `skills/skill-creator` and `skills/pptx`, never FSI `skill-creator` |
| `pptx-author` | financial-analysis | `…/pptx-author/` | PA*, MR, MPA | no | `…/financial-analysis/pptx-author/SKILL.md` | yes |
| `skill-creator` | financial-analysis | `…/skill-creator/` | — | **yes** `scripts/{init_skill,package_skill,quick_validate}.py` | — | **no** (§10) |
| `xlsx-author` | financial-analysis | `…/xlsx-author/` | PA*, ER*, MB*, GL, KYC, VR, MEC, SA (8) | no | `…/financial-analysis/xlsx-author/SKILL.md` | yes |

`dcf-model` / `lbo-model` currently call `python recalc.py` or `python /mnt/skills/public/xlsx/recalc.py`. That file is not in the FSI tree. Canonical is [`skills/xlsx/scripts/recalc.py`](../../../skills/xlsx/scripts/recalc.py). Point both SKILL.md files at that path. Do not copy recalc into the FSI pack.

`dcf-model/SKILL.md` is the layout contract. It places **three sensitivity grids on the DCF sheet** (not a separate `Sensitivity` tab). Port `scripts/validate_dcf.py` and **change the checker**: drop the `Sensitivity` sheet expectation; validate those grids on `DCF` (plus `WACC` as SKILL.md already specifies). Do not add a `Sensitivity` sheet to SKILL.md. Drop unused `requests` from `requirements.txt`.

### 3.2 equity-research (9)

Source: `plugins/vertical-plugins/equity-research/skills/`

| name | vertical | FSI source | agents | scripts? | Neos target | port? |
|---|---|---|---|---|---|---|
| `catalyst-calendar` | equity-research | `…/catalyst-calendar/` | — | no | `skills/financial-services/equity-research/catalyst-calendar/SKILL.md` | yes |
| `earnings-analysis` | equity-research | `…/earnings-analysis/` | ER | no (`references/{best-practices,report-structure,workflow}.md`) | `…/equity-research/earnings-analysis/SKILL.md` | yes |
| `earnings-preview` | equity-research | `…/earnings-preview/` | ER | no | `…/equity-research/earnings-preview/SKILL.md` | yes |
| `idea-generation` | equity-research | `…/idea-generation/` | MR | no | `…/equity-research/idea-generation/SKILL.md` | yes |
| `initiating-coverage` | equity-research | `…/initiating-coverage/` | — | no (`assets/` + 6 `references/`) | `…/equity-research/initiating-coverage/SKILL.md` | yes; BUY/HOLD/SELL stay draft + compliance gate (migration map §3.3) |
| `model-update` | equity-research | `…/model-update/` | ER | no | `…/equity-research/model-update/SKILL.md` | yes |
| `morning-note` | equity-research | `…/morning-note/` | ER | no | `…/equity-research/morning-note/SKILL.md` | yes |
| `sector-overview` | equity-research | `…/sector-overview/` | PA, MR | no | `…/equity-research/sector-overview/SKILL.md` | yes |
| `thesis-tracker` | equity-research | `…/thesis-tracker/` | — | no | `…/equity-research/thesis-tracker/SKILL.md` | yes |

### 3.3 investment-banking (9)

Source: `plugins/vertical-plugins/investment-banking/skills/`  
Only `pitch-deck` is agent-bundled. All nine port.

| name | vertical | FSI source | agents | scripts? | Neos target | port? |
|---|---|---|---|---|---|---|
| `buyer-list` | investment-banking | `…/buyer-list/` | — | no | `skills/financial-services/investment-banking/buyer-list/SKILL.md` | yes |
| `cim-builder` | investment-banking | `…/cim-builder/` | — | no | `…/investment-banking/cim-builder/SKILL.md` | yes |
| `datapack-builder` | investment-banking | `…/datapack-builder/` | — | no | `…/investment-banking/datapack-builder/SKILL.md` | yes |
| `deal-tracker` | investment-banking | `…/deal-tracker/` | — | no | `…/investment-banking/deal-tracker/SKILL.md` | yes |
| `merger-model` | investment-banking | `…/merger-model/` | — | no | `…/investment-banking/merger-model/SKILL.md` | yes |
| `pitch-deck` | investment-banking | `…/pitch-deck/` | PA | no (`reference/` **singular**: calculation / formatting / slide-templates / xml-reference) | `…/investment-banking/pitch-deck/SKILL.md` | yes |
| `process-letter` | investment-banking | `…/process-letter/` | — | no | `…/investment-banking/process-letter/SKILL.md` | yes |
| `strip-profile` | investment-banking | `…/strip-profile/` | — | no. Frontmatter `name: fsi-strip-profile`. Cites missing `examples/Nike_Strip_Profile_Example.pptx` | `…/investment-banking/strip-profile/SKILL.md` | yes |
| `teaser` | investment-banking | `…/teaser/` | — | no | `…/investment-banking/teaser/SKILL.md` | yes |

No slash for `pitch-deck` or `datapack-builder`; invocation is description or PA allowlist.

### 3.4 private-equity (10)

Source: `plugins/vertical-plugins/private-equity/skills/`  
Agent-bundled: `ic-memo`, `portfolio-monitoring`, `returns-analysis` (VR only).

| name | vertical | FSI source | agents | scripts? | Neos target | port? |
|---|---|---|---|---|---|---|
| `ai-readiness` | private-equity | `…/ai-readiness/` | — | no | `skills/financial-services/private-equity/ai-readiness/SKILL.md` | yes |
| `dd-checklist` | private-equity | `…/dd-checklist/` | — | no | `…/private-equity/dd-checklist/SKILL.md` | yes |
| `dd-meeting-prep` | private-equity | `…/dd-meeting-prep/` | — | no | `…/private-equity/dd-meeting-prep/SKILL.md` | yes |
| `deal-screening` | private-equity | `…/deal-screening/` | — | no | `…/private-equity/deal-screening/SKILL.md` | yes |
| `deal-sourcing` | private-equity | `…/deal-sourcing/` | — | no | `…/private-equity/deal-sourcing/SKILL.md` | yes |
| `ic-memo` | private-equity | `…/ic-memo/` | VR | no | `…/private-equity/ic-memo/SKILL.md` | yes |
| `portfolio-monitoring` | private-equity | `…/portfolio-monitoring/` | VR | no | `…/private-equity/portfolio-monitoring/SKILL.md` | yes |
| `returns-analysis` | private-equity | `…/returns-analysis/` | VR | no | `…/private-equity/returns-analysis/SKILL.md` | yes |
| `unit-economics` | private-equity | `…/unit-economics/` | — | no | `…/private-equity/unit-economics/SKILL.md` | yes |
| `value-creation-plan` | private-equity | `…/value-creation-plan/` | — | no | `…/private-equity/value-creation-plan/SKILL.md` | yes |

### 3.5 fund-admin (6)

Source: `plugins/vertical-plugins/fund-admin/skills/`  
No `commands/`, no `hooks/`, no `.mcp.json`. All six land on an ops agent. Do not weaken “never approves” / “Do not post” / “don't plug it”.

| name | vertical | FSI source | agents | scripts? | Neos target | port? |
|---|---|---|---|---|---|---|
| `accrual-schedule` | fund-admin | `…/accrual-schedule/` | MEC | no | `skills/financial-services/fund-admin/accrual-schedule/SKILL.md` | yes |
| `break-trace` | fund-admin | `…/break-trace/` | GL | no | `…/fund-admin/break-trace/SKILL.md` | yes |
| `gl-recon` | fund-admin | `…/gl-recon/` | GL | no | `…/fund-admin/gl-recon/SKILL.md` | yes |
| `nav-tieout` | fund-admin | `…/nav-tieout/` | SA | no | `…/fund-admin/nav-tieout/SKILL.md` | yes |
| `roll-forward` | fund-admin | `…/roll-forward/` | MEC | no | `…/fund-admin/roll-forward/SKILL.md` | yes |
| `variance-commentary` | fund-admin | `…/variance-commentary/` | MEC | no | `…/fund-admin/variance-commentary/SKILL.md` | yes |

### 3.6 operations (2)

Source: `plugins/vertical-plugins/operations/skills/`  
No `commands/`, no `hooks/`, no `.mcp.json`.

| name | vertical | FSI source | agents | scripts? | Neos target | port? |
|---|---|---|---|---|---|---|
| `kyc-doc-parse` | operations | `…/kyc-doc-parse/` | KYC | no | `skills/financial-services/operations/kyc-doc-parse/SKILL.md` | yes |
| `kyc-rules` | operations | `…/kyc-rules/` | KYC | no | `…/operations/kyc-rules/SKILL.md` | yes |

Keep the untrusted wrapper `<untrusted_document> … </untrusted_document>` in `kyc-doc-parse`. KYC never approves.

### 3.7 meeting-prep 3 (orphans → wealth-management)

No current FSI vertical source. Copies live only at `plugins/agent-plugins/meeting-prep-agent/skills/`. Origin is deleted `plugins/vertical-plugins/wealth-management/` (`#349` / `734150c`, 2026-09-11). Bytes still match the WM `SKILL.md` at `734150c^`. `claude-for-financial-advisors` (added `#350`, deleted `#354`) never contained these three names.

FSI `sync-agent-skills.py` and `check.py` §4b **fail** on these three today. Neos restores the vertical first (§4).

| name | vertical | FSI source today | agents | scripts? | Neos target | port? |
|---|---|---|---|---|---|---|
| `client-report` | wealth-management (restored) | `plugins/agent-plugins/meeting-prep-agent/skills/client-report/` | MPA | no | `skills/financial-services/wealth-management/client-report/SKILL.md` | yes |
| `client-review` | wealth-management (restored) | `…/client-review/` | MPA | no | `…/wealth-management/client-review/SKILL.md` | yes |
| `investment-proposal` | wealth-management (restored) | `…/investment-proposal/` | MPA | no | `…/wealth-management/investment-proposal/SKILL.md` | yes |

CMA `pack-writer.yaml` paths only `client-review` + `pptx-author`. `client-report` and `investment-proposal` stay on the orchestrator allowlist / agent.md list, not on the Write leaf.

Deleted with WM and **not** surviving on any agent: `financial-plan`, `portfolio-rebalance`, `tax-loss-harvesting`. Do not invent them back.

### 3.8 partner LSEG (8)

Source: `plugins/partner-built/lseg/skills/`  
Not copied by `sync-agent-skills.py`. No agent bundle. SKILL.md only.

| name | vertical | FSI source | agents | scripts? | Neos target | port? |
|---|---|---|---|---|---|---|
| `bond-futures-basis` | lseg | `…/lseg/skills/bond-futures-basis/` | — | no | `skills/financial-services/lseg/bond-futures-basis/SKILL.md` | yes, entitlement-gated |
| `bond-relative-value` | lseg | `…/bond-relative-value/` | — | no | `…/lseg/bond-relative-value/SKILL.md` | yes, entitlement-gated |
| `equity-research` | lseg | `…/equity-research/` | — | no | `…/lseg/equity-research/SKILL.md` | yes, **separate catalog** (§7) |
| `fixed-income-portfolio` | lseg | `…/fixed-income-portfolio/` | — | no | `…/lseg/fixed-income-portfolio/SKILL.md` | yes, entitlement-gated |
| `fx-carry-trade` | lseg | `…/fx-carry-trade/` | — | no | `…/lseg/fx-carry-trade/SKILL.md` | yes, entitlement-gated |
| `macro-rates-monitor` | lseg | `…/macro-rates-monitor/` | — | no | `…/lseg/macro-rates-monitor/SKILL.md` | yes, entitlement-gated |
| `option-vol-analysis` | lseg | `…/option-vol-analysis/` | — | no | `…/lseg/option-vol-analysis/SKILL.md` | yes, entitlement-gated |
| `swap-curve-strategy` | lseg | `…/swap-curve-strategy/` | — | no | `…/lseg/swap-curve-strategy/SKILL.md` | yes, entitlement-gated |

Keep frontmatter `name: equity-research` on the LSEG skill. Do not rename it (slash `/research-equity` says “See the **equity-research** skill”). Isolation is the separate catalog, not a rename.

### 3.9 partner S&P Global (3)

Source: `plugins/partner-built/spglobal/skills/`  
Dir is `spglobal`; plugin.json / marketplace name is `sp-global`. No commands. Not synced into agents.

| frontmatter name | dir | vertical | FSI source | agents | scripts? | Neos target | port? |
|---|---|---|---|---|---|---|---|
| `earnings-preview-single` | `earnings-preview-beta` | spglobal | `…/spglobal/skills/earnings-preview-beta/` | — | no (`report-template.md`, LICENSE) | `skills/financial-services/spglobal/earnings-preview-beta/SKILL.md` | yes, entitlement-gated |
| `funding-digest` | `funding-digest` | spglobal | `…/funding-digest/` | — | no (`references/sector-seeds.md`) | `…/spglobal/funding-digest/SKILL.md` | yes, entitlement-gated |
| `tear-sheet` | `tear-sheet` | spglobal | `…/tear-sheet/` | — | no (`references/{corp-dev,equity-research,ib-ma,sales-bd}.md`) | `…/spglobal/tear-sheet/SKILL.md` | yes, entitlement-gated |

`tear-sheet/references/equity-research.md` is an **audience template**, not a skill. Still a string collision with LSEG skill `equity-research` and the Anthropic vertical folder `equity-research`. S&P `tear-sheet` calls Neos `skills/docx` for Word mechanics (`Read …/docx/SKILL.md` maps there). Do not fork `docx` into `spglobal/`.

S&P `earnings-preview-single` forbids web search. Anthropic `earnings-preview` allows web consensus. Keep both; allowlists pick one. Never install both into the same un-namespaced index.

### 3.10 Agent allowlists (directory = truth)

These names are the Neos allowlist for `catalog_id: fsi`. They match FSI agent-plugin skill **directories**, including the `xlsx-author` / `pptx-author` extras that FSI `check.py` §4b2 does not reverse-check.

| agent | allowlist (frontmatter / catalog name) |
|---|---|
| pitch-agent | `3-statement-model`, `audit-xls`, `comps-analysis`, `dcf-model`, `deck-refresh`, `ib-check-deck`, `lbo-model`, `pitch-deck`, `pptx-author`, `sector-overview`, `xlsx-author` |
| market-researcher | `competitive-analysis`, `comps-analysis`, `idea-generation`, `pptx-author`, `sector-overview` |
| earnings-reviewer | `audit-xls`, `earnings-analysis`, `earnings-preview`, `model-update`, `morning-note`, `xlsx-author` |
| meeting-prep-agent | `client-report`, `client-review`, `investment-proposal`, `pptx-author` |
| model-builder | `3-statement-model`, `audit-xls`, `comps-analysis`, `dcf-model`, `lbo-model`, `xlsx-author` |
| gl-reconciler | `audit-xls`, `break-trace`, `gl-recon`, `xlsx-author` |
| kyc-screener | `kyc-doc-parse`, `kyc-rules`, `xlsx-author` |
| valuation-reviewer | `ic-memo`, `portfolio-monitoring`, `returns-analysis`, `xlsx-author` |
| month-end-closer | `accrual-schedule`, `audit-xls`, `roll-forward`, `variance-commentary`, `xlsx-author` |
| statement-auditor | `audit-xls`, `nav-tieout`, `xlsx-author` |

Share frequency: `xlsx-author` 8 · `audit-xls` 6 · `pptx-author` 3 · `comps-analysis` 3 · `3-statement-model` / `dcf-model` / `lbo-model` / `sector-overview` 2 · rest 1.

Write-leaf subsets (CMA, for the worker-graph spec): `xlsx-author` on almost every writer; `pptx-author` on market-researcher `note-writer`, meeting-prep `pack-writer` (with `client-review` only), pitch-agent `deck-writer` (with `pitch-deck`). Orchestrator allowlists may be larger than the Write leaf. CI checks orchestrator allowlist ⊇ leaf allowlist, and every name resolves on disk.

21 vertical skills are bundled into **no** FSI agent. Neos still ports 20 of them (all except `skill-creator`) so slash / description invocation works outside named agents.

### 3.11 Out of pack (not FSI domain skills)

- `claude-for-msft-365-install/.claude/skills/verify/SKILL.md` — Office add-in install verifier.
- Empty `hooks/hooks.json` (`{"hooks":{}}`) on equity-research, financial-analysis, investment-banking, private-equity. fund-admin / operations / agents / partners have no hooks file.

---

## 4. meeting-prep 3-skill restore plan

### 4.1 Why restore, and to which vertical

FSI deleted `plugins/vertical-plugins/wealth-management/` in `#349` / `734150c` (2026-09-11) and left the three skills only on `meeting-prep-agent`. `claude-for-financial-advisors` never held `client-report` / `client-review` / `investment-proposal` (it had `pre-meeting` / `post-meeting` / similar, then the whole plugin was deleted in `#354`). The cookbook README still labels meeting-prep-agent as vertical `wealth-management`.

**Restore name: `wealth-management`, not `advisors`.** Neos target paths in §3.7 use that name. `fsi_skill_roots()` includes `wealth-management` from day one; CI fails until the three `SKILL.md` files exist.

### 4.2 Byte source

1. Prefer git: `git show 734150c^:plugins/vertical-plugins/wealth-management/skills/<name>/SKILL.md` (and any sibling files that existed).
2. If the blob is identical to the surviving agent copy (it was, at 2026-09-25), copy from `plugins/agent-plugins/meeting-prep-agent/skills/{client-report,client-review,investment-proposal}/`.
3. Write into `skills/financial-services/wealth-management/<name>/`. Do not leave the only copy under an agent path.

Do not pull anything from `claude-for-financial-advisors` history.

### 4.3 What not to restore

| Deleted WM skill | Action |
|---|---|
| `financial-plan` | Do not restore |
| `portfolio-rebalance` | Do not restore |
| `tax-loss-harvesting` | Do not restore |

Those three were deleted with the vertical and are **not** on meeting-prep-agent. Restoring them is a later full-WM spec, not this pack.

### 4.4 Slash aliases to restore

Deleted with WM (not in the current FSI tree). Restore as thin aliases in `aliases.yaml`:

| slash | skill |
|---|---|
| `/client-report` | `client-report` |
| `/client-review` | `client-review` |
| `/proposal` | `investment-proposal` |

### 4.5 Allowlist vs Write leaf

| Surface | Skills |
|---|---|
| meeting-prep-agent orchestrator / agent.md | `client-report`, `client-review`, `investment-proposal`, `pptx-author` |
| CMA `pack-writer` (only Write leaf) | `client-review`, `pptx-author` |
| profiler / news-reader | none of the three (CRM + CapIQ MCP, no Office write) |

CI: meeting-prep-agent cannot go green until `wealth-management/{client-report,client-review,investment-proposal}/SKILL.md` resolve. There is no orphan allowlist.

### 4.6 Sequence

1. Create `skills/financial-services/wealth-management/`.
2. Copy the three skill directories; confirm YAML `name` equals directory name.
3. Add the three slash aliases.
4. Point meeting-prep-agent allowlist at those paths.
5. Only then enable the meeting-prep-agent profile in runtime tests.
6. Do not run any copytree from vertical → agent. There is no agent skill tree in Neos.

---

## 5. Office split vs `skills/{pptx,docx,xlsx}`

The migration-map sentence that points Office overlap at `neos/coding/skills/` is a **path error**. Coding catalog today is seven flat files (`commit.md`, `notebook.md`, `plan.md`, `read-image.md`, `read-pdf.md`, `verify.md`, `web-search.md`), all with `## When to Use` / `## Boundaries`. There is no pptx/docx/xlsx there.

Real overlap is repo-root research skills:

| Path | Catalog | Job |
|---|---|---|
| `skills/pptx/SKILL.md` | research | Generic PPTX: pptxgenjs create, unzip/XML edit, `scripts/office/validate.py`, LibreOffice visual QA. Trigger: any `.pptx`/`.potx` / “deck” / “slides”. |
| `skills/docx/SKILL.md` | research | Generic Word: docx-js create, XML edit, comments/redline, soffice PDF. Trigger: any `.docx`. |
| `skills/xlsx/SKILL.md` | research | Generic Excel: openpyxl, **`scripts/recalc.py`**, blue/black/green/red, financial-model color conventions. Trigger: workbook-as-deliverable. |
| `skills/pptx-posters/SKILL.md` | research | Scientific one-slide posters. Not IB. |
| `neos/skills/builtin/docx/` | builtin + `skill.py` | Executable read/create/update. Different runtime. |
| `neos/coding/skills/` | coding | Plan/commit/verify. **Not Office.** |

FSI skills that name the generic Office skills (often with drifted paths):

- `dcf-model` / `lbo-model`: `python recalc.py` / `python /mnt/skills/public/xlsx/recalc.py` → **`skills/xlsx/scripts/recalc.py`**
- `earnings-analysis` / `initiating-coverage`: “DOCX skill” / “XLS skill” → `docx` / `xlsx` / `xlsx-author`
- `ppt-template-creator`: “use the pptx skill” → Neos `pptx`, not `pptx-author`
- `strip-profile`: “Reference the **PPTX skill**”; body mixes PptxGenJS (Neos `pptx`) and python-pptx
- S&P `tear-sheet`: `Read /mnt/skills/public/docx/SKILL.md` → Neos `skills/docx`

### 5.1 Split (do not merge)

| Concern | Owner | Not owner |
|---|---|---|
| OOXML zip hygiene, XSD validate, soffice render, pptxgenjs footguns, tracked-changes Word | Neos `skills/pptx`, `skills/docx`, `skills/xlsx` | FSI `pptx-author` / `xlsx-author` (they are ~40-line CMA contracts) |
| Formula recalc after openpyxl write | Neos `skills/xlsx/scripts/recalc.py` | Do not copy recalc into FSI |
| Headless CMA contract: write `./out/<name>.pptx` / `./out/<name>.xlsx`, return relative path, no email | FSI `pptx-author`, `xlsx-author` | Generic pptx/xlsx (no `./out/` contract, no “skip if `mcp__office__*`”) |
| Live Office MCP (`mcp__office__excel_*` / `mcp__office__powerpoint_*`) | FSI modeling/deck skills in Cowork mode | Generic skills never mention Office MCP |
| IB template fill, placeholder vs instruction-box, `reference/xml-reference.md`, LibreOffice-is-not-PowerPoint disclaimer | FSI `pitch-deck` | Generic `pptx` (create-from-scratch / XML edit) |
| Model QA: BS balance, cash tie-out, DCF/LBO/merger bugs, report-first | FSI `audit-xls` | Generic xlsx (formula errors + recalc JSON only) |
| Deck number QC across slides | FSI `ib-check-deck` + `extract_numbers.py` | Generic pptx markitdown dump |
| Teach a firm `.pptx`/`.potx` into a self-contained template skill | FSI `ppt-template-creator` | Neos `skills/skill-creator` **and** FSI `skill-creator` (the latter is not ported) |
| Scientific posters | Neos `pptx-posters` | FSI pitch/morning-note decks |
| S&P tear-sheet Word styling (docx-js helpers in SKILL.md) | S&P `tear-sheet` **calls** Neos `docx` | Do not fork docx into spglobal |

On port, `xlsx-author` **delegates** recalc and openpyxl gotchas to `skills/xlsx` and keeps the CMA path contract + Inputs / Checks tab / named ranges / one-model-per-file / blue-black-green. Neos `xlsx` already documents the same colors plus red for external-file links. Do not drop FSI green = cross-sheet link.

`pptx-author` **delegates** validate / soffice / pptxgenjs footguns to `skills/pptx` and keeps `./out/`, “no external send”, “footnote sheet+cell from `./out/model.xlsx`”, “skip if live Office MCP”.

**Chart policy conflict — preserve, do not paper over:** FSI `pptx-author` prefers PNG embeds from the model when fidelity matters. Neos `pptx` prefers native `addChart()` and forbids falling back to images except Sankey/network/chord. Headless FSI decks follow `pptx-author` (PNG). Ad-hoc user “make me a pptx” outside FSI agents follows Neos `pptx` (native charts). Do not invent OOXML `c:chart` / named-range→PPT chart binding; **it is not in any FSI skill body**. `pitch-deck/reference/xml-reference.md` has tables, arrows, text boxes, images, connectors, EMU — not charts.

Do not put FSI Office skills in `neos/coding/skills/`. Coding skip would drop them, and they would mix IB decks with `plan`/`commit`. They belong under `skills/financial-services/financial-analysis/{pptx-author,xlsx-author}/`.

### 5.2 Three-way mode

| Mode | Detect | Excel | PowerPoint |
|---|---|---|---|
| Cowork + Office MCP | `mcp__office__excel_*` / `powerpoint_*` present | Drive live workbook. **Do not** load `xlsx-author`. | Drive live deck. **Do not** load `pptx-author`. |
| CMA / Neos headless named agent | no open Office; `./out/` append | `xlsx-author` (openpyxl, Inputs/Checks, named ranges, blue/black/green) then **Neos `recalc.py`** | `pptx-author` (python-pptx, prefer PNG charts from the model) |
| Ad-hoc user “make me a pptx/xlsx/docx” outside FSI agents | research catalog trigger on `pptx`/`xlsx`/`docx` | Neos `xlsx` | Neos `pptx` / `docx` |

MS365 install plugin is not an FSI agent. Neos does not provision Office add-ins in this spec. Live Office MCP is used **if already attached**; otherwise headless `./out/`. LibreOffice `soffice` visual QC is optional; FSI already disclaims it is not an accurate PowerPoint renderer.

### 5.3 FSI Office harness skills (condensed)

All under `financial-analysis` except `pitch-deck` (IB).

| Skill | CMA / headless | Cowork live Office | Scripts |
|---|---|---|---|
| `pptx-author` | `./out/<name>.pptx`, python-pptx, firm template at `./templates/` | skip if `mcp__office__powerpoint_*` | none |
| `xlsx-author` | `./out/<name>.xlsx`, openpyxl, Inputs + Checks + named ranges | skip if `mcp__office__excel_*` | none (recalc is Neos xlsx) |
| `audit-xls` | model QA report, no silent edits | `/debug-model` | none |
| `clean-data-xls` | openpyxl helper columns | Office JS `range.formulas` | none; **no agent bundle** |
| `deck-refresh` | regenerate slides after approval gate | edit live runs/chart series | none |
| `ib-check-deck` | read-and-report | same | `extract_numbers.py --check` |
| `pitch-deck` | python-pptx + limited OOXML + soffice loop | template fill | none (`reference/` XML patterns, **no `c:chart`**) |
| `ppt-template-creator` | emits a skill, not a deck | `/ppt-template` | none |

Named ranges: only `xlsx-author` requires them (“for any value referenced from a deck or memo”). `audit-xls` does not check named ranges. `pptx-author` traces numbers by sheet+cell footnote, not Name Manager. Do not invent `DefinedName` APIs.

---

## 6. MCP hub, env, comma-bug fix

FSI README calls `plugins/vertical-plugins/financial-analysis/.mcp.json` the central connector list. **No auth fields, no headers, no env interpolation, no tool catalogs.** Every entry is `"type": "http"` plus a URL. CMA cookbooks inject `${…_MCP_URL}` on the **agent YAML**, not on this file.

Neos ships a **valid** hub at `skills/financial-services/mcp/hub.json`. That file is a **URL catalog** (key → default HTTP URL). It is not an attach list. Nothing in `hub.json` is connected just because it is listed. Attach is `agent mcp_allowlist` ∩ resolved URL ∩ (for partner keys) `fsi.partner_mcp` + entitlement.

### 6.1 Comma bug — fix on port

FSI `json.loads` fails: `JSONDecodeError: Expecting ',' delimiter: line 47 column 5 (char 1100)`.

Observed tail:

```json
    "egnyte": {
      "type": "http",
      "url": "https://mcp-server.egnyte.com/mcp"
    }
    "box": {
      "type": "http",
      "url": "https://mcp.box.com"
  }
}
```

Two defects:

1. **No comma** after the `egnyte` object, before `"box"`.
2. **`box` object never closes.** The next `}` is indented as `mcpServers` close; the last `}` closes the root. Adding only the comma still leaves `box` unclosed.

FSI `check.py` JSON glob is `marketplace.json`, `plugin.json`, `steering-examples.json` only. **`.mcp.json` is not linted.** The hub is invalid in the source tree today.

Neos `hub.json` **must** `json.loads`, include `box`, and close every object. Exact payload:

```json
{
  "mcpServers": {
    "daloopa": {
      "type": "http",
      "url": "https://mcp.daloopa.com/server/mcp"
    },
    "morningstar": {
      "type": "http",
      "url": "https://mcp.morningstar.com/mcp"
    },
    "sp-global": {
      "type": "http",
      "url": "https://kfinance.kensho.com/integrations/mcp"
    },
    "factset": {
      "type": "http",
      "url": "https://mcp.factset.com/mcp"
    },
    "moodys": {
      "type": "http",
      "url": "https://api.moodys.com/genai-ready-data/m1/mcp"
    },
    "mtnewswire": {
      "type": "http",
      "url": "https://vast-mcp.blueskyapi.com/mtnewswires"
    },
    "aiera": {
      "type": "http",
      "url": "https://mcp-pub.aiera.com"
    },
    "lseg": {
      "type": "http",
      "url": "https://api.analytics.lseg.com/lfa/mcp"
    },
    "pitchbook": {
      "type": "http",
      "url": "https://premium.mcp.pitchbook.com/mcp"
    },
    "chronograph": {
      "type": "http",
      "url": "https://ai.chronograph.pe/mcp"
    },
    "egnyte": {
      "type": "http",
      "url": "https://mcp-server.egnyte.com/mcp"
    },
    "box": {
      "type": "http",
      "url": "https://mcp.box.com"
    }
  }
}
```

README Vertical Plugins table says “All 11 data connectors”. README MCP table and this file have **12** keys (box included). Neos keeps all 12. Document-store servers `egnyte` and `box` are for KYC packets and GP packages; **reader only**.

Skills that name MCP vendors in body: `comps-analysis` (S&P Kensho / FactSet / Daloopa exclusive if present — do not web-search); `dcf-model` (Daloopa historicals, web as fallback #3). The other ten hub keys are not referenced by any skill body. Keep their URLs in the catalog. Do not attach them unless an agent `mcp_allowlist` names them (and, for `lseg` / partner S&P, §6.2.2).

### 6.2 Env vars and attach (hub is not auto-attach)

Hub file has **zero** env interpolation. Deploy resolves a URL per **allowlisted** key, then attaches that key only.

| Env var | CMA agents | Hub / stub key | Class |
|---|---|---|---|
| `FACTSET_MCP_URL` | earnings-reviewer, market-researcher | hub `factset` | Mode A **required** |
| `DALOOPA_MCP_URL` | earnings-reviewer, model-builder, pitch-agent | hub `daloopa` | Mode A **required** |
| `CAPIQ_MCP_URL` | market-researcher, meeting-prep-agent, model-builder, pitch-agent | hub `sp-global` (Kensho URL, agent key `capiq`) | Mode A **required** |
| `CRM_MCP_URL` | meeting-prep-agent | **not in hub** → stub `crm` | Mode B internal |
| `GL_MCP_URL` | gl-reconciler, month-end-closer | **not in hub** → stub `internal-gl` | Mode B internal |
| `SUBLEDGER_MCP_URL` | gl-reconciler | **not in hub** → stub `subledger` | Mode B internal |
| `SCREENING_MCP_URL` | kyc-screener | **not in hub** → stub `screening` | Mode B internal |
| `NAV_MCP_URL` | statement-auditor | **not in hub** → stub `nav` | Mode B internal |
| `PORTFOLIO_MCP_URL` | valuation-reviewer | **not in hub** → stub `portfolio` | Mode B internal |

URL resolve for an allowlisted key: `env` if set and non-empty, else the hub catalog URL. Then attach. If the env is empty **and** the hub has no URL for that key, or attach fails, the runtime installs a **read-only stub** and the agent **stops and surfaces** “connector missing”. It does not silently continue.

#### 6.2.1 Mode A required servers (CapIQ / Daloopa / FactSet)

These three are required when the agent’s `mcp_allowlist` names them (pitch/model-builder: `capiq`+`daloopa`; market-researcher: `capiq`+`factset`; earnings-reviewer: `factset`+`daloopa`; meeting-prep: `capiq` plus Mode B `crm`).

- Resolve URL = `CAPIQ_MCP_URL` / `DALOOPA_MCP_URL` / `FACTSET_MCP_URL` if set, else hub URL for `sp-global` / `daloopa` / `factset`.
- If that URL is missing or the server does not come up: **stub + stop-and-surface**. No web-search primary.
- `comps-analysis` must **not** web-search as primary, including after a stub. User-provided files are the only fallback the skill allows. (`dcf-model` may still use web as fallback #3 **after** MCP and user-provided files; comps may not.)
- CapIQ on a Mode A agent is the Kensho URL under agent key `capiq`. That is not partner-plugin attach. See §6.2.2 for hub key `lseg` and the S&P partner catalog.

#### 6.2.2 Partner keys are not attached from the hub

`hub.json` still records URLs for `lseg` and `sp-global` so the catalog is complete. A parent that “attaches every hub key” would pull LSEG without entitlement. Forbidden.

- Do **not** attach hub `lseg` or `lseg-lfa-cl` unless feature flag `fsi.partner_mcp` is on **and** the session has LSEG entitlement.
- Do **not** attach partner S&P (`fsi-spglobal` catalog / partner `.mcp.json`) unless `fsi.partner_mcp` **and** S&P entitlement.
- Mode A `capiq` (env `CAPIQ_MCP_URL` or hub `sp-global` URL) remains the Anthropic CapIQ path and does not require `fsi.partner_mcp`.
- Optional hub keys with no CMA cookbook (`morningstar`, `moodys`, `mtnewswire`, `aiera`, `pitchbook`, `chronograph`, `egnyte`, `box`) stay in the catalog. Attach only if a later profile allowlists them. `egnyte` / `box` are reader-only document stores. Do not invent cookbook bindings.

#### 6.2.3 Mode B internals

Mode B (GL / KYC / NAV / CRM / portfolio): **no URL in-repo**. `internal-stubs.json` declares the six keys with `"type": "http"` and `"url": null`. Runtime attaches a **read-only stub** that answers “connector missing → stop and surface” until the env var is a real URL. Do not invent a write API to a ledger or screening system. Untrusted readers never receive MCP (worker-graph spec).

### 6.3 Other FSI `.mcp.json` — what to port

| FSI path | Parse | Neos action |
|---|---|---|
| `vertical-plugins/financial-analysis/.mcp.json` | invalid | port as `mcp/hub.json` (fixed) |
| `vertical-plugins/investment-banking/.mcp.json` | OK, `"mcpServers": {}` | **do not port** |
| `vertical-plugins/private-equity/.mcp.json` | OK, `"mcpServers": {}` | **do not port** |
| `partner-built/lseg/.mcp.json` | OK | port as `mcp/lseg.json` with key `lseg-lfa-cl` (see §7) |
| `partner-built/spglobal/.mcp.json` | OK | port as `mcp/spglobal.json`; key aliases to hub `sp-global` |
| equity-research, fund-admin, operations, all 10 agent-plugins | no file | nothing to copy |

### 6.4 Partner tool catalogs

LSEG `CONNECTORS.md` (not in JSON) lists: `bond_price`, `bond_future_price`, `fx_spot_price`, `fx_forward_price`, `interest_rate_curve`, `inflation_curve`, `credit_curve`, `fx_forward_curve`, `option_value`, `option_template_list`, `ir_swap`, `fx_vol_surface`, `equity_vol_surface`, `qa_ibes_consensus`, `qa_company_fundamentals`, `qa_historical_equity_price`, `qa_macroeconomic`, `tscc_historical_pricing_summaries`, `yieldbook_bond_reference`, `yieldbook_cashflow`, `yieldbook_scenario`, `fixed_income_risk_analytics`.

Copy `CONNECTORS.md` next to `skills/financial-services/lseg/` (or `mcp/lseg-connectors.md`). S&P has no `CONNECTORS.md`; skills name `kfinance` / Kensho `search` in prose.

### 6.5 `internal-stubs.json`

```json
{
  "mcpServers": {
    "internal-gl": { "type": "http", "url": null, "env": "GL_MCP_URL", "mode": "read-only-stub" },
    "subledger": { "type": "http", "url": null, "env": "SUBLEDGER_MCP_URL", "mode": "read-only-stub" },
    "screening": { "type": "http", "url": null, "env": "SCREENING_MCP_URL", "mode": "read-only-stub" },
    "portfolio": { "type": "http", "url": null, "env": "PORTFOLIO_MCP_URL", "mode": "read-only-stub" },
    "nav": { "type": "http", "url": null, "env": "NAV_MCP_URL", "mode": "read-only-stub" },
    "crm": { "type": "http", "url": null, "env": "CRM_MCP_URL", "mode": "read-only-stub" }
  }
}
```

When the env var is set to a real URL, replace the stub. Until then, any skill or agent that requires that server stops and surfaces the gap. Do not silently fall back to Anthropic ER/IB skills under a partner or internal name.

---

## 7. Partner name collisions

### 7.1 MCP server keys and URLs

| Identity | Core hub | Partner plugin | Collision | Neos |
|---|---|---|---|---|
| LSEG | key `lseg`, url `https://api.analytics.lseg.com/lfa/mcp` | key `lseg`, url `https://api.analytics.lseg.com/lfa/mcp/server-cl` | **Same key, different URL** (`/server-cl` suffix). README MCP table uses the core URL. | Two named variants: hub `lseg` (core) and `lseg-lfa-cl` (partner). Never merge into one map entry. |
| S&P / Kensho | key `sp-global`, url `https://kfinance.kensho.com/integrations/mcp` | key `spglobal` (no hyphen), **same URL** | Same URL, different spelling. plugin.json name `sp-global`, dir `spglobal`. | One key `sp-global`. Alias `spglobal` → `sp-global`. Mode A `capiq` uses this URL without `fsi.partner_mcp`. Partner S&P catalog attach still needs the flag + entitlement. |

If Neos keyed a single MCP map by server name and concatenated hub + partner JSON, LSEG would overwrite or duplicate and S&P would register twice. CI fails if both LSEG URLs are stored under the same key, or if `spglobal` is registered as a second server with the same URL.

### 7.2 Skill / plugin / reference names

| String | Anthropic | LSEG | S&P | Risk if one flat catalog |
|---|---|---|---|---|
| `equity-research` | **vertical plugin** + 9 skills under it (none named `equity-research`) | **skill** `name: equity-research` (`/research-equity`) | `tear-sheet/references/equity-research.md` (audience file) | LSEG skill name equals Anthropic **plugin/vertical** name. `_put` would drop one if they shared an index. |
| `earnings-preview` | skill `earnings-preview` (ER, bundled) | — | dir `earnings-preview-beta`, frontmatter `earnings-preview-single` | Near-duplicate preview. Different data rules (S&P forbids web; Anthropic allows web consensus). |
| `tear-sheet` vs `strip-profile` / `fsi-strip-profile` | IB one-pager PPT | — | Word tear sheet via CapIQ | Product overlap, different names, different Office format. Route by audience + entitlement, not by merging. |
| `funding-digest` | — | — | unique | none |

### 7.3 Port rules

1. Namespace partner skills on disk: `skills/financial-services/lseg/…`, `skills/financial-services/spglobal/…`.
2. Load them from **separate** `MarkdownSkillCatalog` instances (`fsi-lseg`, `fsi-spglobal`). Do not rename LSEG frontmatter `equity-research`.
3. Do **not** sync partner skills into named-agent allowlists. CMA cookbooks never `from_plugin` partner dirs.
4. Gate partner skills and hub `lseg` / `lseg-lfa-cl` behind `fsi.partner_mcp` **and** entitlement (§6.2.2). If those are absent, stub and stop. Do not silently run the Anthropic ER stack under the LSEG skill name. Hub JSON is not auto-attach.
5. S&P `earnings-preview-single` vs Anthropic `earnings-preview`: keep both; agent allowlists pick Anthropic; S&P sessions pick S&P. Never install both into the same un-namespaced index.
6. Slash `/research-equity` resolves in the LSEG catalog only.

---

## 8. Slash command aliases

FSI agent plugins have **no** `commands/`. Cowork slash is vertical + LSEG only. CMA does not deploy commands; entry is `steering-examples.json` events.

Neos does not add a command runtime. A command is an alias that loads one (sometimes two) skills. Filename minus `.md` is the slash name.

Storage:

- **Thin** (`Load the \`skill\`` one-liners, all PE, most IB/ER): `skills/financial-services/aliases.yaml` only. Do not copy the one-line markdown.
- **Thick** (workflow duplicated in the command body: `/comps`, `/dcf`, `/earnings`, `/debug-model`, `/one-pager`, `/ppt-template`, all 8 LSEG): copy `commands/<slash>.md` under the vertical so the extra instructions survive.

Runtime: resolve alias → `load_markdown(skill_name)` (and a second load for `/dcf`). If the command markdown exists, load it after the skill body.

### 8.1 `aliases.yaml` (complete)

```yaml
# financial-analysis
3-statement-model: { catalog: fsi, skills: [3-statement-model] }
competitive-analysis: { catalog: fsi, skills: [competitive-analysis] }
comps: { catalog: fsi, skills: [comps-analysis], extra: commands/comps.md }
dcf: { catalog: fsi, skills: [comps-analysis, dcf-model], extra: commands/dcf.md }
debug-model: { catalog: fsi, skills: [audit-xls], extra: commands/debug-model.md, scope: model }
lbo: { catalog: fsi, skills: [lbo-model] }
ppt-template: { catalog: fsi, skills: [ppt-template-creator], extra: commands/ppt-template.md }

# equity-research
earnings: { catalog: fsi, skills: [earnings-analysis], extra: commands/earnings.md }
earnings-preview: { catalog: fsi, skills: [earnings-preview] }
initiate: { catalog: fsi, skills: [initiating-coverage] }
model-update: { catalog: fsi, skills: [model-update] }
morning-note: { catalog: fsi, skills: [morning-note] }
sector: { catalog: fsi, skills: [sector-overview] }
thesis: { catalog: fsi, skills: [thesis-tracker] }
catalysts: { catalog: fsi, skills: [catalyst-calendar] }
screen: { catalog: fsi, skills: [idea-generation] }

# investment-banking
one-pager: { catalog: fsi, skills: [fsi-strip-profile], extra: commands/one-pager.md, also_try: strip-profile }
cim: { catalog: fsi, skills: [cim-builder] }
teaser: { catalog: fsi, skills: [teaser] }
buyer-list: { catalog: fsi, skills: [buyer-list] }
merger-model: { catalog: fsi, skills: [merger-model] }
process-letter: { catalog: fsi, skills: [process-letter] }
deal-tracker: { catalog: fsi, skills: [deal-tracker] }

# private-equity
ai-readiness: { catalog: fsi, skills: [ai-readiness] }
dd-checklist: { catalog: fsi, skills: [dd-checklist] }
dd-prep: { catalog: fsi, skills: [dd-meeting-prep] }
ic-memo: { catalog: fsi, skills: [ic-memo] }
portfolio: { catalog: fsi, skills: [portfolio-monitoring] }
returns: { catalog: fsi, skills: [returns-analysis] }
screen-deal: { catalog: fsi, skills: [deal-screening] }
source: { catalog: fsi, skills: [deal-sourcing] }
unit-economics: { catalog: fsi, skills: [unit-economics] }
value-creation: { catalog: fsi, skills: [value-creation-plan] }

# wealth-management (restored)
client-report: { catalog: fsi, skills: [client-report] }
client-review: { catalog: fsi, skills: [client-review] }
proposal: { catalog: fsi, skills: [investment-proposal] }

# LSEG (catalog fsi-lseg; MCP playbooks, not thin loaders)
analyze-bond-basis: { catalog: fsi-lseg, skills: [bond-futures-basis], extra: commands/analyze-bond-basis.md }
analyze-bond-rv: { catalog: fsi-lseg, skills: [bond-relative-value], extra: commands/analyze-bond-rv.md }
analyze-fx-carry: { catalog: fsi-lseg, skills: [fx-carry-trade], extra: commands/analyze-fx-carry.md }
analyze-option-vol: { catalog: fsi-lseg, skills: [option-vol-analysis], extra: commands/analyze-option-vol.md }
analyze-swap-curve: { catalog: fsi-lseg, skills: [swap-curve-strategy], extra: commands/analyze-swap-curve.md }
macro-rates: { catalog: fsi-lseg, skills: [macro-rates-monitor], extra: commands/macro-rates.md }
research-equity: { catalog: fsi-lseg, skills: [equity-research], extra: commands/research-equity.md }
review-fi-portfolio: { catalog: fsi-lseg, skills: [fixed-income-portfolio], extra: commands/review-fi-portfolio.md }
```

Special cases to keep:

- `/dcf` chains `comps-analysis` then `dcf-model` (only multi-skill command).
- `/debug-model` forces `audit-xls` scope=`model`.
- `/one-pager` may first load a generated `[company]-ppt-template` skill, then `fsi-strip-profile`. Command body says `"strip-profile"`; catalog name is `fsi-strip-profile`.
- `/ppt-template` is the only FSI command with `allowed-tools: ["Read","Write","Bash","Glob"]` in source. Neos still has no command runtime; the generated template skill is written by the agent under tool policy, not by a slash interpreter.
- LSEG commands stay MCP playbooks (tool sequences), not thin loaders.
- S&P: no commands. Skills fire from description.

### 8.2 Skills with no slash (description or agent Invoke only)

financial-analysis: `clean-data-xls`, `deck-refresh`, `ib-check-deck`, `pptx-author`, `xlsx-author` (`skill-creator` not ported)  
investment-banking: `pitch-deck`, `datapack-builder`  
fund-admin: all 6  
operations: both  
meeting-prep: the three (aliases restored in §4.4; they were missing from the current FSI tree)  
S&P: all 3

---

## 9. CI drift check (no copytree; path resolve)

FSI `scripts/sync-agent-skills.py` (44 lines) indexes vertical skills by **directory name**, then `rmtree` + `copytree` into each agent plugin. Missing source → stderr WARN + **exit 1** (today: the meeting-prep trio). `check.py` §4b byte-compares with `filecmp.dircmp`. §4b2 requires that hyphen-case backtick tokens in `agents/<slug>.md` that exist as vertical names also exist in that agent’s bundle. It does **not** fail if the bundle has extras the prompt forgot.

Neos **does not vendor 51 copies**. Canonical tree is `skills/financial-services/<vertical>/<skill>/`. Agent profiles hold an allowlist of names. That removes the copy-drift class §4b exists to catch, and makes meeting-prep orphans a restore ticket instead of a permanent WARN.

Do not port `sync-agent-skills.py`. Do not `shutil.copytree` skill dirs into agent profiles. If a future change vendors per-agent copies, then and only then byte-compare like 4b.

### 9.1 Resolve rule

For each name on an allowlist or in `aliases.yaml`:

1. Pick the catalog (`fsi` / `fsi-lseg` / `fsi-spglobal`).
2. `skill = catalog.get(name)` (frontmatter `name`). For `/one-pager`, also try directory alias `strip-profile` → `fsi-strip-profile`.
3. `path = skill.path.resolve()`.
4. Fail unless `path.is_file()` and `path.is_relative_to((REPO_ROOT / "skills" / "financial-services").resolve())` and `path.name.upper() == "SKILL.MD"`.
5. Fail if `path` walks through a symlink that escapes the pack (rely on `Path.resolve()` + `is_relative_to`).

No content copy. No hash of agent-local clones.

### 9.2 Gates

| Gate | FSI analog | Neos check | severity |
|---|---|---|---|
| Every agent-profile skill name resolves to an on-disk `SKILL.md` under `skills/financial-services/` | 4b2 + 4b missing-source | Fail. Meeting-prep 3 fail until WM vertical restored. **No orphan allowlist.** | fail |
| Allowlist ⊆ `fsi_catalog()` | — | Fail if name missing from Anthropic FSI catalog | fail |
| Prompt “Skills this agent uses” == allowlist | 4b2 reverse (unchecked in FSI) | Fail if `xlsx-author` / `pptx-author` omitted from ER/MB/PA prompts | fail |
| Write-leaf allowlist ⊆ orchestrator allowlist | CMA `from_plugin` vs leaf `paths` | Fail if leaf names a skill the parent does not | fail |
| Frontmatter `name` unique within one catalog | sync later-glob-wins | Fail on duplicate `name` inside `fsi` / `fsi-lseg` / `fsi-spglobal` | fail |
| Frontmatter `name` vs directory | unchecked | Warn: `strip-profile`/`fsi-strip-profile`, `earnings-preview-beta`/`earnings-preview-single` | warn |
| Partner skills never appear on Anthropic agent allowlists | sync ignores partner | Fail if they do | fail |
| Partner catalogs do not share the Anthropic name index | — | Test: `fsi_catalog().get("equity-research")` is None; LSEG catalog returns the LSEG skill | fail |
| `hub.json` / `lseg.json` / `spglobal.json` / `internal-stubs.json` `json.loads` | **absent today** | Fail. This is how the egnyte/box bug ships. | fail |
| Hub keys == documented 12; LSEG URL variant recorded as `lseg-lfa-cl` | — | Fail on silent key/URL drift vs partner file | fail |
| `spglobal` is an alias, not a second server | — | Fail if both keys exist with the same URL | fail |
| Scripts that SKILL.md invokes exist | — | Fail if `validate_dcf.py` / `extract_numbers.py` missing. **Do not** fail for `recalc.py` inside the FSI tree; require a pointer to `skills/xlsx/scripts/recalc.py` | fail |
| Cited example xlsx/pptx | — | Warn (files are missing in source; do not fabricate) | warn |
| FSI skills are research-indexed, not coding-skipped | catalog | Load pack with warn-only; assert 51 Anthropic skills (48 vertical + 3 WM) even without When to Use | fail |
| `reference/` and `references/` both load | catalog loader | Fail if `earnings-analysis` cannot load `workflow.md` via `reference=` | fail |
| `skill-creator` is absent from the FSI pack | §10 | Fail if the dir is copied into `skills/financial-services/` | fail |
| Coding catalog still excludes FSI names | catalog | `default_catalog().get("xlsx-author")` is None | fail |
| FSI `load_skill.v1` uses `fsi_catalog()` ∩ allowlist | executor | Coding session → `unknown_skill` for `xlsx-author`; FSI parent with name on allowlist → `ok`; empty allowlist → `unknown_skill` | fail |
| `validate_dcf.py` does not require a `Sensitivity` sheet | D13 | Checker accepts three grids on `DCF`; SKILL.md is not rewritten to add a tab | fail |
| Hub JSON is not auto-attach | D8 / D9 | Attach tests: Mode A required keys resolve env-or-hub else stub+stop; `lseg` / partner S&P stay detached without `fsi.partner_mcp` + entitlement; comps does not web-search as primary | fail |

CMA `from_plugin` expands to every skill dir in the agent plugin. Neos analog: the allowlist **is** the bundle. Do not upload a whole vertical when spawning an agent.

---

## 10. Do not port

| Item | Path / mention | Why |
|---|---|---|
| **`skill-creator`** | `plugins/vertical-plugins/financial-analysis/skills/skill-creator/` | Claude `.skill` zip toolchain (`init_skill.py`, `package_skill.py`, `quick_validate.py`). Neos already has `skills/skill-creator/`. Different catalog, different frontmatter rules. Not bundled on any agent. |
| **Missing example workbooks** | `comps-analysis` → `examples/comps_example.xlsx`; `lbo-model` → `examples/LBO_Model.xlsx`; `strip-profile` → `examples/Nike_Strip_Profile_Example.pptx` | Directories do not exist in the plugin. Do not fabricate samples. Skills already ask the user for a template if absent. |
| **`recalc.py` inside FSI** | `dcf-model` `python recalc.py model.xlsx 30`; `lbo-model` `python /mnt/skills/public/xlsx/recalc.py` | Not in the FSI tree. Canonical is `skills/xlsx/scripts/recalc.py`. Point FSI modeling skills at that path. Do not reimplement. |
| Empty `hooks/hooks.json` | four verticals | No-op. Safety is prompt + tool policy + schema, not hooks. Original `hooks.json` objects are all empty. |
| Empty IB/PE `.mcp.json` | `"mcpServers": {}` | Noise. Not a connector list. |
| `claude-for-msft-365-install` `verify` skill | `.claude/skills/verify/` | Add-in provisioning, not FSI workflow. Out of pack unless a later MS365 spec. |
| Deleted `claude-for-financial-advisors` | README still links `./claude-for-financial-advisors` | Skills were `pre-meeting` / `post-meeting` / etc., **not** the meeting-prep trio. Do not port from git. |
| Deleted WM extras | `financial-plan`, `portfolio-rebalance`, `tax-loss-harvesting` | Not on meeting-prep-agent. Restore only with a full WM vertical. |
| Partner skills as Anthropic substitutes | LSEG 8, S&P 3 without entitlement | Stub. Do not pretend Anthropic ER/IB skills substitute. Do not redistribute LSEG/S&P data. |
| Native `c:chart` OOXML / named-range→PPT chart binding | — | **Not in any FSI skill body.** `pptx-author` prefers PNG. Do not invent. |
| Agent-plugin `skills/` copies | 51 vendored dirs | Neos has one tree. Path-resolve CI replaces copytree. |
| `sync-agent-skills.py` | FSI `scripts/sync-agent-skills.py` | copytree by directory name. Not ported. |
| FSI skills as `BaseSkill` / coding-catalog entries | `neos/skills/builtin`, `neos/coding/skills` | Wrong runtime and wrong skip rules. |
| Flattened pack | `skills/financial-services/<skill>/SKILL.md` | Collides partner `equity-research` with the Anthropic vertical. |
| ER ratings as publishable research | `initiating-coverage` BUY/HOLD/SELL | Root README forbids investment advice. Ratings stay draft + compliance gate. |
| Ledger / core-banking write APIs | Mode B MCP | Read-only stub. “Do not post.” |
| KYC auto-approval | `kyc-rules` | Skill says never approve. |

`ppt-template-creator` **is** ported (meta, unbundled, needed for `/ppt-template` and `/one-pager`). It calls Neos `skills/skill-creator` / `skills/pptx`, not FSI `skill-creator`.

---

## 11. Files to create / modify + tests

### 11.1 Create

| Path | Why |
|---|---|
| `skills/financial-services/financial-analysis/<skill>/` × 12 | Port 12 of 13 FA skills (`skill-creator` excluded), including `scripts/` and `references/` |
| `skills/financial-services/equity-research/<skill>/` × 9 | All ER skills |
| `skills/financial-services/investment-banking/<skill>/` × 9 | All IB skills, including singular `pitch-deck/reference/` |
| `skills/financial-services/private-equity/<skill>/` × 10 | All PE skills |
| `skills/financial-services/fund-admin/<skill>/` × 6 | All fund-admin skills |
| `skills/financial-services/operations/<skill>/` × 2 | KYC pair |
| `skills/financial-services/wealth-management/{client-report,client-review,investment-proposal}/` | Restore plan §4 |
| `skills/financial-services/lseg/<skill>/` × 8 | Partner, separate catalog |
| `skills/financial-services/lseg/CONNECTORS.md` | LSEG tool catalog |
| `skills/financial-services/spglobal/<skill>/` × 3 | Partner, separate catalog |
| `skills/financial-services/<vertical>/commands/*.md` | Thick slash wrappers only (FA `/comps` `/dcf` `/debug-model` `/ppt-template`; ER `/earnings`; IB `/one-pager`; LSEG 8) |
| `skills/financial-services/aliases.yaml` | Complete slash map §8.1 |
| `skills/financial-services/allowlists/<slug>.yaml` × 10 | CI source matching §3.10 |
| `skills/financial-services/mcp/hub.json` | Valid 12-server hub |
| `skills/financial-services/mcp/internal-stubs.json` | Six Mode B stubs |
| `skills/financial-services/mcp/lseg.json` | `{ "mcpServers": { "lseg-lfa-cl": { "type": "http", "url": "https://api.analytics.lseg.com/lfa/mcp/server-cl" } } }` |
| `skills/financial-services/mcp/spglobal.json` | `{ "mcpServers": { "sp-global": { "type": "http", "url": "https://kfinance.kensho.com/integrations/mcp", "aliases": ["spglobal"] } } }` |
| `tests/skills/test_fsi_catalog.py` | Nested roots, 51-name presence, partner isolation, warn-only headings |
| `tests/skills/test_fsi_mcp_hub.py` | JSON parse, 12 keys, comma/box closed, LSEG variant, S&P alias |
| `tests/skills/test_fsi_allowlists.py` | Path resolve, no copytree, WM restore gate, partner exclusion |
| `tests/skills/test_fsi_aliases.py` | `/dcf` two-skill chain, `/one-pager` → `fsi-strip-profile`, LSEG catalog, restored WM aliases |
| `tests/coding/test_fsi_load_skill.py` | §2.5 executor branch: coding vs FSI parent vs empty-allowlist reader |

`docs/financial-services/spec/02-skills-mcp.md` is this file.

### 11.2 Modify

| Path | Change |
|---|---|
| `neos/skills/markdown_catalog.py` | Add `FSI_PACK`, `FSI_ANTHROPIC_VERTICALS`, `FSI_PARTNER_VERTICALS`, `fsi_skill_roots()`, `fsi_partner_skill_roots()`, `fsi_catalog()` / partner constructors. Teach `_load_reference` to accept `references/` as an alias of `reference/`. Do **not** recurse `_index_skill_directories`. Do **not** add FSI to `default_skill_roots()`. Do **not** add a new `SkillSource`. |
| `neos/coding/tools/executor.py` | PR2/PR3: `_load_skill` branches as §2.5. FSI actor → named FSI catalog ∩ `skill_allowlist`. Non-FSI → `default_catalog()` unchanged. No new `load_skill.v1` argument. |
| `tests/skills/test_markdown_catalog.py` | Keep coding-only default roots. Add a tmp-path test that a two-level pack is invisible with root=`skills/` and visible with per-vertical roots. Add `references/` load + jail tests (`../secret.md` still None). |
| `skills/financial-services/financial-analysis/dcf-model/SKILL.md` | After copy: point recalc at `skills/xlsx/scripts/recalc.py`. **Do not** add a `Sensitivity` sheet. Three grids stay on `DCF`. |
| `skills/financial-services/financial-analysis/dcf-model/scripts/validate_dcf.py` | After copy: drop the `Sensitivity` sheet requirement; validate the three sensitivity grids on the `DCF` sheet. |
| `skills/financial-services/financial-analysis/dcf-model/requirements.txt` | Drop unused `requests`. |
| `skills/financial-services/financial-analysis/lbo-model/SKILL.md` | After copy: replace `/mnt/skills/public/xlsx/recalc.py` with `skills/xlsx/scripts/recalc.py`. |
| `skills/financial-services/financial-analysis/{pptx-author,xlsx-author}/SKILL.md` | After copy: add an explicit delegate sentence to Neos `skills/pptx` / `skills/xlsx` for validate/recalc/gotchas; keep `./out/` contract and live-MCP skip. |
| Agent profiles (named-agent spec) | Skills section == allowlist YAML. Include previously unlisted `xlsx-author` / `pptx-author` on ER/MB/PA. |
| `docs/financial-services/09-neos-migration-map.md` §1 / §3.2 | Optional later edit: coding-skills Office overlap is a path error; real overlap is `skills/{pptx,docx,xlsx}`. This spec already corrects it. |

Do not modify `neos/coding/skills/`. Do not modify generic `skills/pptx|docx|xlsx` except that FSI SKILL.md files **point at** them.

### 11.3 Tests (behavior)

`tests/skills/test_markdown_catalog.py` (existing file, extend):

- `test_default_skill_roots_are_coding_only` still passes; `xlsx-author` not in coding catalog.
- New: nested pack under `tmp/skills/financial-services/financial-analysis/dcf-model/SKILL.md` is **not** found when roots=`(tmp/skills,)`, **is** found when roots=`(tmp/skills/financial-services/financial-analysis,)`.
- New: `load_markdown("demo", reference="workflow.md")` reads `references/workflow.md` and still rejects `../secret.md`.

`tests/skills/test_fsi_catalog.py`:

- `fsi_catalog().list_skills()` contains exactly the 51 Anthropic names (48 vertical + 3 WM). Does not contain `skill-creator`. Does not contain LSEG `equity-research`.
- `fsi_lseg_catalog().get("equity-research")` is the LSEG skill; path is under `…/lseg/equity-research/SKILL.md`.
- `fsi_spglobal_catalog().get("earnings-preview-single")` resolves; `fsi_catalog().get("earnings-preview")` is Anthropic ER.
- Missing `## When to Use` does not drop `xlsx-author`.
- Duplicate frontmatter `name` in one catalog: second is skipped (existing `_put`) and CI helper reports fail.

`tests/skills/test_fsi_mcp_hub.py`:

- `json.loads` on all four MCP files.
- Hub keys == the 12 in §6.1, each with `type=http` and a non-empty URL.
- `box` object has its own closing brace; file is not the broken FSI tail.
- `lseg.json` URL ends with `/server-cl`; hub `lseg` URL does not.
- `spglobal.json` canonical key is `sp-global`; if `aliases` present it includes `spglobal`.
- Internal stubs: six keys, `url` is JSON `null`, `mode` is `read-only-stub`.
- Hub is a catalog: a helper that “attaches all hub keys” is forbidden. Tests attach only allowlisted Mode A required keys (CapIQ/Daloopa/FactSet) via env-or-hub URL; missing URL → stub + stop-and-surface.
- Without `fsi.partner_mcp` + entitlement, hub `lseg` and partner S&P are not attached even though their URLs sit in the catalog.
- `comps-analysis` fixture: when CapIQ/Daloopa/FactSet are stubbed, the agent does not call `web_search.v1` as primary.

`tests/skills/test_fsi_allowlists.py`:

- For each of 10 slugs, every name in `allowlists/<slug>.yaml` resolves via `fsi_catalog().get` to a `SKILL.md` under the pack.
- Resolved paths are `Path.resolve()`’d and `is_relative_to(FSI_PACK)`.
- `client-report` / `client-review` / `investment-proposal` resolve under `wealth-management/`, not under an agent path.
- No allowlist contains a name that only exists in `fsi-lseg` or `fsi-spglobal`.
- `validate_dcf.py` and `extract_numbers.py` exist next to their SKILL.md.
- `validate_dcf.py` does **not** require a workbook sheet named `Sensitivity`; it looks for the three grids on `DCF`. `dcf-model/SKILL.md` still has no `Sensitivity` tab.
- `recalc.py` is **absent** from the FSI pack; `dcf-model` and `lbo-model` SKILL.md mention `skills/xlsx/scripts/recalc.py`.
- `skill-creator` directory is absent from the pack.
- Helper used by CI is importable as a pytest test, not a copytree script.

`tests/skills/test_fsi_aliases.py`:

- `aliases.yaml` parses; every `skills:` name resolves in the declared catalog.
- `/dcf` lists `comps-analysis` then `dcf-model`.
- `/one-pager` resolves to `fsi-strip-profile`.
- `/proposal` → `investment-proposal`.
- `/research-equity` uses catalog `fsi-lseg`.
- No S&P slash keys.

`tests/coding/test_fsi_load_skill.py` (PR2 or PR3, patches `executor.py` `_load_skill`):

- Coding `SandboxToolExecutor._load_skill` with `name=xlsx-author` and no FSI profile → `unknown_skill`. `default_catalog().get("xlsx-author")` is `None`.
- FSI parent session, `skill_allowlist` includes `xlsx-author` → `ok`; markdown contains the CMA `./out/` contract.
- FSI reader session, `skill_allowlist=[]` → `unknown_skill` for `xlsx-author` and for `kyc-doc-parse`.
- FSI parent `catalog_id: fsi` loading `equity-research` → `unknown_skill`.

### 11.4 Implementation order (this slice only)

1. Catalog API (`fsi_skill_roots`, `references/` alias) + unit tests on tmp_path (no pack files required).
2. Copy 48 vertical skill dirs; rewrite recalc paths; **fix `validate_dcf.py`** (no `Sensitivity` sheet); exclude `skill-creator`.
3. Restore wealth-management trio.
4. Write `hub.json` (valid URL catalog, not auto-attach), stubs, partner MCP JSON, `aliases.yaml`, 10 allowlists.
5. Copy thick command markdown.
6. Copy partner skill dirs into `lseg/` and `spglobal/`.
7. Patch `executor.py` `_load_skill` (§2.5) so FSI actors hit `fsi_catalog()` ∩ allowlist.
8. Inventory + allowlist + MCP + `load_skill.v1` CI tests.
9. Stop. Named-agent prompts and worker graphs consume the allowlists; they are not this spec.

Until step 3 lands, meeting-prep-agent CI is red. That is intended.

---

## Path index

| Role | Path |
|---|---|
| FSI vertical root | `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/` |
| FSI agent copies | `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/` |
| FSI partners | `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/{lseg,spglobal}/` |
| FSI sync (not ported) | `/Users/yeonwoosung/Desktop/financial-services/scripts/sync-agent-skills.py` |
| FSI lint | `/Users/yeonwoosung/Desktop/financial-services/scripts/check.py` |
| FSI hub (invalid JSON) | `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/.mcp.json` |
| Neos catalog | `neos/skills/markdown_catalog.py` |
| Neos Office generics | `skills/{pptx,docx,xlsx}/SKILL.md` |
| Neos recalc | `skills/xlsx/scripts/recalc.py` |
| Neos FSI pack (this spec) | `skills/financial-services/` |
| This spec | `docs/financial-services/spec/02-skills-mcp.md` |
