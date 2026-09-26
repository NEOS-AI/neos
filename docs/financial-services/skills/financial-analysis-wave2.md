# 수직 플러그인: financial-analysis

경로: `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/`

본 문서는 해당 디렉터리의 **존재하는 파일만** 인용한다. 존재하지 않는 파일·필드·URL은 만들지 않는다.

---

## 파일 목록 (전부)

```
.claude-plugin/plugin.json
.mcp.json
commands/3-statement-model.md
commands/competitive-analysis.md
commands/comps.md
commands/dcf.md
commands/debug-model.md
commands/lbo.md
commands/ppt-template.md
hooks/hooks.json
skills/3-statement-model/references/formatting.md
skills/3-statement-model/references/formulas.md
skills/3-statement-model/references/sec-filings.md
skills/3-statement-model/SKILL.md
skills/audit-xls/SKILL.md
skills/clean-data-xls/SKILL.md
skills/competitive-analysis/references/frameworks.md
skills/competitive-analysis/references/schemas.md
skills/competitive-analysis/SKILL.md
skills/comps-analysis/SKILL.md
skills/dcf-model/requirements.txt
skills/dcf-model/scripts/validate_dcf.py
skills/dcf-model/SKILL.md
skills/dcf-model/TROUBLESHOOTING.md
skills/deck-refresh/SKILL.md
skills/ib-check-deck/references/ib-terminology.md
skills/ib-check-deck/references/report-format.md
skills/ib-check-deck/scripts/extract_numbers.py
skills/ib-check-deck/SKILL.md
skills/lbo-model/SKILL.md
skills/ppt-template-creator/SKILL.md
skills/pptx-author/SKILL.md
skills/skill-creator/LICENSE.txt
skills/skill-creator/references/output-patterns.md
skills/skill-creator/references/workflows.md
skills/skill-creator/scripts/init_skill.py
skills/skill-creator/scripts/package_skill.py
skills/skill-creator/scripts/quick_validate.py
skills/skill-creator/SKILL.md
skills/xlsx-author/SKILL.md
```

루트 `plugin.json`은 없다. 메타데이터는 `.claude-plugin/plugin.json`에 있다.
루트 `requirements.txt` / 루트 `TROUBLESHOOTING.md`는 없다. 둘 다 `skills/dcf-model/` 아래에만 있다.

---

## 플러그인 메타데이터 (`plugin.json`)

위치: `.claude-plugin/plugin.json`

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

---

## MCP 커넥터 (`.mcp.json`)

### JSON 구문

파일은 **유효한 JSON이 아니다**. `python json.load` 오류:

> `Expecting ',' delimiter: line 47 column 5 (char 1100)`

원인 (파일 그대로):

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

1. `egnyte` 객체와 `"box"` 키 사이에 **쉼표가 없다**.
2. `"box"` 객체의 닫는 `}`가 없다. `"url"` 다음 들여쓰기 2칸 `}`가 `mcpServers`를 닫고, 그다음 `}`가 루트를 닫는다.

### 커넥터 URL (파일에 적힌 전부)

| 키 | type | url |
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

파일 상단 구조:

```json
{
  "mcpServers": {
    "daloopa": {
      "type": "http",
      "url": "https://mcp.daloopa.com/server/mcp"
    },
```

모든 서버 항목은 `"type": "http"`이다.

---

## 훅 (`hooks/hooks.json`)

```json
{
  "hooks": {}
}
```

훅 정의는 없다.

---

## 커맨드 (`commands/*.md`)

존재하는 커맨드 7개. 프론트매터에 `name` 필드는 없다. `description`과 (대부분) `argument-hint`만 있다.

### `/3-statement-model`

프론트매터:

```
description: Fill out a 3-statement financial model template
argument-hint: "[path to template file]"
```

본문:

> Load the `3-statement-model` skill and populate a 3-statement financial model (Income Statement, Balance Sheet, Cash Flow Statement).
>
> If a file path is provided, use it as the template. Otherwise ask the user for their model template.

### `/competitive-analysis`

프론트매터:

```
description: Create a competitive landscape analysis
argument-hint: "[company or industry]"
```

본문:

> Load the `competitive-analysis` skill and build a competitive landscape analysis for the specified company or industry.
>
> If a company/industry is provided as an argument, use it. Otherwise ask the user what they want to analyze.

### `/comps`

프론트매터:

```
description: Build a comparable company analysis with trading multiples
argument-hint: "[company name or ticker]"
```

본문 제목: `# Comparable Company Analysis Command`

워크플로 (파일 그대로):

1. **Step 1: Gather Company Information** — 인자 없으면 `"What company would you like to analyze?"`
2. **Step 2: Load Comps Analysis Skill** — `skill: "comps-analysis"`
   - Clarify purpose / audience / template
   - Identify peer group (4-6)
   - Gather data (MCP 우선)
   - Build analysis (Operating Statistics + Valuation Multiples + Notes)
3. **Step 3: Create Excel Output**
4. **Step 4: Deliver Output** — Excel + summary

산업별 추가 지표 (커맨드 표):

| Industry | Additional Metrics |
|----------|-------------------|
| Software/SaaS | ARR, Net Dollar Retention, Rule of 40 |
| Retail | Same-store sales, Inventory Turns |
| Financials | ROE, ROA, Efficiency Ratio |
| Manufacturing | Asset Turnover, CapEx/Revenue |
| Healthcare | R&D/Revenue, Pipeline Value |

Quality Checklist (발췌):

> - [ ] 4-6 truly comparable companies
> - [ ] Consistent time periods (all LTM or all FY)
> - [ ] All formulas reference cells (no hardcoded values)
> - [ ] Cell comments on all hardcoded inputs with sources
> - [ ] Statistics include Max, 75th, Median, 25th, Min
> - [ ] Blue = inputs, Black = formulas

### `/dcf`

프론트매터:

```
description: Build a DCF valuation model with comps-informed terminal multiples
argument-hint: "[company name or ticker]"
```

본문 제목: `# DCF Valuation Command`

> Build an institutional-quality DCF model that uses comparable company analysis to inform valuation ranges.

워크플로:

1. Gather Company Information
2. Run Comparable Company Analysis — `skill: "comps-analysis"` (4-6 comps)
3. Build DCF Model — `skill: "dcf-model"`
4. Cross-Check Valuation
5. Deliver Output — comps .xlsx + DCF .xlsx + summary

Comps → DCF 매핑 (파일 표):

| Comps Output | DCF Input |
|--------------|-----------|
| Peer median EV/EBITDA | Terminal exit multiple range |
| Peer 25th-75th EV/EBITDA | Sensitivity analysis range |
| Peer median growth rate | Benchmark for revenue assumptions |
| Peer median EBITDA margin | Target margin in terminal year |
| Peer median P/E | Cross-check implied P/E from DCF |

교차검증:

> 1. Implied EV/EBITDA from DCF vs peer median
> 2. Implied P/E from DCF vs peer median
> 3. Terminal value as % of EV (should be 50-70%)
> 4. Implied growth embedded in valuation vs peer growth rates

### `/debug-model`

프론트매터:

```
description: Debug and audit a financial model for errors
argument-hint: "[path to .xlsx model file]"
```

본문:

> Load the `audit-xls` skill with scope **model** and audit the specified financial model for broken formulas, balance sheet imbalances, hardcoded overrides, circular references, and logic errors — including the full model-integrity checks (BS balance, cash tie-out, roll-forwards, model-type-specific bugs).
>
> If a file path is provided, use it. Otherwise ask the user for the model to review.

### `/lbo`

프론트매터:

```
description: Build an LBO model for a PE acquisition
argument-hint: "[company name or deal details]"
```

본문:

> Load the `lbo-model` skill and build a leveraged buyout model for the specified company or deal.
>
> If a company name is provided as an argument, use it. Otherwise ask the user for the target company and deal parameters.

### `/ppt-template`

프론트매터:

```
description: Create a reusable PPT template skill from a PowerPoint template file
argument-hint: "[path to .pptx or .potx file]"
allowed-tools: ["Read", "Write", "Bash", "Glob"]
```

본문 제목: `# PPT Template Creator Command`

1. Ask for template if not provided (`.pptx` or `.potx`)
2. Load `skill: "ppt-template-creator"`
3. Gather company/template name and primary use cases
4. Execute skill workflow (analyze → generate skill dir → example → package)
5. Deliver packaged skill

---

## 스킬 공통 메모

존재하는 스킬 13개 — 요청 목록과 일치:

`comps-analysis`, `dcf-model`, `lbo-model`, `3-statement-model`, `audit-xls`, `clean-data-xls`, `deck-refresh`, `competitive-analysis`, `ib-check-deck`, `pptx-author`, `xlsx-author`, `ppt-template-creator`, `skill-creator`

프론트매터에 `name` + `description`이 있다. `skill-creator`만 추가로 `license: Complete terms in LICENSE.txt`.

---

## 스킬: comps-analysis

경로: `skills/comps-analysis/SKILL.md` (references/scripts 없음)

### 프론트매터

```
name: comps-analysis
description: |
  Build institutional-grade comparable company analyses with operating metrics, valuation multiples, and statistical benchmarking in Excel/spreadsheet format.

  **Perfect for:**
  - Public company valuation (M&A, investment analysis)
  - Benchmarking performance vs. industry peers
  - Pricing IPOs or funding rounds
  - Identifying valuation outliers (over/under-valued)
  - Supporting investment committee presentations
  - Creating sector overview reports

  **Not ideal for:**
  - Private companies without comparable public peers
  - Highly diversified conglomerates
  - Distressed/bankrupt companies
  - Pre-revenue startups
  - Companies with unique business models
```

### 트리거

description의 Perfect for / Not ideal for가 트리거 범위다. 커맨드 `/comps`가 `skill: "comps-analysis"`를 로드한다.

### 워크플로

데이터 소스 우선순위 (파일 그대로):

> 1. FIRST: Check for MCP data sources - If S&P Kensho MCP, FactSet MCP, or Daloopa MCP are available, use them exclusively
> 2. DO NOT use web search if the above MCP data sources are available
> 3. ONLY if MCPs are unavailable: Then use Bloomberg Terminal, SEC EDGAR filings, or other institutional sources
> 4. NEVER use web search as a primary data source

> "Build the right structure first, then let the data tell the story."

Step-by-Step Process (Section 7):

1. Set up structure (30 minutes)
2. Gather data (60-90 minutes)
3. Build formulas (30 minutes)
4. Add statistics (15 minutes)
5. Quality control (30 minutes)
6. Documentation (15 minutes)

중간 확인:

> After setting up the structure → show the user the header layout
> After entering raw inputs → confirm sources/periods
> After building operating metrics formulas → sanity-check
> After building valuation multiples → confirm before adding statistics
> Do NOT build the entire sheet end-to-end and then present it

### 입출력 (I/O)

입력: 회사/티커, 목적(valuation/efficiency/growth), 청중, 템플릿 선호, MCP 데이터.

출력: Excel/spreadsheet. 예: `examples/comps_example.xlsx`를 구조 참고용으로 언급 (해당 예제 파일은 이 디렉터리에 **존재하지 않음** — SKILL.md 텍스트만 존재).

헤더 블록:

```
Row 1: [ANALYSIS TITLE] - COMPARABLE COMPANY ANALYSIS
Row 2: [List of Companies with Tickers]
Row 3: As of [Period] | All figures in [USD Millions/Billions] except per-share amounts and ratios
```

Operating columns: Company, Revenue, Revenue Growth, Gross Profit, Gross Margin, EBITDA, EBITDA Margin.

Valuation columns: Company, Market Cap, Enterprise Value, EV/Revenue, EV/EBITDA, P/E.

통계: Maximum, 75th Percentile (`=QUARTILE(range,3)`), Median, 25th Percentile (`=QUARTILE(range,1)`), Minimum. 회사 데이터와 통계 사이 빈 행 1개. `"SECTOR STATISTICS"` / `"VALUATION STATISTICS"` 헤더 행은 넣지 말 것.

### 스크립트

없음.

### Excel 컨벤션

환경:

> If running inside Excel (Office Add-in / Office JS): Use Office JS directly (`Excel.run(async (context) => {...})`). Write formulas via `range.formulas = [["=E7/C7"]]`, not `range.values`.
> If generating a standalone .xlsx file: Use Python/openpyxl. Write `cell.value = "=E7/C7"`.

Office JS merged cell:

> Do NOT call `.merge()` then set `.values` on the merged range. Instead write the value to the top-left cell alone, then merge + format.

색:

> Blue text for hardcoded inputs; Black text for formulas.
> Section headers: Dark blue `#1F4E79` or `#17365D`, white bold.
> Column headers: Light blue `#D9E1F2`.
> Statistics rows: Light grey `#F2F2F2`.
> Font: Times New Roman, 11pt data, 12pt headers (defaults).
> No borders. Metrics center-aligned. Uniform column widths.

> The only hardcoded values should be raw input data — and every one of those gets a cell comment with its source

### Headless vs Interactive

- Interactive (Office Add-in / Office JS): 라이브 워크북, native recalc.
- Headless (standalone .xlsx): Python/openpyxl.

---

## 스킬: dcf-model

경로: `skills/dcf-model/` — `SKILL.md`, `TROUBLESHOOTING.md`, `requirements.txt`, `scripts/validate_dcf.py`

### 프론트매터

```
name: dcf-model
description: Real DCF (Discounted Cash Flow) model creation for equity valuation. Retrieves financial data from SEC filings and analyst reports, builds comprehensive cash flow projections with proper WACC calculations, performs sensitivity analysis, and outputs professional Excel models with executive summaries. Use when users need to value a company using DCF methodology, request intrinsic value analysis, or ask for detailed financial modeling with growth projections and terminal value calculations.
```

### 트리거

description: DCF valuation, intrinsic value, financial modeling with growth projections and terminal value.

커맨드 `/dcf`가 comps 이후 이 스킬을 로드한다.

### 워크플로 (DCF Process Workflow)

Step 1 Data Retrieval and Validation
Step 2 Historical Analysis (3-5 years)
Step 3 Build Revenue Projections
Step 4 Operating Expense Modeling
Step 5 Free Cash Flow Calculation
Step 6 Cost of Capital (WACC) Research
Step 7 Discount Rate Application (5-10 Year Forecast)
Step 8 Terminal Value Calculation
Step 9 Enterprise to Equity Value Bridge
Step 10 Sensitivity Analysis

데이터 소스 우선순위:

> 1. MCP Servers (if configured) - Structured financial data from providers like Daloopa
> 2. User-Provided Data
> 3. Web Search/Fetch - Current prices, beta, debt and cash when needed

단계별 확인 (end-to-end 금지):

> After data retrieval → confirm raw inputs
> After revenue projections → confirm top line
> After FCF build → confirm logic before WACC
> After WACC → confirm before discounting
> After terminal value + PV → confirm equity bridge before sensitivity tables

FCF 순서 (파일):

```
EBIT
(-) Taxes (EBIT × Tax Rate)
= NOPAT
(+) D&A
(-) CapEx
(-) Δ NWC
= Unlevered Free Cash Flow
```

WACC:

```
Cost of Equity = Risk-Free Rate + Beta × Equity Risk Premium
After-Tax Cost of Debt = Pre-Tax Cost of Debt × (1 - Tax Rate)
WACC = (Cost of Equity × Equity Weight) + (After-Tax Cost of Debt × Debt Weight)
```

Mid-year convention: periods 0.5, 1.5, 2.5, …

Perpetuity:

```
Terminal FCF = Final Year FCF × (1 + Terminal Growth Rate)
Terminal Value = Terminal FCF / (WACC - Terminal Growth Rate)
Critical Constraint: Terminal Growth < WACC
```

> Terminal Value Sanity Check: Should represent 50-70% of Enterprise Value. If >75%, model may be over-reliant. If <40%, check if terminal assumptions are too conservative.

시나리오: Bear/Base/Bull. Case selector `B6` = 1/2/3. consolidation column:

> `=INDEX(B10:D10, 1, $B$6)`
> NOT scattered IF statements throughout.

민감도 3개 (DCF 시트 **하단**, 별도 시트 아님 — SKILL.md):

1. WACC vs Terminal Growth
2. Revenue Growth vs EBIT Margin
3. Beta vs Risk-Free Rate

> Use an ODD number of rows and columns (standard: 5×5, sometimes 7×7)
> Center cell = base case. Highlight `#BDD7EE` + bold.
> Populate ALL cells (typically 3 tables × 25 cells = 75) with full DCF recalculation formulas
> NOT Excel's "Data Table" feature

파일명: `[Ticker]_DCF_Model_[Date].xlsx`

시트: **DCF** + **WACC**. Sensitivity는 DCF 하단.

납품 전:

> `python recalc.py [path_to_excel_file] [timeout_seconds]`
> Example: `python recalc.py AAPL_DCF_Model_2025-10-12.xlsx 30`
> Zero formula errors required

### 입출력

Minimum Required Inputs:

> 1. Company identifier: Ticker symbol or company name
> 2. Growth assumptions: Revenue growth rates for projection period (or "use consensus")
> 3. Optional: Projection period (default: 5 years), Scenario cases, Terminal growth (default: 2.5-3.0%), Specific WACC inputs

출력: 2시트 Excel. Valuation summary CSV 형식도 SKILL에 예시.

### 스크립트: `scripts/validate_dcf.py`

CLI:

```
Usage: python validate_dcf.py <excel_file> [output.json]
```

검증:

> - Formula errors (#REF!, #DIV/0!, etc.)
> - Terminal growth < WACC (critical)
> - WACC in reasonable range (5-20%)
> - Terminal value proportion of EV (40-80%)

클래스 `DCFModelValidator`:

- `check_sheet_structure()`: `required_sheets = ['DCF', 'WACC', 'Sensitivity']` — 없으면 **warning** `"Recommended sheet missing"`. (SKILL.md는 Sensitivity를 별도 시트가 아니라 DCF 하단에 두라고 함. 스크립트와 SKILL 문구가 다름.)
- `check_formula_errors()`: `#VALUE!`, `#DIV/0!`, `#REF!`, `#NAME?`, `#NULL!`, `#NUM!`, `#N/A`
- `check_dcf_logic()`: terminal growth vs WACC, WACC 5–20%, TV/EV 40–80% (경고 기준; SKILL 본문은 50–70%를 typical로 기술)

결과 JSON 키: `file`, `validation_date`, `status` (`PASS`/`FAIL`), `error_count`, `warning_count`, `errors`, `warnings`, `info`. 예외 시 `status: ERROR`. PASS가 아니면 exit 1.

의존성: `openpyxl` (`ImportError: "openpyxl not installed. Run: pip install openpyxl"`).

### Excel 컨벤션

Office JS vs Python/openpyxl — comps와 동일 패턴. merged cell pitfall 동일.

Font:

> Blue text (RGB: 0,0,255): ALL hardcoded inputs
> Black text (RGB: 0,0,0): ALL formulas
> Green text (RGB: 0,128,0): Links to other sheets

Fill:

> Section headers: `#1F4E79`
> Sub-headers: `#D9E1F2`
> Input cells: `#F2F2F2` or white + blue font
> Output/summary: `#BDD7EE`

Borders: thick 1.5pt around major sections, medium 1pt between sub-sections, thin 0.5pt around data tables. **Borders are mandatory.**

Number formats: years as text; percentages `0.0%`; currency `$#,##0` / `$#,##0.00`; zeros as `-`; negatives `(#,##0)`.

Cell comments: `"Source: [System/Document], [Date], [Reference], [URL if applicable]"` — 생성 즉시.

WACC 시트 입력은 예시에서 `[Yellow input]`으로 표시된다 (DCF 시트의 blue/grey 팔레트와 표기 방식이 다름).

### Headless vs Interactive

- Excel add-in: Office JS, native calc, **do NOT use Python/openpyxl**
- Standalone .xlsx: openpyxl + `recalc.py`

### TROUBLESHOOTING.md

> When to read this file: If recalc.py shows errors OR valuation results seem unreasonable OR case selector not working properly.

| 증상 | 파일 내용 |
|---|---|
| `#REF!` | formulas referencing wrong rows after headers inserted. Prevention: Define all row positions BEFORE writing formulas |
| `#DIV/0!` | `=IF([Divisor]=0,0,[Numerator]/[Divisor])` |
| `#VALUE!` | Verify all inputs are formatted as numbers |
| Implied price too high | TV >80% of EV; terminal growth < WACC; growth/margins |
| Implied price too low | net debt vs net cash; WACC too high; conservative projections; terminal growth too low |
| Case selector not working | selector is 1/2/3; INDEX/OFFSET ranges; `$B$6` absolute; test by changing selector |

### requirements.txt

```
# DCF Model Builder - Python Dependencies

# Excel file handling
openpyxl>=3.0.0

# HTTP requests
requests>=2.28.0
```

---

## 스킬: lbo-model

경로: `skills/lbo-model/SKILL.md` (references/scripts 없음)

### 프론트매터

```
name: lbo-model
description: This skill should be used when completing LBO (Leveraged Buyout) model templates in Excel for private equity transactions, deal materials, or investment committee presentations. The skill fills in formulas, validates calculations, and ensures professional formatting standards that adapt to any template structure.
```

### 트리거

LBO 템플릿 완성, PE 거래, deal materials, IC presentations. 커맨드 `/lbo`.

### 워크플로

템플릿 필수:

> 1. If a template file is attached/provided: Use that template's structure exactly
> 2. If no template is attached: Ask: "Do you have a specific LBO template you'd like me to use? If not, I can use the standard template which includes Sources & Uses, Operating Model, Debt Schedule, and Returns Analysis."
> 3. If using the standard template: Copy `examples/LBO_Model.xlsx` as your starting point
>
> Never decide to "build from scratch" when a template is provided.

(`examples/LBO_Model.xlsx`는 SKILL.md에서만 언급되고 이 디렉터리에는 파일이 없다.)

TEMPLATE ANALYSIS PHASE 후 FILLING FORMULAS hierarchy: Check the Template → Check the User's Instructions → Apply Standard Practice.

섹션별 확인:

> After Sources & Uses → confirm plug
> After Operating Model / Projections → confirm growth/margins
> After Debt Schedule → confirm waterfall
> After Returns (IRR/MOIC) → confirm signs/ranges
> After Sensitivity Tables → confirm each cell varies

### 입출력

입력: 템플릿 + 사용자 assumptions / deal parameters.
출력: 채워진 LBO Excel. recalc:

```
python /mnt/skills/public/xlsx/recalc.py model.xlsx
```

Must return success with zero errors.

### 스크립트

스킬 디렉터리 내 스크립트 없음. recalc 경로는 위 인용.

### Excel 컨벤션

Font:

> Blue (0000FF): Hardcoded inputs
> Black (000000): Formulas with calculations
> Purple (800080): Links to cells on the same tab (`=B9`)
> Green (008000): Links to cells on different tabs

Fill: `#1F4E79` / `#D9E1F2` / `#F2F2F2` / white / `#BDD7EE` (IRR, MOIC, Exit Equity).

Number:

> Currency: `$#,##0;($#,##0);"-"` or `$#,##0.0`
> Percentages: `0.0%`
> Multiples: `0.0"x"`
> MOIC/Detailed Ratios: `0.00"x"`
> All numeric cells: Right-aligned

Interest circularity:

> Use Beginning Balance (not average or ending) to break circular references

Sensitivity: ODD 5×5 or 7×7, center = base, `#BDD7EE` + bold, mixed refs `$A5` / `B$4`. Excel DATA TABLE may not work with openpyxl.

### Headless vs Interactive

Office Add-in: Office JS, native recalc.
Standalone: Python/openpyxl + `recalc.py`.
Merged cell pitfall 동일.

---

## 스킬: 3-statement-model

경로: `skills/3-statement-model/` — `SKILL.md` + `references/{formatting,formulas,sec-filings}.md`

### 프론트매터

```
name: 3-statement-model
description: Complete, populate and fill out 3-statement financial model templates (Income Statement, Balance Sheet, Cash Flow Statement) . Use when asked to fill out model templates, complete existing model frameworks, populate financial models with data, complete a partially filled IS/BS/CF framework, or link integrated financial statements within an existing template structure. Triggers include requests to fill in, complete, or populate a 3-statement model template
```

### 트리거

fill/complete/populate 3-statement template. 커맨드 `/3-statement-model`.

### 워크플로

환경: Office JS vs Python/openpyxl. formulas over hardcodes. merged cell pitfall 동일.

사용자 확인:

> 1. After mapping the template
> 2. After populating historicals
> 3. After building IS projections
> 4. After building BS (Assets = L+E every period)
> 5. After building CF (CF ending cash = BS cash)
> 6. Do NOT populate the entire model end-to-end

Completing templates:

Step 1 Analyze Template Structure
Step 2 Filling in Data Without Breaking Formulas
Step 3 Validating Formulas
Step 4 Quality Checks by Sheet
Step 5 Cross-Statement Integrity Checks
Step 6 Final Review

Margin analysis / Credit metrics: **only if prompted by the user or if the template explicitly requires it**.

시나리오: Base / Upside / Downside. CHOOSE or INDEX/MATCH.

SEC: `references/sec-filings.md` — 템플릿이 10-K/10-Q를 요구할 때만.

### 입출력

입력: 템플릿 경로, 히스토리컬/가정, (선택) SEC filings.
출력: 채워진 3-statement 모델. standalone이면 `recalc.py`.

탭 이름 예 (파일 표): IS/P&L, BS, CF/CFS, WC, DA/D&A/PP&E, Debt, NOL/Tax/DTA, Assumptions/Inputs/Drivers, Checks/Audit/Validation.

### 스크립트

없음. formulas는 `references/formulas.md`.

### Excel 컨벤션

SKILL.md 팔레트:

| Element | Fill | Font |
|---|---|---|
| Section headers | Dark blue `#1F4E79` | White bold |
| Column headers | Light blue `#D9E1F2` | Black bold |
| Input cells | Light grey `#F2F2F2` or white | Blue `#0000FF` |
| Formula cells | White | Black |
| Cross-tab links | White | Green `#008000` |
| Check rows / key totals | Medium blue `#BDD7EE` | Black bold |

`references/formatting.md` 추가:

> Hard-coded inputs: Blue font
> Formulas: Black font
> Links to other sheets: Green font
> Check cells: Red if error, green if balanced
> Negative values: Parentheses, not minus signs
> Percentages: 1 decimal place
> BS check custom format: `[Red][<>0]0.00;[Red][<>0](0.00);0.00`

Credit metric threshold colors (formatting.md):

| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| Total Debt / EBITDA | < 2.5x | 2.5x-4.0x | > 4.0x |
| Net Debt / EBITDA | < 2.0x | 2.0x-3.5x | > 3.5x |
| Interest Coverage | > 4.0x | 2.5x-4.0x | < 2.5x |
| Debt / Total Cap | < 40% | 40%-60% | > 60% |
| Current Ratio | > 1.5x | 1.0x-1.5x | < 1.0x |
| Quick Ratio | > 1.0x | 0.75x-1.0x | < 0.75x |

Circular:

> Enable iterative calculation: maximum iterations 100, maximum change 0.001. Add a circuit breaker toggle in Assumptions tab.

### Headless vs Interactive

Office JS (add-in) vs openpyxl + recalc (standalone). 템플릿 우선.

### 레퍼런스: formulas.md

핵심 연계:

```
Balance Sheet:        Assets = Liabilities + Equity
Net Income:           IS Net Income → CF Operations (starting point)
Cash Flow:            ΔCash = CFO + CFI + CFF
Cash Tie-Out:         Ending Cash (CF) = Cash (BS Asset)
Retained Earnings:    Prior RE + Net Income - Dividends = Ending RE
```

> Gross Profit must be calculated from Net Revenue, not Gross Revenue.

NOL: Year 1 beginning = 0; utilization ≤ 80% of EBT (post-2017); DTA = Ending NOL × Tax Rate.

### 레퍼런스: sec-filings.md

> Only reference this file when a model template specifically requires pulling data from SEC filings (10-K, 10-Q).

EDGAR: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=[TICKER]&type=10-K` (분기 `type=10-Q`).

> 10-K provides 3 years of IS/CF, 2 years of BS. For 3rd year BS, pull from prior year's 10-K.

Item 8 (10-K) / Item 1 (10-Q). 통화·스케일 확인 후 Assumptions에 기록.

---

## 스킬: audit-xls

경로: `skills/audit-xls/SKILL.md`

### 프론트매터

```
name: audit-xls
description: Audit a spreadsheet for formula accuracy, errors, and common mistakes. Scopes to a selected range, a single sheet, or the entire model (including financial-model integrity checks like BS balance, cash tie-out, and logic sanity). Triggers on "audit this sheet", "check my formulas", "find formula errors", "QA this spreadsheet", "sanity check this", "debug model", "model check", "model won't balance", "something's off in my model", "model review".
```

### 트리거

위 description 문구 + 커맨드 `/debug-model` (scope **model** 강제).

### 워크플로

Step 1 Determine scope: selection / sheet / model. 없으면 질문.

Step 2 Formula-level checks (ALL scopes): `#REF!` `#VALUE!` `#N/A` `#DIV/0!` `#NAME?`; hardcodes inside formulas; inconsistent formulas; off-by-one; pasted-over formulas; circular refs; broken cross-sheet links; unit/scale mismatches; hidden rows/tabs.

Step 3 Model-integrity (MODEL only): structural; BS; CF; IS; circular; logic; type-specific (DCF / LBO / Merger / 3-statement).

Step 4 Report — 먼저 보고, 수정은 요청 시:

> Don't change anything without asking — report first, fix on request.

### 입출력

입력: 범위 또는 .xlsx.
출력 표:

```
| # | Sheet | Cell/Range | Severity | Category | Issue | Suggested Fix |
```

Severity: Critical / Warning / Info.

Model scope 요약 줄:

> Model type: [DCF/LBO/3-stmt/...] — Overall: [Clean / Minor Issues / Major Issues] — [N] critical, [N] warnings, [N] info

### 스크립트

없음.

### Excel 컨벤션

감사 대상 컨벤션:

> Blue=input, black=formula, green=link — or whatever the model uses, applied consistently

### Headless vs Interactive

환경 분기는 SKILL에 명시되지 않음. 스코프는 selection/sheet/model.

---

## 스킬: clean-data-xls

경로: `skills/clean-data-xls/SKILL.md`

### 프론트매터

```
name: clean-data-xls
description: Clean up messy spreadsheet data — trim whitespace, fix inconsistent casing, convert numbers-stored-as-text, standardize dates, remove duplicates, and flag mixed-type columns. Use when data is messy, inconsistent, or needs prep before analysis. Triggers on "clean this data", "clean up this sheet", "normalize this data", "fix formatting", "dedupe", "standardize this column", "this data is messy".
```

### 트리거

위 문구 그대로.

### 워크플로

Step 1 Scope — 범위 없으면 used range.
Step 2 Detect issues — whitespace, casing, number-as-text, dates, duplicates, blanks, mixed types, encoding/mojibake, errors.
Step 3 Propose fixes — 변경 전 summary table.
Step 4 Apply.

> Prefer formulas over hardcoded cleaned values — helper columns (`=TRIM(A2)`, `=VALUE(SUBSTITUTE(B2,"$",""))`, `=UPPER(C2)`, `=DATEVALUE(D2)`).
> Only overwrite in place when the user explicitly asks, or when no sensible formula equivalent exists.
> For destructive operations (removing duplicates, filling blanks, overwriting originals), confirm with the user first.
> After each category of fix (whitespace → casing → number conversion → dates → dedup), show a sample and get confirmation.

### 입출력

입력: active sheet 또는 지정 범위.
출력: helper columns 또는 (승인 후) in-place + before/after summary.

### 스크립트

없음.

### Excel 컨벤션

Office JS: `range.values` 읽기, `range.formulas`로 helper.
Standalone: Python/openpyxl.

### Headless vs Interactive

명시된 두 환경 모두. in-place vs helper-column 결정은 공통.

---

## 스킬: deck-refresh

경로: `skills/deck-refresh/SKILL.md`

### 프론트매터

```
name: deck-refresh
description: Updates a presentation with new numbers — quarterly refreshes, earnings updates, comp rolls, rebased market data. Use whenever the user asks to "update the deck with Q4 numbers", "refresh the comps", "roll this forward", "swap in the new earnings", "change all the $485M to $512M", or any request to swap figures across an existing deck without rebuilding it.
```

### 트리거

위 인용 구절.

### 워크플로 (4 phase, 3번째가 승인 게이트)

> This is a four-phase process and the third phase is an approval gate. Don't edit until the user has seen the plan.

Phase 1 Get the data — `ask_user_question`: pasted mapping / uploaded Excel / just the new values. derived numbers 재계산 여부 질문.

Phase 2 Read everything — scale/precision/unit/embedded variants. 숨는 위치: text boxes, table cells, chart labels, chart source data, footnotes, speaker notes.

Phase 3 Present the plan — 전체 change list. flagged derived는 조용히 고치지 않음.

Phase 4 Execute, preserve, report — 최소 편집. 숫자 길이 변화 overflow 시각 검증.

하지 않는 것:

> Not rebuilding slides
> Not recalculating unless asked
> Not touching formatting — if the deck uses `$MM` and the user's mapping says `$M`, match the deck

### 입출력

입력: 기존 덱 + 신규 숫자 매핑.
출력: 수정된 덱 + 변경/미변경 리포트.

### 스크립트

없음.

### PPT 컨벤션

> Text in a shape — change the value, leave font/size/color/bold state exactly as they were.
> Table cell — change the cell, leave the table alone.
> Chart data — update the underlying series values so the bars/lines actually move.

### Headless vs Interactive

> Add-in — the deck is open live; edit text runs, table cells, and chart data directly.
> Chat — the deck is an uploaded file; edit it by regenerating the affected slides with the new values and writing the result back.

---

## 스킬: competitive-analysis

경로: `skills/competitive-analysis/` — `SKILL.md` + `references/{frameworks,schemas}.md`

### 프론트매터

```
name: competitive-analysis
description: Framework for building competitive landscape decks — market positioning, competitor deep-dives, comparative analysis, strategic synthesis. Use when the user asks for a competitive landscape, competitor analysis, peer comparison, market positioning assessment, strategic review, or investment memo deck. Also triggers on "who are the competitors to X", "benchmark X against peers", "build a market map", or any request to systematically evaluate competitive dynamics across an industry.
```

### 트리거

위 description + 커맨드 `/competitive-analysis`.

### 워크플로

Phase 1 Scope — `ask_user_question` (최대 4): Scope, Competitor set, Audience and depth, Investment context.

Phase 2 Outline, approve, then build:

> Do not create slides until the outline is approved.

Analysis steps 0–9:

0. Industry-defining metrics
1. Market context
2. Industry economics
3. Target company profile
4. Competitor mapping
5. Positioning visualization
6. Competitor deep-dives
7. Comparative analysis
8. Strategic context (M&A — `references/schemas.md`)
9. Synthesis (moat; investment이면 bull/base/bear)

소스 우선순위:

> 1. 10-Ks / annual reports (audited)
> 2. Earnings calls / investor presentations
> 3. Sell-side research
> 4. Industry reports (McKinsey, Gartner)
> 5. News (recent developments only; verify against primary sources)

### 입출력

입력: 회사/산업, competitor set, (선택) Excel/CSV.
출력: 10–20 슬라이드 덱 (Phase 1에서 깊이 결정).

> If they've uploaded an Excel/CSV with competitor data, confirm which columns map to which metrics before you start pulling numbers. Source-file fidelity matters: use values exactly as given, don't recalculate or re-round.

### 스크립트

없음.

### PPT 컨벤션

Typography:

> Slide titles: 28-32pt bold
> Section headers: 18-20pt bold
> Body text: 14-16pt (never below 14pt)
> Table text: 14pt
> Sources/footnotes: 14pt, gray

Charts: real chart objects; legend inside boundary; pie ≤6 slices right legend; line/bar ≤4 series bottom; >6 series → split or table.

Tables: light gray header, bold; numbers right, text left.

Color: 2-3 colors max. navy, gray, one accent.

> Slide titles are insights, not labels.
> Missing data shows as "-" or "N/A" with an "[E]" flag for estimates — never blank
> Every number has a citation: "[Company] [Document] ([Date])"

### Headless vs Interactive

> Add-in — the deck is open live; build slides directly into it.
> Chat — generate a `.pptx` file (or build into one the user uploaded).

### 레퍼런스: frameworks.md

2×2 축 쌍:

> Technology/SaaS: Product breadth × Customer segment, Integration depth × Geographic reach
> Consumer/Retail: Price point × Product range, Online × Offline presence
> Financial Services: Product complexity × Customer sophistication, Scale × Specialization
> Healthcare: Care setting × Payer mix, Technology enablement × Service breadth
> Industrial: Customization × Scale, Geographic scope × Vertical focus

### 레퍼런스: schemas.md

M&A table: Acquirer, Target, Date, Deal Value, Multiple, Rationale.

Scenario table: Scenario, Probability, Valuation, Key Assumptions.

Slide structure: insight headline / main content / `Source: [Citation] ([Date])`.

---

## 스킬: ib-check-deck

경로: `skills/ib-check-deck/` — `SKILL.md` + `references/{ib-terminology,report-format}.md` + `scripts/extract_numbers.py`

### 프론트매터

```
name: ib-check-deck
description: Investment banking presentation quality checker. Reviews a pitch deck or client-ready presentation for (1) number consistency across slides, (2) data-narrative alignment, (3) language polish against IB standards, (4) visual and formatting QC. Use whenever the user asks to review, check, QC, proof, or do a final pass on a deck, pitch, or client materials — including requests like "check my numbers", "reconcile figures across slides", "is this client-ready", or "what am I missing before I send this out".
```

### 트리거

위 문구.

### 워크플로

> This is read-and-report only — no edits — so the workflow is identical in both [Add-in and Chat].

1. Read the deck — 슬라이드 마커 markdown으로 추출:

```
## Slide 1
[slide 1 text content]
```

2. Number consistency — `python scripts/extract_numbers.py /tmp/deck_content.md --check`
3. Data-narrative alignment
4. Language polish — `references/ib-terminology.md`
5. Visual and formatting QC

출력 구조: `references/report-format.md`

> Critical — number mismatches, factual errors, data contradicting narrative. These block client delivery.
> Important — language, missing sources, terminology drift. Should fix.
> Minor — font sizes, spacing, date formats. Polish.
>
> Lead with criticals. If there aren't any, say so explicitly — "no number inconsistencies found" is a finding

### 입출력

입력: live deck 또는 uploaded `.pptx`.
출력: Deck Check Report (markdown). 편집 없음.

### 스크립트: `scripts/extract_numbers.py`

Usage (docstring):

```
python extract_numbers.py presentation-content.md
python extract_numbers.py presentation-content.md --output numbers.json
```

argparse: `input_file`, `--output/-o`, `--check/-c`.

`NumberInstance`: value, normalized, unit, slide, context, line_number, category.

단위 배수: T 1e12; B/bn/billion 1e9; M/mm/mn/million 1e6; K/k/thousand 1e3.

카테고리: revenue, ebitda_margin, ebitda, margin, growth, multiple, valuation, percentage, other.

`--check`: 카테고리별 그룹, **5% tolerance**. 가장 큰 그룹을 expected로 보고 나머지를 inconsistency. severity high if category in `['revenue', 'ebitda', 'valuation']` else medium.

연도 1900–2099는 unit/currency 없으면 skip. 2자리 미만 숫자이면서 unit 없으면 skip.

### PPT 컨벤션

시각 QC: missing chart source citations, missing axis labels, typography inconsistencies, number formatting drift (`1,000` vs `1K`), date format drift, footnote/disclaimer gaps, overlaps, overflow, contrast.

### Headless vs Interactive

> Add-in — read from the live open deck.
> Chat — read from the uploaded `.pptx` file.
> read-and-report only — no edits

### 레퍼런스: ib-terminology.md

캐주얼 → IB (발췌): "a lot of growth" → "significant growth" or "X% growth"; "cheap valuation" → "attractive valuation" or "valuation discount"; "cut costs" → "implement cost optimization".

피할 것: contractions, exclamation points, first-person "We think...", superlatives without evidence, vague quantifiers.

### 레퍼런스: report-format.md

템플릿: `# Deck Check Report: [Presentation Name]` → Summary → Critical → Important → Minor → Final Checklist.

---

## 스킬: pptx-author

경로: `skills/pptx-author/SKILL.md`

### 프론트매터

```
name: pptx-author
description: Produce a .pptx file on disk (headless) instead of driving a live PowerPoint document — for managed-agent sessions with no open Office app.
```

### 트리거

Headless / CMA / managed-agent에서 PPT 파일 산출.

### 워크플로

Python + `python-pptx` 스크립트를 Bash로 실행.

```python
from pptx import Presentation
from pptx.util import Inches, Pt

prs = Presentation("./templates/firm-template.pptx")  # if a template is provided
# or: prs = Presentation()

slide = prs.slides.add_slide(prs.slide_layouts[5])    # title-only
slide.shapes.title.text = "Valuation Summary"
prs.save("./out/pitch-<target>.pptx")
```

### 입출력

> Write to `./out/<name>.pptx`. Create `./out/` if it does not exist.
> Return the relative path in your final message so the orchestration layer can collect it.

### 스크립트

스킬 내 고정 스크립트 없음. 런타임에 짧은 Python을 작성·실행.

### PPT 컨벤션

> One idea per slide. Title states the takeaway; body supports it.
> Every number traces to the model. If a figure comes from `./out/model.xlsx`, footnote the sheet and cell.
> Use the firm template when one is mounted at `./templates/`; otherwise default layouts.
> Charts: prefer embedding a PNG rendered from the model over native pptx charts when fidelity matters.
> No external sends. This skill writes a file; it never emails or uploads.

> Conventions (mirror the live-Office `pitch-deck` skill)

### Headless vs Interactive

> If `mcp__office__powerpoint_*` tools are available (Cowork plugin mode), use those instead — they drive the user's live document with review checkpoints. This skill is the file-producing fallback for headless runs.

---

## 스킬: xlsx-author

경로: `skills/xlsx-author/SKILL.md`

### 프론트매터

```
name: xlsx-author
description: Produce a .xlsx file on disk (headless) instead of driving a live Excel workbook — for managed-agent sessions with no open Office app.
```

### 트리거

Headless에서 Excel 파일 산출.

### 워크플로

Python + `openpyxl`, Bash 실행. 예시:

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

wb = Workbook()
ws = wb.active; ws.title = "Inputs"
ws["B2"] = "Revenue"; ws["C2"] = 1_250_000_000
ws["C2"].font = Font(color="0000FF")           # blue = hardcoded input
calc = wb.create_sheet("DCF")
calc["C5"] = "=Inputs!C2*(1+Inputs!C3)"        # black = formula
wb.save("./out/model.xlsx")
```

### 입출력

> Write to `./out/<name>.xlsx`. Create `./out/` if it does not exist.
> Return the relative path in your final message.

### 스크립트

스킬 내 고정 스크립트 없음.

### Excel 컨벤션 (mirror `audit-xls`)

> Blue / black / green. Blue = hardcoded input, black = formula, green = link to another sheet/file.
> No hardcodes in calc cells. Every calculation cell is a formula; every input lives on an Inputs tab.
> Named ranges for any value referenced from a deck or memo.
> Balance checks. Include a Checks tab that ties (BS balances, CF ties to cash, etc.) and surfaces TRUE/FALSE.
> One model per file. Do not append to an existing workbook unless explicitly asked.

### Headless vs Interactive

> If `mcp__office__excel_*` tools are available (Cowork plugin mode), use those instead — they drive the user's live workbook with review checkpoints. This skill is the file-producing fallback for headless runs.

---

## 스킬: ppt-template-creator

경로: `skills/ppt-template-creator/SKILL.md`

### 프론트매터

```
name: ppt-template-creator
description: Creates self-contained PPT template SKILLS (not presentations) from user-provided PowerPoint templates. Use ONLY when a user wants to create a reusable skill from their template. For creating actual presentations, use the pptx skill instead.
```

### 트리거

템플릿 → 재사용 스킬. 실제 발표자료는 `pptx` 스킬. 커맨드 `/ppt-template`.

### 워크플로

> 1. User provides template (.pptx or .potx)
> 2. Analyze template - extract layouts, placeholders, dimensions
> 3. Initialize skill - use the `skill-creator` skill
> 4. Add template - copy .pptx to `assets/template.pptx`
> 5. Write SKILL.md - follow template below
> 6. Create example - generate sample presentation to validate
> 7. Package - use the `skill-creator` skill to package into a .skill file

분석 코드: `python-pptx` `Presentation`; 치수 `/914400` 인치. OBJECT placeholder type == 7의 y가 content start.

> The content area does NOT always start immediately after the subtitle placeholder.

생성 스킬 구조:

```
[company]-ppt-template/
├── SKILL.md
└── assets/
    └── template.pptx
```

PPT-specific rules:

> 1. Template in assets/
> 2. Self-contained SKILL.md
> 3. No manual bullets - use `paragraph.level`
> 4. Delete slides first - always clear existing slides before adding new ones
> 5. Document placeholders by idx

### 입출력

입력: `.pptx` / `.potx` + company/template name + use cases.
출력: 패키징된 `.skill` + example presentation.

### 스크립트

이 스킬 폴더 안에는 스크립트 없음. `skill-creator`의 `init_skill.py` / `package_skill.py`를 사용하라고 본문이 지시.

### PPT 컨벤션

생성 SKILL.md 템플릿에 placeholder 좌표, content area, cover/content 예시 코드가 박혀 있다. 기존 슬라이드 삭제:

```python
while len(prs.slides) > 0:
    rId = prs.slides._sldIdLst[0].rId
    prs.part.drop_rel(rId)
    del prs.slides._sldIdLst[0]
```

### Headless vs Interactive

헤드리스/인터랙티브 분기는 이 SKILL에 없음. 파일 분석 → 스킬 패키징.

---

## 스킬: skill-creator

경로: `skills/skill-creator/` — `SKILL.md`, `LICENSE.txt` (Apache 2.0), `references/{output-patterns,workflows}.md`, `scripts/{init_skill,package_skill,quick_validate}.py`

### 프론트매터

```
name: skill-creator
description: Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations.
license: Complete terms in LICENSE.txt
```

### 트리거

새 스킬 생성 또는 기존 스킬 업데이트.

### 워크플로

> 1. Understand the skill with concrete examples
> 2. Plan reusable skill contents (scripts, references, assets)
> 3. Initialize the skill (run init_skill.py)
> 4. Edit the skill
> 5. Package the skill (run package_skill.py)
> 6. Iterate based on real usage

```
scripts/init_skill.py <skill-name> --path <output-directory>
scripts/package_skill.py <path/to/skill-folder>
scripts/package_skill.py <path/to/skill-folder> ./dist
```

Anatomy:

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter metadata (required)
│   │   ├── name: (required)
│   │   └── description: (required)
│   └── Markdown instructions (required)
└── Bundled Resources (optional)
    ├── scripts/
    ├── references/
    └── assets/
```

Progressive disclosure: metadata always → SKILL.md body on trigger (<5k words, keep under 500 lines) → bundled resources as needed.

> Do not include any other fields in YAML frontmatter.  (본문 Step 4 지침)
> (실제 `quick_validate.py` ALLOWED_PROPERTIES는 `name`, `description`, `license`, `allowed-tools`, `metadata` — 본문과 검증 스크립트가 다름.)

포함하지 말 것: README.md, INSTALLATION_GUIDE.md, QUICK_REFERENCE.md, CHANGELOG.md 등.

### 입출력

입력: 스킬 이름, 경로, 도메인 예시.
출력: 스킬 디렉터리, 이후 `{skill-name}.skill` (zip + `.skill` 확장자).

### 스크립트

**init_skill.py**: Usage `init_skill.py <skill-name> --path <path>`. 이름 요구 (usage print): hyphen-case, lowercase letters/digits/hyphens, max 40 characters, must match directory name. 생성: `SKILL.md`, `scripts/example.py` (chmod 755), `references/api_reference.md`, `assets/example_asset.txt`. 이미 디렉터리 있으면 실패.

**package_skill.py**: `validate_skill` 통과 후에 zip. arcname은 `skill_path.parent` 기준 상대경로. docstring Usage는 `python utils/package_skill.py` (실제 파일 위치는 `scripts/package_skill.py`).

**quick_validate.py**: frontmatter YAML; name hyphen-case `^[a-z0-9-]+$`, max 64 chars; description no `<>`, max 1024 chars; required name+description.

### Excel/PPT 컨벤션

해당 없음 (메타 스킬).

### Headless vs Interactive

해당 없음.

### 레퍼런스

`workflows.md`: Sequential / Conditional workflow 패턴.
`output-patterns.md`: Template pattern (strict vs flexible), Examples pattern (input/output pairs).

### LICENSE.txt

Apache License Version 2.0, January 2004. `http://www.apache.org/licenses/`. TERMS AND CONDITIONS 1–9 + APPENDIX boilerplate. SKILL frontmatter: `license: Complete terms in LICENSE.txt`.

---

## Excel / PPT 컨벤션 대조 (파일에 적힌 것만)

### 폰트 색 (모델)

| 스킬 | Blue | Black | Green | Purple |
|---|---|---|---|---|
| comps-analysis | hardcoded inputs | formulas | (언급 없음) | (없음) |
| dcf-model | RGB 0,0,255 inputs | RGB 0,0,0 formulas | RGB 0,128,0 sheet links | (없음) |
| lbo-model | 0000FF inputs | 000000 formulas | 008000 cross-tab | 800080 same-tab |
| 3-statement-model | `#0000FF` inputs | formulas | `#008000` cross-tab | (없음) |
| xlsx-author | input | formula | link to another sheet/file | (없음) |
| formatting.md (3-stmt) | inputs | formulas | other sheets | (없음); check cells red/green |

### Fill 팔레트 (기본, 템플릿이 우선)

공통적으로 등장: section `#1F4E79`, column `#D9E1F2`, input `#F2F2F2`, output `#BDD7EE`. comps는 header 대안 `#17365D`도 허용.

dcf-model: **borders mandatory**. comps-analysis: **No borders**.

### Headless 산출 경로

- `xlsx-author`: `./out/<name>.xlsx`
- `pptx-author`: `./out/<name>.pptx`
- live Office가 있으면 `mcp__office__excel_*` / `mcp__office__powerpoint_*` 사용, 이 스킬들은 fallback.

### PPT 환경 분기 (덱 스킬)

| 스킬 | Add-in | Chat/headless |
|---|---|---|
| competitive-analysis | build into live deck | generate `.pptx` |
| deck-refresh | edit live runs/cells/charts | regenerate affected slides |
| ib-check-deck | read live (no edits) | read uploaded `.pptx` (no edits) |
| pptx-author | 쓰지 말 것 if live tools exist | write `./out/` |

### 승인 게이트가 있는 스킬

- comps-analysis, dcf-model, lbo-model, 3-statement-model: 섹션별 user verify, end-to-end 금지
- competitive-analysis: outline 승인 전 슬라이드 금지
- deck-refresh: Phase 3 승인 전 편집 금지
- clean-data-xls: destructive 작업 전 확인, 카테고리별 확인
- audit-xls: 보고 먼저, 수정은 요청 시

---

## 커맨드 ↔ 스킬 매핑

| 커맨드 파일 | 로드하는 스킬 |
|---|---|
| `commands/3-statement-model.md` | `3-statement-model` |
| `commands/competitive-analysis.md` | `competitive-analysis` |
| `commands/comps.md` | `comps-analysis` |
| `commands/dcf.md` | `comps-analysis` 후 `dcf-model` |
| `commands/debug-model.md` | `audit-xls` (scope **model**) |
| `commands/lbo.md` | `lbo-model` |
| `commands/ppt-template.md` | `ppt-template-creator` |

커맨드가 없는 스킬: `clean-data-xls`, `deck-refresh`, `ib-check-deck`, `pptx-author`, `xlsx-author`, `skill-creator`.

---

## 스크립트·의존성 요약

### `skills/dcf-model/scripts/validate_dcf.py`

- shebang `#!/usr/bin/env python3`
- `openpyxl.load_workbook` 두 번: `data_only=False` (formulas), `data_only=True` (values)
- recommended sheets `DCF`, `WACC`, `Sensitivity`
- JSON stdout; optional second arg로 파일 저장

### `skills/ib-check-deck/scripts/extract_numbers.py`

- shebang `#!/usr/bin/env python3`
- stdlib only (`argparse`, `json`, `re`, `dataclasses`, `pathlib`, `collections`)
- 슬라이드 마커: `^#+\s*Slide\s*(\d+)` 또는 `^<!-- Slide (\d+)`

### `skills/dcf-model/requirements.txt`

`openpyxl>=3.0.0`, `requests>=2.28.0`

플러그인 루트 requirements.txt 없음.

### SKILL이 가리키지만 이 트리에 없는 경로

- `examples/comps_example.xlsx` (comps-analysis SKILL.md)
- `examples/LBO_Model.xlsx` (lbo-model SKILL.md)
- `recalc.py` / `python /mnt/skills/public/xlsx/recalc.py` (xlsx skill 쪽; 이 플러그인 트리에 파일 없음)
- live-Office `pitch-deck` skill (pptx-author가 mirror한다고 언급)
- `pptx` skill (ppt-template-creator가 실제 발표자료용으로 가리킴)

---

## 파일 간 불일치 (인용만, 해석 추가 없음)

1. `.mcp.json`: egnyte와 box 사이 쉼표 없음; box 객체 닫는 중괄호 없음. JSON 파싱 실패.
2. dcf-model SKILL.md: "Sensitivity tables go at the BOTTOM of the DCF sheet (not on a separate sheet)". `validate_dcf.py`: `required_sheets = ['DCF', 'WACC', 'Sensitivity']`.
3. dcf-model SKILL.md typical TV 50–70% of EV (>75% / <40% flags). `validate_dcf.py` warning if proportion > 0.80 or < 0.40.
4. skill-creator SKILL.md Step 4: "Do not include any other fields in YAML frontmatter." `quick_validate.py` allows `license`, `allowed-tools`, `metadata`. skill-creator 자신의 frontmatter에 `license`가 있다.
5. `package_skill.py` docstring Usage: `python utils/package_skill.py`. 실제 경로: `skills/skill-creator/scripts/package_skill.py`.
6. init_skill.py usage: name max 40 characters. quick_validate.py: name max 64 characters.
7. lbo-model / 3-statement / dcf / comps: Office JS vs openpyxl 분기가 SKILL에 있음. xlsx-author / pptx-author: `mcp__office__excel_*` / `mcp__office__powerpoint_*` vs `./out/` 파일.
8. comps 커맨드 Quality Checklist는 통계에 Max/75th/Median/25th/Min을 요구. comps-analysis SKILL Section 8 간단 레이아웃 예시는 Median/75th/25th만 ASCII 표에 그림 (본문 Section 2는 Max와 Min을 포함).
