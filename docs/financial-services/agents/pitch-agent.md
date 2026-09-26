# Pitch Agent 전수 분석

소스 범위 (발명 없음, 파일에 있는 내용만):

- Cowork 플러그인: `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/pitch-agent/`
- CMA 쿡북: `/Users/yeonwoosung/Desktop/financial-services/managed-agent-cookbooks/pitch-agent/`

파일 목록:

```
plugins/agent-plugins/pitch-agent/.claude-plugin/plugin.json
plugins/agent-plugins/pitch-agent/agents/pitch-agent.md
plugins/agent-plugins/pitch-agent/skills/{3-statement-model,audit-xls,comps-analysis,dcf-model,deck-refresh,ib-check-deck,lbo-model,pitch-deck,pptx-author,sector-overview,xlsx-author}/SKILL.md
plugins/agent-plugins/pitch-agent/skills/3-statement-model/references/{formatting.md,formulas.md,sec-filings.md}
plugins/agent-plugins/pitch-agent/skills/dcf-model/{requirements.txt,TROUBLESHOOTING.md,scripts/validate_dcf.py}
plugins/agent-plugins/pitch-agent/skills/ib-check-deck/{references/ib-terminology.md,references/report-format.md,scripts/extract_numbers.py}
plugins/agent-plugins/pitch-agent/skills/pitch-deck/reference/{calculation-standards.md,formatting-standards.md,slide-templates.md,xml-reference.md}
managed-agent-cookbooks/pitch-agent/{agent.yaml,README.md,steering-examples.json}
managed-agent-cookbooks/pitch-agent/subagents/{researcher.yaml,modeler.yaml,deck-writer.yaml}
```

---

## 1. 시스템 프롬프트 (전체 구조와 가드레일 원문)

### 1.1 플러그인 메타 (`plugin.json`)

경로: `plugins/agent-plugins/pitch-agent/.claude-plugin/plugin.json`

```json
{
  "name": "pitch-agent",
  "version": "0.1.1",
  "description": "Comps, precedents, LBO to a branded pitch deck, end to end",
  "author": {
    "name": "Anthropic FSI"
  }
}
```

### 1.2 Cowork 에이전트 프론트매터 + 본문 (`agents/pitch-agent.md`)

프론트매터 원문:

```
---
name: pitch-agent
description: End-to-end investment banking pitch agent. Given a target company and a strategic situation (e.g., "exploring strategic alternatives"), autonomously pulls comps and precedents from market data, builds a DCF and football-field valuation in Excel, and generates a branded pitch deck on the bank's PowerPoint template. Use when an MD or senior banker asks for a first-draft pitch on a name — not for editing an existing deck (use the pitch-deck skill directly for that).
tools: Read, Write, Edit, mcp__capiq__*
---
```

역할 선언 원문:

```
You are the Pitch Agent — a senior investment banking associate who owns the first draft of a client pitch end to end.
```

역할 범위 제약 (description에서 명시):

- 사용: `Use when an MD or senior banker asks for a first-draft pitch on a name`
- 비사용: `not for editing an existing deck (use the pitch-deck skill directly for that)`

### 1.3 산출물 계약 (`## What you produce`)

원문:

```
Given a target company ticker/name and a one-line situation, you deliver two artifacts:

1. **Excel valuation workbook** — trading comps, precedent transactions, DCF, and a football-field summary. Every output cell is a live formula traceable to an input.
2. **Pitch deck** — populated on the bank's PowerPoint template: situation overview, company snapshot, valuation summary (football field), comps detail, precedents detail, illustrative process. Every chart is bound to the Excel model.
```

입력 계약: `target company ticker/name` + `one-line situation`.

아티팩트 1 내용 요소: trading comps, precedent transactions, DCF, football-field summary. 품질 조건: `Every output cell is a live formula traceable to an input.`

아티팩트 2 슬라이드 구성: situation overview, company snapshot, valuation summary (football field), comps detail, precedents detail, illustrative process. 품질 조건: `Every chart is bound to the Excel model.`

### 1.4 가드레일 원문 (`## Guardrails`) — 전부 인용

```
- **No external communications.** This agent has no email or messaging tools; client outreach happens outside the agent.
- **Cite every number.** If a multiple or precedent can't be sourced from CapIQ or a filing, flag it as `[UNSOURCED]` rather than estimating.
- **Stop and surface for review** after the Excel model is built and again after the deck is generated. The banker approves each artifact before you proceed to the next.
```

가드레일 3조 요약 (원문 키워드 유지):

| # | 제목 | 원문 핵심 |
|---|---|---|
| 1 | No external communications | `no email or messaging tools`; `client outreach happens outside the agent` |
| 2 | Cite every number | 소스가 CapIQ 또는 filing이 아니면 `[UNSOURCED]`로 표시, `rather than estimating` |
| 3 | Stop and surface for review | Excel 모델 완료 후 1회, 덱 생성 후 1회. `The banker approves each artifact before you proceed to the next.` |

### 1.5 스킬 목록 원문 (`## Skills this agent uses`)

```
`sector-overview` · `comps-analysis` · `lbo-model` · `dcf-model` · `3-statement-model` · `audit-xls` · `pitch-deck` · `ib-check-deck` · `deck-refresh`
```

9개. `deck-refresh`는 목록에 있으나 아래 워크플로 9스텝에는 호출되지 않는다. `xlsx-author` / `pptx-author`는 Cowork 에이전트 스킬 목록에 없고 CMA leaf `pitch-deck-writer`에만 연결된다.

### 1.6 CMA에서 붙는 추가 시스템 문장

`managed-agent-cookbooks/pitch-agent/agent.yaml`:

```
system:
  file: ../../plugins/agent-plugins/pitch-agent/agents/pitch-agent.md
  append: "You are running headless. Produce files in ./out/; do not assume an open Office document."
```

즉 CMA 오케스트레이터 시스템 프롬프트 = `pitch-agent.md` 전체 + 위 `append` 한 문장.

---

## 2. 워크플로 스텝과 호출 스킬

`agents/pitch-agent.md` `## Workflow` 원문 9스텝:

```
1. **Scope the ask.** Confirm target, sector, and situation. Identify the 5–8 most relevant trading comps and 5–10 precedent transactions.
2. **Write the situation overview.** Invoke the `sector-overview` skill to draft the company snapshot and strategic-rationale narrative — business description, market position, what's changed, why now.
3. **Pull data.** Use the CapIQ MCP for trading multiples, precedent transaction data, and the target's latest filings. Load full filings — do not summarize from snippets.
4. **Spread the peer set.** Invoke the `comps-analysis` skill to lay out trading comps and precedent transactions with consistent metric definitions and outlier flags.
5. **Stand up the sponsor case.** Invoke the `lbo-model` skill for an illustrative LBO at market leverage — entry/exit assumptions, sources & uses, returns sensitivity.
6. **Build the rest of the model.** Invoke `dcf-model` and `3-statement-model`; follow `audit-xls` conventions (blue/black/green, no hardcodes in calc cells, balance checks).
7. **Generate the football field.** Min/median/max from each methodology — comps, precedents, DCF, LBO — with the current price marker.
8. **Populate the deck.** Invoke the `pitch-deck` skill against the bank's template. Every number on a slide must trace to a named range in the workbook.
9. **Run deck QC.** Invoke `ib-check-deck` — verify totals tie, footnotes present, dates consistent.
```

### 2.1 스텝별 스킬/도구 매핑 (원문에 적힌 것만)

| Step | 제목 | 명시된 스킬/도구 | 원문 산출/제약 |
|---|---|---|---|
| 1 | Scope the ask | (스킬 호출 없음) | target, sector, situation 확인. trading comps **5–8**, precedent transactions **5–10** |
| 2 | Write the situation overview | `sector-overview` | company snapshot + strategic-rationale: `business description, market position, what's changed, why now` |
| 3 | Pull data | CapIQ MCP (스킬 아님) | trading multiples, precedent transaction data, latest filings. `Load full filings — do not summarize from snippets.` |
| 4 | Spread the peer set | `comps-analysis` | trading comps + precedents, `consistent metric definitions and outlier flags` |
| 5 | Stand up the sponsor case | `lbo-model` | illustrative LBO at market leverage — `entry/exit assumptions, sources & uses, returns sensitivity` |
| 6 | Build the rest of the model | `dcf-model`, `3-statement-model`, `audit-xls` conventions | `blue/black/green, no hardcodes in calc cells, balance checks` |
| 7 | Generate the football field | (스킬 호출 없음) | Min/median/max from comps, precedents, DCF, LBO + current price marker |
| 8 | Populate the deck | `pitch-deck` | bank's template. `Every number on a slide must trace to a named range in the workbook.` |
| 9 | Run deck QC | `ib-check-deck` | `verify totals tie, footnotes present, dates consistent` |

### 2.2 워크플로에 없는 스킬

- `deck-refresh`: `## Skills this agent uses`에만 등장. 9스텝 어디에도 `Invoke`되지 않음. 스킬 description: `Updates a presentation with new numbers` — 기존 덱 숫자 교체용. 에이전트 description은 `not for editing an existing deck`이므로 역할이 어긋난다.
- `xlsx-author`, `pptx-author`: 플러그인 에이전트 스킬 목록에 없음. CMA `pitch-deck-writer` leaf에만 연결.

### 2.3 각 스킬 트리거/역할 (SKILL.md frontmatter description 원문)

**sector-overview**

```
Create comprehensive industry and sector landscape reports covering market dynamics, competitive positioning, key players, and thematic trends. Use for client requests, sector initiations, thematic research pieces, or internal knowledge building. Triggers on "sector overview", "industry report", "market landscape", "sector analysis", "industry deep dive", or "thematic research".
```

워크플로 Step 6 산출: `Word document or PowerPoint` + `Excel appendix with detailed company data`. Step 1–5는 TAM, 산업구조, 경쟁, 밸류에이션 컨텍스트, 투자 함의.

**comps-analysis**

```
Build institutional-grade comparable company analyses with operating metrics, valuation multiples, and statistical benchmarking in Excel/spreadsheet format.
```

데이터 소스 우선순위 원문:

```
1. **FIRST: Check for MCP data sources** - If S&P Kensho MCP, FactSet MCP, or Daloopa MCP are available, use them exclusively for financial and trading information
2. **DO NOT use web search** if the above MCP data sources are available
3. **ONLY if MCPs are unavailable:** Then use Bloomberg Terminal, SEC EDGAR filings, or other institutional sources
4. **NEVER use web search as a primary data source**
```

**lbo-model**

```
This skill should be used when completing LBO (Leveraged Buyout) model templates in Excel for private equity transactions, deal materials, or investment committee presentations.
```

템플릿 강제:

```
**This skill uses templates for LBO models. Always check for an attached template file first.**
```

템플릿 없으면 사용자에게 질문: `"Do you have a specific LBO template you'd like me to use? If not, I can use the standard template which includes Sources & Uses, Operating Model, Debt Schedule, and Returns Analysis."`

표준 템플릿 경로: `examples/LBO_Model.xlsx` (이 경로는 SKILL.md에만 언급; pitch-agent 플러그인 트리에는 해당 xlsx가 없음).

**dcf-model**

```
Real DCF (Discounted Cash Flow) model creation for equity valuation. Retrieves financial data from SEC filings and analyst reports, builds comprehensive cash flow projections with proper WACC calculations, performs sensitivity analysis, and outputs professional Excel models with executive summaries.
```

데이터 소스 우선순위 원문:

```
1. **MCP Servers** (if configured) - Structured financial data from providers like Daloopa
2. **User-Provided Data** - Historical financials from their research
3. **Web Search/Fetch** - Current prices, beta, debt and cash when needed
```

산출 파일명: `[Ticker]_DCF_Model_[Date].xlsx`. 시트: `DCF` + `WACC`. Sensitivity tables는 DCF 시트 하단.

**3-statement-model**

```
Complete, populate and fill out 3-statement financial model templates (Income Statement, Balance Sheet, Cash Flow Statement).
```

환경 분기: Office JS vs Python/openpyxl. `If generating a standalone .xlsx file: Use Python/openpyxl. Write formula strings, then run recalc.py before delivery.`

**audit-xls**

```
Audit a spreadsheet for formula accuracy, errors, and common mistakes.
```

스코프: selection / sheet / model. 원칙: `Don't change anything without asking — report first, fix on request.`

**pitch-deck**

```
Populates investment banking pitch deck templates with data from source files. Use when: user provides a PowerPoint template to fill in, user has source data (Excel/CSV) to populate into slides, user mentions populating or filling a pitch deck template, or user needs to transfer data into existing slide layouts. Not for creating presentations from scratch.
```

Phase: Extract → Map → Populate → Validate(LibreOffice) → Final. 필수 고지:

```
"This file was validated using LibreOffice. Please review in Microsoft PowerPoint before distribution, as rendering differences may exist."
```

**ib-check-deck**

```
Investment banking presentation quality checker. Reviews a pitch deck or client-ready presentation for (1) number consistency across slides, (2) data-narrative alignment, (3) language polish against IB standards, (4) visual and formatting QC.
```

`This is read-and-report only — no edits.` 스크립트:

```
python scripts/extract_numbers.py /tmp/deck_content.md --check
```

**deck-refresh** (워크플로 미호출)

```
Updates a presentation with new numbers — quarterly refreshes, earnings updates, comp rolls, rebased market data.
```

4페이즈, Phase 3이 승인 게이트: `Don't edit until the user has seen the plan.`

**xlsx-author** (CMA leaf 전용)

```
Produce a .xlsx file on disk (headless) instead of driving a live Excel workbook — for managed-agent sessions with no open Office app.
```

**pptx-author** (CMA leaf 전용)

```
Produce a .pptx file on disk (headless) instead of driving a live PowerPoint document — for managed-agent sessions with no open Office app.
```

### 2.4 가드레일과 워크플로의 정지점

워크플로 Step 6 완료 ≈ 가드레일 3의 첫 정지점 (`after the Excel model is built`). Step 8–9 완료 ≈ 둘째 정지점 (`after the deck is generated`). Step 7 football field는 모델 산출의 일부로 읽히나 별도 스킬 호출은 없다.

---

## 3. CMA 오버레이 (`agent.yaml`)

경로: `managed-agent-cookbooks/pitch-agent/agent.yaml`

전체 YAML 원문:

```yaml
# Pitch Agent — managed-agent cookbook

name: pitch-agent
model: claude-opus-4-7

system:
  file: ../../plugins/agent-plugins/pitch-agent/agents/pitch-agent.md
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
  - { from_plugin: ../../plugins/agent-plugins/pitch-agent }

callable_agents:
  - { manifest: ./subagents/researcher.yaml }
  - { manifest: ./subagents/modeler.yaml }
  - { manifest: ./subagents/deck-writer.yaml }   # only leaf with Write
```

### 3.1 필드별

| 필드 | 값 |
|---|---|
| `name` | `pitch-agent` |
| `model` | `claude-opus-4-7` |
| `system.file` | `../../plugins/agent-plugins/pitch-agent/agents/pitch-agent.md` |
| `system.append` | `"You are running headless. Produce files in ./out/; do not assume an open Office document."` |
| toolset type | `agent_toolset_20260401` |
| default_config | `{ enabled: false }` — 화이트리스트 |
| 오케스트레이터 활성 도구 | `read`, `grep`, `glob` |
| 오케스트레이터 Write | **없음** (enabled 목록에 write/edit/bash 없음) |
| MCP toolset | `capiq` enabled true, `daloopa` enabled true |
| mcp_servers | url, name `capiq` / `daloopa`, URL 환경변수 `${CAPIQ_MCP_URL}` / `${DALOOPA_MCP_URL}` |
| skills | `{ from_plugin: ../../plugins/agent-plugins/pitch-agent }` — 플러그인 전체 |
| callable_agents | researcher, modeler, deck-writer. 주석: `# only leaf with Write` |

### 3.2 Cowork 프론트매터 vs CMA 도구 차이

Cowork `tools:`: `Read, Write, Edit, mcp__capiq__*`

CMA 오케스트레이터: `read`, `grep`, `glob` + CapIQ MCP + Daloopa MCP. Write/Edit/Bash 없음.

Cowork는 CapIQ만 프론트매터에 명시 (`mcp__capiq__*`). CMA는 CapIQ + Daloopa를 명시.

### 3.3 배포 (README)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export CAPIQ_MCP_URL=... DALOOPA_MCP_URL=...
../../scripts/deploy-managed-agent.sh pitch-agent
```

README 한 줄: `Same source as the pitch-agent Cowork plugin — this directory is the Managed Agent cookbook for POST /v1/agents.`

---

## 4. Leaf worker 각각: tools, Write 권한, 시스템 프롬프트 제약

세 YAML 모두 `model: claude-opus-4-7`, `skills`/`callable_agents` 구조. 공통: `default_config: { enabled: false }` 후 개별 enable.

### 4.1 `pitch-researcher` (`subagents/researcher.yaml`)

시스템 프롬프트 원문:

```
You research comps and precedent transactions for a target. Pull trading
multiples and precedent data from CapIQ/Daloopa, return a structured table.
Read-only — you do not write files.
```

도구:

```
tools:
  - type: agent_toolset_20260401
    default_config: { enabled: false }
    configs:
      - { name: read, enabled: true }
      - { name: grep, enabled: true }
  - { type: mcp_toolset, mcp_server_name: capiq,   default_config: { enabled: true } }
  - { type: mcp_toolset, mcp_server_name: daloopa, default_config: { enabled: true } }
```

- Write: **없음**
- Edit/Bash/Glob: 없음
- MCP: capiq, daloopa (read-only 커넥터로 README가 표기)
- `skills: []`
- `callable_agents: []`

`output_schema` (researcher만 보유):

```yaml
output_schema:
  type: object
  required: [target, comps]
  additionalProperties: false
  properties:
    target: { type: string, maxLength: 64, pattern: "^[A-Za-z0-9 ._-]+$" }
    comps:
      type: array
      maxItems: 30
      items:
        type: object
        additionalProperties: false
        properties:
          ticker:   { type: string, maxLength: 12, pattern: "^[A-Z.]+$" }
          metric:   { type: string, maxLength: 32, pattern: "^[A-Za-z0-9 /_-]+$" }
          value:    { type: number }
    precedents:
      type: array
      maxItems: 30
      items:
        type: object
        additionalProperties: false
        properties:
          target:   { type: string, maxLength: 64, pattern: "^[A-Za-z0-9 ._-]+$" }
          acquirer: { type: string, maxLength: 64, pattern: "^[A-Za-z0-9 ._-]+$" }
          ev:       { type: number }
          multiple: { type: number }
```

제약 정리:

- `required: [target, comps]` — `precedents`는 required가 아님
- `additionalProperties: false` 전 레벨
- ticker: `^[A-Z.]+$`, maxLength 12
- target/acquirer: `^[A-Za-z0-9 ._-]+$`, maxLength 64
- comps/precedents 각 maxItems 30
- 파일 기록 금지: `Read-only — you do not write files.`

### 4.2 `pitch-modeler` (`subagents/modeler.yaml`)

시스템 프롬프트 원문:

```
You build the DCF/LBO valuation in a scratch directory using the comps and
inputs handed to you. Run calculations in Python via Bash; return computed
outputs as structured JSON. You do not write the final workbook — the
deck-writer does.
```

도구:

```
tools:
  - type: agent_toolset_20260401
    default_config: { enabled: false }
    configs:
      - { name: read, enabled: true }
      - { name: bash, enabled: true }
  - { type: mcp_toolset, mcp_server_name: capiq,   default_config: { enabled: true } }
  - { type: mcp_toolset, mcp_server_name: daloopa, default_config: { enabled: true } }
```

- Write: **없음**
- Bash: 있음 (`README`: `Bash (sandboxed)`)
- MCP: capiq, daloopa
- `callable_agents: []`
- `output_schema`: 없음 (researcher만 있음)

스킬:

```
skills:
  - { path: ../../../plugins/agent-plugins/pitch-agent/skills/dcf-model }
  - { path: ../../../plugins/agent-plugins/pitch-agent/skills/lbo-model }
```

`3-statement-model` / `audit-xls` / `comps-analysis`는 modeler에 연결되지 않음. 오케스트레이터는 `from_plugin`으로 플러그인 전체를 받지만, 최종 xlsx는 deck-writer가 씀.

제약: scratch directory에서 계산, JSON 반환, `You do not write the final workbook — the deck-writer does.`

### 4.3 `pitch-deck-writer` (`subagents/deck-writer.yaml`) — 유일한 Write 보유자

시스템 프롬프트 원문:

```
You are the ONLY worker with Write. Take the verified comps, model outputs,
and football field, and produce ./out/model.xlsx and ./out/pitch-<target>.pptx
using xlsx-author and pptx-author. Never open external documents.
```

도구:

```
tools:
  - type: agent_toolset_20260401
    default_config: { enabled: false }
    configs:
      - { name: read,  enabled: true }
      - { name: write, enabled: true }
      - { name: edit,  enabled: true }
```

- Write: **있음** (오케스트레이터·researcher·modeler 중 유일)
- Edit: 있음
- Bash: **없음** (xlsx-author/pptx-author는 `Write a short Python script and run it with Bash`라고 하나, 이 leaf의 tools에는 bash가 없음)
- MCP: `mcp_servers: []` — README 표: Connectors `None`
- `callable_agents: []`

스킬:

```
skills:
  - { path: ../../../plugins/agent-plugins/pitch-agent/skills/xlsx-author }
  - { path: ../../../plugins/agent-plugins/pitch-agent/skills/pptx-author }
  - { path: ../../../plugins/agent-plugins/pitch-agent/skills/pitch-deck }
```

`ib-check-deck`은 이 leaf에 없음. QC는 오케스트레이터 워크플로 Step 9.

제약:

- `ONLY worker with Write`
- 산출 경로 고정: `./out/model.xlsx`, `./out/pitch-<target>.pptx`
- `Never open external documents.`

### 4.4 README 보안 표 vs YAML 이름

README:

```
| Leaf | Tools | Connectors |
|---|---|---|
| `researcher` | `Read`, `Grep` | CapIQ, Daloopa (read-only) |
| `modeler` | `Read`, `Bash` (sandboxed) | CapIQ, Daloopa (read-only) |
| **`deck-writer`** (Write-holder) | `Read`, `Write`, `Edit` | None |
```

YAML `name:`은 `pitch-researcher`, `pitch-modeler`, `pitch-deck-writer`. README는 짧은 이름. 도구 집합은 YAML과 일치.

### 4.5 Write 권한 한눈에

| 주체 | read | grep | glob | bash | write | edit | MCP |
|---|---|---|---|---|---|---|---|
| CMA orchestrator (`pitch-agent`) | Y | Y | Y | N | N | N | capiq, daloopa |
| `pitch-researcher` | Y | Y | N | N | **N** | N | capiq, daloopa |
| `pitch-modeler` | Y | N | N | Y | **N** | N | capiq, daloopa |
| `pitch-deck-writer` | Y | N | N | N | **Y** | Y | none |
| Cowork `pitch-agent.md` | Y | (미기재) | (미기재) | (미기재) | **Y** | Y | `mcp__capiq__*` only |

---

## 5. Steering examples JSON 형태

경로: `managed-agent-cookbooks/pitch-agent/steering-examples.json`

파일 전체 원문:

```json
[
  { "event": "Build pitch book: target CRWD, acquirer PANW, thesis: platform consolidation in security", "description": "Single-target pitch with stated thesis" },
  { "event": "Build pitch book: target SNOW, situation: exploring strategic alternatives", "description": "Sell-side pitch, no named acquirer" },
  { "event": "Refresh comps and football field only for target CRWD", "description": "Follow-up steering event after MD feedback" }
]
```

형태:

- 최상위: JSON array
- 원소 키: `event` (string), `description` (string)
- 다른 키 없음 (`id`, `payload`, `handoff` 등 없음)

세 이벤트:

| # | event | description |
|---|---|---|
| 1 | `Build pitch book: target CRWD, acquirer PANW, thesis: platform consolidation in security` | `Single-target pitch with stated thesis` |
| 2 | `Build pitch book: target SNOW, situation: exploring strategic alternatives` | `Sell-side pitch, no named acquirer` |
| 3 | `Refresh comps and football field only for target CRWD` | `Follow-up steering event after MD feedback` |

이벤트 1은 acquirer+thesis. 이벤트 2는 situation만 (`exploring strategic alternatives`는 에이전트 description 예시와 동일). 이벤트 3은 전체 피치가 아니라 comps + football field만 — `deck-refresh` 스킬과 의미상 가깝지만 쿡북은 스킬 이름을 적지 않음.

README: `See [`steering-examples.json`](./steering-examples.json).`

---

## 6. README 보안 노트

경로: `managed-agent-cookbooks/pitch-agent/README.md` 섹션 `## Security & handoffs` 원문:

```
Task-decomposition split — less about untrusted inputs (data comes from CapIQ/Daloopa MCPs), more about parallelism and artifact isolation. Exactly one worker holds `Write`:

| Leaf | Tools | Connectors |
|---|---|---|
| `researcher` | `Read`, `Grep` | CapIQ, Daloopa (read-only) |
| `modeler` | `Read`, `Bash` (sandboxed) | CapIQ, Daloopa (read-only) |
| **`deck-writer`** (Write-holder) | `Read`, `Write`, `Edit` | None |

Artifacts land in `./out/pitch-<target>.pptx` and `./out/model.xlsx` via `pptx-author` / `xlsx-author`.

**Handoff:** to rebuild the model after a thesis change, the orchestrator emits a `handoff_request` for `model-builder`; `scripts/orchestrate.py` (or your workflow engine) routes it as a new steering event. See the script for the allowlist + payload-validation pattern.
```

보안 포인트 (원문 그대로):

1. **Threat model**: `less about untrusted inputs (data comes from CapIQ/Daloopa MCPs), more about parallelism and artifact isolation.`
2. **Write isolation**: `Exactly one worker holds Write` → deck-writer.
3. **MCP 범위**: researcher/modeler만 CapIQ·Daloopa, `(read-only)`. deck-writer `None`.
4. **Bash sandbox**: modeler만 `Bash (sandboxed)`.
5. **아티팩트 경로 고정**: `./out/pitch-<target>.pptx`, `./out/model.xlsx`.
6. **Handoff**: `handoff_request` for `model-builder`. 라우팅: `scripts/orchestrate.py` (또는 workflow engine) → new steering event. 패턴: `allowlist + payload-validation`.

이름 불일치 (파일에 존재하는 사실):

- leaf YAML `name`: `pitch-modeler`
- README 표: `modeler`
- handoff 대상: `model-builder` — 이 쿡북의 `subagents/`에 `model-builder.yaml`은 **없음**

`scripts/orchestrate.py`는 README가 가리키나 `managed-agent-cookbooks/pitch-agent/` 안에는 없음. 배포 스크립트는 `../../scripts/deploy-managed-agent.sh`.

에이전트 가드레일 보안 관련 원문 (플러그인):

- `No external communications.` / `no email or messaging tools`
- pptx-author: `No external sends. This skill writes a file; it never emails or uploads.`
- deck-writer: `Never open external documents.`
- Cite: unsourced는 `[UNSOURCED]`, `rather than estimating`

---

## 7. 산출 아티팩트

### 7.1 에이전트 계약 (`pitch-agent.md`)

1. Excel valuation workbook — trading comps, precedent transactions, DCF, football-field summary. `Every output cell is a live formula traceable to an input.`
2. Pitch deck — bank's PowerPoint template. 슬라이드: situation overview, company snapshot, valuation summary (football field), comps detail, precedents detail, illustrative process. `Every chart is bound to the Excel model.`

### 7.2 CMA 경로

README: `Artifacts land in ./out/pitch-<target>.pptx and ./out/model.xlsx via pptx-author / xlsx-author.`

deck-writer 시스템: `produce ./out/model.xlsx and ./out/pitch-<target>.pptx`

`system.append`: `Produce files in ./out/`

xlsx-author: `Write to ./out/<name>.xlsx. Create ./out/ if it does not exist.` 예시 `wb.save("./out/model.xlsx")`

pptx-author: `Write to ./out/<name>.pptx`. 예시 `prs.save("./out/pitch-<target>.pptx")`. 템플릿: `./templates/firm-template.pptx` if provided.

### 7.3 스킬별 부가 산출 (플러그인 SKILL.md)

| 스킬 | 산출 (원문) |
|---|---|
| sector-overview | `Word document or PowerPoint` + `Excel appendix with detailed company data` |
| comps-analysis | structured Excel/spreadsheet. 예: `examples/comps_example.xlsx` (플러그인 트리에 해당 xlsx 없음) |
| lbo-model | 템플릿 기반 LBO. 표준: `examples/LBO_Model.xlsx` (플러그인 트리에 없음) |
| dcf-model | `[Ticker]_DCF_Model_[Date].xlsx`, sheets DCF + WACC |
| 3-statement-model | populated 3-statement template |
| audit-xls | findings table (변경 없음, report first) |
| pitch-deck | populated template pptx + `[filename]_backup.pptx` |
| ib-check-deck | Deck Check Report (report-format.md). 중간: `/tmp/deck_content.md` |
| deck-refresh | 기존 덱 in-place 숫자 갱신 |
| xlsx-author | `./out/<name>.xlsx` |
| pptx-author | `./out/<name>.pptx` |

### 7.4 Football field

워크플로 Step 7: `Min/median/max from each methodology — comps, precedents, DCF, LBO — with the current price marker.` 전용 스킬 없음. 모델 워크북 요약 + 덱 valuation summary 슬라이드에 대응하는 산출.

### 7.5 Researcher JSON 산출

researcher는 파일을 쓰지 않고 structured table/JSON (`output_schema`)을 반환. required: `target`, `comps`. optional: `precedents`.

modeler: `return computed outputs as structured JSON`. 스키마 YAML은 없음.

### 7.6 정지·승인 아티팩트

가드레일: Excel 모델 후 1회, 덱 후 1회 banker 승인. CMA headless는 `do not assume an open Office document`이므로 승인 UX는 Cowork live Office와 다를 수 있으나, 정지 문장은 공유 시스템 프롬프트에 남아 있다.

---

## 8. Headless(CMA) vs Cowork 차이

### 8.1 배포 형태

README: `Same source as the pitch-agent Cowork plugin — this directory is the Managed Agent cookbook for POST /v1/agents.`

| | Cowork plugin | CMA cookbook |
|---|---|---|
| 경로 | `plugins/agent-plugins/pitch-agent/` | `managed-agent-cookbooks/pitch-agent/` |
| 엔트리 | `.claude-plugin/plugin.json` + `agents/pitch-agent.md` | `agent.yaml` + `POST /v1/agents` |
| 시스템 프롬프트 | `pitch-agent.md`만 | `pitch-agent.md` + append |
| 모델 | 프론트매터에 없음 | `claude-opus-4-7` (orchestrator + 3 leaves) |

### 8.2 Headless append 원문

```
You are running headless. Produce files in ./out/; do not assume an open Office document.
```

### 8.3 도구

Cowork 단일 에이전트: `Read, Write, Edit, mcp__capiq__*` — 본인이 Write.

CMA: 오케스트레이터는 read/grep/glob만. Write는 `pitch-deck-writer`만.

CMA만 Daloopa MCP를 YAML에 명시. Cowork 프론트매터는 CapIQ만.

### 8.4 Office live vs 파일 아티팩트

xlsx-author:

```
Use this skill when running **headless** (managed-agent / CMA mode) and you need to deliver an Excel workbook as a **file artifact** rather than editing a live workbook via `mcp__office__excel_*`.
```

```
If `mcp__office__excel_*` tools are available (Cowork plugin mode), use those instead — they drive the user's live workbook with review checkpoints. This skill is the file-producing fallback for headless runs.
```

pptx-author 대칭:

```
rather than editing a live document via `mcp__office__powerpoint_*`
```

```
If `mcp__office__powerpoint_*` tools are available (Cowork plugin mode), use those instead — they drive the user's live document with review checkpoints. This skill is the file-producing fallback for headless runs.
```

Cowork 프론트매터 `tools:`에는 `mcp__office__*`가 없고 `mcp__capiq__*`만 있다. Office MCP 사용은 xlsx-author/pptx-author의 "When NOT to use"에만 적힘.

### 8.5 환경 분기 (여러 스킬)

dcf-model / lbo-model / 3-statement-model / comps-analysis:

- Excel add-in / Office JS: `Excel.run`, `range.formulas`, 네이티브 recalc
- standalone xlsx: Python/openpyxl + `recalc.py`

ib-check-deck / deck-refresh:

- Add-in: live open deck
- Chat: uploaded `.pptx`

pitch-deck: LibreOffice `soffice --headless --convert-to pdf` 검증. CMA/Cowork 구분 없음.

### 8.6 스킬 부착

Cowork: `## Skills this agent uses` 9개 (xlsx-author/pptx-author 없음).

CMA orchestrator: `from_plugin` 전체.

CMA leaves:

- researcher: `skills: []`
- modeler: dcf-model, lbo-model
- deck-writer: xlsx-author, pptx-author, pitch-deck

### 8.7 서브에이전트

Cowork `pitch-agent.md`에는 callable subagent가 없음. CMA만 researcher / modeler / deck-writer.

### 8.8 산출 경로

Cowork: 경로 미지정 (live workbook/deck 가정 가능).

CMA: `./out/model.xlsx`, `./out/pitch-<target>.pptx`.

### 8.9 리뷰 게이트

Cowork: `Stop and surface for review` + 다수 스킬의 step-by-step user confirm.

CMA: 같은 문장이 시스템 프롬프트에 남음 + headless append. xlsx-author/pptx-author는 `Return the relative path in your final message so the orchestration layer can collect it.`

### 8.10 Steering / handoff

CMA만 `steering-examples.json`, `handoff_request` for `model-builder`, `scripts/orchestrate.py`. Cowork 에이전트 파일에는 steering 없음.

---

## 부록 A. 스킬 레퍼런스·스크립트 요약 (원문 제약)

### A.1 3-statement-model

- `references/formatting.md`: Blue inputs, black formulas, green links. Check cells red/green. Credit metric thresholds (e.g. Total Debt/EBITDA green `< 2.5x`).
- `references/formulas.md`: `Assets = Liabilities + Equity`, cash tie-out, RE roll-forward, NOL 80% cap.
- `references/sec-filings.md`: 10-K/10-Q only when template requires. EDGAR URL, 3년 historical.

### A.2 dcf-model

- `requirements.txt`: `openpyxl>=3.0.0`, `requests>=2.28.0`
- `scripts/validate_dcf.py`: sheets `['DCF', 'WACC', 'Sensitivity']` — SKILL.md는 sensitivity를 DCF 하단 2시트 구조로 적음 (**충돌**). 검사: formula errors, terminal growth < WACC, WACC 5–20%, TV 40–80% of EV.
- `TROUBLESHOOTING.md`: `#REF!`, `#DIV/0!`, `#VALUE!`, 비합리적 가격, case selector.

핵심 제약 원문: `Formulas Over Hardcodes (NON-NEGOTIABLE)`, `Verify Step-by-Step With the User (DO NOT build end-to-end)`, `python recalc.py model.xlsx 30`.

### A.3 ib-check-deck

- `extract_numbers.py`: markdown `## Slide N`, `--check`, 5% tolerance grouping, units M/MM/B 정규화.
- `ib-terminology.md`: casual → IB (e.g. `"cheap valuation"` → `"attractive valuation"`). 금지: contractions, exclamation points, first-person.
- `report-format.md`: Critical / Important / Minor.

ib-check-deck은 read-and-report only.

### A.4 pitch-deck

- 시작 시 reference 4개 전부 읽기.
- Anti-patterns: placeholder 박스에 데이터 넣기, pipe/tab 테이블, placeholder contrast 상속.
- `Not for creating presentations from scratch.`
- 3 validation cycle 후 escalate.
- xml-reference: python-pptx 우선, 테이블을 XML로 처음부터 만들지 말 것. `Always work on a backup copy`.

### A.5 xlsx-author / pptx-author 컨벤션

xlsx-author mirror `audit-xls`: Blue/black/green, no hardcodes in calc cells, named ranges, Checks tab, one model per file.

pptx-author mirror live `pitch-deck`: one idea per slide, every number traces to model, firm template at `./templates/`, charts as PNG from model when fidelity matters, no external sends.

### A.6 lbo-model 색 컨벤션 (audit-xls 3색과 차이)

lbo-model: Blue 0000FF inputs, Black formulas, **Purple 800080 same-tab links**, Green 008000 cross-tab. audit-xls/xlsx-author/에이전트 Step 6는 blue/black/green만 언급.

### A.7 comps-analysis 비권장

`Not ideal for: Private companies without comparable public peers; Highly diversified conglomerates; Distressed/bankrupt companies; Pre-revenue startups; Companies with unique business models.`

---

## 부록 B. 파일 간 불일치 (원문 대조, 추정 아님)

1. **Write 주체**: Cowork 에이전트는 자신이 Write. CMA는 deck-writer만 Write. 공유 프롬프트는 워크플로 Step 8에서 `Invoke the pitch-deck skill`이지 leaf 위임을 말하지 않음.
2. **MCP**: Cowork `mcp__capiq__*` only. CMA capiq+daloopa. comps-analysis는 Kensho/FactSet/Daloopa를 말하고 CapIQ를 우선순위에 넣지 않음. 워크플로 Step 3은 CapIQ MCP만.
3. **DCF 시트**: SKILL.md `two sheets: DCF, WACC`. `validate_dcf.py` `required_sheets = ['DCF', 'WACC', 'Sensitivity']`.
4. **Handoff 이름**: `model-builder` vs YAML `pitch-modeler`.
5. **deck-refresh**: 스킬 목록에만 있고 워크플로 Invoke 없음. 에이전트는 `not for editing an existing deck`.
6. **xlsx-author Bash vs deck-writer tools**: 스킬은 `Write a short Python script and run it with Bash`. deck-writer tools는 read/write/edit만, bash 없음.
7. **예제 xlsx 부재**: `examples/comps_example.xlsx`, `examples/LBO_Model.xlsx`는 SKILL.md에만 있고 플러그인 트리에 파일 없음.
8. **orchestrate.py 부재**: README가 가리키나 이 쿡북 디렉터리에 없음.
9. **output_schema**: researcher만. modeler의 `structured JSON`은 스키마 없음.
10. **Football field**: 워크플로 Step 7, 전용 스킬 없음.

---

## 부록 C. 원문 가드레일 재수록 (요청 항목 1 보강)

플러그인 에이전트:

```
- **No external communications.** This agent has no email or messaging tools; client outreach happens outside the agent.
- **Cite every number.** If a multiple or precedent can't be sourced from CapIQ or a filing, flag it as `[UNSOURCED]` rather than estimating.
- **Stop and surface for review** after the Excel model is built and again after the deck is generated. The banker approves each artifact before you proceed to the next.
```

CMA append:

```
You are running headless. Produce files in ./out/; do not assume an open Office document.
```

Leaf:

```
Read-only — you do not write files.
```

```
You do not write the final workbook — the deck-writer does.
```

```
You are the ONLY worker with Write. ... Never open external documents.
```

pptx-author:

```
**No external sends.** This skill writes a file; it never emails or uploads.
```
