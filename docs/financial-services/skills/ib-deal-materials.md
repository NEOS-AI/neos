# IB Deal Materials 스킬·커맨드 분석

> 출처: `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/investment-banking/`
> 범위: `skills/` 전체 9개, `commands/` 전체 7개, `pitch-deck/reference/` 4개.
> 원칙: 원문 인용. 원문에 없는 수치·단계·규칙은 추가하지 않음.
> README 분류는 매핑 확인용으로만 사용. 훅(`hooks.json`)은 `{}`.

---

## 1. 범위와 파일 목록

### 1.1 스킬 (9)

| 스킬 디렉터리 | SKILL `name` | 부가 파일 |
|---|---|---|
| `pitch-deck/` | `pitch-deck` | `reference/calculation-standards.md`, `formatting-standards.md`, `slide-templates.md`, `xml-reference.md` |
| `cim-builder/` | `cim-builder` | SKILL.md만 |
| `teaser/` | `teaser` | SKILL.md만 |
| `buyer-list/` | `buyer-list` | SKILL.md만 |
| `merger-model/` | `merger-model` | SKILL.md만 |
| `process-letter/` | `process-letter` | SKILL.md만 |
| `deal-tracker/` | `deal-tracker` | SKILL.md만 |
| `strip-profile/` | `fsi-strip-profile` | SKILL.md만 (`examples/Nike_Strip_Profile_Example.pptx`는 텍스트로만 언급, 디렉터리에 파일 없음) |
| `datapack-builder/` | `datapack-builder` | SKILL.md만 |

### 1.2 커맨드 (7)

| 커맨드 파일 | description | 로드하는 스킬 |
|---|---|---|
| `commands/one-pager.md` | Create a one-page company strip profile using branded PPT template | `strip-profile` |
| `commands/cim.md` | Draft a Confidential Information Memorandum | `cim-builder` |
| `commands/teaser.md` | Draft an anonymous one-page teaser | `teaser` |
| `commands/buyer-list.md` | Build a buyer universe for a sell-side process | `buyer-list` |
| `commands/merger-model.md` | Build an accretion/dilution merger model | `merger-model` |
| `commands/process-letter.md` | Draft a process letter or bid instructions | `process-letter` |
| `commands/deal-tracker.md` | Track and review live deal pipeline | `deal-tracker` |

`pitch-deck`과 `datapack-builder`에는 대응 커맨드 파일이 없다.

### 1.3 README가 묶는 세 묶음

README 원문:

> - **Deal Materials** - CIMs, teasers, process letters, and buyer lists
> - **Presentations** - Strip profiles, pitch decks with branded templates
> - **Transaction Support** - Merger models, deal tracking, and data packs

Skills 표:

> Deal Materials: cim-builder, teaser, process-letter, buyer-list, datapack-builder
> Presentations: strip-profile, pitch-deck
> Transaction Support: merger-model, deal-tracker

README Skills 표는 datapack-builder를 Deal Materials에 넣고, Features 줄은 data packs를 Transaction Support에 넣는다. 원문 그대로 병기.

---

## 2. 스킬–커맨드 관계

커맨드 본문은 대부분 한 줄 로더다. 예외는 `one-pager.md`뿐이며, strip-profile 워크플로·레이아웃·QC를 커맨드 쪽에 다시 적는다.

인용 — `commands/cim.md`:

```
Load the `cim-builder` skill and structure a CIM for the specified company.

If a company name is provided, use it. Otherwise ask the user for the target company and available source materials.
```

인용 — `commands/teaser.md`:

```
Load the `teaser` skill and create a blind teaser for the specified company.

If a company name is provided, use it. Otherwise ask the user for the company details to anonymize.
```

인용 — `commands/buyer-list.md`:

```
Load the `buyer-list` skill and build a universe of potential strategic and financial acquirers.

If a company or sector is provided, use it. Otherwise ask the user for the target company details.
```

인용 — `commands/merger-model.md`:

```
Load the `merger-model` skill and build a merger consequences analysis.

If acquirer and target are provided, use them. Otherwise ask the user for deal details.
```

인용 — `commands/process-letter.md`:

```
Load the `process-letter` skill and draft process correspondence.

If a letter type is specified (IOI, final bid, management meeting invite), use it. Otherwise ask the user what stage the process is in.
```

인용 — `commands/deal-tracker.md`:

```
Load the `deal-tracker` skill to review deal status, update milestones, and manage action items across live deals.
```

`one-pager`는 아래 10절에서 스킬과 함께 인용.

---

## 3. pitch-deck

### 3.1 역할 (원문 description)

> Populates investment banking pitch deck templates with data from source files. Use when: user provides a PowerPoint template to fill in, user has source data (Excel/CSV) to populate into slides, user mentions populating or filling a pitch deck template, or user needs to transfer data into existing slide layouts. **Not for creating presentations from scratch.**

작업 시작 전 4개 reference를 모두 읽으라고 명시한다.

| File | Purpose (원문) |
|------|----------------|
| `formatting-standards.md` | Text, bullets, tables, charts, alignment |
| `slide-templates.md` | Content mapping guidance for common slide types |
| `xml-reference.md` | PowerPoint XML patterns for tables, shapes, arrows |
| `calculation-standards.md` | Financial formulas for verification (CAGR, consensus) |

### 3.2 워크플로 결정 트리

원문:

```
┌─ Populating empty template with source data?
│  └─→ Follow "Template Population Workflow" below
│
├─ Editing existing populated slides?
│  └─→ Extract current content, modify, revalidate
│
└─ Fixing formatting issues on existing slides?
   └─→ See "Common Failures" table, apply targeted fixes
```

### 3.3 LibreOffice 렌더링 제한 (필수 고지)

> LibreOffice is used for validation but DOES NOT render PowerPoint files accurately. It will mangle fonts, gradients, shape positions, text wrapping, and some table formatting.
>
> A slide that passes visual validation in LibreOffice may still have issues in Microsoft PowerPoint. The validation loop catches structural issues (missing content, broken tables, placeholder formatting retained) but **cannot** catch font substitution, subtle alignment shifts, or gradient problems.

납품 시 필수 문장:

> "This file was validated using LibreOffice. Please review in Microsoft PowerPoint before distribution, as rendering differences may exist."

### 3.4 Template Population Workflow (5 Phase)

원문 진행 체크리스트:

```
Pitch Deck Progress:
- [ ] Phase 1: Extract and validate source data
- [ ] Phase 2: Map content to template sections
- [ ] Phase 3: Populate slides with proper formatting
- [ ] Phase 4: Validate → Fix → Repeat until clean
- [ ] Phase 5: Final verification
```

**Phase 1 Data Extraction (원문 단계):**
1. 원본 템플릿 백업 — `[filename]_backup.pptx`
2. 소스 식별 (Excel, CSV, PDF, Word, databases, web)
3. 데이터 추출
4. 원본 대비 숫자 검증
5. 단위·통화 표준화
6. 계산 검증 필요 항목은 `calculation-standards.md`

**Phase 2 Content Mapping:** 템플릿을 열어 시각 검토 → placeholder/content box 식별 → `slide-templates.md`로 매핑 → colored instruction box 식별 → 갭은 `slide-templates.md#handling-data-template-mismatches`

**Phase 3 Population:** instruction box 삭제 후 생산 포맷으로 재작성. 테이블은 실제 table object. 화살표는 PowerPoint shape. 로고 없으면 `"[LOGO NOT PROVIDED - please supply company logo]"`

**Phase 4 Validate 루프:**

```bash
soffice --headless --convert-to pdf presentation.pptx
pdftoppm -jpeg -r 150 presentation.pdf slide
```

검증 체크리스트 (원문):

```
- [ ] Text readable against background?
- [ ] Tables are actual objects (columns aligned, NOT pipe/tab-separated text)?
- [ ] Charts/tables fill designated areas?
- [ ] Bullet formatting consistent within sections?
- [ ] Font sizes match across same-level boxes?
- [ ] No content beyond slide boundaries?
- [ ] No placeholder formatting retained (no large colored boxes with data dumped in)?
- [ ] No text-based "tables" (no `|` or tab separators creating fake columns)?
- [ ] Cross-slide consistency: Same metrics/figures identical across all slides where they appear?
```

Fix cycle: Cycle 1 전체 수정 → Cycle 2 잔여 수정 → Cycle 3이면 이슈 목록·시도 내용·disclaimer와 함께 에스컬레이션. 무한 루프 금지.

**Phase 5:** Final Quality Checklist.

### 3.5 슬라이드 템플릿 (slide-templates.md)

템플릿 분석 3단계: (1) content area 식별 — title/header, subtitle/definition, content boxes, table placeholders, chart/visual, metric callouts, footnote/source bars, logo. (2) 템플릿 관례 — color, font, box styling, bullets, alignment. (3) instruction vs output 구분.

Instruction 식별 원문:

> - **Instruction boxes** — Colored boxes with guidance text (often yellow background, white text)
> - **Placeholder text** — Text in [brackets] indicating what to replace
> - **Example content** — Sample content showing expected format

매핑 워크플로 4단계: Inventory source data → Match to template sections → Identify gaps → Resolve gaps before populating.

갭 유형: Missing data / Extra data / Format mismatches.

#### Market Definition

Typical content areas (원문):
- Segments included in scope (with examples/key players)
- Segments excluded from scope (with examples)
- Market definition text
- Scope rationale/justification

Formatting principle: `Parallel sections (included vs. excluded) should use matching formatting.`

Verification:
- Does every segment have the appropriate symbol (✓ for included, × for excluded)?
- Are key players correctly assigned to segments?
- Does the definition match the source methodology?

#### Market Sizing / TAM

Typical content: Current market size (with year), Growth rate (CAGR with period), Future projection (with target year), Source-by-source breakdown table, Consensus/summary figures, Key takeaways.

Example column headers (원문):

```
Source | [Base Year] Size | CAGR | [Target Year] Projection
```

Formatting principle: `If showing multiple sources, include a consensus/summary row.`

Verification: source figures match originals; consensus calculated not copied from one source; projection years consistent; CAGR projections match manual verify.

#### Competitive Landscape

Typical: Comparison table with competitors as columns; Feature/capability rows; Financial metric rows (revenue, growth, market share); Key observations.

Formatting principle: `Subject company should be visually distinguished from competitors (e.g., bold text, different background color, border, or positioned in rightmost column).`

Verification: all competitors represented; subject distinguished; same time period; ✓/× consistent.

#### Financial Summary

Typical: Key metric callouts; Historical financials table (actuals); Projected financials table (estimates); Growth rates and margins; Optional trend charts.

Example column headers (원문):

```
Metric | FY[Year-2] | FY[Year-1] | FY[Year]A | FY[Year+1]E | FY[Year+2]E
```

Formatting principle: `Clearly distinguish historical (A) from projected (E) data.`

#### Transaction Comparables

Typical: Transaction table (date, target, acquirer, deal value); Valuation multiples (EV/Revenue, EV/EBITDA); Summary statistics (mean, median, high, low); Implied valuation for subject company.

Formatting principle: `Include summary statistics (Mean, Median, High, Low) for multiples.`

Verification: all relevant transactions included; multiples = EV ÷ Metric; summary stats cover all transactions; implied valuation labeled illustrative.

#### Mapping Verification Checklist (원문)

```
### Data Completeness
- [ ] Every template placeholder has mapped source data
- [ ] All source citations are recorded for footnotes
- [ ] No placeholder [brackets] remain unmapped

### Data Accuracy
- [ ] Figures match original source documents exactly
- [ ] Years and time periods are correctly noted
- [ ] Company names are spelled correctly
- [ ] Calculated values (consensus, projections, multiples) verified

### Logical Consistency
- [ ] Included vs. excluded segments are logically coherent
- [ ] Historical data precedes projected data chronologically
- [ ] Comparison data uses consistent time periods
- [ ] Totals and subtotals sum correctly

### Source Attribution
- [ ] Every data point can be traced to a source
- [ ] Source names and publication years recorded
- [ ] Footnote numbers assigned for special notes
```

#### Data-Template Mismatch 처리 (원문, 창작 금지)

Template requires more data than available:
1. Flag the gap explicitly for user review
2. Mark section as "Data not available" with explanation
3. Search for additional sources if appropriate
4. Recommend template adjustment if data doesn't exist

> **Do not:** Fabricate data or make unsupported estimates.

Source has more data: Include most relevant/recent; Summarize or aggregate; Add footnotes; Recommend template expansion if critical.

Format mismatch 변환 목록: Individual figures → Range (min-max); Detailed breakdown → Summary category; Annual figures → CAGR; Absolute values → Percentages; Multiple sources → Consensus.

Terminology: 템플릿 용어를 출력에 사용, 필요 시 footnote.

Template-specific adaptation 4원칙: Follow the template; Match template style; Preserve template structure; Respect template spacing.

> The goal is to populate the template as designed, not to redesign it.

### 3.6 계산 표준 (calculation-standards.md)

역할 문장:

> Source data should already contain calculated figures—use these formulas to verify accuracy.

#### CAGR Projection

```
Future Value = Present Value × (1 + CAGR)^n
```

검증 예시 (원문):

```
Source claims: $22.1bn (2024) at 16.4% CAGR = $55.0bn (2030)
Verify: 22.1 × (1.164)^6 = 22.1 × 2.488 = 55.0 ✓
```

n: `2024→2030 = 6 years`, `2025→2030 = 5 years`.

#### Valuation Multiples

```
EV/Revenue Multiple = Enterprise Value ÷ Revenue
Implied EV = Revenue × Multiple

EV/EBITDA Multiple = Enterprise Value ÷ EBITDA
Implied EV = EBITDA × Multiple
```

예시: `$436m deal at 9.7x revenue multiple on $45m revenue` → `436 ÷ 45 = 9.69 ≈ 9.7x`

#### Market Share

```
Market Share = (Segment Size ÷ Total Market Size) × 100
```

예시: `$18bn` of `$65bn` → `27.7% ≈ 28%`

#### Growth Rate

```
YoY Growth = (Current Year - Prior Year) ÷ Prior Year × 100
CAGR = (End Value ÷ Start Value)^(1/n) - 1
```

#### Consensus Methodology (원문)

**Size Consensus (Range):** Full min-max range across all sources.

```
Sources: $14.9bn, $18.3bn, $21.1bn, $21.2bn, $22.1bn
Consensus: $15-22bn (rounded to nearest $1bn)
```

**CAGR Consensus (Central Cluster):** Exclude outliers (highest and lowest), use central cluster range.

```
Sources: 10.6%, 16.4%, 17.2%, 19.0%, 22.7%
Exclude outliers: 10.6% (low), 22.7% (high)
Central cluster: 16.4%, 17.2%, 19.0%
Consensus: 16-19% or 16-17% (conservative)
```

**Projection Consensus:** Apply consensus CAGR to midpoint of size range.

```
Size range: $15-22bn → Midpoint: $18.5bn
CAGR consensus: 16-17%
At 16%: 18.5 × (1.16)^6 = $45.1bn
At 17%: 18.5 × (1.17)^6 = $47.5bn
Consensus projection: $45-48bn
```

#### Rounding Guidelines (calculation-standards 표)

| Value Type | Typical Rounding | Example |
|------------|------------------|---------|
| Large market sizes ($10bn+) | Nearest $1bn | 18.47 → $18bn |
| Smaller market sizes (<$10bn) | Nearest $0.5bn or $0.1bn | 2.3 → $2.5bn |
| Size ranges | Match precision of sources | 14.9-22.1 → $15-22bn |
| CAGR | Whole % or 0.5% | 16.4% → 16% or 16.5% |
| Market share | Nearest 5% or match source | 27.7% → 25% or 30% |
| Revenue ($m) | 1 decimal | 18.47 → $18.5m |
| Multiples | 1 decimal | 9.688 → 9.7x |

추가 원칙: 반올림이 수치를 실질적으로 바꾸면 안 됨; 일관성이 정밀도보다 중요; 레인지 만들 때 하단은 round down, 상단은 round up; mean/median은 입력 정밀도에 맞춤.

pitch-deck SKILL.md의 Rounding 표는 약간 다르다: Large market `18.5 → $19bn`; Market share `21.4% → 20%`; Revenue($m) 행 없음. 두 표를 섞지 말 것. SKILL.md는 프레젠테이션 관례, calculation-standards는 검증 관례.

#### Calculation Verification Checklist (원문)

```
### Formula Verification
- [ ] Projection uses correct CAGR formula: `PV × (1 + r)^n`
- [ ] Multiples calculated as EV ÷ Metric (not reversed)
- [ ] Growth rates use correct base year in denominator
- [ ] Percentage shares sum to ~100% where applicable

### Input Verification
- [ ] Base year figures match source documents
- [ ] CAGR/growth rates match stated source methodology
- [ ] Time periods (n) calculated correctly
- [ ] Currency and units consistent ($bn vs $m)

### Output Verification
- [ ] Calculated result matches source's stated figure
- [ ] If mismatch, investigate methodology difference
- [ ] Rounding applied consistently
- [ ] Results are plausible (no order-of-magnitude errors)

### Consensus Verification
- [ ] All sources included in range calculations
- [ ] Outlier exclusion methodology documented
- [ ] Midpoint calculations use correct averaging
- [ ] Range bounds represent actual min/max or documented subset
```

#### Red Flags (원문)

- Projection mismatch >5% → 다른 base year, CAGR, rounding
- Multiple mismatch → LTM vs NTM, Revenue vs Net Revenue
- Consensus mismatch → 소스의 데이터 포인트 제외, outlier 처리 차이
- When in doubt: footnote에 discrepancy와 methodology 기록

### 3.7 포맷 표준 (formatting-standards.md)

#### Bullet 구조 예시 (원문 Correct)

```
✓  Consumer mobile and web language learning apps
   (Duolingo, Babbel, Memrise, Busuu)
✓  B2B enterprise language training platforms
   (goFLUENT, Speexx, Learnship)
✓  Online tutoring marketplaces
   (italki, Preply, Cambly)
```

Incorrect는 한 줄 dump.

#### Bullet 기호 (formatting-standards)

| Context | Symbol | Usage |
|---------|--------|-------|
| Included/Positive | ✓ (checkmark) | Items within scope, features present |
| Excluded/Negative | × (cross) | Items outside scope, features absent |
| Neutral list | • (bullet) | General enumeration, commentary |
| Numbered sequence | 1. 2. 3. | Process steps, rankings |
| Sub-bullets | ‣ or – | Secondary points under main bullets |

SKILL.md Quick Reference의 Sub-bullets는 `–`만. formatting-standards는 `‣ or –`. 템플릿 관례에 맞추라고 양쪽 모두 적음.

#### 폰트 크기 (formatting-standards Typical)

| Element | Typical Size (pt) | Style |
|---------|-------------------|-------|
| Slide Title | 40-48 | Bold |
| Subtitle/Definition | 18-22 | Bold |
| Section Headers | 14-16 | Regular |
| Body Text/Bullets | 12-14 | Regular |
| Table Headers | 10-12 | Bold |
| Table Body | 9-11 | Regular |
| Footnotes | 8-9 | Italic |

SKILL.md hierarchy는 Body를 `11-14pt`, Block Label `12-14pt`, Section Header는 Regular 14-16pt. formatting-standards Body는 `12-14pt`. 둘 다 "typical ranges — adjust based on template".

#### Text Density (양쪽 동일)

- Max 6-7 bullets per content box
- Max 2 lines per bullet point
- Parenthetical examples: same line or indented below
- No orphan words

#### Table Creation 규칙 (원문)

> Tables must be actual table objects, NOT text with tab spacing.

Column alignment: Text left; Numeric center or right; Headers match content.

Header row: Bold; Shaded background (template brand color); Contrasting text.

Summary/Total: Bold; Heavier top border; Distinct background shading.

Width: Fill designated section width.

#### Chart/Image

Paste chart ONLY (no source data tables). Resize to fill designated area. Maintain aspect ratio. Axis/legend/data labels legible.

Proper Sizing Workflow: Identify target area → Paste → Immediately resize → Verify readability → Adjust internal elements.

#### Arrows

> Use PowerPoint shape objects, not text characters
> Do not use text-based arrows (→, ⟹) in the final presentation

#### Font Consistency 매칭 표 (원문)

| Box Type | Should Match With |
|----------|-------------------|
| "Segments Included" content | "Segments Excluded" content |
| "Definition" content | "Scope Rationale" content |
| Left column bullets | Right column bullets |
| All label boxes | Each other |
| All section headers | Each other |

Verification: 같은 레벨 박스를 찾아 폰트 비교; 다르면 맞춤; content가 들어가면 큰 쪽, 아니면 작은 쪽을 일관 적용.

### 3.8 XML 참조 (xml-reference.md)

사용 경계 (원문):

**Use python-pptx for:** Creating new tables; Adding text boxes; Inserting images; Most shape creation; Any operation where python-pptx provides an API.

**Use direct XML editing only for:** Modifying properties python-pptx doesn't expose; Fine-tuning cell formatting after python-pptx table creation; Adjusting specific shape properties not in API.

**NEVER use direct XML for:** Creating tables from scratch; Initial shape creation (shape ID collision); Anything you can accomplish via python-pptx.

> Always work on a backup copy — never edit the original file directly.

#### 테이블이 실제 객체인지 검증

python-pptx:

```python
for shape in slide.shapes:
    if shape.has_table:
        print(f"✓ Found table: {len(shape.table.rows)} rows, {len(shape.table.columns)} columns")
```

시각: 컬럼이 내용 길이와 무관하게 정렬; cell border 일관; 선택 시 전체가 단위로 선택.

TEXT 실패 지표: `|` 문자; 길이 따라 컬럼 어긋남; `\t` 스페이싱; 여러 텍스트박스를 표처럼 배열.

> There is no acceptable use case for pipe/tab-separated tabular data in a pitch deck.

기본 테이블 XML 골격 (원문, 색상 `E67E22` 등은 placeholder):

```xml
<a:tbl>
  <a:tblPr firstRow="1" bandRow="1">
    <a:tableStyleId>{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}</a:tableStyleId>
  </a:tblPr>
  <a:tblGrid>
    <a:gridCol w="2000000"/>  <!-- Source column - width in EMUs -->
    <a:gridCol w="1200000"/>  <!-- 2024 Size column -->
    <a:gridCol w="1200000"/>  <!-- CAGR column -->
    <a:gridCol w="1200000"/>  <!-- 2030 Projection column -->
  </a:tblGrid>
</a:tbl>
```

Arrow presets: `rightArrow`, `downArrow`, `chevron`.

Unit conversions (원문):

| Unit | EMUs per unit |
|------|---------------|
| 1 inch | 914400 |
| 1 cm | 360000 |
| 1 point | 12700 |
| 1 pixel (96 DPI) | 9525 |

16:9: Width 12192000 EMUs (13.333 inches), Height 6858000 EMUs (7.5 inches).

Typical positions: Logo (top-right) X=10800000 Y=200000; Title 342583 / 286603; Subtitle 402591 / 1767390; Footer 342583 / 6435334.

### 3.9 MUST / Anti-Patterns / Common Failures

MUST 표 (원문 키): Text Readability; Actual Table Objects; Proper Chart/Table Sizing; Consistent Formatting; Content Boundaries (`Footnote box width: ~32.5cm for 16:9, ~24cm for 4:3`); No Placeholder Formatting.

Anti-Pattern 1: 컬러 instruction box 안에 데이터를 채워 박스를 남김.

| Type | How to identify | What to do |
|------|-----------------|------------|
| Instruction boxes | Bright colors (yellow, orange), guidance text like "Insert X here", white/light text on colored background | DELETE the entire shape, then create new content with production formatting |
| Layout placeholders | Part of slide master/layout, neutral colors matching template theme, "Click to add text" | KEEP the shape, REPLACE the text content only |

Anti-Pattern 2: `|` / tab 텍스트 테이블.

Anti-Pattern 3: placeholder contrast 상속 (white on yellow). Production body는 typically dark text (`#000000` or `#333333`) on white/light.

Placeholder vs Production 표 (원문):

| Element | Placeholder (Input) | Production (Output) |
|---------|---------------------|---------------------|
| Instruction boxes | Colored background, guidance text | Removed or reformatted |
| Data areas | "[Insert data here]" text | Actual data with clean formatting |
| Tables | Description of what table should contain | Actual table object with rows/columns |
| Body text | Light text on colored background | Dark text on light background |

> The placeholder tells you WHAT to create, not HOW to format it.

Common Failures 표 키: Unstructured text dumps; Pipe/tab-separated "tables"; Poor contrast; Tiny pasted charts; Source data pasted with charts; Data dumped into placeholder boxes; Inconsistent bullets; Inconsistent fonts; Content overflow; Missing logo; Remaining `[brackets]`; Text arrows (→, ⟹).

### 3.10 Error Handling (원문)

PDF 변환 실패: `which soffice` → `libreoffice --headless --convert-to pdf` → 수동 export.

소스 불일치 우선순위:
1. Use data explicitly provided in the task files first
2. If using data from other sources (web search, external documents), flag this to the user
3. Document any discrepancies explicitly
4. Add footnote explaining data source choice

계산 불일치:
1. Show your calculation methodology
2. Note the discrepancy and possible causes (different base year, methodology)
3. Present both values if material difference
4. Flag to user for resolution

### 3.11 Footnote / Logo

Footnote 포맷 (원문):

```
Sources: [Source 1] (Year), [Source 2] (Year).
Notes: (1) [First note]; (2) [Second note].
```

예시:

```
Sources: Grand View Research (2024), Mordor Intelligence (2024), Markets and Markets (2023).
Notes: (1) Excludes hardware revenue; (2) Includes both B2B and B2C segments.
```

> All superscript numbers (¹, ², ³) in slide body MUST have corresponding Notes entries.

Logo: task materials의 로고 사용; 없으면 flag; Position typically top-right, consistent size, must not overlap content.

### 3.12 Final Quality Checklist (pitch-deck 원문 전문)

```
### Data Accuracy
- [ ] All figures match original source documents
- [ ] Calculated values verified against formulas (see calculation-standards.md)
- [ ] Years and time periods are correct
- [ ] Company/competitor names spelled correctly
- [ ] Same figures are identical across all slides where they appear

### Content Mapping
- [ ] Every template section populated with appropriate data
- [ ] No `[bracket]` placeholder text remaining
- [ ] All source citations included in footnotes
- [ ] Footnote numbers (¹²³) have corresponding Notes entries

### Formatting
- [ ] Text readable against all backgrounds (sufficient contrast)
- [ ] Tables are actual table objects (NOT pipe/tab-separated text)
- [ ] Charts/tables fill designated areas (no thumbnails)
- [ ] Bullet formatting consistent within each section
- [ ] Font sizes match across same-level boxes
- [ ] No content extends beyond slide boundaries
- [ ] No placeholder boxes retained with data dumped inside
- [ ] No colored instruction boxes in final output

### Template Compliance
- [ ] Placeholder instruction boxes reformatted or removed
- [ ] Formatting matches template style (colors, fonts)
- [ ] Logo present and correctly positioned
- [ ] Production formatting applied (dark text on light background for main content)

### Final Step
- [ ] Recommend user validate in Microsoft PowerPoint before distribution (LibreOffice may render differently)
```

---

## 4. cim-builder

description:

> Structure and draft a Confidential Information Memorandum for sell-side M&A processes. Organizes company information into a professional, investor-ready document with consistent formatting and narrative flow.

Triggers: `"CIM"`, `"confidential information memorandum"`, `"offering memorandum"`, `"info memo"`, `"draft CIM"`, `"sell-side materials"`.

### 4.1 Step 1 입력 요청 목록 (원문)

- Management presentations
- Historical financials (3-5 years)
- Budget/forecast
- Company website and marketing materials
- Customer data (anonymized if needed)
- Org chart
- Prior presentations or board decks
- Quality of earnings report (if available)

### 4.2 CIM 목차 템플릿 (원문)

**I. Executive Summary** (2-3 pages)
- Company overview — what they do, why they win
- Investment highlights (5-7 key selling points)
- Financial summary — headline revenue, EBITDA, growth, margins
- Transaction overview — what's being sold, indicative timeline

**II. Company Overview** (3-5 pages)
- History and founding story
- Mission and value proposition
- Products and services description
- Business model and revenue streams
- Key differentiators and competitive advantages

**III. Industry Overview** (3-5 pages)
- Market size and growth dynamics (TAM/SAM/SOM)
- Key industry trends and tailwinds
- Competitive landscape
- Regulatory environment
- Barriers to entry

**IV. Growth Opportunities** (2-3 pages)
- Organic growth levers (new products, markets, pricing)
- M&A / add-on opportunities
- Operational improvements
- Technology investments
- White space analysis

**V. Customers & Sales** (3-5 pages)
- Customer overview (number, segments, geography)
- Top customer analysis (anonymized if pre-LOI)
- Customer concentration and retention metrics
- Sales process and go-to-market strategy
- Pipeline and backlog

**VI. Operations** (2-3 pages)
- Organizational structure
- Key personnel
- Facilities and geographic footprint
- Technology and systems
- Supply chain / vendor relationships

**VII. Financial Overview** (5-8 pages)
- Historical income statement (3-5 years)
- Revenue analysis — by segment, geography, customer type
- EBITDA bridge and margin analysis
- Balance sheet overview
- Cash flow summary
- Capital expenditure history
- Working capital analysis
- Management forecast / budget (if included)

**VIII. Appendix**
- Detailed financial statements
- Customer list (anonymized)
- Product catalog
- Management bios

페이지 합: 섹션별 범위만 제시. I 2-3 + II 3-5 + III 3-5 + IV 2-3 + V 3-5 + VI 2-3 + VII 5-8. Appendix는 페이지 수 없음. Drafting Guidelines는 총 길이 `40-60 pages`.

### 4.3 Drafting Guidelines (원문)

- **Tone**: Professional, factual, compelling but not hyperbolic
- **Narrative**: Tell a story — why this business is attractive, defensible, and positioned for growth
- **Data-driven**: Support every claim with data. "Strong growth" → "Revenue grew at a 15% CAGR from 2021-2024"
- **Visuals**: Charts and graphs for financial trends, market size, competitive positioning
- **Length**: 40-60 pages total — enough detail to inform first-round bids, not so long buyers won't read it
- **Confidentiality**: Include a disclaimer page. Anonymize sensitive customer data unless seller approves

### 4.4 Output

- Word document (.docx) with professional formatting
- Separate Excel appendix with detailed financials
- Charts and exhibits embedded in the document

### 4.5 Important Notes (QC에 해당하는 원문)

- The CIM is a sales document — lead with strengths, but don't hide material issues (buyers will find them in diligence)
- Investment highlights should address the 3 things every buyer cares about: growth potential, margin profile, and defensibility
- Financial normalization / pro forma adjustments should be clearly labeled and explained
- Work with legal on the confidentiality disclaimer and any regulatory disclosures
- Get management to review for factual accuracy before distribution
- The CIM sets expectations on valuation — make sure the narrative supports the asking price

체크리스트 형식의 QC 섹션은 이 스킬에 없다.

---

## 5. teaser

description:

> Draft anonymous one-page company teasers for sell-side M&A processes. Creates a compelling summary without revealing the company's identity, designed to gauge buyer interest before NDA execution.

Triggers: `"teaser"`, `"blind teaser"`, `"anonymous profile"`, `"one-pager for process"`, `"draft teaser for sell-side"`.

### 5.1 Step 1 입력

- Company description (what they do, how they make money)
- Sector / industry
- Key financial metrics: revenue, EBITDA, growth rate, margins
- Geographic footprint
- Key selling points (3-5 highlights)
- What to anonymize vs. disclose
- Target buyer audience (strategic, financial, or both)

### 5.2 원페이지 구조 템플릿 (원문)

**Header**
- Deal code name (e.g., "Project [Name]")
- Sector descriptor (e.g., "Leading Specialty Industrial Services Platform")
- "Confidential — For Discussion Purposes Only"

**Company Description** (2-3 sentences)
- What the company does, without naming it
- Market position (e.g., "a leading provider of...", "a top-3 player in...")
- Geography (region-level, not city-specific)

**Investment Highlights** (4-6 bullet points)
- Market leadership / positioning
- Revenue quality (recurring %, retention, diversification)
- Growth profile and trajectory
- Margin profile and expansion opportunity
- Management team strength
- Strategic value / synergy potential

**Financial Summary** (table or key metrics)

```
| Metric | Value |
|--------|-------|
| Revenue | $XXM |
| Revenue Growth | XX% CAGR |
| EBITDA | $XXM |
| EBITDA Margin | XX% |
| Employees | XXX |
```

**Transaction Overview** (2-3 sentences)
- What's being offered (100% sale, majority stake, growth equity)
- Indicative timeline
- Contact information for expressions of interest

### 5.3 Anonymization Check (QC)

원문 전체:

- No company name, brand names, or product names
- No specific city (use region: "Southeast US", "Midwest")
- No named customers or partners
- No employee count if it's too distinctive
- Revenue ranges instead of exact figures if the sector is small
- No logos, screenshots, or identifiable imagery

### 5.4 Output

- Word document (.docx) — one page, clean formatting
- PDF version for distribution
- Optional PowerPoint version (single slide)

### 5.5 Important Notes

- The teaser's job is to generate interest, not close a deal — keep it tight and compelling
- Less is more — a good teaser makes buyers want to sign the NDA to learn more
- Use aspirational but accurate language — "leading", "differentiated", "high-growth" are fine if true
- Include enough financial detail to qualify serious buyers but not so much that tire-kickers waste your time
- Always have the client and legal review before distribution
- Track who receives the teaser — it becomes the outreach log for the process

---

## 6. buyer-list

description:

> Build and organize a universe of potential acquirers for sell-side M&A processes. Identifies strategic and financial buyers, assesses fit, and prioritizes outreach.

Triggers: `"buyer list"`, `"buyer universe"`, `"potential acquirers"`, `"who would buy this"`, `"strategic buyers"`, `"financial sponsors"`.

### 6.1 Step 1 Target 이해

- Company description, sector, and business model
- Revenue, EBITDA, and growth profile
- Key assets and capabilities (IP, customer relationships, geographic footprint, team)
- Expected valuation range
- Seller preferences (strategic vs. financial, management continuity, timeline)

### 6.2 Strategic Buyers 카테고리 (원문)

**Direct Competitors** — Rationale: Revenue synergies, eliminate competitor, scale

**Adjacent Players** — Rationale: Product extension, cross-sell, new market entry

**Vertical Integrators** — Rationale: Supply chain control, margin capture, strategic lock-in

**Platform Builders** — Rationale: Tuck-in acquisition, fill capability gap

평가 테이블 템플릿:

```
| Buyer | Sector | Revenue | Strategic Fit | Financial Capacity | M&A Track Record | Likelihood | Priority |
|-------|--------|---------|--------------|-------------------|------------------|------------|----------|
| | | | High/Med/Low | | Active/Moderate/None | | A/B/C |
```

### 6.3 Financial Sponsors

**Platform Investors** — Criteria: Fund size, sector focus, deal size range

**Add-on Buyers** — Identify the specific portfolio company and synergy rationale

**Growth Equity** — Minority vs. majority preference

스폰서 테이블:

```
| Sponsor | Fund Size | Sector Focus | Portfolio Overlap | Recent Activity | Priority |
|---------|-----------|-------------|-------------------|-----------------|----------|
| | | | | | A/B/C |
```

### 6.4 Prioritization 템플릿

- **Tier 1 (5-10)**: Highest strategic fit, proven acquirers, clear rationale — contact first
- **Tier 2 (10-15)**: Good fit but less obvious — contact in second wave
- **Tier 3 (10-20)**: Possible but lower probability — contact if process needs broadening

### 6.5 Contact Mapping (Tier 1)

- Key decision maker (CEO, Corp Dev head, Partner)
- Relationship status (existing relationship, cold outreach, need introduction)
- Known preferences or constraints (size, geography, structure)
- Best approach channel

### 6.6 Output

Excel workbook:
- Strategic buyers tab (sorted by tier)
- Financial sponsors tab (sorted by tier)
- Contact mapping for Tier 1
- Summary statistics (total buyers by tier, by type)

Plus: One-page buyer universe summary for the engagement letter or pitch

### 6.7 Important Notes

- Quality over quantity — a focused list of 30-40 well-researched buyers beats a list of 200 names
- Research recent M&A activity — buyers who just did a deal in the space are either hungry for more or tapped out
- Check for antitrust concerns with direct competitors — flag any that might face regulatory issues
- Financial sponsors: check fund vintage and deployment pace — a fund nearing end of investment period may be more motivated
- Always ask the seller if there are buyers they want included or excluded
- Update the list as the process progresses — move buyers between tiers based on feedback

---

## 7. merger-model

description:

> Build accretion/dilution analysis for M&A transactions. Models pro forma EPS impact, synergy sensitivities, and purchase price allocation.

Triggers: `"merger model"`, `"accretion dilution"`, `"M&A model"`, `"pro forma EPS"`, `"merger consequences"`, `"deal impact analysis"`.

### 7.1 Step 1 입력 템플릿

**Acquirer:** Company name, current share price, shares outstanding; LTM and NTM EPS (GAAP and adjusted); P/E multiple; Pre-tax cost of debt, tax rate; Cash on balance sheet, existing debt.

**Target:** Company name, current share price, shares outstanding (if public); LTM and NTM EPS or net income; Enterprise value or equity value.

**Deal Terms:** Offer price per share (or premium to current); Consideration mix: % cash vs. % stock; New debt raised to fund cash portion; Expected synergies (revenue and cost) and phase-in timeline; Transaction fees and financing costs; Expected close date.

### 7.2 Purchase Price Analysis 테이블

```
| Item | Value |
|------|-------|
| Offer price per share | |
| Premium to current | |
| Equity value | |
| Plus: net debt assumed | |
| Enterprise value | |
| EV / EBITDA implied | |
| P/E implied | |
```

### 7.3 Sources & Uses 테이블

```
| Sources | $ | Uses | $ |
|---------|---|------|---|
| New debt | | Equity purchase price | |
| Cash on hand | | Refinance target debt | |
| New equity issued | | Transaction fees | |
| | | Financing fees | |
| **Total** | | **Total** | |
```

### 7.4 Pro Forma EPS (Accretion / Dilution) — Year 1-3

```
| | Standalone | Pro Forma | Accretion/(Dilution) |
|---|-----------|-----------|---------------------|
| Acquirer net income | | | |
| Target net income | | | |
| Synergies (after tax) | | | |
| Foregone interest on cash (after tax) | | | |
| New debt interest (after tax) | | | |
| Intangible amortization (after tax) | | | |
| Pro forma net income | | | |
| Pro forma shares | | | |
| **Pro forma EPS** | | | |
| **Accretion / (Dilution) %** | | | |
```

### 7.5 Sensitivity

**vs. Synergies and Offer Premium:**

```
| | $0M syn | $25M syn | $50M syn | $75M syn | $100M syn |
|---|---------|----------|----------|----------|-----------|
| 15% premium | | | | | |
| 20% premium | | | | | |
| 25% premium | | | | | |
| 30% premium | | | | | |
```

**vs. Cash/Stock Mix:**

```
| | 100% cash | 75/25 | 50/50 | 25/75 | 100% stock |
|---|-----------|-------|-------|-------|------------|
| Year 1 | | | | | |
| Year 2 | | | | | |
```

### 7.6 Breakeven Synergies

> Calculate the minimum synergies needed for the deal to be EPS-neutral in Year 1.

### 7.7 Output

Excel workbook:
- Assumptions tab
- Sources & uses
- Pro forma income statement
- Accretion/dilution summary
- Sensitivity tables
- Breakeven analysis

Plus: One-page merger consequences summary for pitch book

### 7.8 Important Notes (계산 QC)

- Always show both GAAP and adjusted (cash) EPS where relevant
- Stock deals: use acquirer's current price for exchange ratio, note dilution from new shares
- Include purchase price allocation — goodwill and intangible amortization matter for GAAP EPS
- Synergy phase-in is critical — Year 1 is often only 25-50% of run-rate synergies
- Don't forget foregone interest income on cash used and new interest expense on debt raised
- Tax rate on synergies and interest adjustments should match the acquirer's marginal rate

공식 블록은 pitch-deck `calculation-standards`처럼 별도 파일에 없다. 위 테이블이 모델 골격.

---

## 8. process-letter

description:

> Draft process letters and bid instructions for sell-side M&A processes. Covers initial indication of interest (IOI) instructions, final bid procedures, and management meeting logistics.

Triggers: `"process letter"`, `"bid instructions"`, `"IOI letter"`, `"bid procedures"`, `"final round letter"`, `"management meeting invite"`.

### 8.1 서신 유형 (Step 1)

- **Initial process letter**: Sent with teaser/CIM to outline the process and IOI requirements
- **IOI instructions**: Specific requirements for first-round indications of interest
- **Second round / final bid letter**: Instructions for submitting binding offers after diligence
- **Management meeting invitation**: Logistics for in-person management presentations

### 8.2 Initial Process Letter / IOI 템플릿

**Header:** Date, deal code name; "Confidential"; Addressed to prospective buyer

**Sections:**

1. **Introduction**: Brief overview of the opportunity and the seller's objectives
2. **Process Overview**: Timeline, key dates, expected number of rounds
3. **IOI Requirements**: What to include in the initial indication:
   - Proposed valuation range (enterprise value)
   - Consideration form (cash, stock, earnout, rollover)
   - Financing sources and certainty
   - Key due diligence requirements
   - Indicative timeline to close
   - Any conditions or contingencies
   - Brief description of the buyer and strategic rationale
4. **Submission Details**: Where to send, deadline (date and time), format
5. **Confidentiality Reminder**: Reference to NDA, data room access
6. **Contact Information**: Banker contacts for questions

### 8.3 Final Bid / Second Round — IOI 위에 추가

1. Markup of purchase agreement — Provide the draft SPA/APA and request markup
2. Detailed financing commitments — Committed financing letters required
3. Remaining diligence items
4. Exclusivity terms — Duration and conditions
5. Regulatory analysis — Antitrust filing requirements and timeline
6. Key personnel terms — Employment agreements, compensation, rollover equity
7. Binding vs. non-binding
8. Evaluation criteria — price, certainty, speed, fit

### 8.4 Management Meeting Invitation 템플릿

1. Logistics: Date, time, location (or video link), duration
2. Attendees: Who from the company will present, who from the buyer should attend
3. Agenda: Typical management presentation agenda (overview, financials, operations, growth, Q&A)
4. Ground rules: No recording, confidentiality, questions format
5. Materials: What will be distributed (presentation deck, data room access)
6. Follow-up: Process for submitting additional questions after the meeting

### 8.5 Output

- Word document (.docx) with professional letter formatting
- Firm letterhead placeholder
- Track changes version for client review

### 8.6 Important Notes

- Process letters set the tone for the entire deal — be clear, professional, and organized
- Deadlines should be firm but reasonable — typically 2-3 weeks for IOIs, 3-4 weeks for final bids
- Always include the evaluation criteria — buyers want to know how they'll be judged
- Coordinate with legal on any representations or commitments in the letter
- Client should review and approve before sending — they may want to adjust tone or terms
- Keep a log of who received each letter and when — this becomes the process tracker

---

## 9. deal-tracker

description:

> Track multiple live deals with milestones, deadlines, action items, and status updates. Maintains a deal pipeline view and surfaces upcoming deadlines and overdue items.

Triggers: `"deal tracker"`, `"deal status"`, `"where are we on"`, `"process update"`, `"deal pipeline"`, `"weekly deal review"`.

### 9.1 Deal Setup 필드

- **Deal name / code name**: Project [Name]
- **Client**: Seller or buyer name
- **Deal type**: Sell-side, buy-side, financing, restructuring
- **Role**: Lead advisor, co-advisor, fairness opinion
- **Deal size**: Expected enterprise value
- **Stage**: Pre-mandate → Engaged → Marketing → IOI → Diligence → Final bids → Signing → Close
- **Team**: MD, VP, Associate, Analyst assigned
- **Key dates**: Engagement date, CIM distribution, IOI deadline, management meetings, final bid deadline, target close

### 9.2 Milestone 테이블 템플릿

```
| Milestone | Target Date | Actual Date | Status | Notes |
|-----------|------------|-------------|--------|-------|
| Engagement letter signed | | | | |
| CIM / teaser drafted | | | | |
| Buyer list approved | | | | |
| Teaser distributed | | | | |
| NDA execution | | | | |
| CIM distributed | | | | |
| IOI deadline | | | | |
| IOIs received / reviewed | | | | |
| Shortlist selected | | | | |
| Management meetings | | | | |
| Data room opened | | | | |
| Final bid deadline | | | | |
| Bids received / reviewed | | | | |
| Exclusivity granted | | | | |
| Confirmatory diligence | | | | |
| Purchase agreement signed | | | | |
| Regulatory approval | | | | |
| Close | | | | |
```

Status 값 (원문): `On Track / At Risk / Delayed / Complete`

### 9.3 Action Items 테이블

```
| Action | Deal | Owner | Due Date | Priority | Status |
|--------|------|-------|----------|----------|--------|
| | | | | P0/P1/P2 | Open/Done/Blocked |
```

### 9.4 Weekly Deal Review 템플릿

**For each active deal:**
1. One-line status update
2. Key developments this week
3. Upcoming milestones (next 2 weeks)
4. Blockers or risks
5. Action items for next week

**Pipeline summary:**
- Total active deals by stage
- Deals at risk (missed milestones, stalled processes)
- New mandates / pitches in pipeline
- Expected closings this quarter

### 9.5 Output

Excel:
- Pipeline overview (all deals, one row each)
- Per-deal milestone tracker tabs
- Action item master list
- Weekly review summary

Optional: Markdown summary for email/Slack distribution

### 9.6 Important Notes

- Update the tracker weekly at minimum — stale trackers are worse than no tracker
- Flag deals where milestones are slipping — early warning prevents surprises
- Action items without owners and due dates don't get done — be specific
- The pipeline view should show deal stage, size, and likelihood — useful for revenue forecasting
- Keep notes on buyer/investor feedback — patterns in feedback inform strategy adjustments
- Archive closed/dead deals separately — keep the active view clean

---

## 10. strip-profile (`name: fsi-strip-profile`) + `/one-pager`

description:

> Creates professional investment banking strip profiles (company profiles) for pitch books, deal materials, and client presentations. Generates 1-4 information-dense slides with quadrant layouts, charts, and tables.

커맨드 `one-pager.md`는 이 스킬을 단일 슬라이드 전제로 실행한다.

### 10.1 워크플로 게이트

1. Ask: Single-slide or multi-slide (3-4 slides)? Any specific focus areas?
2. **Only after user confirms**, proceed to research
3. Research 후 아웃라인을 채팅에 출력 (4-5 bullets per item, actual numbers, no placeholders) + style choices (fonts, hex colors, chart types)
4. Get user alignment: `"Does this outline and visual strategy align with your vision?"`
5. **ONE slide at a time**, user approval before next slide

### 10.2 데이터 소스·필수 메트릭 (원문)

Primary: Company filings (BamSEC, SEC EDGAR - "Item 1. Business", MD&A), investor presentations, corporate website

Market data: Bloomberg, FactSet, CapIQ (price, shares, market cap, net debt, EV, ownership)

Estimates: FactSet/CapIQ consensus for NTM revenue, EBITDA, EPS

News: Press releases from last 90 days, M&A activity, guidance changes

Required Metrics:
- Financials: Revenue, EBITDA, margins (%), EPS, FCF for ±3 years
- Valuation: Market Cap, EV, EV/Revenue, EV/EBITDA, P/E multiples
- Growth: YoY growth rates (%)
- Ownership: Top 5 shareholders with % ownership
- Segments: Product mix and/or geographic mix (% breakdown)

Normalization: Convert all amounts to consistent currency; Scale consistently ($mm or $bn throughout, not mixed)

### 10.3 슬라이드별 시각 QC (원문, 매 슬라이드  Mandatory)

변환:

```bash
soffice --headless --convert-to pdf presentation.pptx
pdftoppm -jpeg -r 150 -f 1 -l 1 presentation.pdf slide
```

Visual review:
- Text overlap check
- Text cutoff check
- Chart boundary check — ALL axis labels fully visible
- Quadrant integrity — no bleed

Fix order: (1) Reduce font size 1-2pt (2) Shorten text (3) Adjust positions/container sizes → re-render. Do not proceed until all text fits.

페이지마다 확인할 구체 이슈:
- Table rows colliding with text below them
- Chart x-axis labels cut off at bottom
- Long bullet points wrapping into adjacent content
- Quadrant content bleeding into adjacent quadrants
- Title text overlapping with content below
- Legend text overlapping with chart elements
- Footer/source text colliding with main content

### 10.4 Information Density 규칙

> The #1 goal is MAXIMUM information density. A busy executive should understand the entire company story in 30 seconds. Fill every quadrant to capacity.

Per quadrant targets:
- Company Overview: 6-8 bullets minimum (HQ, founded, employees, CEO/CFO, market cap, ticker, industry, key stat)
- Business & Positioning: 6-8 bullets (revenue drivers, products, market share %, competitive moat, customer count, geographic mix)
- Key Financials: Table with 8-10 rows OR chart + 4-5 key metrics
- Fourth quadrant: 5-7 bullets (ownership %, recent M&A, developments, catalysts)

Packing: Combine related facts; Always include numbers; Add context vs industry avg; Include YoY; Use percentages.

Sparse일 때 추가: Segment %; Geographic splits; Customer concentration; Recent contract wins with $; Guidance vs consensus; Insider ownership %.

> Bullets for ALL body text - NEVER paragraphs.
> Use ONE textbox per section with all bullets inside - do NOT create separate textboxes for each bullet point.

First Page Layout 표의 Overview/Positioning은 `(4-5 bullets)`로도 적혀 있다. 같은 파일의 density 섹션은 `6-8 bullets minimum`. 원문 병기, 해소하지 않음.

### 10.5 4:3 좌표 템플릿 (원문)

```javascript
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_4x3';  // 10" wide × 7.5" tall - MUST USE THIS
```

ASCII 레이아웃:

```
┌─────────────────────────────────────────────────────────────────┐
│ y=0.2  Title: Company Name (Ticker)                             │
├────────────────────────────┬────────────────────────────────────┤
│ y=0.6  Company Overview    │ y=0.6  Business & Positioning      │
│ x=0.3, w=4.7               │ x=5.0, w=4.7                       │
│ h=3.0                      │ h=3.0                              │
├────────────────────────────┼────────────────────────────────────┤
│ y=3.7  Key Financials      │ y=3.7  Stock/Recent Developments   │
│ x=0.3, w=4.7               │ x=5.0, w=4.7                       │
│ h=3.5                      │ h=3.5                              │
└────────────────────────────┴────────────────────────────────────┘
                                                            y=7.5
```

| Quadrant | Position | Content |
|----------|----------|---------|
| 1 | x=0.3, y=0.6, w=4.7, h=3.0 | Company Overview |
| 2 | x=5.0, y=0.6, w=4.7, h=3.0 | Business & Positioning |
| 3 | x=0.3, y=3.7, w=4.7, h=3.5 | Key Financials — **table OR chart, not both** |
| 4 | x=5.0, y=3.7, w=4.7, h=3.5 | Public: 1Y stock + top shareholders. Private: Recent developments or Ownership/M&A history |

Content must stay within bounds — leave 0.3" margin on all sides.

### 10.6 폰트 크기 — USE THESE EXACT VALUES

| Element | Size | Notes |
|---------|------|-------|
| Slide title | 24pt | Bold, company brand color |
| Quadrant headers | 14pt | Bold, with accent bar |
| Body/bullet text | 11pt | Regular weight |
| Table text | 10pt | Use 9pt for dense tables |
| Chart labels | 9pt | Keep labels short |
| Source/footer | 8pt | Bottom of slide |

overflow 시 REDUCE font size by 1pt and re-render.

Title: Title case, left-aligned, not ALL CAPS. Font: Arial (or user/brand). White background only — no boxes, fills, or shading. Company brand colors MUST be researched via web search, not guessed.

Accent bar 예시 색 `E31937`은 코드 샘플. 주석은 `Use company brand color`.

### 10.7 차트 매핑 (원문)

Single-slide: tables for financials; chart only if it replaces the table.

Multi-slide: 2-3 actual PptxGenJS charts. Never placeholder divs or static images.

| Data Type | Chart Type |
|-----------|------------|
| Revenue trends | Line or column (multi-year) |
| Geographic breakdown | Horizontal bar |
| Product mix | Pie with percentages |
| Financial comparison | Column |
| Stock price (1Y daily) | Line |

Subsequent pages: Two-column (40/60 or 50/50), full-slide charts, or sidebar. Suggested flow: Products/Market → Financial Analysis → Leadership.

### 10.8 Financial table 템플릿 (원문 예시 값 포함 — 샘플이지 일반 규칙이 아님)

헤더 행: Metric | FY24 | FY25E

데이터 행 순서: Revenue; YoY Growth; EBITDA; EBITDA Margin; EPS; Market Cap; EV/EBITDA

`slide.addTable()` 사용. Incorrect: plain text prose; HTML tables.

> For projections, use Bear/Base/Bull case scenarios in structured tables.

### 10.9 Quality Checklist (strip-profile 원문)

```
### First Page
- [ ] Title section with company name, ticker, industry
- [ ] Exactly 4 equal quadrants below title
- [ ] All bullets, no paragraphs, 1 line max each
- [ ] Financials in table or chart (not both)

### All Slides
- [ ] No text overflow or cutoff
- [ ] Consistent fonts and colors throughout
- [ ] Charts render correctly
- [ ] No placeholder text - all actual data
- [ ] Consistent scaling ($mm or $bn, not mixed)
- [ ] Sources cited
- [ ] Investment banking quality (GS/MS/JPM standard)

Note: Reference the PPTX skill for PowerPoint file creation.
```

Visual reference: `examples/Nike_Strip_Profile_Example.pptx` — 스킬 디렉터리 목록에는 이 파일이 없다.

### 10.10 `/one-pager` 커맨드 추가분

Step 2: `ls skills/ | grep -E "ppt-template|brand-guidelines"` 후 템플릿 스킬이 있으면 사용자에게 목록을 보여주고 선택. 없으면 branded PPT 파일 경로를 묻거나 clean professional format.

Layout ASCII in command (원문):

```
│ COMPANY OVERVIEW           │ BUSINESS & POSITIONING             │
│ • HQ, Founded, Employees   │ • Core business description        │
│ • CEO, CFO                 │ • Key products/services            │
│ • Market cap, industry     │ • Competitive positioning          │
│ • Key stats                │ • Growth drivers                   │
│ KEY FINANCIALS             │ STOCK PERFORMANCE / OWNERSHIP      │
```

Command Quality Checklist:

```
- [ ] All 4 quadrants populated with real data
- [ ] No placeholder text remaining
- [ ] Company brand colors applied
- [ ] Accent bars on all section headers
- [ ] Financial table properly formatted
- [ ] Sources cited at bottom
- [ ] No text overflow or cutoff
- [ ] Investment banking quality (GS/MS/JPM standard)
```

Deliver: PowerPoint (.pptx); Image preview; Summary of key data points.

one-pager는 single-slide를 확인하라고 한다. 스킬은 1-4 슬라이드를 허용.

---

## 11. datapack-builder

description:

> Build professional financial services data packs from various sources including CIMs, offering memorandums, SEC filings, web search, or MCP servers. ... Do not use for simple financial calculations or working with already-completed data packs.

> Use the xlsx skill for all Excel file creation and manipulation throughout this workflow.

### 11.1 CRITICAL SUCCESS FACTORS

> Every data pack must achieve these standards. Failure on any point makes the deliverable unusable.

**1. Data Accuracy (Zero Tolerance for Errors)**
- Trace every number to source document with page reference
- Use formula-based calculations exclusively (no hardcoded values)
- Cross-check subtotals and totals for internal consistency
- Verify balance sheet balances: Assets = Liabilities + Equity
- Confirm cash flow ties to balance sheet changes

### 11.2 ESSENTIAL RULES 6개 (원문)

**RULE 1: Financial data (measuring money) → Currency format with $**
Triggers: Revenue, Sales, Income, EBITDA, Profit, Loss, Cost, Expense, Cash, Debt, Assets, Liabilities, Equity, Capex
Format: `$#,##0.0` for millions, `$#,##0` for thousands
Negatives: `$(123.0)` NOT `-$123`

**RULE 2: Operational data (counting things) → Number format, NO $**
Triggers: Units, Stores, Locations, Employees, Customers, Square Feet, Properties, Headcount
Format: `#,##0`
Negatives: `(123)` consistent with rest of table

**RULE 3: Percentages (rates and ratios) → Percentage format**
Triggers: Margin, Growth, Rate, Percentage, Yield, Return, Utilization, Occupancy
Format: `0.0%`
Display: `15.0%` NOT `0.15`

**RULE 4: Years → Text format to prevent comma insertion**
Display: `2020, 2021, 2022, 2023A, 2024E` (not `2,024`)

**RULE 5: When context is mixed, each metric gets its own appropriate format**

원문 예시:

```
Segment Analysis, 2022, 2023, 2024
Retail Revenue, $50.0, $55.0, $60.0
  Stores, 100, 110, 120
  Revenue per Store, $0.5, $0.5, $0.5
```

**RULE 6: Use formulas for all calculations → Never hardcode calculated values**

### 11.3 색·폰트 레이어

**Layer 1 Font Colors (MANDATORY from xlsx skill)**
- Blue text (RGB: 0,0,255): ALL hardcoded inputs (historical data, assumptions), NOT normal text
- Black text (RGB: 0,0,0): ALL formulas and calculations
- Green text (RGB: 0,128,0): Links to other sheets

**Layer 2 Fill Colors (Optional)** — only if user requests or enhancing presentation:
- Section headers: Dark blue (RGB: 68,114,196) background with white text
- Sub-headers/column headers: Light blue (RGB: 217,225,242) background with black text
- Input cells: Light green/cream (RGB: 226,239,218) background with blue text
- Calculated cells: White background with black text

Always apply: Bold headers left-aligned; Numbers right-aligned; 2-space indentation for sub-items; Single underline above subtotals; Double underline below final totals; Freeze panes; Minimal borders; Consistent font (typically Calibri or Arial 11pt)

Never include: Borders around every cell; Multiple fonts or font sizes; Charts unless specifically requested; Excessive formatting or decoration

### 11.4 표준 8-탭 구조 (원문, unless explicitly instructed otherwise)

1. Executive Summary
2. Historical Financials (Income Statement)
3. Balance Sheet
4. Cash Flow Statement
5. Operating Metrics
6. Property/Segment Performance (if applicable)
7. Market Analysis
8. Investment Highlights

**Tab 1 Executive Summary:** Company overview (2-3 sentences); Key investment highlights (3-5 bullets); Financial snapshot table (Revenue, EBITDA, Growth for last 3 years + projections); Transaction overview if applicable; Key metrics prominently displayed. Fits on one page.

**Tab 2 Historical Financials:** Revenue breakdown by segment/product; COGS; Gross profit and margin %; OpEx (S&M, R&D, G&A); EBITDA and Adjusted EBITDA; Below-the-line (D&A, interest, taxes); Net income. Years as columns (text). $ millions or $ thousands specified at top.

**Tab 3 Balance Sheet:** Current assets; Long-term assets; Current liabilities; Long-term liabilities; Shareholders' equity. Verify Assets = Liabilities + Equity. Include working capital calculation.

**Tab 4 Cash Flow:** OCF (indirect preferred); Investing; Financing; Net change in cash; Beginning and ending cash. Link to IS and BS. Reconcile NI to OCF.

**Tab 5 Operating Metrics:** NO dollar signs on operational metrics.

**Tab 6 Property/Segment:** if applicable.

**Tab 7 Market Analysis:** Mix of narrative text and tables, cite sources.

**Tab 8 Investment Highlights:** Clear headers, bullet points, concise paragraphs.

### 11.5 6 Phase 워크플로

**Phase 1 Document Processing:** Analyze source; Extract financial statements with page references; Extract operating metrics; Extract market data; Note context and gaps.

**Phase 2 Normalization:** Consistent line item names; Identify one-time charges; Adjusted EBITDA reconciliation; Format detection; Adjustment schedule (what/why/source/dollar impact by year/recurrence risk/reported-to-adjusted calc); Integrity: subtotals, BS balances, CF ties, cross-tab.

**Phase 3 Build Excel:** xlsx skill 필수. 탭 생성 → 포맷 → formulas with row-reference tracking (not hardcoded offsets).

Correct pattern (원문): store row numbers when writing, then reference in formulas. Dictionary `row_refs` for complex models.

Wrong: `f"=B{row-15}/B{row-19}"` magic offsets.

**Phase 4 Scenario Building (if projections included):**
- Management Case — as provided; flag hockey stick inflections
- Base Case (Risk-Adjusted) — revenue growth haircut; moderate margin expansion; increase capex if growth-dependent; add WC if understated; delay synergies
- Downside Case (optional but recommended for LBO) — revenue decline; margin compression; covenant/liquidity; downside protection

Assumptions schedule: key assumptions by scenario; rationale; sensitivity; historical forecast accuracy if available; industry benchmarks.

**Phase 5 QC** — 아래 11.7
**Phase 6 Delivery:** filename `CompanyName_DataPack_YYYY-MM-DD.xlsx`

### 11.6 Normalization Patterns (EBITDA)

1. Restructuring charges — add back if truly non-recurring; Do NOT add back if company restructures every year
2. Stock-based compensation — industry standard add back for PE; consistent across periods
3. Acquisition-related costs — add back transaction fees/integration costs; not ongoing integration investments
4. Legal settlements — add back if isolated; assess recurrence
5. Asset sales or impairments — exclude from operating EBITDA
6. Related party — normalize to market rates; remove personal expenses

Management Case vs Base Case: Base Case는 clearly non-recurring만, recurring "one-time"에 더 높은 검증, speculative 제외. `Recommended for investment decisions`.

Industry adaptations 키 메트릭:
- Technology/SaaS: ARR/MRR, cohort customers, CAC/LTV, churn, NRR, Rule of 40, Magic number
- Manufacturing/Industrial: capacity/utilization, units, inventory turns, GM by product, backlog
- Real Estate/Hospitality: properties/rooms/sqft, occupancy %, ADR, RevPAR, NOI, cap rates %, FF&E reserve
- Healthcare/Services: locations, providers/employees, patients/visits, revenue per visit, payor mix %, same-store growth %

### 11.7 FINAL DELIVERY CHECKLIST (원문 전문에 해당하는 항목)

**Structure:**
- All required tabs present and in logical sequence
- Each tab has clear header and title
- Executive summary is concise (fits on one page)

**Data Accuracy:**
- All numbers trace to source (documents, URLs, or data servers)
- Source references documented for key figures
- All calculations are formula-based (no hardcoded calculated values)
- Subtotals and totals verified
- Balance sheet balances (Assets = Liabilities + Equity)
- No #REF!, #VALUE!, or #DIV/0! errors

**Formatting - Years and Numbers:**
- Years display correctly: 2020, 2021, 2022 (no commas)
- Financial data has $ signs: $50.0, $125.5
- Operational metrics have NO $ signs: 100 stores, 250 employees
- Percentages formatted correctly: 15.0%, 25.5%
- Negatives in parentheses: $(15.0) not -$15.0

**Formatting - Professional Standards:**
- Headers bold and left-aligned
- Numbers right-aligned
- Consistent indentation (2 spaces for sub-items)
- Single underline above subtotals
- Double underline below final totals
- Frozen panes on headers
- Consistent font throughout
- Minimal borders (only for structure)
- Clean, professional appearance throughout

**Content Completeness:**
- Financial statements complete (IS, BS, CF)
- Operating metrics comprehensively captured
- Normalization adjustments documented
- Assumptions clearly stated
- Executive summary clear, concise, and impactful
- Investment highlights compelling
- Market analysis provides context

**Documentation:**
- All normalization adjustments explained
- Every data cell cited from source with comments and links
- Assumptions documented with rationale
- Any data limitations noted
- Filename follows convention: CompanyName_DataPack_YYYY-MM-DD.xlsx

**Final Output:**
- File saved to outputs with proper naming convention
- All quality control checks passed

Phase 5 중간 체크도 동일 축: data accuracy, format consistency, structure completeness, professional presentation, documentation.

datapack-builder에는 대응 커맨드가 없다.

---

## 12. 커맨드 레이어 요약

| 커맨드 | argument-hint | 사용자 입력이 없을 때 |
|---|---|---|
| `/one-pager` | `[company name or ticker]` | "What company would you like to profile?" |
| `/cim` | `[company name]` | ask for target company and available source materials |
| `/teaser` | `[company name]` | ask for the company details to anonymize |
| `/buyer-list` | `[company or sector]` | ask for the target company details |
| `/merger-model` | `[acquirer] acquiring [target]` | ask for deal details |
| `/process-letter` | `[IOI or final bid]` | ask what stage the process is in |
| `/deal-tracker` | `""` | (본문에 fallback 질문 없음 — 스킬 로드만) |

README Commands 표 description은 커맨드 frontmatter description과 대체로 일치.

README example workflows가 생성하는 산출물:
- `/one-pager Target` — Single-slide company profile; 4 quadrants; template margins and branding
- `/cim Target` — Full CIM with executive summary, business overview, financial analysis, market positioning
- `/merger-model Acquirer acquiring Target` — Accretion/dilution; Sources and uses, pro forma financials; Sensitivity on purchase price and synergies

---

## 13. 교차 관찰 (원문에서만)

1. **산출 형식:** pitch-deck·strip-profile = PPTX (+ LibreOffice 이미지 검증). teaser = DOCX + PDF + optional PPT. CIM·process-letter = DOCX. buyer-list·deal-tracker·merger-model·datapack = Excel. teaser·buyer-list·merger-model은 추가 1페이지 요약(PPT 또는 pitch용)을 옵션/추가로 둔다.

2. **명시적 QC 체크리스트가 있는 스킬:** pitch-deck (Phase 4 + Final Quality + calculation verification + mapping verification), strip-profile (First Page / All Slides + per-slide visual list), datapack-builder (Phase 5 + FINAL DELIVERY CHECKLIST), one-pager 커맨드. 나머지 5개 스킬은 "Important Notes"가 QC 역할.

3. **창작 금지:** pitch-deck `Do not: Fabricate data or make unsupported estimates.` datapack은 source trace + formula-only. teaser는 aspirational but accurate, true일 때만 "leading" 등.

4. **익명화:** teaser Step 3 전부. CIM은 customer anonymize if pre-LOI / unless seller approves. process-letter는 NDA·Confidential 헤더.

5. **셀사이드 프로세스 사슬 (각 스킬이 가리키는 산출이 다음 입력):** teaser 배포 → NDA → CIM → IOI (process-letter) → management meetings → data room → final bids → exclusivity → SPA. 이 순서는 deal-tracker milestone 행 순서 그대로다.

6. **숫자 검증 공식이 파일로 있는 곳은 pitch-deck `calculation-standards.md`뿐.** merger-model·datapack은 테이블/규칙으로 검증.

7. **LibreOffice 한계 고지는 pitch-deck에만 필수 문장으로 있다.** strip-profile도 같은 `soffice`/`pdftoppm` 루프를 쓰지만 PPT 재검토 문장은 없다.

8. **이름 불일치:** strip-profile 폴더 vs YAML `name: fsi-strip-profile`. 커맨드는 `skill: "strip-profile"`.

9. **없는 것:** pitch-deck·datapack 커맨드; strip-profile 예제 PPT 실파일; hooks 동작; 한국어 템플릿.

---

## 14. 원문 출처 경로

- `skills/pitch-deck/SKILL.md`
- `skills/pitch-deck/reference/calculation-standards.md`
- `skills/pitch-deck/reference/formatting-standards.md`
- `skills/pitch-deck/reference/slide-templates.md`
- `skills/pitch-deck/reference/xml-reference.md`
- `skills/cim-builder/SKILL.md`
- `skills/teaser/SKILL.md`
- `skills/buyer-list/SKILL.md`
- `skills/merger-model/SKILL.md`
- `skills/process-letter/SKILL.md`
- `skills/deal-tracker/SKILL.md`
- `skills/strip-profile/SKILL.md`
- `skills/datapack-builder/SKILL.md`
- `commands/one-pager.md`, `cim.md`, `teaser.md`, `buyer-list.md`, `merger-model.md`, `process-letter.md`, `deal-tracker.md`
- 매핑 확인: `README.md` (Features/Commands/Skills 표만)
