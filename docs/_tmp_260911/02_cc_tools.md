# Claude Code Tools → NEOS 갭 분석

코딩 루프 기준. CC 카탈로그는 `getAllBaseTools()` (`src/tools.ts`)가 소스 오브 트루스. NEOS 코딩 툴은 `CodingToolRegistry._TOOL_SPECS` 9개만. `neos/tools/`, `neos/skills/`는 코딩 루프에서 import/호출되지 않음 (`neos/coding/**` grep 0건).

작성: explore 서브에이전트 `Analyze CC coding tools` (2026-09-11). 메인 에이전트가 파일로 고정.

성숙도: **있음** / **부분** / **스텁** / **없음** / **일반챗** / **가져오면안됨**.

## 1. CC 툴 카탈로그

| Tool | 역할 | 권한/안전 | 병렬성 | NEOS 대응 | 성숙도 | 우선순위 |
|---|---|---|---|---|---|---|
| Read | 파일/이미지/PDF/ipynb. offset/limit | read 권한, 디바이스 차단 | RO 병렬 | `read_file.v1` (전체 bytes, preview 절단) | 부분 | P0 |
| Edit | exact string replace. 사전 Read 필수 | write + secrets + mtime | 직렬 | 없음. `write_file.v1`는 통째 overwrite | 없음 | P0 |
| Write | 생성/전체 재작성. 기존 파일은 사전 Read | write + secrets | 직렬 | `write_file.v1` | 부분 | P0 |
| Bash | `command` 문자열 셸 | AST+치환차단+path+sed+classifier | RO면 병렬 | `execute.v1` argv allowlist. `sh -c` 거부 | 부분 | P0 |
| Glob | 이름 패턴, 100파일 truncate | read 권한 | RO 병렬 | `list_tree.v1` (디렉터리 나열만) | 부분 | P0 |
| Grep | ripgrep. content/files/count, -A/-B/-C | read 권한, VCS 제외 | RO 병렬 | `search_text.v1` (limit≤100) | 부분 | P0 |
| TodoWrite | 세션 체크리스트 | 항상 allow | 직렬 | snapshot `todos` 필드만. 루프 툴 없음 | 스텁 | P0 |
| Agent | 서브에이전트 | 본체 allow, 자식 툴이 권한 | 병렬(본인은 RO) | 없음 | 없음 | P1 |
| Skill | slash skill 로드/실행 | skill 이름 룰 | 직렬 | `neos/skills`는 챗 전용 | 일반챗 | P1 |
| ToolSearch | deferred 툴 스키마 fetch | RO | RO 병렬 | `search_tools`는 `chat_llm_service`만 | 일반챗 | P1 |
| AskUserQuestion | 1–4개 MCQ | 사용자 응답이 권한 | RO 병렬 | `CodingApproval`은 툴 승인이지 질문 아님 | 부분 | P1 |
| WebFetch | URL→markdown | host 규칙 | RO 병렬 | 없음. `execute`에서 curl/wget 거부 | 없음 | P1 |
| WebSearch | 서버 툴 | passthrough→ask | RO 병렬 | `neos/tools/tools/web_search.py` 챗 전용 | 일반챗 | P1 |
| Enter/Exit PlanMode | 모드 전환 + 플랜 승인 | 메인 스레드만 | Enter RO | 없음 | 없음 | P1 |
| Enter/Exit Worktree | git worktree 격리 | shouldDefer | 기본 직렬 | 샌드박스 워크스페이스가 이미 격리 | 없음 | P2 |
| LSP | 9 op | read 권한 | RO 병렬 | 없음 | 없음 | P2 |
| NotebookEdit | ipynb cell 편집 | write | 직렬 | 없음 | 없음 | P2 |
| git_status/diff/log | (CC는 Bash) | — | — | NEOS 1급 RO 툴 3개 | 있음 | — |
| list_tree / stat | (CC는 Bash/Glob) | — | — | NEOS 1급 RO | 있음 | — |
| Task* / Team* / SendMessage | 비동기 태스크·멀티에이전트 | 혼재 | 혼재 | 런 엔티티는 있으나 모델 툴 아님 | 다른 계층 | P2 |
| MCP | 동적 MCP | deny 룰, 기본 defer | 툴별 | 챗 MCP만 | 일반챗 | P2 |
| Tungsten / REPL / OverflowTest 등 | ant/실험/UI | — | — | — | 가져오면안됨 | — |

## 2. 툴 파이프라인

### CC

`runTools` → `partitionToolCalls`가 `isConcurrencySafe(input)`로 배치 분할. 연속 RO는 최대 10 병렬, 비RO는 직렬.

단일 호출: Zod parse → deferred 힌트 → `validateInput` → Bash classifier → PreToolUse hooks → `canUseTool` → `tool.call` → 결과 크기 캡.

권한 모드: `default` | `plan` | `acceptEdits` | `bypassPermissions` | `dontAsk`. 룰 소스: user/project/local/flag/policy/cli.

### NEOS

`AnthropicCodingLoop._advance_one_tool`:

1. `CodingToolRegistry.validate` — 스키마 + 경로 + execute 정책
2. 실패 → `tool.denied`
3. `evaluate_approval`: READ_ONLY → ALLOW, 그 외 → REQUIRE_APPROVAL
4. 승인 없으면 대기
5. `claim_tool_execution` — 비RO reclaim 시 `tool_outcome_unknown`
6. `SandboxToolExecutor.execute`
7. checkpoint + `tool.completed`

한 턴의 여러 tool_use를 **순차** 처리. 병렬 배치/훅/classifier/모드 없음.

시스템 프롬프트는 `"Work safely in the provided sandbox and complete the coding task."` 한 줄 (`runtime.py:516`).

## 3. 핵심 툴별 상세 (P0)

### Read
- CC: 절대경로, offset/limit, 줄번호, 이미지/PDF/ipynb, 재읽기 stub.
- NEOS: `path`만, 상대·워크스페이스 한정, 바이트 preview+sha256.
- 가져올 것: offset/limit, 줄번호, “기존 파일은 먼저 읽어라”. 미디어는 후순위.
- 유지: 절대경로 금지, symlink escape.

### Edit
- CC: `old_string`/`new_string`/`replace_all`. 유일하지 않으면 실패. 사전 Read 강제.
- NEOS: **없음**. 가장 큰 생산성/안전 구멍.
- 붙일 곳: `edit_file.v1` (WORKSPACE_WRITE) + 사전 read 체크.

### Write
- CC: 기존 파일 사전 Read. Edit 우선.
- NEOS: content 전체 기록. 사전 read 없음. `.git/config|hooks|credentials` 쓰기 거부.
- 가져올 것: 사전 read 계약 + 짧은 사용 규약.

### Bash / execute
- CC: 자유 셸 문자열 + 보안 스택.
- NEOS: argv allowlist, `sh -c` 거부, 네트워크 거부, git은 status/diff/log만.
- 가져올 것: 파괴 경고 분류, RO vs COMMAND 세분. **자유 셸 문자열은 가져오면 안 됨.**

### Glob / Grep
- 가져올 것: glob 패턴, grep output_mode/head_limit/context, “검색은 전용 툴”.

### TodoWrite
- NEOS: `loop_state.todos`를 프로젝션만 읽음. 실루프가 쓰지 않음 → **스텁**.
- 붙일 곳: `todo_write.v1` (승인 불필요) + loop_state.

## 4. 가져올 툴 시스템

- **Deferred tool search**: 툴이 ~20+ 또는 MCP를 코딩에 넣을 때.
- **Permission classifier**: 작은 규칙 분류기만. yolo/auto 모드 금지.
- **Destructive command warnings**: `approval_display_summary`에 `warnings[]`. argv 기반.
- **Worktree isolation**: **복제 금지.** 샌드박스가 이미 다른 축.
- **Plan mode**: “읽기+검색만 하다가 승인 후 쓰기”를 `ToolRisk`+페이즈로.
- **병렬 RO**: P0 시스템.
- **프롬프트-애즈-정책**: 각 툴 description이 모델 행동을 가르침.

## 5. 갭과 병합 후보

| ID | 항목 | 붙일 경로 | 작업량 | 리스크 | 우선 |
|---|---|---|---|---|---|
| G1 | `edit_file.v1` | registry, executor, sandbox, tests | M | 중 | P0 |
| G2 | Read offset/limit + 줄번호 | registry, executor | S | 저 | P0 |
| G3 | 툴 description/사용 규약 | registry, runtime system | S | 저 | P0 |
| G4 | RO 병렬 실행 | anthropic.py 배치, claim 모델 | M | 중 | P0 |
| G5 | Glob/Grep 스키마 확장 | registry + sandbox | M | 저–중 | P0 |
| G6 | 승인 경고 + 세분 정책 | approvals.py | S | 중 | P0 |
| G7 | `todo_write.v1` | registry, loop_state | S | 저 | P0 |
| G8 | AskUser | approvals 또는 새 이벤트 | M | 중 | P1 |
| G9 | 코딩 Skill (좁은 세트) | 샌드박스 전용 스킬 로더 | M | 중 | P1 |
| G10 | Explore 서브에이전트 (RO) | 중첩 루프, 툴 필터 | L | 고 | P1 |
| G11 | Deferred ToolSearch | registry 플래그 | M | 중 | P1 |
| G12 | Plan 페이즈 툴 | phases + 승인 | M | 중 | P1 |
| G13 | 코딩 WebFetch allowlist | 세션 밖 HTTP | M | 고: SSRF | P1 |
| G14 | LSP / Notebook | 새 툴 | L | 고 | P2 |
| G15 | MCP를 코딩 루프에 | assembleToolPool 유사 | L | 고 | P2 |

## 6. 권장 구현 순서

1. 프롬프트 규약 + Read offset/limit
2. Edit
3. 승인 경고 + git/테스트 세분
4. RO 병렬
5. search/list 스키마를 Grep/Glob에 가깝게
6. TodoWrite
7. AskUser 또는 플랜 페이즈
8. 좁은 Skill / Explore 자식
9. ToolSearch는 툴 폭증 후
10. LSP·Notebook·MCP·Team은 샌드박스 경계가 설계된 뒤

원칙: CC의 **계약**을 이식하고 **실행기**(호스트 Bash, 절대경로, 자유 셸)는 이식하지 않는다.

## 7. 가져오면 안 되는 것

- `prompt.ts` 장문 복붙, Ink UI, bun `feature()` 게이트, `USER_TYPE==='ant'`
- Tungsten, REPL, SuggestBackgroundPR, Kairos/프로액티브 툴
- 자유 `command` 문자열, `dangerouslyDisableSandbox`, 호스트 worktree
- 챗 스택 혼입 (`web_search`, builtin research skills를 코딩 레지스트리에 등록)
- Team/coordinator/Workflow

## 8. 근거 파일 목록

CC: `src/tools.ts`, `src/Tool.ts`, `src/constants/tools.ts`, `src/constants/toolLimits.ts`, `src/services/tools/{toolOrchestration,toolExecution}.ts`, `src/utils/permissions/*`, `src/tools/{FileRead,FileEdit,FileWrite,Bash,Glob,Grep,TodoWrite,Agent,Skill,ToolSearch,AskUserQuestion,WebFetch,WebSearch,EnterPlanMode,LSP,NotebookEdit}Tool/`.

NEOS: `neos/coding/tools/{registry,executor}.py`, `loop/anthropic.py`, `domain/approvals.py`, `application/approval_service.py`, `runtime.py`, `sandbox/{paths,command,base}.py`, `tests/coding/tools/`, `neos/tools/tool_search/`, `neos/skills/`.
