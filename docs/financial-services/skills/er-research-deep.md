# Equity Research 스킬·커맨드 심층 읽기

범위: `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/equity-research/`  
방법: 해당 트리의 스킬·커맨드·참조·에셋만 인용. 파일에 없는 문구는 쓰지 않음.  
플러그인 메타: `.claude-plugin/plugin.json` — `"name": "equity-research"`, `"version": "0.1.2"`, `"description": "Equity research tools: earnings analysis, initiating coverage reports, and research workflows"`, `"author": { "name": "Anthropic FSI" }`.  
훅: `hooks/hooks.json`은 `{ "hooks": {} }`만 있다.

---

## 트리와 커맨드 맵

9개 커맨드 → 9개 스킬. 대부분 한 줄로 스킬을 로드한다. `/earnings`만 인라인 리포트 구조를 복제한다.

| 커맨드 | argument-hint | 로드 스킬 |
|---|---|---|
| `commands/catalysts.md` | `[timeframe, e.g. 'next 2 weeks']` | `catalyst-calendar` |
| `commands/earnings-preview.md` | `[company ticker]` | `earnings-preview` |
| `commands/earnings.md` | `[company name or ticker] [quarter, e.g. Q3 2024]` | `earnings-analysis` |
| `commands/initiate.md` | `[company ticker]` | `initiating-coverage` |
| `commands/model-update.md` | `[company ticker]` | `model-update` |
| `commands/morning-note.md` | `""` | `morning-note` |
| `commands/screen.md` | `[screen criteria, e.g. 'undervalued midcap tech']` | `idea-generation` |
| `commands/sector.md` | `[sector or industry]` | `sector-overview` |
| `commands/thesis.md` | `[company ticker]` | `thesis-tracker` |

`initiate.md` 본문:

> Load the `initiating-coverage` skill and begin the 5-task workflow to create an institutional-quality initiation report.

같은 스킬 SKILL.md는 반대로 **SINGLE-TASK MODE ONLY**, “Never execute multiple tasks in sequence”를 요구한다.

---

## Earnings Update 리포트 구조 (인용)

출처: `skills/earnings-analysis/SKILL.md`, `references/report-structure.md`, `commands/earnings.md`.

스펙 (SKILL.md):

> **Length**: 8-12 pages  
> **Word Count**: 3,000-5,000 words  
> **Tables**: 1-3 summary tables (NOT comprehensive)  
> **Figures**: 8-12 charts  
> **Turnaround**: 1-2 days (within 24-48 hours of earnings)  
> **Audience**: Clients already familiar with the company  
> **Focus**: What's NEW - beat/miss, updated estimates, thesis impact  
> **Font**: Times New Roman throughout (unless user specifies otherwise)

사용 금지:

> **Do NOT use if:**  
> - User requests "initiation report" → Use different skill  
> - User requests "flash note" or "quick take" → Different format  
> - Company is not already covered → Need initiation first

Initiation 대비 표 (SKILL.md 그대로):

| Aspect | Earnings Update | Initiation Report |
|--------|----------------|-------------------|
| **Length** | 8-12 pages | 30-50 pages |
| **Words** | 3,000-5,000 | 10,000-15,000 |
| **Tables** | 1-3 summary | 12-20 comprehensive |
| **Figures** | 8-12 | 25-35 |
| **Turnaround** | 1-2 days | 3-6 weeks |
| **Scope** | Quarterly results | Complete company |
| **Focus** | What's NEW | Everything |
| **Company Background** | Brief mention | 6-10 pages |
| **XLS Model** | Optional | Required |

파일명: `[Company]_Q[Quarter]_[Year]_Earnings_Update.docx`.

### PAGE 1: EARNINGS SUMMARY (`report-structure.md`)

```
[COMPANY NAME] ([TICKER])
[QUARTER] [YEAR] EARNINGS UPDATE

[Current Date]

Rating: [MAINTAIN/RAISE/LOWER] [RATING]
Price (as of [date]): $XX.XX
Price Target: [OLD → NEW if changed, or MAINTAIN $XXX]
```

```
EARNINGS SUMMARY
─────────────────────────────────────────────────
Q[X] [YEAR] RESULTS: [BEAT / INLINE / MISS]

                Reported    Est      Variance
Revenue         $X,XXX      $X,XXX   +$XXX (+X%)
EPS (Adj)       $X.XX       $X.XX    +$X.XX (+X%)

Key Takeaways:
■ [Takeaway 1 - one sentence]
■ [Takeaway 2 - one sentence]
■ [Takeaway 3 - one sentence]
```

Investment Impact 불릿 형식 (■ + **bold header** + 문단):

> ■ **Results beat on strong [segment/geography/product], maintaining positive momentum**  
> ■ **Margins expanded XXbps YoY despite [headwind], showcasing operational leverage**  
> ■ **Guidance raised / maintained / lowered - implies [interpretation]**  
> ■ **Maintaining [RATING] with [raised/unchanged] $XXX price target**

하단 `UPDATED FINANCIAL ESTIMATES` 표: FY old/new/change + next-year new. Note: `"E" = Estimate`. Source: `Company data, [Firm Name] estimates.`

`commands/earnings.md` Page 1 ASCII는 이미 추천을 박아 둔다:

> Rating: BUY | Price Target: $XXX (from $XXX)  
> Thesis intact; maintain BUY rating

### PAGES 2–12 (`report-structure.md` 목차)

- **PAGES 2-3: DETAILED RESULTS ANALYSIS** — Revenue Analysis (1 page), Profitability Analysis (1 page). 표: Quarterly Revenue Progression, Margin Analysis. 차트 2-3: quarterly revenue, EPS, margin trends.
- **PAGES 4-5: KEY METRICS & GUIDANCE** — Business Metrics, Guidance & Outlook. `MANAGEMENT GUIDANCE vs. ESTIMATES` 표 (New / Old / Change / Street). 차트 4–6.
- **PAGES 6-7: UPDATED INVESTMENT THESIS** — 각 pillar `Status: [STRENGTHENED / UNCHANGED / WEAKENED]`. Risks Update. 차트 7–8.
- **PAGES 8-10: VALUATION & ESTIMATES** — DCF update, comps, Price Target Methodology, DETAILED ESTIMATE UPDATES.
- **PAGES 11-12: APPENDIX (Optional)** — quarterly models, transcript highlights, peer comparison.

Price Target Methodology 인용:

```
Our $XXX price target (prior: $XXX) is based on:
- XX% DCF
- XX% NTM P/E of XX.Xx (vs. peers at XX.Xx)
- XX% EV/EBITDA

Implied upside: +XX% from current price of $XXX
```

포맷 규칙 (그대로):

> - Lead with numbers ("Revenue grew 15% to $1.2B" not "Strong revenue growth")  
> - Use "vs." not "versus"  
> - Be direct and concise  
> - Focus on what's NEW  
> - Use A for actual (Q3'24A)  
> - Use E for estimate (Q4'24E)

### 워크플로 경고 (`workflow.md`)

> Training data is OUTDATED. Actively search for and retrieve the MOST RECENT earnings materials. Using outdated earnings data is the #1 mistake in earnings analysis.

필수 순서: 오늘 날짜 기록 → “latest earnings” 검색 → 릴리스가 최근 3개월인지 확인 → transcript 날짜가 릴리스 ±1일과 일치. 90일 이상이면 중단.

5 phases: Data Collection (30-60 min) → Analysis (2-3 hours) → Chart Generation (1-2 hours, 8-12 charts) → Report Creation (2-3 hours) → Quality Check (30 min).

필수 차트 8종: Quarterly Revenue Progression, Quarterly EPS Progression, Quarterly Margin Trend, Revenue by Segment/Geography, Key Operating Metrics, Beat/Miss Summary, Estimate Revision, Valuation Chart.

### 품질·헤드라인 (`best-practices.md`)

Good:

> "Nike Q2 FY24: DTC Strength Offsets Wholesale Weakness - Maintaining OW, PT $95"

Bad:

> "Nike Quarterly Update" (too generic, no takeaway)

실수 금지 (발췌):

> ❌ Too comprehensive: Don't write an initiation-length report for quarterly results  
> ❌ Missing beat/miss  
> ❌ Not updating estimates  
> ❌ No investment impact: Must connect results to thesis and rating  
> ❌ Be concise: This is NOT a comprehensive report, stay focused on quarterly results

전달 요약 템플릿은 `Results: [BEAT / INLINE / MISS]`, `Rating: [MAINTAINED / RAISED / LOWERED] [RATING]`, `Price Target: $XXX (prior: $XXX)`를 요구한다. “not a recommendation” 문구는 이 파일에 없다.

---

## Initiating Coverage 리포트 구조 (인용)

출처: `skills/initiating-coverage/SKILL.md`, `assets/report-template.md`, `assets/quality-checklist.md`, `references/task5-report-assembly.md`.

5-task 파이프라인 (한 번에 한 태스크만):

| Task | Name | Prerequisites | Output |
|------|------|--------------|--------|
| **1** | Company Research | Company name/ticker | 6-8K word document |
| **2** | Financial Modeling | 10-K or financials access | Excel model (6 tabs) |
| **3** | Valuation Analysis | Financial model (Task 2) | Valuation + price target |
| **4** | Chart Generation | Tasks 1, 2, 3 + external data | 25-35 PNG/JPG charts |
| **5** | Report Assembly | ALL previous tasks (1-4) | 30-50 page DOCX report |

Deliverables Policy: Task 1 `.md`만, Task 2 `.xlsx`만, Task 3 `.md` + Excel 탭, Task 4 `.zip`만, Task 5 `.docx`만. “completion summaries / executive summaries / next steps documents” 금지.

Task 2 필수 탭 6개: Revenue Model, Income Statement, Cash Flow Statement, Balance Sheet, Scenarios, DCF Inputs.  
품질 체크리스트는 별도로 “15+ tabs”를 요구한다 (아래 불일치).

Task 3 출력:

> **Price target**: $XX.XX  
> **Recommendation**: BUY/HOLD/SELL  
> **Upside**: XX%  
> Key catalysts (3-5)

Task 4 4 mandatory charts: `chart_03` Revenue by product (stacked area), `chart_04` Revenue by geography (stacked bar), `chart_28` DCF sensitivity (2-way heatmap), `chart_32` Valuation football field.

Task 5 스펙:

> **Length**: 30-50 pages (MINIMUM 30)  
> **Word count**: 10,000-15,000 words (MINIMUM 10,000)  
> **Charts**: 25-35 embedded images  
> **Tables**: 12-20 comprehensive tables  
> **Format**: Professional DOCX with clickable hyperlinks

파일명: `[Company]_Initiation_Report_[Date].docx`.

### PAGE 1 헤더 충돌 (둘 다 원문)

`task5-report-assembly.md` / SKILL.md / quality-checklist:

> **"INITIATING COVERAGE" header** (NOT "Company Update")  
> Thesis-focused title (e.g., "AI Platform Leader Positioned for 40% CAGR")

`assets/report-template.md`:

> ## PAGE 1: INVESTMENT UPDATE (MOST IMPORTANT PAGE)  
> This is an "Investment Update" or "Company Update" page, not "Executive Summary"  
> `[OUTPERFORM / NEUTRAL / etc.] RECOMMENDATION / COMPANY UPDATE`

Rating box (`report-template.md`):

```
Rating:             [OUTPERFORM / NEUTRAL / UNDERWEIGHT / etc.]
Price ([Date]):     $[XX.XX]
Target Price:       $[XX.XX]
52-Week Range:      $[XX.XX] - $[XX.XX]
Market Cap:         $[XX.X]B
Enterprise Value:   $[XX.X]B
```

`task5`는 레이팅 집합을 `BUY/OUTPERFORM/HOLD/UNDERPERFORM/SELL`로 적는다.

불릿: ■ + **bold topic header** + 3–5문장. 하단 재무 표는 `[Year-3]A … [Year]E [Year+1]E`.

### TOC (`report-template.md`)

```
Executive Summary....................................................1
Investment Thesis & Risks..........................................3
Company Overview.......................................................6
  Business Description & History................................6
  Management & Ownership..........................................8
  Products & Technology...........................................9
  Customers & Go-to-Market......................................11
Growth Outlook & Drivers...........................................13
Financial Analysis & Performance.................................16
  Historical Performance........................................16
  Financial Projections.........................................19
Industry Overview & Competitive Landscape.....................21
  Market Size & TAM..............................................21
  Competitive Analysis..........................................23
  Industry Trends................................................25
Valuation Analysis..................................................27
Appendices & Disclosures...........................................31
```

SKILL.md 페이지 맵 (약간 다름):

> - Page 1: Investment Summary (INITIATING COVERAGE format)  
> - Pages 2-5: Investment thesis & risks  
> - Pages 6-17: Company 101  
> - Pages 18-30: Financial analysis & projections  
> - Pages 31-40: Valuation analysis  
> - Pages 41-50: Appendices

### Task 5 섹션 단어 수 (`task5-report-assembly.md`)

| Section | Minimum | Target | Critical? |
|---------|---------|--------|-----------|
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

Management bios: “300-400 words EACH for 3-4 executives”. Risks: 8–12 across company / industry / financial / macro.

### 밸류에이션  recon (`report-template.md`)

```
Valuation Method            Weight    Implied Value    Weighted Value
DCF Analysis                50%       $XX - $YY        $ZZ
Trading Comparables         30%       $XX - $YY        $ZZ
Precedent Transactions      20%       $XX - $YY        $ZZ
Weighted Average Price Target         $AA - $BB        $CC
```

Price Target & Recommendation 블록:

```
Current Price:              $XX.XX ([Date])
Price Target:               $YY.YY
Upside/Downside:            ZZ%

Recommendation:             BUY / HOLD / SELL
Time Horizon:               12 months
```

`task3-valuation.md` 최종 블록:

```
INVESTMENT RECOMMENDATION
Current Price:          $42.00 (as of [Date])
Price Target:           $59.00 (12-month)
Upside/(Downside):      +40.5%
Rating:                 BUY / OUTPERFORM
Time Horizon:          12 months
```

`valuation-methodologies.md`:

> Recommendation: BUY with target price of $45 (midpoint of base case)

성공 기준 (`task5`):

> 10. **Enable informed investment decision**  
>     - Client should understand company, valuation, risks  
>     - Should be indistinguishable from JPM/GS/MS research

> This report will be read by institutional investors making million-dollar decisions.

폰트 충돌: SKILL.md는 “Times New Roman throughout”. `quality-checklist.md`와 `task5`는 “Calibri, Arial, or similar”.

---

## 면책·"not a recommendation" 언어 (검색 결과)

**이 플러그인 트리 안에는 `"not a recommendation"` / `"Not investment advice"` / `"does not constitute"` / `"for informational purposes only"` 원문이 없다.**  
전 파일 grep: `not a recommendation` 0건. `Not investment advice` 0건. `does not constitute` 0건.

존재하는 면책·공시 **목록만** (`assets/report-template.md` Pages 35+: APPENDICES & DISCLOSURES):

```
### Required Disclosures
- Analyst certification
- Important disclosures
- Company-specific disclosures
- Legal entity disclosures
- Other regulatory disclosures
```

본문 문장은 제공되지 않는다. Analyst certification 텍스트, FINRA/NYSE 표준 면책, “this is not a recommendation” 문장은 **발명하지 않음 — 파일에 없음**.

반대로 플러그인은 추천을 **발행**한다:

- Earnings: `Rating: [MAINTAIN/RAISE/LOWER] [RATING]`, `commands/earnings.md`의 `Investment recommendation`, `maintain BUY rating`.
- Initiation: `Recommendation: BUY/HOLD/SELL`, `INVESTMENT RECOMMENDATION`, Page 1 rating box.
- Morning note: `Action: Maintain / Upgrade / Downgrade rating? Adjust price target?`
- Model-update: `Maintain or change rating?` / `New price target`.
- Thesis-tracker: `Position: Long or Short`, `Target price / valuation`.
- Idea-generation: `[Company Name] — [Long/Short] — [One-Line Thesis]`.

“This is NOT …”로 실제로 등장하는 문장은 면책이 아니라 품질 가드다:

- earnings `best-practices.md`: `This is NOT a comprehensive report, stay focused on quarterly results`
- initiating-coverage `task5`: `This is not a draft. This is not a summary. This is not an outline. This is the **FINAL PUBLICATION-READY REPORT**.`

---

## 나머지 스킬 (구조만 인용)

### Earnings Preview (`skills/earnings-preview/SKILL.md`)

원페이지. Consensus table + “what to watch” + Bull/Base/Bear.

```
| Scenario | Revenue | EPS | Key Driver | Stock Reaction |
|----------|---------|-----|------------|----------------|
| Bull | | | | |
| Base | | | | |
| Bear | | | | |
```

출력: Company/quarter/date, consensus, ranked metrics, scenario table, catalyst checklist, “Trading setup: recent stock performance, implied move from options”.  
노트: “Consensus estimates change — always note the source and date”; “Whisper numbers … often more relevant than published consensus”.

### Model Update (`skills/model-update/SKILL.md`)

트리거: earnings / guidance / estimate revision / macro / event-driven.  
표 3종: Prior Estimate vs Actual; Old/New FY; Valuation Method Prior/Updated (DCF, P/E NTM, EV/EBITDA, **Price Target**).  
출력: Updated Excel (사용자 모델이 있을 때), estimate change summary, updated PT derivation.  
노트: GAAP vs adjusted, share count, “Check consensus after updating”.

### Morning Note (`skills/morning-note/SKILL.md`)

> Keep it tight — a morning note should be readable in 2 minutes  
> Keep to 1 page max — PMs and traders won't read more

```
**[Date] Morning Note — [Analyst Name]**
**[Sector Coverage]**

**Top Call: [Headline — the one thing PMs need to hear]**
**Overnight/Pre-Market Developments**
**Key Events Today**
**Trade Ideas** (if any)
- [Long/Short] [Company]: 1-2 sentence thesis + catalyst
- Risk: What would make this wrong
```

Earnings quick take 표: Metric / Consensus / Actual / Beat/Miss.  
> Be opinionated — morning notes that just summarize news without a view are useless  
> "No news" is a valid morning note — say "nothing material overnight, maintaining positioning"

### Thesis Tracker (`skills/thesis-tracker/SKILL.md`)

신규 필드: Company, Position Long/Short, 1–2문장 thesis, 3–5 pillars, 3–5 risks, catalysts, target price, stop-loss.  
Update log: Date / Data point / Thesis impact / Action (`No change / Increase position / Trim / Exit`) / conviction.  
Scorecard 열: Pillar | Original Expectation | Current Status | Trend.  
> A thesis should be falsifiable — if nothing could disprove it, it's not a thesis

### Catalyst Calendar (`skills/catalyst-calendar/SKILL.md`)

캘린더 열: Date | Event | Company/Sector | Type | Impact (H/M/L) | Our Positioning | Notes. Type: Earnings/Corp/Industry/Macro. Positioning: Long/Short/Neutral.  
주간 프리뷰: This Week’s Key Events, Next Week Preview, Position Implications.  
출력: Excel workbook, weekly preview markdown, optional Google Calendar.  
컬러: “Red = high impact, Yellow = moderate, Green = routine”.

### Idea Generation (`skills/idea-generation/SKILL.md`)

파라미터: Direction, market cap, sector, style, geography, theme.  
스크린: Value / Growth / Quality / Short / Special Situation (각 불릿 기준은 SKILL.md에 수치로 명시: FCF yield >5%, P/B <1.5x, rev growth >15% 등).  
아이디어 카드: `[Company Name] — [Long/Short] — [One-Line Thesis]` + peer 표 + Thesis 3–5 bullets + Key Risks + Suggested Next Steps.  
출력: 5–10 ideas, methodology, comparison table, prioritized list.  
> Screens surface candidates, not conclusions  
> Short ideas need higher conviction — timing is harder and risk is asymmetric

### Sector Overview (`skills/sector-overview/SKILL.md`)

깊이: “High-level overview (5-10 pages) or deep dive (20-30 pages)”.  
스텝: Market Overview (TAM, structure, trends) → Competitive Landscape (top 5–10 프로필 표) → Valuation Context → Investment Implications → Output Word/PPT + Excel appendix.  
> Source all market size data — cite the research firm or methodology  
> Distinguish between TAM hype and realistic addressable market

---

## Task 1–4 산출물 요약 (인용만)

**Task 1** 문서 목차 (`task1-company-research.md`): Company Overview, History, Management Team, Products & Services, Customers & GTM, Industry Overview, Competitive Landscape, Market Opportunity (TAM), Risk Assessment. 파일: `[Company]_Research_Document_[Date].md`. Task 5는 이 6–8K 단어를 “almost verbatim” 복사.

**Task 2** 색: Blue = hardcoded inputs, Black = formulas, Green = cross-sheet links, Red = errors. 히스토리 3–5년 + 전망 5년. IS 40–50 line items, revenue product 20–30 rows, geography 15–20 rows. 파일: `[Company]_Financial_Model_[Date].xlsx`.

**Task 3** 가중 예: DCF 50% / Comps 40% / Precedent 10%. Comps 통계 행 필수: max / 75th / median / 25th / min. Terminal value “< 70% of total enterprise value”. 산티티: historical multiple, peer premium, implied growth, WACC 8–14% typical.

**Task 4** 25 required + 10 optional, 300 DPI PNG, zip + `chart_index.txt`. 데이터 맵: Task 1 → 9 charts, Task 2 → 8, Task 3 → 6, External → 2 (`chart_01` stock, `chart_34` historical multiples).

---

## 원문 내부 불일치 (파일에 있는 대로)

1. **한 번에 전부 vs 한 태스크**: `commands/initiate.md`는 “begin the 5-task workflow”. SKILL.md는 “Never chain multiple tasks together automatically”.
2. **Page 1 타이틀**: Task 5/checklist = `INITIATING COVERAGE` (NOT Company Update). `report-template.md` = “Investment Update” / “COMPANY UPDATE”.
3. **레이팅 라벨**: template `OUTPERFORM / NEUTRAL / UNDERWEIGHT`; Task 3/5 `BUY/HOLD/SELL` 또는 `BUY/OUTPERFORM/HOLD/UNDERPERFORM/SELL`. Earnings 예시는 OW, Buy, MAINTAIN OUTPERFORM가 혼재.
4. **Excel 탭 수**: SKILL Task 2 = 6 essential tabs. `quality-checklist.md` = “15+ tabs” (Executive Summary, Assumptions, Historical Financials, … Charts).
5. **폰트**: SKILL.md Times New Roman. Task 5 / checklist Calibri or Arial.
6. **차트 캡션 위치**: earnings `report-structure.md`는 caption **above** (`Figure X - [Title]`). initiation `report-template.md`는 caption **below**.
7. **Task 4 의존성**: SKILL 표는 “Tasks 1, 2, 3”. 같은 파일 Important Notes는 “Task 4 requires Tasks 2 & 3”.
8. **면책 본문 없음**: Required Disclosures는 불릿 제목만. 추천 문장은 본문에 반복됨.

---

## 인용·하이퍼링크 규칙 (공통)

Earnings와 Initiation 모두:

> ALL URLs are CLICKABLE HYPERLINKS (not plain text)  
> Blue, underlined hyperlink formatting in Word document  
> No raw URLs displayed anywhere in document

필수 소스 (earnings): earnings release, 10-Q EDGAR, transcript, investor presentation, consensus “as of” date, prior guidance.  
Initiation 말미: “Data Sources & References” 페이지, 카테고리별 SEC / transcripts / company materials / industry reports / news.
