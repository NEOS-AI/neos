# NEOS Hyper Deep Research

## 1. Abstract

HDR은 단일 검색 에이전트라기보다 초심층 연구 파이프라인이다. 주제 분석, 연구 계획, 대규모 query expansion, Tavily/Hybrid/MultiQuery/Skill 기반 수집, 반복 분석, 갭 보강, 교차 검증, 사실 검증, 편향 분석, citation-aware report generation, 반복 섹션 개선을 하나의 긴 실행으로 묶는다.

핵심 구현 위치:

- `neos/agents/search_agents/hyper_deep_research/agent.py`
- `neos/agents/search_agents/hyper_deep_research/config.py`
- `neos/agents/search_agents/hyper_deep_research/data_collection.py`
- `neos/agents/search_agents/hyper_deep_research/hybrid_data_collector.py`
- `neos/agents/search_agents/hyper_deep_research/analysis.py`
- `neos/agents/search_agents/hyper_deep_research/report_generator.py`
- `neos/agents/search_agents/hyper_deep_research/iterative_refiner.py`
- `neos/workflow/hyper_deep/executor.py`

## 2. 실행 경로

### 2.1 독립 에이전트 실행

`HyperDeepResearchAgent.execute(query, context)`를 직접 호출할 수 있다. 직접 실행은 입력 검증, Tavily API 가용성 확인, 언어 감지, 연구 프로세스 실행, `SearchResult` 포맷 반환을 수행한다.

반환 형태는 `SearchAgent.format_output()` 기반의 legacy agent result다.

주요 metadata:

- `processing_type`: `hyper_deep_research`
- `report_id`
- `total_sections`
- `total_sources`
- `total_queries`
- `multi_query_searches`
- `unique_domains`
- `usage.output_tokens`

### 2.2 워크플로우 통합 실행

일반 NEOS Workflow에서는 `hyper_deep_orchestrator` 노드가 HDR을 실행한다.

조건:

- `HYPER_DEEP_AGENT_ENABLED=true`
- autonomy가 Manual이 아님
- intent가 `hyper_deep_research`이거나, 복잡도가 `HYPER_DEEP_COMPLEXITY_THRESHOLD` 이상이고 deep/complex intent인 경우

흐름:

1. `OrchestratorRouter`가 `hyper_deep` route 반환
2. `MultiAgentWorkflow._hyper_deep_orchestrator_node`
3. `RecursiveOrchestrator`
4. `HyperDeepExecutor`
5. `HyperDeepResearchAgent.execute(...)`
6. task-level harness gate

관련 코드:

- `neos/workflow/routing/orchestrator_router.py`
- `neos/workflow/graph.py`
- `neos/workflow/hyper_deep/executor.py`

### 2.3 Recursive/Ray 통합

HDR은 recursive orchestrator의 leaf executor로도 동작한다. `RAY_ENABLED`가 true이면 distributed recursive orchestrator 경로를 사용할 수 있고, 아니면 일반 `RecursiveOrchestrator`에 `HyperDeepExecutor`를 주입한다.

`HyperDeepExecutor`는 agent singleton을 재사용하지만, 각 task 실행 전 내부 상태를 reset한다.

초기화/리셋 대상:

- `current_report_id`
- `sections_data`
- `all_collected_sources`
- `research_metadata`

### 2.4 Ray 기반 분산 컴퓨팅 엔진

HDR의 Ray 경로는 긴 초심층 연구를 sibling subtask 단위로 병렬화하기 위한 실행 엔진이다. 기본값은 비활성화이며, 다음 조건이 모두 충족될 때만 사용된다.

- `hyper_deep_agent.enabled=true`
- `ray.enabled=true` 또는 legacy `RAY_ENABLED=true`
- workflow router가 `hyper_deep` 경로를 선택

초기화 흐름:

1. `neos/main.py` lifespan startup
2. `ray.init(address=settings.RAY_ADDRESS, object_store_memory=settings.RAY_OBJECT_STORE_MEMORY)`
3. `create_all_named_actors(max_tasks_per_level=HYPER_DEEP_MAX_TASKS_PER_LEVEL)`
4. `CostAccumulatorActor` named actor 생성
5. `MultiAgentWorkflow`가 `DistributedRecursiveOrchestrator` 생성
6. 서버 startup 중 `orchestrator.warmup()`으로 worker actor cold start 제거
7. shutdown 시 `ray.shutdown()`

워크플로우 그래프 선택:

```python
if settings.HYPER_DEEP_AGENT_ENABLED:
    if settings.RAY_ENABLED:
        self.hyper_deep_orchestrator = DistributedRecursiveOrchestrator(...)
    else:
        self.hyper_deep_orchestrator = RecursiveOrchestrator(
            executor=HyperDeepExecutor(),
            ...
        )
```

Ray 설정:

| YAML | Legacy env prefix | 기본값 | 의미 |
| --- | --- | --- | --- |
| `ray.enabled` | `RAY_ENABLED` | false | Ray 분산 실행 활성화 |
| `ray.address` | `RAY_ADDRESS` | `auto` | Ray cluster 주소 |
| `ray.num_cpus` | `RAY_NUM_CPUS` | null | Ray CPU 제한 |
| `ray.object_store_memory` | `RAY_OBJECT_STORE_MEMORY` | 2000000000 | object store memory |
| `hyper_deep_agent.max_tasks_per_level` | `HYPER_DEEP_MAX_TASKS_PER_LEVEL` | 3 | worker pool size와 동일하게 사용 |
| `hyper_deep_agent.max_depth` | `HYPER_DEEP_MAX_DEPTH` | 1 | recursive decomposition depth |
| `hyper_deep_agent.budget_cap` | `HYPER_DEEP_BUDGET_CAP` | 5.0 | recursive 비용 한도 |

구성 요소:

| 구성 요소 | 역할 | 기술적 특징 |
| --- | --- | --- |
| `DistributedRecursiveOrchestrator` | Ray-aware recursive orchestrator | `RecursiveOrchestrator`를 상속하고 atomic task/sibling level 실행을 Ray로 대체한다. |
| `RayExecutorPool` | HDR worker pool | `HyperDeepWorkerActor`를 pool size만큼 만들고 round-robin으로 task를 제출한다. |
| `HyperDeepWorkerActor` | 실제 HDR leaf 실행자 | actor당 독립 프로세스에서 `HyperDeepResearchAgent` 1개를 보유한다. `max_concurrency=1`로 상태 충돌을 막는다. |
| `RayAtomizerActor` | 원자성 판단 | stateless named actor. `RecursiveAtomizer`를 감싸고 `atomic/decomposable` 문자열을 반환한다. |
| `RayPlannerActor` | subtask 분해/재계획 | stateless named actor. `RecursivePlanner`를 감싼다. |
| `RayAggregatorActor` | 결과 통합 | stateless named actor. child result를 parent answer로 통합한다. |
| `RayVerifierActor` | 결과 검증 | stateless named actor. 통합 결과의 `satisfied`, `score`, `gaps`를 반환한다. |
| `dag_utils.build_execution_levels()` | sibling DAG level 계산 | `metadata.depends_on`을 읽어 병렬 실행 가능한 subtask index group을 만든다. |

실행 알고리즘:

1. root task의 budget, circular reference, depth를 확인한다.
2. named atomizer가 task를 `ATOMIC` 또는 `DECOMPOSABLE`로 판별한다.
3. `ATOMIC`이면 `RayExecutorPool.submit()`으로 worker actor에 보낸다.
4. `DECOMPOSABLE`이면 named planner가 subtasks를 만든다.
5. `metadata.depends_on`을 기반으로 DAG level을 만든다.
6. 같은 level에 task가 1개면 재귀 처리한다.
7. 같은 level에 독립 task가 여러 개면 `asyncio.gather`로 Ray object ref들을 동시에 기다린다.
8. 각 worker result는 task status/result/cost에 반영한다.
9. named aggregator가 child result를 통합한다.
10. named verifier가 만족도를 평가한다.
11. 검증 실패 시 최대 1회 replan을 수행하고, replan task도 DAG level별로 병렬 실행한다.

Ray worker context 직렬화 규칙:

- Ray에 넘기는 context는 pickle 가능한 값만 포함한다.
- `_stream_callback`은 coroutine/closure라서 제외된다.
- `_cost_accumulator`는 프로세스 경계에서 공유할 수 없어 제외된다.
- `prior_results`는 최대 2개를 요약 문자열로 바꿔 `prior_results_summary`로 전달한다.
- worker 내부 agent context에는 `session_id`, `user_id`, `prior_research_context` 정도만 전달된다.

이 때문에 Ray 경로에서는 non-Ray `HyperDeepExecutor`보다 HDR phase SSE가 제한될 수 있다. `HyperDeepWorkerActor` 주석에도 `_stream_callback`이 Ray pickle 불가라 worker 내부에서 사용 불가하며, StreamBridgeActor 보완이 향후 과제로 언급되어 있다.

Worker actor 격리:

- `@ray.remote(num_cpus=0.5, num_gpus=0, max_concurrency=1)`
- actor별 `HyperDeepResearchAgent` 인스턴스 보유
- task 실행 전 `self._agent.reset()` 호출
- agent state 충돌을 막기 위해 actor당 동시 요청은 1개
- Ray 프로세스 분리로 Python GIL 영향을 줄인다.

메트릭:

| Metric | 의미 |
| --- | --- |
| `neos_ray_executor_pool_utilization` | HDR Ray pool 활용률 |
| `neos_ray_task_duration_seconds` | Ray task 실행 시간 |
| `neos_ray_parallel_speedup_ratio` | 병렬 실행 속도 향상 추정값 |
| `neos_ray_actor_restarts_total` | Ray actor restart count |
| `neos_ray_level_tasks_parallel` | 같은 level에서 병렬 실행한 task 수 |

운영상 주의:

- Ray 초기화 실패 시 warning을 남기고 sequential fallback으로 돌아간다.
- named actor가 없으면 로컬 atomizer/planner/aggregator/verifier 인스턴스를 유지한다.
- Ray worker의 `cost` 반환은 현재 0.0으로 고정되어 있으며, HDR agent 비용 반환 연동은 아직 구현되어 있지 않다.
- worker result는 markdown 문자열 중심이므로 OpenResponses item 단위 결과가 worker 경계에서 유지되지는 않는다.
- `ray.address=auto`는 로컬 Ray가 없으면 초기화 실패할 수 있으므로 운영 환경에서 Ray cluster 또는 로컬 Ray start 상태를 확인해야 한다.

## 3. 설정

`ResearchConfig` 기본값은 HDR의 조사 강도를 정의한다.

주요 기본값:

| 설정 | 기본값 | 의미 |
| --- | --- | --- |
| `multi_query_expansion` | 20 | 쿼리 확장 개수 |
| `parallel_search_batches` | 5 | Tavily 배치 검색 수 |
| `enable_hybrid_collection` | true | 관계형 질문에 hybrid collector 사용 |
| `max_hybrid_queries` | 10 | hybrid 분류 대상 쿼리 상한 |
| `results_per_query` | 10 | 검색 쿼리당 결과 수 |
| `min_total_sources` | 100 | 최소 목표 소스 수 |
| `target_total_sources` | 200 | 목표 소스 수 |
| `analysis_iterations` | 3 | 반복 분석 기본 라운드 |
| `cross_validation_rounds` | 2 | 교차 검증 라운드 |
| `critical_thinking_passes` | 2 | 비판 분석 pass |
| `max_sections` | 15 | 리포트 섹션 상한 |
| `quality_threshold` | 0.9 | 전체 품질 목표 |
| `enable_iterative_refinement` | true | 반복 섹션 개선 사용 |
| `max_iterations_per_section` | 3 | 섹션별 개선 반복 상한 |
| `section_quality_threshold` | 0.8 | 섹션 품질 목표 |
| `max_concurrent_refinements` | 4 | 동시 섹션 개선 상한 |

워크플로우 설정:

- `hyper_deep_agent.enabled`
- `hyper_deep_agent.max_depth`
- `hyper_deep_agent.max_tasks_per_level`
- `hyper_deep_agent.complexity_threshold`
- `hyper_deep_agent.budget_cap`
- `hyper_deep_agent.task_level_harness_enabled`

관련 코드:

- `neos/agents/search_agents/hyper_deep_research/config.py`
- `neos/config/schema.py`

## 4. 전체 단계

현재 `HyperDeepResearchAgent._run_research_process()`는 다음 순서로 동작한다.

| 단계 | 이름 | 핵심 동작 |
| --- | --- | --- |
| 0 | Skill and Tool Selection | `SkillBasedToolSelector`로 skill/tool 후보 선택 |
| 1 | Topic Analysis | 주제를 다차원 분석하고 research questions 추출 |
| 1.5/1.6 | Domain Detection & Skill Initialization | arxiv/pubmed/wikipedia 등 필수 skill 보강 및 초기화 |
| 2 | Research Planning | 방법론과 검색 전략 수립 |
| 3 | Data Collection | query expansion, hybrid search, multi-query, Tavily, skill 수집 |
| 3.5 | Iterative Web Exploration | 초기 소스가 목표의 50% 미만이면 추가 web exploration |
| 4 | Deep Analysis | 여러 라운드의 반복 분석 및 synthesis |
| 4.5 | Recursive Deep Dive | 중요 insight를 재귀적으로 더 파고듦 |
| 5 | Gap Analysis | 지식 갭 식별, gap query 생성, 추가 수집 |
| 6 | Cross-Validation | semantic clustering 후 source triangulation |
| 6.5 | Fact Verification | claim 추출, contradiction 분석 |
| 7 | Critical Analysis | 한계, 반대 관점, 다중 관점 비판 분석 |
| 7.5 | Bias Detection | 편향과 관점 다양성 분석 |
| 8 | Report Synthesis | citation-aware final report 및 반복 refinement |

각 phase start/complete는 `ResearchEventLogger`가 기록한다. 스트리밍 callback이 있으면 HDR phase event가 workflow stream으로 브릿지된다.

## 5. Phase 0: Skill and Tool Selection

HDR은 자체적으로 `SkillBasedToolSelector`를 호출한다.

selection context:

- `intent`: `hyper_deep_research`
- `query_type`: `research`
- `complexity`: `high`
- `requires_analysis`: true
- `requires_data_sources`: true

선택 결과는 `research_metadata`에 기록된다.

- `selected_skills`
- `selected_tools`
- `selection_reasoning`

관련 코드:

- `neos/agents/search_agents/hyper_deep_research/agent.py`
- `neos/agents/skill_based_tool_selector.py`

## 6. Phase 1-2: Topic Analysis and Planning

`TopicAnalyzer`는 LLM을 호출해 주제를 분석하고 research questions를 추출한다.

`ResearchPlanner`는 topic analysis를 바탕으로 research plan과 search strategies를 생성한다. planning은 별도 timeout 설정인 `LLM_TIMEOUT_RESEARCH_PLANNING`을 사용한다.

보강:

- `ComplexityAssessor`가 topic complexity를 평가한다.
- 평가 결과에 따라 `analysis_iterations`가 조정된다.

관련 코드:

- `neos/agents/search_agents/hyper_deep_research/analysis.py`
- `neos/agents/search_agents/hyper_deep_research/utils/complexity_assessor.py`

## 7. Domain Detection and Skill Integration

`SkillsIntegrator`는 선택된 skill 목록을 domain에 맞게 보강한다.

자동 보강 규칙:

- Science/Engineering/AI keyword가 있으면 `arxiv` 추가
- Medical/Biomedical/Health keyword가 있으면 `pubmed` 추가
- 모든 topic에 `wikipedia` 추가

skill 기반 수집:

- ArXiv: query 최대 5개, query당 paper 5개
- PubMed: query 최대 5개, query당 paper 5개
- Wikipedia: query 최대 3개, query당 article 2개

각 결과는 공통 source dict로 정규화된다.

관련 코드:

- `neos/agents/search_agents/hyper_deep_research/skills_integration.py`
- `neos/skills/manager/skill_manager.py`

## 8. Phase 3: Data Collection

HDR의 데이터 수집은 여러 경로를 합친다.

### 8.1 Query Expansion

`DataCollector.generate_query_variations()`가 LLM으로 다양한 관점의 검색 쿼리를 만든다. 생성 결과가 부족하면 fallback query를 추가한다.

기본 상한은 `multi_query_expansion=20`이다.

### 8.2 Hybrid Collection

관계형 질문은 `QuestionTypeClassifier`로 분류한 뒤 `HybridDataCollector`가 적절한 전략을 선택한다.

전략:

- `RELATIONAL`: `MultiHopSearchAgent`
- `COMPREHENSIVE`: `IterativeWebExplorerAgent`
- `STANDARD`: Tavily

초기 Phase 3에서는 먼저 최대 10개 query를 분류하고, relational query만 hybrid collector로 보낸다. 나머지는 standard query로 처리한다.

주의: `HybridDataCollector._collect_with_tavily()`는 현재 `DataCollector.search_parallel()`을 호출하지만 `DataCollector`에는 해당 메서드가 없다. Phase 3 메인 경로는 standard query를 별도 `execute_parallel_searches()`로 처리하므로 대부분의 표준 검색은 정상 경로를 타지만, hybrid collector가 standard 전략으로 직접 진입하면 오류 후보가 있다.

### 8.3 Complex Multi-Query

`ComplexSearchExecutor`는 상위 5개 query를 `MultiQuerySearchAgent`로 실행하고 synthesis 결과를 source처럼 추가한다.

### 8.4 Tavily Batch Search

`DataCollector.execute_parallel_searches()`는 query를 `parallel_search_batches`개 batch로 나누고, 내부적으로 `asyncio.gather`와 semaphore/rate limit을 사용해 Tavily advanced search를 수행한다.

Tavily request 옵션:

- `search_depth="advanced"`
- `max_results=results_per_query`
- `include_answer=True`
- `include_raw_content=True`

### 8.5 Deduplication and Quality Scoring

수집 결과는 `DataProcessor.deduplicate_sources()`로 중복 제거 후 `SourceQualityScorer.rank_sources()`로 품질 점수를 매긴다.

추적 metadata:

- `total_queries_executed`
- `total_sources_collected`
- `unique_domains`
- `hybrid_collection_stats`
- `multi_query_searches`

관련 코드:

- `neos/agents/search_agents/hyper_deep_research/data_collection.py`
- `neos/agents/search_agents/hyper_deep_research/hybrid_data_collector.py`
- `neos/agents/search_agents/hyper_deep_research/utils/source_quality_scorer.py`
- `neos/agents/search_agents/hyper_deep_research/utils/data_processor.py`

## 9. Phase 3.5: Iterative Web Exploration

초기 수집 소스 수가 target의 50% 미만이면 `IterativeWebExplorerAgent`를 추가 실행한다.

보수적 설정:

- `max_depth`: 3
- `max_pages`: 15
- `quality_threshold`: 0.70

결과는 source dict로 변환해 저장하고, 별도 `iterative_exploration` 섹션을 repository에 기록한다.

## 10. Phase 4-5: Deep Analysis and Gap Filling

### 10.1 Deep Analysis

`DeepAnalyzer.perform_deep_analysis()`는 `analysis_iterations`만큼 반복 분석한다.

각 라운드:

1. 이전 라운드 insight를 포함
2. LLM으로 새 분석 생성
3. metadata의 `analysis_iterations_completed` 증가

이후 모든 round를 synthesis한다.

### 10.2 Criticism Feedback

`CriticismProcessor`는 `CriticismFeedbackAgent`로 deep analysis와 validation section에 대한 피드백을 생성한다.

피드백이 추가 조사를 요구하면 suggested queries와 missing perspectives로 검색을 더 수행할 수 있다.

### 10.3 Recursive Deep Dive

`DeepDiveAnalyzer`는 deep analysis synthesis에서 중요한 insight를 찾아 추가 검색과 분석을 수행한다.

### 10.4 Gap Analysis

`GapAnalyzer`는 최대 15개의 knowledge gap을 식별하고, 상위 10개 gap에 대해 gap query를 생성한다. 관계형 gap query는 hybrid collector를 사용하고, 그 외는 standard search를 사용한다.

관련 코드:

- `neos/agents/search_agents/hyper_deep_research/analysis.py`
- `neos/agents/search_agents/hyper_deep_research/report_generator.py`
- `neos/agents/search_agents/hyper_deep_research/utils/deep_dive_analyzer.py`

## 11. Phase 6-7.5: Validation, Fact Check, Bias Analysis

### 11.1 Semantic Clustering

`SemanticClusterer`는 수집된 source를 의미적으로 cluster한다. cross-validation prompt에는 cluster 정보 일부가 포함된다.

### 11.2 Cross-Validation

`ValidationAnalyzer.cross_validate_sources()`는 최대 30개 source sample과 cluster 요약을 사용해 triangulation report를 생성한다.

### 11.3 Fact Verification

`FactChecker`는 source에서 claim을 추출하고 contradiction을 분석한다. 결과는 `fact_verification` 섹션으로 저장된다.

### 11.4 Critical Analysis

`ValidationAnalyzer.perform_critical_analysis()`는 deep analysis와 validation 결과를 기반으로 한계, 반론, 관점 다양성을 분석한다.

### 11.5 Bias Detection

`BiasDetector`는 source들의 편향과 관점 다양성을 분석하고 diversity score를 기록한다.

관련 코드:

- `neos/agents/search_agents/hyper_deep_research/utils/semantic_clusterer.py`
- `neos/agents/search_agents/hyper_deep_research/utils/fact_checker.py`
- `neos/agents/search_agents/hyper_deep_research/utils/bias_detector.py`

## 12. Citation System

HDR report는 `CitationTracker`를 중심으로 citation-aware 방식으로 생성된다.

기능:

- source 등록 및 번호 부여
- DOI/arXiv/PMID 추출
- source list prompt 생성
- `[n]` citation parsing
- invalid citation validation
- reference list 생성
- citation statistics 계산
- APA/Chicago/MLA/Vancouver/numbered style 지원

리포트 생성 흐름:

1. collected sources를 citation tracker에 등록
2. report structure 생성
3. 각 section 생성 prompt에 source list 포함
4. section 생성 후 citation validation
5. section text에서 citation context 파싱
6. final report에 references와 citation stats 포함

관련 코드:

- `neos/agents/search_agents/hyper_deep_research/utils/citation_tracker.py`
- `neos/agents/search_agents/hyper_deep_research/utils/academic_identifier_extractor.py`
- `neos/agents/search_agents/hyper_deep_research/utils/citation_recommender.py`
- `neos/agents/search_agents/hyper_deep_research/report_generator.py`

## 13. Phase 8: Report Synthesis

`ReportGenerator`는 최종 report structure를 계획하고, 각 section을 citation-aware prompt로 생성한다.

기본 report 구성:

- 제목
- 연구 통계
- 섹션들
- 참고문헌
- most cited sources
- report id

반복 개선이 활성화되어 있으면 표준 `synthesize_final_report()` 대신 `_synthesize_with_iterative_refinement()` 경로를 사용한다.

## 14. Iterative Report Refinement

`IterativeReportRefiner`는 Ralph Loop-inspired 반복 개선 구조다.

전체 흐름:

1. 초기 section 생성
2. 각 section을 품질 기준까지 반복 개선
3. section summary로 abstract 생성
4. refined section과 abstract alignment 검사
5. 필요 시 abstract refinement
6. abstract와 section의 consistency alignment
7. final abstract + aligned sections + references 조립

품질 지표:

- citation coverage
- citation quality
- coherence
- completeness
- clarity

기본 가중치:

- citation coverage: 0.30
- citation quality: 0.25
- coherence: 0.20
- completeness: 0.15
- clarity: 0.10

보강 기능:

- adaptive threshold
- learning feedback
- smart content chunking
- conditional refinement skip
- custom metric weights
- metrics collection/export
- invalid citation auto-fix

주의: 현재 `SectionIterator.refine_section_iteratively()` 안에서 지역 변수 `quality_threshold`를 계산하지만 loop 내부에서는 `self.quality_threshold`를 참조한다. `SectionIterator.__init__()`는 `default_quality_threshold`만 설정하므로, 해당 분기가 실행되면 attribute error가 날 수 있는 코드 후보가 있다.

관련 코드:

- `neos/agents/search_agents/hyper_deep_research/iterative_refiner.py`
- `neos/agents/search_agents/hyper_deep_research/content_chunker.py`
- `neos/agents/search_agents/hyper_deep_research/metrics_collector.py`
- `neos/agents/search_agents/hyper_deep_research/learning_feedback.py`

## 15. Repository and Persistence

HDR은 repository pattern으로 DB 접근을 캡슐화한다.

런타임에서 테이블이 없으면 생성을 시도한다.

주요 테이블:

- `hyper_research_reports`
- `hyper_research_sections`
- `hyper_research_data_collection`
- `hyper_research_criticism_feedback`
- `hyper_research_events`

주요 저장 항목:

- report 상태
- phase별 section
- data collection query/results
- criticism feedback
- metadata

보고서 상태:

- 초기: `pending`
- 진행: `in_progress`
- HDR 자체 완료: `candidate_ready`
- 검증 완료: `completed`
- 실패: `failed`

`_finalize_report()`는 기본적으로 `candidate_ready`를 기록한다. `completed`는 검증된 경로에서만 사용하도록 의도되어 있다.

관련 코드:

- `neos/agents/search_agents/hyper_deep_research/repository/hyper_research_repository.py`
- `db/hyper_deep_research.sql`

## 16. Event Streaming and OpenResponses

`ResearchEventLogger`는 HDR 내부 이벤트를 기록한다.

이벤트 종류:

- phase start/progress/complete
- query execution
- sources collected
- LLM call start/complete
- analysis iteration
- gap identified
- criticism feedback
- progress/status message

현재 OpenResponses 브릿지:

- `hyper_deep_phase_start`는 `FunctionCallItem` in-progress로 변환
- `hyper_deep_phase_complete`는 해당 function call completed로 변환
- `hyper_deep_usage`는 response usage에 반영 가능

제한:

- 모든 HDR 세부 이벤트가 OpenResponses item으로 표준화된 것은 아니다.
- query execution, source collection, LLM call detail은 주로 DB/CLI/event logger 중심이다.
- `HyperDeepExecutor.execute()`의 최종 반환은 여전히 markdown 문자열 중심이다.

관련 코드:

- `neos/agents/search_agents/hyper_deep_research/utils/event_logger.py`
- `neos/api/handlers/workflow_stream_handlers.py`
- `neos/api/adapters/stream_adapter.py`

### 16.1 HDR과 프론트엔드 스트림의 관계

HDR이 일반 workflow 안에서 non-Ray 경로로 실행될 때는 `HyperDeepExecutor`가 context의 `_stream_callback`을 agent에 전달한다. `ResearchEventLogger`는 phase start/complete를 `WorkflowStreamCallback`으로 브릿지하고, backend `stream_adapter.py`는 이를 OpenResponses function call item처럼 변환한다.

HDR phase event mapping:

| HDR 내부 이벤트 | Workflow event | OpenResponses 변환 | 프론트 표시 |
| --- | --- | --- | --- |
| `PHASE_STARTED` | `hyper_deep_phase_start` | `response.output_item.added` with `function_call` | `metadata.function_calls`, `workflow_agents`에 in-progress |
| `PHASE_COMPLETED` | `hyper_deep_phase_complete` | `response.output_item.done` | 해당 function call completed |
| usage update | `hyper_deep_usage` | `response.usage` 누적 | `response.completed` usage에 반영 가능 |

프론트엔드 처리:

- `use-chat-stream.ts`는 `response.output_item.added/done`의 `FunctionCallItem`을 workflow tool/agent 진행 상태처럼 표시한다.
- HDR phase name은 function call `arguments`에 `{"phase": "..."}` 형태로 들어간다.
- 최종 markdown report는 일반 assistant text delta/complete 경로로 표시된다.

Ray 경로의 차이:

- Ray worker에는 `_stream_callback`이 전달되지 않는다.
- 따라서 worker 내부 HDR phase event가 실시간 SSE로 직접 노출되지 않을 수 있다.
- 상위 orchestrator의 workflow node event, 최종 aggregated result, harness event는 계속 workflow stream 경로를 탄다.
- phase-level UX가 반드시 필요하면 non-Ray 경로를 쓰거나 Ray StreamBridge 계층을 추가해야 한다.

## 17. Harness Integration

HDR은 두 층의 검증과 연결된다.

### 17.1 Task-level Harness

`HyperDeepExecutor`는 `HYPER_DEEP_TASK_LEVEL_HARNESS_ENABLED`가 true이면 leaf task 결과를 harness로 검증한다.

동작:

1. `build_harness_contract(...)`
2. `HarnessRunner.arun(...)`
3. task metadata에 harness 결과 저장
4. gate mode에서 `fail` 또는 `needs_repair`면 task 실패 처리

### 17.2 Metadata Checks

반복 개선 결과는 `hyper_deep_metadata_checks()`로 하네스 후보 check가 된다.

현재 check:

- `average_section_quality >= 0.80`

관련 코드:

- `neos/workflow/hyper_deep/executor.py`
- `neos/workflow/harness/adapters/hyper_deep.py`

## 18. 다른 NEOS 기능과의 관계

### 18.1 Contextual Retrieval

HDR 자체 수집은 Tavily/skills/hybrid search 중심이지만, NEOS 전체 문서 검색 품질은 contextual retrieval과 연결된다. 문서 ingestion에서 생성된 contextual chunk는 일반 workflow 검색/검색 전략에서 더 좋은 근거를 제공할 수 있다.

관련 코드:

- `neos/services/document_processing/contextual_retrieval.py`
- `neos/services/search/similarity_search_service.py`

### 18.2 Web Lookup

URL 중심 질문은 workflow route에서 `web_lookup`으로 갈 수 있다. HDR 내부에서도 추가 수집이 필요할 때 일반 web/search agent 계열과 결합될 수 있다.

### 18.3 YouTube

YouTube intent는 기본 workflow에서 `youtube_search`로 처리된다. HDR 주제 분석이나 skill/tool selection이 YouTube 관련 tool을 선택할 수 있지만, HDR 본체의 Phase 3 수집은 현재 Tavily, MultiQuery, Hybrid, selected skills 중심이다.

### 18.4 Autonomy

Manual mode에서는 recursive/HDR research route가 차단된다. HDR은 긴 실행과 광범위한 도구 사용이 전제이므로 Assisted 또는 Autonomous에서 현실적으로 동작한다.

## 19. 현재 코드 기준 강점

- 단계가 명확하게 분리되어 있어 추적과 장애 격리가 쉽다.
- 대량 수집, gap filling, criticism feedback, fact/bias 검증까지 포함한다.
- CitationTracker를 통해 인용 번호와 참고문헌을 구조적으로 관리한다.
- Recursive orchestrator leaf로 사용할 수 있어 복잡한 task decomposition과 결합된다.
- report candidate와 verified completed 상태를 분리해 하네스 검증을 끼울 수 있다.
- phase start/complete가 workflow stream으로 브릿지된다.
- domain-specific skill 보강으로 arxiv/pubmed/wikipedia 활용도가 높다.

## 20. 현재 코드 기준 주의점

- Tavily API가 없으면 `HyperDeepResearchAgent.execute()`는 본격 research를 진행하지 않는다.
- `HybridDataCollector`의 standard Tavily fallback 경로에는 존재하지 않는 `DataCollector.search_parallel()` 호출이 있다.
- `SectionIterator`의 `self.quality_threshold` 참조는 attribute error 후보이다.
- `HyperDeepExecutor._extract_sources()`는 `SearchResult.metadata.sources`를 기대하지만 HDR agent가 생성하는 metadata에는 현재 source 목록이 들어가지 않는다. task-level harness가 source 없이 report만 검증할 수 있다.
- `sections_data`는 초기화되지만 실제 section 생성 시 별도로 append되지 않아 summary의 section count가 기대보다 낮을 수 있다.
- OpenResponses 통합은 phase 단위 중심이고, 세부 research telemetry 전체가 itemized response로 변환되지는 않는다.
- 일부 DB 테이블은 repository가 런타임 생성하지만, event table 등은 별도 SQL/migration 적용 상태에 따라 차이가 날 수 있다.

## 21. 코드 맵

| 영역 | 주요 파일 |
| --- | --- |
| 메인 에이전트 | `neos/agents/search_agents/hyper_deep_research/agent.py` |
| 설정 | `neos/agents/search_agents/hyper_deep_research/config.py`, `neos/config/schema.py` |
| 데이터 수집 | `data_collection.py`, `hybrid_data_collector.py` |
| 분석 | `analysis.py` |
| 스킬 통합 | `skills_integration.py` |
| 리포트 생성 | `report_generator.py` |
| 반복 개선 | `iterative_refiner.py`, `content_chunker.py`, `metrics_collector.py`, `learning_feedback.py` |
| 인용 | `utils/citation_tracker.py`, `utils/citation_recommender.py`, `utils/academic_identifier_extractor.py` |
| 검증/품질 | `utils/fact_checker.py`, `utils/bias_detector.py`, `utils/source_quality_scorer.py`, `utils/semantic_clusterer.py` |
| 저장소 | `repository/hyper_research_repository.py`, `db/hyper_deep_research.sql` |
| 이벤트 | `utils/event_logger.py`, `neos/api/handlers/workflow_stream_handlers.py`, `neos/api/adapters/stream_adapter.py` |
| 워크플로우 통합 | `neos/workflow/hyper_deep/executor.py`, `neos/workflow/graph.py`, `neos/workflow/routing/orchestrator_router.py` |
| Ray 분산 실행 | `neos/workflow/recursive/distributed_orchestrator.py`, `neos/workflow/ray_actors/executor_pool.py`, `neos/workflow/ray_actors/stateless_actors.py`, `neos/workflow/ray_actors/dag_utils.py` |
| 하네스 | `neos/workflow/harness/adapters/hyper_deep.py`, `neos/workflow/harness/*` |
