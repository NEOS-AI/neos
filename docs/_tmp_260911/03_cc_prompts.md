# Claude Code Prompts/Skills → NEOS 갭 분석

작성: explore 서브에이전트 `Analyze CC prompts/skills` (2026-09-11). 메인 에이전트가 파일로 고정.

복붙 금지. 아래는 구조와 의도만 요약한다. Anthropic 브랜드/내부 정책 원문 재배포 금지.

## 1. CC 프롬프트 조립 파이프라인

CC는 시스템 프롬프트를 **문자열 배열**로 조립한다. 진입점 `getSystemPrompt()` (`src/constants/prompts.ts`). 섹션 레지스트리 `systemPromptSections.ts`. `cacheBreak: true`만 매 턴 재계산.

시스템 프롬프트와 별도 축: `getSystemContext` / `getUserContext` (`src/context.ts`)가 git 상태·CLAUDE.md·날짜를 **대화 앞 user/system context**로 붙인다.

### 정적 구간 (캐시 가능)

| 섹션 | 함수 | 조건 |
|---|---|---|
| Intro | `getSimpleIntroSection` | 항상 |
| System | `getSimpleSystemSection` | 권한 모드, hook, compact, injection 플래그 |
| Doing tasks | `getSimpleDoingTasksSection` | output style이 없거나 `keepCodingInstructions` |
| Actions | `getActionsSection` | 가역/비가역 게이트 |
| Using tools | `getUsingYourToolsSection` | 전용 도구 vs Bash 역할 분리 |
| Tone | `getSimpleToneAndStyleSection` | 항상 |
| Efficiency | `getOutputEfficiencySection` | 외부/내부 문구 분기 |

### 동적 구간 (경계 뒤)

마커: `SYSTEM_PROMPT_DYNAMIC_BOUNDARY`. 세션 비트(Agent/Skill/Explore 안내)를 정적 prefix에 넣으면 캐시가 갈라지므로 경계 뒤로 옮겼다.

| 섹션 | 조건 |
|---|---|
| `session_guidance` | 활성 도구에 따라 |
| `memory` | `loadMemoryPrompt()` |
| `env_info_simple` | cwd, git, platform, model |
| `output_style` | `getOutputStyleConfig()` |
| `mcp_instructions` | MCP connect 변동 (uncached) |
| `token_budget` | `TOKEN_BUDGET` |

서브에이전트는 `getSystemPrompt`를 타지 않는다. `DEFAULT_AGENT_PROMPT` + env details.

NEOS: `AnthropicLoopConfig.system`은 단일 문자열. 런타임 기본값은 `runtime.py:516`의 한 줄. 섹션, 경계, `cache_control` 없음 (`coding/model/anthropic.py` `_to_anthropic_request`).

채팅 쪽 `SystemPromptBuilder`는 `base + workflow + artifacts + inline_vis`만 이어 붙인다.

## 2. 코딩 에이전트 행동 계약 (NEOS 자체 문구로 재작성)

| 규칙 | CC 출처 | NEOS 현재 | 이식 방법 |
|---|---|---|---|
| 읽지 않은 코드는 바꾸지 않는다 | Doing tasks | 없음. pre-read 강제 없음 | 시스템 섹션 + write/edit description |
| 요청 범위를 넘지 않는다. 과잉 추상화 금지 | 동일 | 1줄 system | `# Doing tasks` NEOS 문구 |
| 완료 전에 실행으로 검증. 못 하면 명시 | thoroughness | tool 없으면 종료 | “테스트/린트를 안 돌렸으면 성공이라고 쓰지 말 것” |
| 결과를 사실대로. 미완료를 완료로 포장 금지 | false-claims 완화 | 없음 | 공개 문구로 완화 이식 |
| 전용 도구 우선, 셸은 최후 | Using tools | 역할 분리 없음 | 시스템 + 각 툴 X vs Y |
| 독립 호출은 병렬, 의존은 직렬 | 동일 | 설계 문서만 | 모델 계약 한 문장 |
| 비가역·공유·외부 공개는 확인 후 | Actions | 정책은 코드, 모델 안내 없음 | “언제 멈추나” 문단 |
| 툴 거부 후 동일 호출 재시도 금지 | System | deny는 루프에 있음 | deny result + 재시도 금지 |
| 외부 툴 결과에 주입 의심 시 먼저 표시 | System | 문서만 (`NEOS_CODING.md` §12.3) | 시스템 한 줄 + result 태그 |
| 이모지/플레이-바이-플레이 금지 | Tone | 없음 | 기본 스타일 |
| 새 파일·README 남발 금지 | Write 툴 | write_file만 | Edit 분리 후 안내 |
| 막히면 원인 진단 후 전술 변경 | Doing tasks | 없음 | “조사 후 질문” |

가져오지 말 것: `USER_TYPE==='ant'` 전용, 브랜드 prefix, attribution 헤더.

## 3. 툴 디스크립션 패턴

CC 패턴: **한 줄 역할 + When/When-not + 다른 툴 포인터 + 실패 모드**.

| 툴 | 역할 | 쓰지 말 때 |
|---|---|---|
| Read | 파일. offset/limit | 디렉터리 → list/Bash |
| Grep | rg. Bash grep 금지 | 다회전 탐색 → Agent |
| Glob | 이름 패턴 | 다회전 glob+grep → Agent |
| Edit | 정확 치환. 한 번은 Read | 신규 파일 → Write |
| Write | 생성/전체 재작성 | 부분 수정 → Edit |
| Bash | 전용 툴이 없는 시스템 | cat/sed/find/grep 대체 금지 |
| Agent | 다회전·컨텍스트 보호 | 한 파일/한 심볼 |
| TodoWrite | 3+ 스텝 | 한 줄 수정·잡담 |
| AskUserQuestion | 선호도/분기 | 플랜 승인 → ExitPlanMode |

NEOS 코딩 레지스트리 설명은 한 줄이다. `NEOS_CODING.md` §6.1 목표 이름과 구현 이름(`*.v1`)이 어긋나 있다. 프롬프트 작업 전에 **이름 표를 고정**.

권장 description 골격: 목적 → 경로 규칙 → 고르는 신호 → 대신 쓸 툴 → 실패 시 할 일.

`execute.v1`에는 정책 요약을 넣는다: 셸 `-c` 금지, 네트워크 금지, 패키지 install 금지, git은 status/diff/log만.

## 4. 스킬 / 메모리 / 아웃풋 스타일

### 스킬 — 점진적 공개

CC: 이름+짧은 description만 노출 → Skill 툴이 본문 펼침. 목록 캡 250자, 예산 ≈ 컨텍스트 1%.

NEOS: `generate_skills_prompt(..., include_body=True)`가 기본이라 XML에 본문을 넣는다. 코딩 루프와 미연결.

매핑: 코딩 시스템/reminder에 인덱스만 → `load_skill.v1`이 본문을 tool result로. 채팅 문서변환 스킬과 **trust zone 분리**.

### 메모리

CC 3층: CLAUDE.md 계층 / `memdir` MEMORY.md / 에이전트 메모리.

NEOS: 연구용 3층 (`neos/memory/`)은 코딩 task와 무관. 설계만 (`NEOS_CODING.md` §5.3). 구현 없음.

권장: 기본 파일명 **`AGENTS.md`**, `CLAUDE.md`는 호환 별칭. 시스템 프롬프트가 아니라 **task bootstrap user context**.

### 아웃풋 스타일

CC: default / Explanatory / Learning. NEOS 코딩/채팅 모두 없음. P2: `default | explanatory | terse`.

## 5. 서브에이전트 프롬프트 전문화

| 타입 | 계약 | 툴 |
|---|---|---|
| Explore | 읽기 전용. 병렬 검색. 파일 생성 금지 | Edit/Write/Agent 금지 |
| Plan | 읽기 전용 설계. Critical Files 3–5 | Explore와 동일 |
| Verification | 적대적 검증. `VERDICT: PASS\|FAIL\|PARTIAL` | 프로젝트 쓰기 금지 |
| general-purpose | 조사+구현. 짧은 보고 | `tools: ['*']` |
| Coordinator | 사용자와만 대화. 결과 날조 금지 | 워커가 구현 |

NEOS는 단일 에이전트. 1차 이식은 서브에이전트 런타임이 아니라 **같은 계약을 메인 루프 페이즈로**:

- explore: 쓰기 툴 미노출
- implement: 전체 툴
- verify: 쓰기 차단, 실행/테스트만, 구조화 보고

## 6. 갭과 병합 후보

| ID | 항목 | 붙일 경로 | 작업량 | 리스크 |
|---|---|---|---|---|
| P0-a | 섹션형 코딩 시스템 프롬프트 | `neos/coding/prompts/` + `AnthropicLoopConfig.system` | S | 낮음 |
| P0-b | 툴 description 확장 + X vs Y | `coding/tools/registry.py` | S | 낮음 |
| P0-c | 검증·정직 보고 문장 | Tasks 섹션 | S | 중간(턴/비용) |
| P1-a | `AGENTS.md`/`CLAUDE.md` bootstrap | `coding/context/instructions.py` | M | 중간(repo 주입) |
| P1-b | Edit/patch + pre-read | registry + executor | M | 중간 |
| P1-c | 코딩 스킬 인덱스 + invoke | SkillManager `include_body=False` + `load_skill` | M | 중간 |
| P1-d | 정적/동적 분할 + cache_control | `coding/model/anthropic.py` | M | 중간 |
| P1-e | Todo 툴 | `todo_replace`/`todo_update` | S | 낮음 |
| P2-a | Explore/Plan/Verify 페이즈 또는 서브에이전트 | loop phase + 제한 툴셋 | L | 높음 |
| P2-b | Output styles | settings + 동적 섹션 | S | 낮음 |
| P2-c | 파일 메모리 | task/user store. 연구 MemoryManager와 분리 | L | 중간 |
| P2-d | Coordinator | 비목표 | — | 하지 않음 |

`CYBER_RISK_INSTRUCTION`은 이 덤프에서 빈 문자열. 원문 복원 금지. NEOS 자체 안전 문단만.

## 7. 권장 구현 순서

1. `neos/coding/prompts/` — `build_coding_system_prompt(tools, env) -> str`. `"Work safely…"` 하드코딩 제거.
2. 툴 description을 빌더와 함께 교체. schema 유지.
3. 행동 계약 6줄: 읽고 수정, 범위 준수, 전용 툴, 검증, 정직 보고, 비가역은 확인.
4. Instruction discovery (`AGENTS.md` + `CLAUDE.md`). user context, 토큰 캡, injection 경고.
5. 캐시: 도구 목록이 안정된 뒤 정적/동적 분할.
6. `apply_patch`/`edit_file` + pre-read.
7. 코딩 전용 스킬 2개: `verify`, `commit` (요청 시에만).
8. 페이즈 또는 읽기 전용 서브에이전트. 메트릭 본 뒤.
9. 스타일/메모리 파일/플랜 모드. 제품 요구 시.

## 8. 가져오면 안 되는 것

- Anthropic 브랜드·제품명·CLI prefix, attribution
- 유출 시스템 프롬프트 전문 재배포
- 내부 전용: Slack 채널 ID, GrowthBook 플래그, ant-only 앵커
- `CYBER_RISK_INSTRUCTION` 원문
- Coordinator/team/fork/remote isolation — Phase 1 비목표
- 채팅 연구 메모리를 코딩 자동 메모리로 재사용

## 9. 근거 파일 목록

CC: `src/constants/{prompts,systemPromptSections,system,outputStyles,cyberRiskInstruction}.ts`, `src/context.ts`, `src/utils/claudemd.ts`, `src/utils/api.ts`, `src/services/api/claude.ts`, `src/memdir/`, `src/skills/`, `src/tools/*/prompt.ts`, `src/tools/AgentTool/built-in/*`, `src/coordinator/coordinatorMode.ts`.

NEOS: `neos/coding/runtime.py:516`, `loop/anthropic.py`, `model/anthropic.py`, `tools/registry.py`, `api/services/chat_system_prompt_builder.py`, `neos/skills/`, `neos/memory/manager.py`, `docs/NEOS_CODING.md` §5.3/§6/§12.3.

**구현 상태 한 줄:** 코딩 루프·샌드박스·정책은 있고, **모델에게 말하는 계약은 거의 없다.** 가장 싼 품질 향상은 프롬프트 조립 + 툴 디스크립션이다.
