# Financial Services Harness / Deployment / Validation / Marketplace / CI / CMA API

**Scope:** `/Users/yeonwoosung/Desktop/financial-services` — harness scripts, marketplace, plugin discovery, managed-agent cookbooks, CI, githooks.  
**License:** Apache License 2.0 (`LICENSE`, January 2004).  
**Rule used:** do not invent. If a field, endpoint, or file is not in this repo, it is marked **ABSENT**.

---

## 1. Dual-surface architecture (Cowork plugin vs Claude Managed Agents API `/v1/agents`)

### 1.1 한 소스, 두 래퍼

Repo root `README.md` and `CLAUDE.md` state the same contract: **each named agent ships two ways from one source**.

| Surface | 무엇 | 어디에 사나 | 어떻게 설치/배포 |
|---|---|---|---|
| **Cowork / Claude Code plugin** | self-contained plugin: `agents/<slug>.md` + bundled `skills/` | `plugins/agent-plugins/<slug>/` | marketplace install, or zip-upload of that directory |
| **Claude Managed Agents (CMA)** | `agent.yaml` + depth-1 `subagents/*.yaml` + `steering-examples.json` | `managed-agent-cookbooks/<slug>/` | `scripts/deploy-managed-agent.sh <slug>` → `POST /v1/agents` |

Canonical system prompt is **one file**:

```
plugins/agent-plugins/<slug>/agents/<slug>.md
```

CMA wrapper inlines it via:

```yaml
system:
  file: ../../plugins/agent-plugins/<slug>/agents/<slug>.md
  append: "You are running headless. Produce files in ./out/; do not assume an open Office document."
```

`append` is identical on all 10 orchestrator manifests. It is the only CMA-specific system-prompt delta in-repo.

### 1.2 레이어 역할 (README "How It Fits Together")

| Layer | What it is | Where |
|---|---|---|
| **Agents** | Self-contained workflow plugins. Cowork and CMA both point at the same directory. | `plugins/agent-plugins/<slug>/` |
| **Skills** | Domain methods. Authored once in verticals; each agent vendors a copy. | source: `plugins/vertical-plugins/<vertical>/skills/` · bundled: `plugins/agent-plugins/<slug>/skills/` |
| **Commands** | Slash actions (`/comps`, `/earnings`, `/ic-memo`). **Cowork / Claude Code only.** | `plugins/vertical-plugins/<vertical>/commands/` |
| **Connectors** | MCP servers. Cowork uses `.mcp.json`. CMA uses `mcp_servers:` in `agent.yaml`. | Cowork: `plugins/vertical-plugins/financial-analysis/.mcp.json` (canonical list) · CMA: per-cookbook YAML |
| **Managed-agent wrappers** | `agent.yaml` + depth-1 subagents + steering examples. | `managed-agent-cookbooks/<slug>/` |

**ABSENT on CMA surface:** `commands/`. Slash commands are never referenced by `deploy-managed-agent.sh` or any `agent.yaml`.

**ABSENT on Cowork agent plugins:** `subagents/`, `callable_agents`, `output_schema`, `steering-examples.json`. Subagent decomposition is CMA-only.

### 1.3 10 named agents (both surfaces)

From root `README.md` + `managed-agent-cookbooks/README.md`:

| Function | slug | Cowork plugin | CMA cookbook | Vertical (cookbook table) |
|---|---|---|---|---|
| Coverage & advisory | `pitch-agent` | `plugins/agent-plugins/pitch-agent` | `managed-agent-cookbooks/pitch-agent` | investment-banking |
| Coverage & advisory | `meeting-prep-agent` | `plugins/agent-plugins/meeting-prep-agent` | `managed-agent-cookbooks/meeting-prep-agent` | **wealth-management** (named in cookbook README; **that vertical plugin is ABSENT**) |
| Research & modeling | `market-researcher` | `plugins/agent-plugins/market-researcher` | `managed-agent-cookbooks/market-researcher` | equity-research |
| Research & modeling | `earnings-reviewer` | `plugins/agent-plugins/earnings-reviewer` | `managed-agent-cookbooks/earnings-reviewer` | equity-research |
| Research & modeling | `model-builder` | `plugins/agent-plugins/model-builder` | `managed-agent-cookbooks/model-builder` | financial-analysis |
| Fund admin | `valuation-reviewer` | `plugins/agent-plugins/valuation-reviewer` | `managed-agent-cookbooks/valuation-reviewer` | private-equity |
| Fund admin | `gl-reconciler` | `plugins/agent-plugins/gl-reconciler` | `managed-agent-cookbooks/gl-reconciler` | financial-analysis |
| Fund admin | `month-end-closer` | `plugins/agent-plugins/month-end-closer` | `managed-agent-cookbooks/month-end-closer` | financial-analysis |
| Fund admin | `statement-auditor` | `plugins/agent-plugins/statement-auditor` | `managed-agent-cookbooks/statement-auditor` | private-equity |
| Operations | `kyc-screener` | `plugins/agent-plugins/kyc-screener` | `managed-agent-cookbooks/kyc-screener` | financial-analysis (cookbook table) / operations (actual KYC skills live under `plugins/vertical-plugins/operations`) |

Partner plugins (`lseg`, `sp-global`) and `claude-for-msft-365-install` are **marketplace-only**. They have **no** `managed-agent-cookbooks/` counterpart.

Root `README.md` also links `[claude-for-financial-advisors](./claude-for-financial-advisors)`. That path is **ABSENT** from this checkout.

### 1.4 Same prompt, different tool envelope (중요)

Cowork `agents/<slug>.md` YAML frontmatter `tools:` is **not** the CMA `tools:` block. CMA orchestrators always disable the toolset by default and re-enable `read` / `grep` / `glob` only. Write lives on exactly one leaf.

| slug | Cowork `agents/<slug>.md` `tools:` | CMA orchestrator `agent.yaml` tools |
|---|---|---|
| `pitch-agent` | `Read, Write, Edit, mcp__capiq__*` | `read, grep, glob` + MCP `capiq`, `daloopa` |
| `market-researcher` | `Read, Write, Edit, mcp__capiq__*, mcp__factset__*` | `read, grep, glob` + MCP `capiq`, `factset` |
| `earnings-reviewer` | `Read, Write, Edit, mcp__factset__*, mcp__daloopa__*` | `read, grep, glob` + MCP `factset`, `daloopa` |
| `meeting-prep-agent` | `Read, Write, mcp__crm__*, mcp__capiq__*` | `read, grep, glob` + MCP `crm`, `capiq` |
| `model-builder` | `Read, Write, Edit, mcp__capiq__*, mcp__daloopa__*` | `read, grep, glob` + MCP `capiq`, `daloopa` |
| `gl-reconciler` | `Read, Grep, Glob, mcp__internal-gl__*, mcp__subledger__*` | `read, grep, glob` + MCP `internal-gl`, `subledger` |
| `kyc-screener` | `Read, Grep, Glob, mcp__screening__*` | `read, grep, glob` + MCP `screening` |
| `month-end-closer` | `Read, Grep, Glob, mcp__internal-gl__*` | `read, grep, glob` + MCP `internal-gl` |
| `statement-auditor` | `Read, Grep, Glob, mcp__nav__*` | `read, grep, glob` + MCP `nav` |
| `valuation-reviewer` | `Read, Grep, Glob, mcp__portfolio__*` | `read, grep, glob` + MCP `portfolio` |

Implications:

- Cowork orchestrator for pitch / market / earnings / meeting-prep / model-builder **holds Write**. CMA orchestrator **never** holds Write.
- Cowork `pitch-agent` lists only `mcp__capiq__*`; CMA also wires `daloopa`.
- CMA always enables `grep` + `glob` on the orchestrator even when Cowork frontmatter omits them.

### 1.5 Headless vs interactive

CMA `append` forces `./out/` artifacts and "do not assume an open Office document." Skills such as `dcf-model` themselves branch on "Office JS vs Python/openpyxl". That branch is skill content, not harness.

CMA per-agent READMEs: **"Not guaranteed"** — agents draft; humans sign off. Root README disclaimer: nothing is investment/legal/tax/accounting advice; no posting to a ledger, no executing transactions, no approving onboarding.

### 1.6 Research preview

Root README:

> **Research Preview:** subagent delegation (`callable_agents`) is a preview capability.

Cookbook README:

> `callable_agents` (multi-agent delegation) supports **one delegation level**. An orchestrator can call workers; workers cannot call further subagents.

---

## 2. Marketplace registration model

File: `.claude-plugin/marketplace.json` (repo-root marketplace, not per-plugin).

### 2.1 Top-level schema (as present)

```json
{
  "name": "claude-for-financial-services",
  "owner": { "name": "Matt Piccolella" },
  "plugins": [ /* 19 entries */ ]
}
```

**Present:** `name`, `owner.name`, `plugins[]`.  
**ABSENT:** `version`, `owner.email`, `metadata`, `description` at marketplace level.

Install identifier used in root README:

```bash
claude plugin marketplace add anthropics/financial-services
claude plugin install financial-analysis@claude-for-financial-services
claude plugin install pitch-agent@claude-for-financial-services
```

The `@claude-for-financial-services` suffix is the marketplace `name`.

### 2.2 Per-plugin marketplace entry schema (as present)

Every entry has:

- `name` — plugin id (must match that plugin's `.claude-plugin/plugin.json` `name` in the samples)
- `displayName`
- `source` — repo-relative path
- `description`

**ABSENT on marketplace entries:** `version`, `category`, `tags`, `strict`, `author`. Version lives only in each plugin's `plugin.json`.

`plugin-validate.yml` comment: Claude Code CLI `2.1.143` is "first release whose `plugin validate` accepts `displayName` on marketplace entries (`2.1.140` and earlier reject it as an unrecognized key)."

### 2.3 Full plugin list (19)

| marketplace `name` | `source` | kind |
|---|---|---|
| `financial-analysis` | `./plugins/vertical-plugins/financial-analysis` | vertical |
| `investment-banking` | `./plugins/vertical-plugins/investment-banking` | vertical |
| `equity-research` | `./plugins/vertical-plugins/equity-research` | vertical |
| `private-equity` | `./plugins/vertical-plugins/private-equity` | vertical |
| `fund-admin` | `./plugins/vertical-plugins/fund-admin` | vertical |
| `operations` | `./plugins/vertical-plugins/operations` | vertical |
| `pitch-agent` | `./plugins/agent-plugins/pitch-agent` | named agent |
| `market-researcher` | `./plugins/agent-plugins/market-researcher` | named agent |
| `earnings-reviewer` | `./plugins/agent-plugins/earnings-reviewer` | named agent |
| `meeting-prep-agent` | `./plugins/agent-plugins/meeting-prep-agent` | named agent |
| `model-builder` | `./plugins/agent-plugins/model-builder` | named agent |
| `gl-reconciler` | `./plugins/agent-plugins/gl-reconciler` | named agent |
| `kyc-screener` | `./plugins/agent-plugins/kyc-screener` | named agent |
| `valuation-reviewer` | `./plugins/agent-plugins/valuation-reviewer` | named agent |
| `month-end-closer` | `./plugins/agent-plugins/month-end-closer` | named agent |
| `statement-auditor` | `./plugins/agent-plugins/statement-auditor` | named agent |
| `lseg` | `./plugins/partner-built/lseg` | partner |
| `sp-global` | `./plugins/partner-built/spglobal` | partner (dir `spglobal`, plugin name `sp-global`) |
| `claude-for-msft-365-install` | `./claude-for-msft-365-install` | Claude Code admin plugin, **not** under `plugins/` |

### 2.4 Cowork install paths (README)

1. Paste repo URL `https://github.com/anthropics/financial-services` into Cowork **Settings → Plugins → Add plugin**, then pick from the marketplace list.
2. Zip any directory under `plugins/` (example: `plugins/agent-plugins/pitch-agent/`) and upload.

### 2.5 `check.py` marketplace rule

```python
mp = ROOT / ".claude-plugin" / "marketplace.json"
for p in json.loads(mp.read_text()).get("plugins", []):
    src = (ROOT / p["source"]).resolve()
    if not (src / ".claude-plugin" / "plugin.json").is_file():
        err(f"marketplace: {p['name']} source -> {p['source']} (no plugin.json)")
```

It does **not** check that marketplace `name` equals `plugin.json` `name`. It does **not** require `displayName` or `description`.

### 2.6 CI vs marketplace

`.github/workflows/plugin-validate.yml` runs:

```bash
claude plugin validate .claude-plugin/marketplace.json
```

then, separately, `claude plugin validate "$plugin_dir"` for every `plugins/**/.claude-plugin/plugin.json`.

**Gap:** `claude-for-msft-365-install` is in the marketplace but **not** in the `find plugins ...` loop, so it is only validated transitively via the marketplace file, not as a standalone plugin dir in CI.

---

## 3. `plugin.json` schema and discovery (skills, commands, agents, hooks, mcp)

### 3.1 Actual schema in this repo

Every plugin has `<root>/.claude-plugin/plugin.json`. Sampled 19/19. Typical Anthropic FSI plugin:

```json
{
  "name": "pitch-agent",
  "version": "0.1.1",
  "description": "Comps, precedents, LBO to a branded pitch deck, end to end",
  "author": { "name": "Anthropic FSI" }
}
```

| Field | Required in practice | Notes |
|---|---|---|
| `name` | yes | kebab-case; matches marketplace `name` in all sampled files |
| `version` | yes | semver `x.y.z`; gates Claude Code update delivery (`version_bump.py` docstring) |
| `description` | yes | |
| `author.name` | yes | `"Anthropic FSI"`, `"Anthropic"`, `"LSEG"`, `"Kensho Technologies"` |
| `author.email` | optional | only `claude-for-msft-365-install`, `sp-global` |
| `homepage` | optional | `sp-global` only |
| `repository` | optional | `sp-global` only |
| `license` | optional | `sp-global` = `"Apache-2.0"` |
| `keywords` | optional | `sp-global` only |

**ABSENT in every `plugin.json`:** `skills`, `commands`, `agents`, `hooks`, `mcp`, `strict`, `displayName` (displayName is marketplace-only).

`CLAUDE.md` says `plugin.json` contains "component discovery settings". **Those keys are not in the files.** Discovery is directory convention.

### 3.2 Convention-based discovery (observed layout)

| Component | Path convention | Who has it |
|---|---|---|
| Skills | `<plugin>/skills/<name>/SKILL.md` (+ optional `scripts/`, `references/`, `assets/`) | all verticals, all agent-plugins, both partners |
| Commands | `<plugin>/commands/<name>.md` | equity-research, financial-analysis, investment-banking, private-equity, lseg, claude-for-msft-365-install. **ABSENT** on agent-plugins, fund-admin, operations, spglobal |
| Agents | `<plugin>/agents/<slug>.md` | **agent-plugins only** (one md per plugin) |
| Hooks | `<plugin>/hooks/hooks.json` | equity-research, financial-analysis, investment-banking, private-equity. Contents: `{"hooks": {}}` |
| MCP | `<plugin>/.mcp.json` | financial-analysis (populated), lseg (populated), spglobal (populated), investment-banking (`{"mcpServers": {}}`), private-equity (`{"mcpServers": {}}`) |

`plugin-validate.yml` comment documents the hooks shape the official linter expects: `{"hooks": {}}`, not a bare `[]`.

### 3.3 Cowork agent markdown frontmatter

`check.py` requires every `plugins/agent-plugins/*/agents/*.md` to start with `---` and YAML frontmatter containing `name` + `description`. Observed extra key, **not** linted by `check.py`: `tools`.

Pattern:

```yaml
---
name: <slug>
description: <when-to-use prose>
tools: Read, Write, Edit, mcp__<server>__*
---
```

`tools` uses Cowork/Claude-Code names (`Read`, `Write`, `Edit`, `Grep`, `Glob`) and MCP wildcards `mcp__<server>__*`. This is **not** the CMA `agent_toolset_20260401` shape.

### 3.4 Command markdown frontmatter (Cowork slash commands)

Example `plugins/vertical-plugins/equity-research/commands/earnings.md`:

```yaml
---
description: Analyze quarterly earnings and create an earnings update report
argument-hint: "[company name or ticker] [quarter, e.g. Q3 2024]"
---
```

Invoked as `/plugin:command-name` (`CLAUDE.md`) or `/earnings` etc. (root README).  
**ABSENT:** `check.py` does **not** lint command frontmatter.

### 3.5 Skill `SKILL.md` frontmatter (from `skill-creator`)

`plugins/vertical-plugins/financial-analysis/skills/skill-creator/scripts/quick_validate.py` allows:

```
ALLOWED_PROPERTIES = {'name', 'description', 'license', 'allowed-tools', 'metadata'}
```

Required: `name`, `description`.  
`name` regex: `^[a-z0-9-]+$`, no leading/trailing hyphen, no `--`, max 64 chars.  
This validator is **inside the skill-creator skill**; `scripts/check.py` does **not** call it.

Skill anatomy (skill-creator):

```
skill-name/
├── SKILL.md          # required
├── scripts/          # optional executables
├── references/       # optional, load-on-demand
└── assets/           # optional output resources
```

CMA upload zips the **directory** (see §7), so `scripts/` / `references/` ride along.

### 3.6 Versions currently in-tree

| plugin | version |
|---|---|
| financial-analysis | 0.1.1 |
| investment-banking | 0.2.1 |
| equity-research | 0.1.2 |
| private-equity | 0.1.2 |
| fund-admin | 0.1.0 |
| operations | 0.1.0 |
| pitch-agent | 0.1.1 |
| market-researcher | 0.1.1 |
| earnings-reviewer | 0.1.1 |
| meeting-prep-agent | 0.1.1 |
| model-builder | 0.1.0 |
| gl-reconciler | 0.1.0 |
| kyc-screener | 0.1.0 |
| valuation-reviewer | 0.1.1 |
| month-end-closer | 0.1.0 |
| statement-auditor | 0.1.0 |
| lseg | 1.0.0 |
| sp-global | 1.0.1 |
| claude-for-msft-365-install | 0.1.13 |

### 3.7 `.mcp.json` Cowork schema (observed)

```json
{
  "mcpServers": {
    "<name>": { "type": "http", "url": "https://..." }
  }
}
```

financial-analysis lists: `daloopa`, `morningstar`, `sp-global`, `factset`, `moodys`, `mtnewswire`, `aiera`, `lseg`, `pitchbook`, `chronograph`, `egnyte`, `box`.

**JSON is currently invalid:** missing comma between `egnyte` and `box`, and `box` object is missing a closing `}`. `python json.loads` → `Expecting ',' delimiter: line 47 column 5`. `check.py` does **not** parse `.mcp.json` (its JSON globs are marketplace, plugin.json, steering-examples only).

URL mismatch: financial-analysis lseg URL is `https://api.analytics.lseg.com/lfa/mcp`; partner `plugins/partner-built/lseg/.mcp.json` is `https://api.analytics.lseg.com/lfa/mcp/server-cl`.

CMA does **not** read `.mcp.json`. CMA MCP is `mcp_servers: [{type: url, name, url: "${ENV}"}]` in YAML.

---

## 4. Skill source-of-truth vs bundled copies; `sync-agent-skills.py` algorithm

### 4.1 Contract

`scripts/sync-agent-skills.py` docstring:

> Agent plugins under `plugins/agent-plugins/<slug>/skills/<name>/` are vendored copies of `plugins/vertical-plugins/*/skills/<name>/`. The vertical copy is the source of truth; run this after editing a skill there to propagate the change into every agent that bundles it.

`CLAUDE.md`: **Edit skills in `vertical-plugins/`**, then `python3 scripts/sync-agent-skills.py`.

### 4.2 Algorithm (verbatim behavior)

```python
ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "plugins" / "agent-plugins"
VERTICALS = ROOT / "plugins" / "vertical-plugins"

src_by_name: dict[str, Path] = {}
for sk in VERTICALS.glob("*/skills/*"):
    if sk.is_dir():
        src_by_name[sk.name] = sk   # last glob win if duplicate names

synced = 0
missing: list[str] = []
for bundled in sorted(AGENTS.glob("*/skills/*")):
    if not bundled.is_dir():
        continue
    src = src_by_name.get(bundled.name)
    if not src:
        missing.append(...)
        continue
    shutil.rmtree(bundled)
    shutil.copytree(src, bundled)   # full replace, not merge
    synced += 1
```

Properties:

- Match is **directory basename only**, not vertical membership. `xlsx-author` in pitch-agent, gl-reconciler, … all copy from the single vertical dir named `xlsx-author` (`financial-analysis/skills/xlsx-author`).
- If two verticals had the same skill name, **last glob wins**. In this checkout skill names are unique across verticals.
- Destructive: `rmtree` then `copytree`. Agent-local edits are wiped.
- Does **not** add new skills to an agent. It only refreshes names **already present** under that agent's `skills/`.
- Does **not** look at `partner-built/`.
- Exit 1 if any bundled dir has no vertical source; still prints `synced N`.

### 4.3 `check.py` drift detector (4b)

```python
src_by_name = {p.name: p for p in PLUGINS.glob("vertical-plugins/*/skills/*") if p.is_dir()}
for bundled in sorted(PLUGINS.glob("agent-plugins/*/skills/*")):
    src = src_by_name.get(bundled.name)
    if not src:
        err(f"bundled-skill: {rel(bundled)}: no vertical-plugins source named '{bundled.name}'")
        continue
    cmp = filecmp.dircmp(src, bundled)
    if cmp.diff_files or cmp.left_only or cmp.right_only:
        err(f"bundled-skill: {rel(bundled)}: drifted from {rel(src)} (run scripts/sync-agent-skills.py)")
```

`filecmp.dircmp` is **shallow** (stat + maybe first-bytes). Nested-only differences can be missed if filenames match.

### 4.4 Current bundle map

| agent-plugin | bundled skill names | vertical source |
|---|---|---|
| earnings-reviewer | audit-xls, earnings-analysis, earnings-preview, model-update, morning-note, xlsx-author | financial-analysis / equity-research |
| gl-reconciler | audit-xls, break-trace, gl-recon, xlsx-author | financial-analysis / fund-admin |
| kyc-screener | kyc-doc-parse, kyc-rules, xlsx-author | operations / financial-analysis |
| market-researcher | competitive-analysis, comps-analysis, idea-generation, pptx-author, sector-overview | financial-analysis / equity-research |
| meeting-prep-agent | client-report, client-review, investment-proposal, pptx-author | **pptx-author → financial-analysis; the other three have NO vertical-plugins source** |
| model-builder | 3-statement-model, audit-xls, comps-analysis, dcf-model, lbo-model, xlsx-author | financial-analysis |
| month-end-closer | accrual-schedule, audit-xls, roll-forward, variance-commentary, xlsx-author | fund-admin / financial-analysis |
| pitch-agent | 3-statement-model, audit-xls, comps-analysis, dcf-model, deck-refresh, ib-check-deck, lbo-model, pitch-deck, pptx-author, sector-overview, xlsx-author | financial-analysis / investment-banking / equity-research |
| statement-auditor | audit-xls, nav-tieout, xlsx-author | financial-analysis / fund-admin |
| valuation-reviewer | ic-memo, portfolio-monitoring, returns-analysis, xlsx-author | private-equity / financial-analysis |

**Drift that `check.py` would fail today:**  
`plugins/agent-plugins/meeting-prep-agent/skills/{client-report,client-review,investment-proposal}` exist only under the agent plugin. Cookbook README labels this agent as vertical `wealth-management`, which is **ABSENT**. Root README's `claude-for-financial-advisors` path is also **ABSENT**. `sync-agent-skills.py` would WARN/exit 1 for those three dirs.

### 4.5 Agent-prose skill-reference check (check.py 4b2)

```python
for ref in set(re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", md.read_text())):
    if ref in src_by_name and ref not in bundle:
        err(f"agent-prose: {rel(md)}: references `{ref}` but plugins/agent-plugins/{slug}/skills/{ref}/ is not bundled")
```

Regex requires **at least one hyphen** (kebab-case). A backtick name that is not in `vertical-plugins` is ignored. So `client-review` referenced in meeting-prep agent.md is **not** flagged by 4b2 (not in `src_by_name`); it **is** flagged by 4b (no vertical source).

---

## 5. `check.py` lint rules

Path: `scripts/check.py`. Exit 0 clean, 1 on issues, 2 if pyyaml missing. Side effect: installs git hooks (best-effort, never fatal).

### 5.0 Hook self-install (runs first)

```python
want = ".githooks"
# git -C ROOT config --get core.hooksPath
# if != want: git config core.hooksPath .githooks
```

Native Husky-`prepare` equivalent. Failures swallowed.

Docstring vs code: docstring says "Every `*.yaml` under `managed-agents/`". Actual path is `managed-agent-cookbooks/` (`MANAGED = ROOT / "managed-agent-cookbooks"`).

### 5.1 YAML parse

`MANAGED.rglob("*.yaml")` → `yaml.safe_load`. Any `YAMLError` recorded. Covers orchestrators and subagents.

### 5.2 JSON parse

Globs:

- `.claude-plugin/marketplace.json`
- `plugins/**/.claude-plugin/plugin.json`
- `managed-agent-cookbooks/*/steering-examples.json`

**Not parsed:** `.mcp.json`, `hooks/hooks.json`, `claude-for-msft-365-install/.claude-plugin/plugin.json` (that plugin.json is **not** under `plugins/`).  
`version_bump.py` **does** see msft-365 via `**/.claude-plugin/plugin.json`. Inconsistency.

### 5.3 agent.md frontmatter

`plugins/agent-plugins/*/agents/*.md` must:

- start with `---`
- split into frontmatter YAML
- contain keys `name` and `description`

Does **not** require `tools`. Does **not** lint vertical-plugin agents (none exist). Does **not** lint commands.

### 5.4 Cross-file refs (`check_refs`)

For every cookbook YAML:

| Manifest key | Resolution | Failure |
|---|---|---|
| `system.file` | `(yaml.parent / file).resolve()` must be a **file** | `ref: … system.file -> … (not found)` |
| `skills[].path` | resolve, must **exist** (file or dir) | `skills.path -> … (not found)` |
| `skills[].from_plugin` | resolve, must contain a `skills/` **directory** | `skills.from_plugin -> … (no skills/ dir)` |
| `callable_agents[].manifest` | resolve, must be a **file** | `callable_agents.manifest -> … (not found)` |

Does **not** check `system.text` non-empty.  
Does **not** check `mcp_servers[].url` or env interpolation.  
Does **not** check depth-1.  
Does **not** require `output_schema` on readers.

### 5.5 Bundled-skill drift — see §4.3

### 5.6 Agent-prose skill refs — see §4.5

### 5.7 Marketplace sources — see §2.5

### 5.8 Required files per cookbook

Every **directory** under `managed-agent-cookbooks/` (not files) must contain:

- `agent.yaml`
- `README.md`
- `steering-examples.json`

Does **not** require `subagents/`. A cookbook with zero workers would pass this rule.

### 5.9 PowerShell ASCII / BOM

```python
ASCII_ONLY_SUFFIXES = {".ps1", ".psm1", ".psd1"}
for ps in sorted(ROOT.rglob("*.ps1")):
    if any(part in {".git", "node_modules"} for part in ps.parts):
        continue
    raw = ps.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        continue  # UTF-8 BOM → non-ASCII allowed
    # else any byte > 0x7F on a line → error, then break (one error per file)
```

Rationale (comment + CLAUDE.md): Windows PowerShell 5.1 decodes BOM-less `.ps1` as the machine ANSI code page. A smart dash/curly quote can decode to a literal `"`, killing parse. Invisible on macOS.

**Gap:** `ASCII_ONLY_SUFFIXES` includes `.psm1` / `.psd1` but the loop is `rglob("*.ps1")` only. Currently the repo has three `.ps1` files, all under `claude-for-msft-365-install/scripts/`. No `.psm1`/`.psd1`.

---

## 6. `validate.py` vs `check.py` vs `test-cookbooks.sh`

| | `check.py` | `validate.py` | `test-cookbooks.sh` |
|---|---|---|---|
| Purpose | Static lint of manifests, refs, skill drift, `.ps1` ASCII | Runtime JSON-Schema check of **worker output** | Dry-run deploy every cookbook; assert resolved POST bodies |
| Input | whole repo | `validate.py <output.json> <schema.json\|yaml>` | none (walks cookbooks) |
| Deps | pyyaml, git (hooks) | jsonschema, pyyaml if schema is YAML | bash, `deploy-managed-agent.sh` (jq, pyyaml, zip) |
| CMA API | no | no | `--dry-run` only (no network) |
| In CI | **no** | **no** | **no** |
| Exit | 0/1/2 | 0 valid, 1 invalid, 2 usage | 0/1 |

### 6.1 `validate.py`

Docstring:

> The CMA API does not enforce structured output today, so the deploy harness runs this between a reader subagent and the orchestrator. Schemas live in each subagent yaml under `output_schema:` — the deploy script extracts them.

**What the code actually does:** load instance + schema, `jsonschema.validate`, print `OK` or `INVALID: {message} at {path}`.

**What it does not do:** extract `output_schema` from YAML itself (caller must pass a schema file). Deploy script does **not** invoke `validate.py` (see §7.8). The "harness runs this between reader and orchestrator" loop is **ABSENT**.

### 6.2 `test-cookbooks.sh`

```bash
for d in managed-agent-cookbooks/*/; do
  bash scripts/deploy-managed-agent.sh "$slug" --dry-run 2>&1 | tail -n +2 | python3 -c '...'
done
```

`tail -n +2` drops the dry-run header line (`# --dry-run: resolved POST /v1/agents bodies ...`). Remaining stdin is a JSON array of bodies (subagents first, orchestrator last).

Assertions:

1. every body has truthy `system`
2. every body **except the last** has falsy `callable_agents` (empty list `[]` is falsy — OK because subagents set `callable_agents: []`)
3. the string `output_schema` must not appear in `json.dumps(b)`

Does **not** check skill_id shape, MCP env interpolation leftover `${…}`, tool default_config, or name uniqueness.

### 6.3 How they compose (intended vs actual)

Intended (comments):

1. `check.py` before commit — static.
2. `test-cookbooks.sh` — resolved payload shape, depth-1.
3. `validate.py` — between untrusted reader output and orchestrator, at **run** time.
4. Official `claude plugin validate` in CI — plugin/marketplace schema.

Actual: (1) local-only + hook install; (2) local-only; (3) CLI exists, **not wired** into deploy or orchestrate; (4) CI only.

---

## 7. `deploy-managed-agent.sh`: endpoints, bodies, env, skill upload, subagent create, orchestrator POST

Path: `scripts/deploy-managed-agent.sh`. `set -euo pipefail`.

### 7.1 CLI

```
scripts/deploy-managed-agent.sh <slug> [--dry-run]
```

`ROLE=$1`. `--dry-run` is only recognized as `$2` exactly. Manifest path: `$ROOT/managed-agent-cookbooks/$ROLE/agent.yaml`. Missing file → exit 1.

Requires: `jq`, `python3` + `pyyaml`. Non-dry-run also requires `ANTHROPIC_API_KEY`. `zip` used for skill upload.

### 7.2 Env vars

| Var | Required | Default | Role |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | yes unless `--dry-run` | — | `x-api-key` |
| `ANTHROPIC_API_BASE` | no | `https://api.anthropic.com` | API host |
| `REPO_SLUG` | if git remote missing | `basename -s .git $(git config --get remote.origin.url)` | cookbook tag prefix |
| `SKILL_TITLE_PREFIX` | no | empty | prepended to skill `display_title` |
| `DEPLOY_DEBUG` | no | unset | if set, prints `{name, callable_agents}` to stderr |
| MCP URL vars | at **runtime** of the agent, not strictly at deploy | interpolated if set | see §7.3 |

MCP vars referenced in YAML (interpolated by `yaml2json` if present in the environment **at deploy time**):

`CAPIQ_MCP_URL`, `DALOOPA_MCP_URL`, `FACTSET_MCP_URL`, `GL_MCP_URL`, `SUBLEDGER_MCP_URL`, `SCREENING_MCP_URL`, `CRM_MCP_URL`, `PORTFOLIO_MCP_URL`, `NAV_MCP_URL`.

If unset, `${NAME}` is **left intact** in the posted JSON (see interpolation). CMA would then receive a literal `${GL_MCP_URL}` string.

### 7.3 `${ENV}` interpolation (`yaml2json`)

Embedded Python:

```python
SAFE = re.compile(r"^[A-Za-z0-9._/:@-]*$")
def sub(m):
    name = m.group(1)
    v = os.environ.get(name)
    if v is None:
        return m.group(0)          # leave ${NAME}
    if not SAFE.fullmatch(v):
        sys.exit(f"refusing ${{{name}}}: value contains characters outside [A-Za-z0-9._/:@-]")
    return v
t = re.sub(r"\$\{([A-Z0-9_]+)\}", sub, t)
json.dump(yaml.safe_load(t), sys.stdout)
```

- Only `${UPPER_SNAKE}` (A–Z, 0–9, `_`). `$FOO` without braces is **not** expanded.
- Allowed value charset: `A-Za-z0-9._/:@-` (covers URLs). Space, `?`, `&`, `=`, query strings → **hard fail**.
- Security: blocks injection of JSON/YAML metacharacters via env.

gl-reconciler uses unquoted `${GL_MCP_URL}`; other cookbooks use `"${CAPIQ_MCP_URL}"`. Both survive YAML load after substitution.

### 7.4 Headers / endpoints

Shared helper `req()` for JSON CMA calls:

```
curl -sS
  -H "x-api-key: $ANTHROPIC_API_KEY"
  -H "anthropic-version: 2023-06-01"
  -H "anthropic-beta: managed-agents-2026-04-01"
  -H "content-type: application/json"
```

| Method | Path | Beta | Body |
|---|---|---|---|
| `POST` | `$API/v1/skills` | `skills-2025-10-02` (multipart; **not** managed-agents) | `display_title`, `files[]=@zip` |
| `POST` | `$API/v1/agents` | `managed-agents-2026-04-01` | resolved JSON manifest |

**ABSENT in this script:** GET/PATCH/DELETE `/v1/agents`, `/v1/agents/{id}`, session create, steer, any retry/backoff, any update-in-place. Every run **creates new** skill ids and agent ids.

Success print:

```
deployed: $ROLE
agent id: $AGENT_ID
cookbook: $COOKBOOK_TAG          # ${REPO_SLUG}/${ROLE}
console:  https://console.anthropic.com/agents/$AGENT_ID
```

### 7.5 Skill upload

```bash
zip="$(mktemp -t skill).zip"
(cd "$(dirname "$path")" && zip -qr "$zip" "$(basename "$path")")
resp=$(curl -sS "$API/v1/skills" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "anthropic-beta: skills-2025-10-02" \
  -F "display_title=${SKILL_TITLE_PREFIX:-}$(basename "$path")" \
  -F "files[]=@$zip")
id=$(jq -r '.id // empty' <<<"$resp")
# posted skill ref:
{"type":"custom","skill_id":"<id>","version":"latest"}
```

Zip contains the skill **directory as the top-level folder** (so `SKILL.md` is at `<name>/SKILL.md` inside the zip).

In-process cache file `SKILL_CACHE_FILE`: key = `basename "$path"` (skill folder name, not absolute path). Same basename reused across orchestrator `from_plugin` and subagent `path` uploads in one deploy.

Dry-run skill ref: `{"type":"custom","skill_id":"DRYRUN_<basename>","version":"latest"}`.

Empty `.id` → print response, `exit 1`.

### 7.6 Manifest conveniences (`resolve_manifest` / `inline_system`)

**`from_plugin`:**

```bash
fp=$(jq -r '.skills[]? | select(.from_plugin) | .from_plugin' <<<"$json" | head -1)
```

Only the **first** `from_plugin` is expanded. Then **all** `from_plugin` entries are stripped and replaced with `{__upload: abs path}` for each `$plugdir/skills/*/`.

**Gotcha:** two `from_plugin` lines → second's plugin is dropped.

**`path`:** rewritten to `{__upload: $base + "/" + .path}`.

**`system` object:**

| key | behavior |
|---|---|
| `system.file` | file contents become body (must exist) |
| `system.text` | used as body if no file, or ignored if file present (`body="$text"` then overwritten by file) |
| `system.append` | concatenated as `body + "\n\n" + append` |
| `system` already a string | left as-is |

`system.text` then `system.file` both set → **file wins**, text discarded. No cookbook currently sets both.

### 7.7 `create_agent` recursion (subagents first, orchestrator last)

```
create_agent(file):
  json = resolve_manifest(file)
  json = inline_system(json, base)
  for each skills[].__upload: upload_skill, replace .skills with [{type, skill_id, version}]
  for each callable_agents[].manifest:
      (id, ver) = create_agent(base/manifest)    # recursive
      collect {type:"agent", id, version: ver}   # ver is JSON number (--argjson)
  json.callable_agents = collected
  del json.output_schema
  json.metadata = (json.metadata // {}) + {anthropic_cookbook: COOKBOOK_TAG}
  POST /v1/agents
  return "<id> <version>"     # version from response `.version // 1`
```

Order for a typical 3-leaf cookbook: leaf1 POST, leaf2 POST, leaf3 POST, orchestrator POST. Dry-run appends bodies in that order, then `jq -s '.'`.

Parent skills are uploaded **before** recursing into children. Cache still hits when children re-upload the same basename.

`callable_agents` API shape actually posted:

```json
{ "type": "agent", "id": "<created-id>", "version": 1 }
```

Cookbook README mapping table says `version: latest`. **The script posts the numeric API version**, not the string `"latest"`. Skills use `"latest"`; agents use a number. Document both.

### 7.8 "Thin validation wrapper" — advertised, ABSENT

Script header:

> Reader subagents with an `output_schema` block get a thin validation wrapper so their JSON is schema-checked before the orchestrator consumes it.

Code path: `del(.output_schema)` only. No wrapper agent is created. No `validate.py` invocation. `test-cookbooks.sh` asserts `output_schema` does **not** leak into POST bodies (because the API would reject an unknown field, per that test).

`output_schema` is a **harness-only** key. Runtime enforcement would have to live in the caller's workflow engine.

### 7.9 Cookbook tag

```
COOKBOOK_TAG="${REPO_SLUG}/${ROLE}"
metadata.anthropic_cookbook = COOKBOOK_TAG
```

Example: `financial-services/gl-reconciler`. Injected on **every** created agent including leaves.

---

## 8. `orchestrate.py`: `handoff_request` protocol, allowlist, schema, threat model, SSE/steer loop

Path: `scripts/orchestrate.py`. Header: **REFERENCE ONLY** — replace with Temporal / Airflow / Guidewire event bus.

### 8.1 Threat model (header comment, quoted)

Handoff requests are surfaced in the orchestrator's **text output**, downstream of untrusted-document readers. An attacker who controls a processed document could embed a literal `handoff_request` blob that, if echoed, would be parsed here.

Mitigations in this script:

1. hard-allowlist `target_agent` against deployed slugs
2. JSON-Schema validate `payload` before steering

Production recommendation in the same comment: emit handoffs via a **dedicated tool call** or a **typed SSE event** the model cannot produce by quoting document text.

### 8.2 Allowlist

```python
ALLOWED_TARGETS = {
    "pitch-agent", "market-researcher", "earnings-reviewer", "meeting-prep-agent",
    "model-builder", "gl-reconciler", "kyc-screener",
    "valuation-reviewer", "month-end-closer", "statement-auditor",
}
```

Equals the 10 named agents. Unknown target → `extract_handoff` returns `None` (silent drop).

### 8.3 Wire format (regex + JSON)

```python
HANDOFF_RE = re.compile(r'\{"type":\s*"handoff_request".*?\}', re.DOTALL)
```

Non-greedy `.*?` up to the first `}`. Nested objects in `payload` can **truncate** the match (first closing brace). A payload with nested `{...}` is fragile.

Expected object (inferred from code, not a schema on the outer object):

```json
{
  "type": "handoff_request",
  "target_agent": "<slug in ALLOWED_TARGETS>",
  "payload": {
    "event": "<string, required, maxLength 2000>",
    "context_ref": "<optional, maxLength 256, pattern ^[A-Za-z0-9 ._/:#-]+$>"
  }
}
```

`HANDOFF_PAYLOAD_SCHEMA`:

```python
{
    "type": "object",
    "additionalProperties": False,
    "required": ["event"],
    "properties": {
        "event": {"type": "string", "maxLength": 2000},
        "context_ref": {"type": "string", "maxLength": 256,
                        "pattern": r"^[A-Za-z0-9 ._/:#-]+$"},
    },
}
```

Outer object is **not** schema-validated. Extra keys on the outer object are ignored. Missing `payload` → `jsonschema.validate(None)` fails → drop.

### 8.4 SSE / steer loop

```python
def run(source_session_id: str, agent_ids: dict[str, str]) -> None:
    client = anthropic.Anthropic()
    with client.beta.agents.sessions.stream(session_id=source_session_id) as stream:
        for event in stream:
            if event.type != "message_delta" or not getattr(event, "text", None):
                continue
            handoff = extract_handoff(event.text)
            ...
            client.beta.agents.sessions.steer(
                agent_id=target_id,
                input=handoff["payload"]["event"],
            )
```

`# type: ignore[attr-defined]` — comment: `/v1/agents` is a preview endpoint; SDK type stubs don't cover it yet.

| Item | In code | Notes |
|---|---|---|
| Stream API | `client.beta.agents.sessions.stream(session_id=...)` | SDK, not curl |
| Event filter | `event.type == "message_delta"` and `event.text` | other event types ignored |
| Steer API | `client.beta.agents.sessions.steer(agent_id=..., input=...)` | **only** `payload.event` string |
| `context_ref` | validated then **discarded** | not passed to steer |
| Target session | **ABSENT** | no `session_id` on steer; no "create session" call in this file |
| Auth | `anthropic.Anthropic()` default env (`ANTHROPIC_API_KEY`) | not using `ANTHROPIC_API_BASE` explicitly |
| `__main__` | `SOURCE_SESSION_ID` required; `AGENT_IDS` JSON default `{}` | `AGENT_IDS` maps slug → deployed CMA agent id |

Named agents **never call each other via `callable_agents`**. Cross-agent work is this text protocol + external bus (`managed-agent-cookbooks/README.md`).

Documented handoff edges (per-agent READMEs):

| from | to | why |
|---|---|---|
| `gl-reconciler` | `month-end-closer` | verified breaks into close commentary |
| `pitch-agent` | `model-builder` | rebuild model after thesis change |
| `earnings-reviewer` | `model-builder` | DCF after earnings-driven thesis change |
| `market-researcher` | `model-builder` | model a name from the ideas shortlist |
| `valuation-reviewer` | `gl-reconciler` | flagged portcos |

`model-builder` README: receives handoffs from `earnings-reviewer` or `pitch-agent`.  
`kyc-screener`, `statement-auditor`, `meeting-prep-agent` READMEs do not name an outbound handoff target.

---

## 9. `version_bump.py` + pre-commit hook + GitHub Action

### 9.1 Why

Docstring: a plugin's `.claude-plugin/plugin.json` `version` **gates update delivery** to already-installed users (Claude Code only re-delivers a plugin when version changes). Goal: any plugin modified on a branch ends up **exactly one patch ahead of `main`**, bumped once, not once per commit.

### 9.2 Modes

| Mode | Mutating? | Change set | Used by |
|---|---|---|---|
| `--apply` | yes: write `plugin.json`, `git add` | **staged** files (`git diff --cached --name-only`) | `.githooks/pre-commit` |
| `--check` | no | `base...HEAD` | `.github/workflows/version-bump.yml` |

`--base` optional. Resolution order: explicit `--base`, `origin/main`, `main`. If none exist (shallow clone offline): print skip, **exit 0**. CI is the backstop.

### 9.3 Semver

```python
def parse_semver(v: str) -> tuple[int,int,int] | None:  # requires exactly 3 numeric parts
def patch_bump(v: str) -> str:
    sv = parse_semver(v)
    if sv is None: return "0.0.1"
    return f"{sv[0]}.{sv[1]}.{sv[2] + 1}"
```

**Never** bumps minor/major. No pre-release support (`1.0.0-rc1` → unparseable → apply would write `0.0.1` if not already "ahead" via string inequality).

`is_ahead`:

- base version None (plugin new on branch) → True
- both parseable → numeric `work > base`
- else → `work != base` (string)

Idempotent apply: if working version already ahead of base, skip. Repeated commits on a branch bump **once**.

New plugin (no base version): apply uses `patch_bump(work or "0.0.0")` only if `is_ahead` is False; new plugins short-circuit True, so a brand-new plugin.json is **not** auto-versioned by apply.

### 9.4 Plugin discovery for bump

```python
ROOT.glob("**/.claude-plugin/plugin.json")  # excluding .git/
plugin_root = plugin_json.parent.parent
```

Includes `claude-for-msft-365-install` and partner plugins. Does **not** bump marketplace.json (no `version` there).

A plugin is "changed" if any staged/diff path equals the plugin root, is under it, or `str(c).startswith(f"{root_rel}/")`.

### 9.5 Pre-commit (`.githooks/pre-commit`)

```bash
#!/usr/bin/env bash
set -euo pipefail
# Install: git config core.hooksPath .githooks
# (scripts/check.py self-installs)
# Bypass: git commit --no-verify
REPO_ROOT="$(git rev-parse --show-toplevel)"
# if no python3: skip, exit 0
python3 "$REPO_ROOT/scripts/version_bump.py" --apply
```

Does **not** run `check.py`. ASCII/drift/ref checks are not hook-enforced.

### 9.6 GitHub Action `version-bump.yml`

```yaml
on: pull_request
permissions: { contents: read }
jobs.version-bump:
  runs-on: ubuntu-latest
  steps:
    - actions/checkout@v4  { fetch-depth: 0 }
    - git fetch --no-tags --depth=1 origin "$BASE_REF"
    - python3 scripts/version_bump.py --check --base "origin/$BASE_REF"
```

`BASE_REF` = `github.base_ref`. Full history on the PR head (`fetch-depth: 0`), shallow fetch of the base.

---

## 10. CMA API field mapping table (manifest convention → `POST /v1/agents`)

From `managed-agent-cookbooks/README.md` plus what the script actually emits.

| Manifest convention | Resolves to (POST body) | Notes |
|---|---|---|
| `name: gl-reconciler` | `name` string | passed through |
| `model: claude-opus-4-7` | `model` string | **all** orchestrators and subagents use this; no other model in-repo |
| `system: {file: …, append: "…"}` | `system: "<file contents>\n\n<append>"` | |
| `system: {text: "…"}` | `system: "<text>"` | all subagents |
| `system: "<string>"` | unchanged | unused in cookbooks |
| `tools: [{type: agent_toolset_20260401, default_config: {enabled: false}, configs: [{name, enabled}]}]` | passed through | tool names observed: `read`, `grep`, `glob`, `write`, `edit`, `bash` |
| `tools: [{type: mcp_toolset, mcp_server_name: <n>, default_config: {enabled: true}}]` | passed through | |
| `mcp_servers: [{type: url, name, url: "${ENV}"}]` | url interpolated if env set | leftover `${ENV}` if unset |
| `skills: [{from_plugin: ../../plugins/agent-plugins/<slug>}]` | `[{type:"custom", skill_id, version:"latest"}, …]` one per `skills/*/` | first `from_plugin` only |
| `skills: [{path: ../../../plugins/agent-plugins/<slug>/skills/<name>}]` | one `{type:"custom", skill_id, version:"latest"}` | |
| `skills: []` | `[]` | many readers |
| `callable_agents: [{manifest: ./subagents/x.yaml}]` | `[{type:"agent", id:<created>, version:<int>}]` | README says `version: latest`; script uses API numeric version |
| `callable_agents: []` | `[]` | required on leaves for depth-1 test |
| `output_schema: {…}` | **deleted** before POST | harness-only |
| *(implicit)* | `metadata.anthropic_cookbook: "<REPO_SLUG>/<ROLE>"` | injected |

### 10.1 Fields ABSENT from every cookbook YAML and never set by the script

`effort`, `temperature`, `max_tokens`, `thinking`, `description` (agent-level), `permissions` (top-level), `version` (agent-level; assigned by API), `stop_sequences`, `tool_choice`.

`permissions` in the user question: **ABSENT** as a CMA YAML key. Isolation is expressed by `agent_toolset_20260401` `default_config.enabled: false` plus an allowlist of `{name, enabled: true}`.

### 10.2 Tool isolation pattern (all 10 cookbooks)

Orchestrator:

```yaml
tools:
  - type: agent_toolset_20260401
    default_config: { enabled: false }
    configs:
      - { name: read,  enabled: true }
      - { name: grep,  enabled: true }
      - { name: glob,  enabled: true }
  - { type: mcp_toolset, mcp_server_name: <trusted>, default_config: { enabled: true } }
```

Untrusted reader leaf: `read`+`grep` only, `mcp_servers: []`, `skills: []`, `callable_agents: []`, plus `output_schema`.

Write-holder leaf: `read`+`write`+`edit`, no MCP, skills for `xlsx-author` / `pptx-author` / domain writers. Cookbook README: **Bold leaf = the only worker with Write.**

Bash: only `pitch-agent` `modeler` (`read`+`bash`, no write) and `model-builder` `builder` (`read`+`write`+`edit`+`bash`).

### 10.3 `output_schema` inventory (harness-only)

| cookbook | subagent file | `name` | required keys |
|---|---|---|---|
| gl-reconciler | reader.yaml | `gl-reconciler-reader` | asset_class, status, breaks |
| kyc-screener | doc-reader.yaml | `kyc-doc-reader` | packet_id, entity, ubos |
| earnings-reviewer | transcript-reader.yaml | `earnings-transcript-reader` | ticker, period, actuals |
| market-researcher | sector-reader.yaml | `market-sector-reader` | sector, facts |
| meeting-prep-agent | news-reader.yaml | `briefing-news-reader` | items |
| model-builder | data-puller.yaml | `model-data-puller` | ticker, historicals |
| month-end-closer | ledger-reader.yaml | `close-ledger-reader` | entity, period, support |
| statement-auditor | statement-reader.yaml | `stmt-statement-reader` | batch_id, lps |
| valuation-reviewer | package-reader.yaml | `valuation-package-reader` | fund, as_of, portcos |
| pitch-agent | researcher.yaml | `pitch-researcher` | target, comps |

Common schema policy: `additionalProperties: false` (except some `actuals`/`historicals` maps that allow additional number properties), `maxLength` + `pattern` on strings, `maxItems` on arrays, enums for closed classes. Purpose (reader.yaml comment): injected instructions cannot survive intact.

---

## 11. Depth-1 `callable_agents` constraint

Cookbook README:

> **Research preview:** `callable_agents` (multi-agent delegation) supports **one delegation level**. An orchestrator can call workers; workers cannot call further subagents.

Enforcement in-repo:

| Layer | Enforces depth-1? |
|---|---|
| `deploy-managed-agent.sh` | **NO** — recurses on any `callable_agents[].manifest`. Nested manifests would POST nested agents. |
| `check.py` | **NO** — only checks the manifest file exists |
| `test-cookbooks.sh` | **YES** — `if i<len(b)-1 and x.get('callable_agents'):` error `depth>1` |
| CMA API | documented as preview limit; not re-tested here beyond the dry-run assertion |

All 30 leaf YAMLs set `callable_agents: []` explicitly (empty list is falsy, so the test passes).

Named-agent-to-named-agent calls are **forbidden** on this axis; they go through `handoff_request` (§8).

---

## 12. CI workflows

`.github/` contains **only** `workflows/` with three YAML files. **ABSENT:** CODEOWNERS, dependabot, issue templates, actions, CODEOWNERS, security policy.

All three: `permissions: contents: read`. No write token, no bot commits.

### 12.1 `plugin-validate.yml`

```yaml
on: [pull_request, push.branches: [main]]
env.CLAUDE_VERSION: "2.1.143"
```

Steps: checkout@v4 → cache `~/.local/bin/claude` + `~/.local/share/claude` → `curl -fsSL https://claude.ai/install.sh | bash -s "$CLAUDE_VERSION"` on cache miss →

```bash
claude plugin validate .claude-plugin/marketplace.json
find plugins -path '*/.claude-plugin/plugin.json' | sort
# for each: claude plugin validate "$plugin_dir"
```

Does **not** run `check.py`, `test-cookbooks.sh`, `validate.py`, or deploy.

Pin rationale in comments: reproducible cache key; 2.1.143 first CLI that accepts marketplace `displayName`.

### 12.2 `version-bump.yml`

See §9.6. `on: pull_request` only (not push to main).

### 12.3 `secret-scan.yml`

```yaml
on: pull_request, push.branches: [main]
```

**gitleaks:**

- download `https://github.com/gitleaks/gitleaks/releases/download/v8.28.0/gitleaks_8.28.0_linux_x64.tar.gz`
- sha256 `a65b5253807a68ac0cafa4414031fd740aeb55f54fb7e55f386acb52e6a840eb`
- `./gitleaks git --redact --exit-code 1 .`

**internal-reference scrub:**

```bash
grep -rInE '\.ant\.dev|antspace\.dev|anthropic-internal|\bgo/[a-z][a-z0-9_-]+\b' \
  --include='*.md' --include='*.yaml' --include='*.yml' --include='*.json' \
  --include='*.py' --include='*.sh' \
  --exclude-dir=.github .
```

Excludes `.github` so the workflow file itself is not matched. Hits → `::error::internal Anthropic references found above` exit 1.

checkout pin: `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683` (# v4.2.2), `fetch-depth: 0`.

---

## 13. Security notes in scripts

### 13.1 `orchestrate.py`

See §8.1. Allowlist + payload schema. Prefers typed tool/SSE in production. Regex-on-text is explicitly a footgun.

### 13.2 `deploy-managed-agent.sh`

- Env interpolation charset allowlist (blocks JSON/YAML injection via MCP URLs).
- Unset env leaves `${NAME}` rather than substituting empty (avoids silently posting empty URL; still may post a useless string).
- `--dry-run` does not require API key.
- Skill zip built from a resolved directory; no fetch-from-URL.
- `DEPLOY_DEBUG` only prints name + callable_agents.

No secret scanning inside the script. API key goes to curl header.

### 13.3 Cookbook security tiers (untrusted docs)

Repeated pattern in per-agent READMEs:

| Tier | Touches untrusted docs? | Tools | Connectors |
|---|---|---|---|
| **reader** | Yes | Read, Grep only | None |
| Orchestrator / mid worker | No | Read, Grep, Glob, Agent (+ trusted MCP) | read-only MCP |
| **writer** | No | Read, Write, Edit | None |

Untrusted-input cookbooks: gl-reconciler (custodian statements), kyc (onboarding docs), earnings (transcripts), market (third-party reports), meeting-prep (client emails — news-reader), month-end (vendor invoices), statement-auditor (generated LP statements treated as untrusted), valuation (GP packages).

Task-decomposition cookbooks (trusted MCP inputs): pitch-agent, model-builder. Still one Write-holder.

Reader output: length-capped, character-class-restricted JSON (`output_schema`). Critic/mid workers re-verify against trusted MCP before writer sees data.

**Not guaranteed** (quoted from READMEs): no writes to a system of record; JE drafts staged not posted; KYC recommends a rating, compliance officer decides; LP reports need IR/CCO sign-off; meeting pack is advisor-facing, no client send.

### 13.4 `check.py` / `.ps1`

See §5.9. Defense against Windows parse-break via non-ASCII.

### 13.5 `secret-scan.yml`

gitleaks + internal hostname/go-link scrub. Does not scan `.ps1` in the grep includes (`.ps1` not in `--include`). gitleaks itself scans the git history.

### 13.6 `.gitignore` secrets

```
.env
.env.local
.env.*.local
*.key
*.pem
```

`CLAUDE.md` claims `*.local.md` is gitignored. **`.gitignore` does not contain `*.local.md`.** Only `.env.local` / `.env.*.local`.

---

## 14. File-based no-build philosophy

Root README: "Everything is file-based — markdown and JSON, no build step."

`CLAUDE.md` development workflow:

1. Edit markdown files directly — changes take effect immediately
2. Test commands with `/plugin:command-name`
3. Skills are invoked automatically when their trigger conditions match

Evidence of no build:

- **ABSENT** at repo root: `package.json`, `pyproject.toml`, `requirements.txt`, `Makefile`, `tsconfig.json`
- Plugins are directories with markdown + JSON + YAML
- Cowork: zip a plugin dir or add the git URL
- CMA "build" is `deploy-managed-agent.sh` resolving files and POSTing; no compile
- Skill "package" tooling exists **inside** `skill-creator` (`package_skill.py` → `.skill` zip) but is not used by the repo harness
- `sync-agent-skills.py` is copytree, not a bundler

Contributing (README):

- New skill → `plugins/vertical-plugins/<vertical>/skills/`, then `sync-agent-skills.py`
- New agent → `plugins/agent-plugins/<slug>/` **and** `managed-agent-cookbooks/<slug>/`
- Run `check.py` before pushing

---

## 15. Other facts that matter for migrating this harness to another agent platform (Neos)

### 15.1 Dual-surface split you must re-encode

Neos needs **two adapters** over one prompt+skill tree:

1. Interactive plugin surface (Cowork): agents md + commands + `.mcp.json` + empty hooks
2. Headless graph surface (CMA): orchestrator + depth-1 workers + env-injected MCP URLs + one Write-holder + `./out/` append

Do not assume Cowork `tools:` == CMA `tools:`. They already diverge.

### 15.2 Skill identity is the directory name

Vertical source of truth, vendored per agent, uploaded as a zip of that directory. CMA skill id is **issued at upload** (`POST /v1/skills` → `.id`), version pinned as `"latest"`. There is no stable skill id in git. Every deploy mints new ids (in-process cache only).

### 15.3 MCP is dual-schema

| Surface | Schema |
|---|---|
| Cowork | `.mcp.json` `{mcpServers: {name: {type:"http", url}}}` |
| CMA | `mcp_servers: [{type:"url", name, url}]` + `tools: [{type: mcp_toolset, mcp_server_name}]` |

Cowork MCP names in agent.md (`mcp__capiq__*`) must match `.mcp.json` keys **or** the CMA `mcp_server_name`. Several CMA names (`internal-gl`, `subledger`, `screening`, `crm`, `nav`, `portfolio`) have **no** corresponding `.mcp.json` entry — they are deploy-time URLs for firm systems.

### 15.4 Preview API surface to re-map

Hard-coded:

- `POST /v1/agents` + beta `managed-agents-2026-04-01`
- `POST /v1/skills` + beta `skills-2025-10-02`
- `anthropic-version: 2023-06-01`
- SDK: `client.beta.agents.sessions.stream` / `.steer`
- Console: `https://console.anthropic.com/agents/$AGENT_ID`
- Toolset type string: `agent_toolset_20260401`
- Model id: `claude-opus-4-7` everywhere

Neos equivalents need an explicit mapping for toolset type, skill upload, agent create, session stream, steer.

### 15.5 Cross-agent protocol is text, not graph

Do not look for `callable_agents` between named agents. Look for `handoff_request` JSON in output + an external router. If Neos has typed tool calls / events, **prefer those** (the script says so).

### 15.6 Validation is three layers, two of them unwired to CI

Bring-up checklist for a port:

1. Port `check.py` rules (refs, drift, marketplace sources, required cookbook files)
2. Port dry-run payload assertions (`test-cookbooks.sh`)
3. Decide where `output_schema` is enforced — today it is **not** on the API and **not** in deploy
4. Official `claude plugin validate` is Claude-Code-specific; Neos needs its own plugin linter
5. Version bump is Claude-Code-update-delivery specific; keep iff Neos plugins are version-gated the same way

### 15.7 Known in-repo holes a port should not copy blindly

| Hole | Detail |
|---|---|
| meeting-prep vertical missing | `client-report` / `client-review` / `investment-proposal` have no `vertical-plugins` source; `wealth-management` plugin ABSENT |
| `claude-for-financial-advisors` | linked from README, path ABSENT |
| `mcp-categories.json` | listed in `CLAUDE.md` Key Files, file ABSENT |
| financial-analysis `.mcp.json` | invalid JSON (missing comma / brace around `box`) |
| `output_schema` wrapper | advertised in deploy header, not implemented |
| `validate.py` not called | by deploy or orchestrate |
| `check.py` / `test-cookbooks.sh` not in CI | only plugin-validate, version-bump, secret-scan |
| `from_plugin` `head -1` | multiple from_plugin entries silently drop extras |
| callable_agents version | README `latest` vs script numeric |
| check.py JSON glob | misses `claude-for-msft-365-install` plugin.json and all `.mcp.json` / `hooks.json` |
| plugin-validate find | misses `claude-for-msft-365-install` |
| depth-1 | only test-cookbooks, not deploy |
| `*.local.md` gitignore | documented, not actually ignored |
| no `requirements.txt` | scripts need pyyaml, jsonschema, anthropic, jq, zip, curl |
| always-create | no PATCH; re-deploy duplicates agents/skills |

### 15.8 Steering events (session kick payload)

`steering-examples.json` is a JSON array of `{event, description}`. `event` is the natural-language steering string. Not posted by `deploy-managed-agent.sh`. Used as documentation + presumably console examples. Shape is **not** an API schema in this repo.

Examples of the `event` DSL (not a parser, just strings):

- `Reconcile GL vs subledger, trade date 2026-04-30, classes: equities, fixed-income, derivatives`
- `Build pitch book: target CRWD, acquirer PANW, thesis: …`
- `Process earnings: NVDA Q1-FY27`
- `Build dcf for MSFT, assumptions: {wacc: 0.085, tgr: 0.025, horizon: 5}`
- `Screen onboarding packet PKT-2026-00318`
- `Briefing pack for client C-004921, meeting cal-evt-8f2a`

Fan-out (earnings coverage list, etc.) is **orchestration-layer** work, not inside the agent.

### 15.9 Leaf `name` vs cookbook slug

Subagent `name` fields are **not** the slug. Examples: `gl-reconciler-reader`, `pitch-deck-writer`, `kyc-doc-reader`, `briefing-pack-writer`, `model-builder-builder`, `stmt-flagger`. CMA `POST /v1/agents` uses these as agent `name`. Orchestrator `name` equals the cookbook slug.

### 15.10 Script copy-identity

`deploy-managed-agent.sh` comment: `REPO_SLUG` is derived from git remote "so this script stays copy-identical across vertical repos". A Neos port that vendors this script should keep `REPO_SLUG` overridable.

### 15.11 Dependencies (no lockfile)

| Script | Needs |
|---|---|
| `check.py` | python3, pyyaml, git |
| `validate.py` | python3, jsonschema, pyyaml (if YAML schema) |
| `sync-agent-skills.py` | python3 stdlib |
| `version_bump.py` | python3 stdlib, git |
| `deploy-managed-agent.sh` | bash, jq, python3+pyyaml, curl, zip, git (for REPO_SLUG) |
| `test-cookbooks.sh` | bash, above, python3 |
| `orchestrate.py` | python3, `anthropic` SDK, jsonschema |

### 15.12 `.gitignore` (full)

OS/IDE junk, `node_modules/`, `venv/`, `__pycache__`, `dist/` `build/` `out/` `target/`, `*.log`, `.env` family, `*.key` `*.pem`, coverage, eggs, `TASKS.md`, `MEMORY.md`, `.claude/worktrees/`.

Does **not** ignore `*.local.md` despite CLAUDE.md.

---

## Appendix A — Leaf workers (complete)

| cookbook | leaf yaml | CMA `name` | Write? | Bash? | MCP | skills.path | output_schema |
|---|---|---|---|---|---|---|---|
| pitch-agent | researcher.yaml | pitch-researcher | | | capiq, daloopa | | yes |
| pitch-agent | modeler.yaml | pitch-modeler | | yes | capiq, daloopa | dcf-model, lbo-model | |
| pitch-agent | deck-writer.yaml | pitch-deck-writer | **yes** | | | xlsx-author, pptx-author, pitch-deck | |
| market-researcher | sector-reader.yaml | market-sector-reader | | | | | yes |
| market-researcher | comps-spreader.yaml | market-comps-spreader | | | capiq, factset | comps-analysis | |
| market-researcher | note-writer.yaml | market-note-writer | **yes** | | | pptx-author | |
| earnings-reviewer | transcript-reader.yaml | earnings-transcript-reader | | | | | yes |
| earnings-reviewer | model-updater.yaml | earnings-model-updater | | | factset, daloopa | model-update | |
| earnings-reviewer | note-writer.yaml | earnings-note-writer | **yes** | | | morning-note, xlsx-author | |
| meeting-prep-agent | profiler.yaml | briefing-profiler | | | crm, capiq | | |
| meeting-prep-agent | news-reader.yaml | briefing-news-reader | | | | | yes |
| meeting-prep-agent | pack-writer.yaml | briefing-pack-writer | **yes** | | | client-review, pptx-author | |
| model-builder | data-puller.yaml | model-data-puller | | | capiq, daloopa | | yes |
| model-builder | builder.yaml | model-builder-builder | **yes** | yes | | dcf, lbo, 3-statement, comps, xlsx-author | |
| model-builder | auditor.yaml | model-auditor | | | | audit-xls | |
| gl-reconciler | reader.yaml | gl-reconciler-reader | | | | | yes |
| gl-reconciler | critic.yaml | gl-reconciler-critic | | | internal-gl, subledger | | |
| gl-reconciler | resolver.yaml | gl-reconciler-resolver | **yes** | | | xlsx-author | |
| kyc-screener | doc-reader.yaml | kyc-doc-reader | | | | | yes |
| kyc-screener | rules-engine.yaml | kyc-rules-engine | | | screening | | |
| kyc-screener | escalator.yaml | kyc-escalator | **yes** | | | xlsx-author | |
| valuation-reviewer | package-reader.yaml | valuation-package-reader | | | | | yes |
| valuation-reviewer | valuation-runner.yaml | valuation-runner | | | portfolio | returns-analysis | |
| valuation-reviewer | publisher.yaml | valuation-publisher | **yes** | | | xlsx-author | |
| month-end-closer | ledger-reader.yaml | close-ledger-reader | | | | | yes |
| month-end-closer | rollforward.yaml | close-rollforward | | | internal-gl | | |
| month-end-closer | poster.yaml | close-poster | **yes** | | | xlsx-author | |
| statement-auditor | statement-reader.yaml | stmt-statement-reader | | | | | yes |
| statement-auditor | reconciler.yaml | stmt-reconciler | | | nav | | |
| statement-auditor | flagger.yaml | stmt-flagger | **yes** | | | xlsx-author | |

### Appendix B — Regexes and schemas collected

`check.py` agent-prose:

```
`([a-z0-9]+(?:-[a-z0-9]+)+)`
```

`yaml2json` env:

```
\$\{([A-Z0-9_]+)\}
SAFE = ^[A-Za-z0-9._/:@-]*$
```

`orchestrate.py` handoff:

```
\{"type":\s*"handoff_request".*?\}
```

`secret-scan.yml` internal refs:

```
\.ant\.dev|antspace\.dev|anthropic-internal|\bgo/[a-z][a-z0-9_-]+\b
```

`version_bump.py` semver: split on `.`, exactly 3 `int` parts.

SKILL.md name (`quick_validate.py`): `^[a-z0-9-]+$`, max 64, no `--`, no edge hyphen.

### Appendix C — Files read for this report

Must-read (complete):  
`scripts/{check,validate,orchestrate,sync-agent-skills,version_bump}.py`, `scripts/{deploy-managed-agent,test-cookbooks}.sh`, `.claude-plugin/marketplace.json`, `CLAUDE.md`, `README.md`, `managed-agent-cookbooks/README.md`, `.github/workflows/{plugin-validate,version-bump,secret-scan}.yml`, `.githooks/pre-commit`, `.gitignore`, `LICENSE` (Apache 2.0 noted).

All 10 `managed-agent-cookbooks/*/agent.yaml` + all 30 `subagents/*.yaml` + all 10 `README.md` + all 10 `steering-examples.json`.

All 19 `plugin.json`. Sampled hooks.json (all `{"hooks": {}}`), all `.mcp.json`, all 10 `agents/<slug>.md` frontmatter, skill-creator SKILL.md + `quick_validate.py`.

**ABSENT files named in docs:** `mcp-categories.json`, `claude-for-financial-advisors/`, `plugins/vertical-plugins/wealth-management/`.
