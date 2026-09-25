# PE 플러그인 스킬·커맨드 분석 (IC 메모 / DD)

출처: `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/private-equity/`  
작성 원칙: 스킬·커맨드 원문에 있는 내용만 인용. 원문에 없는 수치·프로세스·산출물은 추가하지 않음.

---

## 범위와 파일 인벤토리

플러그인 루트에 존재하는 항목은 아래가 전부이다.

| 경로 | 내용 |
|------|------|
| `.claude-plugin/plugin.json` | 플러그인 매니페스트 |
| `.mcp.json` | `{"mcpServers": {}}` (빈 객체) |
| `hooks/hooks.json` | `{"hooks": {}}` (빈 객체) |
| `commands/` | 커맨드 10개 (각 파일이 대응 스킬을 로드) |
| `skills/<name>/SKILL.md` | 스킬 10개. 각 스킬 디렉터리에는 `SKILL.md`만 존재. `references/`, `scripts/`, `assets/` 없음 |

다른 버티컬(equity-research, financial-analysis, investment-banking)과 달리 PE 플러그인 안에는 README가 없다. 스킬 부가 문서도 없다.

---

## 플러그인 매니페스트

`.claude-plugin/plugin.json` 원문:

```json
{
  "name": "private-equity",
  "version": "0.1.2",
  "description": "Private equity deal sourcing and workflow tools: company discovery, CRM integration, and founder outreach",
  "author": {
    "name": "Anthropic FSI"
  }
}
```

매니페스트 description은 소싱/CRM/아웃리치로 좁게 적혀 있으나, 실제 스킬 세트는 소싱부터 포트폴리오 운영까지 10개이다. 상위 README 표는 `"Sourcing, screening, diligence checklists, IC memos, portfolio monitoring."`로 요약한다.

---

## 커맨드–스킬 매핑

커맨드 파일은 모두 짧은 래퍼이다. 패턴: 스킬 로드 → 인자가 있으면 사용, 없으면 사용자에게 요청.

| 커맨드 파일 | description (frontmatter) | argument-hint | 로드하는 스킬 |
|-------------|---------------------------|---------------|---------------|
| `commands/source.md` | Source deals — discover companies and draft founder outreach | `[sector or criteria, e.g. 'industrial services in Texas $10-50M']` | `deal-sourcing` |
| `commands/screen-deal.md` | Screen an inbound deal (CIM or teaser) | `[path to CIM/teaser file]` | `deal-screening` |
| `commands/dd-checklist.md` | Generate a due diligence checklist | `[company name]` | `dd-checklist` |
| `commands/dd-prep.md` | Prep for a diligence meeting or expert call | `[company name] [meeting type]` | `dd-meeting-prep` |
| `commands/unit-economics.md` | Analyze unit economics (ARR cohorts, LTV/CAC, retention) | `[company name or path to data]` | `unit-economics` |
| `commands/returns.md` | Build IRR/MOIC sensitivity tables | `[company or deal parameters]` | `returns-analysis` |
| `commands/ic-memo.md` | Draft an investment committee memo | `[company name]` | `ic-memo` |
| `commands/portfolio.md` | Review portfolio company performance | `[company name or path to financial package]` | `portfolio-monitoring` |
| `commands/value-creation.md` | Build a post-acquisition value creation plan | `[company name]` | `value-creation-plan` |
| `commands/ai-readiness.md` | Scan the portfolio for the highest-leverage AI opportunities | `[path to quarterly materials folder, or company names]` | `ai-readiness` |

상위 README 표와 1:1 일치한다. 커맨드 본문에 추가 로직은 없다.

---

## IC 메모 구조 (원문 인용)

스킬: `skills/ic-memo/SKILL.md`  
커맨드: `commands/ic-memo.md` — `"Load the ic-memo skill and draft a structured IC memo synthesizing due diligence findings, financial analysis, and deal terms."`

### 트리거

Frontmatter description:

> Draft a structured investment committee memo for PE deal approval. Synthesizes due diligence findings, financial analysis, and deal terms into a professional IC-ready document. Use when preparing for investment committee, writing up a deal, or creating a formal recommendation. Triggers on "write IC memo", "investment committee memo", "deal write-up", "prepare IC materials", or "recommendation memo".

### Step 1 입력 (원문 목록)

> Collect from the user (or from prior analysis in the session):
>
> - Company overview and business description
> - Industry/market context
> - Historical financials (3-5 years)
> - Management assessment
> - Deal terms (price, structure, financing)
> - Due diligence findings (commercial, financial, legal, operational)
> - Value creation plan / 100-day plan
> - Returns analysis (base, upside, downside)

세션 내 선행 분석에서 가져오라고 명시되어 있다. DD findings, value creation plan/100-day plan, returns analysis가 IC 입력으로 직접 연결된다.

### Step 2 표준 메모 형식 (원문 전체)

스킬이 `"Standard IC memo format:"`으로 규정한 구조는 아래와 같다. 분량·하위 불릿까지 원문 그대로이다.

**I. Executive Summary** (1 page)
- Company description, deal rationale, key terms
- Recommendation and headline returns
- Top 3 risks and mitigants

**II. Company Overview** (1-2 pages)
- Business description, products/services
- Customer base and go-to-market
- Competitive positioning
- Management team

**III. Industry & Market** (1 page)
- Market size and growth
- Competitive landscape
- Secular trends / tailwinds
- Regulatory environment

**IV. Financial Analysis** (2-3 pages)
- Historical performance (revenue, EBITDA, margins, cash flow)
- Quality of earnings adjustments
- Working capital analysis
- Capex requirements

**V. Investment Thesis** (1 page)
- Why this is an attractive investment (3-5 pillars)
- Value creation levers (organic growth, margin expansion, M&A, multiple expansion)
- 100-day priorities

**VI. Deal Terms & Structure** (1 page)
- Enterprise value and implied multiples
- Sources & uses
- Capital structure / leverage
- Key legal terms

**VII. Returns Analysis** (1 page)
- Base, upside, and downside scenarios
- IRR and MOIC across scenarios
- Key assumptions driving returns
- Sensitivity analysis

**VIII. Risk Factors** (1 page)
- Key risks ranked by severity and likelihood
- Mitigants for each risk
- Deal-breaker risks (if any)

**IX. Recommendation**
- Clear recommendation: Proceed / Pass / Conditional proceed
- Key conditions or next steps

섹션 I–VIII에 페이지 분량이 붙어 있다. IX Recommendation에는 페이지 수가 없다. I–VIII 합산은 스킬이 명시한 범위로 9–12페이지이다 (1+1–2+1+2–3+1+1+1+1). IX는 미기재.

추천 옵션은 세 가지뿐이다: **Proceed / Pass / Conditional proceed**.

### Step 3 산출 형식

- Default: Word document (.docx) with professional formatting
- Alternative: Markdown for quick review
- Include tables for financials and returns, not just prose

### Important Notes (원문)

> - IC memos should be factual and balanced — present both bull and bear cases honestly
> - Don't minimize risks. IC members will find them anyway; credibility matters
> - Use the firm's standard memo template if the user provides one
> - Financial tables should tie — check that EBITDA bridges, S&U balances, and returns math is consistent
> - Ask for missing inputs rather than making assumptions on deal terms or returns

원문에 없는 것: 서명란, 첨부 목록, 페이지 번호 규칙, 폰트/여백, 컴프 표, LBO 모델 상세, 법적 면책 문구.

---

## 딜 스크리닝 기준 (원문 인용)

스킬: `skills/deal-screening/SKILL.md`  
커맨드: `commands/screen-deal.md` — `"Load the deal-screening skill and quickly evaluate an inbound deal against the fund's investment criteria."` 파일 경로가 있으면 사용, 없으면 딜 자료/설명을 요청.

### 트리거

> Quickly screen inbound deal flow — CIMs, teasers, and broker materials — against the fund's investment criteria. Extracts key deal metrics, runs a pass/fail framework, and outputs a one-page screening memo. Use when reviewing new deal flow, triaging inbound materials, or deciding whether to take a first call. Triggers on "screen this deal", "review this CIM", "should we look at this", "triage this teaser", or "deal screening".

### Step 1: Extract Deal Facts (원문)

CIM, teaser, 또는 description에서 추출:

- **Company**: Name, location, sector/subsector
- **Description**: What they do (1-2 sentences)
- **Financials**: Revenue, EBITDA, margins, growth rate
- **Deal type**: Platform, add-on, recap, minority, carve-out
- **Asking price / valuation**: Multiple, enterprise value if stated
- **Seller motivation**: Why selling now
- **Management**: Rolling or exiting
- **Key customers**: Concentration risk
- **Key risks**: Obvious red flags

Deal type 열거는 다섯 가지: Platform, add-on, recap, minority, carve-out.

### Step 2: Screen Against Criteria (원문 표)

스킬 문구: `"Apply the fund's investment criteria (ask user if not known):"`

펀드 기준의 기본값(숫자 밴드)은 스킬에 없다. 기준 **항목**만 고정되어 있다.

| Criterion | Target | Actual | Pass/Fail |
|-----------|--------|--------|-----------|
| Revenue range | | | |
| EBITDA range | | | |
| EBITDA margin | | | |
| Growth profile | | | |
| Sector fit | | | |
| Geography | | | |
| Deal size / EV | | | |
| Valuation (x EBITDA) | | | |
| Customer concentration | | | |
| Management continuity | | | |

10개 기준. Target/Actual/Pass-Fail은 빈 칸이다. 컷오프 수치(예: 최소 EBITDA, 최대 고객 집중도)는 원문에 없다.

### Step 3: Quick Assessment (원문)

> Provide a 3-part assessment:
>
> 1. **Verdict**: Pass / Further Diligence / Hard Pass
> 2. **Bull case** (2-3 bullets): Why this could be a good deal
> 3. **Bear case** (2-3 bullets): Key risks and concerns
> 4. **Key questions**: What you'd need to answer on a first call

헤더는 `"3-part"`이나 번호는 1–4이다. Verdict 값은 **Pass / Further Diligence / Hard Pass** 세 가지. IC 메모의 Proceed / Pass / Conditional proceed와 문구가 다르다.

### Step 4 산출

> One-page screening memo suitable for sharing with partners or an IC quick screen.

파일 형식(.docx/.md)은 이 스킬에 지정되어 있지 않다. IC 메모 스킬만 docx/markdown을 명시한다.

### Important Notes (원문)

> - Speed matters — screening should take minutes, not hours
> - Be direct about red flags. Don't bury concerns
> - If financials seem inconsistent or incomplete, flag it explicitly
> - Ask for the fund's criteria upfront if this is the first screening
> - Save screening criteria in memory for future deals once confirmed

기준은 사용자에게 묻고, 확인되면 memory에 저장하라고 되어 있다. 저장된 기본 기준표는 플러그인 안에 없다.

---

## 딜 소싱 (`deal-sourcing` / `/source`)

3-step sourcing pipeline.

### Step 1: Discover Companies

사용자 기준으로 타깃을 찾고 숏리스트를 만든다.

- **Sector/industry focus**: 예시는 `"B2B SaaS in healthcare"`, `"industrial services in the Southeast"`
- **Deal parameters**: Revenue range, EBITDA range, growth profile, geography, ownership type (founder-owned, PE-backed, corporate carve-out)
- **Sources**: web search, industry reports, conference attendee lists, trade publications, competitor landscapes
- **Output** 필드: name, description, estimated revenue/size, location, founder/CEO name, website, why they fit the thesis

### Step 2: CRM Check

아웃리치 전에 기존 관계를 확인한다.

- Search the user's email (Gmail) for prior correspondence
- Search Slack for internal mentions
- Ask: `"Have you or your team had any prior contact with [Company]?"`
- 회사별 태그: **"New"** / **"Existing"** (요약 포함) / **"Previously Passed"**

### Step 3: Draft Founder Outreach

이메일 구조 (원문 4단):

1. Brief intro — who you are and your firm
2. Why this company caught your attention — reference something specific
3. What you're looking for — partnership, not just a transaction
4. Soft ask — `"Would you be open to a brief conversation?"`

가드레일: 4–6 sentences max. Subject는 짧고 구체적, `"Investment Opportunity"` 금지. 첫 접촉에 첨부 금지. Gmail sent 메일에서 `"reaching out"`, `"introduction"`, `"partnership"`으로 톤을 맞춘다. 숏리스트를 먼저 보여 주고, **명시적 승인 없이 이메일을 보내지 않는다.**

예시 인터랙션 입력: `"Find me founder-owned industrial services companies in Texas doing $10-50M revenue"`. 출력 흐름: 웹 검색 → 5–8개 숏리스트 → Gmail/Slack 체크 → "New"만 초안 → 사용자 리뷰. `"5 well-researched targets beat 20 generic ones"`.

---

## DD 체크리스트 (`dd-checklist` / `/dd-checklist`)

### Step 1 스코프 질문

- Target company: Name, sector, business model
- Deal type: Platform acquisition, add-on, growth equity, recap, carve-out
- Deal size / complexity
- Key concerns (customer concentration, regulatory, environmental 등)
- Timeline: When is LOI / close targeted?

Deal type 열거는 screening의 다섯 가지와 거의 같으나 여기에는 **growth equity**가 있고 **minority**는 없다.

### Step 2 워크스트림 (원문 7개)

**Financial Due Diligence**
- Quality of earnings (QoE) — revenue and EBITDA adjustments
- Working capital analysis — normalized vs. actual
- Debt and debt-like items
- Capital expenditure (maintenance vs. growth)
- Tax structure and exposure
- Audit history and accounting policies
- Pro forma adjustments (run-rate, synergies)

**Commercial Due Diligence**
- Market size and growth (TAM/SAM/SOM)
- Competitive positioning and market share
- Customer analysis — concentration, retention, NPS
- Pricing power and contract structure
- Sales pipeline and backlog
- Go-to-market effectiveness

**Legal Due Diligence**
- Corporate structure and org chart
- Material contracts (customer, supplier, partnership)
- Litigation history and pending claims
- IP portfolio and protection
- Regulatory compliance
- Employment agreements and non-competes

**Operational Due Diligence**
- Management team assessment
- Organizational structure and key person risk
- IT systems and infrastructure
- Supply chain and vendor dependencies
- Facilities and real estate
- Insurance coverage

**HR / People Due Diligence**
- Org chart and headcount trends
- Compensation benchmarking
- Benefits and pension obligations
- Key employee retention risk
- Culture assessment
- Union/labor agreements

**IT / Technology Due Diligence** (for tech-enabled businesses)
- Technology stack and architecture
- Technical debt assessment
- Cybersecurity posture
- Data privacy compliance (GDPR, CCPA, SOC2)
- Product roadmap and R&D spend
- Scalability assessment

**Environmental / ESG** (where applicable)
- Environmental liabilities
- Regulatory compliance history
- ESG risks and opportunities

IC 메모 Step 1의 DD 카테고리는 `"commercial, financial, legal, operational"` 네 가지이다. 체크리스트는 여기에 HR, IT, ESG를 더한다.

### Step 3 상태 추적 표

| Item | Workstream | Priority | Status | Owner | Notes |
|------|-----------|----------|--------|-------|-------|

상태 옵션 (원문 순서): **Not Started → Requested → Received → In Review → Complete → Red Flag**

예시 행: `"QoE report | Financial | P0 | Pending"` , `"Customer interviews | Commercial | P0 | In Progress | 3 of 10 complete"`

### Step 4 레드플래그 필드

- What was found
- Which workstream
- Severity: **deal-breaker / significant / manageable**
- Mitigant or path to resolution
- Impact on valuation or deal terms

### Step 5 산출

- Excel workbook with tabs per workstream (default)
- Summary dashboard: % complete by workstream, outstanding items, red flags
- Weekly status update format for deal team

### 섹터별 추가 항목 (원문 5개)

- **Software/SaaS**: ARR quality, cohort analysis, hosting costs, SOC2
- **Healthcare**: Regulatory approvals, reimbursement risk, payor mix
- **Industrial**: Equipment condition, environmental remediation, safety record
- **Financial services**: Regulatory capital, compliance history, credit quality
- **Consumer**: Brand health, channel mix, seasonality, inventory management

노트: P0는 LOI/close 게이트. 셀러 응답 지연은 이슈 신호로 플래그. 데이터룸 대비 갭 식별. 체크리스트는 living document.

---

## DD 미팅 준비 (`dd-meeting-prep` / `/dd-prep`)

커맨드 미팅 타입 힌트: `"management presentation, expert call, customer reference"`. 스킬 Step 1은 다섯 가지: **Management presentation, expert call, customer reference, advisor check-in, site visit**. advisor check-in과 site visit에는 질문 세트가 없다.

### 미팅 타입별 질문 (원문에 있는 것만)

**Management Presentation** — 6개 블록:

Business Overview (warm-up)
- Walk us through the founding story and key milestones
- How do you describe the business to someone unfamiliar with the space?
- What are you most proud of? What would you do differently?

Revenue & Growth
- Walk us through revenue by customer/segment/geography
- What's driving growth? Price vs. volume vs. new customers
- What does the sales cycle look like? How has win rate trended?
- Where do you see the biggest growth opportunities in the next 3-5 years?

Competitive Positioning
- Who do you lose deals to and why?
- What's your moat? How defensible is it?
- How do customers evaluate you vs. alternatives?

Operations & Team
- Walk us through the org chart — who are the key people?
- What roles are you hiring for? What's been hardest to fill?
- What keeps you up at night operationally?

Financial Deep-Dive
- Walk us through the margin bridge — what's changed and why?
- Any one-time or non-recurring items we should understand?
- How do you think about capex — maintenance vs. growth?
- Working capital seasonality?

Forward Look
- Walk us through the budget/plan for next year
- What assumptions are you most/least confident in?
- What would need to go right/wrong to significantly beat/miss plan?

**Expert Network Call** (5문항)
- How do you view [company]'s positioning in the market?
- What are the secular trends driving this space?
- Who are the strongest competitors and why?
- What risks should an investor be aware of?
- If you were buying this business, what would you diligence most carefully?

**Customer Reference Call** (5문항)
- How did you find [company] and why did you choose them?
- What alternatives did you evaluate?
- What do they do well? Where could they improve?
- How likely are you to renew/expand? What would change that?
- If they raised prices 10-20%, how would you react?

### Step 3–5

벤치마크: industry growth rates and margin profiles; comparable company metrics (세션에 comps가 있을 때); CIM/데이터룸 follow-up; 데이터 소스 간 discrepancy.

Red flags to probe: CIM/재무 불일치, 고객 집중·이탈, 경영진 공백·최근 퇴사, unusual accounting, missing data room items.

산출은 one-page meeting prep doc:

1. Meeting logistics: Who, when, where, duration
2. Objectives: Top 3 things you need to learn
3. Question list: Prioritized, grouped by topic (star the must-asks)
4. Benchmarks
5. Red flags
6. Follow-up items

노트: open-ended, don't lead the witness, body language 기록, 항상 `"What haven't we asked about that we should?"`로 끝낸다. 질문 상한 **15–20**, 세션 **60–90 min**.

---

## 유닛 이코노믹스 (`unit-economics` / `/unit-economics`)

대상: `"software/SaaS, recurring revenue, and subscription businesses"`.

### Step 1 비즈니스 모델 4종

- SaaS / Subscription: ARR, net retention, cohorts
- Recurring services: Contract value, renewal rates, upsell
- Transaction / usage-based: Revenue per transaction, volume trends, take rate
- Hybrid: Break down by revenue stream

### Step 2 핵심 지표

**ARR / Revenue Quality**: ARR bridge (`Beginning ARR → New → Expansion → Contraction → Churn → Ending ARR`); ARR by cohort; Top 10/20/50 concentration; Recurring vs. non-recurring vs. professional services; ACV distribution, multi-year %, auto-renewal %.

**Customer Economics**
- CAC = Total S&M spend / new customers acquired
- LTV = (ARPU × Gross Margin) / Churn Rate
- LTV:CAC — `"Target >3x for healthy businesses"`
- CAC payback period
- Blended vs. segmented (enterprise vs. SMB vs. mid-market)

**Retention**: Gross retention; Net retention (NDR); Logo churn; Dollar churn; Expansion rate.

**Cohort matrix**: Year 0–4, 빈티지 2020–2023 예시 숫자가 들어 있다 (2020: $1.0M → $1.1M → $1.2M → $1.1M 등). 절대액과 indexed (Year 0 = 100%) 둘 다.

**Margin Waterfall**: Revenue → Gross Profit → Contribution Margin → EBITDA. Fully loaded unit economics. Gross margin by stream.

### Step 3 벤치마크 (원문 수치만)

| 지표 | Best-in-class | good | concerning |
|------|---------------|------|------------|
| SaaS Rule of 40 | Growth rate + EBITDA margin > 40% (단일 임계) | | |
| SaaS Magic Number | Net new ARR / prior period S&M spend > 0.75x (단일 임계) | | |
| NDR | >120% | >110% | <100% |
| LTV:CAC | >5x | >3x | <2x |
| Gross retention | >95% | >90% | <85% |
| CAC payback | <12mo | <18mo | >24mo |

### Step 4 Revenue Quality Score (1–5)

Factor: Recurring %, Net retention, Customer concentration, Cohort stability, Growth durability, Margin profile, Overall.

### Step 5 산출

- Excel: ARR bridge, cohort matrix, unit economics dashboard
- Summary slide with key metrics and benchmarks
- Red flags and areas for further diligence

노트: raw customer-level data를 요청. NDR>100%가 높은 gross churn을 가릴 수 있으니 둘 다 보여 준다. `"Cohort analysis is the single most important view for revenue quality"`. contracted ARR vs recognized revenue 구분. usage-based는 전통 ARR보다 consumption/expansion. professional services는 별도 평가 (not recurring, typically lower margins).

---

## 수익률 분석 (`returns-analysis` / `/returns`)

IC와의 연결: description에 `"preparing IC returns exhibits"`; Step 5에 `"One-page returns summary suitable for IC deck"`.

### Step 1 입력 그룹

**Entry:** Entry EBITDA (LTM or NTM); Entry multiple (EV / EBITDA); Enterprise value; Net debt at close; Equity check size; Transaction fees & expenses

**Financing:** Senior debt (x EBITDA, rate, amortization); Subordinated debt / mezzanine; Total leverage at entry (x EBITDA); Equity contribution

**Operating Assumptions:** Revenue growth rate (annual); EBITDA margin trajectory; Capex as % of revenue; Working capital changes; Debt paydown schedule

**Exit:** Hold period (years); Exit multiple (EV / EBITDA); Exit EBITDA (calculated from growth assumptions)

### Step 2 Base Case 표

Entry EV; Equity invested; Exit EBITDA; Exit EV; Net debt at exit; Exit equity value; **MOIC**; **IRR**; Cash-on-cash.

Returns waterfall: EBITDA growth; Multiple expansion/contraction; Debt paydown; Fee/expense drag.

### Step 3 민감도 매트릭스 4종

1. **Entry Multiple vs. Exit Multiple** — 행 Entry 7x–10x, 열 Exit 6x–10x (표 헤더만 채워져 있음)
2. **EBITDA Growth vs. Exit Multiple** (at fixed entry)
3. **Leverage vs. Exit Multiple** (at fixed entry and growth)
4. **Hold Period vs. Exit Multiple**

셀 형식: `"IRR / MOIC"`.

### Step 4 시나리오 표

열: Bull / Base / Bear  
행: Revenue CAGR; Exit EBITDA margin; Exit multiple; Exit EBITDA; MOIC; IRR

### Key Formulas (원문)

- **MOIC** = Exit Equity Value / Equity Invested
- **IRR** = solve for r: Equity Invested × (1 + r)^n = Exit Equity Value (adjust for interim cash flows)
- **Returns attribution**:
  - Growth: (Exit EBITDA - Entry EBITDA) × Exit Multiple / Equity
  - Multiple: (Exit Multiple - Entry Multiple) × Entry EBITDA / Equity
  - Leverage: Debt paydown over hold period / Equity

### 산출

Excel: Assumptions tab; Returns calculation; Sensitivity tables (conditional coloring); Scenario summary. 그리고 IC deck용 1페이지.

노트: gross and net of fees/carry; management rollover/co-invest가 equity check를 바꿈; dividend recaps/interim distributions가 IRR에 영향; transaction costs `"typically 2-4% of EV"`; tax (asset vs. stock, 338(h)(10))가 after-tax returns에 영향.

원문에 없는 것: 목표 IRR/MOIC 허들, 기본 레버리지 배수, 기본 홀드 기간.

---

## 포트폴리오 모니터링 (`portfolio-monitoring` / `/portfolio`)

입력: Excel / PDF / CSV 월·분기 패키지. 추출: Revenue, EBITDA, cash balance, debt outstanding, capex, working capital. 비교: prior period and budget/plan.

### Financial KPIs (원문)

- Revenue vs. budget ($ and %)
- EBITDA and EBITDA margin vs. budget
- Cash balance and net debt
- Leverage ratio (Net Debt / LTM EBITDA)
- Interest coverage ratio
- Capex vs. budget
- Free cash flow

### Operational KPIs (묻거나 데이터에서 추론)

- Customer count / revenue per customer
- Employee headcount / revenue per employee
- Backlog / pipeline
- Churn / retention rates

### RAG 임계 (원문)

- **Green**: Within 5% of plan
- **Yellow**: 5-15% below plan — flag for discussion
- **Red**: >15% below plan or covenant breach risk — immediate attention

위쪽 편차(plan 대비 초과) 임계는 없다. `"below plan"`만 정의.

### 요약 출력 5항

1. One-paragraph executive summary (`"Company X is tracking [ahead/behind/on] plan..."`)
2. KPI table: actual vs. budget vs. prior period
3. Red/yellow flags with context
4. Covenant compliance status (if applicable)
5. Questions for management

복수 기간이 있으면: revenue/EBITDA/cash 추세, accelerating/decelerating/stable, underwriting case 대비.

노트: budget/plan이 없으면 요청. 섹터 KPI를 가정하지 말고 질문. covenant 수준을 모르면 credit agreement terms를 요청. `"board-ready — concise, factual, no fluff"`.

---

## 가치창출 계획 (`value-creation-plan` / `/value-creation`)

IC와의 연결: IC Step 1이 `"Value creation plan / 100-day plan"`을 수집하고, IC 섹션 V가 `"Value creation levers (organic growth, margin expansion, M&A, multiple expansion)"`와 `"100-day priorities"`를 포함한다.

### Step 1 Baseline

Current revenue, EBITDA, margins; org structure/capabilities; operational metrics by function; management strengths/gaps; `"Quick wins already identified during diligence"`.

### Step 2 레버 3군

**Revenue Growth Levers**
- Organic growth: Price increases, volume growth, market expansion
- Cross-sell / upsell
- New market entry: Geographic expansion, new verticals, new channels
- Sales force effectiveness: Hire reps, improve conversion, shorten cycle
- M&A / add-ons

각 레버 필드: Current state → Target state; Revenue impact ($); Timeline; Investment required; Confidence (high/medium/low).

**Margin Expansion Levers**
- Pricing optimization: Price increases, mix shift, bundling
- COGS reduction: Procurement savings, supplier consolidation, automation
- OpEx optimization: Overhead reduction, shared services, offshoring
- Technology investment: Automation, systems integration, data analytics
- Scale leverage

**Strategic / Multiple Expansion**
- Platform building: Add-on acquisitions, tuck-ins
- Recurring revenue shift
- Market positioning: Category leadership, brand building
- Management upgrades
- ESG / governance: Board formation, reporting improvements

### Step 3 EBITDA Bridge 표

열: Year 1–5  
행: Base EBITDA; Organic revenue growth; Pricing; Add-on M&A; COGS savings; OpEx optimization; Technology investment; **Pro Forma EBITDA**; **Margin**

### Step 4 100-Day Plan (원문 구간)

**Days 1-30: Stabilize & Assess**
- Management alignment and retention (sign employment agreements, set comp)
- Quick wins — pricing, obvious cost cuts, low-hanging fruit
- Detailed operational assessment by function
- Customer communication plan
- Set up reporting and KPI dashboards

**Days 31-60: Plan & Initiate**
- Finalize strategic plan and communicate to organization
- Launch top 3-5 value creation initiatives
- Begin add-on M&A pipeline development
- Hire for critical gaps
- Implement new reporting cadence (weekly flash, monthly review, quarterly board)

**Days 61-100: Execute & Measure**
- First results from quick-win initiatives
- First board meeting with operating metrics
- Progress report on each value creation lever
- Adjust plan based on early learnings

### Step 5 KPI 대시보드 (원문 행)

| KPI | Owner | Reporting Frequency |
|-----|-------|---------------------|
| Revenue | CEO | Monthly |
| EBITDA | CFO | Monthly |
| EBITDA margin | CFO | Monthly |
| New customer wins | CRO | Weekly |
| Net retention | CRO | Monthly |
| Employee turnover | CHRO | Monthly |
| Cash conversion | CFO | Monthly |

Current / Year 1 Target 칸은 비어 있다.

### Step 6 산출

Word 또는 PowerPoint: Executive summary (1 page); EBITDA bridge chart; Value creation levers detail (1 page per lever); 100-day plan timeline; KPI dashboard; Accountability matrix. 별도 Excel model backing the EBITDA bridge.

노트: `"most PE value creation takes 12-24 months to show in financials"`; cost cuts에 과도하게 기울이지 말 것; `"co-develop the plan, don't impose it"`; initiative-level P&L; `"Add-on M&A is often the largest value creation lever — start the pipeline on Day 1"`; operating partners/industry experts로 가정 검증.

---

## AI 준비도 (`ai-readiness` / `/ai-readiness`)

포트폴리오 횡단 스캔. 단일 회사이면 스캔은 하되 `"skip the cross-portfolio ranking"`.

### Step 1 데이터 연결 (원문 3옵션)

- MCP servers — data room, SharePoint, Google Drive, or a portfolio-ops database if connected
- Local files — quarterly decks, financials, board packs
- File uploads — PDFs, PowerPoint, or Excel

회사별 추출: sector, revenue, headcount by function, tech stack mentioned, AI/automation initiatives already in flight.

추가로 물을 것: hold period remaining (`"AI payback matters less 12 months from exit"`); 이미 성공 배포가 있는지.

### Step 2 회사별 게이트 3문항 (전부 yes → Go, 하나라도 no → Wait)

1. **Is the data there?** clean input without a 6-month data project
2. **Is there an owner?** management team driver, not a sponsor who will "support"
3. **Can we pilot in 30 days?** one team, one workflow, off-the-shelf. `"first we'd need to..."`이면 quick win이 아님

레버리지 패턴 3군:

**Back Office (usually fastest to pilot)**
- Invoice processing, AP/AR matching, expense categorization
- Contract abstraction — vendor agreements, leases, customer MSAs
- Month-end close: reconciliations, flux commentary, lender reporting first drafts

**Revenue / Front Office**
- RFP and proposal first drafts — project-based revenue일 때
- Sales call summaries and CRM hygiene
- Customer support ticket triage and first-response drafting
- Quoting for configured / complex products

**Operations (sector-dependent)**
- SOP and quality documentation generation
- Scheduling and dispatch (field services, logistics)
- Code generation and review (software portcos)

각 포인트 한 줄: what it replaces, FTE-hours/week saved (**assume 30-50%, not 100%**), buy-off-the-shelf vs light build.

### Step 3 포트폴리오 랭킹 기준

1. Dollar impact — annualized EBITDA (cost out + revenue lift, net of tool cost)
2. Speed to value — months to first measurable result
3. Probability — discount for data quality, change management, management capability

Tiebreaker: favor opportunities with **<18 months** of hold period remaining.

출력 표 열: Rank | Company | Opportunity | Est. EBITDA ($) | Months to Value | Gate | First Step. Gate 예시: `"Go"` / `"Wait — [blocker]"`.

### Step 4 Replays

- Same sector, same function
- Same tool, different company (`>$Xm in AP volume` — X 값은 미기재)
- Shared vendor leverage

Lead company + follower companies.

### Step 5 운영파트너용 1페이지

1. Top 5 across the portfolio — ranked table, owner and 30-day first step
2. Replays — 2-3 playbooks
3. Go / Wait by company
4. What we're NOT doing — gate 탈락 기회
5. Aggregate EBITDA contribution — Year 1 quick wins vs. Years 2-3 scale

노트 핵심 문장:
- `"Rank by dollars, not excitement."` 예시: `"A boring AP automation that saves $400k at a $40m revenue company beats a flashy customer-facing chatbot"`
- `"The binding constraint is almost always data, not models."`
- Off-the-shelf first
- `"Ownership is the real gate."` owner 없으면 금액과 무관하게 Wait
- Hold 3년 남은 회사는 foundational data project 가능. **12 months out**이면 `"LTM EBITDA for the CIM"`에 잡히거나 skip
- Failed pilots are signal

---

## 스킬 간 연결 (원문이 명시한 것만)

플러그인에 오케스트레이션 스크립트는 없다. 아래는 각 SKILL.md가 다른 산출물을 입력으로 지목한 경우만 적는다.

```
deal-sourcing → (inbound CIM/teaser) → deal-screening
deal-screening → "IC quick screen" (1-page)
dd-checklist + dd-meeting-prep → DD findings
unit-economics → revenue quality / further diligence
returns-analysis → "IC returns exhibits" / "IC deck" 1-pager
value-creation-plan → IC Step 1 "Value creation plan / 100-day plan"
                     → IC §V 100-day priorities
위 산출물들 + historical financials → ic-memo
close 이후 → portfolio-monitoring, value-creation-plan, ai-readiness
```

ic-memo Step 1이 세션 선행 분석을 직접 참조한다. deal-screening은 확인된 기준을 memory에 저장한다. value-creation-plan Step 1은 diligence에서 이미 식별된 quick wins를 가져온다. returns-analysis와 ic-memo §VII는 모두 base/upside(bull)/downside(bear)와 IRR/MOIC/sensitivity를 다룬다. 용어는 약간 다르다 (IC: `"base, upside, and downside"` / returns: `"Bull | Base | Bear"`).

---

## 원문에 없는 것 (발명하지 않음)

다음 항목은 10개 스킬·10개 커맨드·매니페스트 어디에도 없다.

- 펀드 기본 투자 기준의 숫자 밴드 (매출/EBITDA 레인지, 최대 밸류에이션 배수, 고객 집중도 한도)
- 목표 IRR/MOIC 허들, 표준 레버리지, 표준 홀드 기간
- IC 메모 템플릿 파일, 폰트/여백, 첨부 리스트
- LBO 모델 스킬 (financial-analysis 버티컬의 `lbo-model`은 이 플러그인 밖)
- 데이터룸 커넥터 구현 (ai-readiness가 MCP/로컬/업로드를 옵션으로 제시할 뿐, `.mcp.json`은 빈 객체)
- hooks 동작 (`hooks.json`은 빈 객체)
- 스킬 `references/` 또는 스크립트
- 커맨드 체이닝/파이프라인 자동화
- 한국어 템플릿 (전 스킬 본문은 영어)

---

## 가드레일 요약 (Important Notes에서 추출)

| 스킬 | 강제 규칙 |
|------|-----------|
| ic-memo | 가정으로 딜 조건/수익을 채우지 말고 입력을 요청. 표는 tie되어야 함. 리스크를 축소하지 말 것 |
| deal-screening | 분 단위. 레드플래그를 숨기지 말 것. 첫 스크리닝이면 기준을 먼저 질문 |
| deal-sourcing | 숏리스트 리뷰 전 이메일 초안 대량 작성 금지. 승인 없이 발송 금지 |
| dd-checklist | P0가 LOI/close 게이트. living document |
| dd-meeting-prep | 유도신문 금지. 질문 15–20 상한. 마지막 질문 고정 |
| unit-economics | 집계 지표만으로 끝내지 말고 customer-level 요청. NDR과 gross retention 병기 |
| returns-analysis | fees/carry 전후, rollover/co-invest, recap, 2–4% transaction costs, 세금 구조 |
| portfolio-monitoring | 예산·코버넌트 모르면 질문. 섹터 KPI 추정 금지 |
| value-creation-plan | 12–24개월 현실성. 성장 희생하는 과도한 비용 절감 금지. Day 1부터 add-on 파이프라인 |
| ai-readiness | 달러 임팩트로 순위. 데이터·오너십 게이트. off-the-shelf 우선. 홀드 잔여가 긴급도를 결정 |
