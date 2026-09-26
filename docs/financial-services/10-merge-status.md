# 10. Neos 병합 상태 — financial-services

조사 기준: 2026-09-25. Neos HEAD `2e621684` (`dev`). 원본 `/Users/yeonwoosung/Desktop/financial-services` (읽기 전용). 최종 부착 웨이브 부록: 같은 날, 커널·완결성 위에 Tasks 1–13이 `2e621684`까지 착륙했다.

이 문서는 원본 인벤토리(`00`–`09`)와 구현 계약(`spec/`)을 **대체하지 않는다**. 커널·완결성·최종 부착 웨이브가 착륙한 뒤, 원본 기능이 Neos 코드에 실제로 있는지를 재감사한 기록이다. 방법: 도메인 서브에이전트 16 + 후속 5, 이후 `2026-09-25-fsi-univer-final.md`.

분류:

| 라벨 | 뜻 |
|---|---|
| **MERGED** | Neos 커널 코드에 있다 (경로 인용) |
| **PARTIAL** | 조각만 있다 |
| **DEFERRED** | 스펙/플랜이 이 웨이브 밖으로 잠갔다 |
| **GAP** | 이 웨이브가 요구하거나, 킬 스위치 주장과 어긋난다 |
| **OUT OF SCOPE** | 원본 기능이 Neos 이식 목표가 아니다 |

판정 막대는 둘이다.

1. **커널 + 최종 부착 웨이브** — `docs/superpowers/plans/2026-09-25-fsi-kernel.md` + completeness + review-fixes + `2026-09-25-fsi-univer-final.md`. 이 막대는 대체로 맞다.
2. **원본 제품** — HTTP `/api/v1/fsi`, MS365, 라이브 MCP, 파트너 스킬, WM 복원. 이 막대는 아직 비어 있다. 48 Anthropic 스킬 · 10 프로필 · MCP 스텁 · parent-only xlsx · 핸드오프 버스는 붙었다.

---

## 1. 한 줄

FSI는 `ParentKind.FSI`와 kebab 다섯 개로 **딥 하네스에 붙어 있다**. 48 Anthropic 스킬, 10개 프로필, `run_parent_spawn` 드라이버, 스크린닝 MCP 스텁, `stage_xlsx.v1`, `handoff.py` `ALLOWED_EDGES`가 디스크에 있다. HTTP `/api/v1/fsi`와 부모 LLM이 `spawn_agent`를 해석하는 내구 턴 루프는 없다. KYC는 픽스처 + 생산 프로필로 `run_leaf` / `run_parent_spawn`이 돈다.

---

## 2. 커널에 있는 것

| 능력 | 상태 | 위치 |
|---|---|---|
| 다섯 kebab `fsi-reader\|writer\|critic\|puller\|modeler` | MERGED | `neos/subagent/catalog.py:159-259` |
| 별칭은 세션 `SpecRegistry` overlay. 모듈 `_SPECS` 불변 | MERGED | `catalog.py:363-404`; `tests/subagent/test_overlay_registry.py` |
| `ParentKind.FSI` + 마이그레이션 `064` | MERGED | `neos/subagent/types.py`; `db/migrations/064_allow_fsi_subagent_parent.sql` |
| `FsiConfig` 기본 off, child는 master 필요 | MERGED | `neos/config/schema.py:2014-2026` |
| CMA `output_schema` 10개 본문 = `READER_SCHEMAS` (필드 단위 동일) | MERGED | `neos/fsi/schemas.py:33-402` |
| fold 게이트: `completed`만, truncated면 `full_summary` | MERGED | `neos/fsi/loop.py:95-97` |
| 리더 `<untrusted_document>` + closer 무력화 | MERGED | `neos/fsi/ports.py:256-264` |
| 작성자 `./out/_spec/*.json` 감옥, nested `_spec` 쓰기 거부, `*.xlsx` → `xlsx_forbidden` | MERGED | `neos/fsi/ports.py:75,97` |
| 오케스트레이터 닫힌 토큰 컴파일 | MERGED | `neos/fsi/profile.py:13-21` |
| KYC 리프 이름 KD17 (`kyc-doc-reader` / `kyc-rules-engine` / `kyc-escalator`) | MERGED | `tests/fsi/fixtures/profiles/kyc-screener.yaml:19-45` |
| critic에 `mcp.screening.search` 이름 union (카탈로그 싱글톤 불변) | MERGED (이름 + 스텁) | `neos/fsi/profile.py:23-25,105-109`; `mcp_attach.py` |
| `BINDING_ACTIONS` 집합 + `quoted_json_is_handoff` → False | MERGED (헬퍼) | `neos/fsi/safety.py` |
| execute 경로 `policy_binding_denied` | MERGED | `FsiParentWorkspacePort` / `FsiSessionPort` (`ports.py:56-57,206-207`) |
| `fsi_catalog()` + `references/` 로드 별칭 | MERGED | `neos/skills/markdown_catalog.py:66-96,405` |
| 48 Anthropic `SKILL.md` (skill-creator·파트너 제외, WM `.gitkeep`만) | MERGED | `skills/financial-services/<vertical>/` |
| `FsiSessionPort.load_skill.v1` | MERGED | `ports.py:212-253` |
| `mcp_attach.py` 스크린닝 스텁 (HTTP 없음) | MERGED | `neos/fsi/mcp_attach.py` |
| `stage_xlsx.v1` 부모 전용 `out/*.xlsx` | MERGED | `neos/fsi/stage_xlsx.py`; `ports.py:48-51,67-68` |
| `handoff.py` `ALLOWED_EDGES` | MERGED | `neos/fsi/handoff.py:26-34` |
| `run_parent_spawn` + `overlay_catalog` + `FlagDisabled` + `cancel_fsi_children` | MERGED | `neos/fsi/loop.py:25-107` |
| 10 named 프로필 YAML | MERGED (compile) | `skills/financial-services/profiles/` |
| 코딩 `spawn_agent.v1` `fsi-*` → `policy_unknown_spec` | MERGED | `neos/coding/loop/_durable/spawn.py:794-795` |
| `can_approve=False`, `can_spawn=False`, `one_shot=True` | MERGED | `catalog.py` 다섯 템플릿 |
| Mode B `NONE` / Mode A 비작성자 `PARENT_RO` / 작성자 `WORKTREE` **스탬프** | MERGED | `neos/fsi/profile.py:123-133` |
| stepper: FSI 이름은 explore 프롬프트가 아님 | MERGED | `neos/subagent/stepper.py:117-122` |
| HTTP `/api/v1/fsi`, MS365, CMA `POST /v1/agents` | OUT OF SCOPE | `neos/` · `web/`에 라우트 없음 |

`neos/fsi/` 런타임 파일: `loop.py`, `ports.py`, `profile.py`, `safety.py`, `schemas.py`, `mcp_attach.py`, `handoff.py`, `stage_xlsx.py`.

---

## 3. 10 named agent → kebab

CMA 오케스트레이터 10/10은 default-deny + `read`/`grep`/`glob` + 신뢰 MCP. Write는 리프 하나. Neos 생산 격리는 `isolation_surface: cma_leaves`.

별칭은 overlay에만 있다. 모듈 `lookup_spec("kyc-doc-reader")`는 `UnknownSpec`이다 (`tests/fsi/test_loop.py:80-81`). 마스터 스펙 문장(`FSI_NEOS_MIGRATION_SPEC.md:341`)은 모듈 lookup을 요구한다. **잠금은 overlay** (`2026-09-25-fsi-kernel-completeness.md:17`).

| CMA 에이전트 | Mode | CMA 리프 | Neos kebab | 상태 |
|---|---|---|---|---|
| kyc-screener | B | doc-reader / rules-engine / **escalator** | reader / critic+screening / writer | **PARTIAL** — 픽스처 + 생산 YAML 컴파일, `run_leaf` / `run_parent_spawn`. 라이브 부모 LLM 루프·HTTP 없음 |
| gl-reconciler | B | reader / critic / **resolver** | reader/critic/writer | PARTIAL — 생산 YAML compile. 라이브 그래프 DEFERRED PR7 |
| month-end-closer | B | ledger-reader / rollforward / **poster** | reader/critic/writer | PARTIAL — 생산 YAML compile. 라이브 그래프 DEFERRED PR8 |
| statement-auditor | B | statement-reader / reconciler / **flagger** | reader/critic/writer | PARTIAL — 생산 YAML compile. 라이브 그래프 DEFERRED PR8 |
| valuation-reviewer | B | package-reader / runner→critic / **publisher** | reader/critic/writer | PARTIAL — 생산 YAML compile. 라이브 그래프 DEFERRED PR9 |
| model-builder | A | data-puller / **builder+bash** / auditor | puller + WORKTREE 스탬프 | PARTIAL — 생산 YAML compile. builder `execute.v1`는 컴파일러가 거부 (**UNRESOLVED** FSI-2) |
| pitch-agent | A | researcher / modeler+bash / **deck-writer** | puller + modeler 템플릿 | PARTIAL — 생산 YAML compile. 라이브 그래프 DEFERRED PR11 |
| market-researcher | A | sector-reader / comps-spreader / **note-writer** | reader/critic/writer | PARTIAL — 생산 YAML compile. 라이브 그래프 DEFERRED PR12 |
| earnings-reviewer | A | transcript-reader / model-updater / **note-writer** | reader/critic/writer | PARTIAL — 생산 YAML compile. 라이브 그래프 DEFERRED PR12 |
| meeting-prep-agent | A | news-reader / profiler / **pack-writer** | reader/critic/writer | PARTIAL — 생산 YAML compile. WM 복원 DEFERRED (KD7) |

`earnings-model-updater` · `market-comps-spreader` · `briefing-profiler`는 `fsi-critic`이다 (`fsi-puller`는 `pitch-researcher`와 `model-data-puller`만, KD19).

생산 프로필 YAML: `skills/financial-services/profiles/` 10개 (KYC는 픽스처와 동일 모양). 픽스처 `tests/fsi/fixtures/profiles/kyc-screener.yaml`은 유지. 둘 다 spec 예시에서 `version` / `identity` / `model` / `system_prompt_path` / `human_gates`를 뺀다. `load_profile`은 그 필드를 강제하지 않는다 (`neos/fsi/profile.py:136-158`). 아홉 그래프는 compile/schema-only. KYC만 `run_parent_spawn` 드라이버가 리프를 스폰한다.

픽스처 프롬프트 `tests/fsi/fixtures/prompts/kyc-screener.md`는 원본 Guardrails의 의역이다. 로더는 `system_prompt_path`를 인라인하지 않는다.

---

## 4. 스킬 팩

원본 canonical: `plugins/vertical-plugins/` 아래 **49** `SKILL.md` 디렉터리 (6 버티컬). `skill-creator` 제외 48 + 복원 WM 3 = 스펙 포트 집합 51. 파트너 11 (LSEG 8 + S&P 3).

| 그룹 | 상태 |
|---|---|
| `skills/financial-services/<vertical>/<skill>/SKILL.md` | MERGED — 48 Anthropic (financial-analysis 12, ER 9, IB 9, PE 10, fund-admin 6, operations 2). `skill-creator` 제외 |
| `fsi_catalog()` / `fsi_skill_roots()` | MERGED — `markdown_catalog.py:66-96`. 버티컬별 루트. `default_catalog()`에 없음 |
| FSI `load_skill.v1` ∩ allowlist | MERGED — `FsiSessionPort` (`ports.py:212-253`). 코딩 `executor.py`는 `default_catalog()`만 (의도) |
| `default_skill_roots`에 FSI 미포함 | MERGED (부재로 성립) |
| `references/` (복수) 로드 별칭 | MERGED — `_load_reference`가 `reference/` 다음 `references/` (`markdown_catalog.py:405`) |
| wealth-management | PARTIAL — `.gitkeep`만. 스킬 0 |
| meeting-prep 3 orphan | DEFERRED (KD7, WM 복원 전). `meeting-prep-agent.yaml`은 vendored `pptx-author`만 |
| 파트너 LSEG/S&P | DEFERRED PR15. `fsi_lseg_catalog()` / `fsi_spglobal_catalog()` 생성자는 있음, 트리 없음 |
| `sync-agent-skills.py`, FSI `skill-creator` | OUT OF SCOPE |
| generic `skills/xlsx`, `skills/pptx` | FSI `xlsx-author` / `pptx-author`가 아님 (D7) |

KYC 픽스처·생산 `skill_allowlist`는 `kyc-doc-parse` / `kyc-rules` / `xlsx-author`. 세션 포트는 카탈로그에서 markdown을 연다. 컴파일러는 여전히 `SKILL.md`를 열지 않는다.

---

## 5. MCP

원본 `.mcp.json` 5개. financial-analysis 허브 JSON은 깨져 있다 (egnyte 뒤 콤마, box 객체). CMA는 서버 이름만 적고 도구 목록은 없다. 스크린닝 도구 이름 `search`는 Neos가 골든으로 정한 것이다.

| 표면 | 상태 |
|---|---|
| `mcp.<server>.<tool>` 정확한 이름, glob 거부 | MERGED (컴파일러) |
| `mcp.screening.search` on `kyc-rules-engine` | MERGED (스텁) — allowlist union + `mcp_attach.screening_search` → `{ok: True, hits: []}` |
| 부모/오케스트레이터 MCP | GAP vs KYC spec (`spec/agents/kyc-screener.md:162-163`). 픽스처·생산 `mcp_allowlist: []` |
| `capiq` / `daloopa` / `factset` / `internal-gl` 등 | 컴파일러가 문자열만 보고 drop. DEFERRED PR5 |
| `neos/fsi/mcp_attach.py` | MERGED (스텁, HTTP 없음) |
| `FsiConfig.partner_mcp` | MERGED (플래그만). attach 소비자 없음 |
| 빈 IB/PE `.mcp.json` | OUT OF SCOPE |
| 라이브 MCP HTTP / `SCREENING_MCP_URL` | DEFERRED |

---

## 6. 안전 · 핸드오프 · 바인딩

| 항목 | 상태 |
|---|---|
| `orchestrate.py` 정규식 미이식 | MERGED (의도) |
| `handoff.v1` 오케스트레이터 토큰, 빈 allowlist면 생략 | MERGED |
| `handoff.v1` 런타임 라우터 / `ALLOWED_EDGES` | MERGED — `neos/fsi/handoff.py`. `FsiSessionPort`는 `handoff_allowlist`가 비어 있지 않을 때만 노출. 생산 10 YAML은 `handoff_allowlist: []` |
| 리프에서 `handoff.v1` ∈ `REFUSED_TOOLS` | MERGED |
| Guardrails 10편 원문 동결 | GAP — `skills/financial-services/agents/<slug>.md` 없음. 리프 프롬프트는 generic (`neos/subagent/prompts.py:23-45`) |
| `approve_onboarding` ∈ `BINDING_ACTIONS` | MERGED (집합) |
| execute 경로 `policy_binding_denied` | MERGED — `FsiParentWorkspacePort` / `FsiSessionPort`가 멤버십보다 먼저 거부 (`ports.py:56-57,206-207`). 미등록 비바인딩 이름은 `tool_not_allowed` |
| `SUCCESS_ARTIFACT_STATUS` | MERGED (stage_xlsx 성공 상태). `loop.py` fold는 쓰지 않음 |
| 빈 `hooks.json` → PreToolUse 미도입 | MERGED |

---

## 7. Mode A / Mode B · 부모 루프

`neos/fsi/loop.py`는 `make_fsi_runtime` + `run_leaf` + `run_parent_spawn` 드라이버다. 부모 LLM이 `spawn_agent.v1`를 해석하는 내구 턴 루프는 없다. `nested_spawn`은 `None`.

| 항목 | 상태 |
|---|---|
| Mode A/B 샌드박스 스탬프 | MERGED |
| Mode A WORKTREE 바인드 | DEFERRED — 스탬프만. FSI 부모에서 git worktree open 없음 |
| `stage_xlsx.v1` | MERGED 부모 전용 `out/*.xlsx` (`stage_xlsx.py`). 자식 `write_file.v1` `*.xlsx`는 `xlsx_forbidden` |
| `glob_files.v1` 부모 포트 | MERGED — `FsiParentWorkspacePort(write=False)` 정의에 glob+stage (`ports.py:48-51`) |
| `run_parent_spawn` / `overlay_catalog` / `FlagDisabled` / `cancel_fsi_children` | MERGED (`loop.py`). 플래그 off면 스폰 전 `FlagDisabled` |
| `model-builder-builder` + `execute.v1` | **UNRESOLVED** — `00-harness-and-profile.md:339`는 이 별칭에 bash를 허용. `compile_leaf_spec`은 템플릿 밖 도구를 거부. `FSI_WRITER`에 `execute.v1` 없음. 생산 YAML도 넣지 않음 |
| `FsiConfig.enabled`가 `run_parent_spawn`을 게이트 | MERGED (`enabled is False` → `FlagDisabled`). `run_leaf` 직접 호출은 게이트하지 않음 |

커널 Task 8이 `run_leaf`만 만들도록 잠갔다. 최종 웨이브가 드라이버를 얹었다. 라이브 부모 모델 루프는 다음 웨이브.

---

## 8. HTTP / UI / MS365

| 원본 표면 | 분류 |
|---|---|
| `deploy-managed-agent.sh` → `POST /v1/agents` | OUT OF SCOPE |
| `claude-for-msft-365-install/` (Graph, sideload, Entra) | OUT OF SCOPE |
| Cowork marketplace / `plugin.json` | OUT OF SCOPE (프로필로 접힘) |
| `POST /api/v1/fsi/sessions`, `web/app/(fsi)/` | DEFERRED — 코드 없음. 커널 플랜이 HTTP를 금지 |
| `fsi_sessions` DDL | DEFERRED. 있는 것은 parent_kind CHECK `064`뿐 |

프로덕션 YAML에 `fsi:` 키가 없다. 플래그 기본값은 off다.

---

## 9. 테스트가 가리는 것

`tests/fsi/` + `tests/subagent/test_fsi_*` + `tests/config/test_fsi_config.py`. 로컬 `Settings()` teardown ERROR는 기존 이슈다.

거짓 확신:

- KYC 픽스처 = 생산 `skills/financial-services/profiles/kyc-screener.yaml` 모양. 둘 다 identity/model 생략, 로더가 거부하지 않음
- `READER_SCHEMAS` 테스트는 **키 집합**. 9/10 본문 골든 없음 (감사 당시 CMA YAML walk는 본문 일치)
- `quoted_json_is_handoff`는 `return False` 항진
- `_FSI_ALIASES`는 스키마 리프 10 + KYC critic/writer. 나머지 ~18 별칭은 메트릭이 `"explore"`로 접힘
- review-fix cancelled/stalled fold는 `failed`만 검증
- Mode A 테스트는 발명한 2-리프 dict. `pitch-modeler`를 빠뜨림

테스트 제로 KD: KD7 WM 복원, KD10 `model.role`, KD13 model-builder 중간 작성자 `execute.v1`, KD14 DCF 엔진, KD15 허브 JSON. 스킬 트리·핸드오프 엣지·`load_skill` FSI는 이 웨이브가 잠갔다.

---

## 10. 스펙 vs 코드 (FSI)

잠금은 커널/완결성 플랜 + 착륙 테스트다.

| ID | 스펙 문장 | 코드 | 상태 |
|---|---|---|---|
| FSI-1 | 모듈 `lookup_spec("kyc-doc-reader")` 성공 | overlay만 | LOCKED→code |
| FSI-2 | `model-builder-builder`에 `execute.v1` | 컴파일러 거부 | **UNRESOLVED** |
| FSI-3 | KYC 부모 `mcp_allowlist: [screening]` | 픽스처 `[]`, 리프만 union | LOCKED→code (이 웨이브) |
| FSI-4 | `identity` / `model` 필수 | 로더 미검사 | LOCKED→code (커널 서브셋) |
| FSI-5 | `skills/financial-services/agents/<slug>.md` | 디렉터리 없음 (프로필 YAML만) | UNRESOLVED (경로도 문서마다 다름) |
| FSI-6 | `loop.py` 부모 세션 | `run_parent_spawn` 드라이버. 라이브 부모 LLM 루프 없음 | LOCKED→code (드라이버) |
| FSI-7 | 빈 handoff allowlist면 strip | `ProfileError` | LOCKED→code |

---

## 11. 코딩 부모 스폰 (공통 — kebab는 MERGED)

`neos/coding/loop/_durable/spawn.py:794-795`는 `lookup_spec` **전에** `fsi-` / `univer-` prefix를 거부한다. `spec=fsi-reader` 등 아홉 kebab는 `policy_unknown_spec`, 자식 런 0 (`tests/coding/loop/test_spawn_subagent.py`). 플래그는 이 경로를 열지 않는다.

세션 overlay 별칭(`kyc-doc-reader` 등 `fsi-` prefix 없음)은 이 게이트 밖이다. 코딩 세션에 overlay가 있으면 여전히 `lookup_spec`이 성공할 수 있다 (**GAP**, 이 웨이브 비목표).

DA는 spec을 `explore`/`research`로 하드코딩한다. 워크플로 템플릿 `spec`은 kebab prefix로 막힌다.

---

## 12. 다음 웨이브 (우선)

1. HTTP `/api/v1/fsi` · MS365 — 사용자가 요청하기 전까지 시작하지 않는다
2. 파트너 LSEG/S&P 스킬 트리
3. wealth-management 복원 (meeting-prep orphan)
4. FSI-2 `model-builder-builder` `execute.v1` (컴파일러가 여전히 거부)
5. 라이브 MCP HTTP / `SCREENING_MCP_URL`
6. Mode A WORKTREE 바인드 (스탬프 너머 git worktree open)
7. 코딩 overlay 별칭을 `fsi-`/`univer-` prefix 없이 거부
8. 부모 LLM이 `spawn_agent`를 해석하는 내구 턴 루프 (`run_parent_spawn`은 드라이버일 뿐)
