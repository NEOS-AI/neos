# 04. Vertical Plugin: `financial-analysis`

Canonical source: `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/`

This plugin is the core modeling vertical for DCF, comps, LBO, 3-statement models, competitive analysis, and deck QC. Author is `Anthropic FSI`. Version `0.1.1`.

---

## 1. Plugin 메타데이터 (`plugin.json`)

Path: `.claude-plugin/plugin.json`

```json
{
  "name": "financial-analysis",
  "version": "0.1.1",
  "description": "Core financial modeling and analysis tools: DCF, comps, LBO, 3-statement models, competitive analysis, and deck QC",
  "author": {
    "name": "Anthropic FSI"
  }
}
```

### Discovery flags (observed)

The file contains **only** `name`, `version`, `description`, `author.name`. There are **no**:

- `user-invocable` / `userInvocable`
- `keywords`
- `commands` listing
- `mcpServers` (those live in `.mcp.json`)
- `allowed-tools`
- marketplace / disable flags

Skill discovery therefore relies on SKILL.md YAML `name` + `description` (the only fields Claude reads to decide when a skill is used, per `skill-creator`).

---

## 2. 디렉터리 인벤토리

Actual tree (every file under the plugin; `find` listing):

```
financial-analysis/
├── .claude-plugin/plugin.json
├── .mcp.json                          # INVALID JSON (see §4)
├── hooks/hooks.json                   # empty
├── commands/
│   ├── 3-statement-model.md
│   ├── competitive-analysis.md
│   ├── comps.md
│   ├── dcf.md
│   ├── debug-model.md
│   ├── lbo.md
│   └── ppt-template.md
└── skills/
    ├── 3-statement-model/
    │   ├── SKILL.md
    │   └── references/{formatting,formulas,sec-filings}.md
    ├── audit-xls/SKILL.md
    ├── clean-data-xls/SKILL.md
    ├── competitive-analysis/
    │   ├── SKILL.md
    │   └── references/{frameworks,schemas}.md
    ├── comps-analysis/SKILL.md        # references examples/comps_example.xlsx — FILE ABSENT
    ├── dcf-model/
    │   ├── SKILL.md
    │   ├── TROUBLESHOOTING.md
    │   ├── requirements.txt
    │   └── scripts/validate_dcf.py
    ├── deck-refresh/SKILL.md
    ├── ib-check-deck/
    │   ├── SKILL.md
    │   ├── references/{ib-terminology,report-format}.md
    │   └── scripts/extract_numbers.py
    ├── lbo-model/SKILL.md             # references examples/LBO_Model.xlsx — FILE ABSENT
    ├── ppt-template-creator/SKILL.md
    ├── pptx-author/SKILL.md
    ├── skill-creator/
    │   ├── SKILL.md
    │   ├── LICENSE.txt                # Apache License 2.0
    │   ├── references/{output-patterns,workflows}.md
    │   └── scripts/{init_skill,package_skill,quick_validate}.py
    └── xlsx-author/SKILL.md
```

**13 skills.** Expected list all exist. No extra skills.

**Referenced but missing:**

- `comps-analysis` cites `examples/comps_example.xlsx` — no `examples/` directory exists.
- `lbo-model` cites `examples/LBO_Model.xlsx` and `/mnt/skills/public/xlsx/recalc.py` — neither is inside this plugin.

---

## 3. Slash commands → skills 매핑

Commands live in `commands/*.md`. Filename (minus `.md`) is the slash command.

| Command | Frontmatter | Loads | Notes |
|---|---|---|---|
| `/3-statement-model` | `description`, `argument-hint: "[path to template file]"` | `3-statement-model` | Populate IS/BS/CF template. Ask for template if no path. |
| `/competitive-analysis` | `description`, `argument-hint: "[company or industry]"` | `competitive-analysis` | Ask if no company/industry. |
| `/comps` | `description`, `argument-hint: "[company name or ticker]"` | `comps-analysis` | Full comps workflow inlined in the command as well as the skill. |
| `/dcf` | `description`, `argument-hint: "[company name or ticker]"` | **`comps-analysis` then `dcf-model`** | Orchestrated two-skill pipeline. |
| `/debug-model` | `description`, `argument-hint: "[path to .xlsx model file]"` | `audit-xls` with scope **model** | Full model-integrity audit. |
| `/lbo` | `description`, `argument-hint: "[company name or deal details]"` | `lbo-model` | Ask for target + deal params if missing. |
| `/ppt-template` | `description`, `argument-hint`, **`allowed-tools: ["Read","Write","Bash","Glob"]`** | `ppt-template-creator` | Only command with `allowed-tools`. |

Skills **without** a dedicated slash command (trigger via description only):

- `audit-xls` (also via `/debug-model`)
- `clean-data-xls`
- `deck-refresh`
- `ib-check-deck`
- `pptx-author`
- `xlsx-author`
- `skill-creator`

No command has `user-invocable`. No skill SKILL.md has `allowed-tools` or `user-invocable`.

### `/dcf` orchestration (command-level, not skill-level)

The DCF command is the only multi-skill command. Sequence:

1. Gather company / ticker.
2. Load `comps-analysis`: 4–6 peers, operating metrics, valuation multiples, Max/75th/Median/25th/Min.
3. Capture comps outputs into DCF inputs:

| Comps output | DCF input |
|---|---|
| Peer median EV/EBITDA | Terminal exit multiple range |
| Peer 25th–75th EV/EBITDA | Sensitivity analysis range |
| Peer median growth rate | Revenue assumption benchmark |
| Peer median EBITDA margin | Terminal-year target margin |
| Peer median P/E | Cross-check implied P/E |

4. Load `dcf-model`: historicals, Bear/Base/Bull, OpEx/FCF, CAPM WACC, discount + TV, equity bridge.
5. Cross-check: implied EV/EBITDA vs peer median; implied P/E vs peer median; TV as % of EV (should be 50–70%); implied growth vs peers.
6. Deliver: comps `.xlsx` + DCF `.xlsx` (scenarios + sensitivity + valuation summary) + narrative.

Example summary block in the command (illustrative numbers are in the command text, not live data):

```
VALUATION SUMMARY: [Company] ([Ticker])
Comparable Companies Analysis:
- Median EV/EBITDA: 12.5x (range: 10.2x - 15.8x)
DCF Valuation (Base Case):
- Implied Share Price / Current Price / Implied Upside
Valuation Cross-Check:
- DCF Implied EV/EBITDA: 13.2x (vs peer median 12.5x)
- Terminal Value: 62% of EV (within normal range)
```

---

## 4. MCP 허브 (`.mcp.json`) — central connector list

This file is described as the central MCP hub. It lists HTTP MCP servers only. **No auth fields, no tool catalogs, no headers, no env vars.**

### JSON is invalid

`python3 json.load` fails:

```
JSONDecodeError: Expecting ',' delimiter: line 47 column 5 (char 1100)
```

Cause: missing comma after the `egnyte` object, before `"box"`. Also the root object is missing a final closing `}` (file ends at the `mcpServers` close). Observed raw tail:

```
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

Connectors as written (12 entries):

| Key | type | URL |
|---|---|---|
| `daloopa` | `http` | `https://mcp.daloopa.com/server/mcp` |
| `morningstar` | `http` | `https://mcp.morningstar.com/mcp` |
| `sp-global` | `http` | `https://kfinance.kensho.com/integrations/mcp` |
| `factset` | `http` | `https://mcp.factset.com/mcp` |
| `moodys` | `http` | `https://api.moodys.com/genai-ready-data/m1/mcp` |
| `mtnewswire` | `http` | `https://vast-mcp.blueskyapi.com/mtnewswires` |
| `aiera` | `http` | `https://mcp-pub.aiera.com` |
| `lseg` | `http` | `https://api.analytics.lseg.com/lfa/mcp` |
| `pitchbook` | `http` | `https://premium.mcp.pitchbook.com/mcp` |
| `chronograph` | `http` | `https://ai.chronograph.pe/mcp` |
| `egnyte` | `http` | `https://mcp-server.egnyte.com/mcp` |
| `box` | `http` | `https://mcp.box.com` |

**Tools exposed:** not described anywhere in this plugin. Skills that mention MCP by name:

- `comps-analysis`: “If S&P Kensho MCP, FactSet MCP, or Daloopa MCP are available, use them exclusively… DO NOT use web search.”
- `dcf-model`: “MCP Servers (if configured) - Structured financial data from providers like Daloopa”; also “Web Search/Fetch” as fallback #3.
- `dcf-model` Available Data Sources: “MCP servers: If configured (Daloopa for historical financials)”.

`morningstar`, `moodys`, `mtnewswire`, `aiera`, `lseg`, `pitchbook`, `chronograph`, `egnyte`, `box` are listed in `.mcp.json` but **not referenced by any skill**.

Auth notes: **none in-repo**. No `Authorization`, OAuth, or API-key documentation.

---

## 5. Hooks (`hooks/hooks.json`)

```json
{
  "hooks": {}
}
```

No PreToolUse / PostToolUse / Stop / SessionStart / Notification hooks. Empty object.

---

## 6. 공통 규약 (Excel / PPT / 환경 / 감사)

These conventions repeat across modeling skills. Documented once here; skills add deltas.

### 6.1 Headless vs interactive (Managed Agent vs Cowork / Add-in)

| Mode | How to detect | Excel | PowerPoint |
|---|---|---|---|
| Office Add-in / Office JS | Live workbook/deck open | `Excel.run(async (context) => {...})`; write `range.formulas`; Excel recalcs natively | Edit live slides |
| Standalone / chat file | Generating `.xlsx`/`.pptx` | Python `openpyxl`; then `recalc.py` | python-pptx or regenerate slides |
| Headless managed-agent / CMA | No open Office app | **`xlsx-author`**: write `./out/<name>.xlsx` | **`pptx-author`**: write `./out/<name>.pptx` |
| Cowork plugin (live Office MCP) | `mcp__office__excel_*` / `mcp__office__powerpoint_*` available | Use those tools; **do not** use `xlsx-author` | Use those tools; **do not** use `pptx-author` |

`pptx-author` and `xlsx-author` exist **only** as the file-producing fallback for Managed Agent mode.

### 6.2 Formulas over hardcodes (non-negotiable)

Quoted from `dcf-model` / `3-statement-model` / `comps-analysis` / `lbo-model`:

- Every projection, roll-forward, linkage, subtotal, margin, multiple, discount factor, PV, and sensitivity cell **MUST** be an Excel formula — never a Python-computed number.
- openpyxl: `ws["D15"] = "=D14*(1+Assumptions!$B$5)"` is correct; `ws["D15"] = 12500` is wrong.
- Office JS: `range.formulas = [["=D14*(1+$B$8)"]]` — never `range.values` for derived cells.
- The **only** hardcoded numbers: (1) historical actuals, (2) assumption drivers, (3) current market data (price, shares, debt). Every blue input gets a cell comment with source.

### 6.3 Font color convention

| Font | Hex / RGB | Meaning |
|---|---|---|
| Blue | `#0000FF` / RGB 0,0,255 | Hardcoded inputs |
| Black | `#000000` | Formulas / calculations |
| Green | `#008000` / RGB 0,128,0 | Cross-sheet links |
| Purple | `#800080` | **LBO only**: same-tab direct links (`=B9`) with no calculation |

`audit-xls` also lists “Blue=input, black=formula, green=link — or whatever the model uses, applied consistently.”

### 6.4 Fill palette (modeling defaults; user/template overrides)

Quoted: “That’s 3 blues + 1 grey + white.” Do **not** introduce greens, yellows, oranges as fills.

| Element | Fill | Font |
|---|---|---|
| Section headers | Dark blue `#1F4E79` | White bold |
| Column headers | Light blue `#D9E1F2` | Black bold |
| Input cells | Light grey `#F2F2F2` or white | Blue font |
| Formula cells | White | Black |
| Check / key outputs | Medium blue `#BDD7EE` | Black bold |

`comps-analysis` also allows navy `#17365D` for section headers and `#D9E2F3` in its optional checklist (slight hex variance vs other skills).

### 6.5 Office JS merged-cell pitfall (all Excel builders)

Do **not** `.merge()` then set `.values` on the merged range — throws `InvalidArgument` because the range still reports pre-merge dimensions. Write the top-left cell first, then merge + format:

```js
ws.getRange("A7").values = [["MARKET DATA & KEY INPUTS"]];
const hdr = ws.getRange("A7:H7");
hdr.merge();
hdr.format.fill.color = "#1F4E79";
```

### 6.6 Sensitivity tables (DCF + LBO)

- **Odd dimensions** (5×5 or 7×7) so there is a true center cell.
- Center cell = base case. Axis: `[base-2Δ, base-Δ, base, base+Δ, base+2Δ]`.
- Center cell output **must equal** the model’s actual output (share price or IRR/MOIC). Highlight `#BDD7EE` + bold.
- **Not** Excel Data Table (`Data → What-If Analysis → Data Table`). Write explicit formulas (openpyxl/Office JS loops). DCF requires 3 tables × 25 cells = **75 formulas**.
- No linear approximations, no placeholder “use Data Table” notes.

### 6.7 Recalc / delivery gate

Standalone `.xlsx` delivery requires:

```bash
python recalc.py model.xlsx 30
```

(`dcf-model` cites `python recalc.py [path] [timeout_seconds]`; `lbo-model` cites `python /mnt/skills/public/xlsx/recalc.py model.xlsx`.) Zero `#REF!` / `#DIV/0!` / `#VALUE!` / `#NAME?` / `#NULL!` / `#NUM!` / `#N/A`. `recalc.py` itself is **not** in this plugin — it is attributed to the external `xlsx` skill.

### 6.8 Step-by-step user verification

Modeling skills forbid end-to-end silent builds. Confirm after each major section (historicals → IS → BS → CF; or Sources & Uses → Operating → Debt → Returns → Sensitivity; or comps structure → inputs → operating formulas → multiples).

### 6.9 PPT conventions (competitive / deck skills)

- Slide titles are **insights**, not labels.
- Typography: titles 28–32pt bold; section headers 18–20pt bold; body/table/sources **never below 14pt**.
- 2–3 colors max (navy, gray, one accent).
- Charts are real chart objects, not tables dressed as charts.
- Every number has a citation: `[Company] [Document] ([Date])`.

---

## 7. Skill-by-skill

Frontmatter fields actually present: `name` + `description` on all 13. Extra: `skill-creator` has `license: Complete terms in LICENSE.txt`. No skill sets `allowed-tools` or `user-invocable`.

---

### 7.1 `comps-analysis`

**Frontmatter**

- `name: comps-analysis`
- `description`: institutional-grade comps in Excel. Perfect for public valuation, peer benchmarking, IPO/funding pricing, outlier identification, IC decks, sector overviews. **Not ideal for:** private companies without public peers, diversified conglomerates, distressed/bankrupt, pre-revenue startups, unique business models.

**When it triggers**

Description-driven: public comps / peer multiples / sector benchmarking. Also loaded by `/comps` and as Step 2 of `/dcf`.

**Data source priority (READ FIRST in SKILL.md)**

1. FIRST: MCP — S&P Kensho, FactSet, Daloopa — use exclusively if available.
2. Do **not** web-search if those MCPs exist.
3. Only if MCPs unavailable: Bloomberg Terminal, SEC EDGAR, other institutional sources.
4. **NEVER** use web search as a primary data source.

**Workflow**

1. Ask: preferred format? audience (IC/board/quick ref)? key question (valuation/growth/positioning/efficiency)? context (M&A/investment/sector/performance)?
2. Header block (rows 1–3): title, company list with tickers, as-of date + units.
3. Operating statistics: Company, Revenue, Growth, Gross Profit, Gross Margin, EBITDA, EBITDA Margin. Optional industry metrics.
4. Statistics after a blank row: `MAX`, `QUARTILE(...,3)`, `MEDIAN`, `QUARTILE(...,1)`, `MIN`. Stats on **ratios/margins/multiples**, not on size metrics (Revenue, EBITDA $, Mkt Cap, EV).
5. Valuation multiples must **cross-reference** operating cells (never re-input revenue).
6. Notes & methodology: sources, EBITDA definition, EV build, thesis.
7. Output checklist before delivery.

**Input / output**

- In: company/ticker, optional template, audience, question, MCP or institutional data.
- Out: `.xlsx` comps sheet. Command also requires a narrative: peer rationale, premium/discount insights, median multiples.

**Scripts / references**

None in-plugin. Cites `examples/comps_example.xlsx` which **does not exist**.

**Formulas**

```excel
Gross Margin (F7): =E7/C7
EBITDA Margin (H7): =G7/C7
EV/Revenue: =[Enterprise Value]/[LTM Revenue]
EV/EBITDA: =[Enterprise Value]/[LTM EBITDA]
P/E: =[Market Cap]/[Net Income]
Rule of 40: =[Growth %]+[FCF Margin %]
Maximum: =MAX(B7:B9)
75th: =QUARTILE(B7:B9,3)
Median: =MEDIAN(B7:B9)
25th: =QUARTILE(B7:B9,1)
Minimum: =MIN(B7:B9)
```

**Excel conventions**

- Default font Times New Roman 11pt data / 12pt headers (optional; user template wins).
- No borders (comps specifically: “clean, minimal”).
- Uniform column widths; consistent row heights (20–25pt).
- Metrics center-aligned.
- Percentages 1 decimal; multiples 1 decimal (`13.5x`); dollars no decimals with thousands separator.
- Blue inputs with comments; hyperlinks to SEC/source when possible.

**Industry extras (skill + `/comps` command)**

| Industry | Additional metrics |
|---|---|
| Software/SaaS | ARR, NDR, Rule of 40, CAC Payback |
| Retail / E-commerce | SSS, inventory turns; GMV, take rate, active buyers |
| Financials | ROE, ROA, Efficiency Ratio; skip Gross Margin/EBITDA for banks |
| Manufacturing | Asset turnover, CapEx/Revenue, backlog |
| Healthcare | R&D/Revenue, pipeline value |

**5–10 rule:** 5 operating + 5 valuation = 10 columns. More than 15 is noise.

**Safety / audit**

- Cell comments on **all** hardcoded inputs (source citation **or** assumption explanation).
- Sanity: Gross margin > EBITDA margin > Net margin; EV/Rev typically 0.5–20x; EV/EBITDA 8–25x; P/E 10–50x.
- Red flags: mixed quarterly/annual; >10% source variance; negative EBITDA on EV/EBITDA; P/E >100x without hypergrowth; mixing pure-plays and conglomerates. “When in doubt, exclude.”
- Better 3 perfect comps than 6 questionable. Command quality checklist also requires 4–6 truly comparable companies.

**Headless vs interactive:** Office JS in Excel add-in; openpyxl for standalone `.xlsx`.

---

### 7.2 `dcf-model`

**Frontmatter**

- `name: dcf-model`
- `description`: Real DCF for equity valuation. SEC filings + analyst reports, cash flow projections, WACC, sensitivity, professional Excel + executive summaries. Triggers: value a company with DCF, intrinsic value, growth projections + terminal value.

**When it triggers**

`/dcf` (after comps) or direct “DCF / intrinsic value / WACC / terminal value” requests.

**Input contract (minimum)**

1. Company identifier (ticker or name).
2. Growth assumptions for projection period (or “use consensus”).
3. Optional: projection period (default 5 years); Bear/Base/Bull; terminal g (default 2.5–3.0%); specific WACC inputs if not CAPM.

**Output contract**

- File: `[Ticker]_DCF_Model_[Date].xlsx`
- Two sheets: **`DCF`** (model + three sensitivity tables at **bottom of DCF sheet**, not a separate sheet) and **`WACC`**.
- `validate_dcf.py` additionally recommends a `Sensitivity` sheet name — **mismatch** with SKILL.md (see script section).

**Workflow (10 steps)**

**Step 1 — Data retrieval.** Priority: (1) MCP (Daloopa etc.), (2) user-provided, (3) web search/fetch for prices, beta, debt/cash. Validate net debt vs net cash, diluted shares, historical margins, growth vs industry, tax 21–28%.

**Step 2 — Historicals (3–5 years):** revenue CAGR, margin progression, D&A/CapEx % rev, NWC efficiency, ROIC/ROE.

**Step 3 — Revenue projections**

```
Revenue(Year N) = Revenue(Year N-1) × (1 + Growth Rate)
Growth %(Year N) = Revenue(Year N) / Revenue(Year N-1) - 1
Bear ~8–12%, Base ~12–16%, Bull ~16–20% (illustrative)
Y1–2 higher; Y3–4 moderate toward industry; Y5+ toward terminal g
```

**Step 4 — OpEx.** Percentages of **REVENUE**, not gross profit. S&M 15–40%, R&D 10–30% (tech), G&A 8–15% with leverage. `EBIT = Gross Profit - Total OpEx`.

**Step 5 — Unlevered FCF**

```
EBIT
(-) Taxes (EBIT × Tax Rate)
= NOPAT
(+) D&A (% of revenue)
(-) CapEx (% of revenue, typically 4–8%; maintenance ~2–3% + growth 2–5%)
(-) Δ NWC (% of Δ revenue; typical -2% to +2%)
= Unlevered Free Cash Flow
```

**Step 6 — WACC (CAPM)**

```
Cost of Equity = Risk-Free Rate + Beta × Equity Risk Premium
  Rf = current 10-Year Treasury
  Beta = 5-year monthly vs market
  ERP = 5.0–6.0%

After-Tax Cost of Debt = Pre-Tax Cost of Debt × (1 - Tax Rate)

Market Value Equity = Price × Shares
Net Debt = Total Debt - Cash
Enterprise Value = Market Cap + Net Debt
Equity Weight = Market Cap / EV
Debt Weight = Net Debt / EV
WACC = (Cost of Equity × Equity Weight) + (After-Tax Cost of Debt × Debt Weight)
```

Special cases: net cash → negative net debt / possibly negative debt weight; no debt → WACC = Cost of Equity.

Typical WACC: large-cap stable 7–9%; growth 9–12%; high growth/risk 12–15%.

**Step 7 — Discount (mid-year convention)**

```
Periods: 0.5, 1.5, 2.5, 3.5, 4.5, ...
Discount Factor = 1 / (1 + WACC)^Period
PV of FCF = Unlevered FCF × Discount Factor
Example: FCF $1,000, WACC 10%, Period 0.5 → DF = 1/(1.10)^0.5 = 0.9535 → PV $954
Projection: 5 years standard; 7–10 high growth; 3 mature.
```

**Step 8 — Terminal value**

Perpetuity (preferred):

```
Terminal FCF = Final Year FCF × (1 + Terminal Growth Rate)
Terminal Value = Terminal FCF / (WACC - Terminal Growth Rate)
Critical: Terminal Growth < WACC (otherwise infinite value)
Do not exceed Rf or long-term GDP.
Conservative g 2.0–2.5%; moderate 2.5–3.5%; aggressive 3.5–5.0% market leaders only.
```

Exit multiple alternative: `TV = Final Year EBITDA × Exit Multiple` (comps / precedents; typical 8–15x).

```
PV of TV = Terminal Value / (1 + WACC)^Final Period
5-year mid-year: Period = 4.5
Sanity: TV should be 50–70% of EV; >75% over-reliant; <40% too conservative.
```

**Step 9 — EV → equity bridge**

```
(+) Sum of PV of Projected FCFs
(+) PV of Terminal Value
= Enterprise Value
(-) Net Debt  [or + Net Cash if negative]
= Equity Value
÷ Diluted Shares
= Implied Price per Share
Implied Return = (Implied Price / Current Price) - 1
```

Adjustments if applicable: minority interests, pension, operating leases. Use diluted shares (options, RSUs, converts).

**Step 10 — Three sensitivity tables** at bottom of DCF sheet (rows 87+ as specified):

1. WACC vs Terminal Growth
2. Revenue Growth vs EBIT Margin
3. Beta vs Risk-Free Rate

Each 5×5, full DCF recalc formulas, mixed refs (`$A88`, `B$87`), center = base, `#BDD7EE` highlight, green-red color scale.

**Scenario architecture**

- Case selector cell (e.g. B6): 1=Bear, 2=Base, 3=Bull.
- Separate blocks per scenario, each with **three** structural rows: merged section header, **mandatory year column headers**, data rows.
- Consolidation column via INDEX, **not** nested IFs in every projection:

```
=INDEX(B10:D10, 1, $B$6)
Revenue Year 1: =D29*(1+$E$10)   # $E$10 is consolidation
```

SKILL.md also shows an IF form in Critical Constraints (`=IF($B$6=1,[Bear],IF($B$6=2,[Base],[Bull]))`) then later **rejects** scattered IFs in favor of INDEX. The INDEX consolidation column is the stated correct pattern.

**Cell comments (as each input is created, never deferred)**

```
"Source: [System/Document], [Date], [Reference], [URL if applicable]"
```

**Layout planning:** lock all section row positions, write all headers/dividers, **then** formulas. Prevents #REF! from inserted header rows.

**Uses the external `xlsx` skill** for formula construction, number formats, `recalc.py`. Delivery gate: `python recalc.py model.xlsx 30` until `"status": "success"`.

**Number formats:** years as text (`"2024"` not `2,024`); `%` as `0.0%`; currency `$#,##0` millions / `$#,##0.00` per-share; zeros as `-` via `$#,##0;($#,##0);-`; negatives in parentheses. **Borders required** (thick 1.5pt around major sections) — unlike comps which prefers no borders.

**WACC sheet** structure (inputs called “Yellow input” in the WACC CSV sketch — this color label is **inconsistent** with the blue-input rule stated elsewhere in the same skill).

**Common mistakes (quoted TOP 5)**

1. Formula row references off → lock rows first.
2. Missing cell comments → add as created.
3. Simplified sensitivity tables → 75 full-recalc formulas.
4. Wrong scenario block refs.
5. No borders.

Also: OpEx on gross profit (wrong); TV > WACC; book vs market weights; FCF including interest (should be unlevered); tax-shield double-count; TV not discounted.

**Variations:** high-growth tech 7–10y, 20–30% growth, WACC 12–15%; mature 3–5y GDP+1–3%, WACC 7–9%; cyclical mid-cycle margins; multi-segment SOTP.

#### `scripts/validate_dcf.py`

Python 3 CLI. Depends on `openpyxl` (see `requirements.txt`: `openpyxl>=3.0.0`, `requests>=2.28.0` — **`requests` is unused** in this script).

**SKILL.md never names `validate_dcf.py`.** Delivery path is `recalc.py`. The validator is a sibling quality tool.

Usage:

```
python validate_dcf.py <excel_file> [output.json]
```

Exit 0 if `status == PASS` (zero errors), 1 if FAIL or exception.

Class `DCFModelValidator`:

1. Loads workbook twice: `data_only=False` (formulas) and `data_only=True` (cached values).
2. `check_sheet_structure()`: recommended sheets `['DCF', 'WACC', 'Sensitivity']`. Missing → **warning**, not error. **Conflicts with SKILL.md**, which puts sensitivity at the bottom of `DCF` and does **not** require a `Sensitivity` sheet.
3. `check_formula_errors()`: scans cached values for `#VALUE!`, `#DIV/0!`, `#REF!`, `#NAME?`, `#NULL!`, `#NUM!`, `#N/A`. Counts formulas (`value.startswith('=')`). Each hit is an error.
4. `check_dcf_logic()`:
   - `_check_terminal_growth_vs_wacc`: scan DCF sheet labels containing both `terminal` and `growth`, and `wacc`; take adjacent numeric 0–1. If `g >= WACC` → **CRITICAL error** (“infinite value”). If not found → warning.
   - `_check_wacc_range`: WACC sheet or DCF; if WACC `< 0.05` or `> 0.20` → warning (typical 5–20%).
   - `_check_terminal_value_proportion`: looks for labels with `terminal`+`value`+`pv` and `enterprise`+`value`. If TV/EV `> 0.80` or `< 0.40` → warning; in-range info. Typical 50–70%.

Heuristic limitation: values must be 0 < x < 1 for WACC/g (so 9 written as 9 not 0.09 will be missed). Label matching is English-substring based.

JSON result: `file`, `validation_date`, `status` PASS/FAIL, counts, `errors`, `warnings`, `info`. Exception path: `status: ERROR`.

#### `TROUBLESHOOTING.md`

Read when recalc.py errors, valuation unreasonable, or case selector broken.

| Symptom | Guidance |
|---|---|
| `#REF!` | Headers inserted after formulas; rebuild with locked rows |
| `#DIV/0!` | `=IF([Divisor]=0,0,[Numerator]/[Divisor])` |
| `#VALUE!` | Text in numeric calc |
| Price too high | TV >80% EV; g ≥ WACC; optimistic growth/margins |
| Price too low | Net debt vs net cash; WACC too high; conservative projections; g too low |
| Case selector dead | Selector must be 1/2/3; INDEX/OFFSET ranges; `$B$6` absolute |

#### `requirements.txt`

```
openpyxl>=3.0.0
requests>=2.28.0
```

---

### 7.3 `lbo-model`

**Frontmatter**

- `name: lbo-model`
- `description`: complete LBO model **templates** in Excel for PE transactions, deal materials, IC. Fills formulas, validates, professional formatting that adapts to any template.

**When it triggers**

`/lbo` or PE/LBO/returns/Sources & Uses requests.

**Template requirement (first instruction)**

1. If a template is attached: **use it exactly**. Never build from scratch when a file is provided.
2. If none: ask *“Do you have a specific LBO template you’d like me to use? If not, I can use the standard template which includes Sources & Uses, Operating Model, Debt Schedule, and Returns Analysis.”*
3. Standard template path: copy `examples/LBO_Model.xlsx` — **this file is not in the plugin**.

**Workflow**

1. Template analysis: map sections, timeline (Closing / Pro Forma vs projection), input vs formula cells, labels, existing formulas, sign convention.
2. Clarify assumptions before filling.
3. Per-cell hierarchy: template formula/comment/neighbors → user instructions → standard LBO practice (document assumptions; ask if uncertain).
4. Section-by-section checkpoints with user sign-off:
   - After Sources & Uses (plug, balance)
   - After Operating Model / P&L
   - After Debt Schedule (waterfall)
   - After Returns (IRR/MOIC signs and ranges)
   - After Sensitivity (center = base, each cell varies)

**Problem areas (quoted)**

- Balancing: one item is the **plug**.
- Tax: only income line × tax rate; do not pull debt schedule into tax.
- Interest circularity: use **Beginning Balance** to break Interest → CF → Paydown → Ending.
- Debt paydown / cash sweep: tranche priority; `MAX`/`MIN` so balances cannot go negative.
- Returns: investment negative, proceeds positive; XIRR needs dates; `MOIC = Total Proceeds / Total Investment`.
- Sensitivity: odd grid, mixed refs `$A5` / `B$4`; Excel DATA TABLE may not work with openpyxl.

**Input / output**

- In: company/deal params + template (user or `examples/LBO_Model.xlsx`).
- Out: populated LBO workbook; `recalc.py` must succeed with zero errors.

**Color (LBO-specific purple)**

Blue `#0000FF` inputs; black formulas with operators; purple `#800080` same-tab links; green `#008000` cross-tab. Number formats: `$#,##0;($#,##0);"-"`, `0.0%`, `0.0"x"`, MOIC `0.00"x"`; all numeric right-aligned.

**Safety / audit checklist**

Sources=Uses; BS Assets=L+E with check row zero; CF ending cash; debt ending ≥ 0; interest on beginning; IRR range complete; sensitivity center equals model IRR/MOIC; no error values.

**Headless vs interactive:** Office JS in add-in (no Python); openpyxl + `recalc.py` for standalone.

---

### 7.4 `3-statement-model`

**Frontmatter**

- `name: 3-statement-model`
- `description`: complete/populate 3-statement **templates** (IS, BS, CF). Triggers: fill/complete/populate a 3-statement template, link integrated statements in an existing framework.

**When it triggers**

`/3-statement-model` or template-population language. This skill **fills templates**; it does not claim to invent a model from a blank workbook.

**Workflow (verify with user at each break)**

1. After mapping tabs/sections → confirm before edits.
2. After historicals → confirm values/periods.
3. After IS projections → subtotal checks, confirm before BS.
4. After BS → Assets = L+E every period, confirm before CF.
5. After CF → cash tie-out, confirm before finalize.
6. **Do not** populate end-to-end then present complete.

**Tab discovery table:** IS/P&L, BS, CF/CFS, WC, DA/PP&E, Debt, NOL/Tax/DTA, Assumptions/Inputs/Drivers, Checks/Audit/Validation.

Projection typically 5 years; labels `FY2024A` vs `FY2025E`.

**Margin analysis and Credit metrics** — **only if user prompts or template requires**; otherwise skip.

Margins: Gross, EBITDA, EBIT, NI — each % under the profit line.

Credit: Total Debt/EBITDA, Net Debt/EBITDA, Interest Coverage, Debt/Total Cap, Debt/Equity, Current Ratio, Quick Ratio. Hierarchy: Upside leverage < Base < Downside; coverage/liquidity inverted. Covenant checks if known.

**Scenarios:** dropdown on Assumptions with `CHOOSE` or `INDEX/MATCH`. Drivers: revenue growth, GM, SG&A %, DSO/DIO/DPO, CapEx %, interest, tax. Audit: all statements switch; BS balances; cash ties; Upside > Base > Downside for NI, EBITDA, FCF, margins.

**NOL (post-2017):** utilization ≤ 80% of EBT; beginning NOL Year 1 = 0 for new business; tax expense = 0 when taxable income ≤ 0; DTA = ending NOL × tax rate.

**Circular interest:** File → Options → Formulas → Enable iterative calculation; max iterations 100, max change 0.001; circuit-breaker toggle on Assumptions.

**Master check:** all sections pass → `"✓ ALL CHECKS PASS"` else `"✗ ERRORS DETECTED - REVIEW BELOW"`.

**Input / output:** template path + source data (user or SEC). Output: populated linked model with Checks tab.

**References**

- `references/formulas.md` — always, unless user specifies otherwise.
- `references/formatting.md` — palette, bold totals, BS check number format, credit threshold colors.
- `references/sec-filings.md` — **only** when template requires 10-K/10-Q pull.

#### `references/formulas.md` (core identities)

```
Balance Sheet:        Assets = Liabilities + Equity
Net Income:           IS Net Income → CF Operations (starting point)
Cash Flow:            ΔCash = CFO + CFI + CFF
Cash Tie-Out:         Ending Cash (CF) = Cash (BS Asset)
Retained Earnings:    Prior RE + Net Income - Dividends = Ending RE
                      (skill body also uses Prior RE + NI + SBC - Dividends)
Equity Raise:         ΔCommon Stock/APIC (BS) = Equity Issuance (CFF)
Year 0 Equity:        Equity Raised (Year 0) = Beginning Equity (Year 1)

Gross Profit MUST be from Net Revenue, not Gross Revenue:
Net Revenue - Cost of Revenue = Gross Profit
```

Forecast % of Net Revenue: COGS, S&M, G&A, R&D, SBC.

WC: DSO = (AR/Revenue)×365; DIO = (Inventory/COGS)×365; DPO = (AP/COGS)×365; NWC = AR + Inventory − AP.

Debt interest: `Avg Debt × Rate` with note to use beginning balance to avoid circularity.

NOL:

```
If EBT > 0:
  Utilization Limit = EBT × 80%
  NOL Utilized = MIN(NOL Available, Utilization Limit)
  Taxable Income = EBT - NOL Utilized
If EBT ≤ 0:
  NOL Utilized = 0; Taxable Income = 0; NOL Generated = ABS(EBT)
Taxes Payable = MAX(0, Taxable Income × Tax Rate)
DTA = Ending NOL × Tax Rate
```

Sign convention (skill body):

| Statement | Item | Sign |
|---|---|---|
| CFO | D&A, SBC | Positive add-back |
| CFO | ΔAR increase | Negative (use) |
| CFO | ΔAP increase | Positive (source) |
| CFI | CapEx | Negative |
| CFF | Debt issuance / repayments | + / − |
| CFF | Dividends | Negative |

#### `references/formatting.md`

Blue/black/green fonts; check cells red if error, green if balanced; negatives in parentheses; currency no decimals for large figures, 2 dp per-share; % 1 decimal.

BS check custom format: `[Red][<>0]0.00;[Red][<>0](0.00);0.00`.

Credit thresholds:

| Metric | Green | Yellow | Red |
|---|---|---|---|
| Total Debt / EBITDA | < 2.5x | 2.5x–4.0x | > 4.0x |
| Net Debt / EBITDA | < 2.0x | 2.0x–3.5x | > 3.5x |
| Interest Coverage | > 4.0x | 2.5x–4.0x | < 2.5x |
| Debt / Total Cap | < 40% | 40%–60% | > 60% |
| Current Ratio | > 1.5x | 1.0x–1.5x | < 1.0x |
| Quick Ratio | > 1.0x | 0.75x–1.0x | < 0.75x |

Margin flags: GM < 0% ERROR; GM > 80% WARNING; EBITDA < 0 FLAG; EBITDA > 50% WARNING; Net < 0 FLAG (may be OK in growth); Net > Gross → ERROR (formula).

#### `references/sec-filings.md`

EDGAR: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=[TICKER]&type=10-K` (10-Q: `type=10-Q`). Identify currency from cover/Note 1. 10-K Item 8 / 10-Q Item 1. Map filing lines to model lines (Revenue, COGS, SG&A, D&A, Interest, Tax, NI; Cash, AR, Inventory, PP&E, AP, ST/LT debt, RE, Equity; CF NI, D&A, ΔAR/Inv/AP, CapEx, equity issuance, debt, dividends). Notes: Debt, PP&E, Revenue segments, Leases. Historicals: 3 years IS/CF; 10-K gives 2 years BS so prior 10-K for year 3. Verify IS NI = CF NI and BS Cash = CF ending cash each year. Variations: D&A in COGS/SG&A → pull D&A from CF; restatements use restated figures; FY ≠ calendar → label FYE.

**Safety:** only edit input cells; never overwrite formulas; match template units and sign convention; temporary #REF!/#DIV/0! until inputs complete; never delete rows/columns without tracing dependents.

---

### 7.5 `audit-xls`

**Frontmatter**

- `name: audit-xls`
- `description`: audit spreadsheet for formula accuracy/errors. Scopes: selected range, sheet, or entire model (BS balance, cash tie-out, logic sanity). Triggers: “audit this sheet”, “check my formulas”, “find formula errors”, “QA this spreadsheet”, “sanity check this”, “debug model”, “model check”, “model won't balance”, “something's off in my model”, “model review”.

**When it triggers**

Those phrases, plus `/debug-model` which **forces scope = model**.

**Workflow**

1. If user did not give scope, **ask**: selection / sheet / model. Model is deepest — for DCF, LBO, 3-statement, merger, comps, any integrated model before client/IC.
2. Formula-level checks (all scopes): `#REF!` `#VALUE!` `#N/A` `#DIV/0!` `#NAME?`; hardcodes inside formulas (`=A1*1.05`); inconsistent neighbor formulas; off-by-one SUM/AVERAGE; pasted-over formulas; circular refs; broken cross-sheet links; unit/scale mismatches; hidden rows/tabs (overrides/stale calcs).
3. Model-integrity (model scope only): identify type DCF/LBO/3-statement/merger/comps/custom.

Structural: input/formula separation; color convention; tab flow Assumptions → IS → BS → CF → Valuation; date headers; units.

BS: Assets = L+E every period; RE rollforward Prior RE + NI − Dividends = Current RE; goodwill from deal (M&A). **If BS doesn't balance, quantify the gap per period and trace — nothing else matters until fixed.**

CF: ending cash = BS cash; CFO+CFI+CFF = Δ Cash; D&A CF = D&A IS; CapEx vs PP&E rollforward; WC signs.

IS: revenue vs segment; Tax = Pretax × rate (allow deferred); share count vs dilution schedule.

Circularity: Interest → debt → cash → interest is common intentional circ in LBO/3-stmt; verify iteration toggle if intentional.

Logic flags: revenue growth >100% unexplained; margins outside industry; TV > ~75% of DCF EV (yellow); hockey-stick; EBITDA compounding absurd by Y10; breaks at 0%/negative growth, negative EBITDA, negative leverage.

**Model-type-specific bugs**

DCF: mid-year vs end-of-year discount on wrong period; TV not discounted; WACC on book not market; FCF includes interest (should be unlevered); tax shield double-counted.

LBO: debt paydown ≠ cash sweep; PIK not accruing; management rollover missing from returns; exit multiple on wrong EBITDA (LTM vs NTM); fees not deducted from Day-1 equity.

Merger: accretion/dilution wrong share count; synergies not phased; PPA doesn’t balance; foregone interest on cash missing; fees not in S&U.

3-statement: WC wrong sign; D&A ≠ PP&E schedule; debt maturity ≠ principal; dividends > NI unexplained.

**Output:** findings table `# | Sheet | Cell/Range | Severity | Category | Issue | Suggested Fix`. Severity: **Critical** (wrong output / BS / cash / broken formula), **Warning** (hardcodes, inconsistent formulas, edge cases), **Info** (style). Model scope prepends: `Model type: [...] — Overall: [Clean / Minor Issues / Major Issues] — [N] critical, [N] warnings, [N] info`.

**Safety:** **Don't change anything without asking — report first, fix on request.** Notes: BS balance first; hardcoded overrides are #1 silent-bug source; sign convention errors extremely common; VBA macros flagged as unauditable from formulas alone.

No scripts.

---

### 7.6 `clean-data-xls`

**Frontmatter**

- `name: clean-data-xls`
- `description`: trim whitespace, fix casing, numbers-stored-as-text, standardize dates, remove duplicates, flag mixed-type columns. Triggers: “clean this data”, “clean up this sheet”, “normalize this data”, “fix formatting”, “dedupe”, “standardize this column”, “this data is messy”.

**When it triggers:** those phrases; pre-analysis prep.

**Workflow**

1. Scope: given range or full used range of active sheet; profile each column’s dominant type.
2. Detect: whitespace, casing, number-as-text (`$`, `,`, `%`), mixed dates, exact and near duplicates, blanks, mixed types, mojibake/non-printing, Excel errors.
3. **Propose** summary table (Column / Issue / Count / Proposed Fix) **before changing anything**.
4. Apply: prefer helper-column formulas (`=TRIM(A2)`, `=VALUE(SUBSTITUTE(B2,"$",""))`, `=UPPER(C2)`, `=DATEVALUE(D2)`) over in-place overwrite. Overwrite in place only if user asks or no formula equivalent (encoding repair). Destructive ops (dedupe, fill blanks, overwrite originals) require confirmation. After each category (whitespace → casing → numbers → dates → dedup) show a sample and confirm. Report before/after.

**Environment:** Office JS in add-in; openpyxl for standalone files.

No scripts / references.

---

### 7.7 `deck-refresh`

**Frontmatter**

- `name: deck-refresh`
- `description`: update presentation numbers — quarterly refreshes, earnings, comp rolls, rebased market data. Triggers: “update the deck with Q4 numbers”, “refresh the comps”, “roll this forward”, “swap in the new earnings”, “change all the $485M to $512M”, swap figures without rebuilding.

**When it triggers:** those phrases. Four-phase; **phase 3 is an approval gate**. Don’t edit until the user has seen the plan.

**Environment:** Add-in = live edits of text runs, table cells, chart data. Chat = regenerate affected slides with new values, write back. Smallest change; existing formatting stays.

**Workflow**

Phase 1 — Get data via `ask_user_question`: pasted mapping, uploaded Excel, or raw new values. Ask whether **derived** numbers (growth rates, share %) should be recalculated.

Phase 2 — Read every slide. Find every variant of each old value: scale (`$485M` / `$0.485B` / `$485,000,000`), precision, unit style (`$MM` vs `$ million`), embedded in sentences, chart axes, footnotes, speaker notes. Build the plan list.

Phase 3 — Present full change list + **FLAGGED** derived items. Approval: proceed as shown / skip flagged / revise mapping.

Phase 4 — Execute preserving font/size/color/bold; update chart **series data** not just labels; report actual vs still-flagged; visual verification (overflow if `$485M` → `$1,205M`).

**Not doing:** rebuild slides; rewrite narrative if it no longer fits (flag only); recalculate unless asked; restyle (`$MM` in deck beats `$M` in mapping).

---

### 7.8 `competitive-analysis`

**Frontmatter**

- `name: competitive-analysis`
- `description`: competitive landscape decks — positioning, competitor deep-dives, comparative analysis, strategic synthesis. Triggers: competitive landscape, competitor analysis, peer comparison, market positioning, strategic review, investment memo deck, “who are the competitors to X”, “benchmark X against peers”, “build a market map”.

**When it triggers:** those phrases + `/competitive-analysis`.

**Two-phase, outline-gated**

Phase 1 — `ask_user_question` (up to 4): scope (single protagonist vs multi-company); competitor set (use named set exactly); audience/depth; investment context (bull/base/bear signposts = Step 9, skip if strategic review). If Excel/CSV uploaded, confirm column mapping; use values exactly, don’t recalculate/re-round.

Phase 2 — Propose slide titles + one-line notes; **do not create slides until outline approved**. Taste calls (2×2 vs radar vs tier; grouping lens) via `ask_user_question`.

**Environment:** Add-in builds into live deck; chat generates `.pptx`.

**Source quality when sources conflict**

1. 10-Ks / annual reports (audited)
2. Earnings calls / investor presentations
3. Sell-side research (private company sizing)
4. Industry reports (McKinsey, Gartner)
5. News (recent only; verify against primary)

**Data comparability:** same fiscal year (flag exceptions); same metric definitions; convert to USD with FX rate+date; missing = `-` or `N/A` with `[E]` for estimates — never blank; every number cited.

**Analysis steps 0–9**

0. Industry-defining 3–5 metrics (SaaS: ARR, NRR, CAC payback, LTV/CAC, Rule of 40; Payments: GPV, take rate, attach, transaction margin; Marketplaces: GMV, take rate, buyer/seller, repeat; Retail: SSS, turns, sales/sq ft; Logistics: volume, cost/unit, on-time, utilization).
1. Market context — quantified (“Embedded payments is $80-100B in 2024, growing 20-25% CAGR (McKinsey 2024)” not “large and growing”).
2. Industry economics (value chain / platform / fragmented).
3. Target company profile table (+ segment breakdown if multi-segment).
4. Competitor mapping by model / segment / posture / origin.
5. Positioning viz (see `references/frameworks.md`).
6. Deep-dives: metrics table + qualitative (business, strengths, weaknesses, strategy).
7. Comparative dots: `●●● $160B` not just `●●●`.
8. Strategic context: M&A, partnerships, capital, regulation (`references/schemas.md` M&A table).
9. Synthesis: moat Strong/Moderate/Weak on network effects, switching costs, scale economies, intangible assets; durable advantages vs structural vulnerabilities; current vs trajectory. Investment contexts only: Bull/Base/Bear probability table.

**Prompt fidelity is strict:** exact titles; chart vs table not interchangeable; complete series; exact ratios (“surpasses DoorDash 4:1, Lyft 8:1” not “7.6x Lyft”).

**Quality checklist:** titles verbatim; charts vs tables; every listed competitor/year; source-file values not recalculated; same metric same value every slide; visual verification for overflow/overlap/contrast.

#### `references/frameworks.md`

2×2 axis pairs:

- Technology/SaaS: Product breadth × Customer segment; Integration depth × Geographic reach
- Consumer/Retail: Price point × Product range; Online × Offline
- Financial Services: Product complexity × Customer sophistication; Scale × Specialization
- Healthcare: Care setting × Payer mix; Technology enablement × Service breadth
- Industrial: Customization × Scale; Geographic scope × Vertical focus

Viz types in SKILL: 2×2, radar/spider, tier diagram, value chain map, ecosystem map.

#### `references/schemas.md`

M&A table: Acquirer | Target | Date | Deal Value | Multiple | Rationale. State methodology “X.Xx EV/Revenue” or “X.Xx EV/EBITDA”.

Scenario table: Scenario | Probability | Valuation | Key Assumptions (quantified).

Slide frame: insight headline, main content, `Source: [Citation] ([Date])`.

---

### 7.9 `ib-check-deck`

**Frontmatter**

- `name: ib-check-deck`
- `description`: IB presentation QC on (1) number consistency, (2) data-narrative alignment, (3) language polish, (4) visual/formatting. Triggers: review, check, QC, proof, final pass, “check my numbers”, “reconcile figures across slides”, “is this client-ready”, “what am I missing before I send this out”.

**When it triggers:** those phrases. **Read-and-report only — no edits.** Workflow identical in Add-in and chat.

**Workflow**

1. Extract every slide’s text with slide attribution into markdown:

```
## Slide 1
[content]
## Slide 2
[content]
```

2. Number consistency — run:

```bash
python scripts/extract_numbers.py /tmp/deck_content.md --check
```

Plus: totals sum, % add up, growth matches endpoints; unit style `$M` vs `$MM` consistent; FY vs LTM vs quarterly labeled.

3. Data-narrative: “declining margins” vs chart direction; “#1 player” vs share math (example: “#1 in a $100B market” with $200M revenue = 0.2% — not #1).
4. Language: see `references/ib-terminology.md`.
5. Visual QC: missing chart sources, axis labels, typography, `1,000` vs `1K`, date formats, footnotes/disclaimers; visual verification for overlap/overflow/contrast.

**Output:** `references/report-format.md`. Lead with criticals; if none, say “no number inconsistencies found” explicitly.

Severity: **Critical** (mismatches, factual errors, data contradicting narrative — block client delivery); **Important** (language, missing sources, terminology); **Minor** (fonts, spacing, dates).

#### `scripts/extract_numbers.py`

Parses markdown (markitdown-style). Slide markers: `^#+\s*Slide\s*(\d+)` or `^<!-- Slide (\d+)`.

Number regex: optional `[$€£¥]`, `[\d,]+(?:\.\d+)?`, optional unit `%|bps|x|Trillion|Billion|Million|Thousand|[TBMK]n?|mm|MM`.

Skip: short numbers without unit (<2 digits); years 1900–2099 without unit/currency.

Normalize multipliers: T 1e12; B/bn/billion 1e9; M/mm/mn/million 1e6; K/k/thousand 1e3.

Categories from context: `revenue`, `ebitda` / `ebitda_margin`, `margin`, `growth`, `multiple`, `valuation`, `percentage`, `other`.

`--check` groups by category, clusters values within **5%** of each other; if multiple clusters, largest is “expected”, others are inconsistencies. Severity `high` if category in `revenue`, `ebitda`, `valuation`, else `medium`. Prints to stderr; JSON to stdout or `--output`.

CLI: `python extract_numbers.py presentation-content.md [--output numbers.json] [--check]`.

#### `references/ib-terminology.md`

Casual → IB: “a lot of growth” → “significant growth” or “X% growth”; “pretty good margins” → “attractive margins” or “margins of X%”; “they bought the company” → “the company was acquired”; “big deal” → “transformative transaction”; “cheap valuation” → “attractive valuation” / “valuation discount”; “expensive” → “premium valuation”; “cut costs” → “implement cost optimization”; “good fit” → “strategic fit”. Avoid contractions, exclamation points, first-person (“We think…” → “Management believes…”), superlatives without evidence, vague quantifiers.

Preferred: “Demonstrated track record of X% revenue CAGR”; “#X player in [specific segment]”; “Synergy potential of $Xm from [specific sources]”.

#### `references/report-format.md`

Template: `# Deck Check Report: [Presentation Name]` with Summary counts, Critical (Number Consistency, Data-Narrative), Important (Language), Minor (Formatting), Final Checklist (numbers reconciled, narrative matches, IB language, charts sourced, formatting consistent).

---

### 7.10 `pptx-author` (headless / Managed Agent)

**Frontmatter**

- `name: pptx-author`
- `description`: Produce a `.pptx` on disk (headless) instead of driving a live PowerPoint document — for managed-agent sessions with no open Office app.

**When it triggers:** CMA / managed-agent / no live Office. **When NOT:** if `mcp__office__powerpoint_*` tools are available (Cowork), use those instead.

**Output contract:** write `./out/<name>.pptx` (create `./out/` if needed); return relative path for orchestration collection.

**How:** short Python script via Bash, `python-pptx`. Optional `./templates/firm-template.pptx`. Example uses `slide_layouts[5]` title-only.

**Conventions (mirror live-Office `pitch-deck` skill — that skill is not in this plugin):**

- One idea per slide; title is the takeaway.
- Every number traces to the model; if from `./out/model.xlsx`, footnote sheet and cell.
- Use firm template when mounted at `./templates/`.
- Charts: prefer PNG rendered from the model over native pptx charts when fidelity matters.
- **No external sends.** Writes a file; never emails or uploads.

---

### 7.11 `xlsx-author` (headless / Managed Agent)

**Frontmatter**

- `name: xlsx-author`
- `description`: Produce a `.xlsx` on disk (headless) instead of driving a live Excel workbook — for managed-agent sessions with no open Office app.

**When NOT:** if `mcp__office__excel_*` available (Cowork), use those.

**Output contract:** `./out/<name>.xlsx`; return relative path.

**How:** Python `openpyxl` via Bash. Example: Inputs sheet blue hardcoded revenue; DCF sheet formula `=Inputs!C2*(1+Inputs!C3)`.

**Conventions (mirror `audit-xls`):**

- Blue / black / green.
- No hardcodes in calc cells; inputs on an Inputs tab.
- Named ranges for values referenced from a deck or memo.
- Checks tab: BS balances, CF ties, TRUE/FALSE.
- One model per file; do not append unless asked.

---

### 7.12 `ppt-template-creator`

**Frontmatter**

- `name: ppt-template-creator`
- `description`: Creates self-contained PPT **template SKILLS (not presentations)** from user-provided PowerPoint templates. Use ONLY when the user wants a reusable skill from their template. For actual presentations, use the `pptx` skill instead.

**When it triggers:** `/ppt-template` (allowed-tools Read/Write/Bash/Glob) or explicit “turn this .pptx/.potx into a skill”.

**Workflow**

1. User provides `.pptx` or `.potx`.
2. Analyze layouts/placeholders/dimensions with `python-pptx` (`slide_width/914400` inches). **Critical:** extract exact placeholder x,y,w,h. True content start is OBJECT placeholder type `7` `y`, **not** subtitle end (gap may be a reserved border).
3. Initialize skill via `skill-creator`.
4. Copy template to `assets/template.pptx`.
5. Write self-contained `SKILL.md` from the embedded template (no reference back to this meta-skill).
6. Generate example presentation to validate.
7. Package with `skill-creator` into `.skill`.

Generated skill structure:

```
[company]-ppt-template/
├── SKILL.md
└── assets/template.pptx
```

Generated SKILL.md must document layout index table, placeholder idx/type/position, content area boundaries, delete-all-slides-first pattern, `paragraph.level` for bullets (no manual bullet characters).

PPT-specific rules: template in `assets/`; self-contained SKILL.md; no manual bullets; delete existing slides before adding; document placeholders by idx.

---

### 7.13 `skill-creator`

**Frontmatter**

- `name: skill-creator`
- `description`: create or update a skill that extends Claude with specialized knowledge, workflows, or tool integrations.
- `license: Complete terms in LICENSE.txt` (Apache License 2.0, January 2004).

Note: body later says “Do not include any other fields in YAML frontmatter” besides `name` and `description`, but this skill itself has `license`, and `quick_validate.py` allows `{name, description, license, allowed-tools, metadata}`.

**When it triggers:** user wants a new/updated skill. Also a dependency of `ppt-template-creator`.

**Core principles:** concise (context window is a public good); Claude is already smart; match degrees of freedom (high/medium/low) to fragility.

**Anatomy:** `SKILL.md` required; optional `scripts/`, `references/`, `assets/`. Do **not** add README, INSTALLATION_GUIDE, QUICK_REFERENCE, CHANGELOG.

**Progressive disclosure:** (1) metadata always ~100 words, (2) SKILL.md body when triggered <5k words / keep under 500 lines, (3) bundled resources as needed. References one level deep from SKILL.md; files >100 lines get a TOC.

**Process**

1. Concrete usage examples / trigger phrases.
2. Plan scripts vs references vs assets.
3. `scripts/init_skill.py <skill-name> --path <output-directory>`
4. Edit; consult `references/workflows.md` and `references/output-patterns.md`. Test scripts by running them. Delete unused example files. Imperative/infinitive voice. Description must include **when to use** (body “When to Use” sections are useless because body loads after trigger).
5. `scripts/package_skill.py <path/to/skill-folder> [./dist]` — validates then zips to `name.skill`.
6. Iterate on real tasks.

#### `scripts/init_skill.py`

Requires `init_skill.py <skill-name> --path <path>` (argv[2] must be `--path`). Creates `<path>/<skill-name>/` with SKILL.md template (TODO placeholders, four structure patterns: workflow / task / reference / capabilities), `scripts/example.py` (chmod 755), `references/api_reference.md`, `assets/example_asset.txt`. Fails if directory exists. CLI help: hyphen-case, `[a-z0-9-]`, max **40** characters, must match directory name. (Validator max name length is **64** — another mismatch.)

#### `scripts/package_skill.py`

Validates via `quick_validate.validate_skill`; if valid, zip with `ZIP_DEFLATED`, arcnames relative to **parent** of skill folder (so zip contains `skill-name/...`). Output `{skill_name}.skill` in cwd or given dir.

#### `scripts/quick_validate.py`

- SKILL.md exists, starts with `---`, valid YAML dict.
- Allowed keys: `name`, `description`, `license`, `allowed-tools`, `metadata`.
- Required: `name`, `description` strings.
- Name: `^[a-z0-9-]+$`, no leading/trailing hyphen, no `--`, max 64 chars.
- Description: no `<` or `>`, max 1024 chars.

Does **not** check the SKILL.md body’s “description completeness and quality” or “resource references” that `package_skill.py` comments claim.

#### `references/workflows.md`

Sequential numbered steps; conditional branch (create vs edit).

#### `references/output-patterns.md`

Strict ALWAYS-use-this-template vs flexible “sensible default”; examples-as-I/O-pairs (commit-message style).

---

## 8. Excel / PPT 규약 요약표

| Topic | Modeling (DCF/LBO/3stmt) | Comps | Decks |
|---|---|---|---|
| Borders | Mandatory thick around sections (DCF) | No borders | Table padding; no overlap |
| Font | Blue/black/green (+ purple LBO) | Same blue/black; Times New Roman default | 28–32 / 18–20 / ≥14pt |
| Fill | 3 blues + grey + white | Same; stats rows `#F2F2F2` | 2–3 muted colors |
| Numbers | `$#,##0;($#,##0);-` ; `%` 1dp; multiples `0.0x` | Same; center-aligned | Consistent `$M` **or** `$MM` |
| Inputs | Comments as created | Comments + hyperlinks | Citations on every number |
| Recalc | `recalc.py` until success | formulas live | N/A |
| Sensitivity | Odd 5×5, 75 full-recalc cells (DCF) | quartiles | N/A |

---

## 9. Safety / audit / hardcode detection (cross-plugin)

Hardcode policy is the central control:

- Derived cells are formulas. Python must not write computed results.
- Blue inputs only for actuals, drivers, market data.
- Every blue cell: comment `Source: [System/Document], [Date], [Reference], [URL]`.
- `audit-xls` hunts `=A1*1.05`-style literals, pasted-over formulas, hidden override tabs.
- `clean-data-xls` prefers helper formulas so transforms stay auditable.
- `ib-check-deck` is **report-only**.
- `deck-refresh` is destructive only after an approval plan; derived figures flagged not silently fixed.
- `pptx-author`: “No external sends.”
- DCF validator: `g >= WACC` is a hard FAIL; WACC outside 5–20% and TV/EV outside 40–80% are warnings.
- 3-statement master check and BS=0 / cash tie-out / RE rollforward / NOL 80% cap.
- LBO: Sources=Uses plug; no negative debt; IRR sign convention.

`/debug-model` is the user-facing entry to the deepest audit.

---

## 10. Headless vs interactive — decision tree

```
Is mcp__office__excel_* available?
  YES → Cowork live Excel; do NOT use xlsx-author
  NO  → Inside Excel add-in (Office JS)?
          YES → Office JS, range.formulas, no recalc.py
          NO  → Managed-agent / CMA? → xlsx-author → ./out/*.xlsx
                else standalone openpyxl + recalc.py

Is mcp__office__powerpoint_* available?
  YES → Cowork live PPT; do NOT use pptx-author
  NO  → Add-in live deck?
          YES → edit runs/cells/charts in place (deck-refresh, competitive-analysis)
          NO  → Managed-agent? → pptx-author → ./out/*.pptx
                else chat: generate/regenerate .pptx
```

Modeling skills state the Office JS vs Python split themselves; `pptx-author` / `xlsx-author` are the CMA-only file artifacts.

---

## 11. 관측된 갭 (source-only; not invented)

1. `.mcp.json` is **not valid JSON** (missing comma before `box`; missing root close). A strict loader cannot register any of the 12 servers.
2. MCP servers have **no auth documentation** and **no tool schemas** in this plugin.
3. Nine of twelve MCP keys are never mentioned by skills (`morningstar`, `moodys`, `mtnewswire`, `aiera`, `lseg`, `pitchbook`, `chronograph`, `egnyte`, `box`).
4. `examples/comps_example.xlsx` and `examples/LBO_Model.xlsx` are required by skills and **absent**.
5. `recalc.py` / `xlsx` skill / `pitch-deck` skill / `pptx` skill are referenced but **not bundled**.
6. `validate_dcf.py` is not invoked by `dcf-model/SKILL.md`; it expects a `Sensitivity` sheet the skill forbids as a separate sheet; `requests` in `requirements.txt` is unused.
7. `plugin.json` has no discovery flags beyond name/version/description/author.
8. `hooks.json` is empty.
9. No skill sets `user-invocable` or `allowed-tools`; only `/ppt-template` sets `allowed-tools`.
10. `skill-creator` body forbids extra frontmatter fields while using `license`; init max name 40 vs validator 64.
11. DCF WACC sheet sketch labels inputs “Yellow input”, conflicting with the blue-input rule.
12. `comps-analysis` SKILL.md has two “Section 6” headings (Best Practices and Advanced Features).
13. `lbo-model` SKILL.md has an extra `---` horizontal rule immediately after frontmatter (harmless markdown).

---

## 12. 파일 경로 인덱스

| Path | Role |
|---|---|
| `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/.claude-plugin/plugin.json` | Plugin identity 0.1.1 |
| `.../.mcp.json` | MCP hub (invalid JSON) |
| `.../hooks/hooks.json` | Empty hooks |
| `.../commands/*.md` | 7 slash commands |
| `.../skills/*/SKILL.md` | 13 skills |
| `.../skills/dcf-model/scripts/validate_dcf.py` | DCF Excel validator |
| `.../skills/ib-check-deck/scripts/extract_numbers.py` | Deck number extractor |
| `.../skills/skill-creator/scripts/{init,package,quick_validate}_skill.py` | Skill tooling |
