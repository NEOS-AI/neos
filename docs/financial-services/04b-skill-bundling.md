# 09. Skill 저자 패턴, 공유 스킬, 에이전트 번들링

Repo: `/Users/yeonwoosung/Desktop/financial-services`  
조사 기준 커밋: 워크스페이스 HEAD (2026-09-25 체크아웃).  
방법: `scripts/sync-agent-skills.py`를 매핑 소스 오브 트루스로 사용하고, 디렉터리 해시로 vertical ↔ agent 복제본을 비교했다. `plugin.json` / `marketplace.json` / `SKILL.md` / `commands/*.md` / `agent.yaml` / git history를 전부 읽었다.

**발명하지 않음.** 아래는 파일에서 관측된 내용만 적는다.

---

## 1. 한 줄 결론

- Canonical skill 원본은 `plugins/vertical-plugins/<vertical>/skills/<name>/` 이다. Agent plugin은 그 디렉터리를 `plugins/agent-plugins/<slug>/skills/<name>/` 로 **통째로 복사**한다 (`scripts/sync-agent-skills.py`).
- 해시 비교 결과: **48/51 agent-bundled skill 디렉터리가 vertical 원본과 byte-identical**. Drift 0. **3개는 vertical 원본이 없다** — `meeting-prep-agent`의 `client-report`, `client-review`, `investment-proposal`.
- `plugin.json`은 컴포넌트 목록을 담지 않는다. Cowork는 디렉터리 관례로 agents/skills/commands/hooks를 발견하고, CMA는 `managed-agent-cookbooks/<slug>/agent.yaml`의 `skills.from_plugin`으로 같은 번들을 업로드한다.
- Headless Office 산출은 `pptx-author` / `xlsx-author` (CMA `./out/` 계약). `audit-xls` / `clean-data-xls`는 라이브 Excel 감사·정제. `skill-creator` / `ppt-template-creator`는 메타 스킬이며 **어떤 agent에도 번들되지 않는다**.
- README가 가리키는 `claude-for-financial-advisors` 디렉터리는 **없다** (`#354`, 2026-09-21 삭제). wealth-management vertical도 **없다** (`#349`, 2026-09-11 삭제). meeting-prep 3스킬은 그 삭제 이후 orphan copy로 남았다.

---

## 2. 아키텍처: 한 소스, 두 래퍼

`CLAUDE.md` / `README.md`가 명시한 레이아웃:

```
plugins/
  agent-plugins/<slug>/
    .claude-plugin/plugin.json
    agents/<slug>.md          # canonical system prompt
    skills/                   # vendored copies from vertical-plugins/
  vertical-plugins/<vertical>/
    .claude-plugin/plugin.json
    commands/                 # slash commands (agent plugin에는 없음)
    skills/                   # SOURCE OF TRUTH
    hooks/hooks.json          # 일부 vertical만, 내용은 {"hooks":{}}
    .mcp.json                 # financial-analysis, investment-banking, private-equity
  partner-built/{lseg,spglobal}/
managed-agent-cookbooks/<slug>/
  agent.yaml                  # system.file → agent-plugins/<slug>/agents/<slug>.md
                              # skills.from_plugin → agent-plugins/<slug>
```

`scripts/sync-agent-skills.py` (매핑 소스 오브 트루스)는 **이름 기반 인덱스**만 쓴다. 어떤 agent가 무엇을 번들하는지는 스크립트에 하드코딩되어 있지 않다. Agent 쪽 `skills/<name>/` 디렉터리 존재가 곧 매핑이다.

```python
src_by_name: dict[str, Path] = {}
for sk in VERTICALS.glob("*/skills/*"):
    if sk.is_dir():
        src_by_name[sk.name] = sk

for bundled in sorted(AGENTS.glob("*/skills/*")):
    src = src_by_name.get(bundled.name)
    if not src:
        missing.append(...)
        continue
    shutil.rmtree(bundled)
    shutil.copytree(src, bundled)
```

동명 스킬이 두 vertical에 있으면 **glob 순회에서 나중에 나온 쪽이 이긴다**. 현재 워크스페이스에서는 동명 충돌 없음 (skill 디렉터리 이름 49개 unique).

`scripts/check.py` §4b는 같은 인덱스로 `filecmp.dircmp` drift 검사를 한다. vertical 원본이 없으면 error:

```
bundled-skill: plugins/agent-plugins/meeting-prep-agent/skills/<name>: no vertical-plugins source named '<name>'
```

현재 트리에서 `python3 scripts/sync-agent-skills.py`와 `python3 scripts/check.py`는 이 3개 때문에 **exit 1**이 된다.

---

## 3. Unique SKILL.md 인벤토리

전 레포 `SKILL.md` = **112개** (agent 복제본 포함). Unique 원본:

| 위치 | Unique skill 수 | 비고 |
|---|---|---|
| `plugins/vertical-plugins/` | **49** | canonical |
| `plugins/agent-plugins/` 전용 (vertical 없음) | **3** | meeting-prep orphan |
| `plugins/partner-built/lseg/` | **8** | agent에 번들되지 않음 |
| `plugins/partner-built/spglobal/` | **3** | agent에 번들되지 않음 |
| `claude-for-msft-365-install/.claude/skills/` | **1** (`verify`) | admin 플러그인 내부, FSI 워크플로 아님 |

Vertical 49 + orphan 3 = **52** FSI domain skills. Partner 11은 별도 플러그인. `verify`는 msft-365 설치 검증용.

### 3.1 Vertical 원본 (49) — 디렉터리 해시

해시 = 디렉터리 내 모든 파일의 `rel:sha256[:12]:size` fingerprint (`fp` 16 hex).

#### equity-research (9)

| skill | nfiles | extras |
|---|---|---|
| catalyst-calendar | 1 | — |
| earnings-analysis | 4 | `references/{best-practices,report-structure,workflow}.md` |
| earnings-preview | 1 | — |
| idea-generation | 1 | — |
| initiating-coverage | 9 | `assets/{quality-checklist,report-template}.md` + `references/task{1-5}-*.md` + `valuation-methodologies.md` |
| model-update | 1 | — |
| morning-note | 1 | — |
| sector-overview | 1 | — |
| thesis-tracker | 1 | — |

#### financial-analysis (13) — 공유/메타 포함

| skill | nfiles | extras |
|---|---|---|
| 3-statement-model | 4 | `references/{formatting,formulas,sec-filings}.md` |
| audit-xls | 1 | — |
| clean-data-xls | 1 | — |
| competitive-analysis | 3 | `references/{frameworks,schemas}.md` |
| comps-analysis | 1 | SKILL.md 661 lines (references 없음) |
| dcf-model | 4 | `scripts/validate_dcf.py`, `requirements.txt`, `TROUBLESHOOTING.md` |
| deck-refresh | 1 | — |
| ib-check-deck | 4 | `references/{ib-terminology,report-format}.md`, `scripts/extract_numbers.py` |
| lbo-model | 1 | — |
| ppt-template-creator | 1 | — |
| pptx-author | 1 | — |
| skill-creator | 7 | `LICENSE.txt`, `references/{output-patterns,workflows}.md`, `scripts/{init_skill,package_skill,quick_validate}.py` |
| xlsx-author | 1 | — |

#### fund-admin (6) — 전부 SKILL.md only

accrual-schedule, break-trace, gl-recon, nav-tieout, roll-forward, variance-commentary.

#### investment-banking (9)

| skill | extras |
|---|---|
| buyer-list, cim-builder, datapack-builder, deal-tracker, merger-model, process-letter, teaser | SKILL.md only |
| pitch-deck | `reference/` (**복수형 아님**) `{calculation-standards,formatting-standards,slide-templates,xml-reference}.md` |
| strip-profile | SKILL.md only. frontmatter `name: fsi-strip-profile` ≠ dir `strip-profile` |

#### operations (2)

kyc-doc-parse, kyc-rules. SKILL.md only.

#### private-equity (10)

ai-readiness, dd-checklist, dd-meeting-prep, deal-screening, deal-sourcing, ic-memo, portfolio-monitoring, returns-analysis, unit-economics, value-creation-plan. 전부 SKILL.md only.

### 3.2 Agent 번들 비교 결과

- MATCH 48
- DRIFT 0
- MISSING vertical source 3 (`client-report`, `client-review`, `investment-proposal`)

Agent가 번들하지 않는 vertical skills (21):

ai-readiness, buyer-list, catalyst-calendar, cim-builder, **clean-data-xls**, datapack-builder, dd-checklist, dd-meeting-prep, deal-screening, deal-sourcing, deal-tracker, initiating-coverage, merger-model, **ppt-template-creator**, process-letter, **skill-creator**, strip-profile, teaser, thesis-tracker, unit-economics, value-creation-plan.

이 21개는 Cowork에서 해당 vertical plugin을 설치해야만 쓸 수 있다. CMA 쿡북은 agent 번들만 업로드하므로 여기 없다.

---

## 4. 매트릭스: unique skill × agent plugin

열 약어:

| 약어 | agent plugin |
|---|---|
| ER | earnings-reviewer |
| GL | gl-reconciler |
| KY | kyc-screener |
| MR | market-researcher |
| MP | meeting-prep-agent |
| MB | model-builder |
| ME | month-end-closer |
| PA | pitch-agent |
| SA | statement-auditor |
| VR | valuation-reviewer |

`●` = 번들됨, 해시 MATCH. `○` = 번들됨, vertical 원본 없음. 빈칸 = 미번들.

### 4.1 financial-analysis 원본

| skill | ER | GL | KY | MR | MP | MB | ME | PA | SA | VR | vertical source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 3-statement-model | | | | | | ● | | ● | | | `plugins/vertical-plugins/financial-analysis/skills/3-statement-model` |
| audit-xls | ● | ● | | | | ● | ● | ● | ● | | `.../financial-analysis/skills/audit-xls` |
| clean-data-xls | | | | | | | | | | | `.../financial-analysis/skills/clean-data-xls` |
| competitive-analysis | | | | ● | | | | | | | `.../financial-analysis/skills/competitive-analysis` |
| comps-analysis | | | | ● | | ● | | ● | | | `.../financial-analysis/skills/comps-analysis` |
| dcf-model | | | | | | ● | | ● | | | `.../financial-analysis/skills/dcf-model` |
| deck-refresh | | | | | | | | ● | | | `.../financial-analysis/skills/deck-refresh` |
| ib-check-deck | | | | | | | | ● | | | `.../financial-analysis/skills/ib-check-deck` |
| lbo-model | | | | | | ● | | ● | | | `.../financial-analysis/skills/lbo-model` |
| ppt-template-creator | | | | | | | | | | | `.../financial-analysis/skills/ppt-template-creator` |
| pptx-author | | | | ● | ● | | | ● | | | `.../financial-analysis/skills/pptx-author` |
| skill-creator | | | | | | | | | | | `.../financial-analysis/skills/skill-creator` |
| xlsx-author | ● | ● | ● | | | ● | ● | ● | ● | ● | `.../financial-analysis/skills/xlsx-author` |

`xlsx-author`는 10개 agent 중 **8개**에 들어간다 (MR, MP 제외 — 둘은 덱/브리핑 쪽이라 `pptx-author`). `audit-xls`는 6개. `pptx-author`는 3개 (MR, MP, PA).

### 4.2 equity-research 원본

| skill | ER | GL | KY | MR | MP | MB | ME | PA | SA | VR | vertical source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| catalyst-calendar | | | | | | | | | | | `.../equity-research/skills/catalyst-calendar` |
| earnings-analysis | ● | | | | | | | | | | `.../equity-research/skills/earnings-analysis` |
| earnings-preview | ● | | | | | | | | | | `.../equity-research/skills/earnings-preview` |
| idea-generation | | | | ● | | | | | | | `.../equity-research/skills/idea-generation` |
| initiating-coverage | | | | | | | | | | | `.../equity-research/skills/initiating-coverage` |
| model-update | ● | | | | | | | | | | `.../equity-research/skills/model-update` |
| morning-note | ● | | | | | | | | | | `.../equity-research/skills/morning-note` |
| sector-overview | | | | ● | | | | ● | | | `.../equity-research/skills/sector-overview` |
| thesis-tracker | | | | | | | | | | | `.../equity-research/skills/thesis-tracker` |

### 4.3 fund-admin 원본

| skill | ER | GL | KY | MR | MP | MB | ME | PA | SA | VR | vertical source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| accrual-schedule | | | | | | | ● | | | | `.../fund-admin/skills/accrual-schedule` |
| break-trace | | ● | | | | | | | | | `.../fund-admin/skills/break-trace` |
| gl-recon | | ● | | | | | | | | | `.../fund-admin/skills/gl-recon` |
| nav-tieout | | | | | | | | | ● | | `.../fund-admin/skills/nav-tieout` |
| roll-forward | | | | | | | ● | | | | `.../fund-admin/skills/roll-forward` |
| variance-commentary | | | | | | | ● | | | | `.../fund-admin/skills/variance-commentary` |

### 4.4 investment-banking 원본

| skill | ER | GL | KY | MR | MP | MB | ME | PA | SA | VR | vertical source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| buyer-list | | | | | | | | | | | `.../investment-banking/skills/buyer-list` |
| cim-builder | | | | | | | | | | | `.../investment-banking/skills/cim-builder` |
| datapack-builder | | | | | | | | | | | `.../investment-banking/skills/datapack-builder` |
| deal-tracker | | | | | | | | | | | `.../investment-banking/skills/deal-tracker` |
| merger-model | | | | | | | | | | | `.../investment-banking/skills/merger-model` |
| pitch-deck | | | | | | | | ● | | | `.../investment-banking/skills/pitch-deck` |
| process-letter | | | | | | | | | | | `.../investment-banking/skills/process-letter` |
| strip-profile | | | | | | | | | | | `.../investment-banking/skills/strip-profile` |
| teaser | | | | | | | | | | | `.../investment-banking/skills/teaser` |

IB 9개 중 agent에 들어가는 것은 **pitch-deck 하나** (pitch-agent). 나머지 8개는 slash command vertical 전용.

### 4.5 operations 원본

| skill | ER | GL | KY | MR | MP | MB | ME | PA | SA | VR | vertical source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| kyc-doc-parse | | | ● | | | | | | | | `.../operations/skills/kyc-doc-parse` |
| kyc-rules | | | ● | | | | | | | | `.../operations/skills/kyc-rules` |

### 4.6 private-equity 원본

| skill | ER | GL | KY | MR | MP | MB | ME | PA | SA | VR | vertical source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ai-readiness | | | | | | | | | | | `.../private-equity/skills/ai-readiness` |
| dd-checklist | | | | | | | | | | | `.../private-equity/skills/dd-checklist` |
| dd-meeting-prep | | | | | | | | | | | `.../private-equity/skills/dd-meeting-prep` |
| deal-screening | | | | | | | | | | | `.../private-equity/skills/deal-screening` |
| deal-sourcing | | | | | | | | | | | `.../private-equity/skills/deal-sourcing` |
| ic-memo | | | | | | | | | | ● | `.../private-equity/skills/ic-memo` |
| portfolio-monitoring | | | | | | | | | | ● | `.../private-equity/skills/portfolio-monitoring` |
| returns-analysis | | | | | | | | | | ● | `.../private-equity/skills/returns-analysis` |
| unit-economics | | | | | | | | | | | `.../private-equity/skills/unit-economics` |
| value-creation-plan | | | | | | | | | | | `.../private-equity/skills/value-creation-plan` |

PE 10개 중 agent에 들어가는 것은 valuation-reviewer의 3개뿐.

### 4.7 Orphan (vertical 없음) — meeting-prep-agent only

| skill | ER | GL | KY | MR | MP | MB | ME | PA | SA | VR | vertical source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| client-report | | | | | ○ | | | | | | **없음** (구 `wealth-management`) |
| client-review | | | | | ○ | | | | | | **없음** |
| investment-proposal | | | | | ○ | | | | | | **없음** |

### 4.8 Partner skills — 어떤 agent에도 번들되지 않음

**lseg** (8): bond-futures-basis, bond-relative-value, equity-research, fixed-income-portfolio, fx-carry-trade, macro-rates-monitor, option-vol-analysis, swap-curve-strategy.

**spglobal** (3): earnings-preview-beta (`name: earnings-preview-single` ≠ dir), funding-digest, tear-sheet.

Partner는 `marketplace.json`에 별도 플러그인으로 등록되고, Cowork에서 `lseg` / `sp-global`을 따로 설치한다. CMA 쿡북 `skills.from_plugin`은 agent-plugins만 가리키므로 partner 스킬은 CMA 경로에 없다.

### 4.9 Agent별 번들 목록 (sync 스크립트가 실제로 복사하는 것)

| agent | bundled skills (dir names) | agent.md "Skills this agent uses" | bundled-not-listed |
|---|---|---|---|
| earnings-reviewer | audit-xls, earnings-analysis, earnings-preview, model-update, morning-note, xlsx-author | earnings-analysis · model-update · audit-xls · morning-note · earnings-preview | **xlsx-author** |
| gl-reconciler | audit-xls, break-trace, gl-recon, xlsx-author | 일치 | — |
| kyc-screener | kyc-doc-parse, kyc-rules, xlsx-author | 일치 | — |
| market-researcher | competitive-analysis, comps-analysis, idea-generation, pptx-author, sector-overview | 일치 | — |
| meeting-prep-agent | client-report, client-review, investment-proposal, pptx-author | 일치 | — |
| model-builder | 3-statement-model, audit-xls, comps-analysis, dcf-model, lbo-model, xlsx-author | dcf-model · lbo-model · 3-statement-model · comps-analysis · audit-xls | **xlsx-author** |
| month-end-closer | accrual-schedule, audit-xls, roll-forward, variance-commentary, xlsx-author | 일치 | — |
| pitch-agent | 3-statement-model, audit-xls, comps-analysis, dcf-model, deck-refresh, ib-check-deck, lbo-model, pitch-deck, pptx-author, sector-overview, xlsx-author | sector-overview · comps-analysis · lbo-model · dcf-model · 3-statement-model · audit-xls · pitch-deck · ib-check-deck · deck-refresh | **pptx-author, xlsx-author** |
| statement-auditor | audit-xls, nav-tieout, xlsx-author | 일치 | — |
| valuation-reviewer | ic-memo, portfolio-monitoring, returns-analysis, xlsx-author | 일치 | — |

`check.py` §4b2는 agent.md가 참조하는 스킬이 번들에 **없으면** 실패한다. 반대(번들됐는데 안 적힘)는 검사하지 않는다. 그래서 xlsx-author / pptx-author 누락 표기는 lint를 통과한다. 이 두 스킬은 CMA 서브에이전트 yaml에서 직접 `path:`로 다시 걸린다 (아래 §7).

---

## 5. SHARED / META 스킬 전문 요약

여섯 개 모두 `plugins/vertical-plugins/financial-analysis/skills/` 아래. skill-creator가 말하는 "harness" 역할과 CMA headless Office 경로가 여기서 갈린다.

### 5.1 skill-creator

Frontmatter: `name`, `description`, **`license: Complete terms in LICENSE.txt`** (레포에서 license 키를 쓰는 유일한 SKILL.md).

역할: 새 스킬을 만드는 가이드. Progressive disclosure 3단:

1. Metadata (`name` + `description`) — 항상 컨텍스트 (~100 words)
2. SKILL.md body — 트리거 후 (<5k words, **500 lines 권고**)
3. Bundled resources — 필요 시 (scripts는 읽지 않고 실행 가능)

Anatomy (스킬 자신이 규정):

```
skill-name/
├── SKILL.md
│   ├── YAML: name (required), description (required)
│   └── Markdown body
└── Bundled Resources (optional)
    ├── scripts/     executable
    ├── references/  load-into-context docs
    └── assets/      output templates, not loaded
```

Frontmatter 작성 규칙 (본문 Step 4):

> Do not include any other fields in YAML frontmatter.

같은 스킬의 `scripts/quick_validate.py`는 허용 키를 `{name, description, license, allowed-tools, metadata}`로 둔다. **자기모순.** 실제 사용: `name`+`description` 111/112, `license` 1/112, `allowed-tools` **0/112**, `metadata` **0/112**.

Description 규칙: WHAT + WHEN을 description에 넣을 것. Body의 "When to Use"는 트리거 후에만 로드되므로 트리거에는 무용. 금지: description 안 `<>` (quick_validate), 1024자, name 64자 hyphen-case.

동봉 스크립트:

- `scripts/init_skill.py` — 템플릿 디렉터리 생성 (`--path`)
- `scripts/package_skill.py` — `.skill` zip 패키징
- `scripts/quick_validate.py` — frontmatter lint

동봉 레퍼런스: `references/workflows.md` (sequential / conditional), `references/output-patterns.md` (template vs examples).

"What to Not Include": README.md, INSTALLATION_GUIDE.md, QUICK_REFERENCE.md, CHANGELOG.md. 그런데 `dcf-model`은 `TROUBLESHOOTING.md`를 갖고, `skill-creator` 자신은 `LICENSE.txt`를 갖는다.

**Agent 번들: 없음.** `/ppt-template` 커맨드가 간접 참조 ("For general skill-building best practices, refer to the skill-creator skill").

### 5.2 pptx-author — CMA PowerPoint harness

43 lines. Description: `Produce a .pptx file on disk (headless) instead of driving a live PowerPoint document — for managed-agent sessions with no open Office app.`

계약:

- Write `./out/<name>.pptx`. `./out/` 없으면 생성.
- 최종 메시지에 relative path를 넣어 orchestration이 collect.

구현: Bash로 짧은 Python, `python-pptx`. 템플릿이 `./templates/firm-template.pptx`에 있으면 사용.

When NOT: `mcp__office__powerpoint_*`가 있으면 (Cowork) 라이브 문서를 드라이브. 이 스킬은 headless fallback.

번들: market-researcher, meeting-prep-agent, pitch-agent.

CMA leaf: `market-researcher/subagents/note-writer.yaml` → pptx-author; `meeting-prep-agent/subagents/pack-writer.yaml` → pptx-author; `pitch-agent/subagents/deck-writer.yaml` → pptx-author + pitch-deck + xlsx-author.

### 5.3 xlsx-author — CMA Excel harness

42 lines. 대칭 계약: `./out/<name>.xlsx`, `openpyxl`, `mcp__office__excel_*`가 있으면 쓰지 말 것.

컨벤션 (audit-xls를 mirror):

- Blue = hardcoded input, black = formula, green = cross-sheet link
- 계산 셀에 hardcode 금지. Inputs 탭.
- Named ranges. Checks 탭 TRUE/FALSE.
- One model per file.

번들: ER, GL, KY, MB, ME, PA, SA, VR (8). MR/MP는 pptx만.

거의 모든 Write-holder 서브에이전트가 `xlsx-author`를 path로 다시 건다 (resolver, escalator, builder, poster, flagger, publisher, note-writer(ER), deck-writer).

### 5.4 ppt-template-creator — 스킬을 만드는 스킬

254 lines. Description이 명시: **SKILLS를 만들지 presentations를 만들지 마라.** "For creating actual presentations, use the pptx skill instead." (레포의 스킬 이름은 `pptx-author`이지 `pptx`가 아님 — 문구 drift.)

워크플로: 유저 `.pptx`/`.potx` → python-pptx로 layout/placeholder 좌표 추출 (EMU/914400 = inches) → skill-creator로 디렉터리 init → `assets/template.pptx` 복사 → 생성된 SKILL.md는 **self-contained** (이 메타 스킬을 참조하지 않음) → 예제 덱 → package.

생성된 스킬 이름 패턴: `[company]-ppt-template`. `/one-pager` 커맨드가 `ls skills/ | grep -E "ppt-template|brand-guidelines"`로 이런 파생 스킬을 찾는다.

Slash wrapper: `commands/ppt-template.md` — **유일한 `allowed-tools` 사용처** (`["Read", "Write", "Bash", "Glob"]`). Body: `Use the skill: "ppt-template-creator" tool`.

Agent 번들: 없음.

### 5.5 audit-xls — 모델 QA harness

156 lines. 트리거 문구가 description에 박혀 있다: `"audit this sheet"`, `"check my formulas"`, `"debug model"`, `"model won't balance"` 등.

Scope 3단: selection / sheet / **model** (BS balance, cash tie-out, roll-forwards, type-specific bugs).

Model-type-specific: DCF / LBO / Merger / 3-statement.

출력: findings table + severity Critical/Warning/Info. **Don't change anything without asking.**

Cowork: `/debug-model` → `Load the audit-xls skill with scope **model**`.

CMA: `model-builder/subagents/auditor.yaml` path. 여러 orchestrator agent.md가 워크플로 중간 "Invoke `audit-xls`"를 지시.

번들: ER, GL, MB, ME, PA, SA.

### 5.6 clean-data-xls — 데이터 정제 (번들 안 됨)

50 lines. Triggers: `"clean this data"`, `"normalize this data"`, `"dedupe"` 등.

Environment 분기:

- Office Add-in / Office JS: `Excel.run`, helper-column formulas (`=TRIM(A2)`)
- standalone .xlsx: Python/openpyxl

Prefer formulas over hardcoded cleaned values. Destructive ops는 유저 확인.

**Slash command 없음** (README Skill & Command Reference도 `—`). **어떤 agent에도 번들되지 않음.** financial-analysis vertical을 Cowork에 설치해야만 자동 트리거.

---

## 6. SKILL.md 컨벤션 (관측)

### 6.1 YAML frontmatter 키 (실제 사용)

| key | count / 112 | 어디서 |
|---|---|---|
| `name` | 112 | 전부 |
| `description` | 112 | 전부 |
| `license` | 1 | skill-creator only |
| `allowed-tools` | 0 | SKILL.md에는 없음. 커맨드 1개만 |
| `metadata` | 0 | quick_validate가 허용만 함 |

name vs directory mismatch 2건:

- `plugins/vertical-plugins/investment-banking/skills/strip-profile` → `name: fsi-strip-profile`
- `plugins/partner-built/spglobal/skills/earnings-preview-beta` → `name: earnings-preview-single`

quick_validate 규칙: hyphen-case `^[a-z0-9-]+$`, 64자, description 1024자, no `<>`.

### 6.2 description 스타일 (트리거)

skill-creator: description이 **유일한 트리거 메커니즘**. Body의 When-to-use는 너무 늦다.

관측 패턴 (vertical 49 + orphan 3 + partner 11):

| 패턴 | 예 |
|---|---|
| `Use when ...` | dcf-model, 3-statement-model, fund-admin 전부, LSEG 전부 |
| `Triggers on "phrase", "phrase"` | PE 10개 전부, IB 다수, audit-xls, clean-data-xls, client-* |
| 둘 다 | returns-analysis, deal-sourcing, competitive-analysis 등 |
| 짧은 한 줄, 트리거 문구 없음 | pptx-author, xlsx-author (23 words). 환경(headless)으로 구분 |
| 마크다운 리스트 `**Perfect for:**` | comps-analysis (description이 multiline YAML) |

길이: 대체로 32–80 words. Partner tear-sheet 107, funding-digest 97 (quoted YAML string). skill-creator 권고 "include all when-to-use here"와 맞게, 짧은 스킬(fund-admin 33–53 lines)은 description + 짧은 Step 워크플로만 있다.

### 6.3 allowed-tools

- SKILL.md: **사용 없음**.
- Agent.md frontmatter: `tools:` (쉼표 구분, Cowork agent 툴 그랜트). 예: `tools: Read, Write, Edit, mcp__capiq__*`
- Command: `plugins/vertical-plugins/financial-analysis/commands/ppt-template.md`만 `allowed-tools: ["Read", "Write", "Bash", "Glob"]`
- CMA: `agent.yaml` / subagent yaml의 `tools: [{type: agent_toolset_20260401, ...}]` — 완전히 다른 스키마.

Cowork agent `tools:`는 Bash/WebFetch를 주지 않는다 (`CLAUDE.md` / restructure 커밋 메시지: "Tighten agent tool grants to declared MCPs only — no Bash, WebFetch"). CMA orchestrator는 기본적으로 read/grep/glob + 선언된 MCP. Write는 **단 하나의 leaf**만.

### 6.4 references/ 패턴

| 디렉터리 이름 | 사용 스킬 |
|---|---|
| `references/` (복수, skill-creator 표준) | earnings-analysis, initiating-coverage, 3-statement-model, competitive-analysis, ib-check-deck, skill-creator, spglobal funding-digest/tear-sheet |
| `reference/` (단수) | **pitch-deck only** |
| `assets/` | initiating-coverage (`quality-checklist.md`, `report-template.md`). ppt-template-creator는 생성된 스킬에 `assets/template.pptx`를 요구하지만 자신은 assets가 없음 |
| 스킬 루트 기타 | dcf-model: `TROUBLESHOOTING.md`, `requirements.txt`; skill-creator: `LICENSE.txt`; spglobal 3스킬: `LICENSE`; spglobal earnings-preview-beta: `report-template.md` (references 밖) |

Progressive disclosure 관측: earnings-analysis SKILL.md (228 lines)가 `See [references/workflow.md](...)` 등으로 위임. initiating-coverage는 783 lines + 6 reference files + 2 assets — skill-creator의 "500 lines" 권고를 초과. dcf-model 1264 lines는 레포에서 가장 길고, references로 안 쪼개져 있다.

### 6.5 scripts/ 동봉 Python

| skill | script | 역할 |
|---|---|---|
| dcf-model | `scripts/validate_dcf.py` (11623 bytes) + `requirements.txt` | DCF 검증. SKILL.md는 별도로 `recalc.py` (xlsx skill 쪽, **이 레포에 없음**)를 호출하라고 함 |
| ib-check-deck | `scripts/extract_numbers.py` (10305 bytes) | 덱 숫자 추출 |
| skill-creator | `init_skill.py`, `package_skill.py`, `quick_validate.py` | 스킬 저자 툴체인 |

그 외 vertical 스킬은 스크립트 없음. Body에 inline Python 예제 (pptx-author, ppt-template-creator, dcf-model, 3-statement-model).

### 6.6 본문 구조 패턴

짧은 ops 스킬 (fund-admin, operations): `# Title` → `## Workflow` Step N → 표 → `## Important Notes` / 가드레일.

모델링 스킬 (dcf, lbo, comps, 3-statement): Overview → Environment (Office JS vs openpyxl) → Critical Constraints → numbered process → Quality rubric → Deliverables.

리서치 스킬 (earnings-analysis, initiating-coverage): 분량/폰트/차트 수 같은 산출 스펙 → Phase workflow → `## Resources`로 references 링크 → Dependencies (`DOCX skill`, `XLS skill` — 이 레포의 이름은 xlsx-author / 별도 docx 스킬 없음).

IB pitch-deck: XML/placeholder 저수준. `reference/xml-reference.md`.

공통 가드레일 문구 (agent.md와 스킬 양쪽): untrusted documents, `[UNSOURCED]`, draft-only / no send, human sign-off.

---

## 7. commands/*.md 가 스킬을 감싸는 방식

Agent plugin에는 `commands/`가 **없다**. Slash command는 vertical + partner + msft-365-install에만 있다.

### 7.1 Frontmatter 키 (vertical)

거의 전부:

```yaml
---
description: <one line>
argument-hint: "[optional args]"
---
```

예외: `ppt-template.md`에 `allowed-tools`. `description`만 있는 것 없음 (vertical). msft-365 커맨드는 대체로 `description`만, `entra-app.md`는 frontmatter 없음.

### 7.2 두 가지 바디 스타일

**Thin wrapper** (대다수, 2–8 lines):

```markdown
Load the `buyer-list` skill and build a universe of ...
If a company or sector is provided, use it. Otherwise ask the user ...
```

**Thick wrapper** (워크플로를 커맨드에 재기술):

- `equity-research/commands/earnings.md` — `Use skill: "earnings-analysis"` + 전체 리포트 구조
- `financial-analysis/commands/dcf.md` — comps-analysis 먼저, 그다음 dcf-model
- `financial-analysis/commands/ppt-template.md` — `skill: "ppt-template-creator"`
- `investment-banking/commands/one-pager.md` — 템플릿 스킬 탐색 + `skill: "strip-profile"`
- LSEG 커맨드 — MCP 툴 이름을 커맨드에 직접 (`bond_future_price`, `ir_swap`). 스킬은 "See the **bond-futures-basis** skill for domain knowledge"

두 호출 문법:

| 문법 | 예 |
|---|---|
| `Load the \`<skill>\` skill` | 대부분의 thin wrapper |
| `Use \`skill: "<name>"\`` | earnings, comps, dcf, ppt-template, one-pager |

커맨드 파일명 ≠ 스킬 디렉터리명인 매핑:

| command file | slash (Cowork) | skill dir |
|---|---|---|
| comps.md | `/comps` | comps-analysis |
| dcf.md | `/dcf` | dcf-model (+ comps-analysis) |
| lbo.md | `/lbo` | lbo-model |
| debug-model.md | `/debug-model` | audit-xls |
| ppt-template.md | `/ppt-template` | ppt-template-creator |
| earnings.md | `/earnings` | earnings-analysis |
| screen.md | `/screen` | idea-generation |
| sector.md | `/sector` | sector-overview |
| thesis.md | `/thesis` | thesis-tracker |
| catalysts.md | `/catalysts` | catalyst-calendar |
| initiate.md | `/initiate` | initiating-coverage |
| cim.md | `/cim` | cim-builder |
| one-pager.md | `/one-pager` | strip-profile |
| dd-prep.md | `/dd-prep` | dd-meeting-prep |
| screen-deal.md | `/screen-deal` | deal-screening |
| source.md | `/source` | deal-sourcing |
| portfolio.md | `/portfolio` | portfolio-monitoring |
| returns.md | `/returns` | returns-analysis |
| value-creation.md | `/value-creation` | value-creation-plan |

스킬은 있고 커맨드가 없는 것: clean-data-xls, deck-refresh, ib-check-deck, pptx-author, xlsx-author, skill-creator, pitch-deck, datapack-builder, 그리고 fund-admin 6개, operations 2개 전부.

fund-admin / operations vertical은 `commands/` 디렉터리 자체가 없다. 그 스킬은 description 트리거 또는 agent 워크플로 `Invoke \`gl-recon\`` 으로만 호출된다.

Claude Code 호출 형식 (`CLAUDE.md`): `/plugin:command-name`. README 예: `/comps`, `/dcf`, `/earnings`, `/ic-memo`.

---

## 8. plugin.json 스키마 — 전수 비교

19개 `plugin.json` (숨김 경로 `.claude-plugin/plugin.json`). **어느 파일도 `agents`, `skills`, `commands`, `hooks` 키를 갖지 않는다.** 컴포넌트 발견은 디렉터리 관례.

### 8.1 필드 매트릭스

| plugin | name | version | description | author | keywords | homepage | repository | license | email |
|---|---|---|---|---|---|---|---|---|---|
| earnings-reviewer | earnings-reviewer | 0.1.1 | ● | Anthropic FSI | | | | | |
| gl-reconciler | gl-reconciler | 0.1.0 | ● | Anthropic FSI | | | | | |
| kyc-screener | kyc-screener | 0.1.0 | ● | Anthropic FSI | | | | | |
| market-researcher | market-researcher | 0.1.1 | ● | Anthropic FSI | | | | | |
| meeting-prep-agent | meeting-prep-agent | 0.1.1 | ● | Anthropic FSI | | | | | |
| model-builder | model-builder | 0.1.0 | ● | Anthropic FSI | | | | | |
| month-end-closer | month-end-closer | 0.1.0 | ● | Anthropic FSI | | | | | |
| pitch-agent | pitch-agent | 0.1.1 | ● | Anthropic FSI | | | | | |
| statement-auditor | statement-auditor | 0.1.0 | ● | Anthropic FSI | | | | | |
| valuation-reviewer | valuation-reviewer | 0.1.1 | ● | Anthropic FSI | | | | | |
| equity-research | equity-research | 0.1.2 | ● | Anthropic FSI | | | | | |
| financial-analysis | financial-analysis | 0.1.1 | ● | Anthropic FSI | | | | | |
| fund-admin | fund-admin | 0.1.0 | ● | Anthropic FSI | | | | | |
| investment-banking | investment-banking | 0.2.1 | ● | **Anthropic** (FSI 접미사 없음) | | | | | |
| operations | operations | 0.1.0 | ● | Anthropic FSI | | | | | |
| private-equity | private-equity | 0.1.2 | ● | Anthropic FSI | | | | | |
| lseg | lseg | 1.0.0 | ● | LSEG | | | | | |
| sp-global | sp-global | 1.0.1 | ● | Kensho Technologies | ● 7개 | ● | ● | Apache-2.0 | ● |
| claude-for-msft-365-install | claude-for-msft-365-install | 0.1.13 | ● | Anthropic | | | | | support@anthropic.com |

공통 최소 스키마 (Anthropic FSI agent/vertical 17개): `{name, version, description, author: {name}}`.

sp-global만 확장: `homepage`, `repository`, `license`, `keywords`, `author.email`.

`displayName`은 plugin.json에 없고 **marketplace.json에만** 있다. 삭제된 `claude-for-financial-advisors` plugin.json(git `6e7f94d`)은 `displayName`을 plugin.json에 넣고 있었다 — 현행 스키마와 불일치.

### 8.2 marketplace.json

경로: `.claude-plugin/marketplace.json`

```json
{
  "name": "claude-for-financial-services",
  "owner": { "name": "Matt Piccolella" },
  "plugins": [ { "name", "displayName", "source", "description" }, ... ]
}
```

19 엔트리. `source`는 레포 상대 경로. `check.py` §4c: 각 source 아래 `.claude-plugin/plugin.json`이 있어야 한다.

등록 순서: 6 vertical → 10 agent → 2 partner → msft-365-install.

**없는 것:** `claude-for-financial-advisors` (삭제됨, README 링크는 남음). wealth-management도 없음.

### 8.3 그 외 매니페스트

- `hooks/hooks.json`: equity-research, financial-analysis, investment-banking, private-equity만 존재. 내용 전부 `{"hooks": {}}`. fund-admin, operations, 모든 agent plugin, partner: hooks 파일 없음.
- `.mcp.json`: financial-analysis (11 connectors; 파일에 `"egnyte"` 블록 뒤 **콤마 누락** 후 `"box"` — JSON 깨짐이 관측됨), investment-banking, private-equity, lseg, spglobal.
- Agent.md frontmatter: `{name, description, tools}`. check.py는 name+description만 요구.
- CMA `agent.yaml`: `{name, model, system, tools, mcp_servers, skills, callable_agents}`. 이 키들은 plugin.json이 아니라 쿡북에 있다.

version-bump: `.githooks` + `scripts/version_bump.py`. 플러그인 `version`이 이미 설치된 유저의 업데이트 게이트. 브랜치는 main보다 patch 하나 앞.

---

## 9. Cowork discovery vs CMA reference

### 9.1 Cowork / Claude Code

설치 (README):

```
claude plugin marketplace add anthropics/financial-services
claude plugin install financial-analysis@claude-for-financial-services
claude plugin install pitch-agent@claude-for-financial-services
```

또는 Cowork Settings → Plugins → Add plugin → 레포 URL 또는 `plugins/` 하위 zip.

발견 경로 (파일 관례, plugin.json 필드 아님):

| 컴포넌트 | 경로 | 동작 |
|---|---|---|
| Plugin identity | `.claude-plugin/plugin.json` | name/version/description |
| Marketplace listing | `.claude-plugin/marketplace.json` | Cowork/Code가 고를 목록 |
| Agents | `agents/<slug>.md` | "agents appear in Cowork dispatch". frontmatter `tools:`가 툴 그랜트 |
| Skills | `skills/<name>/SKILL.md` | "skills fire automatically when their trigger conditions match" (description) |
| Commands | `commands/<file>.md` | `/plugin:command-name` 또는 README의 `/comps` 스타일 |
| Hooks | `hooks/hooks.json` | 현재 빈 객체 |
| MCP | `.mcp.json` | Cowork 세션에 서버 연결 |

Agent plugin은 **self-contained**: 필요한 스킬을 내부에 복사했으므로 vertical을 안 깔아도 에이전트+스킬은 돈다. Slash command와 전체 connector 세트는 vertical (특히 financial-analysis) 설치가 필요.

라이브 Office: 스킬 본문이 `mcp__office__excel_*` / `mcp__office__powerpoint_*` / Office JS를 쓰라고 한다. pptx-author/xlsx-author description은 이 모드에서 쓰지 말 것.

### 9.2 CMA (Claude Managed Agents)

경로: `managed-agent-cookbooks/<slug>/`

`agent.yaml` 공통 모양:

```yaml
name: <slug>
model: claude-opus-4-7
system:
  file: ../../plugins/agent-plugins/<slug>/agents/<slug>.md
  append: "You are running headless. Produce files in ./out/; do not assume an open Office document."
tools:
  - type: agent_toolset_20260401
    default_config: { enabled: false }
    configs:
      - { name: read, enabled: true }
      - { name: grep, enabled: true }
      - { name: glob, enabled: true }
  - { type: mcp_toolset, mcp_server_name: <...>, default_config: { enabled: true } }
mcp_servers:
  - { type: url, name: <...>, url: "${..._MCP_URL}" }
skills:
  - { from_plugin: ../../plugins/agent-plugins/<slug> }
callable_agents:
  - { manifest: ./subagents/<leaf>.yaml }
```

`scripts/deploy-managed-agent.sh`가 하는 일:

1. `from_plugin` → 그 플러그인 `skills/*/` 전부 `{__upload: abs path}`로 펼침
2. 각 디렉터리를 zip → `POST /v1/skills` (`anthropic-beta: skills-2025-10-02`)
3. `system.file`을 인라인 + `append`
4. subagent yaml을 재귀 create 후 `callable_agents: [{type: agent, id, version}]`
5. `POST /v1/agents` (`anthropic-beta: managed-agents-2026-04-01`)

서브에이전트는 `from_plugin` 대신 **개별** `skills: [{path: ../../../plugins/agent-plugins/<slug>/skills/<name>}]`. Write는 볼드 leaf 하나 (`managed-agent-cookbooks/README.md`: "Bold leaf = the only worker with Write").

Headless에서 Office MCP가 없으므로 `append`가 `./out/`을 강제하고, Write-holder가 `pptx-author` / `xlsx-author`를 로드한다. 같은 SKILL.md가 Cowork에서는 "When NOT to use"로 건너뛴다.

CMA는 slash command를 배포하지 않는다. 진입점은 `steering-examples.json` 이벤트 (`Briefing pack for <client-id>, meeting <event-id>` 등).

같은 시스템 프롬프트 파일: Cowork `agents/<slug>.md` = CMA `system.file`. 스킬 바이트도 동일 (meeting-prep 3개 orphan 제외하면 vertical=agent 복사본).

---

## 10. meeting-prep-agent 스킬 출처 추적

### 10.1 현재 상태

`plugins/agent-plugins/meeting-prep-agent/skills/`:

| dir | name | bytes | vertical? |
|---|---|---|---|
| client-report | client-report | 3300 | **없음** |
| client-review | client-review | 3188 | **없음** |
| investment-proposal | investment-proposal | 3584 | **없음** |
| pptx-author | pptx-author | 1825 | financial-analysis, MATCH |

pack-writer.yaml가 실제로 path하는 것: `client-review` + `pptx-author` only. `client-report` / `investment-proposal`은 orchestrator 번들·agent.md 목록에만 있고 서브에이전트 path에는 없다.

### 10.2 git 타임라인 (발명 아님)

| 날짜 | 커밋 | 사건 |
|---|---|---|
| 2026-02-23 | `b891783` Initial commit | `wealth-management/skills/{client-report,client-review,investment-proposal,financial-plan,portfolio-rebalance,tax-loss-harvesting}` + matching `commands/` |
| 2026-05-05 | `bb4a2b3` #81 Restructure | vertical을 `plugins/vertical-plugins/wealth-management/`로 이동. **동시에** `plugins/agent-plugins/meeting-prep-agent/skills/`에 client-report, client-review, investment-proposal, pptx-author 복사 |
| 2026-09-11 | `734150c` #349 | **`plugins/vertical-plugins/wealth-management/` 전체 삭제** (skills 6 + commands 6 + plugin.json + hooks). Agent 쪽 3스킬은 삭제하지 않음 → orphan |
| 2026-09-14 | `6e7f94d` #350 | `claude-for-financial-advisors/` **추가**. 스킬 세트는 **다름**: pre-meeting, post-meeting, prospect-intake, onboarding, compliance, alts-brief, estate-and-tax-brief, portfolio-rebalance-review. client-report 트리오 없음 |
| 2026-09-21 | `574ed36` #354 | `claude-for-financial-advisors/` **삭제** (24 files, 2561 lines) |

### 10.3 README / CMA 문서 drift

- 루트 `README.md` Vertical Plugins 테이블: `**[claude-for-financial-advisors](./claude-for-financial-advisors)**` — 디렉터리 없음.
- `managed-agent-cookbooks/README.md` 행: meeting-prep-agent | **wealth-management** | ... — vertical 없음.
- `check.py` / `sync-agent-skills.py`는 현재 트리에서 이 3개에 대해 실패한다.

### 10.4 삭제된 advisors 플러그인이 갖고 있던 것 (git `6e7f94d`, 현재 트리에 없음)

plugin.json: `name: claude-for-financial-advisors`, `displayName`, `version: 1.0.0`, author `Anthropic — Asset & Wealth Management`.

Skills: alts-brief, compliance (+ references/sec-compliance-checklist.md), estate-and-tax-brief, onboarding (+ miller-demo.md), portfolio-rebalance-review (+ template), post-meeting, pre-meeting (+ template), prospect-intake (+ 3 templates).

Agents (서브워커 스타일 md): compliance-lookup, compliance-scan, holdings-sanity, source-extract, statement-extract, titling-compare.

`.mcp.json` 96 lines (CRM/portfolio/planning/estate connectors — 현재 워크스페이스에 파일 없음).

**meeting-prep의 client-report 트리오와 advisors의 pre-meeting/post-meeting은 다른 유산이다.** 전자는 초기 wealth-management 플러그인, 후자는 9일간 살다 지워진 별도 플러그인. 어느 쪽도 지금 vertical-plugins에 없다.

wealth-management에서 같이 지워져 agent로도 안 살아남은 스킬: `financial-plan`, `portfolio-rebalance`, `tax-loss-harvesting` (+ commands `/financial-plan`, `/proposal`, `/rebalance`, `/tlh`).

---

## 11. CMA 서브에이전트가 다시 집는 스킬

Orchestrator `from_plugin`이 플러그인 스킬 전부를 업로드하고, leaf는 부분집합을 `path:`로 재참조.

| cookbook | leaf | skills.path |
|---|---|---|
| earnings-reviewer | model-updater | model-update |
| earnings-reviewer | note-writer | morning-note, xlsx-author |
| earnings-reviewer | transcript-reader | (none) |
| gl-reconciler | resolver | xlsx-author |
| kyc-screener | escalator | xlsx-author |
| market-researcher | comps-spreader | comps-analysis |
| market-researcher | note-writer | pptx-author |
| meeting-prep-agent | pack-writer | client-review, pptx-author |
| model-builder | auditor | audit-xls |
| model-builder | builder | dcf-model, lbo-model, 3-statement-model, comps-analysis, xlsx-author |
| month-end-closer | poster | xlsx-author |
| pitch-agent | deck-writer | xlsx-author, pptx-author, pitch-deck |
| pitch-agent | modeler | dcf-model, lbo-model |
| statement-auditor | flagger | xlsx-author |
| valuation-reviewer | publisher | xlsx-author |
| valuation-reviewer | valuation-runner | returns-analysis |

Reader/critic 계열은 스킬 없이 Read/Grep만. 이것이 "untrusted docs never meet Write" 분리.

---

## 12. 관측된 불일치 / 깨진 참조 (문서용, 수정하지 않음)

1. `client-report` / `client-review` / `investment-proposal`: vertical 원본 삭제, check.py/sync 실패.
2. README → `./claude-for-financial-advisors` 404.
3. CMA README: meeting-prep vertical = `wealth-management` (없음).
4. `financial-analysis/.mcp.json`: `"egnyte"` 다음 콤마 없음 → `"box"` 블록 JSON 무효.
5. SKILL.md `name` ≠ 디렉터리: `fsi-strip-profile`, `earnings-preview-single`.
6. `pitch-deck`만 `reference/` (단수). 나머지 `references/`.
7. skill-creator 본문 "frontmatter에 name/description만" vs `quick_validate.py`가 license/allowed-tools/metadata 허용 vs 자신은 `license` 사용.
8. ppt-template-creator / earnings-analysis가 `pptx` / `DOCX skill` / `XLS skill`을 가리키는데 레포 이름은 `pptx-author` / (docx 스킬 없음) / `xlsx-author`.
9. dcf-model이 `python recalc.py`를 요구. 해당 스크립트는 이 레포 스킬 트리에 없다 (xlsx 스킬 외부 의존으로 서술).
10. dcf-model 1264 lines, initiating-coverage 783 — skill-creator 500-line 권고 초과. TROUBLESHOOTING.md는 "What to Not Include"와 충돌.
11. Agent.md가 번들된 pptx-author/xlsx-author를 목록에서 빼먹는 경우 3 agent (ER, MB, PA). CMA leaf yaml이 메움.
12. clean-data-xls, skill-creator, ppt-template-creator는 공유 harness인데 agent 번들 0.
13. Agent plugins에 commands 없음 → CMA/agent-only 설치 시 `/dcf` 같은 슬래시 엔트리 없음. 스킬 description 트리거 + agent 워크플로 Invoke만.
14. Partner `equity-research` 스킬 이름이 vertical `equity-research` 플러그인/스킬 세트와 충돌 가능 (다른 패키지라 Cowork 동시 설치 시에만 문제).

---

## 13. 파일 경로 인덱스 (절대)

Canonical vertical skills root: `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/`

Sync script: `/Users/yeonwoosung/Desktop/financial-services/scripts/sync-agent-skills.py`  
Lint: `/Users/yeonwoosung/Desktop/financial-services/scripts/check.py`  
CMA deploy: `/Users/yeonwoosung/Desktop/financial-services/scripts/deploy-managed-agent.sh`

Marketplace: `/Users/yeonwoosung/Desktop/financial-services/.claude-plugin/marketplace.json`

Harness skills:

- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/skill-creator/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/pptx-author/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/xlsx-author/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/ppt-template-creator/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/audit-xls/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/skills/clean-data-xls/SKILL.md`

Orphan meeting-prep skills:

- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/meeting-prep-agent/skills/client-report/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/meeting-prep-agent/skills/client-review/SKILL.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/agent-plugins/meeting-prep-agent/skills/investment-proposal/SKILL.md`
