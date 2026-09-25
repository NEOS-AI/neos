# Equity Research 플러그인 파일 분석

범위: `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/equity-research/`  
방법: 해당 디렉터리의 모든 파일을 읽고 인용. 파일에 없는 내용은 쓰지 않음.  
파일 수: 31개 (find 기준).

---

## 플러그인 메타데이터 (`plugin.json`)

경로: `.claude-plugin/plugin.json`

```json
{
  "name": "equity-research",
  "version": "0.1.2",
  "description": "Equity research tools: earnings analysis, initiating coverage reports, and research workflows",
  "author": {
    "name": "Anthropic FSI"
  }
}
```

- 이름: `equity-research`
- 버전: `0.1.2`
- 설명: `"Equity research tools: earnings analysis, initiating coverage reports, and research workflows"`
- 저자: `"Anthropic FSI"`
- 그 외 필드(라이선스, 키워드, 의존성 등)는 파일에 없음.

---

## Hooks

경로: `hooks/hooks.json`

```json
{
  "hooks": {}
}
```

훅 정의는 비어 있음. PreToolUse/PostToolUse/Stop 등 항목 없음.

---

## 커맨드 맵

9개 커맨드. 대부분 해당 스킬을 로드하라는 한 줄. `/earnings`만 인라인 워크플로가 길다.

| 커맨드 파일 | description (frontmatter) | argument-hint | 로드하는 스킬 |
|---|---|---|---|
| `commands/catalysts.md` | View or update the catalyst calendar | `[timeframe, e.g. 'next 2 weeks']` | `catalyst-calendar` |
| `commands/earnings-preview.md` | Build a pre-earnings preview with scenarios | `[company ticker]` | `earnings-preview` |
| `commands/earnings.md` | Analyze quarterly earnings and create an earnings update report | `[company name or ticker] [quarter, e.g. Q3 2024]` | `earnings-analysis` |
| `commands/initiate.md` | Create an initiating coverage report | `[company ticker]` | `initiating-coverage` |
| `commands/model-update.md` | Update a financial model with new data | `[company ticker]` | `model-update` |
| `commands/morning-note.md` | Draft a morning meeting note | `""` | `morning-note` |
| `commands/screen.md` | Run a stock screen or generate investment ideas | `[screen criteria, e.g. 'undervalued midcap tech']` | `idea-generation` |
| `commands/sector.md` | Create a sector overview report | `[sector or industry]` | `sector-overview` |
| `commands/thesis.md` | Create or update an investment thesis | `[company ticker]` | `thesis-tracker` |

### 커맨드별 본문 (인용)

**`catalysts.md`**
> Load the `catalyst-calendar` skill to build or review upcoming catalysts across the coverage universe.
> If a timeframe is provided, use it. Otherwise default to the next 2 weeks.

**`earnings-preview.md`**
> Load the `earnings-preview` skill and build a pre-earnings analysis with consensus estimates, key metrics to watch, and bull/base/bear scenarios.
> If a ticker is provided, use it. Otherwise ask the user which company is reporting.

**`initiate.md`**
> Load the `initiating-coverage` skill and begin the 5-task workflow to create an institutional-quality initiation report.
> If a ticker is provided, use it. Otherwise ask the user which company to initiate on.

참고: 이 커맨드는 “5-task workflow”를 시작하라고 하지만, 스킬 본문은 “SINGLE-TASK MODE ONLY”, “Never execute multiple tasks in sequence”를 요구한다.

**`model-update.md`**
> Load the `model-update` skill and plug in new earnings, guidance, or revised assumptions.
> If a ticker is provided, use it. Otherwise ask the user which model to update and what changed.

**`morning-note.md`**
> Load the `morning-note` skill and draft a concise morning note covering overnight developments, earnings reactions, and trade ideas across the coverage universe.

**`screen.md`**
> Load the `idea-generation` skill and run quantitative screens or thematic sweeps to surface new investment ideas.
> If criteria are provided, use them. Otherwise ask the user what they're looking for (long/short, sector, style, theme).

**`sector.md`**
> Load the `sector-overview` skill and create an industry landscape report covering market sizing, competitive dynamics, and investment implications.
> If a sector is provided, use it. Otherwise ask the user which industry to cover.

**`thesis.md`**
> Load the `thesis-tracker` skill to create a new thesis or update an existing one with new data points.
> If a ticker is provided, use it. Otherwise ask the user which position to review.

**`earnings.md`** — 유일한 장문 커맨드. 스킬을 호출하면서 워크플로·리포트 구조·품질 체크리스트를 커맨드 파일 안에 복제한다.

Step 1: 회사/분기 파싱, 없으면 질문.  
Step 2: “**CRITICAL**: Before proceeding, verify you have the latest data” — 최근 3개월, transcript 날짜 일치.  
Step 3: `skill: "earnings-analysis"` — Data Collection, Beat/Miss, Key Metrics, 8-12 charts, 8-12 page report.  
Step 4: DOCX + Summary (beat/miss, guidance, thesis impact).

Page 1 템플릿에 이미 추천이 들어간다:
> Rating: BUY | Price Target: $XXX (from $XXX)
> Thesis intact; maintain BUY rating
> PAGES 6-7: THESIS UPDATE — Investment recommendation
> PAGES 8-10: VALUATION — Price target justification

품질 체크:
> Rating and price target stated upfront
> 8-12 pages, 3,000-5,000 words

---

## 스킬 목록

9개 스킬. 각 스킬은 `skills/<name>/SKILL.md`에 YAML frontmatter (`name`, `description`)가 있다.

| 스킬 | 참조/에셋 |
|---|---|
| `earnings-analysis` | `references/workflow.md`, `report-structure.md`, `best-practices.md` |
| `initiating-coverage` | `references/task1`–`task5`, `valuation-methodologies.md`; `assets/quality-checklist.md`, `report-template.md` |
| `earnings-preview` | 없음 (SKILL.md만) |
| `model-update` | 없음 |
| `morning-note` | 없음 |
| `sector-overview` | 없음 |
| `thesis-tracker` | 없음 |
| `catalyst-calendar` | 없음 |
| `idea-generation` | 없음 |

---

## 스킬: earnings-analysis

### Frontmatter

```
name: earnings-analysis
description: Create professional equity research earnings update reports (8-12 pages, 3,000-5,000 words) analyzing quarterly results for companies already under coverage. Fast-turnaround format focusing on beat/miss analysis, key metrics, updated estimates, and revised thesis. Includes 1-3 summary tables and 8-12 charts. Use when user requests "earnings update", "quarterly update", "earnings analysis", "Q1/Q2/Q3/Q4 results", or post-earnings report.
```

### 사용 조건 (인용)

> Use when the user requests: "Create an earnings update for [Company] Q3 2024" / "Analyze [Company]'s quarterly results" / "Post-earnings report" / "Q1/Q2/Q3/Q4 update"
>
> **Do NOT use if:**
> - User requests "initiation report" → Use different skill
> - User requests "flash note" or "quick take" → Different format
> - Company is not already covered → Need initiation first

### 핵심 스펙

- Length: 8-12 pages; Word Count: 3,000-5,000
- Tables: 1-3 summary; Figures: 8-12 charts
- Turnaround: 1-2 days (within 24-48 hours of earnings)
- Audience: “Clients already familiar with the company”
- Focus: “What's NEW - beat/miss, updated estimates, thesis impact”
- Font: “Times New Roman throughout (unless user specifies otherwise)”
- 파일명: `[Company]_Q[Quarter]_[Year]_Earnings_Update.docx`

Initiation과의 차이 표:

| Aspect | Earnings Update | Initiation Report |
|---|---|---|
| Length | 8-12 pages | 30-50 pages |
| Words | 3,000-5,000 | 10,000-15,000 |
| Tables | 1-3 summary | 12-20 comprehensive |
| Figures | 8-12 | 25-35 |
| Turnaround | 1-2 days | 3-6 weeks |
| Scope | Quarterly results | Complete company |
| XLS Model | Optional | Required |

### 워크플로 (5 phases)

1. **Data Collection (30-60 min)** — “TRAINING DATA IS OUTDATED”. 오늘 날짜 기록 → “latest earnings” 검색 → 최근 3개월 확인 → transcript 날짜 일치. 상세는 `references/workflow.md`.
2. **Analysis (2-3 hours)** — beat/miss, segment, margin, guidance, model/estimates.
3. **Chart Generation (1-2 hours)** — 8-12 charts (quarterly revenue/EPS/margins, segment, beat/miss, estimate revisions, valuation).
4. **Report Creation (2-3 hours)** — 8-12 page DOCX. 상세는 `references/report-structure.md`.
5. **Quality Check (30 min)** — `references/best-practices.md`.

의존성: “Python (matplotlib, pandas, seaborn) for chart generation”, “DOCX skill for report creation”. Optional: “XLS skill for model updates”.

### 리포트 구조 (`references/report-structure.md`)

- **PAGE 1: EARNINGS SUMMARY** — Rating `[MAINTAIN/RAISE/LOWER] [RATING]`, Price, Price Target `[OLD → NEW if changed, or MAINTAIN $XXX]`, RESULTS `[BEAT / INLINE / MISS]`, Key Takeaways 3개, Investment Impact 3-4 bullets (■), Updated Estimates table.
- **PAGES 2-3: DETAILED RESULTS** — Revenue Analysis, Profitability Analysis, 차트 2-3개.
- **PAGES 4-5: KEY METRICS & GUIDANCE** — Operating metrics, Management Guidance vs Estimates.
- **PAGES 6-7: UPDATED INVESTMENT THESIS** — 각 pillar Status `[STRENGTHENED / UNCHANGED / WEAKENED]`, Risks Update.
- **PAGES 8-10: VALUATION & ESTIMATES** — DCF update, comps, Price Target Methodology (`XX% DCF / XX% NTM P/E / XX% EV/EBITDA`), Detailed Estimate Updates.
- **PAGES 11-12: APPENDIX (Optional)** — quarterly models, transcript highlights, peer comparison.

포맷: “Lead with numbers”, “Use `vs.` not `versus`”, “Focus on what's NEW”.  
Hyperlink: “ALL URLs must be clickable hyperlinks in Word”, “Blue, underlined”, “No plain text URLs”.

필수 출처:
- Earnings release (date + URL)
- 10-Q (filing date + EDGAR)
- Earnings call transcript (date)
- Investor presentation (if available)
- Consensus (Bloomberg/FactSet + date)
- Prior guidance

### 리서치 vs 추천

이 스킬은 분석과 추천을 한 리포트에 묶는다. 파일에 “not investment advice” 문구는 없다.

추천이 들어가는 위치 (인용):
- Page 1: `Rating: [MAINTAIN/RAISE/LOWER] [RATING]`, `Price Target`
- Pages 6-7: “Updated investment thesis”, “Investment recommendation” (`commands/earnings.md`)
- Pages 8-10: “Price target justification”
- Workflow Step 11 (`workflow.md`): “Decide whether to change rating” — “significantly better + guidance raised → Consider upgrade”; “significantly worse + guidance cut → Consider downgrade”; “inline or mixed → Usually maintain rating”
- Price Target Decision: estimates 변화 >5%면 “Usually change price target”
- Delivery summary: `Rating: [MAINTAINED / RAISED / LOWERED] [RATING]`, `Price Target: $XXX (prior: $XXX)`

`best-practices.md` 좋은 헤드라인 예:
> "Nike Q2 FY24: DTC Strength Offsets Wholesale Weakness - Maintaining OW, PT $95"
> "Tesla Q3'24: Cybertruck Ramp Ahead of Plan - Raising Estimates, PT to $285"

나쁜 헤드라인: `"Nike Quarterly Update"` (no takeaway), `"Company Reports Earnings"` (no analysis).

필수 실수 회피:
> “No investment impact: Must connect results to thesis and rating”
> “Missing price target update: If estimates changed materially, PT should too”

### 참조 파일

- `skills/earnings-analysis/references/workflow.md` — Phase 1–5 상세. 최신 데이터 강제, fiscal calendar (Nike/Apple/Walmart 예), materials 수집 (press release, 10-Q/10-K, transcript, presentation, consensus “as of [date before earnings]”), beat/miss 분석 프레임, 8-12 차트 스펙, 품질 체크리스트, delivery 템플릿.
- `skills/earnings-analysis/references/report-structure.md` — 페이지별 템플릿, 표 형식, citation 예시.
- `skills/earnings-analysis/references/best-practices.md` — 헤드라인, tips, common mistakes, content/format/citations/accuracy/timeliness/writing 체크리스트, 5-minute final review, summary delivery format.

---

## 스킬: initiating-coverage

### Frontmatter

```
name: initiating-coverage
description: Create institutional-quality equity research initiation reports through a 5-task workflow. Tasks must be executed individually with verified prerequisites - (1) company research, (2) financial modeling, (3) valuation analysis, (4) chart generation, (5) final report assembly. Each task produces specific deliverables (markdown docs, Excel models, charts, or DOCX reports). Tasks 3-5 have dependencies on earlier tasks.
```

표준: “JPMorgan, Goldman Sachs, Morgan Stanley format”.  
Default Font: “Times New Roman throughout all documents (unless user specifies otherwise)”.

### 워크플로 — 한 번에 한 태스크만

> **THIS SKILL OPERATES IN SINGLE-TASK MODE ONLY.**

전체 파이프라인 요청 시:
1. 어떤 태스크인지 묻고 5개 목록을 제시.
2. “all tasks together”면 “Currently, this skill supports executing one task at a time… We're working on a seamless end-to-end workflow…”
3. “Never automatically assume which task to start”
4. “Never execute multiple tasks in sequence”

규칙:
- Execute exactly ONE task per user request
- Always verify prerequisites
- Deliver outputs and wait
- Never chain tasks
- Never execute Tasks 3-5 without verifying inputs

Deliverables Policy: extra documents 금지 (“Completion summaries”, “Executive summaries”, “Quick reference guides”, “Next steps documents”, “Task completion reports”).

태스크별 산출물만:
- Task 1: Research document (.md) — NOTHING ELSE
- Task 2: Financial model (.xlsx) — NOTHING ELSE
- Task 3: Valuation analysis (.md) + Excel tabs added to Task 2 file
- Task 4: Charts zip (.zip)
- Task 5: Final report (.docx)

의존성:
- Task 1: independent
- Task 2: 10-K or financials (Task 1 optional)
- Task 3: requires Task 2
- Task 4: requires Tasks 1, 2, 3 + external data
- Task 5: requires ALL 1–4
- “Tasks 1 and 2 can be run in any order”

참조 로드 규칙: “Load ONLY the reference file associated with the specific task… do not load multiple reference files at once.”

세션: 같은 세션이면 산출물 자동 사용, 다른 세션이면 경로를 명시.  
권장 폴더: `Task1_Research/`, `Task2_Model/`, `Task3_Valuation/`, `Task4_Charts/`, `Task5_Report/`.

참고: Task 3 폴더 예시에 `[Company]_Valuation_Analysis.pdf`가 나오지만, Task 3 산출물 스펙은 `.md` + Excel 탭이다.

### Task 1 — Company Research

전제: 회사명/티커만.  
산출: 6,000–8,000 words markdown. 파일: `[Company]_Research_Document_[Date].md`

섹션과 단어 수 (`task1-company-research.md`):
1. Company Overview 800–1,200
2. Company History 800–1,200
3. Management Team 1,000–1,400 (300–400 word bio × 3–4 execs; CEO, CFO 필수)
4. Products & Services 700–1,000
5. Customers & Go-to-Market 500–700
6. Industry Overview 800–1,200
7. Competitive Landscape 700–1,000 (5–10 competitors)
8. Market Opportunity (TAM) 500–700
9. Risk Assessment 600–900 — 8–12 risks, 4 categories, each 50–100 words
   - Company-Specific 4–6
   - Industry/Market 3–4
   - Financial 2–3
   - Macroeconomic 2–3
+ DATA SOURCES (dates and URLs)

1차 소스: 10-K, 10-Q, DEF 14A, 8-K, IR, presentations, transcripts. Private: website, LinkedIn, Crunchbase/PitchBook.  
2차: competitor filings, Gartner/Forrester/IDC, news.

Task 5에서 “Company 101 sections copied verbatim”.

### Task 2 — Financial Modeling

전제: 공시 재무 (public: Latest 10-K from SEC EDGAR; private: statements/estimates) 또는 사용자가 준 historicals.  
산출: `[Company]_Financial_Model_[Date].xlsx` — 6 essential tabs:

1. Revenue Model — product 20–30 rows + geography 15–20 rows
2. Income Statement — 40–50 line items, 3–5 years historical + 5 years projected
3. Cash Flow Statement
4. Balance Sheet
5. Scenarios — Bull/Base/Bear
6. DCF Inputs — unlevered FCF for Task 3

색: Blue = hardcoded inputs, Black = formulas, Green = cross-sheet links, Red = errors.  
“No circular references”, “No hardcoded numbers in formulas (except constants)”.  
Historical extraction 시 별도 `[Company]_Historical_Financials_[Date].xlsx`를 만들 수 있음 (Income Statement / Cash Flow / Balance Sheet / Metrics / Notes).

업종 특수 고려 (`task2`):
- High-Growth Tech/SaaS: ARR, net retention, LTV/CAC, path to profitability
- E-commerce/Retail: channel, store count, inventory turns
- Manufacturing/Industrial: capacity, volume/price/mix, CapEx

### Task 3 — Valuation Analysis

전제: Task 2 모델. 없으면 “Stop immediately… Do not attempt to proceed or create placeholder valuations.”

산출:
- `[Company]_Valuation_Analysis_[Date].md` (4–6 pages)
- Task 2 xlsx에 탭 추가: DCF, Sensitivity, Comparable companies, Valuation summary (Precedent optional)

내용:
- DCF + sensitivity (WACC vs g, Revenue CAGR vs terminal EBITDA margin)
- Comps 5–10 peers, statistical summary **MANDATORY**: max / 75th / median / 25th / min
- Precedent transactions if applicable
- Valuation football field
- **Price target**: $XX.XX
- **Recommendation**: BUY/HOLD/SELL
- **Upside**: XX%
- Key catalysts 3–5

가중 예 (`task3-valuation.md`):
> DCF Analysis $42 $46 $51 50%
> Trading Comps (NTM) $64 $71 $78 40%
> Precedent Trans. $70 $79 $88 10%
> Rounded Price Target: $59.00
> Rating: BUY / OUTPERFORM
> Time Horizon: 12 months

WACC: 10y Treasury, CAPM (ERP 5–6%), after-tax cost of debt, market-value weights.  
Terminal: Perpetuity Growth preferred (g typically 2.0–3.0%, “Should not exceed long-term GDP growth”, base 2.5%); Exit Multiple alternative.  
“Choose one method or average both.”

Sanity: historical multiple, peer premium/discount, implied growth, market cap, terminal value < 60–70% of EV, WACC 8–14% (tech 10–14%, mature 7–10%), IRR vs rating.

### Task 4 — Chart Generation

전제: Tasks 1+2+3 + external (Yahoo Finance, Bloomberg). 없으면 placeholder 금지.

산출: `[Company]_Charts_[Date].zip` — 25–35 PNG/JPG, 300 DPI + `chart_index.txt`

4 MANDATORY:
- chart_03 Revenue by product (stacked area)
- chart_04 Revenue by geography (stacked bar)
- chart_28 DCF sensitivity (2-way heatmap)
- chart_32 Valuation football field (horizontal bars)

25 REQUIRED: chart_01, 02, 03⭐, 04⭐, 05–18, 28⭐–34.  
10 OPTIONAL: chart_19–27, 35.

데이터 매핑: Task 1 → 9 charts, Task 2 → 8, Task 3 → 6, External → 2 (stock price, historical multiples).

환경: `pip install matplotlib seaborn pandas numpy plotly`, seaborn-v0_8-darkgrid, DPI=300.

### Task 5 — Report Assembly

전제: 1–4 전부. 불완전 조립 금지.

산출: `[Company]_Initiation_Report_[Date].docx` ONLY.

스펙:
- Length: 30–50 pages (MINIMUM 30)
- Words: 10,000–15,000 (MINIMUM 10,000)
- Charts: 25–35 embedded
- Tables: 12–20
- Density: 60–80% page coverage, 1 chart per 200–300 words

섹션 단어 수 (`task5-report-assembly.md`):

| Section | Minimum | Target | Critical? |
|---|---|---|---|
| Investment Summary (Page 1) | 500 | 700 | |
| Investment Thesis | 800 | 1,200 | |
| Risk Factors | 600 | 900 | |
| Company Description | 800 | 1,200 | |
| Management Bios | 1,000 | 1,400 | |
| Products & Services | 700 | 1,000 | |
| **Projection Assumptions** | **2,000** | **3,000** | ⭐ YES |
| **Scenario Analysis** | **1,500** | **2,000** | ⭐ YES |
| Financial Analysis | 1,200 | 1,800 | |
| Valuation Methodology | 800 | 1,200 | |

페이지 맵 (SKILL.md):
- Page 1: Investment Summary (INITIATING COVERAGE format)
- Pages 2–5: Investment thesis & risks
- Pages 6–17: Company 101
- Pages 18–30: Financial analysis & projections
- Pages 31–40: Valuation analysis
- Pages 41–50: Appendices

조립 철학:
- Task 1 content “40–50% of report”, “Use Task 1 content verbatim”
- Task 2/3 data “30–40%”
- Original writing “10–20%”: thesis, projection assumptions, scenario analysis
- Tools: “Use Claude's DOCX and XLSX skills (NOT Python libraries)”
- Page 1은 분석이 끝난 뒤 마지막에 작성

### 리포트 구조 — `assets/report-template.md`와의 차이

`assets/report-template.md`는 이렇게 시작한다:
> PAGE 1: INVESTMENT UPDATE (MOST IMPORTANT PAGE)
> This is an "Investment Update" or "Company Update" page, not "Executive Summary"
> MAIN CONTENT - GRAY HEADER BAR: `[OUTPERFORM / NEUTRAL / etc.] RECOMMENDATION / COMPANY UPDATE`

반면 SKILL.md / quality-checklist / task5:
> "INITIATING COVERAGE" header (NOT "Company Update")
> Thesis-focused title (NOT event-driven like "Strong Q4 Results")

같은 템플릿 파일 안의 TOC는 `Executive Summary....................................................1`로 적혀 있다.

차트 목표도 템플릿은 “20-30+ chart images”, 스킬은 “25-35”.

폰트: SKILL.md “Times New Roman”; task5/quality-checklist “Calibri, Arial, or similar”.

Excel 탭 수: Task 2는 6 + Task 3이 4탭. `quality-checklist.md`는:
> 15+ tabs in Excel workbook
> Tabs include: Executive Summary, Assumptions, Historical Financials, Revenue Model, Operating Expenses, Income Statement, Balance Sheet, Cash Flow, Supporting Schedules, DCF Valuation, Comps Analysis, Precedent Transactions, Scenarios, Sensitivity Analysis, Charts

quality-checklist는 DOCX와 함께 XLS를 최종 산출로 보고, Task 5 SKILL은 “DELIVER ONLY THIS 1 DOCX FILE”이라고 한다. `task5-report-assembly.md` Output Files는 Primary DOCX + Supporting XLS from Task 2, “Both files should be packaged together”.

### 리서치 vs 추천

Task 1 리스크 평가는 연구. Task 3부터 추천이 산출의 일부다.

인용:
> **Recommendation**: BUY/HOLD/SELL
> Rating: BUY / OUTPERFORM
> “Arrive at defensible price target”
> “Provide clear buy/hold/sell recommendation”
> Page 1 rating box: BUY/OUTPERFORM/HOLD/UNDERPERFORM/SELL (task5)
> report-template rating box: OUTPERFORM / NEUTRAL / UNDERWEIGHT / etc.

`task5` 문장:
> “This report will be read by institutional investors making million-dollar decisions.”
> “This represents the complete professional work product. Deliver institutional-quality research worthy of a $1M+ investment decision.”

`report-template.md` 말미 Appendices:
> ### Required Disclosures
> - Analyst certification
> - Important disclosures
> - Company-specific disclosures
> - Legal entity disclosures
> - Other regulatory disclosures

본문 템플릿/체크리스트에 실제 disclosure 문장은 없고 제목만 있다.  
“not investment advice”, “for informational purposes only”, 적합성/라이선스 가드는 SKILL·참조에 없음.

`task5` Writing Style:
> Objective: Present facts, acknowledge risks
> Confident: State views clearly with supporting evidence
> Precise: Avoid "might", "could", "possibly"

### 참조/에셋 목록

- `references/task1-company-research.md`
- `references/task2-financial-modeling.md`
- `references/task3-valuation.md`
- `references/task4-chart-generation.md`
- `references/task5-report-assembly.md`
- `references/valuation-methodologies.md` — DCF / Trading Comps / Precedent / Reconciliation 이론. UFCF 공식, WACC, terminal, 멀티플 선택, control premium 20–40%, 가중 DCF 40–60% / Comps 25–40% / Precedent 15–25%. 결론 예: `Recommendation: BUY with target price of $45 (midpoint of base case)`
- `assets/report-template.md`
- `assets/quality-checklist.md`

---

## 스킬: earnings-preview

### Frontmatter

```
name: earnings-preview
description: Build pre-earnings analysis with estimate models, scenario frameworks, and key metrics to watch. Use before a company reports quarterly earnings to prepare positioning notes, set up bull/bear scenarios, and identify what will move the stock. Triggers on "earnings preview", "what to watch for [company] earnings", "pre-earnings", "earnings setup", or "preview Q[X] for [company]".
```

### 워크플로

1. Gather Context — company/quarter, consensus via web search, earnings date/time, prior-quarter call guidance.
2. Key Metrics Framework — Financial (revenue, EPS, margins, FCF, guidance) + Operational by sector (Tech/SaaS ARR/NRR/RPO; Retail SSS; Industrials backlog/book-to-bill; Financials NIM/credit; Healthcare scripts/pipeline).
3. Scenario Analysis — Bull / Base / Bear table (Revenue, EPS, Key Driver, Stock Reaction). 각 시나리오에 operational path, management commentary, historical stock move.
4. Catalyst Checklist — 3–5 items that determine reaction (metric vs consensus/whisper, guidance, narrative shift).
5. Output — One-page preview: company/quarter/date, consensus table, ranked metrics, bull/base/bear, catalyst checklist, “Trading setup: recent stock performance, implied move from options”.

### 리포트 구조

원페이지. DOCX 강제 없음. 표: consensus, scenarios, catalyst checklist.

### 리서치 vs 추천

포지셔닝·트레이딩 셋업이 목적.
> “prepare positioning notes”
> “Stock Reaction” 열
> “Trading setup: recent stock performance, implied move from options”
> “Whisper numbers from buy-side surveys are often more relevant than published consensus”

명시적 BUY/HOLD/SELL 필드는 이 SKILL.md에 없다. “not investment advice”도 없다.

### 참조

없음.

---

## 스킬: model-update

### Frontmatter

```
name: model-update
description: Update financial models with new data — quarterly earnings, management guidance, macro changes, or revised assumptions. Adjusts estimates, recalculates valuation, and flags material changes. Use after earnings, guidance updates, or when assumptions need refreshing. Triggers on "update model", "plug earnings", "refresh estimates", "update numbers for [company]", "new guidance", or "revise estimates".
```

### 워크플로

1. Identify What Changed — Earnings / Guidance / Estimate revision / Macro / Event-driven (M&A, restructuring, product, management).
2. Plug New Data — Prior Estimate vs Actual vs Delta (Revenue, GM, OpEx, EBITDA, EPS, key metrics); segment; BS/CF (cash, debt, share count, capex, WC).
3. Revise Forward Estimates — Old/New FY and Next FY for Revenue, EBITDA, EPS; assumption changes with reasons.
4. Valuation Impact — DCF, P/E (NTM EPS × target multiple), EV/EBITDA, **Price Target**.
5. Summary & Action — “Is this a thesis-changing event or noise?”; “Maintain or change rating?”; “New price target (if changed)”; “Upside/downside to current price”.
6. Output — Updated Excel (if user provides existing model), estimate change summary (markdown or Word), updated PT derivation.

Notes: reconcile to reported figures; GAAP vs adjusted; revision history; signal vs noise; compare to Street after update; share count/dilution.

### 리서치 vs 추천

Step 5가 명시적으로 레이팅·목표가 액션이다.
> **Rating / Price Target:**
> - Maintain or change rating?
> - New price target (if changed) with methodology
> - Upside/downside to current price

“not investment advice” 없음.

### 참조

없음.

---

## 스킬: morning-note

### Frontmatter

```
name: morning-note
description: Draft concise morning meeting notes summarizing overnight developments, trade ideas, and key events for coverage stocks. Designed for the 7am morning meeting format — tight, opinionated, actionable. Triggers on "morning note", "morning meeting", "what happened overnight", "trade idea", "morning call prep", or "daily note".
```

### 워크플로

1. Overnight Developments — earnings/guidance, M&A, management, product/reg, competitor analyst rating changes, macro; futures, sector ETF, commodities/FX, today’s data.
2. Format — “readable in 2 minutes”:
   - `[Date] Morning Note — [Analyst Name]` / `[Sector Coverage]`
   - **Top Call:** headline PMs need; 2–3 sentences; “Stock impact: price target, rating reiteration/change”
   - Overnight/Pre-Market Developments — one-line + “our take”
   - Key Events Today
   - **Trade Ideas** (if any) — `[Long/Short] [Company]: 1-2 sentence thesis + catalyst` / `Risk: What would make this wrong`
3. Quick Takes on Earnings — consensus vs actual table; **Our Take** 2–3 sentences “is this good or bad for the stock? Does it change our thesis?”; **Action**: Maintain / Upgrade / Downgrade? Adjust PT?
4. Output — Markdown for email/Slack, Word if formal, “Keep to 1 page max — PMs and traders won't read more”

### 리서치 vs 추천

가장 액션 지향.
> “tight, opinionated, actionable”
> “Be opinionated — morning notes that just summarize news without a view are useless”
> Trade Ideas: Long/Short + catalyst + what would make this wrong
> Action: Maintain / Upgrade / Downgrade rating? Adjust price target?
> “No news is a valid morning note — say nothing material overnight, maintaining positioning”
> “If you're wrong, own it in the next morning note — credibility matters more than being right every time”

컴플라이언스/“not advice” 문장 없음. 시간 스탬프 주의만 있음: “if you're writing at 6am, note that pre-market may change by open”.

### 참조

없음.

---

## 스킬: sector-overview

### Frontmatter

```
name: sector-overview
description: Create comprehensive industry and sector landscape reports covering market dynamics, competitive positioning, key players, and thematic trends. Use for client requests, sector initiations, thematic research pieces, or internal knowledge building. Triggers on "sector overview", "industry report", "market landscape", "sector analysis", "industry deep dive", or "thematic research".
```

### 워크플로

1. Define Scope — sector/subsector, purpose (client/internal/pitch/idea generation), depth 5–10 vs 20–30 pages, angle “Neutral landscape vs. thematic thesis”, universe public vs private.
2. Market Overview — TAM with source, 5y CAGR, forecast, segmentation; structure (top 5 share, value chain, business models, barriers); trends (3–5 tailwinds, headwinds, tech disruption, regulation, M&A).
3. Competitive Landscape — top 5–10 profiles table (Revenue, Growth, EBITDA Margin, Market Share, Key Differentiator) + 2–3 sentence profile, moat, recent developments, valuation snapshot (P/E, EV/EBITDA, EV/Revenue); dynamics (how they compete, share gain/loss, disruption).
4. Valuation Context — sector multiples current vs historical, premium/discount drivers, M&A multiples, vs broader market.
5. Investment Implications — “Where are the best risk/reward opportunities?”, thematic bets, “Key debates (bull vs. bear arguments)”, “Catalysts that could change the sector narrative”.
6. Output — Word or PowerPoint (market overview, competitive map, comparison table, valuation summary, charts) + Excel appendix.

Notes: source all TAM; distinguish TAM hype vs realistic; “note the date and flag data that may be stale”; charts essential; “If for a client, tailor the so what to their specific situation (M&A target identification, competitive positioning, market entry)”.

### 리포트 구조

고정 페이지 템플릿 없음. Step 2–5가 본문 골격. Depth 두 단: 5–10 or 20–30 pages.

### 리서치 vs 추천

섹터 레벨 함의까지 간다.
> Step 5: Investment Implications
> “Where are the best risk/reward opportunities?”
> “What thematic bets can be expressed through this sector?”

개별 종목 BUY/HOLD/SELL 필수 필드는 이 파일에 없다. “not investment advice” 없음.

### 참조

없음.

---

## 스킬: thesis-tracker

### Frontmatter

```
name: thesis-tracker
description: Maintain and update investment theses for portfolio positions and watchlist names. Track key data points, catalysts, and thesis milestones over time. Use when updating a thesis with new information, reviewing position rationale, or checking if a thesis is still intact. Triggers on "update thesis for [company]", "is my thesis still intact", "thesis check", "add data point to [company]", or "review my positions".
```

### 워크플로

1. Define or Load Thesis — Company; **Position: Long or Short**; 1–2 sentence thesis; 3–5 pillars; 3–5 invalidating risks; catalysts; **Target price / valuation**; **Stop-loss trigger**.
2. Update Log — Date, data point, thesis impact (strengthen/weaken/neutralize a pillar), **Action: No change / Increase position / Trim / Exit**, Updated conviction High/Medium/Low.
3. Thesis Scorecard — Pillar / Original Expectation / Current Status / Trend (예: Revenue growth >20%, Margin expansion, New product launch).
4. Catalyst Calendar — Date / Event / Expected Impact / Notes.
5. Output — “Thesis summary suitable for: Morning meeting discussion, Portfolio review, Risk committee presentation”. Concise markdown or Word with scorecard, updates, conviction.

Notes:
> “A thesis should be falsifiable — if nothing could disprove it, it's not a thesis”
> “Track disconfirming evidence as rigorously as confirming evidence”
> “Review theses at least quarterly”
> “If the user manages multiple positions, offer to do a full portfolio thesis review”
> “Store thesis data in a structured format so it can be referenced across sessions”

### 리서치 vs 추천

포지션 관리 스킬. Long/Short, stop-loss, Increase/Trim/Exit가 워크플로에 내장.  
“not investment advice” 없음.

### 참조

없음.

---

## 스킬: catalyst-calendar

### Frontmatter

```
name: catalyst-calendar
description: Build and maintain a calendar of upcoming catalysts across a coverage universe — earnings dates, conferences, product launches, regulatory decisions, and macro events. Helps prioritize attention and position ahead of events. Triggers on "catalyst calendar", "upcoming events", "what's coming up", "earnings calendar", "event calendar", or "catalyst tracker".
```

커맨드 기본 시계열: “next 2 weeks”.

### 워크플로

1. Define Coverage Universe — tickers, sector, include macro?, horizon (2 weeks / month / quarter).
2. Gather Catalysts
   - Earnings & Financial: quarterly date/time (pre/post), AGM, investor/analyst/capital markets day, debt maturity/refi
   - Corporate: product, FDA/reg, contract, M&A milestones, management transitions, insider windows/lockups
   - Industry: conferences, trade shows, comment periods, industry data
   - Macro: FOMC, jobs/CPI/GDP, ECB/BOJ, geopolitics
3. Calendar View table: Date | Event | Company/Sector | Type (Earnings/Corp/Industry/Macro) | Impact (H/M/L) | **Our Positioning** | Notes  
   Positioning 열: **Long/Short/Neutral**
4. Weekly Preview — This Week’s Key Events (consensus vs our estimate), Next Week, **Position Implications**: “Events that could move specific positions”, “Any pre-positioning recommended”, “Risk management ahead of binary events”
5. Output — Excel workbook (sortable), Weekly preview email/note (markdown), Optional Google Calendar

Notes: verify dates vs IR/Bloomberg/FactSet; pre-announce history; conference attendance vs absence; recurring monthly data templates; color-code Red/Yellow/Green; “Archive past catalysts with the actual outcome”.

### 리서치 vs 추천

캘린더 + 포지셔닝.
> Our Positioning: Long/Short/Neutral
> “Any pre-positioning recommended”
> “Helps prioritize attention and position ahead of events”

종목 레이팅 산출 필드는 없음. “not investment advice” 없음.

### 참조

없음.

---

## 스킬: idea-generation

### Frontmatter

```
name: idea-generation
description: Systematic stock screening and investment idea sourcing. Combines quantitative screens, thematic research, and pattern recognition to surface new long and short ideas. Use when looking for new ideas, running screens, or conducting thematic sweeps. Triggers on "idea generation", "stock screen", "find ideas", "what looks interesting", "screen for", "new ideas", or "pitch me something".
```

### 워크플로

1. Define Search Criteria — Direction Long/short/both; Market cap; Sector; Style (Value, growth, quality, special situation, event-driven); Geography; Theme.
2. Quantitative Screens
   - **Value**: P/E below sector median; EV/EBITDA below historical avg; FCF yield >5%; P/B below 1.5x; insider buying last 90 days; dividend yield above market
   - **Growth**: Rev >15% YoY; EPS >20% YoY; acceleration; expanding margins; ROIC >15%; NRR >110% SaaS
   - **Quality**: 5+ years consistent growth; stable/expanding margins; ROE >15%; low D/E; high FCF conversion; insider ownership >5%
   - **Short**: declining/decelerating rev; margin compression; rising receivables/inventory vs sales; insider selling; unjustified premium; high SI + deteriorating fundamentals; accounting red flags (auditor changes, restatements)
   - **Special Situation**: recent IPO/SPAC lockups; spin-offs last 12 months; restructuring; activist; management change at underperformers
3. Thematic Sweep — define thesis, map value chain, pure-play vs diversified, priced-in vs under-appreciated, second-order beneficiaries.
4. Idea Presentation — `[Company] — [Long/Short] — [One-Line Thesis]` + metrics vs peers table; Thesis 3–5 bullets (mispriced, what market missing, catalyst); Key Risks; Suggested Next Steps (“Build full model? Deep-dive diligence? Expert call?”)
5. Output — Shortlist 5–10 one-pagers, screening methodology, comparison table, prioritized research list.

Notes:
> “Screens surface candidates, not conclusions — every screen output needs fundamental work”
> “Avoid crowded trades — check ownership data, short interest, and how many analysts cover the name”
> “Contrarian ideas need a catalyst — being early without a catalyst is the same as being wrong”
> “Short ideas need higher conviction — timing is harder and risk is asymmetric”

### 리서치 vs 추천

아이디어 = Long/Short 피치. 스크린을 “conclusions”이 아니라고 못 박지만, 산출은 롱/숏 리스트다. 풀 initiation 전 단계로 “Suggested Next Steps”에 모델/딥다이브를 둔다.  
“not investment advice” 없음.

### 참조

없음.

---

## 리서치 vs 추천 안전장치 (플러그인 전체)

파일에서 **확인된 것**과 **없는 것**을 구분한다.

### 파일에 있는 추천/액션 언어

| 위치 | 인용 |
|---|---|
| earnings-analysis / commands/earnings.md | Rating BUY, Price Target, maintain/raise/lower, “Investment recommendation” |
| initiating-coverage Task 3/5 | BUY/HOLD/SELL, OUTPERFORM, 12-month PT, catalysts |
| report-template | OUTPERFORM / NEUTRAL / UNDERWEIGHT; Required Disclosures **제목만** |
| model-update | Maintain or change rating; new PT; upside/downside |
| morning-note | opinionated, Trade Ideas Long/Short, Upgrade/Downgrade |
| thesis-tracker | Long or Short; Increase / Trim / Exit; stop-loss |
| catalyst-calendar | Our Positioning Long/Short/Neutral; pre-positioning recommended |
| idea-generation | Long/Short ideas, one-line thesis |
| earnings-preview | positioning notes, Stock Reaction, trading setup, options implied move |
| sector-overview | “best risk/reward opportunities”, “thematic bets” |
| task5 writing | Avoid "might", "could", "possibly"; “million-dollar decisions” |

### 파일에 없는 것 (검색한 범위에서 문장 없음)

- “not investment advice”
- “for informational purposes only”
- 개인 맞춤 적합성(suitability) 확인
- 라이선스/등록 애널리스트만 추천 가능
- 추천과 리서치를 분리하라는 가드 (예: 분석만 하고 레이팅은 사용자에게 맡김)
- FINRA/SEC research-report 규정 본문
- 이해상충, 셀사이드 vs 바이사이드 구분 강제 (morning-note는 PM/trader 독자를 가정)

유일하게 가까운 항목은 `assets/report-template.md` Appendix “Required Disclosures” 불릿 제목(Analyst certification, Important disclosures 등)뿐이며, 문구 템플릿은 없다.

`quality-checklist.md`도 disclosure 본문 없이 인용·하이퍼링크·길이·차트 수를 검사한다.

`thesis-tracker`의 반증 추적, `idea-generation`의 “screens surface candidates, not conclusions”, `earnings-analysis`의 리스크 업데이트는 분석 품질 가드이지 추천 금지 가드가 아니다.

---

## 참조·에셋 전체 목록

플러그인 안에 존재하는 참조/에셋은 initiating-coverage와 earnings-analysis에만 있다.

```
skills/earnings-analysis/references/
  best-practices.md
  report-structure.md
  workflow.md

skills/initiating-coverage/references/
  task1-company-research.md
  task2-financial-modeling.md
  task3-valuation.md
  task4-chart-generation.md
  task5-report-assembly.md
  valuation-methodologies.md

skills/initiating-coverage/assets/
  quality-checklist.md
  report-template.md
```

나머지 7개 스킬은 SKILL.md 단일 파일. hooks는 빈 객체. README/LICENSE는 이 디렉터리 find 결과에 없음.

---

## 파일 간 불일치 (양쪽 인용, 해석 추가 없음)

1. **Initiation Page 1 헤더**  
   - SKILL.md / task5 / quality-checklist: `"INITIATING COVERAGE" header present (NOT "Company Update")`  
   - report-template.md: `"Investment Update" or "Company Update" page`, gray bar `RECOMMENDATION / COMPANY UPDATE`

2. **차트 수**  
   - SKILL.md Task 4/5: 25–35  
   - report-template.md: “20-30+ chart images”, “Generate 20-30+ chart images”

3. **폰트**  
   - initiating-coverage SKILL.md: Times New Roman  
   - task5 + quality-checklist: “Calibri, Arial, or similar”

4. **Excel 탭 수**  
   - Task 2: 6 essential tabs; Task 3 adds DCF/Sensitivity/Comps/Valuation summary  
   - quality-checklist: “15+ tabs” and a longer named list including Executive Summary, Assumptions, Charts, etc.

5. **Task 5 최종 산출물**  
   - SKILL.md Task 5: “DELIVER ONLY THIS 1 DOCX FILE”  
   - task5 Output Files / quality-checklist: DOCX + XLS packaged together; “No XLS financial model → MISSING DELIVERABLE”

6. **Task 3 폴더 예시 vs 산출 확장자**  
   - SKILL.md File Organization: `Task3_Valuation/[Company]_Valuation_Analysis.pdf`  
   - Task 3 Output: `.md` + Excel tabs

7. **레이팅 라벨 집합**  
   - Task 3: BUY/HOLD/SELL and example “BUY / OUTPERFORM”  
   - task5 Page 1: BUY/OUTPERFORM/HOLD/UNDERPERFORM/SELL  
   - report-template: OUTPERFORM / NEUTRAL / UNDERWEIGHT / etc.  
   - earnings best-practices headlines: OW, Buy, PT

8. **`/initiate` 커맨드 vs 스킬 단일 태스크 모드**  
   - command: “begin the 5-task workflow”  
   - skill: “SINGLE-TASK MODE ONLY”, never chain

9. **report-template TOC**는 “Executive Summary”인데, 같은 파일 Page 1은 Executive Summary가 아니라고 한다.

---

## 파일 인벤토리 (find 전체)

```
.claude-plugin/plugin.json
commands/catalysts.md
commands/earnings-preview.md
commands/earnings.md
commands/initiate.md
commands/model-update.md
commands/morning-note.md
commands/screen.md
commands/sector.md
commands/thesis.md
hooks/hooks.json
skills/catalyst-calendar/SKILL.md
skills/earnings-analysis/SKILL.md
skills/earnings-analysis/references/best-practices.md
skills/earnings-analysis/references/report-structure.md
skills/earnings-analysis/references/workflow.md
skills/earnings-preview/SKILL.md
skills/idea-generation/SKILL.md
skills/initiating-coverage/SKILL.md
skills/initiating-coverage/assets/quality-checklist.md
skills/initiating-coverage/assets/report-template.md
skills/initiating-coverage/references/task1-company-research.md
skills/initiating-coverage/references/task2-financial-modeling.md
skills/initiating-coverage/references/task3-valuation.md
skills/initiating-coverage/references/task4-chart-generation.md
skills/initiating-coverage/references/task5-report-assembly.md
skills/initiating-coverage/references/valuation-methodologies.md
skills/model-update/SKILL.md
skills/morning-note/SKILL.md
skills/sector-overview/SKILL.md
skills/thesis-tracker/SKILL.md
```
