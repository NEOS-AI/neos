# 05. Vertical Plugins — `investment-banking` & `equity-research`

분석 범위: `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/investment-banking/` 및 `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/equity-research/` 의 **모든 파일**. 본 문서는 원문을 인용·요약하며, 존재하지 않는 워크플로·템플릿·MCP 서버를 발명하지 않는다.

---

## 1. 파일 인벤토리 (실재 파일만)

### 1.1 `investment-banking` (32 files)

| 경로 | 역할 |
|------|------|
| `.claude-plugin/plugin.json` | 플러그인 메타 |
| `.mcp.json` | MCP 서버 맵 (빈 객체) |
| `hooks/hooks.json` | 훅 맵 (빈 객체) |
| `.gitignore` | `.claude/*.local.md` 무시 |
| `.claude/investment-banking.local.md.example` | 로컬 뱅커 설정 템플릿 |
| `README.md` | 설치·커맨드·스킬 개요 |
| `commands/{one-pager,cim,teaser,buyer-list,merger-model,process-letter,deal-tracker}.md` | 슬래시 커맨드 7개 |
| `skills/{strip-profile,pitch-deck,datapack-builder,cim-builder,teaser,buyer-list,merger-model,process-letter,deal-tracker}/SKILL.md` | 스킬 9개 |
| `skills/pitch-deck/reference/{formatting-standards,slide-templates,xml-reference,calculation-standards}.md` | pitch-deck 참조 4개 |

**없는 것:** `examples/Nike_Strip_Profile_Example.pptx` (strip-profile이 참조하지만 디렉터리에 없음). `pitch-deck`·`datapack-builder`에 대응하는 슬래시 커맨드 없음.

### 1.2 `equity-research` (30 files)

| 경로 | 역할 |
|------|------|
| `.claude-plugin/plugin.json` | 플러그인 메타 |
| `hooks/hooks.json` | 훅 맵 (빈 객체) |
| `commands/{earnings,earnings-preview,initiate,model-update,morning-note,sector,thesis,catalysts,screen}.md` | 슬래시 커맨드 9개 |
| `skills/{earnings-analysis,earnings-preview,initiating-coverage,model-update,morning-note,sector-overview,thesis-tracker,catalyst-calendar,idea-generation}/SKILL.md` | 스킬 9개 |
| `skills/earnings-analysis/references/{workflow,report-structure,best-practices}.md` | earnings 참조 3개 |
| `skills/initiating-coverage/references/{task1-company-research,task2-financial-modeling,task3-valuation,task4-chart-generation,task5-report-assembly,valuation-methodologies}.md` | initiation 참조 6개 |
| `skills/initiating-coverage/assets/{report-template,quality-checklist}.md` | initiation 에셋 2개 |

**없는 것:** `README.md`, `.mcp.json`, `.gitignore`, `.claude/` extras. ER 플러그인은 MCP 설정을 전혀 싣지 않는다.

---

## 2. `plugin.json` / `hooks.json` / `.mcp.json` 전문

### 2.1 `investment-banking/.claude-plugin/plugin.json`

```json
{
  "name": "investment-banking",
  "version": "0.2.1",
  "description": "Investment banking productivity tools: client and market insights, deck creation, financial analysis, and transaction management",
  "author": {
    "name": "Anthropic"
  }
}
```

### 2.2 `equity-research/.claude-plugin/plugin.json`

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

### 2.3 `investment-banking/.mcp.json` (전문)

```json
{
  "mcpServers": {}
}
```

### 2.4 `investment-banking/hooks/hooks.json` 및 `equity-research/hooks/hooks.json` (둘 다 동일, 전문)

```json
{
  "hooks": {}
}
```

ER에는 `.mcp.json`이 **없다**. IB `.mcp.json`은 빈 `mcpServers`만 있다. 어느 플러그인도 MCP 서버를 선언하지 않는다.

### 2.5 IB `.gitignore` (전문)

```
# User-specific settings
.claude/*.local.md
```

---

## 3. `investment-banking` 플러그인 개요

### 3.1 README (실제 내용)

README 제목: `# Investment Banking Plugin`. 첫 문장이 equity research를 섞어 쓴다:

> Investment banking productivity tools for equity research, valuation, presentations, and deal materials.

설치:

```bash
claude --plugin-dir /path/to/investment-banking
```

또는 프로젝트 `.claude-plugin/`에 복사.

커맨드 표 (README 원문):

| Command | Description |
|---------|-------------|
| `/one-pager [company]` | One-page strip profile for pitch books |
| `/cim [company]` | Draft Confidential Information Memorandum |
| `/teaser [company]` | Anonymous one-page company teaser |
| `/buyer-list [company]` | Strategic and financial buyer universe |
| `/merger-model [deal]` | Accretion/dilution M&A analysis |
| `/process-letter [deal]` | Bid instructions and process correspondence |
| `/deal-tracker` | Track live deals, milestones, and action items |

스킬은 Deal Materials (`cim-builder`, `teaser`, `process-letter`, `buyer-list`, `datapack-builder`), Presentations (`strip-profile`, `pitch-deck`), Transaction Support (`merger-model`, `deal-tracker`)로 분류된다. `datapack-builder`와 `pitch-deck`은 README 스킬 표에만 있고 커맨드 표에는 없다.

예시 워크플로 3개: `/one-pager Target` → 4-quadrant PPT; `/cim Target` → CIM; `/merger-model Acquirer acquiring Target` → accretion/dilution.

### 3.2 `.claude/investment-banking.local.md.example`

YAML frontmatter + 노트 섹션. 사용자에게 `.claude/investment-banking.local.md`로 복사하라고 지시. 필드:

- 신원: `name`, `title` (예: `"Vice President"`), `group` (`"Technology M&A"`), `firm`, `email_signature`
- 커버리지: `sectors` (Enterprise Software, Fintech, Cybersecurity), `verticals` (B2B SaaS, Infrastructure, AI/ML)
- 딜 파라미터: `typical_deal_size_range: "$50M - $500M"`, `transaction_types` (M&A Sell-side/Buy-side, Capital Raise, Strategic Advisory)
- `active_mandates` 예시: Project Alpine (Sell-side, Marketing, management presentations), Project Summit (Buy-side, Due Diligence, revised LOI)
- `priority_targets`: Target Corp, Growth Co
- `default_valuation_methodologies`: Comparable Companies, Precedent Transactions, DCF
- `comps_multiples`: EV/Revenue, EV/EBITDA, EV/ARR

본문 노트: Market Themes, Key Relationships, Recent Precedent Transactions 표 (`Target | Acquirer | Value | Multiple | Date`). 스킬/커맨드가 이 파일을 **명시적으로 load하라고 지시하지는 않는다**. deal-tracker README 설명과 설정 예시의 `active_mandates`가 의도적으로 연결되는지는 코드상 명시되지 않음.

---

## 4. IB 커맨드 (`commands/`)

7개 모두 YAML frontmatter + 짧은 본문. `/one-pager`만 자체 워크플로를 풀로 적고, 나머지는 대응 스킬을 load한다.

### 4.1 `/one-pager` — `commands/one-pager.md`

Frontmatter:

```
description: Create a one-page company strip profile using branded PPT template
argument-hint: "[company name or ticker]"
```

자체 5-step 워크플로:

1. 회사명/티커 없으면 `"What company would you like to profile?"`
2. `ls skills/ | grep -E "ppt-template|brand-guidelines"`로 브랜드 템플릿 스킬 탐색. 있으면 목록 제시 후 `skill: "[template-name]"`. 없으면 사용자에게 PPT 경로 요청, 없으면 “clean professional format”.
3. `skill: "strip-profile"` 로드. 요구사항 확인(single-slide), 회사 리서치, 4:3 / 4-quadrant 레이아웃.
4. 슬라이드를 이미지로 변환해 overlap/cutoff 검사.
5. 산출: PowerPoint (.pptx), image preview, key data summary.

레이아웃 ASCII (원문 발췌):

```
│ Company Name (TICKER)                                    [Logo] │
├────────────────────────────┬────────────────────────────────────┤
│ COMPANY OVERVIEW           │ BUSINESS & POSITIONING             │
│ KEY FINANCIALS             │ STOCK PERFORMANCE / OWNERSHIP      │
Source: Company filings, FactSet
```

품질 체크리스트: 4 quadrants 실데이터, placeholder 없음, brand colors, accent bars, financial table, sources, no overflow, “Investment banking quality (GS/MS/JPM standard)”.

**이름 불일치:** 커맨드는 `skill: "strip-profile"`을 지시하지만 스킬 frontmatter `name`은 `fsi-strip-profile`.

### 4.2 `/cim` — `commands/cim.md`

```
description: Draft a Confidential Information Memorandum
argument-hint: "[company name]"
```

본문 전문: `cim-builder` 스킬 로드. 회사명 없으면 target과 source materials를 묻는다.

### 4.3 `/teaser` — `commands/teaser.md`

```
description: Draft an anonymous one-page teaser
argument-hint: "[company name]"
```

`teaser` 스킬 로드. 회사명 없으면 anonymize할 상세를 묻는다.

### 4.4 `/buyer-list` — `commands/buyer-list.md`

```
description: Build a buyer universe for a sell-side process
argument-hint: "[company or sector]"
```

`buyer-list` 스킬 로드. 회사/섹터 없으면 target details를 묻는다.

### 4.5 `/merger-model` — `commands/merger-model.md`

```
description: Build an accretion/dilution merger model
argument-hint: "[acquirer] acquiring [target]"
```

`merger-model` 스킬 로드. acquirer/target 없으면 deal details를 묻는다.

### 4.6 `/process-letter` — `commands/process-letter.md`

```
description: Draft a process letter or bid instructions
argument-hint: "[IOI or final bid]"
```

`process-letter` 스킬 로드. 유형(IOI, final bid, management meeting invite)이 없으면 process stage를 묻는다.

### 4.7 `/deal-tracker` — `commands/deal-tracker.md`

```
description: Track and review live deal pipeline
argument-hint: ""
```

`deal-tracker` 스킬 로드. 인자 없음.

---

## 5. IB 스킬 (`skills/`)

각 스킬 frontmatter `description`이 trigger 문구를 포함한다.

### 5.1 `strip-profile` (`name: fsi-strip-profile`)

**Trigger / 사용:** “professional investment banking strip profiles (company profiles) for pitch books, deal materials, and client presentations. Generates 1-4 information-dense slides with quadrant layouts, charts, and tables.” 커맨드 `/one-pager`가 이를 호출.

**데이터 기대:**

- Primary: Company filings (BamSEC, SEC EDGAR — “Item 1. Business”, MD&A), investor presentations, corporate website
- Market data: Bloomberg, FactSet, CapIQ (price, shares, market cap, net debt, EV, ownership)
- Estimates: FactSet/CapIQ consensus NTM revenue, EBITDA, EPS
- News: last 90 days press, M&A, guidance changes
- Required metrics: Revenue/EBITDA/margins/EPS/FCF ±3 years; Market Cap, EV, EV/Revenue, EV/EBITDA, P/E; YoY growth; Top 5 shareholders; product/geo mix
- 통화·스케일 정규화 ($mm 또는 $bn, mixed 금지)

**워크플로:**

1. Clarify: single-slide vs 3–4 slides, focus areas. **사용자 확인 후에만** 리서치.
2. Research & Planning: 실제 숫자로 4–5 bullet outline + 폰트/hex/차트 타입을 채팅에 출력 후 “Does this outline and visual strategy align with your vision?”
3. Slide-by-slide: **한 슬라이드씩** PptxGenJS. 매 슬라이드 후:

```bash
soffice --headless --convert-to pdf presentation.pptx
pdftoppm -jpeg -r 150 -f 1 -l 1 presentation.pdf slide
```

overlap/cutoff 발견 시 폰트 1–2pt 축소 → 텍스트 단축 → 위치 조정. **다음 슬라이드 전에 사용자 승인 대기.**

**산출 아티팩트:** `.pptx` (LAYOUT_4x3, 10" × 7.5"). 참조 예시: `examples/Nike_Strip_Profile_Example.pptx` — **플러그인 트리에 파일이 없음**. “Reference the **PPTX skill** for PowerPoint file creation.”

**템플릿 조각 (좌표):**

```
Title y=0.2  Company Name (Ticker)
Q1 x=0.3 y=0.6 w=4.7 h=3.0  Company Overview
Q2 x=5.0 y=0.6 w=4.7 h=3.0  Business & Positioning
Q3 x=0.3 y=3.7 w=4.7 h=3.5  Key Financials (table OR chart, not both)
Q4 x=5.0 y=3.7 w=4.7 h=3.5  public: 1Y chart + shareholders; private: news/ownership
```

폰트: title 24pt, quadrant headers 14pt, body 11pt, table 10pt (dense 9pt), chart labels 9pt, footer 8pt. Accent bar `w: 0.08, h: 0.25`. 단일 textbox + PptxGenJS bullets. 정보밀도: Overview 6–8 bullets, Business 6–8, Financials 8–10 rows OR chart+4–5 metrics, Q4 5–7 bullets.

후속 페이지: 2-column / full-slide charts / sidebar. 제안 흐름: Products/Market → Financial Analysis → Leadership.

차트 매핑: revenue trends line/column; geo horizontal bar; product mix pie; financial comparison column; 1Y stock line. 단일 슬라이드는 테이블 우선.

**컴플라이언스:** 명시적 “not a recommendation” 문구 없음. 품질 기준은 “GS/MS/JPM standard”, sources cited.

### 5.2 `pitch-deck`

**Trigger:** 사용자가 PPT 템플릿을 채워 달라고 할 때. **“Not for creating presentations from scratch.”** 커맨드 없음.

**참조 (task start 시 전부 읽기):**

| File | Purpose |
|------|---------|
| `reference/formatting-standards.md` | Text, bullets, tables, charts, alignment |
| `reference/slide-templates.md` | Content mapping for common slide types |
| `reference/xml-reference.md` | PowerPoint XML patterns |
| `reference/calculation-standards.md` | CAGR, consensus 검증 공식 |

**의사결정 트리:** populate empty template / edit populated slides / fix formatting.

**Critical rendering limitation (원문):** LibreOffice는 PPT를 정확히 렌더하지 않음. 납품 시 필수 문구:

> "This file was validated using LibreOffice. Please review in Microsoft PowerPoint before distribution, as rendering differences may exist."

**5-phase 워크플로:**

1. Extract/validate source data. 원본을 `[filename]_backup.pptx`로 백업.
2. Map content to template (`slide-templates.md`). instruction box vs layout placeholder 구분.
3. Populate: instruction box **삭제** 후 production formatting. 실제 table objects. 로고 없으면 `"[LOGO NOT PROVIDED - please supply company logo]"`.
4. Validate loop (`soffice` → `pdftoppm`). 3 사이클 후 escalate.
5. Final Quality Checklist.

**Anti-patterns:** (1) 컬러 instruction box에 데이터 dump, (2) pipe/tab “tables”, (3) placeholder contrast 상속.

**슬라이드 타입 데이터 요구 (`slide-templates.md`):** Market Definition, Market Sizing/TAM, Competitive Landscape, Financial Summary, Transaction Comparables. mismatch 시 **“Do not: Fabricate data or make unsupported estimates.”**

**계산 (`calculation-standards.md`):** `Future Value = Present Value × (1 + CAGR)^n`; EV/Revenue, EV/EBITDA; market share; YoY; CAGR from endpoints. Consensus: size = min-max; CAGR = exclude outliers then central cluster; projection = consensus CAGR × midpoint. mismatch >5%는 footnote.

**XML (`xml-reference.md`):** python-pptx를 기본으로 쓰고, XML은 기존 요소 속성만. 테이블 신규 생성에 XML 금지. EMU: 1 inch = 914400. 16:9 슬라이드 12192000 × 6858000 EMU.

**산출:** populated `.pptx`. 커맨드 없음 — 스킬 직접 호출.

### 5.3 `datapack-builder`

**Trigger:** CIM, OM, SEC filings, web search, **or MCP servers**에서 IC-ready Excel. “Do not use for simple financial calculations or already-completed data packs.” 커맨드 없음.

**의존:** “Use the xlsx skill for all Excel file creation.”

**데이터 기대:** uploaded documents, web search for public filings, **or MCP server data**. 인용 형식: “page numbers for documents, URLs for web sources, server references for MCP data”. `.mcp.json`은 비어 있으므로 **플러그인이 MCP 서버를 제공하지는 않음** — 스킬 텍스트만 MCP를 허용한다.

**필수 규칙 6개:** (1) money → currency `$` `$(123.0)`; (2) operational counts → number no `$`; (3) rates → `0.0%`; (4) years as text (`2024E` not `2,024`); (5) mixed context는 metric별 포맷; (6) 계산은 전부 수식, hardcoded 금지.

폰트 색 (xlsx skill 필수): Blue RGB(0,0,255) inputs; Black formulas; Green cross-sheet links. Fill은 optional.

**표준 8탭 (명시적으로 달리 지시되지 않으면):** 1 Executive Summary, 2 Historical Financials (IS), 3 Balance Sheet, 4 Cash Flow, 5 Operating Metrics, 6 Property/Segment Performance, 7 Market Analysis, 8 Investment Highlights.

**6-phase 워크플로:** Document processing → Normalization (Adjusted EBITDA recon, one-time schedule) → Build workbook (xlsx skill, row-ref tracking) → Scenario (Management / Base risk-adjusted / optional Downside for LBO) → QC → Delivery `CompanyName_DataPack_YYYY-MM-DD.xlsx`.

산업 적응: Tech/SaaS (ARR, CAC, LTV, churn, NRR, Rule of 40, Magic number); Manufacturing; Real Estate/Hospitality (ADR, RevPAR, NOI, cap rates); Healthcare/Services.

**컴플라이언스:** “Zero Tolerance for Errors”; conservative Base Case는 IC용, Management Case는 공격적 add-back. 조작된 데이터 금지 문구는 pitch-deck에만 명시.

### 5.4 `cim-builder`

**Trigger:** `"CIM"`, `"confidential information memorandum"`, `"offering memorandum"`, `"info memo"`, `"draft CIM"`, `"sell-side materials"`.

**데이터 기대 (사용자에게 요청):** management presentations, 3–5yr historicals, budget/forecast, website/marketing, customer data (anonymized if needed), org chart, prior decks, QoE if available.

**TOC (원문 구조):**

- I. Executive Summary (2–3p): overview, 5–7 investment highlights, financial headline, transaction overview
- II. Company Overview (3–5p)
- III. Industry Overview (3–5p): TAM/SAM/SOM
- IV. Growth Opportunities (2–3p)
- V. Customers & Sales (3–5p): anonymize top customers pre-LOI
- VI. Operations (2–3p)
- VII. Financial Overview (5–8p): 3–5yr IS, segment revenue, EBITDA bridge, BS, CF, capex, WC, mgmt forecast
- VIII. Appendix: detailed financials, anonymized customer list, product catalog, mgmt bios

길이 40–60 pages. Tone: “Professional, factual, compelling but not hyperbolic.” “Strong growth” → “Revenue grew at a 15% CAGR from 2021-2024”.

**산출:** Word `.docx` + separate Excel appendix + embedded charts.

**컴플라이언스:**

> Include a disclaimer page. Anonymize sensitive customer data unless seller approves.
> The CIM is a sales document — lead with strengths, but don't hide material issues (buyers will find them in diligence)
> Work with legal on the confidentiality disclaimer and any regulatory disclosures
> Get management to review for factual accuracy before distribution
> The CIM sets expectations on valuation — make sure the narrative supports the asking price

Investment highlights는 “growth potential, margin profile, and defensibility”를 다뤄야 함. 정규화/pro forma는 명확히 라벨.

### 5.5 `teaser`

**Trigger:** `"teaser"`, `"blind teaser"`, `"anonymous profile"`, `"one-pager for process"`, `"draft teaser for sell-side"`.

**구조 (1 page):** Header (deal code name, sector descriptor, `"Confidential — For Discussion Purposes Only"`); 2–3 sentence anonymized description; 4–6 investment highlights; financial summary table (Revenue, CAGR, EBITDA, margin, employees); transaction overview + contact.

**Anonymization check:** no name/brands/products; region not city; no named customers; distinctive headcount 주의; small sector면 revenue ranges; no logos.

**산출:** `.docx` one page, PDF, optional PPT single slide.

**컴플라이언스:** “Always have the client and legal review before distribution.” “Track who receives the teaser.” “aspirational but accurate”.

### 5.6 `buyer-list`

**Trigger:** `"buyer list"`, `"buyer universe"`, `"potential acquirers"`, `"who would buy this"`, `"strategic buyers"`, `"financial sponsors"`.

**전략 바이어 카테고리:** Direct Competitors, Adjacent Players, Vertical Integrators, Platform Builders. 표 컬럼: Buyer, Sector, Revenue, Strategic Fit (H/M/L), Financial Capacity, M&A Track Record, Likelihood, Priority A/B/C.

**금융 스폰서:** Platform Investors, Add-on Buyers (specific portco), Growth Equity. 표: Sponsor, Fund Size, Sector Focus, Portfolio Overlap, Recent Activity, Priority.

**Tiering:** Tier 1 = 5–10, Tier 2 = 10–15, Tier 3 = 10–20. “focused list of 30–40” vs 200 names.

**산출:** Excel (strategic tab, sponsors tab, Tier 1 contact mapping, summary stats) + one-page buyer universe summary for engagement letter/pitch.

**컴플라이언스:** “Check for antitrust concerns with direct competitors — flag any that might face regulatory issues.” Seller include/exclude 요청. Fund vintage/deployment pace.

### 5.7 `merger-model`

**Trigger:** `"merger model"`, `"accretion dilution"`, `"M&A model"`, `"pro forma EPS"`, `"merger consequences"`, `"deal impact analysis"`.

**입력:** Acquirer (price, shares, LTM/NTM EPS GAAP+adjusted, P/E, pre-tax cost of debt, tax rate, cash, debt); Target (price/shares if public, LTM/NTM EPS or NI, EV/equity value); Deal terms (offer/premium, cash vs stock mix, new debt, synergies phase-in, fees, close date).

**스텝:** Purchase price table → Sources & Uses → Pro Forma EPS Y1–Y3 (acquirer NI + target NI + AT synergies − AT foregone interest − AT new debt interest − AT intangible amort) → Sensitivity (synergies × premium; cash/stock mix) → Breakeven synergies for Y1 EPS-neutral.

**산출:** Excel (Assumptions, S&U, PF IS, A/D summary, sensitivities, breakeven) + one-page merger consequences for pitch book.

**노트:** GAAP vs adjusted (cash) EPS 둘 다; stock deals는 current price로 exchange ratio; PPA/goodwill/intangible amort; Y1 synergies often 25–50% of run-rate; tax rate = acquirer marginal.

### 5.8 `process-letter`

**Trigger:** `"process letter"`, `"bid instructions"`, `"IOI letter"`, `"bid procedures"`, `"final round letter"`, `"management meeting invite"`.

**4 유형:** Initial process letter; IOI instructions; Second round / final bid; Management meeting invitation.

**IOI 요구:** EV range, consideration form (cash/stock/earnout/rollover), financing sources/certainty, DD requirements, timeline to close, conditions, buyer description/rationale.

**Final bid 추가:** SPA/APA markup, committed financing letters, remaining diligence, exclusivity, antitrust filings, key personnel terms, binding vs non-binding, evaluation criteria.

**Mgmt meeting:** logistics, attendees, agenda, no recording, materials, follow-up Q process.

**산출:** `.docx` professional letter, firm letterhead placeholder, track-changes for client review.

**컴플라이언스:** “Coordinate with legal on any representations or commitments.” “Client should review and approve before sending.” Deadlines typically 2–3 weeks IOI, 3–4 weeks final. “Keep a log of who received each letter.”

### 5.9 `deal-tracker`

**Trigger:** `"deal tracker"`, `"deal status"`, `"where are we on"`, `"process update"`, `"deal pipeline"`, `"weekly deal review"`.

**Deal setup 필드:** code name Project [Name], client, type (Sell-side/buy-side/financing/restructuring), role (Lead/co-advisor/fairness opinion), expected EV, stage (`Pre-mandate → Engaged → Marketing → IOI → Diligence → Final bids → Signing → Close`), team (MD/VP/Associate/Analyst), key dates.

**마일스톤 표:** EL signed, CIM/teaser drafted, buyer list approved, teaser distributed, NDA, CIM distributed, IOI deadline, IOIs reviewed, shortlist, mgmt meetings, data room, final bid, bids reviewed, exclusivity, confirmatory DD, SPA signed, regulatory, Close. Status: On Track / At Risk / Delayed / Complete.

**Action items:** Action, Deal, Owner, Due Date, P0/P1/P2, Open/Done/Blocked.

**Weekly review:** per-deal one-liner, developments, next 2 weeks, blockers, next-week actions; pipeline by stage, at-risk, new mandates, expected closings.

**산출:** Excel (pipeline overview, per-deal milestone tabs, action master, weekly summary) + optional Markdown for email/Slack.

---

## 6. `equity-research` 플러그인 개요

README 없음. `plugin.json` description만 존재: “earnings analysis, initiating coverage reports, and research workflows”. Author `Anthropic FSI`, version `0.1.2`. MCP/hooks 비어 있음(hooks만 존재).

커맨드↔스킬 1:1:

| Command | Skill loaded |
|---------|----------------|
| `/earnings` | `earnings-analysis` (커맨드가 자체 워크플로 + 스킬 로드) |
| `/earnings-preview` | `earnings-preview` |
| `/initiate` | `initiating-coverage` |
| `/model-update` | `model-update` |
| `/morning-note` | `morning-note` |
| `/sector` | `sector-overview` |
| `/thesis` | `thesis-tracker` |
| `/catalysts` | `catalyst-calendar` |
| `/screen` | `idea-generation` |

---

## 7. ER 커맨드 (`commands/`)

### 7.1 `/earnings` — `commands/earnings.md`

```
description: Analyze quarterly earnings and create an earnings update report
argument-hint: "[company name or ticker] [quarter, e.g. Q3 2024]"
```

자체 4-step + 스킬 로드:

1. Parse company + quarter; 없으면 질문.
2. **Verify Timeliness:** search `"[Company] latest earnings results [current year]"`; release last 3 months; transcript date matches. stale면 알리고 재검색.
3. `skill: "earnings-analysis"`: press release, 10-Q EDGAR, transcript, IR deck, consensus (Bloomberg/FactSet); beat/miss; 8–12 charts; 8–12 page report with rating and PT.
4. Deliver DOCX + summary (beat/miss, guidance, thesis impact positive/negative/neutral).

Page 1 ASCII는 `Rating: BUY | Price Target: $XXX`. Quality: latest quarter, quantified beat/miss, 8–12 charts, clickable hyperlinks, 8–12 pages, 3,000–5,000 words.

### 7.2 `/earnings-preview`

```
description: Build a pre-earnings preview with scenarios
argument-hint: "[company ticker]"
```

`earnings-preview` 로드. ticker 없으면 묻는다.

### 7.3 `/initiate`

```
description: Create an initiating coverage report
argument-hint: "[company ticker]"
```

`initiating-coverage` 로드, “5-task workflow”. ticker 없으면 묻는다. **커맨드는 5-task를 한 번에 시작하라고 쓰지만, 스킬은 한 번에 전체 파이프라인 실행을 금지한다.**

### 7.4 `/model-update`

```
description: Update a financial model with new data
argument-hint: "[company ticker]"
```

`model-update` 로드. ticker 없으면 모델과 변경점을 묻는다.

### 7.5 `/morning-note`

```
description: Draft a morning meeting note
argument-hint: ""
```

`morning-note` 로드. 인자 없음.

### 7.6 `/sector`

```
description: Create a sector overview report
argument-hint: "[sector or industry]"
```

`sector-overview` 로드.

### 7.7 `/thesis`

```
description: Create or update an investment thesis
argument-hint: "[company ticker]"
```

`thesis-tracker` 로드.

### 7.8 `/catalysts`

```
description: View or update the catalyst calendar
argument-hint: "[timeframe, e.g. 'next 2 weeks']"
```

`catalyst-calendar` 로드. timeframe 없으면 **default next 2 weeks**.

### 7.9 `/screen`

```
description: Run a stock screen or generate investment ideas
argument-hint: "[screen criteria, e.g. 'undervalued midcap tech']"
```

`idea-generation` 로드. criteria 없으면 long/short, sector, style, theme을 묻는다.

---

## 8. ER 스킬 — 운영 워크플로 (initiation 제외)

### 8.1 `earnings-analysis`

**Trigger:** `"earnings update"`, `"quarterly update"`, `"earnings analysis"`, `"Q1/Q2/Q3/Q4 results"`, post-earnings report.

**Do NOT use:** initiation → other skill; “flash note”/“quick take” → different format; company not already covered → need initiation first.

**스펙:** 8–12 pages, 3,000–5,000 words, 1–3 summary tables, 8–12 charts, 1–2 day turnaround (24–48h of earnings), audience already familiar, Times New Roman, filename `[Company]_Q[Quarter]_[Year]_Earnings_Update.docx`. Optional XLS.

**데이터 (필수 소스 리스트):**

- Earnings release (date + URL)
- 10-Q (filing date + EDGAR `https://www.sec.gov/cgi-bin/viewer?accession=...`)
- Earnings call transcript (date; Seeking Alpha / IR / AlphaStreet / Motley Fool)
- Investor presentation/supplementals
- Consensus Bloomberg/FactSet/Refinitiv/Yahoo **pre-earnings “as of” date**
- Prior guidance from previous quarter

**Timeliness (원문 강조):** Training data is OUTDATED. 4 steps: write today’s date → search latest → verify last 3 months → transcript date matches. >3 months면 재검색.

Fiscal calendar 예: Nike May YE, Apple September YE, Walmart January YE.

**5 phases (`references/workflow.md`):**

- Phase 1 (30–60 min): search IR/EDGAR, extract metrics table (Reported vs Our Est vs Consensus), call themes (tone, guidance, surprises).
- Phase 2 (2–3h): beat/miss WHY; segment/geo/product; margins; guidance vs prior vs Street; model update; PT if estimates change >5%; rating upgrade/downgrade/maintain.
- Phase 3 (1–2h): 8 required charts (qtr revenue, qtr EPS, margins, segment, operating metrics, beat/miss waterfall, estimate revision, valuation multiple) + optional peer/guidance/FCF/BS.
- Phase 4 (2–3h): DOCX via DOCX skill. Page map in `report-structure.md`.
- Phase 5 (30 min): checklist + delivery summary.

**Page 구조 (`report-structure.md`):**

```
PAGE 1: [COMPANY] ([TICKER]) [QUARTER] [YEAR] EARNINGS UPDATE
Rating: [MAINTAIN/RAISE/LOWER] [RATING]
EARNINGS SUMMARY: BEAT / INLINE / MISS
■ 3–4 investment-impact bullets (bold header + paragraph)
UPDATED FINANCIAL ESTIMATES old vs new
PAGES 2–3: detailed results (revenue + profitability)
PAGES 4–5: key metrics & guidance
PAGES 6–7: thesis pillars STRENGTHENED/UNCHANGED/WEAKENED
PAGES 8–10: DCF/comps PT methodology
PAGES 11–12 optional appendix
```

**Best practices 헤드라인 예:** `"Nike Q2 FY24: DTC Strength Offsets Wholesale Weakness - Maintaining OW, PT $95"`. Bad: `"Nike Quarterly Update"`.

**컴플라이언스 / 추천 언어:** 이 스킬은 **명시적으로 rating과 price target을 산출**한다 (`BUY`, `OW`, MAINTAIN/RAISE/LOWER). “not investment advice” / “research note ≠ recommendation” 문구는 **파일에 없음**. 대신: clickable hyperlinks 필수, consensus source+date, 모든 figure/table source, institutional tone, “Do NOT rely on training data”.

의존: Python matplotlib/pandas/seaborn; DOCX skill; optional XLS skill.

### 8.2 `earnings-preview`

**Trigger:** `"earnings preview"`, `"what to watch for [company] earnings"`, `"pre-earnings"`, `"earnings setup"`, `"preview Q[X] for [company]"`.

**데이터:** web search consensus (revenue, EPS, key segments); earnings date/time pre vs after-hours; prior-quarter call guidance.

**What-to-watch:** Financial (rev/EPS/margins/FCF/guidance) + sector ops: Tech/SaaS ARR/NRR/RPO/customers; Retail SSS/traffic/basket; Industrials backlog/book-to-bill/price-volume; Financials NIM/credit/loan growth/fees; Healthcare scripts/volumes/pipeline.

**시나리오 표:** Bull/Base/Bear × Revenue × EPS × Key Driver × Stock Reaction. Historical reaction search `"[company] earnings reaction history"`. Options-implied move.

**산출:** one-page preview: company/quarter/date, consensus table, ranked metrics, scenarios, 3–5 catalyst checklist, trading setup (recent performance, implied move).

**노트:** consensus source+date; whisper numbers “often more relevant than published consensus”.

### 8.3 `model-update`

**Trigger:** `"update model"`, `"plug earnings"`, `"refresh estimates"`, `"update numbers for [company]"`, `"new guidance"`, `"revise estimates"`.

**트리거 유형:** Earnings release; Guidance change; Estimate revision; Macro (rates/FX/commodities); Event-driven (M&A, restructuring, product, mgmt).

**After earnings 표:** Prior Estimate / Actual / Delta / Notes for Revenue, GM, OpEx, EBITDA, EPS, key metrics; segment mix; BS/CF (cash, debt, share count, capex, WC).

**Forward:** Old/New FY and Next FY for Revenue/EBITDA/EPS + assumption reasons.

**Valuation impact:** DCF FV, P/E NTM, EV/EBITDA NTM, Price Target.

**산출:** Updated Excel **if user provides existing model**; estimate change summary markdown/Word; updated PT derivation.

**노트:** GAAP vs adjusted; non-recurring items; revision history; Street comparison; share count (SBC, converts, buybacks).

### 8.4 `morning-note`

**Trigger:** `"morning note"`, `"morning meeting"`, `"what happened overnight"`, `"trade idea"`, `"morning call prep"`, `"daily note"`. “7am morning meeting format — tight, opinionated, actionable.”

**스캔:** overnight earnings/guidance; M&A rumors; mgmt changes; product/regulatory; competitor upgrades/downgrades; futures, sector ETF, commodities/FX, today’s data.

**템플릿 (원문):**

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

Earnings quick take 표 + “Our Take” + Action Maintain/Upgrade/Downgrade + PT.

**산출:** Markdown for email/Slack; Word if formal; **1 page max**.

**노트:** “Be opinionated”; “No news is a valid morning note”; timestamp 6am takes; “If you're wrong, own it in the next morning note”. Rating 액션을 포함 — 리서치 노트이면서 거래 아이디어/레이팅 액션을 요구.

### 8.5 `sector-overview`

**Trigger:** `"sector overview"`, `"industry report"`, `"market landscape"`, `"sector analysis"`, `"industry deep dive"`, `"thematic research"`.

**Scope 질문:** sector/subsector, purpose (client/internal/pitch/idea gen), depth 5–10 vs 20–30 pages, angle neutral vs thematic, public only vs include private.

**내용:** TAM + 5yr CAGR + forecast; structure (top-5 share, value chain, business models, barriers); 3–5 tailwinds/headwinds; top 5–10 company table (Revenue, Growth, EBITDA Margin, Share, Differentiator) + 2–3 sentence profile + P/E, EV/EBITDA, EV/Revenue; valuation context vs market; investment implications (best R/R, thematic bets, bull vs bear debates, catalysts).

**산출:** Word or PowerPoint + Excel appendix.

**노트:** source all market size; “Distinguish between TAM hype and realistic addressable market”; date-stamp; charts essential. Client이면 “so what”을 M&A target ID / competitive positioning / market entry에 맞춤.

### 8.6 `thesis-tracker`

**Trigger:** `"update thesis for [company]"`, `"is my thesis still intact"`, `"thesis check"`, `"add data point to [company]"`, `"review my positions"`.

**신규 테시스:** Company/ticker, Long or Short, 1–2 sentence core, 3–5 pillars, 3–5 invalidating risks, catalysts, target price/valuation, stop-loss trigger.

**Update log:** Date, data point, thesis impact (strengthen/weaken/neutralize pillar), Action (No change / Increase / Trim / Exit), conviction High/Med/Low.

**Scorecard 예:** `Revenue growth >20% | On track | Q3 was 22% | Stable`.

**산출:** markdown or Word for morning meeting / portfolio review / risk committee. “Store thesis data in a structured format so it can be referenced across sessions.”

**노트:** “A thesis should be falsifiable”; track disconfirming evidence; quarterly review even without drama.

### 8.7 `catalyst-calendar`

**Trigger:** `"catalyst calendar"`, `"upcoming events"`, `"what's coming up"`, `"earnings calendar"`, `"event calendar"`, `"catalyst tracker"`.

**Universe:** tickers, sector, include macro?, horizon (커맨드 default 2 weeks).

**촉매 유형:** Earnings & financial (qtr date pre/post, AGM, investor/analyst/capital markets day, debt maturity); Corporate (product, FDA, contracts, M&A milestones, mgmt transitions, lockups); Industry (conferences, trade shows, comment periods, monthly industry data); Macro (FOMC, jobs/CPI/GDP, ECB/BOJ, geopolitics).

**캘린더 컬럼:** Date | Event | Company/Sector | Type | Impact H/M/L | Our Positioning Long/Short/Neutral | Notes.

**Weekly preview:** this week ranked events with consensus vs our estimate; next week heads-up; position implications / pre-positioning / risk mgmt for binary events.

**산출:** Excel sortable calendar + weekly preview markdown email; **Optional: integration with Google Calendar**.

**노트:** verify vs IR and Bloomberg/FactSet; pre-announce history; conference attendance (who is absent); color-code Red/Yellow/Green; archive outcomes.

### 8.8 `idea-generation`

**Trigger:** `"idea generation"`, `"stock screen"`, `"find ideas"`, `"what looks interesting"`, `"screen for"`, `"new ideas"`, `"pitch me something"`.

**파라미터:** Direction Long/Short/both; market cap; sector; style Value/Growth/Quality/Special situation/Event-driven; geography; theme.

**스크린 기준 (원문 수치):**

- Value: P/E < sector median; EV/EBITDA < historical avg; FCF yield >5%; P/B <1.5x; insider buying 90d; dividend yield > market
- Growth: Rev >15% YoY; earnings >20% YoY; acceleration; expanding margins; ROIC >15%; SaaS NRR >110%
- Quality: 5+ yrs consistent growth; stable/expanding margins; ROE >15%; low D/E; high FCF conversion; insider ownership >5%
- Short: declining/decelerating rev; margin compression; rising AR/inventory vs sales; insider selling; unjustified premium; high SI + deteriorating fundamentals; auditor changes/restatements
- Special: IPO/SPAC lockups; spin-offs 12m; post-restructuring; activist; mgmt change at underperformers

**Thematic sweep:** define thesis → value chain → pure-play vs diversified → priced-in vs under-appreciated → second-order beneficiaries.

**아이디어 카드:** one-line thesis; metrics vs peers (mkt cap, EV/EBITDA NTM, P/E NTM, rev growth, EBITDA margin, FCF yield); 3–5 bullets why mispriced; key risks; next steps (full model / DD / expert call).

**산출:** 5–10 one-pagers, screening methodology, comparison table, prioritized research list.

**노트:** “Screens surface candidates, not conclusions”; crowded-trade check (ownership, SI, analyst coverage); shorts need higher conviction. **명시적 추천 면책 없음.** Long/Short 아이디어를 산출한다.

---

## 9. ER 스킬 — `initiating-coverage` (5-task)

### 9.1 Frontmatter / 운영 규칙

`name: initiating-coverage`. Default font Times New Roman. **SINGLE-TASK MODE ONLY.**

풀 파이프라인 요청 시 필수 응답: 5개 태스크를 나열하고 어느 것부터 할지 묻는다. “all tasks together”면:

> Currently, this skill supports executing one task at a time... We're working on a seamless end-to-end workflow... Would you like to start with Task 1 (Company Research)?

금지: 자동 시퀀스, 다음 태스크 가정, Task 3–5를 선행 산출물 없이 실행. 여분 문서(“completion summaries”, “executive summaries”, “quick reference guides”) 금지.

**Deliver-only 정책:**

| Task | Output only |
|------|-------------|
| 1 | `[Company]_Research_Document_[Date].md` 6–8K words |
| 2 | `[Company]_Financial_Model_[Date].xlsx` 6 tabs |
| 3 | `[Company]_Valuation_Analysis_[Date].md` + 4 tabs added to Task 2 xlsx |
| 4 | `[Company]_Charts_[Date].zip` 25–35 PNG/JPG + `chart_index.txt` |
| 5 | `[Company]_Initiation_Report_[Date].docx` 30–50p, 10–15K words |

Task 1·2 독립(병렬 가능). Task 3 ← Task 2. Task 4 ← Tasks 1+2+3 (SKILL 본문 일부는 “Tasks 2 & 3”이라고도 씀 — 불일치). Task 5 ← 1–4 전부.

참조 파일은 **해당 태스크만** 로드 (파일이 큼).

### 9.2 Task 1 Company Research (`references/task1-company-research.md`)

**데이터 소스:**

- Public: latest 10-K (Business, risk factors, MD&A, financials), recent 10-Qs, DEF 14A (comp, board), 8-Ks; IR presentations, last 2–3 transcripts, press, product docs
- Private: website/blog, press, LinkedIn bios, Crunchbase/PitchBook funding
- Secondary: competitor 10-Ks, Gartner/Forrester/IDC, trade press, LinkedIn execs

**섹션·단어수:** Overview 800–1200; History 800–1200; Management 1000–1400 (300–400 × 3–4 execs, CEO+CFO 필수); Products 700–1000; Customers & GTM 500–700; Industry 800–1200; Competitive 700–1000 (5–10 competitors); TAM 500–700; Risks 600–900 (8–12 across company 4–6 / industry 3–4 / financial 2–3 / macro 2–3, each 50–100 words). DATA SOURCES 목록 with dates and URLs.

### 9.3 Task 2 Financial Modeling (`references/task2-financial-modeling.md`)

**선행:** public → latest 10-K + recent 10-Qs EDGAR Item 8; private → statements/estimates; OR user-provided 3–5yr IS/CF/BS.

**6 essential tabs:** Revenue Model, Income Statement, Cash Flow, Balance Sheet, Scenarios, DCF Inputs.

색: Blue inputs, Black formulas, Green cross-sheet, Red errors. No circular refs. Named ranges.

Revenue Model: 20–30 product rows + 15–20 geography rows + optional channel. IS 40–50 line items, 3–5yr hist + 5yr proj. BS 35–45 items with BALANCE CHECK. DCF Inputs: EBIT → NOPAT → UFCF. Scenarios Bull/Base/Bear (CAGR, GM, EBITDA margin, CapEx%).

SaaS 특수: ARR, NRR, LTV/CAC, path to profitability. E-comm: stores/comp, inventory turns. Manufacturing: capacity, volume/price/mix.

**품질 체크리스트와의 불일치:** `assets/quality-checklist.md`는 최종 XLS에 **15+ tabs** (Executive Summary, Assumptions, Historical Financials, Revenue Model, Operating Expenses, IS, BS, CF, Supporting Schedules, DCF, Comps, Precedent Transactions, Scenarios, Sensitivity, Charts)를 요구. Task 2는 6탭, Task 3가 DCF/Sensitivity/Comps/Valuation summary(+ optional Precedent)를 **기존 파일에 추가**. 15+는 최종 합본을 가리키는 것으로 읽히지만 Task 2 산출 스펙과 숫자가 다름.

### 9.4 Task 3 Valuation (`references/task3-valuation.md` + `valuation-methodologies.md`)

Task 2 없이 시작 금지.

**DCF 실행:** 10y Treasury Rf (예 4.0–4.5% late 2024); CAPM `Rf + Beta × ERP` ERP 5–6%; after-tax cost of debt; market-value weights; WACC. Terminal: perpetuity preferred `FCF_n×(1+g)/(WACC−g)` g 2.0–3.0% not > GDP; or exit multiple. EV − net debt ± non-op − MI − pref → equity / diluted shares.

**2-way sensitivity 필수:** WACC vs g; Revenue CAGR vs terminal EBITDA margin. Heatmap green→red.

**Comps:** 5–10 peers; LTM+NTM EV/Rev, EV/EBITDA, P/E; **statistical summary max/75th/median/25th/min MANDATORY**. Sources: FactSet/CapIQ/Bloomberg preferred; else Yahoo/Seeking Alpha.

**Precedent optional:** 5–10 deals last 3–5 years, size 0.5x–2x; control premium typically 20–40%; multiples 10–20% above trading.

**가중 예:** DCF 50% / Comps 40% / Precedent 10%. Typical ranges DCF 40–60, comps 25–40, precedent 10–25.

**추천 블록 원문 필드:** Current Price, PT 12-month, Upside, Rating **BUY / OUTPERFORM**, methodology, 5 catalysts, downside/upside risks with probability and % impact.

Sanity: historical multiples; peer premium; implied growth; TV < 60–70% of EV; WACC 8–14% (tech 10–14, mature 7–10); 12m IRR vs rating.

`valuation-methodologies.md`는 UFCF 정의, NWC, maintenance vs growth capex, target vs current capital structure, P/B banks, EV/Production E&P, EV/Subscriber media 등 이론 보충.

### 9.5 Task 4 Charts (`references/task4-chart-generation.md`)

Python: `pip install matplotlib seaborn pandas numpy plotly`. DPI 300, seaborn-v0_8-darkgrid.

**4 mandatory ⭐:** chart_03 stacked area product; chart_04 stacked bar geo; chart_28 2-way DCF heatmap; chart_32 football field.

**25 required:** 01 stock 12–24m (Yahoo/Bloomberg/Alpha Vantage); 02 rev trajectory; 03⭐; 04⭐; 05–09 company 101; 10 GM; 11 EBITDA margin; 12 FCF; 13 ops dashboard; 14 scenarios; 15 TAM; 16 positioning; 17 share; 18 benchmarking; 28⭐–34 valuation.

**10 optional (19–27, 35):** CAC, unit economics, roadmap, geo map, R&D, S&M efficiency, WC, debt maturity, ownership, analyst PT distribution.

파일명 `chart_##_description.png`. Zip + `chart_index.txt`. 검증: mandatory 존재, 25–35 count, sample size >50KB.

외부 데이터: Yahoo Finance, Bloomberg for price and historical multiples.

### 9.6 Task 5 Report Assembly (`references/task5-report-assembly.md` + `assets/report-template.md` + `assets/quality-checklist.md`)

**도구:** DOCX skill, XLSX skill, Read tool. Python 라이브러리로 Word 만들지 말 것. Markdown 최종본 금지.

**길이:** 30–50 pages MIN 30; 10,000–15,000 words MIN 10,000; 25–35 charts; 12–20 tables; 60–80% page density; 1 chart / 200–300 words.

**섹션 단어수 하한:** Projection Assumptions 2,000–3,000 ⭐; Scenario Analysis 1,500–2,000 ⭐; Task 1 Company 101 verbatim 40–50% of report.

**Page 1 필수 (SKILL + quality-checklist):** `"INITIATING COVERAGE"` header (**NOT** `"Company Update"`); thesis-focused title; rating box (rating, price, target, 52w, mkt cap, EV); analyst credentials; Figure 1 stock chart; 3–4 ■ bullets with **bold header** + 3–5 sentences; financial table A/E suffixes.

**충돌:** `assets/report-template.md`는 Page 1을 **“Investment Update” / “COMPANY UPDATE”** 로 기술하고 헤더 예가 `[OUTPERFORM / NEUTRAL / etc.] RECOMMENDATION / COMPANY UPDATE`. quality-checklist와 SKILL.md는 `"INITIATING COVERAGE"`를 강제. Rating 스케일도 혼재: Task 3 `BUY/HOLD/SELL`; template `OUTPERFORM / NEUTRAL / UNDERWEIGHT`; quality-checklist `BUY/OUTPERFORM/HOLD/UNDERPERFORM/SELL`.

**폰트 충돌:** SKILL default Times New Roman; quality-checklist “Calibri, Arial, or similar”; template도 Calibri/Arial.

**필수 테이블:** Full IS 40–50 rows 5+5 years; CF 30–40; BS 35–45; product 20–30; geo 15–20; channel 10–15; comps with stats; DCF 30–40; WACC 8–10; two sensitivities.

**Appendices (`report-template.md` Required Disclosures):**

> - Analyst certification
> - Important disclosures
> - Company-specific disclosures
> - Legal entity disclosures
> - Other regulatory disclosures

**하이퍼링크:** SEC EDGAR viewer, transcripts (Seeking Alpha or IR), press IR, presentation PDFs, industry reports if public; Bloomberg/FactSet는 `"(subscription required)"`. raw URL 금지.

**품질 게이트 (quality-checklist):** 미달 시 DO NOT DELIVER — <30 pages, <25 charts, <12 tables, <10,000 words, no XLS, charts as text descriptions. Cross-file: spot-check 10–15 numbers DOCX vs XLS.

**파일 조직 제안 (SKILL.md):** Task3 폴더에 `[Company]_Valuation_Analysis.pdf`라고 적혀 있으나 Task 3 실제 산출은 `.md`. 또 다른 문서 불일치.

---

## 10. 데이터 기대: filings / transcripts / MCP

### 10.1 Filings

| 플러그인 | 명시 소스 |
|----------|-----------|
| IB `strip-profile` | BamSEC, SEC EDGAR Item 1 Business, MD&A |
| IB `datapack-builder` | SEC filings, CIMs, OMs |
| IB `cim-builder` | mgmt decks, historicals, QoE — SEC 명시 없음 (프라이빗 셀사이드 가정) |
| ER `earnings-analysis` | 10-Q/10-K EDGAR viewer URL |
| ER initiation Task 1 | 10-K, 10-Q, DEF 14A, 8-K |
| ER initiation Task 2 | Item 8 Financial Statements from latest 10-K + 10-Qs |

### 10.2 Transcripts / IR

ER earnings: IR webcast, Seeking Alpha, AlphaStreet, Motley Fool; date must match release ±1 day. Initiation Task 1: last 2–3 quarter transcripts, investor presentations, last 12 months press. IB strip-profile: investor presentations, last 90 days news.

### 10.3 Market data terminals (텍스트 언급, 플러그인 미연결)

Bloomberg, FactSet, CapIQ/Capital IQ, Refinitiv, Yahoo Finance, Alpha Vantage. Consensus “as of” pre-earnings. Subscription noted `(subscription required)`.

### 10.4 MCP

- IB `.mcp.json`: `"mcpServers": {}` — **서버 0개**.
- ER: `.mcp.json` **파일 없음**.
- IB `datapack-builder` 본문만 “MCP servers” / “MCP server data” / “server references for MCP data”를 허용. 서버 이름(Daloopa, FactSet MCP 등)은 **이 두 플러그인 안에 없음** (같은 레포 `financial-analysis` 스킬들이 Daloopa/Kensho/FactSet MCP를 말하지만 본 스코프 밖).
- ER 스킬은 MCP를 호출하지 않고 web search + EDGAR + IR + (optional) user Excel에 의존.

### 10.5 기타 툴 의존 (플러그인 밖 스킬)

IB: PPTX skill, PptxGenJS, LibreOffice `soffice`/`pdftoppm`, xlsx skill, python-pptx. ER: DOCX skill, XLSX skill, matplotlib/seaborn/pandas/numpy/plotly.

---

## 11. Safety / compliance 언어 — research notes vs recommendations

### 11.1 실제 존재하는 면책·리뷰 게이트 (IB)

| 스킬 | 언어 |
|------|------|
| `cim-builder` | disclaimer page; legal on confidentiality & regulatory disclosures; management factual review; don’t hide material issues |
| `teaser` | Confidential — For Discussion Purposes Only; client **and legal** review; outreach log |
| `process-letter` | legal on representations/commitments; client approve before send |
| `buyer-list` | antitrust flags on competitors |
| `datapack-builder` | IC-ready; conservative vs aggressive normalization; zero-tolerance accuracy |
| `pitch-deck` | LibreOffice rendering disclaimer; “Do not fabricate data”; 3-cycle escalate; logo missing flag |
| `merger-model` | GAAP vs adjusted EPS; PPA/amort |
| `strip-profile` | sources cited; GS/MS/JPM quality — **추천/비추천 구분 없음** |

IB 산출물은 딜 자료(CIM, teaser, process letter, merger model)이지 sell-side equity **rating**이 아니다. 명시적 “this is not a research report / not a recommendation” 문장은 **없음**.

### 11.2 ER — 리서치 노트가 곧 추천을 만든다

두 플러그인 어디에도 “this is not investment advice”, “for institutional clients only”, “not a solicitation” 문장은 **없다**. 반대로 ER은 rating/PT를 **필수 산출**로 박아 둔다.

| 스킬 | 추천 언어 |
|------|-----------|
| `earnings-analysis` | Page 1 `Rating: BUY`, MAINTAIN/RAISE/LOWER, price target; headline 예 `Maintaining OW, PT $95` |
| `initiating-coverage` Task 3/5 | `BUY/HOLD/SELL` 및/또는 `OUTPERFORM/NEUTRAL/UNDERWEIGHT` |
| `model-update` | Maintain or change rating; new PT |
| `morning-note` | Upgrade/Downgrade; Long/Short trade ideas |
| `idea-generation` | Long/Short idea cards |
| `thesis-tracker` | Long or Short, stop-loss, Increase/Trim/Exit |
| `earnings-preview` | Bull/Base/Bear **stock reaction** |
| `catalyst-calendar` | Our Positioning Long/Short/Neutral; pre-positioning |

존재하는 규제 흉내:

- Initiation appendix: Analyst certification, Important disclosures, Company-specific disclosures, Legal entity disclosures, Other regulatory disclosures — **템플릿 불릿만**, 문구 본문 없음.
- 모든 figure/table 출처 + clickable EDGAR/IR links.
- Consensus에 vendor + as-of date.
- “Present both positive and negative aspects objectively” (`report-template.md` note 11).
- Thesis falsifiability; disconfirming evidence (`thesis-tracker`).
- Screens ≠ conclusions (`idea-generation`).

**정리:** 이 코드베이스는 research note와 recommendation을 분리하지 않는다. initiation/earnings는 기관 sell-side 리포트 포맷(rating box + PT)을 복제한다. 컴플라이언스 가드는 출처·적시성·허위 데이터 금지·IB 쪽 legal review이지, 추천 자체를 억제하는 가드가 아니다.

---

## 12. 커맨드–스킬 매핑 및 갭

### 12.1 IB

| Command | Skill | Notes |
|---------|-------|-------|
| `/one-pager` | `strip-profile` (`name: fsi-strip-profile`) | 이름 불일치 |
| `/cim` | `cim-builder` | |
| `/teaser` | `teaser` | |
| `/buyer-list` | `buyer-list` | |
| `/merger-model` | `merger-model` | |
| `/process-letter` | `process-letter` | |
| `/deal-tracker` | `deal-tracker` | |
| *(none)* | `pitch-deck` | README 스킬만 |
| *(none)* | `datapack-builder` | README 스킬만; MCP 언급 |

### 12.2 ER

9 커맨드 = 9 스킬 1:1. `/initiate`는 5-task를 “begin”하라고 하지만 스킬은 한 태스크씩만.

---

## 13. 문서 내부 불일치 (발명 없이 관측)

1. IB README 첫 문장에 “equity research”가 들어가 IB 범위와 섞임.
2. `/one-pager` → `skill: "strip-profile"` vs YAML `name: fsi-strip-profile`.
3. `strip-profile`이 `examples/Nike_Strip_Profile_Example.pptx`를 지시하나 파일 없음.
4. `pitch-deck`/`datapack-builder` 커맨드 없음.
5. IB `.mcp.json` 빈 객체 vs `datapack-builder` MCP 소스 허용.
6. `/initiate` 전체 워크플로 vs `initiating-coverage` single-task lock.
7. Initiation Page 1: `INITIATING COVERAGE` vs template `COMPANY UPDATE`.
8. Rating taxonomy: BUY/HOLD/SELL vs OUTPERFORM/NEUTRAL/UNDERWEIGHT vs OW in earnings headlines.
9. Font: Times New Roman vs Calibri/Arial.
10. Task 2 “6 essential tabs” vs quality-checklist “15+ tabs”.
11. SKILL file tree shows Task 3 `.pdf`; actual output `.md`.
12. Task 4 의존성: “Tasks 1, 2, AND 3” vs 한 구절 “Tasks 2 & 3”.
13. `report-template.md` “Generate 20-30+ chart images” vs Task 4 “25-35”.
14. ER에 README/MCP/gitignore 없음; IB는 있음.
15. Hooks 양쪽 모두 빈 `{}` — session start, file-edit, prompt-submit 훅 없음.

---

## 14. 산출 아티팩트 총괄

### IB

| 스킬 | 산출 |
|------|------|
| strip-profile | `.pptx` 4:3 + image preview |
| pitch-deck | populated `.pptx` + LibreOffice disclaimer |
| datapack-builder | `CompanyName_DataPack_YYYY-MM-DD.xlsx` 8 tabs |
| cim-builder | `.docx` 40–60p + Excel appendix |
| teaser | 1p `.docx` + PDF + optional PPT |
| buyer-list | Excel multi-tab + 1p summary |
| merger-model | Excel + 1p merger consequences |
| process-letter | `.docx` letter + track-changes |
| deal-tracker | Excel pipeline + optional md |

### ER

| 스킬 | 산출 |
|------|------|
| earnings-analysis | `[Company]_Q[X]_[Year]_Earnings_Update.docx` 8–12p; optional XLS |
| earnings-preview | 1p preview |
| initiating-coverage | md research; xlsx model; md valuation; zip charts; 30–50p docx |
| model-update | updated xlsx if provided + estimate/PT note |
| morning-note | 1p md/Word |
| sector-overview | Word or PPT + Excel appendix |
| thesis-tracker | md/Word scorecard |
| catalyst-calendar | Excel + weekly md; optional Google Calendar |
| idea-generation | 5–10 one-pagers + screen methodology |

---

*End of file inventory. All identifiers and workflow fragments are taken from the plugin files listed in §1. No MCP servers, hooks, or example PPTX files were inferred beyond what those files contain.*
