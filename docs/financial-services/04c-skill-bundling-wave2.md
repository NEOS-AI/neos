# Skill × Agent 번들링 매트릭스

**Repo:** `/Users/yeonwoosung/Desktop/financial-services`  
**조사일 기준 HEAD 상태 (작업 트리).** 읽기 전용. 추측 없음.  
**매핑 소스 오브 트루스:** `scripts/sync-agent-skills.py` (전 디렉터리 복사, 스킬 **디렉터리 이름**으로 vertical → agent 매칭).  
**드리프트 게이트:** `scripts/check.py` §4b (`filecmp.dircmp`) + §4b2 (agent.md backtick 참조가 vertical에 있으면 번들에 있어야 함).

카운트 (작업 트리):

| 집합 | 개수 |
|---|---|
| `.claude-plugin/plugin.json` | 19 |
| marketplace 등록 플러그인 | 19 (advisors 없음) |
| vertical 스킬 디렉터리 (canonical) | 49 (이름 중복 0) |
| agent-plugins 번들 스킬 디렉터리 | 51 |
| partner-built 스킬 디렉터리 | 11 (sync 대상 아님) |
| vertical SKILL.md ↔ 대응 agent 복사본 바이트 일치 | 48/48 (소스 있는 것) |
| agent 전용, vertical 소스 없음 | 3 (`client-report`, `client-review`, `investment-proposal`) |
| vertical 스킬 중 어떤 agent에도 안 실림 | 21 |

---

## 1. 매핑 소스: `scripts/sync-agent-skills.py`

파일 전체 (44줄). 동작은 주석과 코드가 같다.

- **소스:** `plugins/vertical-plugins/*/skills/<name>/` — 디렉터리 이름을 키로 인덱스. 같은 이름이 두 vertical에 있으면 **나중에 glob된 쪽이 덮어씀** (`src_by_name[sk.name] = sk`). 현재 작업 트리에서 이름 충돌 0.
- **타깃:** `plugins/agent-plugins/<slug>/skills/<name>/`.
- **복사:** `shutil.rmtree(bundled)` 후 `shutil.copytree(src, bundled)` — **SKILL.md만이 아니라 스킬 디렉터리 전체** (references/, scripts/, assets/, TROUBLESHOOTING.md 등).
- **소스 없음:** stderr에 `WARN: no vertical source found for:` + 상대경로, **exit 1**. 현재 이 경로에 걸릴 항목 3개:

```
plugins/agent-plugins/meeting-prep-agent/skills/client-report
plugins/agent-plugins/meeting-prep-agent/skills/client-review
plugins/agent-plugins/meeting-prep-agent/skills/investment-proposal
```

- partner-built, `claude-for-msft-365-install`, CMA cookbooks는 이 스크립트가 건드리지 않는다.
- `check.py` 4b는 같은 이름 인덱스를 쓰고 `filecmp.dircmp`로 `diff_files` / `left_only` / `right_only`가 있으면 `drifted from … (run scripts/sync-agent-skills.py)` 에러. 소스 없으면 `no vertical-plugins source named '<name>'`.

즉: **vertical이 canonical**. agent `skills/`는 벤더 카피. 편집은 vertical에서 하고 sync로 전파 (CLAUDE.md·README 동일 지시).

---

## 2. `plugin.json` 스키마 비교 (19개)

위치: 각 플러그인의 `.claude-plugin/plugin.json`. marketplace: `.claude-plugin/marketplace.json` (`name: claude-for-financial-services`). marketplace `plugins[].source`는 아래 19개와 1:1.

### 2.1 필드 출현

| 필드 | 사용 플러그인 수 | 비고 |
|---|---|---|
| `name` | 19/19 | 필수 |
| `description` | 19/19 | 필수 |
| `version` | 19/19 | 필수. 키 순서는 파일마다 다름 |
| `author` | 19/19 | 객체. 최소 `{ "name": … }` |
| `author.email` | 2/19 | msft-365-install, sp-global만 |
| `homepage` | 1/19 | sp-global만 |
| `repository` | 1/19 | sp-global만 |
| `license` | 1/19 | sp-global `"Apache-2.0"` |
| `keywords` | 1/19 | sp-global만 |
| `displayName` | 0/19 현재 트리 | 삭제된 `claude-for-financial-advisors`만 git 이력에 보유 |
| `agents` / `skills` / `commands` / `mcpServers` | 0/19 | 컴포넌트는 디렉터리 컨벤션으로 발견 |

Cowork는 `agents/`, `skills/`, `commands/` 디렉터리를 스캔한다. plugin.json은 메타데이터만.

### 2.2 그룹별 스키마

**A. agent-plugins (10)** — 키 순서 `name, version, description, author`. author는 전부 `{ "name": "Anthropic FSI" }`.

| name | version | description (그대로) |
|---|---|---|
| earnings-reviewer | 0.1.1 | Earnings call and filings to model update to note draft |
| gl-reconciler | 0.1.0 | Finds breaks, traces root cause, routes for sign-off |
| kyc-screener | 0.1.0 | Parses onboarding docs, runs the rules engine, flags gaps |
| market-researcher | 0.1.1 | Sector or theme to industry overview, competitive landscape, peer comps, and ideas shortlist |
| meeting-prep-agent | 0.1.1 | Briefing pack before every client meeting |
| model-builder | 0.1.0 | DCF, LBO, 3-statement, comps - live in Excel |
| month-end-closer | 0.1.0 | Accruals, roll-forwards, variance commentary |
| pitch-agent | 0.1.1 | Comps, precedents, LBO to a branded pitch deck, end to end |
| statement-auditor | 0.1.0 | Audits pre-generated LP statements before distribution |
| valuation-reviewer | 0.1.1 | Ingests GP packages, runs valuation template, stages LP reporting |

에이전트 플러그인에는 `commands/`가 없다. 스킬은 자동 트리거 + agent.md 워크플로에서 backtick 이름으로 호출.

**B. vertical-plugins (6)** — 같은 4키 스키마. author 예외 1건.

| name | version | author.name | description (그대로) |
|---|---|---|---|
| financial-analysis | 0.1.1 | Anthropic FSI | Core financial modeling and analysis tools: DCF, comps, LBO, 3-statement models, competitive analysis, and deck QC |
| equity-research | 0.1.2 | Anthropic FSI | Equity research tools: earnings analysis, initiating coverage reports, and research workflows |
| investment-banking | 0.2.1 | **Anthropic** (FSI 접미사 없음) | Investment banking productivity tools: client and market insights, deck creation, financial analysis, and transaction management |
| private-equity | 0.1.2 | Anthropic FSI | Private equity deal sourcing and workflow tools: company discovery, CRM integration, and founder outreach |
| fund-admin | 0.1.0 | Anthropic FSI | Fund administration and finance ops skills: GL reconciliation, break tracing, accruals, roll-forwards, variance commentary, NAV tie-out |
| operations | 0.1.0 | Anthropic FSI | Operational workflows: KYC document parsing and rules-grid evaluation |

**C. partner-built (2)**

| name | version | 추가 필드 | author |
|---|---|---|---|
| lseg | 1.0.0 | 없음 (4키, agent/vertical과 동일) | `{ "name": "LSEG" }` |
| sp-global | 1.0.1 | homepage, repository, license, keywords | Kensho Technologies + email |

**D. claude-for-msft-365-install (1)**

```json
{
  "name": "claude-for-msft-365-install",
  "description": "Provision direct cloud access (Vertex AI, Bedrock, Azure AI Foundry, or LLM gateway) for the Claude Office add-in. …",
  "version": "0.1.13",
  "author": { "name": "Anthropic", "email": "support@anthropic.com" }
}
```

스킬 경로가 예외: `skills/`가 아니라 `.claude/skills/verify/SKILL.md`. FSI 번들 매핑 밖.

### 2.3 marketplace vs README 불일치 (사실만)

- marketplace 19개: 6 vertical + 10 agent + lseg + sp-global + msft-365-install.
- README Vertical Plugins 표는 여전히 **`[claude-for-financial-advisors](./claude-for-financial-advisors)`** 행을 가진다. 디렉터리는 커밋 `574ed36` (#354, 2026-09-21)에서 삭제. marketplace에는 항목 없음.

---

## 3. SKILL.md 프론트매터 컨벤션 (실사용)

조사 범위: vertical 49 + agent 번들 51 + partner 11 = 작업 트리 SKILL.md 중 FSI 플러그인 경로. (agent 카피는 vertical과 바이트 동일하므로 unique 본문은 vertical 49 + orphan 3 + partner 11.)

### 3.1 키

| 키 | 출현 | 규칙 |
|---|---|---|
| `name` | 전수 | YAML 스칼라. 거의 항상 디렉터리 이름과 동일. |
| `description` | 전수 | 트리거 문. Claude가 스킬 선택에 쓰는 유일한 본문 밖 필드 (`skill-creator` 본문 명시). |
| `license` | 1 | `financial-analysis/skill-creator`만: `license: Complete terms in LICENSE.txt` |

다른 키 (`version`, `allowed-tools`, `argument-hint`, `compatibility`, `metadata`)는 SKILL.md 프론트매터에 **없다**. (`argument-hint` / `allowed-tools`는 **commands/*.md** 프론트매터.)

`skill-creator` 본문 Step 4는 "Do not include any other fields in YAML frontmatter"라고 하지만, 그 스킬 자신이 `license`를 가진다.

### 3.2 `name` ↔ 디렉터리 불일치 (2건)

| 디렉터리 | frontmatter `name` | 경로 |
|---|---|---|
| `strip-profile` | `fsi-strip-profile` | `plugins/vertical-plugins/investment-banking/skills/strip-profile/` |
| `earnings-preview-beta` | `earnings-preview-single` | `plugins/partner-built/spglobal/skills/earnings-preview-beta/` |

sync/check는 **디렉터리 이름**으로 매칭하므로 `strip-profile`은 이름 불일치여도 번들 키는 `strip-profile`. 현재 어떤 agent도 `strip-profile`을 번들하지 않는다.

### 3.3 `description` 문체 (관찰된 패턴)

1. **What + Use when + Triggers on `"…"` 인용 목록** — equity-research·IB·PE 다수. 예: `catalyst-calendar`, `buyer-list`, `ic-memo`.
2. **What + Use when, Triggers 없음** — fund-admin 6개, operations 2개, `pptx-author`, `xlsx-author`. fund-admin은 가드레일을 description에 넣음 ("the JE is a draft for controller approval, not a posting").
3. **`This skill should be used when …`** — `lbo-model`, `skill-creator`.
4. **블록 스칼라 `description: \|`** — `comps-analysis` (**Perfect for / Not ideal for**), `strip-profile` (`name: fsi-strip-profile`).
5. **따옴표로 감싼 한 줄** — `pitch-deck`, spglobal `funding-digest`, `tear-sheet`.
6. **CMA 헤드리스 폴백** — `pptx-author`, `xlsx-author`: "for managed-agent sessions with no open Office app". 사용자 발화 트리거 문구 없음.

`skill-creator`는 description에 "when to use"를 넣고 본문의 "When to Use This Skill" 섹션은 쓰지 말라고 한다. 실제 FSI 스킬 다수는 본문에 워크플로를 두고 description에 트리거를 둔다.

### 3.4 본문/번들 리소스

`skill-creator`가 규정한 해부:

```
skill-name/
├── SKILL.md          # frontmatter name+description + markdown body
├── scripts/          # 실행 코드
├── references/       # 필요 시 로드
└── assets/           # 출력에 쓰는 파일
```

vertical에서 SKILL.md 외에 파일이 있는 스킬 (8):

| 스킬 | 추가 파일 |
|---|---|
| earnings-analysis | `references/{best-practices,report-structure,workflow}.md` |
| initiating-coverage | `assets/{quality-checklist,report-template}.md` + `references/task{1-5}-*.md` + `valuation-methodologies.md` |
| 3-statement-model | `references/{formatting,formulas,sec-filings}.md` |
| competitive-analysis | `references/{frameworks,schemas}.md` |
| dcf-model | `TROUBLESHOOTING.md`, `requirements.txt`, `scripts/validate_dcf.py` |
| ib-check-deck | `references/{ib-terminology,report-format}.md`, `scripts/extract_numbers.py` |
| skill-creator | `LICENSE.txt`, `references/{output-patterns,workflows}.md`, `scripts/{init,package,quick_validate}_skill.py` |
| pitch-deck | `reference/` (**references 가 아님**) `{calculation,formatting}-standards.md`, `slide-templates.md`, `xml-reference.md` |

`dcf-model`의 `TROUBLESHOOTING.md`는 skill-creator가 "만들지 말라"고 한 보조 문서 유형에 가깝다. `pitch-deck`만 폴더명이 `reference/` (단수).

---

## 4. 공유/메타 스킬 심층 (`financial-analysis`)

요청된 6개. 전부 canonical 경로: `plugins/vertical-plugins/financial-analysis/skills/<name>/`.

### 4.1 `skill-creator` — 메타, 에이전트 미번들

- frontmatter: `name`, `description`, `license`.
- 역할: 새 스킬(또는 기존 스킬 업데이트) 작성 가이드. 스크립트 `init_skill.py` / `package_skill.py` / `quick_validate.py`.
- 규정하는 프론트매터: `name` + `description`만. description이 트리거. 본문은 트리거 후 로드.
- Progressive disclosure: (1) name+description 항상 (~100 words) (2) SKILL.md body 트리거 시 (<5k words, 500줄 목표) (3) bundled resources 필요 시.
- 명령 없음. README 표: Command 열 `—`.
- 어떤 agent-plugin에도 복사되지 않음.

### 4.2 `ppt-template-creator` — 메타, 에이전트 미번들

- description: "Creates self-contained PPT template SKILLS (not presentations)". 실제 발표 자료는 `pptx` 스킬을 쓰라고 함 (repo에는 `pptx`라는 스킬 이름이 없고, 가까운 것은 `pptx-author` / `pitch-deck`).
- 워크플로가 `skill-creator`를 호출해 스킬 뼈대를 만든 뒤 `assets/template.pptx` + 자체 완결 SKILL.md를 씀.
- 생성 스킬 프론트매터 템플릿: `name: [company]-ppt-template`, `description: [Company] PowerPoint template…`.
- 명령: `/ppt-template` (`commands/ppt-template.md`). 이 커맨드만 `allowed-tools: ["Read", "Write", "Bash", "Glob"]`를 가진다.
- 에이전트 미번들.

### 4.3 `pptx-author` — CMA 헤드리스 산출, 3 에이전트

- description: live PowerPoint (`mcp__office__powerpoint_*`) 대신 디스크에 `.pptx` 산출.
- 출력 계약: `./out/<name>.pptx`. `python-pptx`.
- Cowork에서 Office MCP가 있으면 이 스킬을 쓰지 말 것.
- 번들: `market-researcher`, `meeting-prep-agent`, `pitch-agent`.
- 명령 없음.

### 4.4 `xlsx-author` — CMA 헤드리스 산출, 8 에이전트 (최대 공유)

- description: live Excel (`mcp__office__excel_*`) 대신 `./out/<name>.xlsx`. `openpyxl`.
- 컨벤션을 `audit-xls`와 맞춘다고 본문에 명시: blue/black/green, Inputs 탭, Checks 탭, named ranges.
- 번들: `earnings-reviewer`, `gl-reconciler`, `kyc-screener`, `model-builder`, `month-end-closer`, `pitch-agent`, `statement-auditor`, `valuation-reviewer`. (`market-researcher`, `meeting-prep-agent`는 ppt 산출이라 xlsx-author 없음.)
- 명령 없음.
- agent.md에 안 적힌 채 번들만 된 경우: `earnings-reviewer`, `model-builder`, `pitch-agent` (아래 매트릭스 주석).

### 4.5 `audit-xls` — 모델 QA, 6 에이전트

- description에 트리거 문구 다수: "audit this sheet", "debug model", "model won't balance" 등.
- 스코프: selection / sheet / model. model일 때 BS 균형, cash tie-out, DCF/LBO/merger/3-stmt 특화 버그.
- "Don't change anything without asking — report first, fix on request."
- 명령: `/debug-model` → `Load the \`audit-xls\` skill with scope **model**`.
- 번들: `earnings-reviewer`, `gl-reconciler`, `model-builder`, `month-end-closer`, `pitch-agent`, `statement-auditor`. (KYC·meeting-prep·market-researcher·valuation-reviewer 없음.)

### 4.6 `clean-data-xls` — 데이터 정규화, 에이전트 미번들

- description 트리거: "clean this data", "dedupe", "this data is messy".
- 환경 분기: Office JS vs openpyxl.
- 파괴적 변경 전 확인. 헬퍼 컬럼 공식 선호.
- 명령 없음. README Command 열 `—`.
- 어떤 agent에도 없음.

---

## 5. `commands/*.md`가 스킬을 감싸는 방식

에이전트 플러그인에는 커맨드가 없다. 커맨드는 vertical (및 LSEG partner) 전용. Cowork에서 `/plugin:command-name` (README: `/comps`, `/dcf`, `/earnings` …).

### 5.1 커맨드 프론트매터

거의 전부:

```yaml
---
description: <한 줄>
argument-hint: "<…>"
---
```

예외: `financial-analysis/commands/ppt-template.md`만 `allowed-tools` 추가.

`name` 키는 커맨드 프론트매터에 없다. 파일명이 슬래시 커맨드 이름이 된다 (`comps.md` → `/comps`).

### 5.2 래핑 패턴 3종 (vertical)

**패턴 A — 단문 로더 (다수).** 본문 2–4문장. 스킬 backtick 이름 + 인자 없으면 질문.

예 (`private-equity/commands/ic-memo.md` 전문):

```
Load the `ic-memo` skill and draft a structured IC memo synthesizing due diligence findings, financial analysis, and deal terms.

If a company name is provided, use it. Otherwise ask the user for the target and available materials.
```

동일 골격: PE 10개 전부, IB 대부분 (`buyer-list`, `cim`, `deal-tracker`, `merger-model`, `process-letter`, `teaser`), FA (`lbo`, `debug-model`, `3-statement-model`, `competitive-analysis`), ER (`catalysts`, `earnings-preview`, `initiate`, `model-update`, `morning-note`, `screen`, `sector`, `thesis`).

**패턴 B — 장문 워크플로 + `skill: "name"` 도구 문법.** 커맨드가 스킬 위 오케스트레이션을 다시 적는다.

| 커맨드 | 바이트 | 로드 문법 | 스킬 |
|---|---|---|---|
| `equity-research/commands/earnings.md` | 4582 | `Use skill: "earnings-analysis"` | earnings-analysis |
| `financial-analysis/commands/comps.md` | 4425 | `Use skill: "comps-analysis"` | comps-analysis |
| `financial-analysis/commands/dcf.md` | 3259 | 먼저 `comps-analysis` 후 `dcf-model` | **2개 스킬** |
| `financial-analysis/commands/ppt-template.md` | 1190 | `skill: "ppt-template-creator"` | ppt-template-creator |
| `investment-banking/commands/one-pager.md` | 4121 | `skill: "[template-name]"` 후 `skill: "strip-profile"` | strip-profile (+ 선택 템플릿 스킬) |

`/dcf`는 커맨드가 스킬 체인을 강제한다: comps로 터미널 멀티플 → DCF. 스킬 자체는 서로를 모름.

**패턴 C — LSEG partner.** `See the **bond-futures-basis** skill for domain knowledge…` 볼드 이름 + MCP 툴 호출 시퀀스. `Load the \`…\` skill` / `skill: "…"` 문법 아님. 스킬은 도메인 지식, 커맨드는 툴 오케스트레이션.

### 5.3 커맨드 파일명 ≠ 스킬 디렉터리명

README Skill & Command 표와 파일 시스템 일치. 이름이 다른 쌍:

| 커맨드 파일 | 슬래시 | 스킬 디렉터리 |
|---|---|---|
| comps.md | `/comps` | comps-analysis |
| dcf.md | `/dcf` | dcf-model (+ comps-analysis) |
| lbo.md | `/lbo` | lbo-model |
| debug-model.md | `/debug-model` | audit-xls |
| ppt-template.md | `/ppt-template` | ppt-template-creator |
| earnings.md | `/earnings` | earnings-analysis |
| initiate.md | `/initiate` | initiating-coverage |
| screen.md | `/screen` | idea-generation |
| sector.md | `/sector` | sector-overview |
| thesis.md | `/thesis` | thesis-tracker |
| catalysts.md | `/catalysts` | catalyst-calendar |
| one-pager.md | `/one-pager` | strip-profile |
| cim.md | `/cim` | cim-builder |
| screen-deal.md | `/screen-deal` | deal-screening |
| source.md | `/source` | deal-sourcing |
| dd-prep.md | `/dd-prep` | dd-meeting-prep |
| portfolio.md | `/portfolio` | portfolio-monitoring |
| returns.md | `/returns` | returns-analysis |
| value-creation.md | `/value-creation` | value-creation-plan |
| proposal.md (삭제된 WM) | `/proposal` | investment-proposal |

이름이 같은 쌍: `3-statement-model`, `competitive-analysis`, `earnings-preview`, `model-update`, `morning-note`, `buyer-list`, `deal-tracker`, `merger-model`, `process-letter`, `teaser`, `ai-readiness`, `dd-checklist`, `ic-memo`, `unit-economics` 등.

### 5.4 스킬은 있고 커맨드는 없는 것 (현재 트리)

vertical README가 명시한 것 + 디렉터리 확인:

- financial-analysis: `clean-data-xls`, `deck-refresh`, `ib-check-deck`, `pptx-author`, `xlsx-author`, `skill-creator`
- investment-banking: `pitch-deck`, `datapack-builder`
- fund-admin 스킬 6개 전부 — `commands/` 디렉터리 없음. README Skill & Command 표에도 fund-admin/operations 섹션 없음.
- operations 스킬 2개 전부 — `commands/` 없음.

### 5.5 vertical별 커맨드 유무

| vertical | commands/*.md | skills | hooks.json | .mcp.json |
|---|---|---|---|---|
| financial-analysis | 7 | 13 | `{"hooks":{}}` | 있음 |
| equity-research | 9 | 9 | `{"hooks":{}}` | 없음 |
| investment-banking | 7 | 9 | `{"hooks":{}}` | 있음 |
| private-equity | 10 | 10 | `{"hooks":{}}` | 있음 |
| fund-admin | 0 | 6 | 없음 | 없음 |
| operations | 0 | 2 | 없음 | 없음 |

---

## 6. meeting-prep-agent 스킬 오리진

현재 번들: `client-review`, `client-report`, `investment-proposal`, `pptx-author`.

`pptx-author`만 vertical 소스 있음 (`financial-analysis`). 나머지 3개는 **현재 트리의 어떤 vertical에도 없다.** `sync-agent-skills.py`와 `check.py` 4b는 이 3개에 대해 실패한다.

### 6.1 git로 확인한 실제 출처

| 커밋 | 날짜 | 내용 |
|---|---|---|
| `bb4a2b3` / `a6d7d6b` (#81) | 2026-05-05 | `plugins/vertical-plugins/wealth-management/skills/{client-report,client-review,investment-proposal}/` **생성**. 동시에 agent 카피 생성. 당시 md5는 현재와 다름 (프론트매터 이전). |
| `ef165e4` / `8d59999` (#243) | (frontmatter 수정) | 세 파일 md5가 **현재와 일치**하기 시작. |
| `734150c` / `8e67ead` (#349) | 2026-09-11 | **wealth-management vertical 전체 삭제** (plugin.json, commands 6, skills 6, hooks). agent 카피는 남김. |
| `eefd376` / `6e7f94d` (#350) | (WM 삭제 이후) | `claude-for-financial-advisors/` **추가**. 스킬 이름이 다름 (아래). 세 WM 스킬을 포함하지 않음. |
| `574ed36` / `a829ed2` (#354) | 2026-09-21 | `claude-for-financial-advisors/` **삭제**. |

현재 orphan 3개의 SKILL.md md5는 `734150c^` 시점 wealth-management 소스와 **바이트 일치**. 즉 카피는 WM 삭제 직전 canonical과 같고, 그 이후 수정되지 않았다.

### 6.2 `claude-for-financial-advisors`는 대체물이 아님

런치 커밋 `6e7f94d` 트리의 스킬 (8):

`alts-brief`, `compliance`, `estate-and-tax-brief`, `onboarding`, `portfolio-rebalance-review`, `post-meeting`, `pre-meeting`, `prospect-intake`

에이전트 (6): `compliance-lookup`, `compliance-scan`, `holdings-sanity`, `source-extract`, `statement-extract`, `titling-compare`

`client-report` / `client-review` / `investment-proposal`은 advisors 플러그인에 **한 번도 없었다.** 미팅 프렙의 가장 가까운 advisors 쪽은 `pre-meeting` / `post-meeting` (다른 파일, 다른 워크플로).

삭제된 advisors `plugin.json` (git `6e7f94d`, 현재 트리에 없음):

- `name: claude-for-financial-advisors`
- `displayName: Claude for Financial Advisors` (현재 19개 plugin.json 중 이 키를 가진 것은 없음)
- `version: 1.0.0`
- `author.name: Anthropic — Asset & Wealth Management`

### 6.3 삭제된 wealth-management가 가지고 있던 것

`bb4a2b3` 트리:

- 스킬 6: `client-report`, `client-review`, `financial-plan`, `investment-proposal`, `portfolio-rebalance`, `tax-loss-harvesting`
- 커맨드 6: `client-report.md`, `client-review.md`, `financial-plan.md`, `proposal.md` (→ investment-proposal), `rebalance.md`, `tlh.md`
- plugin.json: `name: wealth-management`, `version: 0.1.2`, author Anthropic FSI

커맨드 래핑은 패턴 A. 예: `Load the \`client-report\` skill to generate…` / `Load the \`investment-proposal\` skill to create…`.

WM 삭제 후 meeting-prep-agent는 소스 vertical 없이 3개 스킬 카피만 보유. `financial-plan` / `portfolio-rebalance` / `tax-loss-harvesting`은 agent에도 vertical에도 없음.

### 6.4 README 잔존

README L113은 삭제된 advisors 플러그인을 vertical로 나열. marketplace는 미등록.

---

## 7. 체크섬: vertical canonical vs agent 카피

방법: 각 스킬 디렉터리 전체 파일 md5 맵 비교 + SKILL.md md5/sha256. 소스 있는 48개 번들 디렉터리: **SKILL.md 일치, 추가/누락 파일 0, 내용 드리프트 0.**

### 7.1 vertical unique SKILL.md (49)

| vertical | skill | files | md5 | sha256 |
|---|---|---|---|---|
| equity-research | catalyst-calendar | 1 | `02c430013efe59712a9013f37e070bb4` | `12ac4ae7659ab848a8910dfceadab5b21479f23c8d3e0c57a3f5bf814bcf8186` |
| equity-research | earnings-analysis | 4 | `68d70380e6b8b9a329452888700d2d24` | `4db857c27a53141b6ebc38ec9ee7f0020dec59cab084ae6753e53366d118c8ee` |
| equity-research | earnings-preview | 1 | `8b5ec5abb1d43234751b767302d53af9` | `a30d383a6f1c06b732b4d34e422dd2ff18f6340db67229a3347d057d52697f33` |
| equity-research | idea-generation | 1 | `7dedadb04a0b9b302390da9ae97e775c` | `e5f49f0f513fc434bb3448c8a942f6f99f66457e425a65b9375bb230922e9a45` |
| equity-research | initiating-coverage | 9 | `2b905c487f592cba0bae5fe95c6d40d0` | `9d21c6e460bc3692e19eeda6dc6d425a704b21243bd28af7f13b6f1dd888ed63` |
| equity-research | model-update | 1 | `ff200100a71c03358b326be3ef09d57d` | `62b2256bf3b52ac3759cb446a10aaa3066a51b4909e09bae0e3b98b741a37fb5` |
| equity-research | morning-note | 1 | `7c963e2eb7520bbc10b17df00afcfb95` | `38f0b36cd414bb0b702bdef0f7f3d53480f8338f8495286d7ebb012f0a92774c` |
| equity-research | sector-overview | 1 | `098af53b584bfd07a9a4d81fe3a81f74` | `8d4b7b47c3fe1591bde0a4260b1ffbe489e7ddbe3eddd3dbeb046ce29f315608` |
| equity-research | thesis-tracker | 1 | `722df1d96fabe0a2e9371b8a69018764` | `6b4ce2967c5e01c6b42f5c140fa1e94dee2713b5d2de3eb71957ff5a5c11469b` |
| financial-analysis | 3-statement-model | 4 | `bed22475d83090f218e7db5e88a2cdbf` | `bc2aeb423a3cc9e6ab973dcc4e3c6682427c751e20d8b3a0eec057eab67b1e83` |
| financial-analysis | audit-xls | 1 | `8aa9bcd5f999c81e56d0673ba61bbb1b` | `df771f6b90fc3b3d4996d5e8682ab00d4fa6f55beef308ea764b0f7a2a1c38e2` |
| financial-analysis | clean-data-xls | 1 | `720ad4b85075160f620fda98ea874645` | `f0dfceb01532a637b0edbbe15dbab9fe2d52279b140cea4ba8ba7823e46ad15b` |
| financial-analysis | competitive-analysis | 3 | `49c8c1a053b36dac01b2079399f007d9` | `65c6e2a68ba67660076e1f5b7d3602f71b3e97d3cdc1f2a6b03c12c05c24f1f9` |
| financial-analysis | comps-analysis | 1 | `6a5998e9f4a02a41b19f487ee3e26309` | `2d49d9d694297da6ca3b084564ce10ed496f4ff21f275dae6b6c50d7b4dd889a` |
| financial-analysis | dcf-model | 4 | `70e5fa1c75a7209e9a04de44baf16783` | `2bb3ed672ab2fa76f8820ee919b158a67dc6df10e7052eeb661599140a9a2494` |
| financial-analysis | deck-refresh | 1 | `03d0317ba4633fa388aca1e503d59be5` | `de179184d2d099fe8f895794aca1cc9e3801565a0b77b8143ba5dbcecb52fce5` |
| financial-analysis | ib-check-deck | 4 | `4bcff468ed69eceddf0fb1e05a4e8984` | `ddb30ad936035f2bb71acdc1dbf723663e74a3d2aba640f7bb84e6007f3210c1` |
| financial-analysis | lbo-model | 1 | `b580c003a781507c5062a2bd68d542a5` | `19749a568d6960137a2e0b83a2ac2215bf45c54d94a042626678e0bc955aaca7` |
| financial-analysis | ppt-template-creator | 1 | `19c3a81ad3fc0bd1fc98bc844a84556b` | `a117a538e70a2cf4f242a923b57651db15e2f945191352207bfd9d0464db6ef9` |
| financial-analysis | pptx-author | 1 | `ab93562b49447abe9feb85332f445bf9` | `db3f0f249787e2a4d5baf75daf9f5e96f151d1a84e89a1215cc59716a2e97bec` |
| financial-analysis | skill-creator | 7 | `b67fed4d1f7aea8cbb95d7fc9176faee` | `b2e3d83f60425c2d0b9d4162efb8f9aa322b45843497340f2289f42be422801c` |
| financial-analysis | xlsx-author | 1 | `34a4bcf8cfa35b0e82aeb94712c885a6` | `85b5b76901a7c53f9725220251ccf0f014dc5f66a3f100e762b64fddb368cfa6` |
| fund-admin | accrual-schedule | 1 | `ef4dc87b49aaad498b24e1736f3b759f` | `10974031f91be9048fa6ee7504a41a240322de7b618850b39ba0f68cc0f227ba` |
| fund-admin | break-trace | 1 | `b9a48c62dd0c884df96435ed007f7489` | `a7064b5cea13a4dc68f4b0ee36f8aa6efc70d738753c0eb721020bfb65932a9a` |
| fund-admin | gl-recon | 1 | `2dc9b5fe1c9dd22f083f38daded0802a` | `81029137f227ed9119107a659f58ad499cf375f67de834b9f553eddbba9f79e0` |
| fund-admin | nav-tieout | 1 | `ee1a24e6df73f3bf5c62c2bf561d2252` | `e0811592d89f02e4a2aa90676939a2781780538bff9dbbf9bba089fcca185f61` |
| fund-admin | roll-forward | 1 | `ff00a82da5b6ef4104397f910f62bd42` | `2d777fd303f933dfb4c15a2140c49eb490f6084dc889cc3e4b95ba2541c224c1` |
| fund-admin | variance-commentary | 1 | `0bd5a9758d3cc711155497d9a1b0f2f2` | `11624574b72c05756f62cb4a2d4888a2511d661ce58b1bf980577e03d9d36ea8` |
| investment-banking | buyer-list | 1 | `ae24ed02a76ec8a5aa577b92193b9a36` | `df6875147c70fc987f500c04d3743302a29ec6d97beead3c85f1b09bd8677b96` |
| investment-banking | cim-builder | 1 | `a538b9593af48b64ce2a3abf2f62fce7` | `b2cb7106d02595618631c69a5e60087db1d652901c573750decfb03a4b024487` |
| investment-banking | datapack-builder | 1 | `210e8716083624cada01cca7f3545733` | `eb5e83d1a166525eebab1b776ab6974feacee3e2a6332a7ee07b3b1821a1411e` |
| investment-banking | deal-tracker | 1 | `e89bd7dc92e69a8b220249dd215351b8` | `04538ceb21129667add105a5ae052f284cc3e2428d70d09c8c4634e69bb9cfa6` |
| investment-banking | merger-model | 1 | `75981d83532e88ecaa357cdfbc29b109` | `c4f758d64ad3818061cbe7200bb503510d80107f08a4f4d6ec444e709d99961f` |
| investment-banking | pitch-deck | 5 | `dbbbad7c23314cb66dd01d066ba6473c` | `118318d96bb794a42604c5899f3bb7db2692c23112f434d28b94a6c77a0313a6` |
| investment-banking | process-letter | 1 | `520f8420938f5f372b847b49dba6e01e` | `348771f577d943f8b46b64ee8cce6465d7419b51390f74a81d19f459e1582120` |
| investment-banking | strip-profile | 1 | `2bfa09c5ac5ce5bdcd57fc40ff40c8c7` | `16ec4d6055904e4dd3ecd26de5f94437e9d4e36755fd156d92e182165de9bcf0` |
| investment-banking | teaser | 1 | `35c7976a94c90c015e8502dc7460fccb` | `ec6ea35a740c40d4ba62b325483d6f63b0e06fc51202eeff6b01808a876c1020` |
| operations | kyc-doc-parse | 1 | `9b826b2846b1e4003d90dd745502fe05` | `cf826d96f0808195dbd4a10b5933e3824fc9ceef8858d637ad1e5d5bd8d6eef5` |
| operations | kyc-rules | 1 | `6cf2f28c3c5ba13b7376ab998533bf61` | `6da1bcd3eb5ab78db0150856841d68543266c7287858a9ca394c95afd51e80ec` |
| private-equity | ai-readiness | 1 | `0fb8db511da4ff9e20a39772754f85ec` | `b1bed0ae1234d16b5b7d3107edfcd064ea0bf0a53f01613b36a8f22f4372048b` |
| private-equity | dd-checklist | 1 | `c641c626d5aded2c30836844af8eb756` | `f2a8210587b7595fa642e8457b197ede9fa2ce4eb9f71bb25a26e7d707eddf8c` |
| private-equity | dd-meeting-prep | 1 | `6c87458ad2b3a5b0bf5516a977177878` | `a74eecadece794106d515ce3d00e07b3857ed123e841e8962e26363d2413d94f` |
| private-equity | deal-screening | 1 | `6ebdd6dd61b6c925dc9380158b834f6d` | `6d3aaf149316ac10949b5ab1654bd2b37870f23c5965eec80a8fdc0c7e80303e` |
| private-equity | deal-sourcing | 1 | `9f5486624bc966afbfd75c9e3dab15fe` | `47429d5cb48067b6d62b4f1c4e86fb608c873df2c41abf8d2da7a52f9d7beaf4` |
| private-equity | ic-memo | 1 | `1f9280d53f9f5161de9c73863b7e662a` | `62ab741880a946ab3e738b1f1514cb44b4e8b4f8b1d2e7b42c1e1ba5fcbb417f` |
| private-equity | portfolio-monitoring | 1 | `84380f5b45f39aeb7a9b063da56747b8` | `7a3b7bbd66109e334b39d7c154d2f6375b7501671c06fccab206bb2bcd345640` |
| private-equity | returns-analysis | 1 | `a9ed1042cb9b7adb01c5078643403722` | `362f2a713bc519f2b22721cb2f3b788fd9eb0a17b20a8a736697c7c995c7abab` |
| private-equity | unit-economics | 1 | `33cb500c5aa416fd00440a0213d02b4a` | `e2d1493ca6d312723eb60132ec0ab155d8c763761fd47a5af79ca93a701d6ac3` |
| private-equity | value-creation-plan | 1 | `083a5b5524635dd8412c6e1e95401aa7` | `3440bd7821020634b2bc1a566bb76ff4199e9645fdaac2a8db4e13a683809336` |

### 7.2 orphan (vertical 소스 없음)

| skill | 위치 | md5 | sha256 |
|---|---|---|---|
| client-report | meeting-prep-agent only | `8756898cf3ddceb5dc38cd8179cbf2a8` | `bbfede2e0dab00ae368767e51576498c9308b4832aaeaaa77f0fee723a90e4d4` |
| client-review | meeting-prep-agent only | `f8f75ddcc850439084939df597ddac29` | `ad848eac45494aa27263feb5e24e08e4ffd3fb613a747d55956e5b92935a9e98` |
| investment-proposal | meeting-prep-agent only | `89df49d334e6e5e43c36e7d90a949f10` | `69cecd980f44a61b5e429757aeae5968702106e2154f8afb3dd7ff8b0103f7c2` |

이 세 md5는 삭제된 `plugins/vertical-plugins/wealth-management/skills/<name>/SKILL.md` at `ef165e4`–`734150c^`와 동일.

---

## 8. Skill × Agent 번들링 매트릭스

열 = `plugins/agent-plugins/<slug>/skills/`에 디렉터리가 있으면 ●.  
`agents/<slug>.md`의 `## Skills this agent uses` backtick 목록에 없으면 `●*` (번들은 됐으나 프롬프트 목록 누락).  
CMA cookbook `managed-agent-cookbooks/<slug>/agent.yaml`은 전부 `skills: [{ from_plugin: ../../plugins/agent-plugins/<slug> }]` — 플러그인 스킬 디렉터리 전체를 가져오므로 아래 열과 동일.

약어: PA=pitch-agent, MR=market-researcher, ER=earnings-reviewer, MPA=meeting-prep-agent, MB=model-builder, GL=gl-reconciler, KYC=kyc-screener, VR=valuation-reviewer, MEC=month-end-closer, SA=statement-auditor.

### 8.1 번들된 스킬 (agent 열에 하나라도 ●)

| skill | canonical vertical | PA | MR | ER | MPA | MB | GL | KYC | VR | MEC | SA | n |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3-statement-model | financial-analysis | ● | | | | ● | | | | | | 2 |
| audit-xls | financial-analysis | ● | | ● | | ● | ● | | | ● | ● | 6 |
| competitive-analysis | financial-analysis | | ● | | | | | | | | | 1 |
| comps-analysis | financial-analysis | ● | ● | | | ● | | | | | | 3 |
| dcf-model | financial-analysis | ● | | | | ● | | | | | | 2 |
| deck-refresh | financial-analysis | ● | | | | | | | | | | 1 |
| ib-check-deck | financial-analysis | ● | | | | | | | | | | 1 |
| lbo-model | financial-analysis | ● | | | | ● | | | | | | 2 |
| pptx-author | financial-analysis | ●* | ● | | ● | | | | | | | 3 |
| xlsx-author | financial-analysis | ●* | | ●* | | ●* | ● | ● | ● | ● | ● | 8 |
| earnings-analysis | equity-research | | | ● | | | | | | | | 1 |
| earnings-preview | equity-research | | | ● | | | | | | | | 1 |
| idea-generation | equity-research | | ● | | | | | | | | | 1 |
| model-update | equity-research | | | ● | | | | | | | | 1 |
| morning-note | equity-research | | | ● | | | | | | | | 1 |
| sector-overview | equity-research | ● | ● | | | | | | | | | 2 |
| pitch-deck | investment-banking | ● | | | | | | | | | | 1 |
| accrual-schedule | fund-admin | | | | | | | | | ● | | 1 |
| break-trace | fund-admin | | | | | | ● | | | | | 1 |
| gl-recon | fund-admin | | | | | | ● | | | | | 1 |
| nav-tieout | fund-admin | | | | | | | | | | ● | 1 |
| roll-forward | fund-admin | | | | | | | | | ● | | 1 |
| variance-commentary | fund-admin | | | | | | | | | ● | | 1 |
| kyc-doc-parse | operations | | | | | | | ● | | | | 1 |
| kyc-rules | operations | | | | | | | ● | | | | 1 |
| ic-memo | private-equity | | | | | | | | ● | | | 1 |
| portfolio-monitoring | private-equity | | | | | | | | ● | | | 1 |
| returns-analysis | private-equity | | | | | | | | ● | | | 1 |
| client-report | **없음** (구 wealth-management) | | | | ● | | | | | | | 1 |
| client-review | **없음** (구 wealth-management) | | | | ● | | | | | | | 1 |
| investment-proposal | **없음** (구 wealth-management) | | | | ● | | | | | | | 1 |

`●*` 상세: ER·MB·PA의 `xlsx-author`, PA의 `pptx-author`는 디스크에 있으나 해당 `agents/<slug>.md` "Skills this agent uses" 줄에 없음. check.py 4b2는 "vertical에 있는 이름을 프롬프트가 말하는데 번들 없음"만 잡고, 반대 방향(번들됐는데 프롬프트 미기재)은 안 잡는다.

### 8.2 에이전트별 번들 목록 (디렉터리 = 진실)

| agent | plugin.json ver | 번들 디렉터리 (정렬) | agent.md 미기재 |
|---|---|---|---|
| pitch-agent | 0.1.1 | 3-statement-model, audit-xls, comps-analysis, dcf-model, deck-refresh, ib-check-deck, lbo-model, pitch-deck, pptx-author, sector-overview, xlsx-author | pptx-author, xlsx-author |
| market-researcher | 0.1.1 | competitive-analysis, comps-analysis, idea-generation, pptx-author, sector-overview | — |
| earnings-reviewer | 0.1.1 | audit-xls, earnings-analysis, earnings-preview, model-update, morning-note, xlsx-author | xlsx-author |
| meeting-prep-agent | 0.1.1 | client-report, client-review, investment-proposal, pptx-author | — |
| model-builder | 0.1.0 | 3-statement-model, audit-xls, comps-analysis, dcf-model, lbo-model, xlsx-author | xlsx-author |
| gl-reconciler | 0.1.0 | audit-xls, break-trace, gl-recon, xlsx-author | — |
| kyc-screener | 0.1.0 | kyc-doc-parse, kyc-rules, xlsx-author | — |
| valuation-reviewer | 0.1.1 | ic-memo, portfolio-monitoring, returns-analysis, xlsx-author | — |
| month-end-closer | 0.1.0 | accrual-schedule, audit-xls, roll-forward, variance-commentary, xlsx-author | — |
| statement-auditor | 0.1.0 | audit-xls, nav-tieout, xlsx-author | — |

공유 빈도: `xlsx-author` 8 · `audit-xls` 6 · `pptx-author` 3 · `comps-analysis` 3 · `3-statement-model`/`dcf-model`/`lbo-model`/`sector-overview` 2 · 나머지 1.

### 8.3 vertical에만 있고 어떤 agent에도 없는 스킬 (21)

| vertical | skill | 대응 커맨드 (있으면) |
|---|---|---|
| equity-research | catalyst-calendar | `/catalysts` |
| equity-research | initiating-coverage | `/initiate` |
| equity-research | thesis-tracker | `/thesis` |
| financial-analysis | clean-data-xls | 없음 |
| financial-analysis | ppt-template-creator | `/ppt-template` |
| financial-analysis | skill-creator | 없음 |
| investment-banking | buyer-list | `/buyer-list` |
| investment-banking | cim-builder | `/cim` |
| investment-banking | datapack-builder | 없음 |
| investment-banking | deal-tracker | `/deal-tracker` |
| investment-banking | merger-model | `/merger-model` |
| investment-banking | process-letter | `/process-letter` |
| investment-banking | strip-profile | `/one-pager` |
| investment-banking | teaser | `/teaser` |
| private-equity | ai-readiness | `/ai-readiness` |
| private-equity | dd-checklist | `/dd-checklist` |
| private-equity | dd-meeting-prep | `/dd-prep` |
| private-equity | deal-screening | `/screen-deal` |
| private-equity | deal-sourcing | `/source` |
| private-equity | unit-economics | `/unit-economics` |
| private-equity | value-creation-plan | `/value-creation` |

IB 스킬 9개 중 agent에 실리는 것은 `pitch-deck` 하나. PE 10개 중 3개만 (`ic-memo`, `portfolio-monitoring`, `returns-analysis` → valuation-reviewer). ER 9개 중 6개가 earnings-reviewer 또는 market-researcher/pitch-agent로 감. fund-admin 6개 전부 어떤 ops 에이전트엔가 실림. operations 2개 전부 kyc-screener.

### 8.4 partner-built (sync 매핑 밖)

LSEG 8 스킬 (커맨드가 볼드로 참조): bond-futures-basis, bond-relative-value, equity-research, fixed-income-portfolio, fx-carry-trade, macro-rates-monitor, option-vol-analysis, swap-curve-strategy.

S&P Global 3: `tear-sheet`, `funding-digest`, `earnings-preview-beta` (frontmatter name `earnings-preview-single`).

이 11개는 agent-plugins에 복사되지 않는다.

### 8.5 CMA 연결

10개 cookbook 전부 `from_plugin`으로 해당 agent-plugin 루트를 가리킨다. 스킬 path를 개별로 나열하지 않음. 따라서 번들 매트릭스 = Cowork 플러그인 매트릭스 = CMA 스킬 집합.

---

## 9. 관찰된 불일치 (발명 없이 파일에서)

1. `sync-agent-skills.py` / `check.py`는 meeting-prep 3 스킬에 대해 **현재 실패**해야 한다 (소스 없음). 카피 자체는 구 wealth-management과 바이트 일치.
2. README는 삭제된 `claude-for-financial-advisors`를 링크. marketplace·디렉터리에는 없음. advisors 스킬 세트는 WM/meeting-prep 세트와 교집합 0.
3. `strip-profile` 디렉터리 vs `name: fsi-strip-profile`. `earnings-preview-beta` vs `name: earnings-preview-single`.
4. `investment-banking` plugin.json author가 `"Anthropic"` (다른 FSI 플러그인은 `"Anthropic FSI"`).
5. `xlsx-author`/`pptx-author`가 일부 agent.md 목록에서 빠짐 (디스크에는 있음).
6. fund-admin·operations는 커맨드 없음. README Skill & Command 표에도 두 vertical이 없음.
7. `skill-creator`는 프론트매터에 name+description만 두라고 하면서 자신은 `license`를 둔다.
8. `pitch-deck`만 `reference/` (단수). 다른 스킬은 `references/`.
9. 키 순서: 대부분 plugin.json이 `name, version, description, author`. msft-365와 sp-global은 `name, description, version, author`.

---

## 10. 근거 파일

- `/Users/yeonwoosung/Desktop/financial-services/scripts/sync-agent-skills.py` (전문)
- `/Users/yeonwoosung/Desktop/financial-services/scripts/check.py` (§4b, 4b2)
- `/Users/yeonwoosung/Desktop/financial-services/.claude-plugin/marketplace.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/{agent,vertical,partner-built}-plugins/**/.claude-plugin/plugin.json` (18) + `claude-for-msft-365-install/.claude-plugin/plugin.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/*/skills/*/SKILL.md` (49)
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/*/skills/*/SKILL.md` (51 dirs)
- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/*/commands/*.md` (33)
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/*/agents/*.md` (10)
- git: `bb4a2b3`, `ef165e4`, `734150c`, `6e7f94d`, `574ed36`
