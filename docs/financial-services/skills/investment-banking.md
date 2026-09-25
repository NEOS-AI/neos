# Investment Banking 플러그인 분석

범위: `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/investment-banking/`  
방법: 디렉터리 내 모든 파일을 읽고 인용. 없는 내용은 만들지 않음.  
기준일: 파일 내용 그대로.

---

## 파일 목록 (실재 파일만)

```
.claude-plugin/plugin.json
.claude/investment-banking.local.md.example
.gitignore
.mcp.json
commands/buyer-list.md
commands/cim.md
commands/deal-tracker.md
commands/merger-model.md
commands/one-pager.md
commands/process-letter.md
commands/teaser.md
hooks/hooks.json
README.md
skills/buyer-list/SKILL.md
skills/cim-builder/SKILL.md
skills/datapack-builder/SKILL.md
skills/deal-tracker/SKILL.md
skills/merger-model/SKILL.md
skills/pitch-deck/SKILL.md
skills/pitch-deck/reference/calculation-standards.md
skills/pitch-deck/reference/formatting-standards.md
skills/pitch-deck/reference/slide-templates.md
skills/pitch-deck/reference/xml-reference.md
skills/process-letter/SKILL.md
skills/strip-profile/SKILL.md
skills/teaser/SKILL.md
```

스킬 9개, 커맨드 7개. `datapack-builder`와 `pitch-deck`에는 대응 커맨드 파일이 없다.

---

## plugin.json

경로: `.claude-plugin/plugin.json`

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

- name: `investment-banking`
- version: `0.2.1`
- author: Anthropic
- description 키워드: client and market insights, deck creation, financial analysis, transaction management

---

## README.md

제목: `# Investment Banking Plugin`

한 줄 소개:

> Investment banking productivity tools for equity research, valuation, presentations, and deal materials.

### Features (README 인용)

- **Deal Materials** - CIMs, teasers, process letters, and buyer lists
- **Presentations** - Strip profiles, pitch decks with branded templates
- **Transaction Support** - Merger models, deal tracking, and data packs

### Installation (README 인용)

```bash
claude --plugin-dir /path/to/investment-banking
```

또는 프로젝트 `.claude-plugin/` 디렉터리에 복사.

### Commands 표 (README)

| Command | Description |
|---------|-------------|
| `/one-pager [company]` | One-page strip profile for pitch books |
| `/cim [company]` | Draft Confidential Information Memorandum |
| `/teaser [company]` | Anonymous one-page company teaser |
| `/buyer-list [company]` | Strategic and financial buyer universe |
| `/merger-model [deal]` | Accretion/dilution M&A analysis |
| `/process-letter [deal]` | Bid instructions and process correspondence |
| `/deal-tracker` | Track live deals, milestones, and action items |

### Skills 표 (README)

Deal Materials: `cim-builder`, `teaser`, `process-letter`, `buyer-list`, `datapack-builder`  
Presentations: `strip-profile`, `pitch-deck`  
Transaction Support: `merger-model`, `deal-tracker`

README Example Workflows가 생성하는 산출물:

- `/one-pager`: Single-slide company profile using PPT template; 4 quadrants: Overview, Business, Financials, Ownership
- `/cim`: Full CIM document with executive summary, business overview, financial analysis, and market positioning
- `/merger-model`: Accretion/dilution analysis; Sources and uses, pro forma financials; Sensitivity on purchase price and synergies

README는 `equity research, valuation`을 소개 문장에 넣지만, 전용 equity-research 스킬/커맨드 파일은 없다.

---

## hooks.json

경로: `hooks/hooks.json`

```json
{
  "hooks": {}
}
```

훅 정의 없음.

---

## .mcp.json

경로: `.mcp.json`

```json
{
  "mcpServers": {}
}
```

MCP 서버 정의 없음. `datapack-builder` description은 "MCP servers"를 소스 옵션으로 언급하지만 플러그인 자체 `.mcp.json`은 비어 있다.

---

## .gitignore

```
# User-specific settings
.claude/*.local.md
```

로컬 설정 파일 무시.

---

## .claude extras

경로: `.claude/investment-banking.local.md.example`

프론트매터 YAML (복사 후 `.claude/investment-banking.local.md`로 커스터마이즈하라고 명시):

- Your info: `name`, `title`, `group`, `firm`, `email_signature`
- Coverage focus: `sectors`, `verticals`
- Deal parameters: `typical_deal_size_range` (`"$50M - $500M"`), `transaction_types` (M&A Sell-side / Buy-side / Capital Raise / Strategic Advisory)
- Active deals: `active_mandates` (예시: Project Alpine Sell-side Marketing, Project Summit Buy-side Due Diligence)
- Target tracking: `priority_targets`
- Valuation defaults: Comparable Companies, Precedent Transactions, DCF; comps multiples EV/Revenue, EV/EBITDA, EV/ARR

본문 Notes 섹션 템플릿:

- Market Themes
- Key Relationships
- Recent Precedent Transactions 표 (`Target | Acquirer | Value | Multiple | Date`)

이 파일은 예시이며 실행 훅이 아니다. `.gitignore`가 `.claude/*.local.md`를 무시한다.

---

## 스킬: strip-profile

경로: `skills/strip-profile/SKILL.md`  
프론트매터 name은 폴더명과 다름: `fsi-strip-profile`

### Frontmatter

```yaml
name: fsi-strip-profile
description: |
  Creates professional investment banking strip profiles (company profiles) for pitch books, deal materials, and client presentations. Generates 1-4 information-dense slides with quadrant layouts, charts, and tables.
```

### Workflow

1. Clarify Requirements — 단일 슬라이드 vs 3–4 슬라이드, 강조 주제. "Only after user confirms, proceed to research"
2. Research & Planning — 소스: BamSEC, SEC EDGAR Item 1 / MD&A, investor presentations, Bloomberg/FactSet/CapIQ, FactSet/CapIQ consensus, 최근 90일 뉴스
3. Slide-by-Slide Creation — **한 슬라이드씩**. 이미지 변환 후 시각 검수. 사용자 승인 전 다음 슬라이드 금지

필수 변환 명령:

```bash
soffice --headless --convert-to pdf presentation.pptx
pdftoppm -jpeg -r 150 -f 1 -l 1 presentation.pdf slide
```

### Templates / 레이아웃

- 종횡비: `LAYOUT_4x3` (10" × 7.5")
- 1페이지 4분면:
  - Q1 Company Overview (x=0.3, y=0.6, w=4.7, h=3.0)
  - Q2 Business & Positioning (x=5.0, y=0.6, w=4.7, h=3.0)
  - Q3 Key Financials (x=0.3, y=3.7, w=4.7, h=3.5)
  - Q4 상장: 1Y stock + shareholders / 비상장: Recent developments or Ownership/M&A
- 폰트: 제목 24pt, 분면 헤더 14pt, 본문 11pt, 표 10pt(밀집 9pt), 차트 9pt, 소스 8pt
- 구현: PptxGenJS. 헤더+불릿은 단일 텍스트박스. 재무는 `slide.addTable()` 또는 차트(둘 다 아님)
- 시각 참조: `examples/Nike_Strip_Profile_Example.pptx` (이 경로의 실제 pptx 파일은 플러그인 트리에 없음)
- 후속 페이지: two-column, full-slide charts, sidebar. 권장 흐름: Products/Market → Financial Analysis → Leadership

### Output artifacts

- PowerPoint (PptxGenJS). 스킬 본문은 "Reference the **PPTX skill** for PowerPoint file creation"
- 검수용 이미지 (pdf → jpeg)
- 명시된 파일명 규칙은 없음

### Safety / 품질 언어

- "actual numbers, no placeholders"
- "Do not guess or assume colors" — 브랜드 색은 웹 검색
- "STOP and wait for explicit user approval"
- "Never use placeholder divs or static images"
- "NEVER plain text prose or HTML tables"
- Quality: "Investment banking quality (GS/MS/JPM standard)"
- 소스 인용 체크리스트: "Sources cited"

법적 disclaimer / 고객 리뷰 요구는 이 스킬에 없음.

---

## 스킬: pitch-deck

경로: `skills/pitch-deck/SKILL.md`  
대응 커맨드 없음.

### Frontmatter

```yaml
name: pitch-deck
description: "Populates investment banking pitch deck templates with data from source files. Use when: user provides a PowerPoint template to fill in, user has source data (Excel/CSV) to populate into slides, user mentions populating or filling a pitch deck template, or user needs to transfer data into existing slide layouts. Not for creating presentations from scratch."
```

### Workflow

Decision tree: (1) 빈 템플릿에 소스 데이터 채우기 (2) 이미 채워진 슬라이드 편집 (3) 포맷 수정

Template Population 5단계:

1. Extract and validate source data — 원본을 `[filename]_backup.pptx`로 백업
2. Map content to template sections
3. Populate slides with proper formatting — instruction box 삭제 후 생산 포맷
4. Validate → Fix → Repeat (최대 3 사이클)
5. Final verification

검증 루프:

```bash
soffice --headless --convert-to pdf presentation.pptx
pdftoppm -jpeg -r 150 presentation.pdf slide
```

### Templates

스킬 자체는 슬라이드 템플릿을 내장하지 않음. 사용자가 제공하는 PPT 템플릿을 채움. 참조 파일 4개:

| File | Purpose (스킬 표 인용) |
|------|------------------------|
| `formatting-standards.md` | Text, bullets, tables, charts, alignment |
| `slide-templates.md` | Content mapping guidance for common slide types |
| `xml-reference.md` | PowerPoint XML patterns for tables, shapes, arrows |
| `calculation-standards.md` | Financial formulas for verification (CAGR, consensus) |

공통 슬라이드 타입 (`slide-templates.md`): Market Definition, Market Sizing/TAM, Competitive Landscape, Financial Summary, Transaction Comparables.

### Output artifacts

- 채워진 `.pptx` (원본 템플릿 수정본)
- 백업 `[filename]_backup.pptx`
- 3사이클 후에도 문제 남으면 이슈 목록과 disclaimer를 붙인 파일

### Safety 언어 (직접 인용)

렌더링 한계 — 전달 시 필수 문구:

> "This file was validated using LibreOffice. Please review in Microsoft PowerPoint before distribution, as rendering differences may exist."

3사이클 실패 시:

> "The following issues could not be resolved automatically: [list]. Manual review required."

데이터:

> **Do not:** Fabricate data or make unsupported estimates. (`slide-templates.md`)

로고 없을 때:

> "[LOGO NOT PROVIDED - please supply company logo]"

XML:

> **Always work on a backup copy** — never edit the original file directly.

소스 불일치:

> If using data from other sources (web search, external documents), flag this to the user

계산 불일치:

> Present both values if material difference / Flag to user for resolution

Anti-patterns: instruction box에 데이터 넣기, 파이프/탭 가짜 표, placeholder 대비 상속.

---

## 스킬: datapack-builder

경로: `skills/datapack-builder/SKILL.md`  
대응 커맨드 없음. 플러그인에서 가장 긴 스킬 (656줄).

### Frontmatter

```yaml
name: datapack-builder
description: Build professional financial services data packs from various sources including CIMs, offering memorandums, SEC filings, web search, or MCP servers. Extract, normalize, and standardize financial data into investment committee-ready Excel workbooks with consistent structure, proper formatting, and documented assumptions. Use for M&A due diligence, private equity analysis, investment committee materials, and standardizing financial reporting across portfolio companies. Do not use for simple financial calculations or working with already-completed data packs.
```

### Workflow (6 phase)

1. Document Processing and Data Extraction
2. Data Normalization and Standardization
3. Build Excel Workbook (`xlsx` skill 사용 강제)
4. Scenario Building (Management / Base / Downside)
5. Quality Control and Validation
6. Final Delivery

### Templates / 구조

표준 8탭 (명시적 지시 없으면):

1. Executive Summary
2. Historical Financials (Income Statement)
3. Balance Sheet
4. Cash Flow Statement
5. Operating Metrics
6. Property/Segment Performance (if applicable)
7. Market Analysis
8. Investment Highlights

서식 규칙 6개: 통화 `$`, 운영지표 `$` 없음, 퍼센트, 연도 텍스트, 혼합 시 메트릭별 포맷, 계산은 수식만.

폰트 색 (xlsx skill 강제): 입력 파랑 RGB(0,0,255), 수식 검정, 시트 링크 초록 RGB(0,128,0).

시나리오: Management Case, Base Case (Risk-Adjusted), Downside Case (LBO에 권장).

산업 적응: Technology/SaaS, Manufacturing/Industrial, Real Estate/Hospitality, Healthcare/Services.

### Output artifacts

- Excel: `CompanyName_DataPack_YYYY-MM-DD.xlsx`
- "File saved to outputs with proper naming convention"

### Safety / 정확성 언어

> Data Accuracy (Zero Tolerance for Errors)

> Trace every number to source document with page reference

> Use formula-based calculations exclusively (no hardcoded values)

> Verify balance sheet balances: Assets = Liabilities + Equity

> Flag any "hockey stick" inflections that require skepticism

정규화: 반복적 "one-time" 가산 금지. Base Case는 IC에 방어 가능해야 함.

법적 합의/소송 정규화는 회계 조정으로만 다루며, 법률 자문 요구 문장은 없음.

---

## 스킬: cim-builder

경로: `skills/cim-builder/SKILL.md`

### Frontmatter

```yaml
name: cim-builder
description: Structure and draft a Confidential Information Memorandum for sell-side M&A processes. Organizes company information into a professional, investor-ready document with consistent formatting and narrative flow. Use when preparing sell-side materials, drafting a CIM, or organizing company data for a sale process. Triggers on "CIM", "confidential information memorandum", "offering memorandum", "info memo", "draft CIM", or "sell-side materials".
```

### Workflow

Step 1 Gather Source Materials: management presentations, 3–5년 실적, budget/forecast, website, 고객 데이터(필요 시 익명), org chart, 기존 덱, QoE(있으면).

Step 2 CIM Structure (목차):

- I. Executive Summary (2–3 pages)
- II. Company Overview (3–5)
- III. Industry Overview (3–5) — TAM/SAM/SOM
- IV. Growth Opportunities (2–3)
- V. Customers & Sales (3–5)
- VI. Operations (2–3)
- VII. Financial Overview (5–8)
- VIII. Appendix

Step 3 Drafting Guidelines: 톤 professional/factual; 데이터로 주장 뒷받침; 총 40–60 pages.

### Templates

목차와 섹션 길이 가이드가 템플릿. 별도 파일 템플릿 없음.

### Output artifacts

- Word document (.docx) with professional formatting
- Separate Excel appendix with detailed financials
- Charts and exhibits embedded in the document

### Safety 언어

> **Confidentiality**: Include a disclaimer page. Anonymize sensitive customer data unless seller approves

> The CIM is a sales document — lead with strengths, but don't hide material issues (buyers will find them in diligence)

> Work with legal on the confidentiality disclaimer and any regulatory disclosures

> Get management to review for factual accuracy before distribution

> The CIM sets expectations on valuation — make sure the narrative supports the asking price

---

## 스킬: teaser

경로: `skills/teaser/SKILL.md`

### Frontmatter

```yaml
name: teaser
description: Draft anonymous one-page company teasers for sell-side M&A processes. Creates a compelling summary without revealing the company's identity, designed to gauge buyer interest before NDA execution. Triggers on "teaser", "blind teaser", "anonymous profile", "one-pager for process", or "draft teaser for sell-side".
```

### Workflow

1. Gather Inputs (사업 설명, 섹터, 재무, 지역, 3–5 highlights, 익명화 범위, 타깃 바이어)
2. Teaser Structure (1페이지)
3. Anonymization Check
4. Output

### Templates (1페이지 구조)

- Header: Deal code name, Sector descriptor, `"Confidential — For Discussion Purposes Only"`
- Company Description 2–3문장 (이름 없이)
- Investment Highlights 4–6 bullets
- Financial Summary 표: Revenue, Revenue Growth, EBITDA, EBITDA Margin, Employees
- Transaction Overview 2–3문장 + EOI 연락처

### Output artifacts

- Word document (.docx) — one page
- PDF version for distribution
- Optional PowerPoint version (single slide)

### Safety 언어

익명화 체크:

- No company name, brand names, or product names
- No specific city (use region)
- No named customers or partners
- No employee count if too distinctive
- Revenue ranges instead of exact figures if the sector is small
- No logos, screenshots, or identifiable imagery

> Always have the client and legal review before distribution

> Track who receives the teaser — it becomes the outreach log for the process

> Use aspirational but accurate language — "leading", "differentiated", "high-growth" are fine if true

---

## 스킬: buyer-list

경로: `skills/buyer-list/SKILL.md`

### Frontmatter

```yaml
name: buyer-list
description: Build and organize a universe of potential acquirers for sell-side M&A processes. Identifies strategic and financial buyers, assesses fit, and prioritizes outreach. Use when preparing for a sell-side mandate, building a buyer universe, or evaluating potential partners. Triggers on "buyer list", "buyer universe", "potential acquirers", "who would buy this", "strategic buyers", or "financial sponsors".
```

### Workflow

1. Understand the Target
2. Strategic Buyers — Direct Competitors / Adjacent Players / Vertical Integrators / Platform Builders
3. Financial Sponsors — Platform Investors / Add-on Buyers / Growth Equity
4. Prioritization — Tier 1 (5–10), Tier 2 (10–15), Tier 3 (10–20)
5. Contact Mapping (Tier 1)
6. Output

### Templates (표)

Strategic: `Buyer | Sector | Revenue | Strategic Fit | Financial Capacity | M&A Track Record | Likelihood | Priority`  
Sponsors: `Sponsor | Fund Size | Sector Focus | Portfolio Overlap | Recent Activity | Priority`

### Output artifacts

- Excel: Strategic buyers tab, Financial sponsors tab, Contact mapping for Tier 1, Summary statistics
- One-page buyer universe summary for the engagement letter or pitch

### Safety 언어

> Check for antitrust concerns with direct competitors — flag any that might face regulatory issues

> Always ask the seller if there are buyers they want included or excluded

> Quality over quantity — a focused list of 30-40 well-researched buyers beats a list of 200 names

법률 리뷰/disclaimer 페이지 요구는 없음. antitrust는 "flag"만.

---

## 스킬: merger-model

경로: `skills/merger-model/SKILL.md`

### Frontmatter

```yaml
name: merger-model
description: Build accretion/dilution analysis for M&A transactions. Models pro forma EPS impact, synergy sensitivities, and purchase price allocation. Use when evaluating a potential acquisition, preparing merger consequences analysis for a pitch, or advising on deal terms. Triggers on "merger model", "accretion dilution", "M&A model", "pro forma EPS", "merger consequences", or "deal impact analysis".
```

### Workflow

1. Gather Inputs (Acquirer / Target / Deal Terms)
2. Purchase Price Analysis
3. Sources & Uses
4. Pro Forma EPS (Year 1–3)
5. Sensitivity (시너지×프리미엄, 현금/주식 mix)
6. Breakeven Synergies (Year 1 EPS-neutral)
7. Output

### Templates (표)

- Purchase Price: Offer price, Premium, Equity value, net debt, EV, EV/EBITDA, P/E
- Sources & Uses
- Pro Forma EPS: Standalone / Pro Forma / Accretion/(Dilution) — NI, synergies AT, foregone interest, new debt interest, intangible amortization, PF shares, PF EPS, A/(D)%
- Sensitivity: $0–100M syn × 15–30% premium; 100% cash → 100% stock

### Output artifacts

Excel workbook:

- Assumptions tab
- Sources & uses
- Pro forma income statement
- Accretion/dilution summary
- Sensitivity tables
- Breakeven analysis

추가: One-page merger consequences summary for pitch book

파일명 규칙 없음. xlsx skill 강제 문구 없음.

### Safety 언어

모델 주의 (Important Notes):

- Always show both GAAP and adjusted (cash) EPS where relevant
- Include purchase price allocation — goodwill and intangible amortization matter for GAAP EPS
- Synergy phase-in is critical — Year 1 is often only 25-50% of run-rate synergies
- Don't forget foregone interest income on cash used and new interest expense on debt raised
- Tax rate on synergies and interest adjustments should match the acquirer's marginal rate

법률/고객 승인/disclaimer 문장 없음. "advice"는 description의 "advising on deal terms"뿐.

---

## 스킬: process-letter

경로: `skills/process-letter/SKILL.md`

### Frontmatter

```yaml
name: process-letter
description: Draft process letters and bid instructions for sell-side M&A processes. Covers initial indication of interest (IOI) instructions, final bid procedures, and management meeting logistics. Triggers on "process letter", "bid instructions", "IOI letter", "bid procedures", "final round letter", or "management meeting invite".
```

### Workflow

1. Determine Letter Type — Initial process letter / IOI instructions / Second round·final bid / Management meeting invitation
2. Initial Process Letter / IOI Instructions
3. Final Bid / Second Round Letter
4. Management Meeting Invitation
5. Output

### Templates (섹션)

초기/IOI: Header(Date, deal code, "Confidential", addressed to prospective buyer) → Introduction, Process Overview, IOI Requirements, Submission Details, Confidentiality Reminder (NDA, data room), Contact Information

IOI 요구: EV range, consideration form, financing sources/certainty, DD requirements, timeline, conditions, buyer description/rationale

Final bid 추가: SPA/APA markup, committed financing letters, remaining diligence, exclusivity, regulatory/antitrust, key personnel, binding vs non-binding, evaluation criteria

Management meeting: logistics, attendees, agenda, ground rules (no recording, confidentiality), materials, follow-up

마감 가이드: "typically 2-3 weeks for IOIs, 3-4 weeks for final bids"

### Output artifacts

- Word document (.docx) with professional letter formatting
- Firm letterhead placeholder
- Track changes version for client review

### Safety 언어

> Coordinate with legal on any representations or commitments in the letter

> Client should review and approve before sending — they may want to adjust tone or terms

> Keep a log of who received each letter and when — this becomes the process tracker

> "Confidential" 헤더, Confidentiality Reminder, NDA 참조

---

## 스킬: deal-tracker

경로: `skills/deal-tracker/SKILL.md`

### Frontmatter

```yaml
name: deal-tracker
description: Track multiple live deals with milestones, deadlines, action items, and status updates. Maintains a deal pipeline view and surfaces upcoming deadlines and overdue items. Use when managing a book of business, tracking process milestones, or preparing for weekly deal reviews. Triggers on "deal tracker", "deal status", "where are we on", "process update", "deal pipeline", or "weekly deal review".
```

### Workflow

1. Deal Setup — code name, client, type, role, size, stage, team, key dates
2. Milestone Tracking
3. Action Items
4. Weekly Deal Review
5. Output

Stage 체인: `Pre-mandate → Engaged → Marketing → IOI → Diligence → Final bids → Signing → Close`

마일스톤 표 행: Engagement letter signed, CIM/teaser drafted, Buyer list approved, Teaser distributed, NDA execution, CIM distributed, IOI deadline, IOIs received/reviewed, Shortlist, Management meetings, Data room opened, Final bid deadline, Bids received/reviewed, Exclusivity granted, Confirmatory diligence, Purchase agreement signed, Regulatory approval, Close

Status: On Track / At Risk / Delayed / Complete  
Action priority: P0/P1/P2, Open/Done/Blocked

### Templates

표 4종: Deal fields, Milestone tracker, Action items, Weekly review 서술 구조.

### Output artifacts

Excel:

- Pipeline overview (all deals, one row each)
- Per-deal milestone tracker tabs
- Action item master list
- Weekly review summary

Optional: Markdown summary for email/Slack distribution

### Safety 언어

운영 주의만:

> Update the tracker weekly at minimum — stale trackers are worse than no tracker

> Flag deals where milestones are slipping

> Action items without owners and due dates don't get done

> Archive closed/dead deals separately

기밀/법률/disclaimer 문장 없음. 마일스톤에 "Regulatory approval", "NDA execution"은 추적 항목일 뿐.

---

## 커맨드: /one-pager

경로: `commands/one-pager.md`  
연결 스킬: `strip-profile` (`skill: "strip-profile"`). 스킬 frontmatter name은 `fsi-strip-profile`.

### Frontmatter

```yaml
description: Create a one-page company strip profile using branded PPT template
argument-hint: "[company name or ticker]"
```

### Workflow (커맨드에 내장, 다른 커맨드보다 김)

1. Gather Company Information — 인자 없으면 "What company would you like to profile?"
2. Check for Available PPT Template Skills — `ls skills/ | grep -E "ppt-template|brand-guidelines"`; 없으면 템플릿 경로 요청
3. Load Strip Profile Skill — 단슬라이드 확인, 회사 리서치, 4분면 작성
4. Visual Review — 이미지 변환, overlap/cutoff, placeholder 없음
5. Deliver Output

### Templates

커맨드 내 ASCII 4분면 레이아웃. 소스 푸터: `Source: Company filings, FactSet`

### Output artifacts

1. PowerPoint file (.pptx)
2. Image preview
3. Summary of key data points included

### Safety / 품질

Quality Checklist: 4분면 실데이터, no placeholder, brand colors, accent bars, 재무 표 포맷, sources cited, no overflow, "Investment banking quality (GS/MS/JPM standard)"

법률 리뷰 요구 없음.

---

## 커맨드: /cim

경로: `commands/cim.md`

### Frontmatter

```yaml
description: Draft a Confidential Information Memorandum
argument-hint: "[company name]"
```

### Workflow (전문)

> Load the `cim-builder` skill and structure a CIM for the specified company.
>
> If a company name is provided, use it. Otherwise ask the user for the target company and available source materials.

템플릿/산출물/안전 문구는 커맨드에 없고 스킬에 위임.

---

## 커맨드: /teaser

경로: `commands/teaser.md`

### Frontmatter

```yaml
description: Draft an anonymous one-page teaser
argument-hint: "[company name]"
```

### Workflow (전문)

> Load the `teaser` skill and create a blind teaser for the specified company.
>
> If a company name is provided, use it. Otherwise ask the user for the company details to anonymize.

안전 관련 단어: anonymous / blind teaser / anonymize. 상세 익명화·legal review는 스킬.

---

## 커맨드: /buyer-list

경로: `commands/buyer-list.md`

### Frontmatter

```yaml
description: Build a buyer universe for a sell-side process
argument-hint: "[company or sector]"
```

### Workflow (전문)

> Load the `buyer-list` skill and build a universe of potential strategic and financial acquirers.
>
> If a company or sector is provided, use it. Otherwise ask the user for the target company details.

---

## 커맨드: /merger-model

경로: `commands/merger-model.md`

### Frontmatter

```yaml
description: Build an accretion/dilution merger model
argument-hint: "[acquirer] acquiring [target]"
```

### Workflow (전문)

> Load the `merger-model` skill and build a merger consequences analysis.
>
> If acquirer and target are provided, use them. Otherwise ask the user for deal details.

---

## 커맨드: /process-letter

경로: `commands/process-letter.md`

### Frontmatter

```yaml
description: Draft a process letter or bid instructions
argument-hint: "[IOI or final bid]"
```

### Workflow (전문)

> Load the `process-letter` skill and draft process correspondence.
>
> If a letter type is specified (IOI, final bid, management meeting invite), use it. Otherwise ask the user what stage the process is in.

---

## 커맨드: /deal-tracker

경로: `commands/deal-tracker.md`

### Frontmatter

```yaml
description: Track and review live deal pipeline
argument-hint: ""
```

### Workflow (전문)

> Load the `deal-tracker` skill to review deal status, update milestones, and manage action items across live deals.

인자가 비어 있음. 회사/딜 이름을 묻지 않음.

---

## 커맨드 ↔ 스킬 매핑 (파일 기준)

| Command | Loads skill | 커맨드 자체 산출물 명시 |
|---------|-------------|-------------------------|
| `/one-pager` | `strip-profile` | .pptx, image preview, summary |
| `/cim` | `cim-builder` | 없음 (스킬에 .docx + Excel appendix) |
| `/teaser` | `teaser` | 없음 (스킬에 .docx, PDF, optional PPT) |
| `/buyer-list` | `buyer-list` | 없음 (스킬에 Excel + one-pager summary) |
| `/merger-model` | `merger-model` | 없음 (스킬에 Excel + one-page summary) |
| `/process-letter` | `process-letter` | 없음 (스킬에 .docx + track-changes) |
| `/deal-tracker` | `deal-tracker` | 없음 (스킬에 Excel + optional Markdown) |

커맨드 없는 스킬: `datapack-builder`, `pitch-deck`

이름 불일치: 커맨드/README는 `strip-profile`, 스킬 YAML `name`은 `fsi-strip-profile`.

---

## pitch-deck 참조 파일 요약 (인용)

### calculation-standards.md

검증 공식: CAGR `FV = PV × (1+CAGR)^n`, EV/Revenue, EV/EBITDA, Market Share, YoY, CAGR from endpoints.

Consensus: Size는 full min-max; CAGR은 최고/최저 제외 중앙 클러스터; Projection은 합의 CAGR을 사이즈 중점에 적용.

Red flags: 출처와 >5% 차이, 배수 정의 불일치(LTM vs NTM). "When in doubt: Note the discrepancy in a footnote"

### formatting-standards.md

불릿 기호: ✓ 포함, × 제외, • 중립, 번호 순서, ‣/– 서브. 표는 실제 table object. 화살표는 PPT shape (텍스트 → 금지). 템플릿 브랜드 색/폰트에 맞출 것.

### slide-templates.md

템플릿 분석 → 데이터 인벤토리 → 섹션 매핑 → 갭 해결 후 populate. 데이터 부족 시 사용자에게 flag / "Data not available". **Do not fabricate.**

### xml-reference.md

python-pptx를 기본으로 쓰고, 직접 XML은 기존 요소 미세조정만. 테이블을 XML로 처음부터 만들지 말 것. 항상 백업. 단위: 1 inch = 914400 EMU. 16:9 슬라이드 12192000 × 6858000 EMU.

색 예시 `E67E22`, `D35400`은 placeholder이며 템플릿 브랜드 색으로 교체.

---

## 안전 언어 종합 (있는 것만)

| 위치 | 있는 것 | 없는 것 |
|------|---------|---------|
| plugin.json / README / hooks / mcp | 없음 | 규제 고지, 투자 자문 부인 |
| cim-builder | disclaimer page, 고객 익명화, legal on disclaimer/regulatory, management factual review, don't hide material issues | "not investment advice" |
| teaser | 익명화 체크리스트, client and legal review before distribution, NDA 전 단계 | |
| process-letter | Confidential, NDA reminder, legal on representations, client approve before sending | |
| buyer-list | antitrust flag, seller include/exclude | legal review 강제 |
| pitch-deck | LibreOffice≠PowerPoint 고지, 데이터 날조 금지, 로고 미제공 플래그, 소스 불일치 플래그, 백업 | 투자 자문 부인 |
| datapack-builder | zero-tolerance 추적, 수식만, BS 균형, hockey-stick 회의 | legal review |
| strip-profile / one-pager | placeholder 금지, 사용자 슬라이드 승인, GS/MS/JPM 품질 | legal/disclaimer |
| merger-model | GAAP vs cash EPS, PPA, synergy phase-in | 모델은 예시일 뿐 등 |
| deal-tracker | stale tracker 경고 | 기밀 취급 지침 |

전 플러그인에 공통 "this is not legal/financial advice" 문장은 없다.

---

## 관찰 (파일에 근거, 추정 최소화)

- 훅·MCP는 빈 객체.
- `datapack-builder`, `pitch-deck`은 README Skills 표에만 있고 Commands 표/commands/ 에는 없음.
- README 도입부의 "equity research, valuation"은 전용 스킬로 구현되어 있지 않음. valuation은 merger-model 배수, datapack, pitch-deck comps, strip-profile 배수, local.md 기본 방법론에 흩어져 있음.
- `examples/Nike_Strip_Profile_Example.pptx`는 strip-profile이 참조하나 이 트리에 파일이 없다.
- 대부분 커맨드는 2문장 래퍼. `/one-pager`만 자체 워크플로·체크리스트를 가짐.
- 산출물 형식: PPT(strip/pitch/one-pager/optional teaser), Word(CIM/teaser/process-letter), Excel(datapack/merger/buyer-list/deal-tracker/CIM appendix).
