# Async Research Redis Streams Design

## 목적

Celery 워커가 생성한 `async_research` 진행 이벤트를 API 프로세스의 SSE 응답으로
안전하게 전달한다. 늦은 접속과 재연결에서도 이벤트를 재생하며, 완료 또는 실패 이벤트를
받으면 스트림을 종료한다.

이 변경은 `async_research` 경로에만 적용한다. `deep_analysis`의 DB 이벤트 로그와 다른
`StreamManager` 호출자는 변경하지 않는다.

## 현재 결함

API와 Celery 워커는 서로 다른 프로세스에서 각자의 전역 `StreamManager`를 사용한다.
SSE GET은 API 프로세스에 세션을 만들지만 워커에는 해당 세션이 없다. 따라서 워커의
`add_event()`는 `False`를 반환하고 이벤트를 폐기한다. API의 SSE 루프는 terminal event를
받지 못해 heartbeat만 계속 보낼 수 있다.

## 선택한 접근

공용 `redis.asyncio` 클라이언트 위에 세션별 Redis Stream 저장소를 추가한다.

- 키: `neos:async-research:events:{session_id}`
- 발행: `XADD`를 사용하고 Redis가 생성한 entry ID를 SSE event ID로 사용한다.
- 읽기: `XREAD`로 마지막 전달 ID 이후의 이벤트를 blocking read한다.
- 보존: 각 append에서 근사 `MAXLEN` 제한을 적용하고 stream key의 TTL을 갱신한다.
- 직렬화: `event`, JSON `data` 필드를 저장한다.

Redis Pub/Sub은 구독 전에 발생한 이벤트를 재생할 수 없어 사용하지 않는다. DB 이벤트
로그는 내구성은 높지만 이 경로에 필요한 범위보다 마이그레이션과 결합 비용이 크므로
채택하지 않는다.

## 구성 요소

### `AsyncResearchEventStream`

새 저장소 클래스는 Redis 명령과 직렬화만 책임진다.

- `append(session_id, event, data) -> str`: 이벤트를 추가하고 Redis entry ID를 반환한다.
- `read_after(session_id, last_event_id, block_ms, count) -> list[StreamEvent]`:
  커서 이후 이벤트를 읽어 기존 `StreamEvent` 형태로 반환한다.
- 입력 `last_event_id`가 없으면 `0-0`부터 읽어 제출 직후 발생한 이벤트도 재생한다.
- malformed Redis record는 전체 SSE 연결을 깨뜨리지 않고 해당 record를 건너뛰며
  구조화된 경고를 남긴다.

저장소는 `cache_manager.redis_client`를 재사용하되, 초기화되지 않았다면 기존
`CacheManager.initialize()`를 통해 연결한다. 테스트에서는 Redis protocol을 흉내 낸
fake client를 주입할 수 있어야 한다.

### Celery 발행자

`execute_workflow_async`의 시작·완료·실패 이벤트 발행을 새 저장소로 전환한다.
발행 실패를 조용히 삼키지 않는다.

- 시작 이벤트 발행 실패: 워크플로우 실행 전에 작업 실패로 처리한다.
- 완료 이벤트 발행 실패: 연구 결과가 생성됐더라도 Celery 작업을 실패로 표시해 SSE와
  상태 API가 서로 다른 성공 상태를 보이지 않게 한다.
- 실패 이벤트 발행 실패: 원래 예외를 보존하고 발행 실패를 로그에 함께 기록한다.

### SSE 소비자

소유권 검증은 기존 session owner 캐시 키를 그대로 사용한다. 검증 후 요청의
`Last-Event-ID` 헤더를 초기 커서로 사용하며, 헤더가 없으면 `0-0`부터 읽는다.

SSE generator는 blocking `XREAD`를 반복한다. 이벤트가 없으면 heartbeat를 보내고,
`workflow_completed` 또는 `workflow_failed`를 전송한 직후 종료한다. 같은 응답 내에서는
마지막으로 전송한 Redis entry ID를 커서로 갱신하므로 이벤트를 중복 전송하지 않는다.

유효하지 않은 `Last-Event-ID`는 `400 Bad Request`로 거부한다. Redis 읽기 장애는 heartbeat로
숨기지 않고 SSE `stream_error` terminal event를 보낸 뒤 연결을 종료한다.

## 수명과 용량

- TTL: 기존 session owner TTL과 같은 24시간
- 최대 길이: 세션당 1,000개 이벤트, Redis `MAXLEN ~` 사용
- read batch: 최대 100개
- blocking read: 15초; timeout마다 heartbeat 1회

TTL은 이벤트 append마다 갱신한다. owner key와 event stream은 같은 보존 기간을 사용하지만
원자적으로 생성될 필요는 없다. 소유권 키가 사라지면 새 SSE 접속은 기존 정책대로 404다.

## 오류 및 보안 경계

- session ID는 서버가 생성한 UUID이며 Redis key 구성 외에 명령으로 해석되지 않는다.
- SSE 접속 전에 owner key를 확인하므로 다른 사용자의 stream key를 읽을 수 없다.
- 이벤트 data는 JSON으로 직렬화하며 SSE 출력 시 줄 단위 규칙을 지키도록 기존
  `StreamEvent.to_sse_format()`을 재사용한다.
- Redis 연결 실패는 명시적인 작업 실패 또는 terminal SSE 오류로 노출한다.
- 로그에는 query 본문이나 이벤트 data 전체를 기록하지 않는다.

## 테스트 전략

1. 저장소 단위 테스트
   - `XADD`, `MAXLEN`, TTL 명령 계약
   - `0-0` 및 지정 커서 이후 순서 보존
   - JSON 왕복과 malformed record 격리
2. Celery 발행 계약 테스트
   - 시작·완료·실패 이벤트가 새 저장소로 전달됨
   - 발행 실패가 성공으로 위장되지 않음
3. API SSE 테스트
   - owner 검증 유지
   - 늦은 최초 접속에서 과거 이벤트 재생
   - `Last-Event-ID` 이후만 전달하고 중복 없음
   - terminal event 종료, timeout heartbeat, Redis 장애 종료
4. 프로세스 경계 회귀 테스트
   - 발행자와 소비자가 공유 메모리 없이 같은 fake Redis backend를 통해 이벤트를 교환함

## 제외 범위

- deep_analysis 이벤트 저장 방식 변경
- 기존 `StreamManager` 제거 또는 전체 호출자 마이그레이션
- WebSocket 도입
- 무기한 이벤트 보존과 소비자 그룹
- UI 변경

## 완료 조건

- Celery 워커와 API가 인메모리 세션 없이 이벤트를 교환한다.
- 최초 접속과 `Last-Event-ID` 재연결 모두 누락과 중복 없이 동작한다.
- terminal event 후 SSE가 종료되고 Redis 장애가 무한 heartbeat로 숨겨지지 않는다.
- 관련 API·workflow 테스트와 Ruff 검사가 통과한다.
- `docs/TODO_260729.md`의 §15가 완료 상태와 검증 근거로 갱신된다.
