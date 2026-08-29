# 계획 — pytest-timeout 도입 + C3-m1 (판정자 지출 채널)

**작성일:** 2026-08-29
**브랜치:** `dev`
**근거 문서:** `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §7.4(멈춤 감지 부재) · §7 C3-m1

두 과제는 **서로 다른 파일 집합**을 건드리고 의존이 없다. 병렬로 진행한다.

---

## Global Constraints

이 프로젝트의 규율이다. 두 태스크 모두에 구속력이 있다.

1. **커밋하지 않는다.** 구현만 하고 보고한다. 커밋은 컨트롤러가 리뷰 후에 한다.
   (병렬 실행이라 같은 저장소에서 두 에이전트가 커밋하면 git 인덱스가 경합한다.)
2. **전체 테스트 스위트를 절대 돌리지 않는다.** 이 저장소의 테스트는 공유
   PostgreSQL 하나를 쓰고, `cleanup_test_data` 가 매 테스트마다 TRUNCATE/DELETE 한다.
   **동시에 두 스위트가 돌면 테이블 락으로 교착한다** — 이 세션에서 실제로 6시간
   매달렸다. 자기 태스크가 지정한 파일만 돌린다.
3. **매직넘버 금지.** 상수는 설정으로, 프롬프트는 파일로 (설계 §11).
4. 주석·독스트링은 **주변 코드의 언어를 따른다** (이 저장소는 한국어 주석이 많다).
   무엇을 하는지가 아니라 **왜 그런지**를 적는다.
5. `neos/workflow/deep_analysis/` 는 프레임워크 프리다 — Celery·FastAPI·ChatService 를
   임포트하지 않는다.
6. 새 fallback 을 추가하면 **그 fallback 이 남기는 이벤트를 함께 정의한다** (§3.2).
7. 파이썬 실행은 `.venv/bin/python` 이다 (bare `pytest` 는 asyncio 마커 수집 실패).

---

## Task 1 — pytest-timeout 도입

**왜:** §7.4 의 멈춤을 **사람이 10시간 46분 뒤에** 알아챘다. 멈춤은 실패보다 나쁘다 —
`pytest` 가 세지 않고 CI 는 타임아웃까지 초록도 빨강도 아니다. 자동 감지 수단이 없다.

**파일:** `pyproject.toml` · `pytest.ini` (그리고 필요하면 `tests/` 아래 새 테스트 1개)

**요구사항:**

1. `pytest-timeout` 을 **dev 의존성**에 추가한다 (`pyproject.toml` 의 dev 그룹 —
   `pytest-randomly` 가 있는 곳과 같은 자리).
2. `pytest.ini` 의 `addopts` 가 아니라 **전용 설정 키**로 기본 타임아웃을 건다
   (`timeout = ...`, `timeout_method = ...`).
3. **값을 측정해서 정한다.** 추측 금지.
   - 현재 전체 스위트는 3294 tests / 약 120초다.
   - 가장 느린 테스트들을 `--durations=25` 로 실제로 재고, 그 최대값에 **넉넉한
     배수**를 곱해 정한다. 정상 테스트를 죽이는 타임아웃은 이 도입을 되돌리게 만든다.
   - 고른 값과 **측정한 근거 수치**를 `pytest.ini` 주석에 남긴다.
4. `timeout_method` 를 고르고 **왜 그것인지 주석에 적는다.**
   - `signal`(SIGALRM)은 메인 스레드만 중단시킨다. §7.4 의 멈춤은 메인 스레드의
     `join()` 이었으므로 잡힌다.
   - `thread` 는 모든 스레드의 스택을 덤프하고 프로세스를 죽인다 — 진단 정보가 많다.
   - 판단해서 고르고 근거를 적을 것.
5. **실제로 잡히는지 증명한다.** 일부러 멈추는 테스트를 만들어 타임아웃이
   발동하는 것을 확인한다. 그 확인용 테스트를 저장소에 남길지는 판단에 맡긴다 —
   남긴다면 **반드시 빠르게** 끝나야 하고(예: 자체 `@pytest.mark.timeout(1)`),
   남기지 않는다면 확인 결과를 보고서에 붙인다.
6. 정상 테스트가 죽지 않는지 확인한다. **전체 스위트는 돌리지 말고**, 위 3에서
   가장 느렸던 파일 2~3개만 돌려 통과를 확인한다.

**⚠️ DB 금지:** 이 태스크는 **DB 를 건드리는 테스트를 하나도 돌리지 않는다.**
느린 파일 확인은 `-m no_db` 로 제한하거나, `--collect-only` 와 `--durations` 만
쓴다. 동시에 다른 에이전트가 DB 테스트를 돌리고 있다.

**완료 기준:** 의존성 추가 · 설정 키 2개와 근거 주석 · 멈춤이 실제로 잡히는 것을
관측한 증거 · 느린 테스트가 죽지 않는 것을 관측한 증거.

---

## Task 2 — C3-m1: 판정자에게 지출 채널을 연다

**왜:** 에이전틱 판정자의 토큰은 **성공하든 실패하든** `DAQuestion.spent_tokens` 에
들지 않는다. C3 은 `claim_graded` 진단의 `judge_tokens` 로 **보이게만** 했다.
지금 그 채널을 연다.

**⚠️ 이 변경은 예산 동작을 바꾼다 (의도된 것).** `total_spent()` 가 올라가고
`budgeter.should_stop()` 이 조금 일찍 멈춘다. 수가 커진 것이 아니라 **원래 맞았어야
할 수가 되는 것**이다. 이 사실을 숨기지 말고 코드 주석과 보고서에 적을 것.

**파일:**
- `neos/workflow/deep_analysis/models.py` — `Verdict`
- `neos/workflow/deep_analysis/graders/agentic.py`
- `neos/workflow/deep_analysis/orchestrator.py` — `_grade`
- `neos/workflow/deep_analysis/ledger.py` — `commit_pass`
- 테스트: `tests/workflow/deep_analysis/test_agentic_grader.py` 및 필요한 새 파일

**요구사항:**

1. `Verdict` 에 `tokens_spent: int = 0` 을 더한다. 기본값 0 은 필수다 — `Verdict` 를
   짓는 곳이 많고 전부 고칠 일이 아니다.
2. `AgenticGrader.grade()` 가 그 값을 채운다. **이미 계산돼 있다** — `_diagnostics()`
   의 `judge_tokens` 와 **같은 수**여야 한다. 두 수가 갈라지면 원장이 자기모순이 된다.
   `skipped`(디스패치 없음)는 0이다.
3. `Orchestrator._grade()` 가 그 값을 **보존**한다. 지금 `replace(agentic_verdict,
   diagnostics=...)` 로 돌려주므로 자동 보존되지만, **결정론 verdict 만 반환하는
   분기들**(`not_configured` · det 실패로 skip · `TokenBudgetExhausted`)을 확인할 것.
   `exhausted` 분기는 판정자가 토큰을 썼을 수도 있다 — 확인하고 판단해서 처리하되
   **판단 근거를 주석에 적을 것.**
4. `Ledger.commit_pass()` 가 `question.spent_tokens` 에 verdict 들의 토큰을 더한다.
   `commit_pass` 는 이미 `verdicts: dict[str, Verdict]` 를 받는다 (`ledger.py:772`).
   지금 그 줄은 `question.spent_tokens += result.tokens_spent` 다 (`ledger.py:819`).
   **이중 계상 금지** — 워커 토큰과 판정자 토큰이 겹치지 않는지 확인할 것.
5. **테스트로 고정한다:**
   - `Verdict.tokens_spent` 가 `judge_tokens` 진단과 **같은 수**임
   - `skipped` 는 0
   - `commit_pass` 후 `question.spent_tokens` 가 워커 토큰 + 판정자 토큰임
   - 이중 계상이 없음
6. **P2 (단일 작성자) 유지** — 원장 쓰기는 오케스트레이터/Ledger 한 곳이다.
   판정자는 값을 실어 보낼 뿐 원장에 쓰지 않는다.

**돌릴 테스트 (이 파일들만):**
```
.venv/bin/python -m pytest tests/workflow/deep_analysis/test_agentic_grader.py \
  tests/workflow/deep_analysis/test_llm.py -q -p no:randomly
```
Ledger 테스트는 DB 를 쓴다. 필요하면 **이 태스크만** 돌려도 된다 (다른 에이전트는
DB 를 안 쓴다):
```
.venv/bin/python -m pytest tests/workflow/deep_analysis/test_ledger_m2.py \
  tests/workflow/deep_analysis/test_ledger_m3.py -q -p no:randomly
```

**완료 기준:** 위 5개 단언이 테스트로 서 있고, 지정한 파일들이 통과하며,
예산 동작이 바뀐다는 사실이 코드 주석에 적혀 있다.

---

## 컨트롤러가 직접 하는 것 (에이전트 몫 아님)

- 커밋 (두 태스크 각각)
- 로드맵 갱신 — §7.4 의 "남은 후속", C3-m1 종결, **새 표본 비교 경계** 기록
- 전체 스위트 검증 (시드 여러 개, 순차)
