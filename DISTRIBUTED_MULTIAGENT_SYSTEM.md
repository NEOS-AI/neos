# NEOS 분산 멀티에이전트 시스템

## 📋 개요

NEOS를 **진정한 분산 멀티에이전트 시스템**으로 전환하기 위한 종합 개선 작업이 완료되었습니다.

### 주요 개선 사항

1. **에이전트 자율성**: 중앙 제어 → 자율적 작업 발견 및 실행
2. **통신 메커니즘**: 직접 함수 호출 → 비동기 메시지 기반 통신
3. **협력 패턴**: 독립 실행 → 동적 협상 및 협력
4. **동적 확장**: 하드코딩 → 런타임 에이전트 등록/발견
5. **상태 관리**: 단일 전역 상태 → 계층적 로컬/전역 상태
6. **부하 분산**: 고정 병렬 → 동적 작업 큐 기반 분산
7. **일관성 보장**: 부재 → 분산 트랜잭션 지원
8. **자가 치유**: 제한적 → Supervisor 기반 자동 복구

---

## 🏗️ 아키텍처

### 핵심 컴포넌트

```
┌─────────────────────────────────────────────────────────────┐
│                   분산 워크플로우 계층                         │
│  (DistributedMultiAgentWorkflow)                            │
└─────────────────────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
┌───────▼────────┐  ┌────────▼────────┐  ┌───────▼────────┐
│  Message Bus   │  │  Agent Registry │  │  State Manager │
│  (이벤트 통신)   │  │  (동적 발견)      │  │  (계층적 상태)   │
└────────────────┘  └─────────────────┘  └────────────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
┌───────▼────────┐  ┌────────▼────────┐  ┌───────▼────────┐
│  Work Queue    │  │   Supervisor    │  │  Collaboration │
│  (부하 분산)     │  │  (자가 치유)      │  │  (에이전트 협력) │
└────────────────┘  └─────────────────┘  └────────────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                    ┌────────▼────────┐
                    │ Autonomous      │
                    │ Agents          │
                    │ (자율 실행)       │
                    └─────────────────┘
```

---

## 📂 파일 구조

### 새로 추가된 파일

```
neos/
├── workflow/
│   ├── distributed/                    # 분산 시스템 컴포넌트
│   │   ├── __init__.py
│   │   ├── message_bus.py             # 이벤트 기반 메시지 버스
│   │   ├── agent_registry.py          # 동적 에이전트 레지스트리
│   │   ├── state_manager.py           # 계층적 상태 관리
│   │   ├── collaboration.py           # 협력 프로토콜 (Contract Net)
│   │   ├── work_queue.py              # 작업 큐 및 부하 분산
│   │   ├── supervisor.py              # Supervisor 패턴
│   │   └── transaction.py             # 분산 트랜잭션 (Saga)
│   │
│   └── distributed_graph.py           # 분산 워크플로우 그래프
│
└── agents/
    ├── autonomous_base.py              # 자율 에이전트 베이스 클래스
    └── autonomous_search_example.py    # 마이그레이션 예시
```

---

## 🚀 사용 방법

### 1. 기본 설정

```python
from neos.workflow.distributed_graph import distributed_workflow

# 워크플로우 초기화
await distributed_workflow.initialize()
```

### 2. 자율 에이전트 등록

```python
from neos.agents.autonomous_search_example import AutonomousKnowledgeSearchAgent

# 에이전트 생성
agent = AutonomousKnowledgeSearchAgent()

# 워크플로우에 등록 (자동으로 시작됨)
await distributed_workflow.register_autonomous_agent(agent)
```

### 3. 워크플로우 실행

```python
# 사용자 입력
user_input = {
    "user_id": "user123",
    "session_id": "session456",
    "query": "Python에서 비동기 프로그래밍 방법"
}

# 분산 워크플로우 실행
result = await distributed_workflow.execute_workflow(user_input)

print(result)
# {
#     "success": True,
#     "response": "...",
#     "distributed": True,
#     "quality_score": 0.85
# }
```

### 4. 시스템 모니터링

```python
# 통계 조회
stats = await distributed_workflow.get_statistics()
print(stats)

# 헬스 체크
health = await distributed_workflow.health_check()
print(health)
```

---

## 🔧 주요 기능

### 1. 이벤트 기반 통신

에이전트들은 메시지 버스를 통해 비동기적으로 통신합니다.

```python
from neos.workflow.distributed import get_message_bus, Event, EventType

message_bus = await get_message_bus()

# 이벤트 발행
await message_bus.publish(Event(
    event_id="evt-001",
    event_type=EventType.TASK_SUBMITTED,
    source="agent_a",
    data={"task": "search", "query": "test"}
))

# 이벤트 구독
async def handler(event):
    print(f"Received: {event.data}")

await message_bus.subscribe(EventType.TASK_SUBMITTED, handler)
```

### 2. 동적 에이전트 발견

능력 기반으로 에이전트를 찾고 선택합니다.

```python
from neos.workflow.distributed import get_agent_registry, AgentCapability

registry = await get_agent_registry()

# 능력으로 에이전트 찾기
agents = await registry.discover_by_capability(
    AgentCapability.WEB_SEARCH,
    status=AgentStatus.AVAILABLE
)

# 최적 에이전트 선택
best_agent = await registry.select_best_agent(
    AgentCapability.WEB_SEARCH,
    strategy="least_loaded"
)
```

### 3. 에이전트 협력

Contract Net Protocol을 사용한 작업 위임.

```python
from neos.workflow.distributed import get_collaboration_protocol

collaboration = await get_collaboration_protocol()

# 작업 위임
assigned_agent = await collaboration.delegate_task(
    task_description="웹에서 최신 뉴스 검색",
    required_capability=AgentCapability.WEB_SEARCH,
    requester_id="agent_a"
)
```

### 4. 작업 큐 및 부하 분산

우선순위 기반 작업 큐.

```python
from neos.workflow.distributed import get_work_queue, TaskPriority

work_queue = await get_work_queue()

# 작업 제출
task_id = await work_queue.submit_simple_task(
    description="데이터 분석 수행",
    capability=AgentCapability.DATA_ANALYSIS,
    payload={"data": [...], "options": {}},
    priority=TaskPriority.HIGH
)
```

### 5. Supervisor (자가 치유)

에이전트 실패 시 자동 복구.

```python
from neos.workflow.distributed import get_supervisor

supervisor = await get_supervisor()

# 에이전트 감독
await supervisor.supervise_agent(
    agent=my_agent,
    agent_id=my_agent.agent_id,
    restart_callback=lambda: my_agent.start()
)

# 실패 히스토리 조회
failures = supervisor.get_failure_history()
```

### 6. 분산 트랜잭션 (Saga)

복잡한 워크플로우의 일관성 보장.

```python
from neos.workflow.distributed import DistributedTransaction

# 트랜잭션 정의
transaction = DistributedTransaction(name="Multi-step Search")

transaction.add_step(
    name="웹 검색",
    execute=perform_web_search,
    compensate=undo_web_search
).add_step(
    name="결과 분석",
    execute=analyze_results,
    compensate=undo_analysis
).add_step(
    name="보고서 생성",
    execute=generate_report,
    compensate=delete_report
)

# 실행
success = await transaction.execute()
```

---

## 📊 성능 및 확장성

### 수평 확장

- PostgreSQL 기반 분산 상태 관리로 여러 인스턴스 동시 실행 가능
- Redis Pub/Sub으로 에이전트 간 통신 (In-Memory에서 업그레이드 가능)

### 부하 분산

- 동적 워커 풀로 작업 자동 분배
- 우선순위 큐로 중요 작업 우선 처리
- 에이전트 성능 기반 최적 할당

### 장애 복구

- Circuit Breaker로 장애 격리
- Supervisor가 자동 재시작
- Saga 패턴으로 트랜잭션 롤백

---

## 🔄 마이그레이션 가이드

### 기존 에이전트 → 자율 에이전트

1. **AutonomousAgent 상속**

```python
from neos.agents.autonomous_base import AutonomousAgent
from neos.workflow.distributed import AgentCapability

class MyAutonomousAgent(AutonomousAgent):
    def __init__(self):
        super().__init__(
            name="MyAgent",
            llm=my_llm,
            role="Specialist",
            goal="Do something",
            backstory="...",
            capabilities=[AgentCapability.WEB_SEARCH]
        )
```

2. **execute_autonomous_task() 구현**

```python
async def execute_autonomous_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
    payload = task_data.get("payload", {})
    # 작업 수행
    result = await self.do_work(payload)
    return {"success": True, "result": result}
```

3. **협력 지원 (선택사항)**

```python
async def handle_collaboration_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
    # 다른 에이전트 요청 처리
    return {"can_help": True, "data": ...}
```

4. **등록 및 시작**

```python
agent = MyAutonomousAgent()
await distributed_workflow.register_autonomous_agent(agent)
```

---

## 📈 모니터링 및 디버깅

### 로깅

```python
import logging

# 분산 시스템 컴포넌트 로깅 활성화
logging.getLogger("neos.workflow.distributed").setLevel(logging.DEBUG)
```

### 메트릭

```python
# 에이전트 메트릭
agent_metrics = agent.get_metrics()
print(agent_metrics)
# {
#     "agent_id": "...",
#     "tasks_completed": 42,
#     "success_rate": 0.95,
#     "average_response_time": 2.3
# }

# 시스템 전체 통계
system_stats = await distributed_workflow.get_statistics()
```

---

## 🎯 다음 단계

### 권장 사항

1. **기존 에이전트 마이그레이션**
   - 하나씩 자율 에이전트로 변환
   - `autonomous_search_example.py` 참고

2. **Redis 업그레이드**
   - In-Memory 메시지 큐 → Redis Pub/Sub
   - `settings.MESSAGE_QUEUE_TYPE = "redis"` 설정

3. **모니터링 도구 추가**
   - Prometheus 메트릭 익스포트
   - Grafana 대시보드 구축

4. **성능 테스트**
   - 동시 작업 처리 능력 측정
   - 병목 지점 식별 및 최적화

---

## 🐛 트러블슈팅

### 에이전트가 작업을 받지 못함

- `capabilities` 올바르게 설정되었는지 확인
- 레지스트리에 등록되었는지 확인: `await registry.get_all_agents()`

### 작업이 큐에서 멈춤

- 워커 풀이 시작되었는지 확인: `await work_queue.start()`
- 워커 수 증가: `DistributedWorkQueue(num_workers=10)`

### Supervisor가 재시작하지 않음

- `auto_restart=True` 설정 확인
- 재시작 횟수 제한 확인: `max_restart_intensity`

---

## 📚 참고 자료

- **Message Bus**: `neos/workflow/distributed/message_bus.py`
- **Agent Registry**: `neos/workflow/distributed/agent_registry.py`
- **Collaboration**: `neos/workflow/distributed/collaboration.py`
- **Work Queue**: `neos/workflow/distributed/work_queue.py`
- **Supervisor**: `neos/workflow/distributed/supervisor.py`
- **Transaction**: `neos/workflow/distributed/transaction.py`

---

## ✅ 체크리스트

- [x] Phase 1: 기초 분산 인프라
  - [x] 이벤트 기반 메시지 버스
  - [x] 동적 에이전트 레지스트리
  - [x] 계층적 상태 관리

- [x] Phase 2: 에이전트 자율성 및 협력
  - [x] 자율 에이전트 베이스 클래스
  - [x] 협력 프로토콜 (Contract Net)

- [x] Phase 3: 분산 처리 고도화
  - [x] 작업 큐 및 부하 분산
  - [x] Supervisor 패턴
  - [x] 분산 트랜잭션 (Saga)

- [x] Phase 4: 통합 및 마이그레이션
  - [x] 분산 워크플로우 그래프
  - [x] 마이그레이션 예시
  - [x] 문서화

---

## 🎉 결론

NEOS는 이제 **진정한 분산 멀티에이전트 시스템**입니다:

✅ 에이전트가 자율적으로 작업 발견 및 실행
✅ 이벤트 기반 비동기 통신
✅ 동적 협력 및 협상
✅ 런타임 에이전트 등록/발견
✅ 계층적 상태 관리
✅ 동적 부하 분산
✅ 분산 트랜잭션 지원
✅ 자가 치유 능력

**확장 가능하고, 탄력적이며, 자율적인 멀티에이전트 시스템**이 완성되었습니다! 🚀
