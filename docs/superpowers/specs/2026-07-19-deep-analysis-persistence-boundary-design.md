# Deep Analysis Persistence Boundary Design

## 목적

완료된 deep-analysis 보고서를 대화 메시지로 복제하는 부가 영속화가 실패해도 정본 run의
성공 상태와 job 결과를 바꾸지 않게 한다. 작업 취소는 계속 전파하고, 실패 로그에는 민감할
수 있는 예외 원문을 남기지 않는다.

## 현재 결함

`neos/tasks/deep_analysis_job_task.py::_persist_assistant_message`는
`ChatService.add_message()`만 `try`로 감싼다. 그 전에 실행되는 `get_session_ctx()`,
`session.get(DARun, run_id)`, run 속성 접근은 경계 밖이다. 이 단계에서 DB 오류가 나면
`_execute()`까지 전파되어 이미 완료된 deep-analysis run이 Celery 재시도 또는 inline task
실패로 바뀐다.

보고서 정본은 이미 `job_completed` 이벤트와 deep-analysis 원장에 있으므로 대화 메시지
복제 실패가 run 성공을 무효화해서는 안 된다는 기존 D23 결정과 모순된다.

## 선택한 설계

`_persist_assistant_message()`의 DB 조회부터 `ChatService.add_message()`까지를 하나의
fail-soft `try` 경계로 묶는다.

1. 짧은 DB session에서 `DARun`을 조회한다.
2. `conversation_id` 또는 `assistant_message_id`가 없으면 정상 no-op으로 반환한다.
3. 둘 다 있으면 기존 인자 그대로 `ChatService.add_message()`를 호출한다.
4. 위 단계의 일반 예외는 경고 로그 후 반환한다.

함수의 반환형은 기존처럼 `None`을 유지한다. 호출자는 부가 영속화 성공 여부에 따라 run
결과를 분기하지 않는다.

## 예외와 취소

- `Exception` 하위의 DB 연결·조회·메시지 저장 오류는 삼킨다.
- Python 3.12에서 `asyncio.CancelledError`는 `BaseException` 하위이므로 이 경계에 잡히지 않고
  전파된다.
- `KeyboardInterrupt`, `SystemExit`도 잡지 않는다.
- 경고 로그는 `run_id`와 `type(exc).__name__`만 기록한다.
- 예외 문자열, 보고서 markdown, conversation/message ID, DB 연결 정보는 기록하지 않는다.

로그 메시지는 다음 구조로 고정한다.

```text
failed to persist deep_analysis report message: run=<run_id> error_type=<type>
```

## 테스트

단위 테스트는 다음 계약을 검증한다.

- DB session 진입 실패가 `_persist_assistant_message()` 밖으로 전파되지 않는다.
- `session.get()` 실패가 전파되지 않는다.
- `ChatService.add_message()` 실패가 전파되지 않는다.
- 경고 로그가 `run_id`와 예외 타입을 포함하고 예외 원문은 포함하지 않는다.
- `CancelledError`는 전파된다.
- 대화 연결이 없는 run은 기존처럼 no-op이다.

기존 PostgreSQL 통합 테스트 3개를 실행해 실제 대화 메시지 저장과 `_execute()` 사슬이
계속 동작하는지 확인한다. 관련 task/workflow 테스트와 Ruff도 함께 실행한다.

## 제외 범위

- outbox 테이블과 별도 persistence worker
- 메시지 복제 재시도 정책
- run/event schema 변경
- `ChatService` API 변경
- 대화 메시지 저장 실패를 사용자 SSE 이벤트로 노출하는 계약

## 완료 조건

- 모든 부가 영속화 일반 실패가 완료된 run 결과를 바꾸지 않는다.
- 작업 취소는 전파된다.
- 실패 로그에 예외 원문과 보고서 내용이 없다.
- 단위 및 실제 PostgreSQL 통합 테스트, 관련 회귀, Ruff가 통과한다.
- `docs/TODO_260729.md`의 §8이 완료 상태와 검증 근거로 갱신된다.
