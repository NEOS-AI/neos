# 00. Claude for Financial Services — 개요

원본 README 한 줄:

> Reference agents, skills, and data connectors for the financial-services workflows we see most — investment banking, equity research, private equity, and wealth management.

모든 산출물은 **적격 전문가가 검토하는 초안**이다. 투자·법률·세무·회계 자문이 아니고, 거래 집행·리스크 확정·원장 전기·온보딩 승인을 하지 않는다.

## 1. 듀얼 서피스

같은 소스가 두 런타임에 실린다.

| 서피스 | 진입점 | 누가 쓰나 |
|---|---|---|
| **Cowork / Claude Code plugin** | `plugins/agent-plugins/<slug>/` + `plugins/vertical-plugins/<vertical>/` | 애널리스트가 세션에서 설치 |
| **Claude Managed Agents** | `managed-agent-cookbooks/<slug>/` → `POST /v1/agents` | 플랫폼 팀이 워크플로 엔진 뒤에 배포 |

Canonical 시스템 프롬프트는 항상 `plugins/agent-plugins/<slug>/agents/<slug>.md`. Cookbook `agent.yaml`은 `system.file`로 그 파일을 인라인하고, 아래 한 줄을 append한다.

```
You are running headless. Produce files in ./out/; do not assume an open Office document.
```

Cowork는 열린 Excel/PowerPoint(`mcp__office__excel_*` / `mcp__office__powerpoint_*`)를 가정한다. CMA는 `xlsx-author` / `pptx-author`로 `./out/`에 파일을 쓴다.

빌드 스텝은 없다. 마크다운·YAML·JSON이 소스다.

## 2. 디렉터리 구조

```
plugins/
  agent-plugins/<slug>/          # named agent (self-contained)
    .claude-plugin/plugin.json
    agents/<slug>.md             # canonical system prompt
    skills/                      # vertical에서 동기화한 복사본
  vertical-plugins/<vertical>/   # 스킬 소스 오브 트루스
    skills/, commands/, hooks/, .mcp.json
  partner-built/{lseg,spglobal}/
managed-agent-cookbooks/<slug>/  # CMA 래퍼
  agent.yaml
  subagents/*.yaml               # depth-1 leaf, 항상 3개
  steering-examples.json
  README.md                      # security tier + handoff
claude-for-msft-365-install/     # Office add-in 프로비저닝 (FSI 에이전트와 분리)
scripts/                         # check, validate, deploy, orchestrate, sync, version_bump
.claude-plugin/marketplace.json
```

`CLAUDE.md` 규칙: 스킬은 `vertical-plugins/`에서 고치고 `python3 scripts/sync-agent-skills.py`로 에이전트 번들에 전파한다. 번들이 소스와 어긋나면 `check.py`가 fail한다.

## 3. Named agents (10)

| Function | Agent | 산출물 | CMA Write leaf |
|---|---|---|---|
| Coverage & advisory | `pitch-agent` | comps/precedents/LBO + 브랜드 피치덱 | `deck-writer` |
| | `meeting-prep-agent` | 미팅 브리핑 팩 | `pack-writer` |
| Research & modeling | `market-researcher` | 섹터 프라이머, comps, 아이디어 숏리스트 | `note-writer` |
| | `earnings-reviewer` | 실적 모델 업데이트 + 노트 초안 | `note-writer` |
| | `model-builder` | DCF / LBO / 3-statement / comps `.xlsx` | `builder` |
| Fund admin | `valuation-reviewer` | GP 패키지 검토 + LP 리포팅 스테이징 | `publisher` |
| | `gl-reconciler` | GL↔서브레저 브레이크 + 예외 리포트 | `resolver` |
| | `month-end-closer` | 발생/롤포워드/variance 패키지 | `poster` |
| | `statement-auditor` | LP 명세서 NAV tie-out | `flagger` |
| Operations | `kyc-screener` | 온보딩 파싱 + 룰 엔진 + 에스컬레이션 | `escalator` |

모델은 cookbook 전부 `claude-opus-4-7`.

## 4. 버티컬 플러그인

| Plugin | 역할 | 스킬 수 | slash commands |
|---|---|---|---|
| `financial-analysis` | 코어 모델링, Excel/PPT QC, **MCP 허브** | 13 | 7 (`/comps` `/dcf` `/lbo` …) |
| `investment-banking` | CIM, teaser, pitch, merger model | 9 | 7 (`/cim` `/teaser` `/one-pager` …) |
| `equity-research` | 실적 노트, initiation, thesis | 9 | 9 (`/earnings` `/initiate` …) |
| `private-equity` | 소싱~IC~포트폴리오 | 10 | 10 (`/ic-memo` `/source` …) |
| `fund-admin` | recon, accrual, NAV | 6 | **없음** |
| `operations` | KYC parse + rules | 2 | **없음** |

`fund-admin` / `operations`는 커맨드·훅·`.mcp.json`이 없다. 에이전트 번들로만 소비된다.

## 5. 스킬 번들 매트릭스 (에이전트 ← 버티컬)

`sync-agent-skills.py`는 스킬 **디렉터리 이름**으로 vertical 소스를 찾는다.

| Agent | Bundled skills |
|---|---|
| pitch-agent | 3-statement-model, audit-xls, comps-analysis, dcf-model, deck-refresh, ib-check-deck, lbo-model, pitch-deck, pptx-author, sector-overview, xlsx-author |
| market-researcher | competitive-analysis, comps-analysis, idea-generation, pptx-author, sector-overview |
| earnings-reviewer | audit-xls, earnings-analysis, earnings-preview, model-update, morning-note, xlsx-author |
| meeting-prep-agent | client-report, client-review, investment-proposal, pptx-author |
| model-builder | 3-statement-model, audit-xls, comps-analysis, dcf-model, lbo-model, xlsx-author |
| gl-reconciler | audit-xls, break-trace, gl-recon, xlsx-author |
| kyc-screener | kyc-doc-parse, kyc-rules, xlsx-author |
| valuation-reviewer | ic-memo, portfolio-monitoring, returns-analysis, xlsx-author |
| month-end-closer | accrual-schedule, audit-xls, roll-forward, variance-commentary, xlsx-author |
| statement-auditor | audit-xls, nav-tieout, xlsx-author |

**갭:** `client-report` / `client-review` / `investment-proposal`은 vertical 소스가 없다. README의 `claude-for-financial-advisors/`가 그 자리인데 클론에 디렉터리가 없다. `sync-agent-skills.py`와 `check.py`는 이 세 스킬에서 fail한다.

## 6. 두 가지 운영 모드

프롬프트와 CMA YAML을 겹치면 에이전트는 두 클러스터로 나뉜다.

**Mode A — 리서치/IB (신뢰 데이터 MCP 중심)**  
`pitch-agent`, `market-researcher`, `earnings-reviewer`, `meeting-prep-agent`, `model-builder`

- Cowork frontmatter에 오케스트레이터 `Write`(+ 대개 `Edit`)가 있다.
- CMA는 오케스트레이터 Write를 제거하고 leaf 하나에만 Write를 준다.
- 비신뢰 입력은 트랜스크립트·이메일·제3자 리포트 정도. Isolation이 Mode B보다 약하다(earnings/meeting-prep는 reader 격리, pitch/model-builder는 MCP가 신뢰 소스).

**Mode B — 운영/컴플라이언스 (비신뢰 문서 + 원장 인접)**  
`gl-reconciler`, `kyc-screener`, `valuation-reviewer`, `month-end-closer`, `statement-auditor`

- Cowork frontmatter부터 오케스트레이터는 `Read, Grep, Glob`만.
- 3단 격리: untrusted reader → 신뢰 MCP 중간층 → Write-holder.
- 바인딩 액션 거부: 원장 전기 금지, KYC 승인 금지, LP 배포 금지.

## 7. 공통 프롬프트 골격

10개 시스템 프롬프트가 같은 5블록을 쓴다.

1. YAML frontmatter: `name`, `description`, `tools`만 (`model`/`color` 없음)
2. 한 줄 정체성: “You are the X — a … who …”
3. `## What you produce`
4. `## Workflow` (번호 매긴 단계, 백틱 스킬 호출)
5. `## Guardrails`
6. `## Skills this agent uses` (가운데점 `·`)

`description`은 Cowork 라우터다. “Use when … not for … (use `<other-slug>` for that).” 상호 라우팅 예: `gl-reconciler` ↔ `month-end-closer`.

Canonical 프롬프트는 `handoff_request`를 말하지 않는다. 크로스 에이전트는 cookbook README + `scripts/orchestrate.py`만 담당한다.

## 8. 파일 기반 철학과 검증

- `check.py`: YAML/JSON parse, frontmatter `name`+`description`, `system.file`/`skills.path`/`from_plugin`/`callable_agents.manifest` 존재, 번들 드리프트, marketplace 경로, cookbook 필수 파일, `.ps1` ASCII/BOM.
- `validate.py`: reader `output_schema`를 CMA 밖에서 검사. CMA API는 structured output을 강제하지 않는다.
- `test-cookbooks.sh`: 전 cookbook `--dry-run`, depth-1, 비어 있지 않은 system, `output_schema` 누수 금지.
- `version_bump.py`: 플러그인 `version`이 이미 설치된 사용자에게 업데이트를 밀어주는 게이트. 브랜치당 패치 +1.
- CI: `plugin-validate.yml` (Claude CLI 2.1.143), `version-bump.yml`, `secret-scan.yml` (gitleaks v8.28.0 SHA pin + 내부 참조 scrub).

## 9. 이 클론에서 확인된 결함

1. `plugins/vertical-plugins/financial-analysis/.mcp.json` — `egnyte`와 `box` 사이 **콤마 누락**. strict JSON 로더는 커넥터 전체를 버린다. `check.py`는 `.mcp.json`을 파싱하지 않는다.
2. `claude-for-financial-advisors/` **부재**. marketplace에도 없다.
3. meeting-prep 3 스킬은 vertical 소스 없음 → `check.py` / `sync-agent-skills.py` fail 조건.
4. DCF `validate_dcf.py`는 `Sensitivity` 시트를 기대하지만 SKILL.md는 민감도를 DCF 시트 하단에 두라고 한다. SKILL.md는 이 스크립트를 호출하지 않는다.
5. 스킬이 인용하는 예제 파일(`comps_example.xlsx`, `LBO_Model.xlsx`, Nike strip profile PPT)은 트리에 없다. `recalc.py`도 외부 `xlsx` 스킬 소속.
6. LSEG MCP URL이 코어(`…/lfa/mcp`)와 파트너(`…/lfa/mcp/server-cl`)에서 다르다.
7. `plugin-validate.yml`은 `plugins/**/plugin.json`만 본다. `claude-for-msft-365-install`은 검증하지 않는다.
8. `deploy-managed-agent.sh` 헤더는 reader에 “thin validation wrapper”를 붙인다고 하지만, 구현은 `del(.output_schema)`뿐이다. 검증은 별도 `validate.py`.
9. Equity-research initiation 스킬 내부 충돌: BUY/HOLD/SELL vs OUTPERFORM/NEUTRAL/UNDERWEIGHT, 탭 수, 폰트, 페이지 헤더.
10. ER 스킬 다수가 레이팅·프라이스 타깃을 산출물로 요구한다. 리포 루트 README의 “do not make investment recommendations”와 긴장이 있다.

## 10. 라이선스

루트 `LICENSE`는 Apache 2.0. S&P 플러그인과 각 스킬은 Kensho Apache 2.0 (`Copyright 2026-present Kensho Technologies, LLC`). LSEG 트리에는 LICENSE가 없다.
