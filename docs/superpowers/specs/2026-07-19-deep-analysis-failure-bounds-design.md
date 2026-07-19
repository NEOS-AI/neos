# Deep Analysis 실패 바운드 설계

**작성일:** 2026-07-19  
**상태:** 승인됨  
**범위:** `docs/TODO_260729.md` §1 — 토큰을 쓰지 않는 워커 실패의 무한 루프와 인라인 job의 무제한 실행

## 1. 문제

`Orchestrator`의 정지 조건은 소비 토큰과 질문 가치 점수를 기준으로 한다. 워커가 계통적으로 실패하면서 `tokens_spent=0`을 반환하면 예산이 줄지 않아 같은 질문이 무기한 다시 선택될 수 있다.

기존 D15 무진전 감지는 새 feedback 같은 상태 변화를 진전으로 인정한다. 따라서 실패 패스가 ledger 상태를 바꾸면 실질적인 조사 성과가 없어도 무진전 카운터가 초기화될 수 있다.

Celery 실행자는 soft/hard time limit이 있지만 기본 구성인 인라인 실행자는 `_execute()`를 제한 없이 `asyncio.create_task()`로 실행한다. 오케스트레이터 안전장치가 작동하지 않으면 웹 프로세스 안에서 job이 무기한 남는다.

## 2. 목표와 비목표

### 목표

- 토큰을 소비하지 않는 반복 워커 실패가 제한된 횟수 안에 수렴한다.
- 질문 하나의 실패가 다른 질문의 정상 진행을 불필요하게 중단하지 않는다.
- 인라인 실행에도 Celery soft limit과 같은 성격의 전체 실행시간 상한을 둔다.
- 인라인 timeout은 run을 `failed`로 기록하고 기존 resume 경로로 재시도할 수 있게 한다.
- timeout으로 끝난 불완전 보고서를 완료 결과나 채팅 메시지로 저장하지 않는다.

### 비목표

- 전역 token cap의 라운드 내 초과 문제(TODO §4)는 이번 변경에서 다루지 않는다.
- Celery 브로커 장애 fallback 정책(TODO §5)은 바꾸지 않는다.
- 일반적인 worker retry/backoff 정책을 새로 도입하지 않는다.
- partial 보고서를 성공 결과로 발행하지 않는다.

## 3. 오케스트레이터 실패 바운드

`Orchestrator`에 run 범위의 질문별 연속 실패 카운터를 둔다. 이 카운터는 기존 `_stall_counts`와 역할을 분리한다.

- `WorkerResult.status == "failed"`이면 토큰·verified claim·feedback 변화와 관계없이 해당 질문의 실패 카운터를 1 증가시킨다.
- 정상 또는 partial 패스가 실질적인 진전을 만들면 해당 질문의 실패 카운터를 0으로 초기화한다.
- 다른 질문의 성공은 실패한 질문의 카운터에 영향을 주지 않는다.
- split으로 생긴 자식 질문은 독립 카운터로 시작한다.
- 연속 실패가 `max_stall_rounds`에 도달하면 기존 D15 종료 경로를 사용한다. 최대 깊이 전이면 split하고, 최대 깊이면 abandon한다.
- 기존 `fail_streak`과 effort ladder 동작은 유지한다. 새 카운터는 실행 안전장치이고, ledger의 실패 이력은 조사 전략 신호다.

운영 관측을 위해 실패 패스에는 질문 ID, 연속 실패 횟수, 마지막 실패 사유를 이벤트로 남긴다. 상한 도달 시 기존 `stall_terminated` 이벤트에도 종료 근거가 반복 실패임을 구분할 수 있는 payload를 포함한다.

## 4. 인라인 job 전체 timeout

job 코어의 `execute_run()`과 `resume_run()`에 선택적 `timeout_seconds` 인자를 추가한다. 인라인 실행자는 `deep_analysis.job_soft_time_limit`을 전달하고, Celery 실행자는 기존 soft/hard limit을 사용하므로 이 인자를 전달하지 않는다.

`execute_run()`은 기존 실패 처리 `try` **안에서** `orchestrator.run()`을 `asyncio.wait_for()`로 감싼다. 바깥 dispatch 계층에서 `_execute()` 전체를 감싸지 않는다. 그래야 timeout으로 내부 task가 취소된 뒤 발생하는 `TimeoutError`가 기존 `_record_failure()` 경계를 통과해 run 상태와 lifecycle event를 함께 확정한다.

```text
submit_deep_analysis_job
  -> inline _execute(timeout_seconds=job_soft_time_limit)
       -> execute_run의 실패 처리 try
            -> wait_for(orchestrator.run)
                 -> 정상 종료: job_completed + assistant message 저장
                 -> timeout: 별도 세션에서 run.status = failed
                             + job_failed 이벤트 커밋
                             + TimeoutError 재전파
                             + assistant message 저장 안 함
                             + resume_run 대상 유지
```

timeout을 성공이나 partial completion으로 변환하지 않는다. `execute_run()`의 기존 실패 기록 계약을 재사용하며, 새 상태 저장 경로나 별도 복구 포맷을 만들지 않는다. `resume_run()`도 받은 timeout 값을 재개된 `execute_run()`에 전달한다.

Celery 경로의 soft/hard limit과 retry 의미는 이번 변경에서 바꾸지 않는다.

## 5. 오류 처리

- 개별 워커 예외는 기존처럼 `WorkerResult(status="failed")`로 변환한다. 한 번의 워커 실패로 전체 run을 즉시 실패시키지 않는다.
- 반복 실패 상한은 질문 단위로 적용한다.
- timeout 취소가 발생하면 예외를 삼키지 않는다. `execute_run()`이 run과 lifecycle event를 내구성 있게 실패 처리한다.
- timeout 뒤 `_persist_assistant_message()`를 호출하지 않는다.
- 완료된 run에 timeout 실패 이벤트가 추가되는 경쟁이 없도록 정상 완료와 timeout 경계를 검증한다.

## 6. 테스트 전략

1. `tokens_spent=0`인 항상 실패 워커로 `Orchestrator.run()`이 제한된 라운드 안에 종료되는 회귀 테스트를 추가한다.
2. 실패 뒤 실질적인 성공이 발생하면 해당 질문의 연속 실패 카운터가 초기화되는지 검증한다.
3. 질문별 카운터가 서로 격리되고 split 자식이 독립적으로 시작하는지 검증한다.
4. 인라인 실행이 `job_soft_time_limit`을 넘으면 task가 취소되고 timeout 예외가 관측되는지 검증한다.
5. timeout이 `run.status="failed"`, `job_failed` 이벤트, `resume_run()` 가능 상태를 함께 만드는지 job 계약 테스트로 검증한다.
6. 기존 정상 실행, partial worker, split/abandon, Celery dispatch 테스트를 실행해 회귀가 없음을 확인한다.

## 7. 수용 기준

- 항상 실패하며 토큰을 소비하지 않는 워커가 더 이상 무한 루프를 만들지 않는다.
- 실패 상한은 질문별이며 정상 질문의 진행을 방해하지 않는다.
- 인라인 job은 `job_soft_time_limit`보다 오래 실행되지 않는다.
- 인라인 timeout 후 run은 `failed`이고 `job_failed` 이벤트가 존재한다.
- timeout run은 기존 `resume_run()`으로 재개할 수 있다.
- timeout run의 불완전 보고서는 assistant message로 저장되지 않는다.
- 기존 Celery dispatch 및 정상 deep-analysis 테스트가 통과한다.
