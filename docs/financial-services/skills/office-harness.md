# Headless CMA Office 하네스 — 스킬 원문 정리

> **범위.** 아래 경로만 읽었다. `financial-services`와 `neos`는 수정하지 않았다.
>
> - `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/pptx-author/`
> - `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/xlsx-author/`
> - `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/ppt-template-creator/`
> - `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/audit-xls/`
> - `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/clean-data-xls/`
> - `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/deck-refresh/`
> - `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/ib-check-deck/` (`SKILL.md`, `references/`, `scripts/extract_numbers.py`)
> - `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/skill-creator/`
> - `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/investment-banking/skills/pitch-deck/` (존재함)
>
> **원칙.** 인용은 원문 그대로. 원문에 없는 메커니즘(예: named range → native PPT 차트 OLE 바인딩, `c:chart` XML 작성 절차)은 만들지 않는다. 원문이 침묵하는 지점은 “원문에 없음”으로 표시한다.

---

## 역할 맵 — 어떤 스킬이 무엇을 하는가

| 스킬 | 경로 | frontmatter `description` (원문) |
|------|------|----------------------------------|
| `pptx-author` | `financial-analysis/skills/pptx-author/SKILL.md` | “Produce a .pptx file on disk (headless) instead of driving a live PowerPoint document — for managed-agent sessions with no open Office app.” |
| `xlsx-author` | `financial-analysis/skills/xlsx-author/SKILL.md` | “Produce a .xlsx file on disk (headless) instead of driving a live Excel workbook — for managed-agent sessions with no open Office app.” |
| `ppt-template-creator` | `financial-analysis/skills/ppt-template-creator/SKILL.md` | “Creates self-contained PPT template SKILLS (not presentations) from user-provided PowerPoint templates. Use ONLY when a user wants to create a reusable skill from their template. For creating actual presentations, use the pptx skill instead.” |
| `audit-xls` | `financial-analysis/skills/audit-xls/SKILL.md` | “Audit a spreadsheet for formula accuracy, errors, and common mistakes. …” |
| `clean-data-xls` | `financial-analysis/skills/clean-data-xls/SKILL.md` | “Clean up messy spreadsheet data — trim whitespace, fix inconsistent casing, convert numbers-stored-as-text, standardize dates, remove duplicates, and flag mixed-type columns. …” |
| `deck-refresh` | `financial-analysis/skills/deck-refresh/SKILL.md` | “Updates a presentation with new numbers — quarterly refreshes, earnings updates, comp rolls, rebased market data. …” |
| `ib-check-deck` | `financial-analysis/skills/ib-check-deck/SKILL.md` | “Investment banking presentation quality checker. Reviews a pitch deck or client-ready presentation for (1) number consistency across slides, (2) data-narrative alignment, (3) language polish against IB standards, (4) visual and formatting QC. …” |
| `skill-creator` | `financial-analysis/skills/skill-creator/SKILL.md` | “Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations.” |
| `pitch-deck` | `investment-banking/skills/pitch-deck/SKILL.md` | “Populates investment banking pitch deck templates with data from source files. Use when: user provides a PowerPoint template to fill in, user has source data (Excel/CSV) to populate into slides, … Not for creating presentations from scratch.” |

**Headless CMA에서 Office 파일을 만드는 핵심 쌍은 `pptx-author` + `xlsx-author`다.** 둘 다 “managed-agent / CMA mode”, “file artifact”, live `mcp__office__*` 대비 fallback이라고 명시한다.

---

## Headless CMA vs Live Office — 분기

### `pptx-author`

> “Use this skill when running **headless** (managed-agent / CMA mode) and you need to deliver a PowerPoint deck as a **file artifact** rather than editing a live document via `mcp__office__powerpoint_*`.”

> “If `mcp__office__powerpoint_*` tools are available (Cowork plugin mode), use those instead — they drive the user's live document with review checkpoints. This skill is the file-producing fallback for headless runs.”

### `xlsx-author`

> “Use this skill when running **headless** (managed-agent / CMA mode) and you need to deliver an Excel workbook as a **file artifact** rather than editing a live workbook via `mcp__office__excel_*`.”

> “If `mcp__office__excel_*` tools are available (Cowork plugin mode), use those instead — they drive the user's live workbook with review checkpoints. This skill is the file-producing fallback for headless runs.”

### `clean-data-xls` 환경 분기

> “**If running inside Excel (Office Add-in / Office JS):** Use Office JS directly (`Excel.run(async (context) => {...})`). Read via `range.values`, write helper-column formulas via `range.formulas = [["=TRIM(A2)"]]`.”

> “**If operating on a standalone .xlsx file:** Use Python/openpyxl.”

### `deck-refresh` / `ib-check-deck` 환경 분기

`deck-refresh`:

> “This skill works in both the PowerPoint add-in and chat. Identify which you're in before starting — the edit mechanism differs, the intent doesn't:”
>
> - “**Add-in** — the deck is open live; edit text runs, table cells, and chart data directly.”
> - “**Chat** — the deck is an uploaded file; edit it by regenerating the affected slides with the new values and writing the result back.”

`ib-check-deck`:

> “This skill works in both the PowerPoint add-in and chat.”
>
> - “**Add-in** — read from the live open deck.”
> - “**Chat** — read from the uploaded `.pptx` file.”
>
> “This is read-and-report only — no edits — so the workflow is identical in both.”

---

## 산출물 계약 (Output contract)

`pptx-author`와 `xlsx-author`가 동일한 디스크 계약을 쓴다.

`pptx-author`:

> “- Write to `./out/<name>.pptx`. Create `./out/` if it does not exist.”
> “- Return the relative path in your final message so the orchestration layer can collect it.”

`xlsx-author`:

> “- Write to `./out/<name>.xlsx`. Create `./out/` if it does not exist.”
> “- Return the relative path in your final message so the orchestration layer can collect it.”

구현 방식도 동일 패턴이다. “Write a short Python script and run it with Bash.” PPT는 `python-pptx`, XLSX는 `openpyxl`.

`pptx-author` 예시:

```python
from pptx import Presentation
from pptx.util import Inches, Pt

prs = Presentation("./templates/firm-template.pptx")  # if a template is provided
# or: prs = Presentation()

slide = prs.slides.add_slide(prs.slide_layouts[5])    # title-only
slide.shapes.title.text = "Valuation Summary"
# ... add tables / charts / text boxes ...

prs.save("./out/pitch-<target>.pptx")
```

`xlsx-author` 예시:

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

`pptx-author` 추가 제약:

> “**No external sends.** This skill writes a file; it never emails or uploads.”

---

## XML / OOXML 접근

원문에서 OOXML을 **직접 다루는 곳은 `pitch-deck/reference/xml-reference.md`가 유일하다.** `pptx-author`는 `python-pptx` API만 지시하고 XML을 말하지 않는다. `xlsx-author`는 `openpyxl`만 지시하고 OOXML을 말하지 않는다. `skill-creator`는 예시로 “For OOXML details: See [OOXML.md](OOXML.md)”를 들지만, 이 스킬 폴더에 `OOXML.md`는 없다.

### python-pptx vs 직접 XML — 언제 무엇을 쓰는가

`pitch-deck/reference/xml-reference.md`:

> “This file contains XML patterns for programmatic PowerPoint editing. Use these patterns when working directly with OOXML format.”

> “**Use python-pptx for:**
> - Creating new tables (handles cell structure and relationships automatically)
> - Adding text boxes
> - Inserting images
> - Most shape creation
> - Any operation where python-pptx provides an API”

> “**Use direct XML editing only for:**
> - Modifying properties of existing elements that python-pptx doesn't expose
> - Fine-tuning cell formatting after table creation via python-pptx
> - Adjusting specific shape properties not available via the python-pptx API”

> “**NEVER use direct XML for:**
> - Creating tables from scratch (relationship management is error-prone and will likely corrupt the file)
> - Initial shape creation (shape ID collision risk)
> - Anything you can accomplish via python-pptx”

> “The XML patterns in this file are for **reference and targeted modifications**, not wholesale element construction.”

### XML 편집 위험

> “Direct XML editing can corrupt PowerPoint files if not done carefully:
> - PowerPoint XML has interdependencies (relationship files, content types)
> - Invalid XML or missing relationships can corrupt the entire file
> - Shape IDs must be unique across each slide”

> “**Always work on a backup copy** — never edit the original file directly.”

`pitch-deck/SKILL.md` Phase 1도 백업을 강제한다:

> “**Create backup** of original template before any modifications — copy to `[filename]_backup.pptx`. Direct XML editing or unexpected errors can corrupt files.”

### xml-reference.md가 실제로 제공하는 XML 패턴

목차 원문:

> “- [Table Implementation](#table-implementation)
> - [Arrow Shapes](#arrow-shapes)
> - [Text Boxes](#text-boxes)
> - [Shapes with Fill](#shapes-with-fill)
> - [Image Insertion](#image-insertion)
> - [Connector Lines](#connector-lines)
> - [Unit Conversions](#unit-conversions)”

**차트(`c:chart`, `c:ser`, chart part, chart relationships) XML 패턴은 이 파일에 없다.** 이미지 삽입만 relationship을 예시한다 (`ppt/slides/_rels/slideN.xml.rels`의 `rIdLogo`).

테이블 골격 인용:

```xml
<a:tbl>
  <a:tblPr firstRow="1" bandRow="1">
    <a:tableStyleId>{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}</a:tableStyleId>
  </a:tblPr>
  <a:tblGrid>
    <a:gridCol w="2000000"/>  <!-- Source column - width in EMUs -->
    ...
  </a:tblGrid>
</a:tbl>
```

이미지 relationship 인용:

```xml
<Relationship Id="rIdLogo"
  Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
  Target="../media/logo.png"/>
```

### 단위 (EMU)

`xml-reference.md`:

| Unit | EMUs per unit |
|------|---------------|
| 1 inch | 914400 |
| 1 cm | 360000 |
| 1 point | 12700 |
| 1 pixel (96 DPI) | 9525 |

> “### Common Slide Dimensions (16:9)
> - Width: 12192000 EMUs (13.333 inches)
> - Height: 6858000 EMUs (7.5 inches)”

`ppt-template-creator`도 같은 환산 상수를 쓴다:

> `print(f"Dimensions: {prs.slide_width/914400:.2f}\" x {prs.slide_height/914400:.2f}\"")`
>
> `left = ph.left / 914400`

### 표는 반드시 실제 table object

`pitch-deck/SKILL.md`:

> “Create tables as actual table objects (NEVER use pipe/tab-separated text)”

`xml-reference.md` 검증:

```python
for shape in slide.shapes:
    if shape.has_table:
        print(f"✓ Found table: {len(shape.table.rows)} rows, {len(shape.table.columns)} columns")
```

> “Text-based "tables" cannot be edited by the recipient, will misalign when fonts change, and signal amateur work. There is no acceptable use case for pipe/tab-separated tabular data in a pitch deck.”

### python-pptx의 내부 XML 조작 (`ppt-template-creator`)

생성 스킬 템플릿이 기존 슬라이드를 지울 때 `python-pptx` private API로 slide ID list / relationship을 건드린다:

```python
# DELETE all existing slides first
while len(prs.slides) > 0:
    rId = prs.slides._sldIdLst[0].rId
    prs.part.drop_rel(rId)
    del prs.slides._sldIdLst[0]
```

원문은 이 코드를 “Generated SKILL.md Template”에 넣으라고 한다. OOXML 패키지 relationship을 직접 설명하지는 않는다.

### LibreOffice는 검증용이지 정확한 렌더러가 아니다

`pitch-deck/SKILL.md`:

> “**LibreOffice is used for validation but DOES NOT render PowerPoint files accurately.** It will mangle fonts, gradients, shape positions, text wrapping, and some table formatting.”

> “A slide that passes visual validation in LibreOffice may still have issues in Microsoft PowerPoint. The validation loop catches structural issues (missing content, broken tables, placeholder formatting retained) but **cannot** catch font substitution, subtle alignment shifts, or gradient problems.”

필수 고지:

> “This file was validated using LibreOffice. Please review in Microsoft PowerPoint before distribution, as rendering differences may exist.”

검증 루프 명령:

```bash
soffice --headless --convert-to pdf presentation.pptx
pdftoppm -jpeg -r 150 presentation.pdf slide
```

실패 시:

> “1. Check LibreOffice is installed: `which soffice`
> 2. Try alternative: `libreoffice --headless --convert-to pdf presentation.pptx`
> 3. If still failing, open in PowerPoint/LibreOffice manually and export”

---

## Named ranges

**이 목록의 스킬 중 named range를 명시한 곳은 `xlsx-author` 한 줄뿐이다.**

`xlsx-author` “Conventions (mirror `audit-xls`)”:

> “- **Named ranges** for any value referenced from a deck or memo.”

같은 섹션의 나머지 규약:

> “- **Blue / black / green.** Blue = hardcoded input, black = formula, green = link to another sheet/file.”
> “- **No hardcodes in calc cells.** Every calculation cell is a formula; every input lives on an Inputs tab.”
> “- **Balance checks.** Include a Checks tab that ties (BS balances, CF ties to cash, etc.) and surfaces TRUE/FALSE.”
> “- **One model per file.** Do not append to an existing workbook unless explicitly asked.”

`audit-xls`는 “Color convention”과 “Input/formula separation”을 검사하지만, **named range를 검사 항목으로 적지 않는다.**

`pptx-author`의 숫자 추적 규약 (named range가 아니라 시트/셀 각주):

> “**Every number traces to the model.** If a figure comes from `./out/model.xlsx`, footnote the sheet and cell.”

`pitch-deck`의 데이터 추출은 Excel/CSV를 읽고 숫자를 슬라이드에 넣는 매핑이지, named range 바인딩이 아니다.

**원문에 없는 것:** named range 생성 API (`wb.defined_names`), Name Manager 조작, named range를 PPT 차트 시리즈에 연결하는 절차.

---

## Chart binding

원문은 “chart binding”이라는 용어를 쓰지 않는다. 차트 관련 지시는 스킬마다 다르다. **Excel named range ↔ PowerPoint native chart 링크를 설명하는 문장은 없다.**

### 1) Headless 생성 (`pptx-author`) — PNG 임베드 선호

> “**Charts**: prefer embedding a PNG rendered from the model over native pptx charts when fidelity matters.”

`python-pptx` 주석만 있다: `# ... add tables / charts / text boxes ...`. native chart 생성/바인딩 코드는 없다.

### 2) 기존 덱 숫자 교체 (`deck-refresh`) — 시리즈 값을 직접 갱신

숫자가 숨는 위치:

> “- Chart data labels and axis labels
> - Chart source data — the numbers driving the bars, not just the labels on them”

실행 표준:

> “**Chart data** — update the underlying series values so the bars/lines actually move. Editing just the label without the data leaves a chart that lies.”

환경별 메커니즘:

> “**Add-in** — edit the specific run, cell, or chart series directly in the live deck.”
> “**Chat** — regenerate the affected slide with the new value in place, preserving every other element exactly as it was, and write it back to the file.”

### 3) 템플릿 채우기 (`pitch-deck` + `formatting-standards.md`) — Excel에서 붙여넣기

> “### Pasting Charts from Excel
>
> When pasting charts from Excel:
>
> 1. **Paste the chart ONLY** - do not include source data tables
> 2. **Resize to fill the designated area** - charts should not appear as tiny thumbnails
> 3. **Maintain aspect ratio** - do not distort the chart
> 4. **Verify readability** - axis labels, legends, data labels must be legible”

MUST:

> “**Proper Chart/Table Sizing** | Pasted visuals MUST fill designated area.”

화살표는 차트 바인딩이 아니라 shape object다:

> “Use PowerPoint shape objects, not text characters”
> “Do not use text-based arrows (→, ⟹) in the final presentation”

`xml-reference.md`는 `rightArrow` / `downArrow` / `chevron` preset geometry XML을 주지만 **chart XML은 주지 않는다.**

### 4) QC (`ib-check-deck`) — 차트는 검증 대상

> “Trend statements ("declining margins") → does the chart actually go that direction?”

> “You're looking for: missing chart source citations, missing axis labels, …”

> “Visual verification catches overlaps, overflow, and contrast issues that don't show up in text extraction. Don't skip it — a chart with no source citation looks the same as a properly sourced one in the text dump.”

### 정리 (원문 한계)

| 질문 | 원문 답 |
|------|---------|
| Headless에서 native pptx chart를 만들까? | 선호하지 않음. PNG embed. |
| 차트 데이터를 어떻게 바꾸나? | Add-in: series 직접 수정. Chat: 슬라이드 재생성. 라벨만 바꾸면 “a chart that lies”. |
| Excel 차트를 덱에 넣는 방법? | “Paste the chart ONLY”, 리사이즈, aspect ratio. |
| OOXML `c:chart` 작성법? | **없음.** |
| Named range로 차트 연결? | **없음.** |

---

## QC (품질 관리)

QC는 네 갈래다. (1) 모델/시트 감사 `audit-xls`, (2) 데이터 정리 `clean-data-xls`, (3) 덱 숫자 일관성·언어·비주얼 `ib-check-deck`, (4) 템플릿 채움 후 시각 루프 `pitch-deck` Phase 4–5. `deck-refresh`는 편집 후 visual verification을 한 번 더 돌린다.

### 1. `audit-xls` — 스프레드시트 / 모델 무결성

스코프를 먼저 받는다: selection / sheet / model.

> “The **model** scope is the deepest — use it for DCF, LBO, 3-statement, merger, comps, or any integrated financial model before sending to a client or IC.”

전 스코프 공식 검사:

| Check | What to look for |
|---|---|
| Formula errors | `#REF!`, `#VALUE!`, `#N/A`, `#DIV/0!`, `#NAME?` |
| Hardcodes inside formulas | `=A1*1.05` — the `1.05` should be a cell reference |
| Inconsistent formulas | A formula that breaks the pattern of its neighbors |
| Off-by-one ranges | `SUM`/`AVERAGE` that misses the first or last row |
| Pasted-over formulas | Cell that looks like a formula but is actually a hardcoded value |
| Circular references | Intentional or accidental |
| Broken cross-sheet links | References to cells that moved or were deleted |
| Unit/scale mismatches | Thousands mixed with millions, % stored as whole numbers |
| Hidden rows/tabs | Could contain overrides or stale calculations |

모델 스코프 구조:

> “Input/formula separation”, “Color convention: Blue=input, black=formula, green=link”, “Tab flow (Assumptions → IS → BS → CF → Valuation)”, “Date headers”, “Units”.

BS:

> “Total Assets = Total Liabilities + Equity (every period)”
> “If BS doesn't balance, **quantify the gap per period and trace where it breaks** — nothing else matters until this is fixed.”

CF:

> “CF Ending Cash = BS Cash (every period)”
> “CFO + CFI + CFF = Δ Cash”

보고:

> “**Don't change anything without asking** — report first, fix on request.”

Severity: Critical / Warning / Info.

노트:

> “**Hardcoded overrides are the #1 source of silent bugs** — search aggressively”
> “If the model uses VBA macros, note any macro-driven calculations that can't be audited from formulas alone”

### 2. `clean-data-xls` — 분석 전 데이터 준비

이슈 표: Whitespace, Casing, Number-as-text, Dates, Duplicates, Blanks, Mixed types, Encoding, Errors (`#REF!`, `#N/A`, `#VALUE!`, `#DIV/0!`).

핵심 원칙:

> “**Prefer formulas over hardcoded cleaned values** — where the cleaned output can be expressed as a formula (e.g. `=TRIM(A2)`, `=VALUE(SUBSTITUTE(B2,"$",""))`, `=UPPER(C2)`, `=DATEVALUE(D2)`), write the formula in an adjacent helper column rather than computing the result in Python and overwriting the original. This keeps the transformation transparent and auditable.”

> “For destructive operations (removing duplicates, filling blanks, overwriting originals), confirm with the user first”

> “After each category of fix (whitespace → casing → number conversion → dates → dedup), show the user a sample of what changed and get confirmation before moving to the next category”

### 3. `ib-check-deck` — 덱 QC 4차원

> “Perform comprehensive QC on the presentation across four dimensions. Read every slide, then report findings.”

1. Number consistency
2. Data-narrative alignment
3. Language polish
4. Visual and formatting QC

추출 포맷:

```
## Slide 1
[slide 1 text content]
```

스크립트:

```bash
python scripts/extract_numbers.py /tmp/deck_content.md --check
```

> “It normalizes units ($500M vs $500MM vs $500,000,000 → same number), categorizes values (revenue, EBITDA, multiples, margins), and flags when the same metric category shows conflicting values on different slides.”

스크립트 밖 추가 검증:

> “- Calculations are correct (totals sum, percentages add up, growth rates match the endpoints)
> - Unit style is consistent — the deck should pick one of $M or $MM and stick with it
> - Time periods are aligned — FY vs LTM vs quarterly, explicitly labeled”

Severity:

> “- **Critical** — number mismatches, factual errors, data contradicting narrative. These block client delivery.
> - **Important** — language, missing sources, terminology drift. Should fix.
> - **Minor** — font sizes, spacing, date formats. Polish.”

> “Lead with criticals. If there aren't any, say so explicitly — "no number inconsistencies found" is a finding, not an absence of one.”

#### `extract_numbers.py` 동작 (원문 코드)

- `NumberInstance`: `value`, `normalized`, `unit`, `slide`, `context`, `line_number`, `category`
- 단위 배수: `T` 1e12, `B`/`bn`/`billion` 1e9, `M`/`mm`/`mn`/`million` 1e6, `K`/`k`/`thousand` 1e3
- 카테고리: revenue, ebitda, ebitda_margin, margin, growth, multiple, valuation, percentage, other
- 슬라이드 마커: `^#+\s*Slide\s*(\d+)` 또는 `^<!-- Slide (\d+)`
- 연도(1900–2099)는 단위/통화 없으면 skip
- `find_inconsistencies`: 카테고리별로 정규화 값 5% 허용오차로 그룹. 가장 큰 그룹을 expected, 나머지를 found. `revenue`/`ebitda`/`valuation`은 severity `high`, 그 외 `medium`

#### 리포트 포맷 (`references/report-format.md`)

섹션: Summary → Critical (Number Consistency, Data-Narrative Alignment) → Important (Language Polish) → Minor (Formatting) → Final Checklist.

Final Checklist 원문:

> “- [ ] Numbers reconciled
> - [ ] Narrative matches data
> - [ ] Language meets IB standards
> - [ ] Charts sourced
> - [ ] Formatting consistent”

언어 치환은 `references/ib-terminology.md` (예: “a lot of growth” → “significant growth” or “X% growth”). 금지: contractions, exclamation points, first-person, 근거 없는 superlatives, vague quantifiers.

### 4. `pitch-deck` Phase 4–5 — Validate → Fix → Repeat

시각 체크리스트 원문:

> “- [ ] Text readable against background?
> - [ ] Tables are actual objects (columns aligned, NOT pipe/tab-separated text)?
> - [ ] Charts/tables fill designated areas?
> - [ ] Bullet formatting consistent within sections?
> - [ ] Font sizes match across same-level boxes?
> - [ ] No content beyond slide boundaries?
> - [ ] **No placeholder formatting retained** (no large colored boxes with data dumped in)?
> - [ ] **No text-based "tables"** (no `|` or tab separators creating fake columns)?
> - [ ] **Cross-slide consistency**: Same metrics/figures identical across all slides where they appear?”

사이클: 1 수정+재검증, 2 남은 이슈 수정+재검증, 3이면 escalate.

> “Do not continue cycling indefinitely. Some issues (font rendering, complex shape alignment) may require manual intervention in PowerPoint.”

Phase 5 Final Quality Checklist는 Data Accuracy / Content Mapping / Formatting / Template Compliance / “Recommend user validate in Microsoft PowerPoint before distribution”.

계산 검증은 `reference/calculation-standards.md`: CAGR `PV × (1 + r)^n`, EV/Revenue, EV/EBITDA, Market Share, YoY, consensus (size는 min-max, CAGR는 outlier 제외 central cluster). Red flag: projection mismatch >5%.

### 5. `deck-refresh` 편집 후 QC

> “Run standard visual verification checks on every edited slide. A number that got longer (`$485M` → `$1,205M`) might now overflow its text box or push a table column width. Catch it before the user does.”

승인 게이트:

> “This is a four-phase process and the third phase is an approval gate. Don't edit until the user has seen the plan.”

파생 숫자는 침묵 수정 금지:

> “Flag it; don't silently fix it, don't silently leave it.”

스타일은 덱이 진실:

> “if the deck uses `$MM` and the user's mapping says `$M`, match the deck, not the mapping. Values change; style stays.”

> “The deck's existing style is correct by definition; you're a surgeon, not a renovator.”

---

## Template teaching — 템플릿을 스킬로 가르친다

세 층이다.

1. **`skill-creator`**: 스킬 일반 해부학, progressive disclosure, init/package/validate.
2. **`ppt-template-creator`**: 사용자 `.pptx`/`.potx`를 **재사용 가능한 PPT 템플릿 스킬**로 변환. “This skill creates SKILLS, not presentations.”
3. **`pitch-deck`**: 이미 있는 IB 템플릿에 소스 데이터를 채운다. “Not for creating presentations from scratch.”

Headless 생성 시 `pptx-author`는 마운트된 펌 템플릿을 쓴다:

> “**Use the firm template** when one is mounted at `./templates/`; otherwise default layouts.”
> `prs = Presentation("./templates/firm-template.pptx")  # if a template is provided`

### `skill-creator` — 스킬을 어떻게 가르치나

Anatomy 원문:

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter metadata (required)
│   │   ├── name: (required)
│   │   └── description: (required)
│   └── Markdown instructions (required)
└── Bundled Resources (optional)
    ├── scripts/          - Executable code (Python/Bash/etc.)
    ├── references/       - Documentation intended to be loaded into context as needed
    └── assets/           - Files used in output (templates, icons, fonts, etc.)
```

Progressive disclosure:

> “1. **Metadata (name + description)** - Always in context (~100 words)
> 2. **SKILL.md body** - When skill triggers (<5k words)
> 3. **Bundled resources** - As needed by Claude (Unlimited because scripts can be executed without loading into context window)”

> “Keep SKILL.md body to the essentials and under 500 lines”

Freedom 수준:

> “**High freedom** (text-based instructions)” / “**Medium freedom** (pseudocode or scripts with parameters)” / “**Low freedom** (specific scripts, few parameters)”
>
> “Think of Claude as exploring a path: a narrow bridge with cliffs needs specific guardrails (low freedom), while an open field allows many routes (high freedom).”

`description`이 트리거다:

> “These are the only fields that Claude reads to determine when the skill gets used”
> “Include all "when to use" information here - Not in the body.”

Assets 예:

> “`assets/slides.pptx` for PowerPoint templates”

생성 프로세스: Understand examples → Plan scripts/references/assets → `scripts/init_skill.py <skill-name> --path <output-directory>` → Edit → `scripts/package_skill.py <path/to/skill-folder>` → Iterate.

패키징:

> “The .skill file is a zip file with a .skill extension.”

`quick_validate.py` 허용 frontmatter 키: `name`, `description`, `license`, `allowed-tools`, `metadata`. name은 hyphen-case, 최대 64자. description은 `<>` 금지, 최대 1024자.

출력 패턴 (`references/output-patterns.md`): Template Pattern (strict vs flexible), Examples Pattern (input/output pairs).

워크플로 (`references/workflows.md`): Sequential steps, Conditional branching.

DOCX 예시 안에 OOXML 언급 (이 스킬의 실제 OOXML 가이드가 아님):

> “For simple edits, modify the XML directly.
> **For tracked changes**: See [REDLINING.md](REDLINING.md)
> **For OOXML details**: See [OOXML.md](OOXML.md)”

넣지 말 것: README.md, INSTALLATION_GUIDE.md, QUICK_REFERENCE.md, CHANGELOG.md 등 “extraneous documentation”.

### `ppt-template-creator` — 템플릿을 측정해서 스킬에 각인

워크플로 원문:

> “1. **User provides template** (.pptx or .potx)
> 2. **Analyze template** - extract layouts, placeholders, dimensions
> 3. **Initialize skill** - use the `skill-creator` skill to set up the skill structure
> 4. **Add template** - copy .pptx to `assets/template.pptx`
> 5. **Write SKILL.md** - follow template below with PPT-specific details
> 6. **Create example** - generate sample presentation to validate
> 7. **Package** - use the `skill-creator` skill to package into a .skill file”

생성물:

> “- `assets/template.pptx` - the template file
> - `SKILL.md` - complete instructions (no reference to this meta skill needed)”

> “The generated SKILL.md must be **self-contained** with all instructions embedded.”

분석 핵심:

> “**CRITICAL: Extract precise placeholder positions** - this determines content area boundaries.”

측정 항목: Title position, Subtitle/description, Footer placeholders, Content area (“The space BETWEEN subtitle and footer”).

OBJECT placeholder (type `7`)가 true content start:

> “The content area does NOT always start immediately after the subtitle placeholder. Many templates have a visual border, line, or reserved space between the subtitle and content area.”
>
> “Look at Layout 2 or similar "content" layouts that have an OBJECT placeholder - this placeholder's `y` position indicates where content should actually start.”

예시:

> “- Subtitle ending at y=1.38"
> - But OBJECT placeholder starting at y=1.90"
> - The gap (0.52") is reserved for a border/line - **do not place content there**”

생성 스킬에 넣을 것:

- Layout index 표
- Placeholder Mapping: idx, Type, Position, Use
- Content Area Boundaries (left, top, width, height; 4-quadrant이면 열/행 좌표)
- 채움 코드: TITLE type `1`, `paragraph.level`로 hierarchy. “Do NOT add manual bullet characters - slide master handles formatting.”
- 기존 슬라이드 전부 삭제 후 `add_slide`

PPT-specific rules:

> “1. **Template in assets/** - always bundle the .pptx file
> 2. **Self-contained SKILL.md** - all instructions embedded, no external references
> 3. **No manual bullets** - use `paragraph.level` for hierarchy
> 4. **Delete slides first** - always clear existing slides before adding new ones
> 5. **Document placeholders by idx** - placeholder idx values are template-specific”

### `pitch-deck` — 기존 템플릿을 “가르친” 뒤 채운다

시작 시 네 reference를 모두 읽는다:

| File | Purpose (원문) |
|------|----------------|
| `formatting-standards.md` | “Text, bullets, tables, charts, alignment” |
| `slide-templates.md` | “Content mapping guidance for common slide types” |
| `xml-reference.md` | “PowerPoint XML patterns for tables, shapes, arrows” |
| `calculation-standards.md` | “Financial formulas for verification (CAGR, consensus)” |

결정 트리:

> “Populating empty template with source data?” → Template Population Workflow
> “Editing existing populated slides?” → Extract, modify, revalidate
> “Fixing formatting issues?” → Common Failures table

Placeholder vs production (핵심 안티패턴):

> “The placeholder tells you WHAT to create, not HOW to format it.”

두 종류의 placeholder:

| Type | How to identify | What to do |
|------|-----------------|------------|
| **Instruction boxes** | “Bright colors (yellow, orange), contains guidance text like "Insert X here", white/light text on colored background” | “DELETE the entire shape, then create new content with production formatting” |
| **Layout placeholders** | “Part of slide master/layout, neutral colors matching template theme, "Click to add text"” | “KEEP the shape, REPLACE the text content only” |

`slide-templates.md` 분석 3단계: Identify All Content Areas → Note Template Conventions → Identify Instruction vs. Output Areas. 그다음 source inventory → match → gaps → resolve. 데이터 날조 금지:

> “**Do not:** Fabricate data or make unsupported estimates.”

공통 슬라이드 타입: Market Definition, Market Sizing/TAM, Competitive Landscape, Financial Summary, Transaction Comparables.

용어는 템플릿을 따른다:

> “Use template terminology in output”
> “The goal is to populate the template as designed, not to redesign it.”

`formatting-standards.md` Template Adaptation:

> “1. **Colors**: Use the template's brand colors rather than prescribing specific colors
> 2. **Fonts**: Use the template's font family
> 3. **Spacing**: Match the template's existing spacing conventions
> 4. **Layout**: Follow the template's section structure”

불변 원칙:

> “- Text must be readable against its background
> - Tables must be actual table objects
> - Content should fill available space appropriately
> - Formatting should be consistent across parallel elements
> - Charts/images should be properly sized”

---

## 스킬 간 연결 (원문이 가리키는 방향만)

```
skill-creator
    ↑ init / package / progressive disclosure
ppt-template-creator  --분석(EMU, placeholder idx, OBJECT y)-->  [company]-ppt-template skill
                                                              assets/template.pptx + self-contained SKILL.md

pptx-author  (headless CMA)
    python-pptx + ./templates/firm-template.pptx → ./out/<name>.pptx
    “mirror the live-Office pitch-deck skill”
    charts: PNG from model when fidelity matters
    numbers: footnote sheet+cell from ./out/model.xlsx

xlsx-author  (headless CMA)
    openpyxl → ./out/<name>.xlsx
    “mirror audit-xls”: blue/black/green, Inputs tab, named ranges, Checks tab

pitch-deck   (live-Office 템플릿 채움; python-pptx + 제한적 OOXML + LibreOffice 시각 루프)

deck-refresh (기존 덱 숫자만; 차트 시리즈 값 갱신; 승인 게이트)
ib-check-deck (읽기 전용 QC; extract_numbers.py --check)
audit-xls / clean-data-xls (엑셀 쪽 QC / 정리; 후자는 Office JS 또는 openpyxl)
```

`pptx-author` 원문: “Conventions (mirror the live-Office `pitch-deck` skill)”.
`xlsx-author` 원문: “Conventions (mirror `audit-xls`)”.

---

## 원문에 없는 것 (발명하지 말 것)

다음 항목은 지정된 스킬 원문에 **없다**:

- Excel named range를 PowerPoint native chart에 바인딩하는 API/XML
- `c:chart`, `c:ser`, chart part, `chart.xml` 작성 패턴
- `openpyxl` `DefinedName` / Name Manager 코드
- CMA orchestration이 `./out/`를 수집하는 구현 (계약만 있음: “Return the relative path … so the orchestration layer can collect it”)
- `skill-creator`가 예시로 든 `OOXML.md` 실파일
- `pptx-author`의 native `python-pptx` Chart API 사용법
- OLE/embedded workbook 차트 링크 유지 방법

차트 “바인딩”에 가장 가까운 원문 문장은 `deck-refresh`의 “update the underlying series values so the bars/lines actually move”와 `pptx-author`의 “prefer embedding a PNG rendered from the model”이다.

---

## 파일 목록 (읽은 것)

```
financial-analysis/skills/pptx-author/SKILL.md
financial-analysis/skills/xlsx-author/SKILL.md
financial-analysis/skills/ppt-template-creator/SKILL.md
financial-analysis/skills/audit-xls/SKILL.md
financial-analysis/skills/clean-data-xls/SKILL.md
financial-analysis/skills/deck-refresh/SKILL.md
financial-analysis/skills/ib-check-deck/SKILL.md
financial-analysis/skills/ib-check-deck/references/ib-terminology.md
financial-analysis/skills/ib-check-deck/references/report-format.md
financial-analysis/skills/ib-check-deck/scripts/extract_numbers.py
financial-analysis/skills/skill-creator/SKILL.md
financial-analysis/skills/skill-creator/references/output-patterns.md
financial-analysis/skills/skill-creator/references/workflows.md
financial-analysis/skills/skill-creator/scripts/init_skill.py
financial-analysis/skills/skill-creator/scripts/package_skill.py
financial-analysis/skills/skill-creator/scripts/quick_validate.py
investment-banking/skills/pitch-deck/SKILL.md
investment-banking/skills/pitch-deck/reference/xml-reference.md
investment-banking/skills/pitch-deck/reference/formatting-standards.md
investment-banking/skills/pitch-deck/reference/slide-templates.md
investment-banking/skills/pitch-deck/reference/calculation-standards.md
```
