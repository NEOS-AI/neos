# 09. Neos 마이그레이션 맵

이 문서는 `financial-services`를 Neos로 옮길 때 **어디에 무엇을 붙일지**를 고정한다. 구현 계획이 아니라 대응 표다.

## 1. 현재 Neos 쪽 자리

| Neos 세계 | 경로 | FSI에 쓸 수 있는 점 | 쓰지 말 것 |
|---|---|---|---|
| Markdown skill catalog | `neos/skills/markdown_catalog.py`, repo-root `skills/` | `SKILL.md` name+description 인덱싱, on-demand body | coding catalog의 `## When to Use` / `## Boundaries` 강제는 FSI 스킬이 안 지킨다. research catalog는 warn-only. |
| Builtin/research skills | `neos/skills/`, `SkillRegistry` | 실행형 `skill.py`가 있는 도메인 스킬 | FSI 스킬은 거의 전부 마크다운 절차서. `BaseSkill`로 바꾸지 말 것. |
| Coding skills | `neos/coding/skills/` | pptx/docx 등 Office 산출 | FSI `pptx-author`/`xlsx-author`와 역할이 겹친다. 합치거나 명시적으로 위임. |
| Subagent runtime (Approach C/M) | `neos/subagent/`, `docs/SUBAGENT_RUNTIME_DESIGN.md` | parent-driven 1-step child, `can_spawn=False`, depth-1 | 지금 catalog는 explore-only. FSI Write leaf는 P2(write worker) 필요. |
| Parent-mediated fan-out | `docs/PARENT_MEDIATED_COLLABORATION_DESIGN.md` | 자식끼리 대화 금지, 부모가 fold. FSI와 같은 모양. | “N agents collaborate”로 키우지 말 것. |
| Deep analysis orchestrator | `neos/workflow/deep_analysis/` | 오케스트레이터만 ledger write | FSI 원장 금지를 DA ledger와 혼동하지 말 것. |
| LangGraph MultiAgentWorkflow | `neos/workflow/graph.py` | 고정 specialist 파이프라인 | FSI named agent를 여기 클래스로 포팅하지 말 것. |
| Contract Net | `neos/workflow/distributed/` | — | 되살리지 말 것. |
| Harness verdict | `docs/HARNESS_WHITEPAPER.md` | pass / advisory_pass / needs_repair / fail | FSI “stage for sign-off”를 fail로 바꾸지 말 것. 스테이징은 성공 경로. |

## 2. 이식 단위

FSI는 세 층이다. Neos도 세 층으로 옮긴다.

```
vertical SKILL.md  →  Neos markdown skills (financial vertical pack)
named agent.md     →  Neos agent profile (system prompt + tool policy + skill allowlist)
cookbook YAML      →  Neos worker graph (depth-1, one writer, output_schema gate)
```

Cowork slash commands는 Neos에서 **스킬 트리거 별칭**이면 충분하다. 별도 커맨드 런타임이 원본에도 거의 없다 (대부분은 `Load the \`skill\`` 한 줄).

## 3. 스킬 이식

### 3.1 카탈로그

- 위치 제안: `skills/financial-services/<vertical>/<skill>/SKILL.md` (repo-root research catalog).
- frontmatter는 원본 그대로 `name` + `description`. `allowed-tools`는 원본 스킬에 거의 없다.
- `sync-agent-skills.py`에 해당하는 검사는 Neos CI에서 “에이전트 프로필이 가리키는 스킬 경로가 존재하고 소스와 동일”로 재현.
- meeting-prep 3 스킬(`client-report`, `client-review`, `investment-proposal`)은 소스 오브 트루스를 `wealth-management` 또는 `advisors` 버티컬로 **먼저 복원**한 뒤 번들한다.

### 3.2 우선순위

1. **하네스 스킬** — `xlsx-author`, `pptx-author`, `audit-xls`. CMA 산출이 여기에 의존한다. Neos 기존 `skills/pptx`, `skills/docx`와 역할을 나눈다: FSI 버전은 `./out/` + blue/black/green + named range 계약.
2. **모델링** — `dcf-model`, `lbo-model`, `3-statement-model`, `comps-analysis`. `validate_dcf.py`는 가져오되 Sensitivity 시트 기대와 SKILL 레이아웃 불일치를 고친 뒤.
3. **운영 안전** — `kyc-doc-parse`, `kyc-rules`, `gl-recon`, `break-trace`, `nav-tieout`, `accrual-schedule`. 문구를 약화하지 말 것 (`never approves`, `Do not post`, `don't plug it`).
4. **IB/ER/PE 콘텐츠 스킬** — 프롬프트·템플릿이 본체. 실행 코드는 `ib-check-deck/scripts/extract_numbers.py` 정도.
5. **파트너 스킬** — LSEG/S&P는 MCP entitlement가 없으면 스텁. 이름 충돌 주의: LSEG `equity-research` vs Anthropic vertical `equity-research`; S&P `earnings-preview-beta` vs Anthropic `earnings-preview`.

### 3.3 하지 말 것

- FSI `skill-creator`를 Neos `create-skill`과 합치지 말 것. 원본은 Claude skill zip 규약이고 Neos는 다른 카탈로그다.
- ER initiation의 BUY/HOLD/SELL 산출을 그대로 켜지 말 것. 루트 README는 투자 권유를 금지한다. Neos 이식 시 **레이팅/PT는 초안 라벨 + 컴플라이언스 게이트**로 둔다.
- `recalc.py` / 예제 xlsx는 원본 트리에 없다. Neos `xlsx` 스킬의 recalc를 쓰거나 명시적으로 추가한다.

## 4. Named agent 이식

각 에이전트 프로필이 가져야 하는 필드:

| FSI | Neos |
|---|---|
| `agents/<slug>.md` body | system prompt (frontmatter 포함 인라인 가능) |
| frontmatter `tools` | default-deny tool policy |
| CMA `system.append` | headless/file-artifact 모드 플래그 |
| `skills/` 번들 | skill allowlist |
| cookbook MCP | MCP attach allowlist (env URL) |
| `callable_agents` 3 leaves | SubagentRuntime catalog entries, `can_spawn=false` |
| Write-holder leaf | 유일한 write-capable child |
| `output_schema` | parent가 child fold 전에 jsonschema |
| steering `event` | session follow-up / steer 문자열 |
| `handoff_request` | parent-mediated typed event, 모델 인용 JSON 금지 |

프롬프트 골격(What you produce / Workflow / Guardrails / Skills)은 유지한다. 정체성 문장(“senior associate who owns the first draft”)도 유지한다. 서명 임원으로 올리지 말 것.

### Mode A vs Mode B

- Mode A (pitch, market-researcher, earnings, meeting-prep, model-builder): 신뢰 MCP + 아티팩트 분리. Write leaf + (model-builder) auditor.
- Mode B (GL, KYC, valuation, month-end, statement): 비신뢰 reader 필수. reader는 Read/Grep, MCP 없음, 스키마 JSON만.

Neos SubagentRuntime P1은 explore-only다. FSI 이식을 켜려면:

1. catalog에 `reader` (read-only, schema fold), `writer` (write/edit, no MCP to untrusted), `critic` (read-only trusted MCP) 타입을 추가하거나
2. DA식 `Worker` 순수함수로 Mode B를 먼저 재현한다.

추천: **Mode B를 DA/Worker 패턴으로 먼저** 옮긴다. 이미 “오케스트레이터만 write, worker는 순수”가 DA P2와 같다. Mode A Write leaf는 coding subagent P2(worktree)와 맞춘다.

## 5. 안전장치 이식 — 약화 금지

원본 안전은 훅이 아니다. 네 겹이다.

1. **프롬프트 가드레일** — no post, never approve, never publish, untrusted, `[UNSOURCED]`.
2. **도구 default-deny + 역할 분리** — reader에 Write/MCP/Bash 없음. writer는 외부 문서를 열지 않음.
3. **스키마** — 길이·문자집합으로 주입 문구가 살아남지 못하게.
4. **외부 오케스트레이터 allowlist** — 핸드오프.

Neos 훅(`PreToolUse` 등)으로 대체하지 말고, **도구 정책 + schema gate + typed handoff**를 그대로 둔다. 원본 `hooks.json`은 전부 빈 객체다.

추가 게이트 (원본 README):

- 투자 권유 / 거래 집행 / 리스크 바인딩 / 원장 전기 / 온보딩 승인 = 런타임에서 거부.
- 산출물 상태는 `staged_for_signoff`. harness verdict `pass`는 “사람이 서명해도 되는 초안”이지 “원장에 넣어도 된다”가 아니다.

KYC 문서 래퍼를 유지한다:

```
<untrusted_document> … </untrusted_document>
```

## 6. MCP

Neos MCP 레이어에 두 묶음으로 나눈다.

**시장 데이터 (Mode A)**  
Daloopa, FactSet, CapIQ/Kensho, Morningstar, Moody’s, LSEG, PitchBook, Aiera, MT Newswires. 구독/키가 없으면 스킬이 MCP 우선 → 사용자 제공 → 웹 폴백 순서를 유지하되, comps는 “웹을 primary로 쓰지 말 것”.

**내부 시스템 (Mode B)**  
`internal-gl`, `subledger`, `screening`, `portfolio`, `nav`, `crm`. 원본은 URL env placeholder만 있다. Neos 배포 시 실제 서버를 붙이기 전에는 **read-only stub** + “connector missing → stop and surface”.

`.mcp.json` 콤마 버그는 이식본에서 고친다. LSEG URL은 파트너 path(`server-cl`)와 코어 path를 설정으로 분리한다.

문서 스토어 Egnyte/Box는 KYC 패킷·GP 패키지 입력용. reader만 접근.

## 7. 아티팩트와 Office

| 원본 | Neos |
|---|---|
| Cowork live Excel/PPT MCP | 있으면 사용 (MS365 add-in 경로) |
| CMA `xlsx-author` / `pptx-author` → `./out/` | coding sandbox write + 아티팩트 수집. 기존 pptx/docx 스킬을 headless fallback으로 재사용 가능 |
| blue/black/green | 모델 스킬 불변 규칙으로 이전 |
| `ib-check-deck` + `extract_numbers.py` | 그대로 스크립트 스킬 |
| LibreOffice `soffice` visual QC | 선택. 원본도 “accurate renderer 아님” Disclaimer |

MS365 install 플러그인은 FSI 에이전트가 아니다. Neos가 Office add-in을 직접 프로비저닝할 계획이 없으면 **이식 범위 밖**. 부트스트랩이 스킬/MCP를 유저별로 밀어주는 패턴만 참고.

## 8. 핸드오프 버스

원본 `orchestrate.py`를 프로덕션으로 가져오지 않는다. 위협 모델이 그걸 금지한다.

Neos 대응:

- parent가 child fold를 받은 뒤, **도구 호출** `handoff.v1 {target, event, context_ref}`를 낸다.
- 서버가 allowlist + schema를 검사하고 대상 에이전트 세션에 steer.
- 문서에서 나온 동일 JSON 문자열은 도구가 아니면 무시.

Allowlist는 원본 10 slug + 이후 Neos id.

## 9. 제안 이식 순서

1. **안전 계약** — staged_for_signoff, no-post, never-approve, untrusted wrapper, one-writer. 코드보다 정책 테스트.
2. **카탈로그** — 49 vertical SKILL.md + meeting-prep 3개를 `skills/financial-services/`로. sync/drift CI.
3. **Mode B 파일럿** — `kyc-screener` 또는 `gl-reconciler`. reader schema + critic + writer. DA Worker와 가장 잘 맞는다.
4. **모델링 파일럿** — `model-builder` + `dcf-model`/`xlsx-author`. `./out/model.xlsx`.
5. **Mode A 피치** — `pitch-agent` (researcher / modeler / deck-writer). Bash는 sandbox만.
6. **핸드오프 버스** — earnings/pitch → model-builder, GL → month-end.
7. **파트너 MCP** — entitlement 있는 것만.
8. **MS365** — 별 트랙, 필요 시.

## 10. 명시적 비범위

- `claude-for-financial-advisors` (원본에도 없음)
- LSEG/S&P 데이터를 Neos가 재배포
- 원장/코어 뱅킹 write API
- KYC 자동 승인
- ER 레이팅을 고객 배포 가능한 research로 취급
- Contract-Net / 자식 간 메시지
- 원본 `orchestrate.py` 정규식 파서
