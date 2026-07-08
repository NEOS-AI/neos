# NEOS Workflow

## 1. Abstract

NEOS Workflow는 사용자 질의를 `AgentState`로 정규화하고, LangGraph 기반 실행 그래프에서 분류, 스킬/도구 선택, 검색/분석/생성, 검증, 수리, 최종 응답 생성을 조합하는 멀티 에이전트 런타임이다. 채팅 스트림, 일반 질의 API, 외부 채널, 커스텀 워크플로우, 승인/자율성 정책, A2UI, HyperDeep/Recursive 실행이 모두 이 런타임 주변에 연결된다.

핵심 구현 위치:

- `neos/workflow/graph.py`
- `neos/workflow/state.py`
- `neos/workflow/routing/orchestrator_router.py`
- `neos/api/services/workflow_service.py`
- `neos/api/services/query_service.py`
- `neos/api/services/chat_stream_pipeline.py`

## 2. 실행 진입점

### 2.1 Query API

`QueryService`는 일반 질의 요청을 받아 캐시/템플릿/워크플로우 실행을 관리한다.

흐름:

1. `neos/api/services/query_service.py`
2. `WorkflowService.execute(...)`
3. `MultiAgentWorkflow.execute_workflow(...)`
4. LangGraph 실행
5. `response`, `metadata`, `quality_score`, `errors` 형태의 결과 반환

캐시는 자율성 수준을 포함한 키를 사용한다. Manual 모드 또는 mission 요청은 캐시를 우회한다.

### 2.2 Chat Streaming

`ChatStreamPipeline`은 채팅 메시지를 저장한 뒤, 필요하면 먼저 워크플로우를 실행하고 그 결과를 최종 LLM 응답의 시스템 컨텍스트에 주입한다.

흐름:

1. 사용자 메시지 저장
2. OpenResponses 스트림 시작
3. 대화 이력과 컨텍스트 로딩
4. 워크플로우 실행
5. 승인 interrupt가 있으면 `responseStatus=incomplete` 메타데이터 저장 후 중단
6. `SystemPromptBuilder`가 workflow result, artifact prompt, inline visualization prompt를 통합
7. LLM 스트리밍 전략 실행
8. content/tool/reasoning/usage 이벤트 저장 및 SSE 전송

관련 코드:

- `neos/api/services/chat_stream_pipeline.py`
- `neos/api/services/chat_system_prompt_builder.py`
- `neos/api/services/chat_stream_strategy.py`
- `neos/api/services/chat_chunk_dispatcher.py`

### 2.3 Channel Gateway

`NEOS_OPENCLAW.md`의 채널 개념은 `ChannelGateway`로 구현되어 있다. Telegram, Discord, Slack 같은 외부 채널에서 들어온 요청을 같은 워크플로우 엔진으로 보낼 수 있게 설계되어 있다.

관련 코드:

- `neos/channels/gateway.py`

주의: 현재 `ChannelGateway._run_workflow()`는 `result.get("final_response")`를 기대하지만, `MultiAgentWorkflow._create_workflow_result()`는 최종 응답을 `response` 키로 반환한다. 채널 응답이 비어 보일 수 있는 키 불일치 후보가 있다.

### 2.4 Custom Workflow Builder

커스텀 워크플로우는 DB에 저장된 노드/엣지를 LangGraph로 재구성해 실행한다.

주요 구성:

- `CustomWorkflowBuilder`: 노드, 엣지, MCP 서버를 저장
- `CustomWorkflowExecutor`: 저장된 workflow를 로드해 LangGraph로 컴파일
- `NodeExecutor`: `mcp_tool`, `processor`, `agent`, `skill` 노드 실행
- `WorkflowManager`: 목록/조회/상태 변경/삭제

관련 코드:

- `neos/workflow/builder/workflow_builder.py`
- `neos/workflow/builder/workflow_executor.py`
- `neos/workflow/builder/executors.py`
- `neos/workflow/builder/workflow_manager.py`
- `neos/database/workflow_models.py`

주의: 현재 executor는 conditional edge를 완전히 해석하지 않고 경고 후 일반 edge처럼 처리한다. 일부 builder 코드에는 `db_manager.get_session()` 사용 방식이 다른 코드와 어긋나는 지점도 있어 실제 DB 세션 동작 검증이 필요하다.

## 3. AgentState

`AgentState`는 전체 워크플로우의 공통 상태 컨테이너다. TypedDict로 정의되어 있으며 런타임 노드들이 이 상태를 부분 업데이트한다.

주요 범주:

- 사용자/세션: `query`, `user_id`, `session_id`, `language`, `channel_source`
- 분류: `query_classification`, `query_intent`, `complexity_score`
- 계획: `required_agents`, `selected_skills`, `selected_tools`
- 실행 결과: `search_results`, `analysis_results`, `generation_results`
- 통합/검증: `integrated_results`, `fact_check_results`, `quality_validation`
- 하네스: `harness_result`, `harness_repair_attempts`, `harness_blocked_response`
- 자율성/승인: `autonomy_level`, `pending_approvals`, `approval_decision`
- 고급 실행: `recursive_result`, `hyper_deep_result`, `mission_*`, `ui_frame`
- 메모리/컨텍스트: `memory_context`, `conversation_context`, `context_summary`
- 출력: `final_response`, `metrics`, `errors`

관련 코드:

- `neos/workflow/state.py`

## 4. 기본 LangGraph 파이프라인

`MultiAgentWorkflow`는 한 번 초기화하면 checkpointer 사용 여부에 따라 컴파일된 그래프를 캐시한다. 승인 interrupt가 필요한 경로는 checkpointer graph에서 `interrupt_before`로 처리된다.

기본 노드 흐름:

1. `refinement`
2. `query_refinement` 또는 `continuation_handler`
3. `conversation_context`
4. `query_classifier`
5. `skill_tool_selector`
6. 라우터 분기

일반 연구 파이프라인:

1. `hypothesis_generation`
2. `search_orchestrator`
3. `hypothesis_evaluation`
4. 필요 시 `replanner` 루프
5. `analysis_orchestrator`
6. `generation_orchestrator`
7. `result_integrator`
8. `fact_check`
9. `quality_validator`
10. 필요 시 재생성
11. `self_reflection`
12. `response_generator`
13. `research_harness`
14. 필요 시 repair 루프

특수 분기:

- `direct_response`: 단순 질의 또는 캐시 가능한 응답
- `task_scheduling`: 예약/cron 질의
- `mission_*`: 장기/다단계 mission 실행
- `recursive_orchestrator`: recursive research
- `hyper_deep_orchestrator`: HyperDeep research
- `execution_approval`: 승인 interrupt
- `ui_frame_generator`: A2UI 폼 생성

관련 코드:

- `neos/workflow/graph.py`
- `neos/workflow/enums.py`

## 5. 라우팅 정책

`OrchestratorRouter`는 분기 우선순위를 정한다.

우선순위:

1. A2UI가 활성화되어 있고 UI가 필요한 요청이면 `ui_frame`
2. task scheduling intent면 `task_scheduling`
3. pending approval이 있으면 `approval`
4. HyperDeep 조건이면 `hyper_deep`
5. Recursive 조건이면 `recursive`
6. 검색/분석/생성 agent가 필요하면 `orchestrators`
7. 그렇지 않으면 `direct_response`

HyperDeep/Recursive는 Manual 자율성에서는 차단된다. `AutonomyPolicy.allows_recursive_research()`가 Manual에서 false이기 때문이다.

관련 코드:

- `neos/workflow/routing/orchestrator_router.py`
- `neos/workflow/autonomy/policy.py`

## 6. 자율성 슬라이더와 승인

자율성 수준은 `AutonomyLevel`로 표현된다.

| Level | 이름 | 동작 |
| --- | --- | --- |
| 0 | Manual | 선택된 agent, skill, tool 전체 승인 필요. recursive/replan 차단 |
| 1 | Assisted | 설정된 민감 skill만 승인 필요 |
| 2 | Autonomous | 승인 없이 실행. recursive/replan 허용 |

정책 구현:

- `AutonomyPolicy.get_approval_required_actions(...)`
- `AutonomyPolicy.allows_recursive_research()`
- `AutonomyPolicy.allows_autonomous_replan()`

승인 흐름:

1. `skill_tool_selector`가 agent/skill/tool 후보를 선택
2. `AutonomyPolicy`가 approval 대상 계산
3. `pending_approvals`가 있으면 graph interrupt 발생
4. 클라이언트는 `/api/v1/approval/respond`로 승인/거절
5. 서버가 checkpointer 상태를 이어서 실행
6. `/api/v1/approval/stream/{session_id}`로 resume 결과 스트리밍

관련 코드:

- `neos/workflow/autonomy/policy.py`
- `neos/api/handlers/approval_handlers.py`

## 7. Query Classification

`QueryClassifier`는 키워드 규칙, URL 감지, optional LLM structured output을 조합한다.

주요 판단:

- YouTube URL은 `YOUTUBE_API_KEY`가 있으면 `youtube_search`, 없으면 `web_lookup`
- 일반 URL은 `web_lookup`
- 복잡도와 intent에 따라 `deep_research`, `recursive_research`, `hyper_deep_research`
- 시간 표현과 action keyword가 함께 있으면 `task_scheduling`
- A2UI는 task/generation intent와 UI keyword가 함께 있을 때 `needs_ui`

관련 코드:

- `neos/workflow/nodes/query_classifier.py`

## 8. Agent, Skill, MCP Tool

### 8.1 기본 에이전트군

`WorkflowConfig` 기준 주요 에이전트:

- Search: `knowledge_search`, `realtime_info_search`, `realtime_data_search`, `multi_query_search`, `deep_research`, `web_lookup`, `youtube_search`
- Analysis: `data_analysis`, `comparative_analysis`
- Generation: `image_generation`, `api_call`, `file_processing`, `task_creation`
- 특수: `hyper_deep_research`, recursive orchestrator, mission runtime

`AgentRegistry`에는 `hyper_deep_research`도 검색 에이전트로 등록되어 있으며, 설명상 30-60분 소요의 초심층 조사로 분류된다.

관련 코드:

- `neos/workflow/agent_registry.py`
- `neos/workflow/state.py`

### 8.2 Skill Manager

`SkillManager`는 builtin skill 등록, auto-discovery, lazy initialize, `execute_skill`을 담당한다.

기본 수동 등록 skill:

- `docx`
- `pdf`
- `research-assistant`
- `arxiv`
- `pubmed`
- `wikipedia`

파일 시스템 auto-discovery로 추가될 수 있는 skill:

- `semantic_scholar`
- `openalex`
- `google_scholar`
- `news_api`
- `reddit`
- `sec_edgar`
- `canvas`
- `cron`

관련 코드:

- `neos/skills/manager/skill_manager.py`
- `neos/skills/manager/skill_registry.py`
- `neos/skills/builtin/__init__.py`
- `neos/skills/manager/auto_discovery.py`

### 8.3 MCP Manager

기본 MCP tool:

- web search
- file processing
- database
- git
- link follower
- YouTube

관련 코드:

- `neos/tools/manager/mcp_manager.py`

### 8.4 서브에이전트 기술 특징

아래 표는 `AgentRegistry`에 등록된 기본 에이전트와 HDR/검색 내부에서 직접 사용하는 보조 에이전트를 현재 코드 기준으로 정리한 것이다.

| 에이전트 | 유형 | 기술적 특징 | 주요 의존성/제약 |
| --- | --- | --- | --- |
| `knowledge_search` | search | query embedding을 받아 과거 query/result 지식 베이스를 halfvec distance로 검색한다. | query embedding이 없으면 빈 결과를 반환한다. 현재 SQL은 `halfvec(3072)`를 사용한다. |
| `realtime_info_search` | search | Tavily advanced search 결과를 LLM으로 citation 포함 답변으로 재가공한다. thread pool timeout과 raw fallback이 있다. | `TAVILY_API_KEY` 필요. API timeout/rate limit 시 raw result fallback. |
| `realtime_data_search` | search | 통계/수치 데이터 질의를 Tavily로 검색하고 숫자/표/지표 중심으로 처리한다. | `TAVILY_API_KEY` 필요. |
| `multi_query_search` | search | 하나의 질의를 여러 관점의 query로 확장한 뒤 Tavily 검색 결과를 synthesis한다. | `TAVILY_API_KEY` 필요. HDR의 complex search에도 재사용된다. |
| `deep_research` | search | 15-25분 수준의 심층 조사 흐름. multi-step collection, gap analysis, synthesis를 수행한다. | `TAVILY_API_KEY` 의존도가 높다. |
| `hyper_deep_research` | search | 초심층 조사. skill/tool selection, 100+ source 목표, gap filling, validation, citation-aware report, iterative refinement를 포함한다. | 자세한 내용은 `NEOS_HDR.md` 참조. |
| `youtube_search` | search | YouTube Data API 검색, transcript 수집, LLM relevance scoring, playlist/video 비교, semantic duplicate 탐지를 수행한다. | metadata/search는 `YOUTUBE_API_KEY` 필요. transcript-only 경로는 일부 동작 가능. |
| `data_analysis` | analysis | 검색 결과에서 숫자, 날짜, 텍스트 패턴을 추출해 pandas/numpy 기반 통계와 LLM insight를 생성한다. | 입력 search result 품질에 민감하다. |
| `comparative_analysis` | analysis | source별 grouping, content Jaccard similarity, score 분포, metadata 차이를 비교한다. | 정량 비교는 result metadata와 score에 의존한다. |
| `web_lookup` | analysis | URL을 추출해 HTTP fetch/본문 추출/LLM 분석을 수행하는 lightweight 분석 에이전트다. | `analysis_agents.py`의 버전과 `search_agents/web_lookup.py` 버전이 함께 존재한다. |
| `image_generation` | generation | 이미지 요청을 감지하고 DALL-E 3 기반 prompt enhancement와 이미지 생성을 수행한다. | OpenAI image API 설정 필요. |
| `api_call` | generation | weather/currency/stock intent를 분석하고 외부 API를 호출한다. | OpenWeatherMap, ExchangeRate, Yahoo Finance, FinancialDatasets 설정에 따라 동작 범위가 달라진다. |
| `file_processing` | generation | 파일/문서/스프레드시트 처리 intent를 감지하고 파일 처리 결과 형태를 만든다. | 실제 파일 접근 context가 필요하다. |
| `task_creation` | generation | 요구사항을 task/workflow/todo/process 유형으로 분류하고 난이도별 task list를 생성한다. | 규칙 기반 task breakdown 중심이다. |
| `MultiHopSearchAgent` | internal search | relational query를 hop 단위 질문/검색/답변 chain으로 분해한다. HDR hybrid collector가 relational query에 사용한다. | Tavily 기반 검색. hop citation metadata를 생성할 수 있다. |
| `IterativeWebExplorerAgent` | internal search | initial search 후 링크 follow/품질 평가/depth 탐색을 반복한다. | Tavily, aiohttp, BeautifulSoup 사용. HDR에서 source 부족 시 보강 경로로 사용된다. |
| `CriticismFeedbackAgent` | internal review | 섹션 결과를 비판하고 missing perspective, suggested query를 만든다. | HDR deep analysis/validation 후 추가 조사 트리거에 사용된다. |

### 8.5 Builtin Skill 기술 특징

스킬은 `SkillManager`가 lazy initialize하고 `SkillResult`로 결과를 반환한다. 수동 등록되는 핵심 스킬과 auto-discovery 대상 스킬이 섞여 있으며, tool search가 켜져 있으면 스킬 schema도 registry 검색 대상이 될 수 있다.

| Skill | 주요 action | 기술적 특징 | 외부 의존성/주의점 |
| --- | --- | --- | --- |
| `docx` | `read`, `create`, `update` | python-docx 기반 Word 문서 읽기/생성/수정. | 파일 경로 권한과 문서 포맷에 의존. |
| `pdf` | `read`, `extract_text`, `create` | PyPDF2로 텍스트/metadata 추출, reportlab으로 PDF 생성. | PyPDF2/reportlab 설치 상태에 따라 기능 제한. |
| `research-assistant` | `analyze_source`, `summarize`, `extract_references` | 연구 출처 분석, 요약, 참고문헌 추출을 LLM 없이 규칙/텍스트 처리 중심으로 제공한다. | HDR skill integration에서 보조 분석 API로 호출 가능. |
| `arxiv` | `search`, `get_by_id` | LangChain `ArxivAPIWrapper`로 논문 검색과 metadata 추출. | `langchain-community`, `arxiv` 필요. |
| `pubmed` | `search`, `get_by_pmid` | LangChain `PubMedAPIWrapper`로 의학 문헌 검색. PMID URL 생성. | `langchain-community` 필요. |
| `wikipedia` | `search`, `get_page` | LangChain `WikipediaAPIWrapper`로 문서 검색/페이지 로딩. 언어 옵션을 받는다. | `wikipedia` 패키지 필요. |
| `semantic_scholar` | `search`, `get_citations`, `get_references`, `get_paper` | Semantic Scholar Graph API로 논문, citation/reference graph, open access PDF metadata를 조회한다. | API key는 선택. httpx 필요. |
| `openalex` | `search_works`, `search_authors`, `search_institutions`, `get_work` | OpenAlex 무료 API로 학술 메타데이터, 저자, 기관, DOI/OpenAlex ID 상세 조회. inverted index abstract 복원. | API key 불필요. polite pool email 설정 가능. |
| `google_scholar` | `search`, `cite` | SerpAPI를 통해 Google Scholar 결과와 citation format 조회. | `SERPAPI_API_KEY` 필요. |
| `news_api` | `search`, `top_headlines` | NewsAPI.org의 실시간 뉴스 검색/헤드라인 조회. | `NEWS_API_KEY` 필요. |
| `reddit` | `search`, `subreddit_search` | OAuth2 또는 old.reddit JSON fallback으로 Reddit 게시물/서브레딧 검색. | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` 있으면 인증 rate limit 개선. |
| `sec_edgar` | `full_text_search`, `company_filings` | SEC EDGAR EFTS/company submissions API로 10-K, 10-Q, 8-K 등 공시 검색. | API key 불필요. User-Agent 설정 권장. |
| `github_search` | `search_repos`, `search_code`, `search_issues` | GitHub REST API v3로 레포지토리, 코드, 이슈 검색. | token 없이도 동작하나 rate limit이 낮다. |
| `canvas` | schema 기반 render | 연구 결과를 동적 canvas payload로 렌더링하는 OpenClaw/A2UI 계열 스킬. | frontend renderer와 payload schema 정합성이 중요하다. |
| `cron` | schedule creation | 자연어/직접 cron 표현식을 파싱, 검증하고 DB에 예약 작업을 저장한다. 규칙 기반 파서 후 LLM fallback을 사용한다. | `croniter` 검증. channel type은 `api`, `telegram`, `discord`, `slack` 계열. |

## 9. Advanced Tool Search

Advanced Tool Search는 모든 tool schema를 매 요청 프롬프트에 넣는 방식 대신, 핵심 tool과 `search_tools`만 먼저 노출하고 필요 시 registry에서 관련 tool을 검색해 활성화한다.

주요 구성:

- `ToolRegistryStore`: tool metadata, schema, embedding, category, tags, source type 저장
- `HybridSearchEngine`: vector search + BM25 + RRF 결합
- `SearchToolsHandler`: LLM이 호출하는 `search_tools` 처리
- `sync.py`: skill/MCP/artifact tool을 registry에 동기화

스트리밍 경로:

1. `ToolSearchStreamStrategy`
2. registry core tools + `search_tools`
3. LLM이 `search_tools` 호출
4. 검색된 tool schema를 active tools에 추가
5. 다음 tool round에서 실제 tool 호출

관련 코드:

- `neos/tools/tool_search/tool_registry_store.py`
- `neos/tools/tool_search/hybrid_search_engine.py`
- `neos/tools/tool_search/search_tools_handler.py`
- `neos/api/services/chat_stream_strategy.py`
- `neos/services/chat_llm_service.py`

주의:

- 현재 `ToolSearchStreamStrategy`는 `SystemPromptBuilder`가 넘긴 `tools` 인자를 무시하고 registry core tools를 사용한다. artifact/inline visualization tool이 tool-search 경로에서 보이려면 core 등록 또는 별도 병합이 필요하다.
- 현재 검색 코드는 `embedding::halfvec(3072)` 경로를 사용하고, config 기본 embedding도 Gemini 3072 차원이다. 반면 `db/migrations/019_add_tool_registry.sql`에는 `vector(1536)`가 남아 있어 기존 DB와 차원 불일치가 날 수 있다.

## 10. Search Orchestration

`SearchOrchestrator`는 전략 패턴으로 검색을 선택한다.

전략:

- `StandardSearchStrategy`: 일반 agent/MCP 검색, fallback chain, synthesis, dedupe, cache
- `MultiHopSearchStrategy`: 관계형/다단계 질문에 multi-hop search
- `IterativeSearchStrategy`: 깊은 탐색, 비교, comprehensive research에 iterative web explorer

보강 기능:

- 대화 컨텍스트 기반 query enhancement
- cost-aware downgrade
- cache hybrid path
- fallback chain
- result synthesizer
- optional knowledge graph population

관련 코드:

- `neos/workflow/orchestrators/search_orchestrator.py`
- `neos/workflow/search_strategies.py`

## 11. Web Lookup Agent

`WebLookUpAgent`는 URL을 직접 처리하는 검색 에이전트다.

동작:

- URL 추출 및 검증
- `aiohttp` 기반 HTML fetch
- optional Playwright dynamic rendering
- title, description, main content 추출
- script/style/nav/header/footer/aside 제거
- LLM으로 URL별 분석과 종합 답변 생성

제약:

- HTML 중심이다.
- 인증이 필요한 페이지는 처리하지 않는다.
- 큰 본문은 잘라서 분석한다.
- PDF/영상/파일은 별도 도구가 필요하다.

관련 코드:

- `neos/agents/search_agents/web_lookup.py`

## 12. YouTube Agent and Tool

YouTube 기능은 MCP tool과 검색 에이전트로 나뉜다.

`YouTubeMCPTool` operation:

- `search_videos`
- `get_transcript`
- `get_video_info`
- `analyze_video`
- `get_playlist_info`
- `get_playlist_videos`
- `compare_videos`

`YouTubeSearchAgent` 기능:

- 비디오 검색
- transcript 수집
- LLM relevance scoring
- summary 생성
- 비디오 비교
- playlist 분석
- 중복/유사/semantic duplicate 탐지
- 학습 순서, 난이도, 인기, 길이, topic cluster, prerequisite chain 기준 재정렬

주의:

- search/metadata는 YouTube Data API key가 필요하다.
- transcript 추출은 API key 없이도 가능한 경우가 있다.
- 현재 `YouTubeSearchAgent._generate_summaries()`에는 `SearchResult` 생성자에 현재 dataclass와 맞지 않는 keyword를 넘기는 코드가 있어, 해당 경로 실행 시 런타임 오류 후보가 있다.

관련 코드:

- `neos/tools/mcp/youtube_tool.py`
- `neos/agents/search_agents/youtube_search.py`

## 13. API Call Agent

`ApiCallAgent`는 자연어에서 API 호출 intent와 파라미터를 추출한다.

현재 구현:

- weather: OpenWeatherMap
- currency: ExchangeRate API 또는 free fallback
- stock: Yahoo Finance 기본, FinancialDatasets 선택
- financial statements: Yahoo 또는 FinancialDatasets

키워드상 news/translation도 감지하지만 실제 구현은 weather/currency/stock 중심이다.

관련 코드:

- `neos/agents/generation_agents/api_call.py`

## 14. Context Optimization and Contextual Retrieval

### 14.1 Context Optimization

컨텍스트 최적화는 LLM 호출 전 메시지/도구 결과가 너무 커지는 문제를 줄인다.

기능:

- token counting
- tool result summary
- 오래된 메시지 compression
- semantic dedupe
- workflow별 token budget

현재 config 기본값은 큰 컨텍스트를 전제로 한다.

- `context_optimization.max_context_tokens`: 800000
- `tool_result_max_length`: 4000
- `message_history_max_tokens`: 50000
- `workflow_default_budget`: 100000

주의: 기본 non-tool streaming 경로는 context optimizer를 거치지만, tool-search streaming 경로는 별도 loop를 사용하므로 최적화 적용 범위를 확인해야 한다.

관련 코드:

- `neos/services/context_optimizer.py`
- `neos/services/chat_llm_service.py`

### 14.2 Contextual Retrieval

문서 ingestion 시 chunk마다 LLM이 contextual snippet을 생성하고, `context_snippet + chunk_text`를 embedding/BM25 검색 대상으로 사용한다.

동작:

1. 문서 chunk 생성
2. contextual retrieval 활성화 시 chunk별 context snippet 생성
3. contextual text embedding
4. `document_chunk_contextual` 검색 전략 사용
5. vector + BM25 + RRF 결합
6. reranker는 `contextual_text`를 우선 사용

관련 코드:

- `neos/services/document_processing/contextual_retrieval.py`
- `neos/services/document_processor.py`
- `neos/services/search/similarity_search_service.py`
- `neos/services/search/reranker.py`

주의: contextual search SQL도 `halfvec(3072)`를 사용한다. 오래된 1536 차원 DB 스키마와 함께 쓰면 마이그레이션 점검이 필요하다.

## 15. Artifact and Inline Visualization

Artifact와 inline visualization은 채팅 LLM tool 호출에서 처리된다.

Artifact:

- artifact prompt와 tool schema를 system prompt에 추가
- tool result metadata를 assistant message에 저장
- OpenResponses extension event로 artifact metadata 전송

Inline visualization:

- `renderDiagram`
- `renderChart`
- Pydantic validation 후 `neos:inline_viz` 이벤트 전송
- assistant message metadata의 `inline_visualizations`에 저장
- 현재 렌더링은 assistant message 뒤쪽 블록 형태에 가깝고, 텍스트 중간 interleaving은 제한적이다.

관련 코드:

- `neos/api/services/chat_system_prompt_builder.py`
- `neos/api/services/chat_chunk_dispatcher.py`
- `neos/tools/inline_vis_tools.py`
- `neos/tools/inline_vis_tool_handler.py`

## 16. OpenResponses Streaming

NEOS는 item 기반 response stream 모델을 사용한다.

주요 item/event:

- message content delta
- reasoning delta
- function_call item
- output_item added/done
- usage
- error
- extension events: `neos:workflow_progress`, `neos:artifact_meta`, `neos:inline_viz`, `neos:ui_frame`, `neos:approval_request`

워크플로우 이벤트는 `WorkflowStreamCallback`과 `stream_adapter.py`를 통해 OpenResponses 호환 이벤트로 변환된다.

관련 코드:

- `neos/api/adapters/stream_adapter.py`
- `neos/api/handlers/workflow_stream_handlers.py`
- `neos/api/models/open_responses.py`

### 16.1 프론트엔드 통신 프로토콜

현재 프론트엔드는 Next.js route handler를 얇은 프록시로 사용하고, 백엔드 FastAPI는 SSE를 반환한다.

채팅 요청 경로:

1. React hook: `web/hooks/use-chat-stream.ts`
2. FE route: `POST /api/chat`
3. Backend route: `POST /api/v1/chat/conversations/{conversation_id}/messages/stream`
4. Response: `Content-Type: text/event-stream`
5. Stream 종료: `data: [DONE]`

`/api/chat` 요청 body:

```json
{
  "id": "frontend-chat-uuid",
  "message": {
    "id": "message-id",
    "role": "user",
    "parts": [{ "type": "text", "text": "..." }],
    "metadata": {}
  },
  "selectedChatModel": "model-id",
  "selectedVisibilityType": "private",
  "autonomy_level": 1
}
```

Next.js route는 backend conversation을 생성/조회한 뒤 다음 body로 백엔드 스트림 API를 호출한다.

```json
{
  "content": "...",
  "role": "user",
  "metadata": {
    "fe_chat_id": "frontend-chat-uuid",
    "model": "model-id",
    "visibility": "private",
    "autonomy_level": 1
  }
}
```

응답 헤더:

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `Connection: keep-alive`
- `X-Accel-Buffering: no`
- `X-OpenResponses-Version: 2024-01-01`
- `X-Conversation-Id: {conversation_id}`

SSE wire format:

```text
event: response.output_text.delta
data: {"type":"response.output_text.delta","delta":"..."}

data: [DONE]
```

프론트 처리 방식:

- `useChatStream.processStream()`이 `ReadableStream`을 직접 읽는다.
- `event:` line은 건너뛰고 `data:` JSON만 파싱한다.
- `detectEventFormat()`이 legacy/OpenResponses를 판별한다.
- legacy event는 `web/lib/adapters/stream-adapter.ts`에서 OpenResponses event로 변환한다.
- OpenResponses event는 `web/lib/open-responses-types.ts`의 type guard로 분기한다.
- assistant message의 `parts[0].text`와 `metadata`를 점진적으로 갱신한다.

Legacy event 변환:

| Legacy event | Frontend 변환 |
| --- | --- |
| `start` | `response.in_progress`, `response.output_item.added`, `response.content_part.added` |
| `content` | `response.output_text.delta` |
| `complete` | `response.output_text.done`, `response.content_part.done`, `response.output_item.done`, `response.completed` |
| `error` | `response.failed` |
| `workflow_node_start` | `response.output_item.added` with `function_call` |
| `workflow_node_complete` | `response.output_item.done` |
| `workflow_progress` | `neos:workflow_progress` |
| `artifact_meta/delta/finish` | `neos:artifact_*` |
| `ui_frame` | `neos:ui_frame` |

OpenResponses core event 처리:

| Event | UI 반영 |
| --- | --- |
| `response.in_progress` | assistant message 생성, `responseStatus=in_progress` |
| `response.output_text.delta` | text part에 delta append |
| `response.output_item.added` with `function_call` | `metadata.function_calls`, `metadata.workflow_agents` 추가 |
| `response.output_item.done` | function call/workflow agent 완료 표시 |
| `response.completed` | `responseStatus=completed`, usage 전달 |
| `response.failed` | `responseStatus=failed`, hook error 처리 |

NEOS extension event 처리:

| Event | Payload 핵심 | UI 반영 |
| --- | --- | --- |
| `neos:artifact_meta` | `artifact_id`, `artifact_title`, `artifact_kind` | `metadata.artifact` 저장 |
| `neos:artifact_delta` | `content` | artifact data delta로 전달 |
| `neos:artifact_finish` | `artifact_id` | artifact 완료 신호 |
| `neos:workflow_progress` | `progress_percent`, `message` | workflow progress callback |
| `neos:harness` | `event`, `data` | `metadata.harness` 상태 갱신 |
| `neos:approval_request` | `session_id`, `pending_approvals` | `responseStatus=incomplete`, approval card 표시 |
| `neos:ui_frame` | `ui_frame` | `metadata.ui_frame` 저장, UIFrameRenderer 표시 |
| `neos:inline_viz` | `viz_id`, `viz_type`, `data` | `metadata.inline_visualizations` append |
| `neos:inline_viz_error` | `tool_name`, `error` | non-fatal console warning |

주의: frontend legacy adapter는 approval/harness/inline visualization을 legacy 이름에서 변환하지 않는다. 이 이벤트들은 backend가 `neos:*` OpenResponses extension 형태로 보내는 것을 전제로 한다.

### 16.2 Approval 프로토콜

Manual/Assisted 모드에서 승인 필요 action이 있으면 workflow는 checkpointer interrupt를 발생시키고 chat stream은 `neos:approval_request`를 내보낸다.

프론트 흐름:

1. `neos:approval_request` 수신
2. assistant message metadata에 `approval_requests`, `approval_session_id` 저장
3. approval card 렌더링
4. 사용자가 approve/reject
5. `POST /api/approval/respond`
6. Next.js가 `POST /api/v1/approval/respond`로 프록시
7. `GET /api/approval/stream/{sessionId}` 구독
8. Next.js가 `GET /api/v1/approval/stream/{session_id}`로 프록시

승인 request payload의 핵심 필드:

```json
{
  "request_id": "...",
  "skill_name": "...",
  "params": {},
  "timeout_seconds": 300
}
```

### 16.3 A2UI 프로토콜

A2UI는 backend가 `neos:ui_frame` 이벤트로 UI frame schema를 내려주고, frontend가 해당 schema를 form으로 렌더링한 뒤 submit 결과를 다시 SSE로 받는 구조다.

UIFrame payload:

```json
{
  "frame_id": "...",
  "intent": "...",
  "components": [
    {
      "id": "field",
      "type": "text_field",
      "label": "Field",
      "required": true
    }
  ],
  "session_id": "...",
  "conversation_id": "...",
  "timeout_seconds": 300
}
```

Submit 경로:

1. `UIFrameForm`
2. `POST /api/ui-submit`
3. Backend `POST /api/v1/ui/submit`
4. Backend workflow 재실행
5. SSE response body에서 최종 텍스트 추출

지원 component type:

- `text_field`
- `date_picker`
- `time_picker`
- `select`
- `multi_select`
- `slider`
- `checkbox`
- `file_upload`
- `card`
- `chart`
- `table`
- `progress`
- `divider`
- `button`
- `form`

## 17. Research Harness

Research Harness는 연구 결과의 품질을 검증하고, 조건에 따라 repair loop를 실행하거나 차단한다.

역할:

- contract 생성
- report/sources 검증
- gate/advisory 모드 판단
- failed checks 기록
- repair 가능 여부 판단
- 하네스 결과를 workflow metadata에 반영

HyperDeep/direct deep research는 gate 성격의 검증을 받도록 설계되어 있다.

관련 코드:

- `neos/workflow/harness/*`
- `neos/workflow/processors/research_harness_processor.py`

## 18. A2UI and Task Scheduling

A2UI는 사용자의 요청을 바로 텍스트 응답으로 끝내기보다 UI form/frame이 필요한 경우 `UIFrameGenerator`가 구조화된 UIFrame을 생성한다.

흐름:

1. query classifier가 `needs_ui` 판단
2. `ui_frame_generator` 노드 실행
3. LLM tool call로 UIFrame 생성
4. DB에 `UIFrameSession` 저장
5. `neos:ui_frame` SSE 전송
6. 사용자가 `/api/v1/ui/submit`으로 제출
7. 제출 데이터를 새 workflow context로 실행

Task scheduling은 cron skill 및 scheduling intent를 통해 예약 작업을 만든다.

관련 코드:

- `neos/workflow/ui_frame_generator.py`
- `neos/api/handlers/ui_submit_handlers.py`
- `neos/skills/builtin/cron`

## 19. OpenClaw 관점에서의 현재 구현

`NEOS_OPENCLAW.md`의 주요 개념은 현재 코드에 다음처럼 대응된다.

| OpenClaw 개념 | NEOS 구현 |
| --- | --- |
| ChannelGateway | `neos/channels/gateway.py` |
| LangGraph runtime | `neos/workflow/graph.py` |
| BaseSkill | `neos/skills/base.py` 및 builtin/auto-discovery |
| Execution approval | `AutonomyPolicy`, approval handlers |
| Provider registry | `neos/utils/llm_factory.py`, settings/schema |
| Memory/context engine | conversation context, memory loader, context optimizer |
| A2UI | `UIFrameGenerator`, UI submit handlers |
| Cron skill | builtin cron skill, task scheduling route |

## 20. 운영상 주의점

### 20.1 HTTP resource access matrix

| Resource | Read | Mutate |
| --- | --- | --- |
| Private conversation | owner | owner |
| Public conversation | authenticated user | owner |
| Message | conversation owner; public list through conversation route only | conversation owner |
| Document/chunk/KG/search | owner | owner |
| Approval/resume stream | owner | owner |
| UI frame | owner | owner, one submission |
| Query/history/SSE | authenticated user/self | authenticated user/self |
| Health/trending/related | public | none |
| Metrics/info/cache/stats | admin | admin |

Current WebSocket endpoints are not covered by this HTTP plan and must remain disabled at the deployment perimeter until the authenticated WebSocket plan is implemented.

- Tool Search의 embedding 차원은 현재 코드상 3072이고 일부 migration 문서는 1536이다.
- Tool Search 경로는 builder가 만든 tool list를 무시하므로 artifact/inline visualization tool 노출 여부를 별도로 확인해야 한다.
- ChannelGateway의 최종 응답 키는 workflow result와 불일치 후보가 있다.
- Custom Workflow conditional edge는 아직 완전 구현이 아니다.
- YouTube summary 생성 경로에 `SearchResult` 인자 불일치 후보가 있다.
- Context optimizer 적용 범위는 LLM 호출 전략별로 다르다.
- Manual autonomy에서는 recursive/hyper-deep research가 라우팅되지 않는다.
- 승인 interrupt를 쓰려면 checkpointer graph로 실행해야 한다.

## 21. 코드 맵

| 영역 | 주요 파일 |
| --- | --- |
| 상태/그래프 | `neos/workflow/state.py`, `neos/workflow/graph.py` |
| 라우팅 | `neos/workflow/routing/orchestrator_router.py` |
| 자율성/승인 | `neos/workflow/autonomy/policy.py`, `neos/api/handlers/approval_handlers.py` |
| Query API | `neos/api/services/query_service.py`, `neos/api/services/workflow_service.py` |
| Chat streaming | `neos/api/services/chat_stream_pipeline.py`, `neos/api/adapters/stream_adapter.py` |
| Tool Search | `neos/tools/tool_search/*` |
| Skill system | `neos/skills/manager/*`, `neos/skills/builtin/*` |
| MCP tools | `neos/tools/manager/mcp_manager.py`, `neos/tools/mcp/*` |
| Search orchestration | `neos/workflow/orchestrators/search_orchestrator.py`, `neos/workflow/search_strategies.py` |
| Contextual retrieval | `neos/services/document_processing/contextual_retrieval.py`, `neos/services/search/*` |
| Workflow Builder | `neos/workflow/builder/*`, `neos/database/workflow_models.py` |
| A2UI | `neos/workflow/ui_frame_generator.py`, `neos/api/handlers/ui_submit_handlers.py` |
| Harness | `neos/workflow/harness/*` |
| HDR integration | `neos/workflow/hyper_deep/executor.py`, `neos/agents/search_agents/hyper_deep_research/*` |
