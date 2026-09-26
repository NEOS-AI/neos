# Model Builder 전수 분석

범위: `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/` 및 `/Users/yeonwoosung/Desktop/financial-services/managed-agent-cookbooks/model-builder/`.  
방법: 해당 디렉터리의 **모든 파일**을 읽음. CMA overlay·handoff·Write isolation은 cookbook README와 `managed-agent-cookbooks/README.md`, `scripts/orchestrate.py`, `scripts/deploy-managed-agent.sh`, `scripts/validate.py`의 **명시 인용만** 사용. 존재하지 않는 파일·예시·동작을 발명하지 않음.

---

## 1. 파일 목록 (전수)

### 1.1 Cowork 플러그인 (`plugins/agent-plugins/model-builder/`)

| 경로 | 역할 |
|---|---|
| `.claude-plugin/plugin.json` | 플러그인 메타 (`name`, `version`, `description`, `author`) |
| `agents/model-builder.md` | 정규 시스템 프롬프트 (Cowork + CMA 공통 소스) |
| `skills/dcf-model/SKILL.md` | DCF 스킬 |
| `skills/dcf-model/TROUBLESHOOTING.md` | DCF 디버깅 |
| `skills/dcf-model/requirements.txt` | `openpyxl>=3.0.0`, `requests>=2.28.0` |
| `skills/dcf-model/scripts/validate_dcf.py` | DCF 검증 스크립트 |
| `skills/lbo-model/SKILL.md` | LBO 스킬 |
| `skills/3-statement-model/SKILL.md` | 3-statement 스킬 |
| `skills/3-statement-model/references/formatting.md` | 서식 참조 |
| `skills/3-statement-model/references/formulas.md` | 수식 참조 |
| `skills/3-statement-model/references/sec-filings.md` | 10-K/10-Q 추출 참조 |
| `skills/comps-analysis/SKILL.md` | 트레이딩 컴프 스킬 |
| `skills/audit-xls/SKILL.md` | 엑셀 감사 스킬 |
| `skills/xlsx-author/SKILL.md` | 헤드리스 `.xlsx` 산출 스킬 |

플러그인 트리에 `examples/LBO_Model.xlsx`, `examples/comps_example.xlsx`, `recalc.py` **파일은 없음**. LBO/comps/DCF 스킬 본문이 그 경로를 지시하지만, model-builder 번들 안에는 존재하지 않는다.

### 1.2 CMA cookbook (`managed-agent-cookbooks/model-builder/`)

| 경로 | 역할 |
|---|---|
| `agent.yaml` | CMA 오케스트레이터 매니페스트 (`POST /v1/agents`) |
| `README.md` | 배포, steering, security/handoff |
| `steering-examples.json` | steering 이벤트 예시 3건 |
| `subagents/data-puller.yaml` | 리프: CapIQ/Daloopa 입력 수집 (Read-only) |
| `subagents/builder.yaml` | 리프: **유일한 Write 보유자** |
| `subagents/auditor.yaml` | 리프: `./out/model.xlsx` 재검증 (Read-only) |

---

## 2. 시스템 프롬프트

정규 소스는 `plugins/agent-plugins/model-builder/agents/model-builder.md`. CMA `agent.yaml`은 이 파일을 `system.file`로 인라인한 뒤 `system.append`를 붙인다 (`managed-agent-cookbooks/README.md`: `system: {file: ..., append: "..."}` → `system: "<inlined contents + append>"`).

### 2.1 Frontmatter

```
---
name: model-builder
description: Builds DCF, LBO, three-statement, and trading-comps models live in Excel from a ticker and assumption set. Use when you need a clean model from scratch — not for updating an existing coverage model (use earnings-reviewer for that).
tools: Read, Write, Edit, mcp__capiq__*, mcp__daloopa__*
---
```

역할 경계: **scratch 모델**. 기존 coverage 모델 업데이트는 `earnings-reviewer`.

### 2.2 역할 선언 (verbatim)

```
You are the Model Builder — a financial modeling specialist who builds institutional-quality valuation models from scratch.
```

### 2.3 산출물 4종 (verbatim)

```
Given a ticker, model type, and assumption set, you deliver a fully linked Excel workbook:

1. **DCF** — projection period, terminal value, WACC build, sensitivity tables.
2. **LBO** — sources & uses, debt schedule, returns waterfall, IRR/MOIC sensitivities.
3. **Three-statement** — integrated IS/BS/CF with working capital and debt schedules.
4. **Comps** — trading multiples table with summary statistics.
```

### 2.4 오케스트레이터 워크플로 5단계 (verbatim)

```
## Workflow

1. **Pull inputs.** CapIQ/Daloopa MCP for historicals, consensus, and filings.
2. **Build the model.** Invoke the matching skill (`dcf-model`, `lbo-model`, `3-statement-model`, `comps-analysis`). Blue/black/green color coding; no hardcodes in calc cells.
3. **Audit.** Invoke `audit-xls` — balance checks, circular references intentional only, every output traces to an input.
4. **Sensitize.** Build the standard sensitivity tables for the model type.
5. **Surface for review.** Stop after the model is built; user reviews before any downstream use.
```

### 2.5 Guardrails (verbatim)

```
## Guardrails

- **Every output is a formula.** No typed numbers in calculation cells.
- **Cite every input.** Hardcoded assumptions are labeled with source or marked `[ASSUMPTION]`.
- **Stop and surface** after build and again after audit. The user approves before sensitivities.
```

관측된 긴장: Workflow 4단계는 감사 직후 **Sensitize**, Guardrail은 **“The user approves before sensitivities.”** 문서에 해소 규칙이 없다.

### 2.6 에이전트가 쓰는 스킬 목록 (verbatim)

```
## Skills this agent uses

`dcf-model` · `lbo-model` · `3-statement-model` · `comps-analysis` · `audit-xls`
```

시스템 프롬프트 목록에 `xlsx-author`는 **없다**. CMA `builder.yaml`만 명시적으로 `xlsx-author`를 장착한다.

### 2.7 CMA append (verbatim, `agent.yaml`)

```
You are running headless. Produce files in ./out/; do not assume an open Office document.
```

`xlsx-author` SKILL.md: “If `mcp__office__excel_*` tools are available (Cowork plugin mode), use those instead — they drive the user's live workbook with review checkpoints. This skill is the file-producing fallback for headless runs.”

---

## 3. 플러그인 메타데이터

`.claude-plugin/plugin.json` 전문:

```json
{
  "name": "model-builder",
  "version": "0.1.0",
  "description": "DCF, LBO, 3-statement, comps - live in Excel",
  "author": {
    "name": "Anthropic FSI"
  }
}
```

Cowork frontmatter `tools`는 `Read, Write, Edit, mcp__capiq__*, mcp__daloopa__*`. CMA 오케스트레이터 `agent.yaml` tools는 이와 **다르다** (섹션 9).

루트 `README.md` 타일: “DCF, LBO, 3-statement, comps — live in Excel”.  
`managed-agent-cookbooks/README.md` Cowork tile: “DCF, LBO, 3-statement, comps — as a file”.

---

## 4. DCF 워크플로 (`skills/dcf-model/`)

### 4.1 스킬 정체

Frontmatter `name: dcf-model`. description 핵심: “Real DCF (Discounted Cash Flow) model creation for equity valuation. Retrieves financial data from SEC filings and analyst reports, builds comprehensive cash flow projections with proper WACC calculations, performs sensitivity analysis, and outputs professional Excel models with executive summaries.”

Overview: “This skill creates institutional-quality DCF models for equity valuation following investment banking standards. Each analysis produces a detailed Excel model (with sensitivity analysis included at the bottom of the DCF sheet).”

### 4.2 환경 분기: Office JS vs Python/openpyxl (verbatim 요지)

- **Excel (Office Add-in / Office JS):** “Use Office JS directly — do NOT use Python/openpyxl. Write formulas via `range.formulas = [["=D19*(1+$B$8)"]]`. No separate recalc step needed.”
- **Standalone .xlsx:** “Use Python/openpyxl as described below, then run `recalc.py` before delivery.”
- Merged cell pitfall: merge 후 `.values`를 merged range에 넣으면 `InvalidArgument`. “write the value to the top-left cell alone, then merge and format the full range.”

### 4.3 Formulas Over Hardcodes (NON-NEGOTIABLE, verbatim)

```
- Every projection, margin, discount factor, PV, and sensitivity cell MUST be a live Excel formula — never a value computed in Python and written as a number
- When using openpyxl: `ws["D20"] = "=D19*(1+$B$8)"` is correct; `ws["D20"] = calculated_revenue` is WRONG
- The only hardcoded numbers permitted are: (1) raw historical inputs, (2) assumption drivers (growth rates, WACC inputs, terminal g), (3) current market data (share price, debt balance)
- If you catch yourself computing something in Python and writing the result — STOP. The model must flex when the user changes an assumption.
```

### 4.4 사용자 확인 체크포인트 (DO NOT build end-to-end)

1. After data retrieval → raw inputs 확인  
2. After revenue projections → top line/growth 확인  
3. After FCF build → FCF schedule 확인  
4. After WACC → WACC 확인  
5. After terminal value + PV → equity bridge 확인 후 sensitivity  

“Catch errors at each stage — a wrong margin assumption discovered after sensitivity tables are built means rebuilding everything downstream”

### 4.5 프로세스 10단계 (SKILL.md `## DCF Process Workflow`)

**Step 1: Data Retrieval and Validation**  
우선순위: (1) MCP Servers — “Structured financial data from providers like Daloopa”, (2) User-Provided Data, (3) Web Search/Fetch.  
Validation: net debt vs net cash, diluted shares, historical margins, revenue growth vs industry, tax rate “typically 21-28%”.

**Step 2: Historical Analysis (3-5 years)**  
Revenue CAGR, Gross/EBIT/FCF margin, D&A and CapEx % of revenue, NWC, ROIC/ROE. LTM summary table 템플릿 제공.

**Step 3: Build Revenue Projections**  
`Revenue(Year N) = Revenue(Year N-1) × (1 + Growth Rate)`.  
Year 1-2 높은 성장, Year 3-4 산업 평균으로 완화, Year 5+ terminal growth 접근.  
Bear 8-12% / Base 12-16% / Bull 16-20% (예시).

**Step 4: Operating Expense Modeling**  
S&M 15-40% of revenue, R&D 10-30% (tech), G&A 8-15%. “ALL percentages based on REVENUE, not gross profit.” `EBIT = Gross Profit - Total OpEx`.

**Step 5: Free Cash Flow** (verbatim 구조)

```
EBIT
(-) Taxes (EBIT × Tax Rate)
= NOPAT (Net Operating Profit After Tax)
(+) D&A (non-cash expense, % of revenue)
(-) CapEx (% of revenue, typically 4-8%)
(-) Δ NWC (change in working capital)
= Unlevered Free Cash Flow
```

NWC: “-2% to +2% of revenue change”. Maintenance CapEx ~2-3% revenue, Growth CapEx 2-5%.

**Step 6: WACC (CAPM)**

```
Cost of Equity = Risk-Free Rate + Beta × Equity Risk Premium
```

Rf = 10-Year Treasury, Beta = 5-year monthly, ERP = 5.0-6.0%.  
After-Tax Cost of Debt = Pre-Tax × (1 - Tax Rate).  
`WACC = (Cost of Equity × Equity Weight) + (After-Tax Cost of Debt × Debt Weight)`.  
Net cash면 Debt Weight 음수 가능. No debt면 WACC = Cost of Equity.  
Typical: Large Cap 7-9%, Growth 9-12%, High Growth/Risk 12-15%.

**Step 7: Discount (5-10 year, mid-year)**  
Periods 0.5, 1.5, 2.5… `Discount Factor = 1 / (1 + WACC)^Period`.  
5년 standard, 7-10 high growth, 3년 mature.

**Step 8: Terminal Value**  
Preferred: perpetuity growth.

```
Terminal FCF = Final Year FCF × (1 + Terminal Growth Rate)
Terminal Value = Terminal FCF / (WACC - Terminal Growth Rate)
Critical Constraint: Terminal Growth < WACC (otherwise infinite value)
```

Terminal g: Conservative 2.0-2.5%, Moderate 2.5-3.5%, Aggressive 3.5-5.0% (market leaders only). “Do not exceed: Risk-free rate or long-term GDP growth”.  
Alternative: `Terminal Value = Final Year EBITDA × Exit Multiple` (8-15x).  
5-year mid-year: TV period = 4.5.  
Sanity: TV “Should represent 50-70% of Enterprise Value”. “If >75%, model may be over-reliant”. “If <40%, check if terminal assumptions are too conservative”.

**Step 9: EV → Equity bridge**

```
(+) Sum of PV of Projected FCFs
(+) PV of Terminal Value
= Enterprise Value
(-) Net Debt [or + Net Cash if negative]
= Equity Value
÷ Diluted Shares Outstanding
= Implied Price per Share
Implied Return = (Implied Price / Current Price) - 1
```

조정: minority interests, pension, operating leases (if applicable). Diluted shares 사용.

**Step 10: Sensitivity — 3 tables at bottom of DCF sheet (NOT a separate sheet, NOT Excel Data Table)**

1. WACC vs Terminal Growth  
2. Revenue Growth vs EBIT Margin  
3. Beta vs Risk-Free Rate  

규칙: ODD dimensions (5×5, sometimes 7×7). Center = base case. Center fill `#BDD7EE` + bold. “Populate ALL cells (typically 3 tables × 25 cells = 75) with full DCF recalculation formulas”. “NO placeholder text, NO linear approximations, NO manual steps required”.

### 4.6 Scenario blocks + consolidation column

Case selector (예: B6): 1=Bear, 2=Base, 3=Bull.  
각 시나리오 블록은 **세 구조 요소 필수**: (1) merged section header, (2) **column header row showing years (MANDATORY)**, (3) data rows.  
권장: `=INDEX(B10:D10, 1, $B$6)` consolidation column.  
금지: projection 전체에 흩어진 nested IF.  
문서 앞부분 Scenario Blocks는 `=IF($B$6=1,[Bear cell],IF($B$6=2,[Base cell],[Bull cell]))`를 보여 주지만, `<correct_patterns>`는 이를 “NOT this”로 명시. 후자가 정본.

### 4.7 시트 아키텍처 (verbatim)

```
Create **two sheets**:

1. **DCF** - Main valuation model with sensitivity analysis at bottom
2. **WACC** - Cost of capital calculation

**CRITICAL**: Sensitivity tables go at the BOTTOM of the DCF sheet (not on a separate sheet).
```

파일명: `[Ticker]_DCF_Model_[Date].xlsx`.  
Sensitivity 위치 지정: rows 87-100, 102-115, 117-130 (5×5 each).

**불일치:** `validate_dcf.py` `check_sheet_structure()`는 `required_sheets = ['DCF', 'WACC', 'Sensitivity']`를 찾고 없으면 warning “Recommended sheet missing”. SKILL.md는 Sensitivity **별도 시트를 금지**.

### 4.8 Recalc (MANDATORY)

```
python recalc.py [path_to_excel_file] [timeout_seconds]
python recalc.py AAPL_DCF_Model_2025-10-12.xlsx 30
```

“Recalculate all formulas in all sheets using LibreOffice”. 에러: `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#NULL!`, `#NUM!`, `#N/A`. status `"success"`까지 반복.  
model-builder 트리에 `recalc.py` **없음** — “xlsx skill”을 가리킴.

### 4.9 Cell comments (verbatim)

```
"Source: [System/Document], [Date], [Reference], [URL if applicable]"
```

“Add cell comments AS each hardcoded value is created”. “Do not defer to end or write "TODO: add source"”.

### 4.10 TOP 5 ERRORS (verbatim)

1. Formula row references off → Define ALL row positions BEFORE writing formulas  
2. Missing cell comments → Add comments AS cells are created  
3. Simplified sensitivity tables → full DCF recalc, not approximations  
4. Scenario block references wrong  
5. No borders  

추가 카테고리: WACC (book vs market, beta, tax, 10Y, net cash), Growth (g≥WACC, historical inconsistency), Terminal (method, >80% EV, discount period), Cash flow (OpEx on GP, D&A/CapEx, NWC, tax, NOPAT).

### 4.11 Quality rubric / 최소 입력 / 최종 체크리스트

Maximize: realistic assumptions, CAPM WACC, comprehensive sensitivity, clear TV, professional structure, transparent documentation.

Minimum: ticker/name, growth assumptions (or "use consensus"). Optional: projection period (default 5), Bear/Base/Bull, terminal g default 2.5-3.0%, specific WACC inputs.

Final checklist: recalc success; two sheets DCF+WACC; Blue/Black/Green; comments; sensitivity populated; borders; OpEx on revenue; TV 50-70% EV; g < WACC; tax 21-28%; naming `[Ticker]_DCF_Model_[Date].xlsx`.

### 4.12 TROUBLESHOOTING.md

언제: “If recalc.py shows errors OR valuation results seem unreasonable OR case selector not working properly.”

- `#REF!`: 헤더 삽입 후 row shift → layout first.  
- `#DIV/0!`: `=IF([Divisor]=0,0,[Numerator]/[Divisor])`.  
- `#VALUE!`: 입력이 숫자인지.  
- Price too high: TV>80% EV, g≥WACC, optimistic growth/margins.  
- Price too low: net debt vs cash, WACC too high, conservative projections, low g.  
- Case selector: B6 in {1,2,3}, INDEX/OFFSET 범위, `$B$6` absolute.

### 4.13 `validate_dcf.py`

클래스 `DCFModelValidator`: `data_only=False` + `data_only=True` 두 워크북.  
`validate_all()`: `check_sheet_structure`, `check_formula_errors`, `check_dcf_logic`.  
status `'PASS'` iff `len(self.errors)==0`.

`check_dcf_logic`:

- `_check_terminal_growth_vs_wacc`: 인접 셀에서 0<value<1인 terminal growth와 WACC. `terminal_growth >= wacc` → **error** “CRITICAL: … creates infinite value”.  
- `_check_wacc_range`: WACC <5% or >20% → **warning**.  
- `_check_terminal_value_proportion`: `'terminal' and 'value' and 'pv'` vs `'enterprise' and 'value'`. proportion >0.80 또는 <0.40 → warning (typical 50-70%).

CLI: `python validate_dcf.py <excel_file> [output.json]`. PASS면 exit 0, 아니면 1. 예외 시 status `'ERROR'`.

`requirements.txt`: `openpyxl>=3.0.0`, `requests>=2.28.0`. 스크립트 본문은 `requests`를 import하지 않음.

### 4.14 DCF 시트 상세 섹션 (SKILL이 고정한 레이아웃)

Section 1 Header: Row1 company DCF Model, Row2 Ticker|Date|Year End, Row4 Case Selector, Row5 Case Name `=IF([Selector]=1"Bear"IF([Selector]=2"Base""Bull"))` (따옴표/쉼표가 SKILL 원문에 그대로 결여).  
Section 2 Market Data: price, shares, Market Cap formula, Net Debt.  
Section 3 Scenario assumptions (horizontal by year).  
Section 4 Historical & Projected Financials (IS build, OpEx % of revenue).  
Section 5 FCF: NOPAT + D&A − CapEx − ΔNWC.  
Section 6 Discounting & Valuation + IMPLIED PRICE PER SHARE.

WACC sheet: Cost of Equity / Cost of Debt / Capital Structure / WACC CALCULATION. 일부 입력에 “[Yellow input]” 라벨 — DCF 본문의 Blue/Black/Green 규칙과 **표기가 충돌**.

---

## 5. LBO 워크플로 (`skills/lbo-model/SKILL.md`)

### 5.1 스킬 정체

`name: lbo-model`. “completing LBO (Leveraged Buyout) model templates in Excel for private equity transactions, deal materials, or investment committee presentations.”

### 5.2 TEMPLATE REQUIREMENT (verbatim)

```
**This skill uses templates for LBO models. Always check for an attached template file first.**

Before starting any LBO model:
1. **If a template file is attached/provided**: Use that template's structure exactly - copy it and populate with the user's data
2. **If no template is attached**: Ask the user: *"Do you have a specific LBO template you'd like me to use? If not, I can use the standard template which includes Sources & Uses, Operating Model, Debt Schedule, and Returns Analysis."*
3. **If using the standard template**: Copy `examples/LBO_Model.xlsx` as your starting point and populate it with the user's assumptions

**IMPORTANT**: When a file like `LBO_Model.xlsx` is attached, you MUST use it as your template - do not build from scratch. ... Never decide to "build from scratch" when a template is provided.
```

`examples/LBO_Model.xlsx`는 model-builder 플러그인 트리에 **없음**.

### 5.3 Core principles

- Every calculation = Excel formula. Never Python-computed hardcodes.  
- Use template structure; “Do not invent your own layout.”  
- Proper cell references; no typed numbers that should come from other cells.  
- Sign convention follows template.  
- Section-by-section user verification. “Do NOT build the entire model end-to-end”.

### 5.4 LBO 전용 폰트 색 (4색)

- Blue `0000FF`: hardcoded inputs  
- Black `000000`: formulas with operators/functions  
- **Purple `800080`**: same-tab links (`=B9`) — DCF/3-stmt/xlsx-author에는 없음  
- Green `008000`: cross-tab links  

Fill: `#1F4E79` headers, `#D9E1F2` column headers, `#F2F2F2` inputs, white formulas, `#BDD7EE` key outputs (IRR, MOIC, Exit Equity). “3 blues + 1 grey + white.”

Number formats: currency `$#,##0;($#,##0);"-"`, percent `0.0%`, multiples `0.0"x"`, MOIC `0.00"x"`, right-aligned.

### 5.5 작성 계층

1. Check the Template (existing formula, comments, labels, neighbors)  
2. Check the User's Instructions  
3. Apply Standard Practice; document assumptions; ask if uncertain  

### 5.6 COMMON PROBLEM AREAS (verbatim 요지)

- **Balancing:** Sources = Uses, 하나가 plug.  
- **Tax:** income line + tax rate only; “Should NOT reference unrelated sections (e.g., debt schedules)”.  
- **Interest/circ:** “Use **Beginning Balance** (not average or ending) to break circular references”. Pattern: Interest → Cash Flow → Paydown → Ending Balance.  
- **Debt paydown / cash sweeps:** priority waterfall; “Balances cannot go negative - use MAX or MIN”.  
- **IRR/MOIC:** Investment negative, Proceeds positive. XIRR needs dates. `MOIC = Total Proceeds / Total Investment`.  
- **Sensitivity:** ODD 5×5 or 7×7; center = base; `#BDD7EE`+bold; mixed refs `$A5`, `B$4`; “Excel's DATA TABLE function may not work with openpyxl”.

### 5.7 Section-by-section checkpoints

1. After Sources & Uses → balanced table, plug  
2. After Operating Model / Projections → P&L, growth/margins  
3. After Debt Schedule → balances, interest, waterfall  
4. After Returns (IRR/MOIC) → CF signs/ranges  
5. After Sensitivity Tables → each cell varies, base lands correctly  

“Never present a completed model without having checked in at each section”

### 5.8 Verification checklist (완료 후)

`python /mnt/skills/public/xlsx/recalc.py model.xlsx` — “Must return success with zero errors.” 경로는 public xlsx 스킬을 가리키며 model-builder 번들에 해당 파일이 없다.

체크 항목: section balancing; income/operating; BS Assets=L+E + check row zero; CF ending cash; supporting roll-forwards; debt (beginning interest, no negative balances); returns; sensitivity ODD/symmetric/center equals model IRR/MOIC; formatting 4색; no error values; logical sanity.

### 5.9 Common errors table

Hardcoding calculated values; wrong refs after copy; circular refs; sections don't balance; negative balances; IRR sign/range; sensitivity all same value; roll-forwards don't tie; inconsistent signs.

---

## 6. 3-Statement 워크플로 (`skills/3-statement-model/`)

### 6.1 스킬 정체

`name: 3-statement-model`. “Complete, populate and fill out 3-statement financial model templates (Income Statement, Balance Sheet, Cash Flow Statement)”. Trigger: fill/complete/populate existing template. **템플릿 완성**이지 DCF처럼 from-scratch 시트 설계가 주가 아님.

### 6.2 Critical principles

Office JS vs Python 동일 분기. Formulas over hardcodes: “The ONLY cells that should contain hardcoded numbers are: (1) historical actuals, (2) assumption drivers in the Assumptions tab”.

Verify step-by-step:

1. After mapping template  
2. After populating historicals  
3. After IS projections (subtotal checks)  
4. After BS (Assets = L+E every period)  
5. After CF (CF ending cash = BS cash)  
6. “Do NOT populate the entire model end-to-end and present it complete”

### 6.3 탭 식별

Common names: IS/P&L, BS, CF/CFS, WC, DA/D&A/PP&E, Debt, NOL/Tax/DTA, Assumptions/Inputs/Drivers, Checks/Audit/Validation.  
Projection: “typically project 5 years forward”. Labels FY2024A / FY2025E. Named ranges 검토.

### 6.4 선택 섹션 (user prompt 또는 템플릿이 요구할 때만)

**Margin analysis** — skip if no prompt. Gross / EBITDA / EBIT / NI margin, 각 profit line 바로 아래 %.

**Credit metrics** — skip if no prompt. Total Debt/EBITDA, Net Debt/EBITDA, Interest Coverage, Debt/Total Cap, Debt/Equity, Current Ratio, Quick Ratio. Hierarchy: Upside strongest (leverage Upside < Base < Downside). Covenant checks if known.

**Scenario:** Assumptions 탭 toggle, CHOOSE or INDEX/MATCH. Base = guidance/consensus, Upside, Downside. Drivers: Revenue growth, Gross margin, SG&A %, DSO/DIO/DPO, CapEx %, Interest rate, Tax rate. Audit: all statements switch; BS balances; cash ties; Upside > Base > Downside for NI, EBITDA, FCF, margins.

### 6.5 Completing templates — 6 steps

**Step 1 Analyze:** input vs formula (Blue/Black/Green), Trace Precedents, map Assumptions → IS → BS → CF.

**Step 2 Fill without breaking formulas:** only edit inputs; Paste Values; match units; respect sign; circular refs → Enable Iterative Calculation. Never delete rows/columns without checking dependents.

**Step 3 Validate formulas:** Trace Precedents/Dependents, Evaluate Formula, no hardcodes in projections, test values, Ctrl+\ for differences.

**Step 4 Quality by sheet:**

- IS: historicals match source, subtotals, tax on losses, forecast from Assumptions, reasonable PoP.  
- BS: A=L+E, cash = CF ending, WC schedules, RE = Prior RE + NI − Div ± adj, debt schedule, signs.  
- CF: NI matches IS, D&A/SBC add-backs, WC signs (increase in asset = use = negative), CapEx, financing vs BS, Ending Cash = BS Cash, Beginning = prior Ending.  
- Schedules: opening = prior close, Beginning + Additions − Deductions = Ending.

**Step 5 Cross-statement:**

| Check | Formula | Expected |
|---|---|---|
| Balance Sheet Balance | Assets - Liabilities - Equity | = 0 |
| Cash Tie-Out | CF Ending Cash - BS Cash | = 0 |
| Net Income Link | IS Net Income - CF Starting Net Income | = 0 |
| Retained Earnings | Prior RE + NI - Dividends - BS Ending RE | = 0 |

**Step 6 Final:** toggle all scenarios; resolve `#REF!` `#DIV/0!` `#VALUE!` `#NAME?`; no placeholders; consistent units.

### 6.6 Circular reference (verbatim)

```
Interest expense creates circularity: Interest → Net Income → Cash → Debt Balance → Interest

Enable iterative calculation in Excel: File → Options → Formulas → Enable iterative calculation. Set maximum iterations to 100, maximum change to 0.001. Add a circuit breaker toggle in Assumptions tab.
```

### 6.7 Check categories (Checks 탭)

1. Currency consistency  
2. BS integrity A=L+E  
3. CF integrity (cash, monthly vs annual, NI, D&A, SBC, ΔAR/Inv/AP, CapEx)  
4. RE roll-forward (Prior RE + NI + SBC − Div)  
5. WC DSO/DIO/DPO reasonability  
6. Debt schedule  
6b. Equity financing: ΔCS/APIC = Equity Issuance (CFF); Year 0 Equity = Beginning Year 1  
6c. NOL: Y1 beginning 0; increases only if EBT<0; DTA ties; utilization ≤ 80% of EBT (post-2017); non-negative; tax=0 when taxable income ≤ 0  
7. Scenario hierarchy (credit leverage inverted)  
8. Formula integrity: COGS/S&M/G&A/R&D/SBC % of Revenue; no error values  
9. Credit thresholds Green/Yellow/Red  

Master: all pass → “✓ ALL CHECKS PASS”; else “✗ ERRORS DETECTED - REVIEW BELOW”.

### 6.8 `references/formulas.md` 핵심 항등식 (verbatim)

```
Balance Sheet:        Assets = Liabilities + Equity
Net Income:           IS Net Income → CF Operations (starting point)
Cash Flow:            ΔCash = CFO + CFI + CFF
Cash Tie-Out:         Ending Cash (CF) = Cash (BS Asset)
Cash Monthly/Annual:  Closing Cash (Monthly) = Closing Cash (Annual)
Retained Earnings:    Prior RE + Net Income - Dividends = Ending RE
Equity Raise:         ΔCommon Stock/APIC (BS) = Equity Issuance (CFF)
Year 0 Equity:        Equity Raised (Year 0) = Beginning Equity (Year 1)
```

**Gross Profit:** “must be calculated from Net Revenue, not Gross Revenue.” `Net Revenue - Cost of Revenue = Gross Profit`.

Forecast: Cost of Revenue / S&M / G&A / R&D / SBC = Net Revenue × % assumption.

WC: AR/Inventory/AP roll-forwards with DSO=(AR/Rev)×365, DIO=(Inv/COGS)×365, DPO=(AP/COGS)×365. NWC = AR + Inventory − AP.

DA: Gross PP&E + CapEx; Accum Dep + Dep Exp; Net = Gross − Accum.

Debt: Beg + Borrowings − Repayments. Interest = Avg Debt × Rate, “Use beginning balance to avoid circularity, or iterate if circular refs enabled”.

RE: Beg + NI + SBC − Div.

NOL: Beg Y1=0; Generated = ABS(EBT) if EBT<0; Utilized = MIN(available, EBT×80%); Taxes Payable = MAX(0, Taxable Income × Tax Rate); DTA = Ending NOL × Tax Rate.

IS structure ends: EBT → NOL Utilization → Taxable Income → Taxes → Net Income.

### 6.9 `references/formatting.md`

Font: inputs blue, formulas black, cross-sheet green, check cells red if error / green if balanced. Negatives in parentheses. Currency no decimals for large, 2 for per-share. Percentages 1 decimal. Headers bold + bottom border. Units row.

Visual: thin vertical between historical/projected; thick bottom after section totals; single bottom subtotals; double bottom grand totals. Totals/subtotals **bold** (IS/BS/CF 목록 제공, “non-exhaustive”).

BS check custom format: `[Red][<>0]0.00;[Red][<>0](0.00);0.00`.

Credit threshold colors:

| Metric | Green | Yellow | Red |
|---|---|---|---|
| Total Debt / EBITDA | < 2.5x | 2.5x-4.0x | > 4.0x |
| Net Debt / EBITDA | < 2.0x | 2.0x-3.5x | > 3.5x |
| Interest Coverage | > 4.0x | 2.5x-4.0x | < 2.5x |
| Debt / Total Cap | < 40% | 40%-60% | > 60% |
| Current Ratio | > 1.5x | 1.0x-1.5x | < 1.0x |
| Quick Ratio | > 1.0x | 0.75x-1.0x | < 0.75x |

Margin flags: GM<0% ERROR; GM>80% WARNING; EBITDA<0 FLAG; EBITDA>50% WARNING; NI<0 FLAG (may be acceptable); NI margin > GM ERROR.

Checks tab: pass green fill, fail red, warning yellow; difference=0 light green, ≠0 light red.

### 6.10 `references/sec-filings.md`

“Only reference this file when a model template specifically requires pulling data from SEC filings (10-K, 10-Q).”

EDGAR: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=[TICKER]&type=10-K` (10-Q는 `type=10-Q`).  
Item 8 (10-K) / Item 1 (10-Q). Currency from cover/Note 1. 최소 3년: 10-K는 IS/CF 3년, BS 2년 → 3년차 BS는 prior 10-K.  
매핑 표: IS (Net revenues→Revenue, COGS, SG&A, D&A, Interest, Tax, NI), BS (Cash, AR, Inventory, PP&E net, Total Assets, AP, ST/LT Debt, RE, Equity), CF (NI, D&A, ΔAR/Inv/AP, CapEx, equity issuance, debt, dividends).  
Notes: Debt, PP&E, Revenue, Leases.  
Checklist: currency/scale, 3yr IS/CF/BS, IS NI = CF NI, BS Cash = CF Ending Cash, debt maturity, D&A/lives, one-time items.  
Variations: D&A in COGS/SG&A → pull from CF; restatements; FY ≠ calendar; non-USD.

---

## 7. Comps 워크플로 (`skills/comps-analysis/SKILL.md`)

### 7.1 스킬 정체 / 적합성

Perfect for: public valuation (M&A, investment), peer benchmarking, IPO/funding pricing, outliers, IC, sector overviews.  
Not ideal for: private w/o public peers, conglomerates, distressed/bankrupt, pre-revenue startups, unique business models.

### 7.2 Data source priority (CRITICAL, verbatim)

```
1. **FIRST: Check for MCP data sources** - If S&P Kensho MCP, FactSet MCP, or Daloopa MCP are available, use them exclusively for financial and trading information
2. **DO NOT use web search** if the above MCP data sources are available
3. **ONLY if MCPs are unavailable:** Then use Bloomberg Terminal, SEC EDGAR filings, or other institutional sources
4. **NEVER use web search as a primary data source**
```

에이전트 시스템 프롬프트/CMA tools는 **CapIQ + Daloopa**만 연결. Kensho/FactSet는 이 스킬 문장의 일반 우선순위이며, model-builder `agent.yaml` mcp_servers에는 없음.

### 7.3 예시 파일

“An example comparable company analysis is provided in `examples/comps_example.xlsx`.”  
**DO** use for hierarchy/rigor/principles. **DO NOT** exact reproduction. Always ask preferred format, audience, key question, context.  
model-builder 트리에 해당 xlsx **없음**.

### 7.4 Philosophy / 확인 단계

“Build the right structure first, then let the data tell the story.”  
Checkpoints: structure → raw inputs/sources → operating metrics → valuation multiples. “Do NOT build the entire sheet end-to-end”.

### 7.5 구조

Header rows 1-3: title, company list with tickers, “As of [Period] | All figures in [USD Millions/Billions] except per-share amounts and ratios”.

**Section 2 Operating:** Company, Revenue, Revenue Growth, Gross Profit, Gross Margin, EBITDA, EBITDA Margin. Optional: quarterly vs LTM, FCF/FCF margin, NI, OpInc, CapEx, Rule of 40, FCF Conversion.

Statistics after company rows (blank row, **no** “SECTOR STATISTICS” header): MAX, QUARTILE(,3), MEDIAN, QUARTILE(,1), MIN.  
Statistics **needed** on ratios/margins/growth/multiples. **Not** on size (Revenue, EBITDA, NI, Mkt Cap, EV).

**Section 3 Valuation:** Company, Market Cap, EV, EV/Revenue, EV/EBITDA, P/E. Optional FCF yield, PEG, P/B, ROE/ROA, CAGR, asset turnover, D/E.  
“Valuation multiples MUST reference the operating metrics section. Never input the same raw data twice.”

**Section 4 Notes:** sources (MCP/Bloomberg/SEC), period, verification, EBITDA/FCF definitions, EV method, thesis/metrics interpretation.

### 7.6 5-10 Rule / 질문 프레임

5 operating + 5 valuation = 10 columns. “If you have more than 15 metrics, you're probably including noise.”

질문별: undervalued → EV/Rev, EV/EBITDA, P/E, Mkt Cap; efficiency → margins, FCF, AT; growth → growth/CAGR; cash → FCF metrics.

Industry: SaaS (growth, GM, Rule of 40); Manufacturing (EBITDA margin, AT, CapEx/Rev); Financials (ROE, ROA, Efficiency, P/E — skip GM/EBITDA); Retail (growth, GM, inventory turns).

### 7.7 Sanity / red flags

Margin test: GM > EBITDA margin > NI margin.  
Multiples typical: EV/Rev 0.5-20x, EV/EBITDA 8-25x, P/E 10-50x.  
Red: mixed periods; missing data; >10% source variance; negative EBITDA on EBITDA multiples; P/E>100x w/o hypergrowth; FYE mismatch; mixing pure-play and conglomerates. “When in doubt, exclude the company. Better to have 3 perfect comps than 6 questionable ones.”

문서 오타 원문 유지: “🚩ixing pure-play and conglomerates”.

### 7.8 Comps 서식 (DCF와 충돌하는 지점)

Defaults: Times New Roman 11pt data / 12pt headers; **No borders (clean, minimal appearance)**; metrics **center-aligned**; uniform column widths; row height 20-25pt; one blank row before stats; no separate statistics header rows.  
DCF SKILL은 “Borders are mandatory”. 모델 타입별로 스킬이 갈린다.

Workflow 시간 가이드: structure 30m, gather 60-90m, formulas 30m, stats 15m, QC 30m, docs 15m.

Output checklist: comparable companies, consistent periods, units labeled, formulas not hardcodes, comments on every hardcode, hyperlinks, ≥5 stats metrics, notes, blue/black, sanity, date stamp, no #DIV/0!/#REF!/#N/A.

---

## 8. 감사 스킬 (`skills/audit-xls/SKILL.md`)

시스템 프롬프트: “Invoke `audit-xls` — balance checks, circular references intentional only, every output traces to an input.”  
CMA auditor.yaml: “per check-model conventions” — **저장소에 `check-model` 스킬/파일은 없음**. 실제 장착 스킬은 `audit-xls`.

### 8.1 Scope

Ask if unspecified: **selection** / **sheet** / **model**.  
“The **model** scope is the deepest — use it for DCF, LBO, 3-statement, merger, comps, or any integrated financial model before sending to a client or IC.”

### 8.2 Formula-level (ALL scopes)

`#REF!` `#VALUE!` `#N/A` `#DIV/0!` `#NAME?`; hardcodes inside formulas (`=A1*1.05`); inconsistent formulas; off-by-one SUM/AVERAGE; pasted-over formulas; circular refs; broken cross-sheet links; unit/scale mismatches; hidden rows/tabs.

### 8.3 Model-integrity (MODEL scope)

Structural: input/formula separation; Blue=input, black=formula, green=link; tab flow Assumptions → IS → BS → CF → Valuation; date headers; units.

BS: A=L+E every period; RE rollforward Prior RE + NI − Div; goodwill from acquisition if M&A. “If BS doesn't balance, **quantify the gap per period and trace where it breaks** — nothing else matters until this is fixed.”

CF: Ending Cash = BS Cash; CFO+CFI+CFF=ΔCash; D&A CF=IS; CapEx vs PP&E; WC signs.

IS: revenue build; Tax = EBT × rate (deferred adj allowed); share count vs dilution.

Circ: “Interest → debt balance → cash → interest is a common intentional circ in LBO/3-stmt models”. Intentional → iteration toggle; else trace/flag.

Logic flags: >100% revenue growth unexplained; margins outside norms; TV > ~75% of DCF EV (yellow); hockey-stick; EBITDA absurd by Y10; breaks at 0%/negative growth, negative EBITDA, negative leverage.

Type-specific:

- **DCF:** wrong discount period (mid vs end); TV not discounted; WACC book not market; FCF includes interest (should be unlevered); tax shield double-counted.  
- **LBO:** paydown ≠ cash sweep; PIK not accruing; management rollover missing; exit multiple on wrong EBITDA (LTM vs NTM); fees not deducted from Day 1 equity.  
- **Merger:** accretion/dilution share count; synergies phasing; PPA; foregone interest; fees in S&U. (시스템 프롬프트 4종에 merger는 없음 — audit 스킬 일반 범위)  
- **3-statement:** WC sign; Dep vs PP&E; debt maturity vs principal; dividends > NI unexplained.

### 8.4 Report

Table: `# | Sheet | Cell/Range | Severity | Category | Issue | Suggested Fix`  
Severity: Critical (wrong output), Warning (hardcodes/inconsistent/edge), Info (style).  
Model summary: `Model type: [DCF/LBO/3-stmt/...] — Overall: [Clean / Minor Issues / Major Issues] — [N] critical, [N] warnings, [N] info`  
“**Don't change anything without asking** — report first, fix on request.”

Notes: “BS balance first”; “Hardcoded overrides are the #1 source of silent bugs”; sign convention errors common; VBA macros “can't be audited from formulas alone”.

---

## 9. CMA overlay

### 9.1 한 소스, 두 래퍼

`managed-agent-cookbooks/README.md`: “Every agent in this repo ships **two ways** … **Same agent, same skills — pick your surface.**”  
`CLAUDE.md`: `agents/<slug>.md` ← “canonical system prompt (one source, two wrappers)”.  
model-builder cookbook README: “Same source as the [`model-builder`](../../plugins/agent-plugins/model-builder) Cowork plugin — this directory is the Managed Agent cookbook for `POST /v1/agents`.”

Cookbook 표 행:

```
| [`model-builder`](./model-builder/) | financial-analysis | DCF, LBO, 3-statement, comps — as a file | `Build <dcf\|lbo\|3-stmt> for <ticker>, assumptions: {...}` | data-puller · **builder** · auditor |
```

“**Bold** leaf = the only worker with `Write`.”

### 9.2 `agent.yaml` 전문 구조

```
name: model-builder
model: claude-opus-4-7

system:
  file: ../../plugins/agent-plugins/model-builder/agents/model-builder.md
  append: "You are running headless. Produce files in ./out/; do not assume an open Office document."

tools:
  - type: agent_toolset_20260401
    default_config: { enabled: false }
    configs:
      - { name: read,  enabled: true }
      - { name: grep,  enabled: true }
      - { name: glob,  enabled: true }
  - { type: mcp_toolset, mcp_server_name: capiq,   default_config: { enabled: true } }
  - { type: mcp_toolset, mcp_server_name: daloopa, default_config: { enabled: true } }

mcp_servers:
  - { type: url, name: capiq,   url: "${CAPIQ_MCP_URL}" }
  - { type: url, name: daloopa, url: "${DALOOPA_MCP_URL}" }

skills:
  - { from_plugin: ../../plugins/agent-plugins/model-builder }

callable_agents:
  - { manifest: ./subagents/data-puller.yaml }
  - { manifest: ./subagents/builder.yaml }       # only leaf with Write
  - { manifest: ./subagents/auditor.yaml }
```

오케스트레이터 도구: **Read, Grep, Glob만**. Write/Edit/Bash **없음**. MCP CapIQ+Daloopa 활성.  
`from_plugin`은 플러그인 `skills/*` 전부 업로드 (`deploy-managed-agent.sh`: `for sk in "$plugdir"/skills/*/`). 따라서 오케스트레이터에도 dcf/lbo/3-stmt/comps/audit-xls/xlsx-author가 스킬로 붙지만, Write가 없어 파일 산출은 builder에 위임하는 설계.

`callable_agents` preview: “supports **one delegation level**. An orchestrator can call workers; workers cannot call further subagents.” 세 리프 모두 `callable_agents: []`.

### 9.3 매니페스트 → API 해석 (`managed-agent-cookbooks/README.md`)

| Manifest | Resolves to |
|---|---|
| `system: {file: ..., append: "..."}` | inlined contents + append |
| `system: {text: "..."}` | text |
| `skills: [{from_plugin: ...}]` | upload every `skills/*` → custom skill_id |
| `skills: [{path: ...}]` | custom skill_id |
| `callable_agents: [{manifest: ...}]` | `{type: agent, id, version: latest}` |

Deploy: `export ANTHROPIC_API_KEY=...`; `export CAPIQ_MCP_URL=... DALOOPA_MCP_URL=...`; `../../scripts/deploy-managed-agent.sh model-builder`.

`deploy-managed-agent.sh`: `${CAPIQ_MCP_URL}` 치환은 `[A-Za-z0-9._/:@-]`만 허용. beta `managed-agents-2026-04-01`, skills `skills-2025-10-02`. `output_schema`는 POST body에서 `del(.output_schema)`. metadata `anthropic_cookbook: ${REPO_SLUG}/model-builder`.

### 9.4 Cowork vs CMA 도구 차이 (문서에 적힌 사실만)

| | Cowork `model-builder.md` frontmatter | CMA `agent.yaml` orchestrator |
|---|---|---|
| 모델 편집 | `Write`, `Edit` | 없음 (Read/Grep/Glob) |
| MCP | `mcp__capiq__*`, `mcp__daloopa__*` | capiq, daloopa toolsets |
| 산출 | “live in Excel” | `./out/` 파일, “do not assume an open Office document” |
| 스킬 xlsx-author | 시스템 프롬프트 목록에 없음 | builder.yaml path로 장착; from_plugin으로 오케스트레이터에도 업로드 |

---

## 10. Leaf workers

### 10.1 `data-puller` (`subagents/data-puller.yaml`)

```
name: model-data-puller
model: claude-opus-4-7
system:
  text: |
    You pull historicals and consensus from CapIQ/Daloopa for the requested
    ticker and return a structured input table. Read-only.
```

Tools: Read, Grep + CapIQ/Daloopa MCP. `mcp_servers` 동일 URL 템플릿. `skills: []`. `callable_agents: []`.

`output_schema` (additionalProperties: false at root):

```
required: [ticker, historicals]
ticker: { type: string, maxLength: 12, pattern: "^[A-Z.]+$" }
historicals: object, additionalProperties: { type: number }
consensus: object, additionalProperties: { type: number }   # not in required
```

`validate.py`: “The CMA API does not enforce structured output today, so the deploy harness runs this between a reader subagent and the orchestrator. Schemas live in each subagent yaml under `output_schema:` — the deploy script extracts them.”  
`deploy-managed-agent.sh` 헤더: “Reader subagents with an `output_schema` block get a thin validation wrapper so their JSON is schema-checked before the orchestrator consumes it.” 스크립트 본문은 schema를 POST에서 **삭제**할 뿐, 래퍼 생성 코드는 이 파일에 보이지 않음.

### 10.2 `builder` (`subagents/builder.yaml`) — Write-holder

```
name: model-builder-builder
model: claude-opus-4-7
system:
  text: |
    You are the ONLY worker with Write. Build the requested model
    (DCF/LBO/3-stmt/comps) into ./out/model.xlsx using xlsx-author conventions.
    Inputs are the validated table from data-puller plus user assumptions.
```

Tools: Read, **Write**, **Edit**, **Bash**. `mcp_servers: []` (데이터 MCP 없음).  
Skills (path): `dcf-model`, `lbo-model`, `3-statement-model`, `comps-analysis`, `xlsx-author`. **audit-xls 없음**.  
`callable_agents: []`.

Cookbook README는 Bash를 “(sandboxed)”로 표기. yaml 자체에 sandbox 키는 없음.

산출 경로 고정: `./out/model.xlsx` (DCF 스킬의 `[Ticker]_DCF_Model_[Date].xlsx`와 **파일명 규칙이 다름**).

### 10.3 `auditor` (`subagents/auditor.yaml`)

```
name: model-auditor
model: claude-opus-4-7
system:
  text: |
    You re-check ./out/model.xlsx for ties, balance checks, and hardcodes per
    check-model conventions. Read-only — return a pass/fail report with
    locations of any issues.
```

Tools: Read, Grep only. MCP 없음. Skill: `audit-xls` only. `callable_agents: []`.  
Write 없음 → audit-xls의 “Don't change anything without asking — report first”와 정합.  
“check-model conventions”는 이름만 있고 대응 파일 없음; 실제 컨벤션 문서는 `audit-xls`.

### 10.4 리프 비교 (cookbook README 표 + yaml)

| Leaf | Tools (README) | Connectors | Skills (yaml) | 산출 |
|---|---|---|---|---|
| `data-puller` | `Read`, `Grep` | CapIQ, Daloopa (read-only) | 없음 | schema JSON (ticker, historicals, optional consensus) |
| **`builder`** (Write-holder) | `Read`, `Write`, `Edit`, `Bash` (sandboxed) | None | dcf, lbo, 3-stmt, comps, xlsx-author | `./out/model.xlsx` |
| `auditor` | `Read`, `Grep` | None | audit-xls | pass/fail report + locations |

README: “`auditor` re-checks ties and balances after `builder` writes `./out/model.xlsx`.”

---

## 11. Write isolation

Cookbook README 원문:

```
Task-decomposition split — inputs come from trusted MCPs, so the split is about artifact isolation and re-verification. Exactly one worker holds `Write`:
```

요지:

- 입력은 **trusted MCP** (CapIQ/Daloopa). earnings-reviewer/market-researcher의 “untrusted docs” 3-tier와 **다른 근거**.  
- 목적은 문서 격리보다 **artifact isolation + re-verification**.  
- Write는 **builder만**. 오케스트레이터도 Write 없음.  
- builder는 MCP 없음 → 시트를 외부 데이터 툴로 직접 쓰지 못함. 입력은 “validated table from data-puller plus user assumptions”.  
- auditor는 읽기만, 파일 수정 불가.  
- `agent.yaml` 주석: `{ manifest: ./subagents/builder.yaml }       # only leaf with Write`.  
- 상위 표: “**Bold** leaf = the only worker with `Write`.”

xlsx-author 계약:

```
- Write to `./out/<name>.xlsx`. Create `./out/` if it does not exist.
- Return the relative path in your final message so the orchestration layer can collect it.
- **One model per file.** Do not append to an existing workbook unless explicitly asked.
```

builder 시스템 텍스트는 파일명을 `./out/model.xlsx`로 고정.

---

## 12. Steering

### 12.1 예시 (`steering-examples.json` 전문)

```json
[
  { "event": "Build dcf for MSFT, assumptions: {wacc: 0.085, tgr: 0.025, horizon: 5}", "description": "DCF with explicit assumptions" },
  { "event": "Build lbo for TGT, assumptions: {entry_multiple: 9.0, leverage: 5.5, hold: 5}", "description": "LBO from entry multiple and leverage" },
  { "event": "Build 3-stmt for SHOP, source: latest 10-K", "description": "Three-statement from filings" }
]
```

Comps 전용 steering 예시는 **이 파일에 없음**. 상위 표 패턴은 `Build <dcf|lbo|3-stmt> for <ticker>, assumptions: {...}` — comps 토큰도 없음.

Cookbook README: “See [`steering-examples.json`](./steering-examples.json).”

### 12.2 인바운드 handoff (다른 에이전트 → model-builder)

Named agents “never call each other directly”. `handoff_request` → `scripts/orchestrate.py` (또는 Temporal/Airflow/Guidewire)가 **새 steering event**.

문서화된 호출자:

- **pitch-agent:** “to rebuild the model after a thesis change, the orchestrator emits a `handoff_request` for `model-builder`”  
- **earnings-reviewer:** “to rebuild a DCF after an earnings-driven thesis change, emit a `handoff_request` for `model-builder`”  
- **market-researcher:** “to model a single name surfaced in the ideas shortlist, emit a `handoff_request` for `model-builder`”

model-builder cookbook: “**Handoff:** when invoked from `earnings-reviewer` or `pitch-agent`, the calling agent's `handoff_request` is routed here by `scripts/orchestrate.py`.” (market-researcher는 이 README 문장에 없음.)

### 12.3 `orchestrate.py` 허용·스키마

`ALLOWED_TARGETS`에 `"model-builder"` 포함.

```
HANDOFF_PAYLOAD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["event"],
    "properties": {
        "event": {"type": "string", "maxLength": 2000},
        "context_ref": {"type": "string", "maxLength": 256,
                        "pattern": r"^[A-Za-z0-9 ._/:#-]+$"},
    },
}
HANDOFF_RE = re.compile(r'\{"type":\s*"handoff_request".*?\}', re.DOTALL)
```

target이 allowlist 밖이거나 payload 검증 실패면 `None` (무시).  
성공 시 `client.beta.agents.sessions.steer(agent_id=target_id, input=handoff["payload"]["event"])`.

스크립트 헤더: REFERENCE ONLY. “handoff requests are surfaced in the orchestrator's text output, which is downstream of untrusted-document readers.” 완화: (a) hard-allowlist, (b) schema-validate. “In production, prefer emitting handoffs via a dedicated tool call or a typed SSE event the model cannot produce by quoting document text.”

---

## 13. Security

### 13.1 model-builder 고유 티어

README 원문 재인용: “inputs come from trusted MCPs, so the split is about artifact isolation and re-verification.”

| 통제 | 문서상 내용 |
|---|---|
| Write 단일화 | builder만 Write/Edit/Bash |
| MCP 분리 | 데이터 MCP는 오케스트레이터 + data-puller. builder/auditor는 `mcp_servers: []` |
| 입력 스키마 | data-puller ticker `^[A-Z.]+$`, maxLength 12; historicals/consensus 값은 number; root additionalProperties false |
| 재검증 | auditor가 `./out/model.xlsx` ties/balances/hardcodes, pass/fail + locations |
| 헤드리스 산출 경로 | `./out/` only |
| 인간 승인 | 시스템 프롬프트 “Stop after the model is built; user reviews before any downstream use”; Guardrail “Stop and surface after build and again after audit” |
| CMA API 키/URL | deploy 시 `ANTHROPIC_API_KEY`, `CAPIQ_MCP_URL`, `DALOOPA_MCP_URL`; URL 문자 화이트리스트 |

Cowork 플러그인 시스템 프롬프트는 오케스트레이터에 Write/Edit를 준다. Write isolation은 **CMA leaf split**에만 존재.

### 13.2 크로스 에이전트 위협 모델 (`orchestrate.py`)

handoff blob이 untrusted document에서 echo될 수 있음 → allowlist + payload schema. model-builder는 그 타깃 중 하나.

### 13.3 루트 면책 (`financial-services/README.md`)

“Nothing in this repository constitutes investment, legal, tax, or accounting advice. These agents draft analyst work product — models, memos, research notes, reconciliations — for review by a qualified professional. They do not make investment recommendations, execute transactions, bind risk, post to a ledger, or approve onboarding; every output is staged for human sign-off.”

시스템 프롬프트 “Surface for review”와 일치.

### 13.4 다른 에이전트와의 대조 (혼동 방지)

earnings-reviewer/market-researcher: untrusted docs → reader는 Read/Grep only, length-capped schema JSON, Write-holder는 문서에 손대지 않음.  
model-builder README는 그 패턴을 **채택하지 않고** trusted-MCP + artifact isolation이라고 **명시**.

### 13.5 `output_schema`와 CMA API

`validate.py`: CMA API는 structured output을 강제하지 않음. 하니스가 reader와 orchestrator 사이에서 검증.  
deploy는 POST 전 `output_schema` 삭제 (`test-cookbooks.sh`: “output_schema leaked into a body”면 실패).

---

## 14. Excel conventions

여러 스킬이 겹치되 **완전히 동일하지 않음**. 아래는 파일별 원문.

### 14.1 오케스트레이터 / xlsx-author / audit-xls 공통 3색

시스템 프롬프트: “Blue/black/green color coding; no hardcodes in calc cells.”

xlsx-author:

```
- **Blue / black / green.** Blue = hardcoded input, black = formula, green = link to another sheet/file.
- **No hardcodes in calc cells.** Every calculation cell is a formula; every input lives on an Inputs tab.
- **Named ranges** for any value referenced from a deck or memo.
- **Balance checks.** Include a Checks tab that ties (BS balances, CF ties to cash, etc.) and surfaces TRUE/FALSE.
- **One model per file.**
```

xlsx-author 예시 코드: `Font(color="0000FF")` on input; formula `=Inputs!C2*(1+Inputs!C3)`; save `./out/model.xlsx`.

audit-xls: “Blue=input, black=formula, green=link — or whatever the model uses, applied consistently”.

### 14.2 DCF / 3-statement fill palette (3 blues + 1 grey + white)

| Element | Fill | Font |
|---|---|---|
| Section headers | Dark blue `#1F4E79` | White bold |
| Column/sub headers | Light blue `#D9E1F2` | Black bold |
| Input cells | Light grey `#F2F2F2` or white | Blue `#0000FF` |
| Formula cells | White | Black |
| Cross-tab links | White | Green `#008000` |
| Output/check/summary | Medium blue `#BDD7EE` | Black bold |

“Do NOT introduce greens, yellows, oranges, or multiple accent colors.”  
“Font color tells you WHAT it is (input/formula/link). Fill color tells you WHERE you are (header/data/output).”  
User/template 색이 항상 override.

### 14.3 LBO 4색 폰트 + 동일 fill

Blue / Black / **Purple same-tab** / Green cross-tab. Fill은 위와 동일 (`#1F4E79` / `#D9E1F2` / `#F2F2F2` / white / `#BDD7EE`).

### 14.4 숫자 형식

DCF: Years as text (“2024” not “2,024”); % `0.0%`; currency `$#,##0` millions, `$#,##0.00` per-share; zeros `$#,##0;($#,##0);-`; negatives `(#,##0)`; units in headers (“Revenue ($mm)”).

LBO: currency `$#,##0;($#,##0);"-"` or `$#,##0.0`; % `0.0%`; multiples `0.0"x"`; MOIC `0.00"x"`; right-aligned.

3-stmt formatting.md: negatives parentheses; large figures no decimals, per-share 2; % 1 decimal; leverage `2.5x`.

Comps: % 1 decimal; multiples 1 decimal; dollars no decimals + thousands sep; **center-aligned**; **no borders**.

### 14.5 Borders

DCF: **mandatory**. Thick 1.5pt major sections (KEY INPUTS, PROJECTION ASSUMPTIONS, 5-YEAR CF, TV, VALUATION SUMMARY, each sensitivity table); medium 1pt sub-sections; thin 0.5pt data tables; “No borders: Individual cells within tables”.

3-stmt: thin vertical historical vs projected; thick after section totals; single subtotals; double grand totals.

Comps: “No borders (clean, minimal appearance)”.

### 14.6 Comments / `[ASSUMPTION]`

시스템: “Hardcoded assumptions are labeled with source or marked `[ASSUMPTION]`.”  
DCF/comps: comment AS created, format “Source: [System/Document], [Date], [Reference], [URL if applicable]”. Comps는 assumption explanation 또는 hyperlink도 허용.

### 14.7 Sensitivity 공통 (DCF + LBO)

ODD grid; symmetric axes `[base-2Δ, base-Δ, base, base+Δ, base+2Δ]`; center = model output; `#BDD7EE`+bold; live formulas not Data Table; no placeholders/linear approx.

### 14.8 Office JS merged cells (DCF/LBO/3-stmt/comps 동일 함정)

`.merge()` 후 merged range에 `.values` 금지 → `InvalidArgument`. 좌상단 셀에 값 → 그다음 merge + format.

### 14.9 Recalc / 에러

DCF/LBO: `recalc.py` + LibreOffice (DCF 명시). Zero `#REF!` `#DIV/0!` `#VALUE!` `#NAME?` 등.  
경로 표기 불일치: DCF `python recalc.py model.xlsx 30`; LBO `python /mnt/skills/public/xlsx/recalc.py model.xlsx`. 둘 다 model-builder 번들에 스크립트 없음.

### 14.10 Checks 탭

xlsx-author: Checks tab TRUE/FALSE.  
3-stmt: master “✓ ALL CHECKS PASS” / “✗ ERRORS DETECTED - REVIEW BELOW”.  
audit-xls: findings table, don't fix unless asked.

---

## 15. 문서 간 불일치 (관측, 해석 발명 없음)

1. **Sensitivity 순서:** Workflow 4 = Sensitize after audit. Guardrail = user approves **before** sensitivities.  
2. **xlsx-author:** CMA builder 필수, 시스템 프롬프트 스킬 목록에 없음.  
3. **파일명:** DCF `[Ticker]_DCF_Model_[Date].xlsx` vs builder `./out/model.xlsx`.  
4. **Sensitivity 시트:** DCF SKILL = bottom of DCF sheet only. `validate_dcf.py`는 `Sensitivity` 시트 권장.  
5. **WACC 입력 색:** WACC sheet “[Yellow input]” vs 전역 Blue inputs.  
6. **Scenario IF vs INDEX:** 앞부분은 nested IF, `<correct_patterns>`는 nested IF를 금지하고 INDEX consolidation을 요구.  
7. **check-model:** auditor 시스템 텍스트에만 등장. 실제 스킬 `audit-xls`.  
8. **LBO/comps 예시 xlsx, recalc.py:** 스킬이 가리키는 경로가 플러그인 트리에 없음.  
9. **Purple:** LBO만 same-tab purple. xlsx-author/DCF/3-stmt는 3색.  
10. **Borders:** DCF mandatory vs comps no borders.  
11. **TV 임계:** DCF sanity 50-70%, flag >75%; common mistakes >80%; validate_dcf warning >80% or <40%; audit-xls yellow TV>~75%.  
12. **오케스트레이터 Write:** Cowork frontmatter Write/Edit vs CMA orchestrator Read-only.  
13. **Comps MCP 이름:** 스킬은 Kensho/FactSet/Daloopa; 에이전트 MCP는 CapIQ/Daloopa.  
14. **Handoff README:** model-builder는 earnings-reviewer·pitch-agent만 언급. market-researcher README는 model-builder로 handoff한다고 적음.  
15. **Steering 예시:** DCF/LBO/3-stmt만. 시스템 프롬프트 4번째 산출 Comps에 대한 event 없음.  
16. **Case Name 수식:** DCF header `=IF([Selector]=1"Bear"IF([Selector]=2"Base""Bull"))` — 원문에 쉼표/괄호 누락.  
17. **validate_dcf `requests`:** requirements에 있으나 스크립트 미사용.  
18. **3-stmt RE 공식:** Step 5 `Prior RE + NI - Dividends`; Core Linkages/Section 4는 `+ SBC`. formulas.md 상단 Core Linkages는 SBC 없이, 이후 RE Formula는 SBC 포함.

---

## 16. 인용 원천 경로 (절대 경로)

- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/.claude-plugin/plugin.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/agents/model-builder.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/dcf-model/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/dcf-model/TROUBLESHOOTING.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/dcf-model/requirements.txt`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/dcf-model/scripts/validate_dcf.py`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/lbo-model/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/3-statement-model/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/3-statement-model/references/formatting.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/3-statement-model/references/formulas.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/3-statement-model/references/sec-filings.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/comps-analysis/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/audit-xls/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/model-builder/skills/xlsx-author/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/managed-agent-cookbooks/model-builder/agent.yaml`
- `/Users/yeonwoosung/Desktop/financial-services/managed-agent-cookbooks/model-builder/README.md`
- `/Users/yeonwoosung/Desktop/financial-services/managed-agent-cookbooks/model-builder/steering-examples.json`
- `/Users/yeonwoosung/Desktop/financial-services/managed-agent-cookbooks/model-builder/subagents/data-puller.yaml`
- `/Users/yeonwoosung/Desktop/financial-services/managed-agent-cookbooks/model-builder/subagents/builder.yaml`
- `/Users/yeonwoosung/Desktop/financial-services/managed-agent-cookbooks/model-builder/subagents/auditor.yaml`
- CMA 해석 보조: `managed-agent-cookbooks/README.md`, `scripts/orchestrate.py`, `scripts/deploy-managed-agent.sh`, `scripts/validate.py`, `CLAUDE.md`, 루트 `README.md`, pitch/earnings/market-researcher cookbook README의 handoff 문장.
