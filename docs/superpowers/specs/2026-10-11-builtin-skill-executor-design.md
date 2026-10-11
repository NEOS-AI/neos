# 빌트인 스킬 공통 실행 노드 (P1)

- 날짜: 2026-10-11
- 상태: 설계 승인(섹션 1~4, 2026-10-11) · 스펙 검토 대기
- 범위: 스킬 체계 재정비의 **P1**. P2(`skills/` 플러그인 스킬의 동적 선택 + 코딩 샌드박스 실행)는 별도 spec 이다(§7)
- 목표(사용자 결정 2026-10-11): 빌트인 스킬은 **셀렉터가 고르고 공통 실행 노드가 실행한다**. 코딩 스킬은 지금대로 둔다

## 1. 배경 — 진단 (코드 대조 2026-10-11, `ead2efb5`)

스킬 체계는 서로 연결되지 않은 세 시스템이다.

| | 위치 | 상태 |
|---|---|---|
| `SkillManager`(실행형, `BaseSkill.execute`) | `neos/skills/manager/` | 기동 때 `builtin/` 자동 발견 15개(`neos/main.py` 의 `register_builtin_skills(use_auto_discovery=True)`) |
| `MarkdownSkillCatalog`(점진 공개) | `neos/skills/markdown_catalog.py` | 코딩 9개 · k-skill · security-audit · univer · fsi. `research_skill_roots()` 는 호출자가 없다 |
| Tool Search 레지스트리 | `neos/tools/tool_search/` | `register_from_skill_registry()` 는 있으나 `sync_tool_registry` 를 부르는 곳이 없다 |

빌트인 스킬의 실제 흐름:

- 메인 그래프는 **매 질의** `QUERY_CLS → SKILL_TOOL_SELECTOR` 에서 LLM 을 한 번 부른다. 결과 `selected_skills` 는 승인
  정책(`workflow/autonomy/policy.py`)과 `learn/research_lessons.py` 만 읽는다. **실행하는 노드가 없다.**
- 실행은 HyperDeepResearch 의 `skills_integration.py` 한 곳 — `arxiv`·`pubmed`·`wikipedia` 를 if 문으로 하드코딩한다.
  나머지 12개는 REST `/skills/{name}/execute` 와 워크플로우 빌더 `skill` 노드에서만 돈다.
- 등록이 두 갈래다 — 기동은 자동 발견 15개, HDR 폴백은 수동 목록 `get_builtin_skills()` 6개.
- 13개 스킬이 `get_input_schema()` 를 오버라이드하지 않아 기본 `{query, action, max_results}` 를 물려받는다.
  docx·pdf(`file_path`)·research-assistant(`content`)는 스키마와 실제 입력이 다르다.
- 셀렉터 프롬프트는 ko/en/ja/zh **네 사본**이다. 폴백 휴리스틱은 없는 이름(`bigquery_skill`, `pdf_skill`)을 고른다.
- `neos/skills/README.md` 는 없어진 `bigquery` 를 설명하고 "7개" 라고 적는다.

빌트인 15개의 입력 모양:

| 그룹 | 스킬 | P1 에서 |
|---|---|---|
| 검색형 (10) | arxiv, pubmed, wikipedia, openalex, semantic-scholar, google-scholar, sec-edgar, github-search, reddit, news-api | 자동 실행 (1단계) |
| 입력물형 | research-assistant (`content`) | 자동 실행 (2단계, 1단계 결과를 입력으로) |
| 입력물형 | docx, pdf (`file_path`) | 후보에서 뺀다 — §1.1 |
| 부작용형 | cron (스케줄 생성), canvas (렌더링) | 후보에서 뺀다 — 각자 `TASK_SCHEDULING`·`UI_FRAME` 경로가 있다 |

### 1.1 docx·pdf 를 빼는 이유

- 웹 채팅의 첨부는 메인 그래프에 오지 않는다 — `chat_stream_pipeline.py` 가 `execute_workflow` 에 넘기는 것은
  `query`·`chat_history`·`autonomy_level`·`preferences` 뿐이다. `channel_attachments` 는 채널 경로에서만 채워진다.
- 첨부는 이미 N8(`neos/services/attachment_blocks.py`)이 최종 LLM 호출에 직접 붙인다 — PDF 는 네이티브 블록, DOCX 는
  `parse_word`. 그래프에서 다시 해석하면 같은 파일을 두 번 읽는다.

## 2. 그래프 위치와 흐름

```
SKILL_TOOL_SELECTOR ──▶ _route_after_skill_tool_selector
                          ├─ skip_orchestrators ─▶ SKILL_EXECUTOR ─▶ DIRECT_RESPONSE        (search_results 를 읽도록 변경)
                          ├─ use_orchestrators  ─▶ SKILL_EXECUTOR ─▶ HYPOTHESIS_GENERATION
                          ├─ needs_approval ─▶ EXECUTION_APPROVAL ─approved─▶ SKILL_EXECUTOR ─▶ HYPOTHESIS_GENERATION
                          │                                       └rejected─▶ RESP_GENERATOR (실행 안 함)
                          └─ mission · hyper_deep · recursive · deep_analysis · task_scheduling · ui_frame
                               ─▶ 기존대로. 스킬을 실행하지 않는다
```

- **노드는 하나, 진입 엣지는 셋.** 실행 노드를 경로마다 복제하지 않는다.
- **출구는 다시 계산한다.** 조건부 엣지 함수는 상태에 쓸 수 없으므로 라우터의 결정을 상태에 남길 수 없다. 출구 엣지
  `_route_after_skill_executor` 는:
  - `approval_decision == "approved"` → `HYPOTHESIS_GENERATION`
  - 그 밖에는 `orchestrator_router.base_route(state)` — `SKIP_ORCHESTRATORS` → `DIRECT_RESPONSE`, 그 외 →
    `HYPOTHESIS_GENERATION`
  - 근거: `base_route` 는 상태만 읽는 순수 함수이고 `search_results` 를 읽지 않으므로 실행 전후 답이 같다.
    **이 가정은 테스트로 고정한다**(§6).
- **결과가 버려지는 경로에서는 돌지 않는다.** `search_results` 를 읽는 것은 오케스트레이터 체인과 `RESP_GENERATOR`
  뿐이다. mission·HDR·ROMA·DA·`DIRECT_RESPONSE` 는 각자 `final_response` 를 만들고 응답 생성기는
  `_preserve_existing_response` 로 그대로 통과시킨다. 그래서 `DIRECT_RESPONSE` 만 `search_results` 를 읽도록 바꾸고,
  나머지 경로에는 실행 노드를 두지 않는다.
- **턴당 한 번.** `REGENERATE`·`continue_search` 루프는 `HYPOTHESIS_GENERATION` 으로 돌아가 실행 노드를 다시 지나지
  않는다. 방어적으로 상태 키 `skill_execution_done` 이 참이면 노드는 즉시 빈 갱신을 낸다.
- **승인.** `pending_approvals` 에 걸린 스킬은 승인 전에 실행되지 않는다 — 승인 대기 경로는 실행 노드를 지나지 않고
  `EXECUTION_APPROVAL` 로 가며, `approved` 일 때만 실행 노드에 들어온다.
- **라우터는 바꾸지 않는다.** `base_route` 에 `selected_skills` 를 더하지 않는다. `skip_orchestrators` 에서도 스킬이
  돌고 `DIRECT_RESPONSE` 가 결과를 읽으므로, "arxiv 최신 논문 3개" 같은 질의는 오케스트레이터 체인 없이 답한다.

### 2.1 실행 노드 내부

1. 1단계 — `skill_calls` 중 research-assistant 를 뺀 것을 `asyncio.gather` 로 병렬 실행. 스킬마다
   `initialize`+`execute` 를 타임아웃으로 감싼다.
2. 2단계 — research-assistant 가 선택됐고 1단계 결과가 하나 이상이면, 1단계 `SearchResult` 들의 본문을 묶어
   `content` 로 넣고 실행한다.
3. 각 결과를 그 스킬의 `to_search_results()` 로 변환해 `search_results` 에 더한다(`operator.add` 리듀서).
4. `skill_execution_done = True`, 스킬별 `execution_steps` 항목을 쓴다.

노드 계약(`@node_contract`):

- reads: `skill_calls`, `skill_execution_done`, `original_query`, `refined_query`, `execution_steps`
- writes: `search_results`, `skill_execution_done`, `execution_steps`
- requires: 없음(빈 `skill_calls` 는 빈 갱신)

## 3. 셀렉터 출력 계약과 스킬 스키마

### 3.1 후보 집합

`SKILL.md` frontmatter 에 `auto_execute: true` 를 새로 둔다 — 검색형 10개와 research-assistant 에만. 셀렉터는 이 11개만
후보로 본다. 나머지는 레지스트리·REST·워크플로우 빌더에 그대로 남는다. `metadata_parser` 가 이 키를 읽어 `SkillInfo`
에 싣는다(기본 `false`). 승인 정책은 이름만 비교하므로 영향이 없다.

### 3.2 출력 형식

```json
{
  "skill_calls": [
    {"name": "arxiv", "params": {"query": "diffusion transformer", "max_results": 5}, "reason": "..."},
    {"name": "research-assistant", "params": {"action": "summarize"}, "reason": "..."}
  ],
  "selected_tools": ["..."],
  "reasoning": "...",
  "priority_order": []
}
```

- `SkillToolSelection` 에 `skill_calls: list[SkillCall]` 를 더한다. `SkillCall = (name, params, reason)`.
- **`selected_skills` 는 `skill_calls` 의 이름에서 파생한다** — 정본은 하나다. 승인 정책·HDR·research_lessons 는
  바꾸지 않는다. 두 필드를 따로 채우면 승인은 A 를 보고 실행은 B 를 하는 우회가 생길 수 있다.
- 상태에 `skill_calls: Optional[List[Dict[str, Any]]]` 를 더한다. 셀렉터 노드의 writes 에 추가한다.

### 3.3 검증

1. 이름이 후보(§3.1) 밖이면 버린다.
2. `params` 를 그 스킬의 `get_input_schema()` 로 `jsonschema` 검증한다(의존성 이미 있음). 실패하면 버리지 않고
   `{"query": refined_query or original_query}` 로 **대체**한다 — 이름을 맞게 고른 선택은 "질의 그대로 검색" 이
   "아무것도 안 함" 보다 낫다.
3. 개수 상한 `max_skills_per_turn`(기본 3)을 넘으면 앞에서부터 자른다.
4. research-assistant 의 `content` 는 LLM 이 쓰지 않는다. 스키마에 없고 실행 노드가 채운다.

### 3.4 스키마

검색형 10개에 `get_input_schema()` 오버라이드를 더한다 — 각 스킬이 `execute` 에서 실제로 읽는 키(`year_from`,
`form_type`, `subreddit`, `language`, `sort` …)와 허용 `action` 값을 그대로 드러낸다. research-assistant 는
`action` 만.

### 3.5 결과 변환

`BaseSkill.to_search_results(result: SkillResult) -> list[SearchResult]` 를 추가한다. 기본 구현은 빈 목록 + 경고.
결과 모양(`papers`·`works`·`filings`·`posts`·`repositories` …)을 아는 것은 스킬 자신이므로 각 스킬이 구현한다.
`SearchResult.source` 는 스킬 이름, `metadata` 에 `{"skill": name, "via": "skill_executor"}` 를 싣는다.

### 3.6 셀렉터 정리

- ko/en/ja/zh 프롬프트 네 사본을 **템플릿 하나 + 응답 언어 지시**로 합친다.
- 낡은 폴백 휴리스틱(`bigquery_skill`·`pdf_skill`)을 지운다. 파싱·호출 실패 시 `skill_calls=[]` 를 낸다.
  `selected_tools` 폴백(`web_search` 등)은 이번 범위에서 손대지 않는다.

## 4. 오류 처리 · 플래그 · 관측

- **실패는 턴을 죽이지 않는다.** 초기화 실패·`execute` 예외·타임아웃·`success=False` 는 로그 + `execution_steps`
  항목을 남기고 건너뛴다. 1단계가 전부 실패하면 2단계도 건너뛴다. `asyncio.CancelledError` 는 삼키지 않는다.
- **상한.** 스킬당 결과 수 `max_results_per_skill`, `SearchResult.content` 길이 `max_content_chars`.
- **신뢰 경계.** 스킬 결과는 검색 에이전트 결과와 같은 외부 데이터다. 응답 생성기의 출처 표기·인용 경로를 그대로 탄다.
  새 경계를 만들지 않는다.
- **플래그.** `WorkflowConfig` 아래 `skill_execution` 블록:

  ```yaml
  workflow:
    skill_execution:
      enabled: false          # 스키마 기본. neos.development.yaml 에서 true
      max_skills_per_turn: 3
      timeout_seconds: 15     # search_orchestration_timeout(40) 보다 짧게
      max_results_per_skill: 5
      max_content_chars: 4000
  ```

  꺼져 있으면 그래프 배선·라우팅·`DIRECT_RESPONSE` 동작이 **지금과 같다**. 셀렉터는 `skill_calls` 를 내지만 아무도
  실행하지 않는다. `docs/CONFIGURATION.md` 와 `docs/CONFIG_INVENTORY.md` 에 키를 적는다.
- **관측.** 노드 단위 `node_started`/`node_completed` SSE 는 기존 콜백이 낸다. 스킬별로는 `execution_steps` 에
  `{skill, status, duration_ms, result_count, reason_code}`. 새 SSE 이벤트 종류는 만들지 않는다 — FE 계약 픽스처
  (`chat_stream_event_types.json`)를 건드리지 않는다.

## 5. 함께 고치는 것 / 범위 밖

**함께 고친다**

- HDR `skills_integration.py` 의 `_search_with_arxiv/pubmed/wikipedia` 안 변환 코드를 `to_search_results()` 호출로
  바꾼다 — 같은 변환 두 사본을 남기지 않는다.
- HDR 의 등록 폴백 `register_builtin_skills()`(수동 6개)을 자동 발견으로 바꾼다. 다른 호출자가 없으면
  `get_builtin_skills()` 수동 목록과 `register_builtin_skills(use_auto_discovery=False)` 분기를 지운다.
- `neos/skills/README.md` 를 현재 상태로 고친다.

**범위 밖**

- P2 — `skills/` 플러그인 스킬의 색인·동적 선택·샌드박스 실행
- 첨부 배관과 docx·pdf 자동 실행
- HDR 의 흐름(if 문 하드코딩·키워드 규칙 `ensure_required_skills`) 자체
- 설계 그래프(`graph_design_enabled`)에서 실행 노드를 어디 둘지의 품질 — 계약을 달면 카탈로그에 들어가고, 설계자가
  배치를 정한다. 동적 그래프에서는 출구 재계산 엣지가 없고 설계자가 그린 엣지를 따른다
- Tool Search 레지스트리 연결(`sync_tool_registry` 호출자 없음)

## 6. 테스트

- **셀렉터 파싱**(`tests/test_skill_based_tool_selector.py`) — `skill_calls` 정상, 후보 밖 이름 버림, 스키마 위반 →
  대체값, 상한 자르기, `selected_skills` 파생, 파싱 실패 → 빈 선택, 언어별 응답 지시가 한 템플릿에서 나옴.
- **실행 노드 단위** — 1단계 병렬, 스킬 하나 타임아웃이 나머지를 막지 않음, `success=False`·예외 건너뜀, 2단계
  research-assistant 가 1단계 결과를 `content` 로 받음, 1단계 전부 실패 시 2단계 생략, `skill_execution_done` 가드.
- **그래프**(`tests/test_workflow_graph.py`, `tests/workflow/test_static_graph_contract.py`) — 진입 셋, 출구 재계산,
  **승인 전에 실행되지 않음**, 거절 시 실행 안 함, 루프에서 재실행 안 함, `base_route` 가 `search_results` 를 읽지
  않는다는 가정의 고정.
- **계약** — `DIRECT_RESPONSE` reads 에 `search_results`, 새 노드 계약(`tests/workflow/test_node_contracts.py`),
  설계 카탈로그 픽스처(`tests/workflow/test_subagent_node_catalog.py` 의 "정적 31개") 의도적 갱신.
- **스킬별 `to_search_results`** — 저장된 응답 픽스처로. 네트워크 없음.
- **스킬별 스키마** — 각 스킬의 `get_input_schema()` 가 `execute` 가 읽는 키를 빠짐없이 덮는지(AST 로 `params.get`
  키를 뽑아 대조).
- **플래그 off 회귀** — 노드 집합·엣지·`DIRECT_RESPONSE` 결과가 지금과 같다.

## 7. 다음 — P2 로 넘기는 것

- `skills/` 최상위 179개 + 팩 넷. 178개에 `When to Use`/`Boundaries` 절이 없고, 109개 디렉터리에 스크립트가 있다.
  설명 평균 395자 — 전부 나열하면 약 18K 토큰이라 나열이 아니라 검색이 필요하다
- 실행은 코딩 샌드박스까지 허용한다(사용자 결정 2026-10-11) — FSI·Univer 처럼 서브에이전트 경로
- 이름 충돌 — `skills/docx`·`skills/pdf` 가 빌트인 `docx`·`pdf` 와 같다. `MarkdownSkillCatalog._put()` 은 먼저 온 쪽을
  남기고 나머지를 조용히 버린다
- P1 셀렉터의 `skill_calls` 계약이 P2 의 플러그인 후보 확장의 바탕이 된다
