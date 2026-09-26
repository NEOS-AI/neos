# 금융 분석 모델링 코어 스킬 (canonical vertical-plugins)

출처: `financial-services/plugins/vertical-plugins/financial-analysis/` (agent 복제본이 아닌 vertical-plugins 원본).
읽은 트리만 인용. 발명하지 않음.

- `skills/dcf-model/` — `SKILL.md`, `TROUBLESHOOTING.md`, `scripts/validate_dcf.py`, `requirements.txt`
- `skills/lbo-model/` — `SKILL.md` (이 디렉터리에 다른 파일 없음)
- `skills/3-statement-model/` — `SKILL.md`, `references/formatting.md`, `references/formulas.md`, `references/sec-filings.md`
- `skills/comps-analysis/` — `SKILL.md`
- `commands/` — `dcf.md`, `lbo.md`, `comps.md`, `3-statement-model.md`

---

## 라이브 수식 규칙 (Formulas Over Hardcodes)

네 스킬 모두 NON-NEGOTIABLE. Python에서 계산한 숫자를 셀에 쓰지 않는다. 모델은 가정 변경 시 자동으로 움직여야 한다.

### DCF (`dcf-model/SKILL.md`)

> Every projection, margin, discount factor, PV, and sensitivity cell MUST be a live Excel formula — never a value computed in Python and written as a number
>
> When using openpyxl: `ws["D20"] = "=D19*(1+$B$8)"` is correct; `ws["D20"] = calculated_revenue` is WRONG
>
> The only hardcoded numbers permitted are: (1) raw historical inputs, (2) assumption drivers (growth rates, WACC inputs, terminal g), (3) current market data (share price, debt balance)
>
> If you catch yourself computing something in Python and writing the result — STOP. The model must flex when the user changes an assumption.

Office JS 환경:

```js
range.formulas = [["=D19*(1+$B$8)"]]
```

파생 셀에 `.values`를 쓰지 않는다. `.formulas`만.

### 3-Statement (`3-statement-model/SKILL.md`)

> Every projection cell, roll-forward, linkage, and subtotal MUST be an Excel formula — never a pre-computed value
>
> When using Python/openpyxl: write formula strings (`ws["D15"] = "=D14*(1+Assumptions!$B$5)"`), NOT computed results (`ws["D15"] = 12500`)
>
> The ONLY cells that should contain hardcoded numbers are: (1) historical actuals, (2) assumption drivers in the Assumptions tab
>
> Why: the model must flex when scenarios toggle or assumptions change. Hardcodes break every downstream integrity check silently.

### LBO (`lbo-model/SKILL.md`)

> Every calculation must be an Excel formula - NEVER compute values in Python and hardcode results into cells. When using openpyxl, write `cell.value = "=B5*B6"` (formula string), NOT `cell.value = 1250` (computed result). The model must be dynamic and update when inputs change.
>
> Use proper cell references - All formulas should reference the appropriate cells. Never type numbers that should come from other cells.

Office JS: `range.formulas = [["=B5*B6"]]`, 계산 셀에 `range.values` 금지.

### Comps (`comps-analysis/SKILL.md`)

> Every derived value (margin, multiple, statistic) MUST be an Excel formula referencing input cells — never a pre-computed number pasted in
>
> When using Python/openpyxl to build the sheet: write `cell.value = "=E7/C7"` (formula string), NOT `cell.value = 0.687` (computed result)
>
> The only hardcoded values should be raw input data (revenue, EBITDA, share price, etc.) — and every one of those gets a cell comment with its source
>
> Why: the model must update automatically when an input changes. A hardcoded margin is a silent bug waiting to happen.

### 하드코드 허용 범위 요약 (스킬이 명시한 것만)

| 스킬 | 하드코드 허용 | 하드코드 금지 |
|------|---------------|---------------|
| DCF | (1) raw historical inputs (2) assumption drivers (growth, WACC inputs, terminal g) (3) current market data (share price, debt balance) | projection, margin, discount factor, PV, sensitivity |
| 3-stmt | (1) historical actuals (2) Assumptions 탭 driver | projection, roll-forward, linkage, subtotal |
| LBO | 다른 셀을 참조하지 않는 typed numbers | 계산 결과, 다른 셀에서 와야 하는 숫자 |
| Comps | raw input (revenue, EBITDA, share price 등) + 셀 코멘트 필수 | margin, multiple, statistic |

### 하드코드 검출 (Hardcode Detection)

스킬이 별도 Python 하드코드 스캐너를 제공하지는 않는다. 검출은 아래 규칙으로 수행한다.

**3-statement 품질 검증 (`SKILL.md` Step 3):**

> Check for hardcodes | Projection formulas should reference assumptions, not contain hardcoded values

> Formula Integrity: COGS, S&M, G&A, R&D, SBC driven by % of Revenue (no hardcodes)

**DCF 금지 패턴:**

```
// WRONG - Linear approximation
B97: =B88*(1+(0.096-0.116))    // Assumes linear relationship

// WRONG - Division shortcut
B105: =B88/(1+(E48-0.07))      // Doesn't recalculate full DCF
```

OpEx를 Gross Profit에 거는 것도 하드코드/잘못된 드라이버:

```
S&M: =E33*0.15    // E33 = Gross Profit (WRONG)
S&M: =E29*0.15    // E29 = Revenue (CORRECT)
```

**Comps 금지:**

> Hardcoding numbers into formulas instead of cell references
> Hard-coded inputs without cell comments citing the source OR explaining the assumption

**LBO 금지 표:**

> Hardcoding calculated values | Model doesn't update when inputs change | Always use formulas that reference source cells

**셀 코멘트 (하드코드 입력의 감사 추적):**

DCF 형식: `"Source: [System/Document], [Date], [Reference], [URL if applicable]"`

> Add cell comments AS each hardcoded value is created
> Every blue input must have a comment before moving to next section
> Do not defer to end or write "TODO: add source"

Comps 예시:

- `"Bloomberg Terminal - MSFT Equity DES, accessed 2024-10-02"`
- `"Q4 2024 10-K filing, page 42, line item 'Total Revenue'"`
- `"FactSet consensus estimate as of 2024-10-02"`
- `"Assumed 15% EBITDA margin based on peer median, company does not disclose"`

**xlsx `recalc.py`는 수식 오류만 스캔한다.** 하드코드 숫자 검출기가 아니다. DCF 스킬:

> Recalculate all formulas in all sheets using LibreOffice
> Scan ALL cells for Excel errors (#REF!, #DIV/0!, #VALUE!, #NAME?, #NULL!, #NUM!, #N/A)

`validate_dcf.py`도 하드코드를 스캔하지 않는다. 수식 오류 문자열 + DCF 논리(terminal g vs WACC, WACC 범위, TV/EV)만 검사.

---

## 파란/검정/초록 Excel 컨벤션

폰트 색 = **무엇인가** (input / formula / link). 채움색 = **어디에 있는가** (header / data / output).

### DCF / 3-Statement / Comps — 3색 폰트

DCF `SKILL.md` Layer 1 (xlsx skill 필수):

- **Blue text (RGB: 0,0,255)**: ALL hardcoded inputs (stock price, shares, historical data, assumptions)
- **Black text (RGB: 0,0,0)**: ALL formulas and calculations
- **Green text (RGB: 0,128,0)**: Links to other sheets (WACC sheet references)

3-statement:

| Element | Fill | Font |
|---|---|---|
| Section headers (IS / BS / CF titles) | Dark blue `#1F4E79` | White bold |
| Column headers (FY2024A, FY2025E, etc.) | Light blue `#D9E1F2` | Black bold |
| Input cells (historicals, assumption drivers) | Light grey `#F2F2F2` or white | Blue `#0000FF` |
| Formula cells | White | Black |
| Cross-tab links | White | Green `#008000` |
| Check rows / key totals | Medium blue `#BDD7EE` | Black bold |

> That's 3 blues + 1 grey + white.

Comps 기본 팔레트도 동일 원칙: 파란 입력, 검정 수식. 채움은 dark blue `#1F4E79` / `#17365D`, light blue `#D9E1F2`, light grey `#F2F2F2`, white. Comps는 **테두리 없음**이 기본.

### LBO — 4색 폰트 (보라 추가)

`lbo-model/SKILL.md`:

- **Blue (0000FF)**: Hardcoded inputs - typed numbers that don't reference other cells
- **Black (000000)**: Formulas with calculations - any formula using operators or functions (`=B4*B5`, `=SUM()`, `=-MAX(0,B4)`)
- **Purple (800080)**: Links to cells on the **same tab** - direct references with no calculation (`=B9`, `=B45`)
- **Green (008000)**: Links to cells on **different tabs** - cross-sheet references (`=Assumptions!B5`, `='Operating Model'!C10`)

LBO 채움 팔레트: 섹션 헤더 `#1F4E79`, 컬럼 헤더 `#D9E1F2`, 입력 `#F2F2F2`, 수식 white, 핵심 출력(IRR/MOIC/Exit Equity) `#BDD7EE`.

### 3-Statement `formatting.md` 상세

**기본 표:**

| Element | Format |
|---------|--------|
| Hard-coded inputs | Blue font |
| Formulas | Black font |
| Links to other sheets | Green font |
| Check cells | Red if error, green if balanced |
| Negative values | Parentheses, not minus signs |
| Currency | No decimals for large figures, 2 decimals for per-share |
| Percentages | 1 decimal place |
| Headers | Bold, bottom border |
| Units row | Include units row below headers ($ millions, %, etc.) |

**시각 분리:**

- Thin vertical border between historical and projected columns
- Thick bottom border after section totals (e.g., Total Assets)
- Single bottom border for subtotals
- Double bottom border for grand totals

**합계/소계는 볼드.** IS: Gross Revenue, Total Cost of Revenue, Gross Profit, Total SG&A, EBITDA, EBIT, EBT, Net Profit After Tax. BS: Total Current/Non-Current/Other Assets, Total Assets, Total Current/Non-Current Liabilities, Total Equity, Total Liabilities and Equity. CF: Cash Generated from Operations Before WC, Total WC Changes, Net Cash from Operations/Investing/Financing, Closing Cash Balance.

**BS 체크 행 숫자 서식:**

```
[Red][<>0]0.00;[Red][<>0](0.00);0.00
```

또는 조건부 서식 "Cell Value ≠ 0" → Red font. `= 0`이면 Black.

**신용 지표 임계색 (`formatting.md`):**

| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| Total Debt / EBITDA | < 2.5x | 2.5x-4.0x | > 4.0x |
| Net Debt / EBITDA | < 2.0x | 2.0x-3.5x | > 3.5x |
| Interest Coverage | > 4.0x | 2.5x-4.0x | < 2.5x |
| Debt / Total Cap | < 40% | 40%-60% | > 60% |
| Current Ratio | > 1.5x | 1.0x-1.5x | < 1.0x |
| Quick Ratio | > 1.0x | 0.75x-1.0x | < 0.75x |

레버리지 배수: `2.5x` (1 decimal + "x"). Net Debt 음수 = 괄호 = net cash.

**마진 합리성 플래그:**

- Gross Margin < 0% → ERROR: Review COGS
- Gross Margin > 80% → WARNING: Verify revenue/COGS
- EBITDA Margin < 0% → FLAG: Operating losses
- EBITDA Margin > 50% → WARNING: Unusually high
- Net Margin < 0% → FLAG: Net losses (may be acceptable in growth phase)
- Net Margin > Gross Margin → ERROR: Formula issue

**Checks 탭 조건부 서식:** pass → Green fill, fail → Red fill, warning → Yellow fill, Difference = 0 → Light green, ≠ 0 → Light red.

### DCF 채움/테두리/숫자

채움 팔레트 (사용자 지정 없으면):

- Section headers: `#1F4E79` + white bold
- Sub-headers: `#D9E1F2` + black bold
- Input cells: `#F2F2F2` + blue font
- Calculated: white + black
- Output/summary (per-share, EV): `#BDD7EE` + black bold
- Sensitivity center cell: `#BDD7EE` + bold

테두리: Thick 1.5pt (KEY INPUTS, PROJECTION ASSUMPTIONS, 5-YEAR CF, TERMINAL VALUE, VALUATION SUMMARY, 각 sensitivity table), Medium 1pt 서브섹션, Thin 0.5pt 데이터 테이블. 테이블 내부 개별 셀 테두리 없음.

숫자:

- Years: text `"2024"` not `"2,024"`
- Percentages: `0.0%`
- Currency: `$#,##0` millions; `$#,##0.00` per-share
- Zeros: `$#,##0;($#,##0);-`
- Negatives: `(#,##0)` 괄호, 마이너스 기호 아님

LBO 숫자: Currency `$#,##0;($#,##0);"-"`, Percentages `0.0%`, Multiples `0.0"x"`, MOIC `0.00"x"`. 모든 숫자 오른쪽 정렬.

Comps 정밀도: Percentages 1 decimal, Multiples 1 decimal (`13.5x`), Dollar no decimals with thousands separator. 메트릭 가운데 정렬. 통계 행 `#F2F2F2`.

---

## DCF 공식

### 매출 전망

```
Revenue(Year N) = Revenue(Year N-1) × (1 + Growth Rate)
Growth %(Year N) = Revenue(Year N) / Revenue(Year N-1) - 1
```

성장 프레임: Year 1-2 높음, Year 3-4 산업평균으로 완화, Year 5+ terminal growth에 접근.

시나리오 예시 (SKILL 예시, 강제값 아님):

```
Bear Case: Conservative growth (e.g., 8-12%)
Base Case: Most likely scenario (e.g., 12-16%)
Bull Case: Optimistic growth (e.g., 16-20%)
```

### 영업비용 / EBIT

- ALL percentages based on REVENUE, not gross profit
- S&M typically 15-40% of revenue
- R&D typically 10-30% for technology companies
- G&A typically 8-15% of revenue
- EBIT = Gross Profit - Total OpEx

### Unlevered FCF

```
EBIT
(-) Taxes (EBIT × Tax Rate)
= NOPAT (Net Operating Profit After Tax)
(+) D&A (non-cash expense, % of revenue)
(-) CapEx (% of revenue, typically 4-8%)
(-) Δ NWC (change in working capital)
= Unlevered Free Cash Flow
```

NWC: % of revenue change (delta revenue). Typical range -2% to +2%. Negative = source of cash. Positive = use of cash.

CapEx: Maintenance ~2-3% revenue, Growth additional 2-5%.

시트 패턴 (consolidation column 참조):

```csv
Item,Formula,Reference
D&A,=E29*$E$21,$E$21 = consolidation column for D&A %
CapEx,=E29*$E$22,$E$22 = consolidation column for CapEx %
Δ NWC,=(E29-D29)*$E$23,$E$23 = consolidation column for NWC %
Unlevered FCF,=E57+E58-E60-E62,E57=NOPAT E58=D&A E60=CapEx E62=Δ NWC
```

매출 수식: `=D29*(1+$E$10)` ($E$10 = FY1 growth consolidation). 중첩 IF 금지:

```
NOT: =E29*(1+IF($B$6=1,$B$10,IF($B$6=2,$C$10,$D$10)))
```

### 시나리오 선택 (INDEX 통합열)

Case selector (예: B6): 1=Bear, 2=Base, 3=Bull.

권장:

```
=INDEX(B10:D10, 1, $B$6)
```

SKILL 초반 IF 예시가 있으나, correct_patterns와 Case Selector 섹션은 **중첩 IF를 금지**하고 INDEX/OFFSET 통합열을 요구한다.

각 시나리오 블록 필수 3행: (1) section header (merge), (2) column header with years — MANDATORY, (3) data rows.

### Mid-year 할인

```
Discount Period: 0.5, 1.5, 2.5, 3.5, 4.5, etc.
Discount Factor = 1 / (1 + WACC)^Period
PV of FCF = Unlevered FCF × Discount Factor
```

예시 (Year 1): FCF $1,000, WACC 10%, Period 0.5 → `1 / (1.10)^0.5 = 0.9535` → PV $954.

전망 기간: 5년 표준, 7-10년 고성장, 3년 성숙.

### Terminal Value

**Perpetuity (Preferred):**

```
Terminal FCF = Final Year FCF × (1 + Terminal Growth Rate)
Terminal Value = Terminal FCF / (WACC - Terminal Growth Rate)

Critical Constraint: Terminal Growth < WACC (otherwise infinite value)
```

Terminal g: Conservative 2.0-2.5% (GDP), Moderate 2.5-3.5%, Aggressive 3.5-5.0% (market leaders only). Do not exceed risk-free rate or long-term GDP growth. Default 입력: 2.5-3.0%.

**Exit Multiple (Alternative):**

```
Terminal Value = Final Year EBITDA × Exit Multiple
Typical range: 8-15x EBITDA
```

**PV of TV:**

```
PV of Terminal Value = Terminal Value / (1 + WACC)^Final Period
5-year model with mid-year convention: Period = 4.5
```

**Sanity:** TV should be 50-70% of EV. If >75% over-reliant. If <40% too conservative. TROUBLESHOOTING은 implied price가 너무 높으면 TV >80% of EV를 점검하라고 한다. `validate_dcf.py` 경고 임계는 >0.80 또는 <0.40, 전형 범위 텍스트는 50-70%.

### EV → Equity Bridge

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

Net Debt = Total Debt - Cash & Equivalents. 양수면 EV에서 차감, 음수(Net Cash)면 EV에 가산. Diluted shares 사용. 기타: minority interests, pension, operating leases.

### 세율

Validation checklist: typically 21-28%.

### 환경 / Office JS merge 함정

Excel 세션: Office JS, Python/openpyxl 금지, recalc 불필요.
Standalone .xlsx: openpyxl 후 `python recalc.py model.xlsx 30`.

Merge 함정: `.merge()` 후 merged range에 `.values` 쓰면 `InvalidArgument`. 값 먼저 top-left, 그다음 merge+format.

```js
// WRONG
const hdr = ws.getRange("A7:H7");
hdr.merge();
hdr.values = [["MARKET DATA & KEY INPUTS"]];

// CORRECT
ws.getRange("A7").values = [["MARKET DATA & KEY INPUTS"]];
const hdr = ws.getRange("A7:H7");
hdr.merge();
hdr.format.fill.color = "#1F4E79";
hdr.format.font.bold = true;
hdr.format.font.color = "#FFFFFF";
```

동일 함정이 3-statement, LBO, comps에도 적혀 있다.

### 단계별 사용자 확인 (end-to-end 금지)

DCF: data retrieval → revenue projections → FCF → WACC → TV+PV equity bridge → sensitivity. 각 단계 후 확인.

파일명: `[Ticker]_DCF_Model_[Date].xlsx`. 시트 2개: **DCF** (sensitivity는 DCF 시트 하단, 별도 시트 아님), **WACC**.

---

## WACC

### CAPM Cost of Equity

```
Cost of Equity = Risk-Free Rate + Beta × Equity Risk Premium

Where:
- Risk-Free Rate = Current 10-Year Treasury Yield
- Beta = 5-year monthly stock beta vs market index
- Equity Risk Premium = 5.0-6.0% (market standard)
```

### After-tax Cost of Debt

```
After-Tax Cost of Debt = Pre-Tax Cost of Debt × (1 - Tax Rate)

Determine Pre-Tax Cost of Debt from:
- Credit rating (if available)
- Current yield on company bonds
- Interest expense / Total Debt from financials
```

### 자본구조 가중

```
Market Value Equity = Current Stock Price × Shares Outstanding
Net Debt = Total Debt - Cash & Equivalents
Enterprise Value = Market Cap + Net Debt

Equity Weight = Market Cap / Enterprise Value
Debt Weight = Net Debt / Enterprise Value

WACC = (Cost of Equity × Equity Weight) + (After-Tax Cost of Debt × Debt Weight)
```

Special cases:

- **Net Cash** (Cash > Debt): Net Debt NEGATIVE, Debt Weight may be negative, WACC adjusts
- **No Debt**: WACC = Cost of Equity

Typical WACC ranges (SKILL):

- Large Cap, Stable: 7-9%
- Growth Companies: 9-12%
- High Growth/Risk: 12-15%

`validate_dcf.py` 합리적 범위는 **5%-20%**. 이 범위 밖이면 warning.

WACC 시트 키 수식 (SKILL 재인용):

```
Market Cap = Price × Shares
Net Debt = Total Debt - Cash
Enterprise Value = Market Cap + Net Debt
Equity Weight = Market Cap / EV
Debt Weight = Net Debt / EV
WACC = (Cost of Equity × Equity Weight) + (After-tax Cost of Debt × Debt Weight)
```

WACC 시트 레이아웃 라벨: Risk-Free Rate / Beta / ERP는 `[Yellow input]`, Cost of Equity `[Calculated blue]`, Tax Rate `[Link to DCF sheet]`, After-Tax Cost of Debt `[Calculated blue]`, 시세/주식수는 `[Link to DCF]`, Total Debt/Cash `[Yellow input]`, 최종 WACC `[Green output]`. (이 yellow 라벨은 WACC 시트 구조 csv에만 등장. 본문 폰트 컨벤션은 blue/black/green.)

### WACC 계산 오류 (common_mistakes)

- Mixing book and market values in capital structure
- Using equity beta instead of asset/unlevered beta incorrectly
- Wrong tax rate application to cost of debt
- Incorrect risk-free rate (must use current 10Y Treasury)
- Failure to adjust for net debt vs net cash position

TROUBLESHOOTING: implied price too low → WACC too high 점검. too high → terminal g < WACC 검증.

---

## Sensitivity

### DCF 3개 테이블 (DCF 시트 하단, 별도 시트 아님)

1. WACC vs Terminal Growth (rows 87-100) — 5×5 = 25 cells
2. Revenue Growth vs EBIT Margin (rows 102-115) — 5×5
3. Beta vs Risk-Free Rate (rows 117-130) — 5×5

**Total formulas to write: 75.** Excel Data Table 기능 사용 금지. 선형 근사 금지. placeholder 금지.

규칙:

- **ODD** rows and columns (5×5, sometimes 7×7) — true center
- **Center cell = base case.** 중간 행/열 헤더가 모델 실제 가정과 일치 (예: WACC 9.0%, g 3.0%)
- Center output MUST equal 모델 실제 implied share price
- Center fill `#BDD7EE` + bold
- 축: `axis_values = [base - 2*step, base - step, base, base + step, base + 2*step]`
- 각 셀은 해당 가정 조합으로 **full DCF recalculation**
- mixed references: WACC `$A88`, Terminal Growth `B$87`
- 조건부 서식: Green scale 높은 값, red scale 낮은 값

권장 수식 구조:

```
=([SUM of PV FCFs using $A88 as discount rate] + [Terminal Value using B$87 as growth rate and $A88 as WACC] - [Net Debt]) / [Shares]
```

Python 루프 패턴:

```python
# Pseudocode for populating sensitivity table
for row_idx, wacc_value in enumerate(wacc_range):
    for col_idx, term_growth_value in enumerate(term_growth_range):
        # Build formula that uses wacc_value and term_growth_value
        formula = f"=<DCF recalc using {wacc_value} and {term_growth_value}>"
        ws.cell(row=start_row+row_idx, column=start_col+col_idx).value = formula
```

WRONG 근사 (인용):

```
B97: =B88*(1+(0.096-0.116))
B105: =B88/(1+(E48-0.07))
```

### LBO Sensitivity

동일 홀수 격자 규칙. Center = 모델 실제 IRR/MOIC. 예: entry multiple 10.0x → `[8.0x, 9.0x, 10.0x, 11.0x, 12.0x]`. Excel DATA TABLE은 openpyxl과 동작하지 않을 수 있음 → 행/열 헤더를 참조하는 명시 수식. 모든 셀이 **다른 값**. mixed refs `$A5`, `B$4`. 방향: higher exit multiple → higher IRR.

### 3-Statement 시나리오 (Base / Upside / Downside)

Assumptions 탭 토글 + CHOOSE or INDEX/MATCH.

Key drivers: Revenue growth, Gross margin, SG&A %, DSO/DIO/DPO, CapEx %, Interest rate, Tax rate.

Hierarchy: Upside > Base > Downside for NI, EBITDA, FCF, margins. Leverage는 반대 (Upside < Base < Downside).

---

## `validate_dcf.py` 로직

경로: `skills/dcf-model/scripts/validate_dcf.py`

의존성 `requirements.txt`:

```
# DCF Model Builder - Python Dependencies

# Excel file handling
openpyxl>=3.0.0

# HTTP requests
requests>=2.28.0
```

CLI:

```
Usage: python validate_dcf.py <excel_file> [output.json]

Validates DCF model for:
  - Formula errors (#REF!, #DIV/0!, etc.)
  - Terminal growth < WACC (critical)
  - WACC in reasonable range (5-20%)
  - Terminal value proportion of EV (40-80%)
```

종료코드: PASS → 0, FAIL/예외 → 1.

### 클래스 흐름

`DCFModelValidator.__init__`: openpyxl import, 파일 존재 확인, **두 번 로드**:

```python
self.workbook_formulas = openpyxl.load_workbook(excel_path, data_only=False)
self.workbook_values = openpyxl.load_workbook(excel_path, data_only=True)
self.errors = []
self.warnings = []
self.info = []
```

`validate_all()` 순서:

```python
self.check_sheet_structure()
self.check_formula_errors()
self.check_dcf_logic()
```

status: `'PASS' if len(self.errors) == 0 else 'FAIL'`. warnings만 있으면 PASS.

### `check_sheet_structure`

필수(권장) 시트: `['DCF', 'WACC', 'Sensitivity']`. **없으면 warning** (`"Recommended sheet missing: {sheet}"`), error가 아님. SKILL은 sensitivity를 DCF 시트 하단에 두므로 `Sensitivity` 시트가 없는 것이 정상일 수 있다.

### `check_formula_errors`

에러 문자열:

```python
excel_errors = ['#VALUE!', '#DIV/0!', '#REF!', '#NAME?', '#NULL!', '#NUM!', '#N/A']
```

`data_only=True` 값에 위 문자열이 있으면 `self.errors.append(f"{err} at {location}")`. 수식 개수는 `data_only=False` 값이 `'='`로 시작하는 문자열인 셀을 센다.

### `check_dcf_logic` → 3개 서브체크

**1. `_check_terminal_growth_vs_wacc` (CRITICAL)**

DCF 시트 최대 100행×20열. 라벨에 `'terminal'` AND `'growth'` → 오른쪽 1–4열에서 `0 < adjacent < 1`인 숫자. 라벨에 `'wacc'` → 동일. 둘 다 찾으면:

```python
if terminal_growth >= wacc:
    self.errors.append(
        f"CRITICAL: Terminal growth ({terminal_growth:.2%}) >= WACC ({wacc:.2%}). "
        "This creates infinite value and is mathematically invalid."
    )
```

못 찾으면 warning `"Could not locate terminal growth and WACC values"`. DCF 시트 없으면 `"DCF sheet not found"`.

**2. `_check_wacc_range`**

`workbook_values.get('WACC') or workbook_values['DCF']`. 라벨 `'wacc'`, 인접 `0 < x < 1`.

```python
if wacc < 0.05 or wacc > 0.20:
    self.warnings.append(
        f"WACC ({wacc:.2%}) is outside typical range (5%-20%). Verify calculation."
    )
```

**3. `_check_terminal_value_proportion`**

DCF 시트 최대 200행×20열. `'terminal'` AND `'value'` AND `'pv'` → TV. `'enterprise'` AND `'value'` → EV. `enterprise_value > 0`이면 `proportion = terminal_value / enterprise_value`.

```python
if proportion > 0.80:
    # warning: typically should be 50-70%. over-reliant
elif proportion < 0.40:
    # warning: typically should be 50-70%. too conservative
```

라벨 매칭은 소문자 `in` 부분문자열. 인접 셀만 본다. 계산을 재수행하지 않는다. 하드코드 검출 없음. 민감도 격자 검증 없음.

결과 JSON 키: `file`, `validation_date`, `status`, `error_count`, `warning_count`, `errors`, `warnings`, `info`. 예외 시 `status: 'ERROR'`.

`validate_dcf_model(excel_path)` 래퍼가 `validate_all()`을 호출.

### TROUBLESHOOTING.md (recalc 오류 / 비합리적 가치 / case selector)

`#REF!`: 헤더 삽입 후 행 참조 어긋남. 행 위치를 수식 전에 고정.

`#DIV/0!`: `=IF([Divisor]=0,0,[Numerator]/[Divisor])`

`#VALUE!`: 입력이 숫자가 아님.

Implied price too high: TV >80% of EV, terminal g < WACC, 성장/마진 낙관.

Implied price too low: net debt vs net cash, WACC too high, conservative projections, terminal g too low.

Case selector: B6가 1/2/3인지, INDEX/OFFSET 범위, `$B$6` 절대참조.

---

## 3-Statement 공식 (`references/formulas.md`)

### 핵심 연계

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

SKILL.md 감사 표는 RE에 SBC를 포함한다: `Prior RE + NI + SBC - Dividends - BS Ending RE = 0`. formulas.md 상단 핵심 연계는 SBC 없이 `Prior RE + Net Income - Dividends`. RE 상세 블록과 Check Formulas는 SBC 포함.

### Gross Profit — Net Revenue 기준

```
Net Revenue - Cost of Revenue = Gross Profit
```

Gross Revenue로 시작 금지 (returns/allowances/discounts 차감 전이라 overstate).

### 마진

```
Gross Margin %      = Gross Profit / Net Revenue
EBITDA              = EBIT + D&A  (or = Gross Profit - OpEx)
EBITDA Margin %     = EBITDA / Net Revenue
EBIT Margin %       = EBIT / Net Revenue
Net Income Margin % = Net Income / Net Revenue
```

SKILL 마진 분석은 **사용자 요청 또는 템플릿 요구 시에만**. 아니면 skip.

### 신용 지표 공식

```
Total Debt            = Current Portion of Debt + Long-Term Debt
Net Debt              = Total Debt - Cash
Total Debt / EBITDA   = Total Debt / EBITDA (from IS)
Net Debt / EBITDA     = Net Debt / EBITDA (from IS)
Interest Coverage     = EBITDA / Interest Expense (from IS)
Net Int Exp % Debt    = Net Interest Expense / Long-Term Debt
Debt / Total Cap      = Total Debt / (Total Debt + Total Equity)
Debt / Equity         = Total Debt / Total Equity
Current Ratio         = Total Current Assets / Total Current Liabilities
Quick Ratio           = (Total Current Assets - Inventory) / Total Current Liabilities
```

신용 분석도 사용자/템플릿 요청 시에만.

### 전망 (% of Net Revenue)

```
Cost of Revenue (Forecast) = Net Revenue × Cost of Revenue % Assumption
S&M (Forecast)             = Net Revenue × S&M % Assumption
G&A (Forecast)             = Net Revenue × G&A % Assumption
R&D (Forecast)             = Net Revenue × R&D % Assumption
SBC (Forecast)             = Net Revenue × SBC % Assumption
```

### Working Capital

```
DSO = (AR / Revenue) × 365
DIO = (Inventory / COGS) × 365
DPO = (AP / COGS) × 365
Net Working Capital = AR + Inventory - AP
ΔWC = Current NWC - Prior NWC
```

AR: Prior + Revenue − Cash Collections (plug) = Ending.
Inventory: Prior + Purchases (plug) − COGS = Ending.
AP: Prior + Purchases − Cash Payments (plug) = Ending.

### D&A

```
Beginning PP&E (Gross) + CapEx = Ending PP&E (Gross)
Beginning Accumulated Depreciation + Depreciation Expense = Ending Accumulated Depreciation
PP&E (Net) = Gross PP&E - Accumulated Depreciation
```

### Debt

```
Beginning Debt Balance + New Borrowings - Repayments = Ending Debt Balance
Interest Expense = Avg Debt Balance × Interest Rate
  (Use beginning balance to avoid circularity, or iterate if circular refs enabled)
```

### RE

```
Beginning Retained Earnings
+ Net Income (from IS)
+ Stock-Based Compensation (SBC) (from IS)
- Dividends
= Ending Retained Earnings
```

### NOL (post-2017)

```
Beginning NOL Balance (Year 1 / Formation = 0)
+ NOL Generated (if EBT < 0, then ABS(EBT), else 0)
- NOL Utilized (limited by taxable income and utilization cap)
= Ending NOL Balance
```

EBT > 0: `Utilization Limit = EBT × 80%`, `NOL Utilized = MIN(NOL Available, Utilization Limit)`, `Taxable Income = EBT - NOL Utilized`.
EBT ≤ 0: Utilized = 0, Taxable Income = 0, Generated = ABS(EBT).

```
Taxes Payable = MAX(0, Taxable Income × Tax Rate)
DTA - NOL Carryforward = Ending NOL Balance × Tax Rate
```

Year 1 beginning NOL = 0 (new business). NOL non-negative. Tax expense = 0 when taxable income ≤ 0.

### 체크 수식

```
BS Balance Check:       = Assets - Liabilities - Equity  (must = 0)
Cash Tie-Out:           = BS Cash - CF Ending Cash       (must = 0)
RE Roll-Forward:        = Prior RE + NI + SBC - Div - BS RE  (must = 0)
DTA Tie-Out:            = NOL Schedule DTA - BS DTA      (must = 0)
Equity Raise Tie-Out:   = ΔCommon Stock/APIC (BS) - Equity Issuance (CFF)  (must = 0)
Year 0 Equity Tie-Out:  = Equity Raised (Year 0) - Beginning Equity (Year 1)  (must = 0)
Cash Monthly vs Annual: = Closing Cash (Monthly) - Closing Cash (Annual)  (must = 0)
NOL Utilization Cap:    = NOL Utilized ≤ EBT × 80%       (must be TRUE for post-2017)
NOL Non-Negative:       = Ending NOL Balance ≥ 0         (must be TRUE)
NOL Starting Balance:   = Beginning NOL (Year 1) = 0     (must be TRUE for new business)
NOL Accumulation:       = NOL increases only when EBT < 0 (losses generate NOL)
```

Master check: 전부 pass → `"✓ ALL CHECKS PASS"`, 하나라도 fail → `"✗ ERRORS DETECTED - REVIEW BELOW"`.

### 부호 규칙 (SKILL)

| Statement | Item | Sign Convention |
|-----------|------|-----------------|
| CFO | D&A, SBC | Positive (add-back) |
| CFO | ΔAR (increase) | Negative (use of cash) |
| CFO | ΔAP (increase) | Positive (source of cash) |
| CFI | CapEx | Negative |
| CFF | Debt issuance | Positive |
| CFF | Debt repayments | Negative |
| CFF | Dividends | Negative |

### 순환참조

Interest → Net Income → Cash → Debt Balance → Interest.

Excel: File → Options → Formulas → Enable iterative calculation. Max iterations 100, max change 0.001. Assumptions에 circuit breaker 토글.

LBO는 **Beginning Balance**로 순환을 끊는다 (average/ending 사용 금지).

### 템플릿 탭 이름

IS/P&L/Income Statement, BS/Balance Sheet, CF/CFS/Cash Flow, WC/Working Capital, DA/D&A/Depreciation/PP&E, Debt, NOL/Tax/DTA, Assumptions/Inputs/Drivers, Checks/Audit/Validation.

전망: 통상 last historical 이후 5년. FY2024A vs FY2025E.

---

## SEC 공시 지침 (`references/sec-filings.md`)

**사용 시점:** 템플릿이 10-K/10-Q에서 데이터를 요구할 때만. 다른 소스를 쓰면 이 파일을 읽지 않는다.

### 위치

```
https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=[TICKER]&type=10-K
```

분기: `type=10-Q`.

### 통화

커버/헤더, statement headers (`in thousands of U.S. dollars`), Note 1. 모델 통화를 공시와 맞추고 Assumptions에 기록.

| Indicator | Currency |
|-----------|----------|
| $, USD | US Dollar |
| €, EUR | Euro |
| £, GBP | British Pound |
| ¥, JPY | Japanese Yen |
| ¥, CNY, RMB | Chinese Yuan |
| CHF | Swiss Franc |
| CAD, C$ | Canadian Dollar |

### 탐색

- 10-K **Item 8** / 10-Q **Item 1**: Financial Statements
- Consolidated Statements of Operations, Balance Sheets, Cash Flows, Notes

### 라인 매핑

**IS:** Net revenues/Net sales → Revenue; COGS → COGS; SG&A → SG&A; D&A → D&A; Interest expense, net → Interest Expense; Income tax expense → Taxes; Net income → Net Income.

**BS:** Cash and cash equivalents → Cash; AR net → AR; Inventories → Inventory; PP&E net → PP&E (Net); Total assets → Total Assets; AP → AP; ST debt / current portion LT → Current Debt; LT debt → LT Debt; RE → Retained Earnings; Total stockholders' equity → Total Equity.

**CF:** NI → NI; D&A → D&A; ΔAR, ΔInventory, ΔAP; CapEx; Proceeds from issuance of common stock → Equity Issuance; Debt proceeds/repayments; Dividends paid.

### Notes

Debt (maturity, rates, covenants), PP&E (gross, accum dep, useful lives), Revenue (segment/geo), Leases (operating vs finance).

### 역사 데이터

최소 3년. 10-K: 3년 IS/CF, 2년 BS → 3년차 BS는 직전 10-K. 분기는 10-Q.

체크리스트: 통화/스케일; 3년 IS/CF/BS; IS NI = CF starting NI; BS Cash = CF Ending Cash; debt maturity; D&A/useful lives; non-recurring 정규화.

### 변형

| Variation | How to Handle |
|-----------|---------------|
| D&A embedded in COGS/SG&A | Pull D&A from Cash Flow Statement |
| "Other" line items are material | Check notes for breakdown |
| Restatements | Use restated figures, note in assumptions |
| Fiscal year ≠ calendar year | Label with fiscal year end (e.g., FYE Jan 2025) |
| Non-USD reporting currency | Adapt model currency to match filing |

---

## LBO 코어 (`lbo-model/SKILL.md`)

템플릿 필수. 첨부 템플릿이 있으면 **그대로 복사해 채운다. from scratch 금지.** 없으면 사용자에게 템플릿 여부 질문. 표준이면 `examples/LBO_Model.xlsx` 복사. (이 스킬 디렉터리 listing에는 `SKILL.md`만 존재. examples는 스킬 텍스트가 가리키는 경로.)

표준 섹션 이름 (질문 문구): Sources & Uses, Operating Model, Debt Schedule, Returns Analysis.

### 문제 영역 (스킬이 명시한 패턴만)

**Balancing:** Sources = Uses일 때 한 항목이 plug = 차이.

**Tax:** 관련 income line과 tax rate만 참조. debt schedule 등 무관 섹션 참조 금지.

**Interest 순환:** Beginning Balance 사용.

```
Interest → Cash Flow → Paydown → Ending Balance
```

ending/average를 쓰면 순환.

**Debt paydown / cash sweep:** 트랜치 우선순위 waterfall. 잔액 음수 금지: `MAX`/`MIN`.

**Returns:**

- Investment = negative, Proceeds = positive
- XIRR은 날짜 필요, IRR은 consecutive periods
- `MOIC = Total Proceeds / Total Investment`

**섹션별 사용자 확인:** Sources & Uses → Operating Model → Debt Schedule → Returns (IRR/MOIC) → Sensitivity.

**recalc:** `python /mnt/skills/public/xlsx/recalc.py model.xlsx` — zero errors.

**논리 방향:** higher exit multiple → higher IRR.

---

## Comps 코어 (`comps-analysis/SKILL.md`)

### 데이터 소스 우선순위

1. FIRST: MCP (S&P Kensho, FactSet, Daloopa) — 있으면 **exclusively**
2. MCP 있으면 web search 쓰지 않음
3. MCP 없을 때만 Bloomberg, SEC EDGAR, 기타 institutional
4. NEVER web search as primary

### 부적합

Private without public peers, diversified conglomerates, distressed/bankrupt, pre-revenue startups, unique business models.

### 구조

Header rows 1-3: title, company•ticker list, `As of [Period] | All figures in [USD Millions/Billions] except per-share amounts and ratios`.

Operating: Company, Revenue, Revenue Growth, Gross Profit, Gross Margin, EBITDA, EBITDA Margin.

Valuation: Company, Market Cap, EV, EV/Revenue, EV/EBITDA, P/E.

통계 (비교 가능 메트릭만):

```
Maximum: =MAX(B7:B9)
75th Percentile: =QUARTILE(B7:B9,3)
Median: =MEDIAN(B7:B9)
25th Percentile: =QUARTILE(B7:B9,1)
Minimum: =MIN(B7:B9)
```

통계 **필요**: Growth %, margins, EPS, EV/Revenue, EV/EBITDA, P/E, Dividend Yield %, Beta.
통계 **불필요**: Revenue, EBITDA, NI, Market Cap, EV (규모 메트릭).

회사 데이터와 통계 사이 빈 행 1개. `"SECTOR STATISTICS"` / `"VALUATION STATISTICS"` 헤더 행 넣지 않음.

### 수식

```excel
Gross Margin (F7): =E7/C7
EBITDA Margin (H7): =G7/C7
Rule of 40: =[Growth %]+[FCF Margin %]
EV/Revenue: =[Enterprise Value]/[LTM Revenue]
EV/EBITDA: =[Enterprise Value]/[LTM EBITDA]
P/E Ratio: =[Market Cap]/[Net Income]
FCF Yield: =[LTM FCF]/[Market Cap]
PEG Ratio: =[P/E]/[Growth Rate %]
```

Cross-reference: 배수 분모는 operating 섹션 셀. 동일 raw data 두 번 입력 금지.

기타 비율 가이드:

```excel
FCF Conversion = FCF / Operating Cash Flow
ROE = Net Income / Shareholders' Equity
ROA = Net Income / Total Assets
Asset Turnover = Revenue / Total Assets
Debt/Equity = Total Debt / Shareholders' Equity
```

FCF definition in notes: Operating CF - CapEx. EV: Market Cap + Net Debt.

### 5-10 Rule

5 operating + 5 valuation = 10 columns. 15개 초과면 noise.

Peer group: 4-6 truly comparable. 의심스러우면 제외. 3 perfect > 6 questionable.

### Sanity

- Gross margin > EBITDA margin > Net margin (always true by definition)
- EV/Revenue typically 0.5-20x
- EV/EBITDA typically 8-25x
- P/E typically 10-50x
- Higher growth usually higher multiples

Red flags: 분기/연간 혼용; 소스 간 >10% 차이; negative EBITDA에 EBITDA multiple; P/E >100x without hypergrowth; FYE 불일치; conglomerate를 pure-play와 섞기.

폰트 기본: Times New Roman, 11pt data, 12pt headers.

---

## Commands

### `commands/dcf.md`

comps-analysis를 **먼저** 로드 → 4-6 peers, median EV/EBITDA를 terminal exit multiple에, 25th-75th를 sensitivity range에, peer growth/margins를 DCF 가정 벤치마크에, median P/E를 교차검증에 사용. 그다음 dcf-model.

교차검증: DCF implied EV/EBITDA vs peer median; implied P/E vs peer; TV % of EV 50-70%; implied growth vs peers.

산출: comps .xlsx + DCF .xlsx (Bear/Base/Bull, sensitivity, implied upside/downside) + summary.

Command 설명: "Build a DCF valuation model with comps-informed terminal multiples".

### `commands/lbo.md`

`lbo-model` 스킬 로드. 인수 대상/딜 파라미터 없으면 질문.

### `commands/comps.md`

`skill: "comps-analysis"`. 4-6 peers. Excel: header, operating stats, valuation multiples, Max/QUART/MEDIAN/MIN, notes. Blue inputs, black formulas. 산업 추가 메트릭 표: SaaS ARR/NDR/Rule of 40; Retail SSS/Inventory Turns; Financials ROE/ROA/Efficiency; Manufacturing Asset Turnover/CapEx/Revenue; Healthcare R&D/Revenue/Pipeline.

### `commands/3-statement-model.md`

`3-statement-model` 스킬 로드. argument가 템플릿 경로. 없으면 사용자에게 템플릿 요청.

---

## 공통 운영 규칙 (네 스킬이 공유)

1. Office JS 라이브 세션 vs standalone openpyxl + `recalc.py`.
2. Merge 후 범위에 values 쓰지 않음 (top-left 먼저).
3. 라이브 수식. Python 계산값 쓰기 금지.
4. 사용자와 섹션 단위 확인. end-to-end 빌드 후 일괄 제출 금지.
5. 파란 입력 / 검정 수식 / 초록 시트링크 (LBO만 같은 탭 링크 보라).
6. 하드코드 입력에 소스 코멘트. TODO 금지.
7. 행 레이아웃을 수식보다 먼저 고정 (DCF `#REF!` 예방).
8. 민감도(해당 시): 홀수 격자, 중앙 = base, `#BDD7EE`, full recalc 수식.
9. `recalc.py` success, 수식 오류 0.
10. 사용자/템플릿 색상·레이아웃이 기본 팔레트보다 우선.

### DCF TOP 5 오류

1. Formula row references off → 행 위치 먼저 정의
2. Missing cell comments → 생성 즉시 코멘트
3. Simplified sensitivity tables → 75셀 full DCF 수식
4. Scenario block references wrong → INDEX 통합열
5. No borders → 섹션 테두리

### DCF 최종 체크리스트 (SKILL)

- `python recalc.py model.xlsx 30` success
- Sheets: DCF (sensitivity at bottom), WACC
- Blue/Black/Green fonts
- Comments on ALL hardcoded inputs
- Sensitivity fully populated
- Professional borders
- OpEx on revenue not GP
- TV 50-70% of EV
- Terminal growth < WACC
- Tax 21-28%
- `[Ticker]_DCF_Model_[Date].xlsx`
