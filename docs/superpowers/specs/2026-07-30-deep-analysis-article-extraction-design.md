# Deep Analysis — fetch 본문 추출 개선 설계

**작성일:** 2026-07-30
**상태:** 설계 승인됨
**선행:** `docs/TODO_260729.md` §7 (dead_end 90건 원인 규명 + 실측 검증)
**관련:** `docs/superpowers/specs/2026-07-27-deep-analysis-discard-recall-design.md`

---

## 1. 배경 — 추출기가 멀쩡한 출처를 읽을 수 없게 만들고 있다

2026-07-29 측정 run은 6/6 완료됐지만 dev claim이 **4건**뿐이었다(prompt v3 38건,
entailment 평가 22건). `dead_end` 이벤트가 **90건**이었고, 워커가 남긴 dead_end
텍스트를 분류하니 약 45%가 fetch 품질 문제였다 — "네비게이션/목차만 포함됨"
23%, "빈 내용" 20%.

### 1.1 근본 원인

`neos/workflow/deep_analysis/fetch.py:15-38`의 `html_to_text`는 `HTMLParser`로
`<script>`/`<style>`만 제외하고 **나머지 모든 텍스트 노드를 이어붙인다.** 본문,
네비게이션, 헤더, 푸터, 쿠키 배너, 목차가 구분 없이 하나의 문자열이 된다.

### 1.2 실측 — 본문은 처음부터 HTML 안에 있었다

이 run이 실제로 fetch한 URL 163건을 재수집해 비교했다(HTTP만, LLM 토큰 미사용).
비교 가능 143건:

- 중앙값 문자수 13,084 → 7,551 (비율 **0.70**)
- **32/143건(22%)** 은 텍스트의 절반 이상이 사라졌다 — 그만큼이 보일러플레이트였다
- trafilatura가 빈 문자열을 반환한 경우 **5/143건(3%)**

결정적 근거는 워커가 **이름을 들어 거부한 바로 그 페이지들**이다:

| 페이지 | 워커 보고 | trafilatura |
|---|---|---|
| EU AI Act Article 55 | "네비게이션/목차만 포함됨" | **1,702자** — "Article 55: Obligations of providers of general-purpose AI models with systemic risk…" |
| WHO 아스파탐 발표 | "탐색 메뉴만 fetch됨, 본문 없음" | **5,143자** — "Assessments of the health impacts of the non-sugar sweetener aspartame…" |
| AI Act high-level summary | "조문 전문 미포함" | **16,466자** |
| unesda.eu/aspartame | "빈 내용" | HTTP 403 — 실제 차단, 추출기로 해결 불가 |

즉 출처 품질 문제가 아니다. **12,389자의 네비게이션 텍스트에 본문이 묻혀 LLM이
"이 페이지엔 본문이 없다"고 판단했다.**

### 1.3 해결 수단은 이미 저장소에 있다

`trafilatura>=2.0.0`이 이미 의존성으로 선언돼 있고,
`neos/agents/analysis_agents.py:583`에서 이미 같은 목적(보일러플레이트 제거 본문
추출)으로 쓰인다. deep_analysis fetch 경로만 채택하지 않았다.

---

## 2. 설계

### 2.1 변경

`fetch.py`에 `extract_article_text(html: str) -> str`를 추가한다.

```
trafilatura.extract(html) 시도
  ├─ 비어 있지 않음 → 이 결과 사용
  └─ 비어 있음/예외  → 기존 html_to_text(html)로 fallback
```

`produce()`가 HTML 분기에서 `html_to_text` 대신 이 함수를 호출한다.
PDF 분기와 non-2xx 분기는 **변경하지 않는다.**

### 2.2 ⚠️ 정규화를 반드시 통과시킨다

`html_to_text`는 결과를 `normalize_evidence_text`로 정규화한다. trafilatura
출력도 **같은 정규화를 거쳐야 한다.** 이 정규화가 `_content_hash` 입력이고 quote
대조의 기준이므로, 빼먹으면 해싱 동작이 조용히 바뀌고 quote 대조가 추출기와
무관한 두 번째 이유로 깨진다.

### 2.3 fallback을 택한 이유

trafilatura 실패 시 빈 문자열을 반환하면 그 3%는 `E_NO_EVIDENCE`로 정직하게
거부되지만, **지금 통과하던 claim이 기각된다.** fallback은 "어떤 페이지에서도
현행보다 나빠지지 않는다"를 보장한다. 최악의 경우가 현재 동작과 동일하다.

fallback 발동 시 debug 로그를 남겨 이후 run에서 3% 비율을 관측 가능하게 한다.
블롭 스키마는 바꾸지 않는다.

---

## 3. 비목표

- **`quote_match_threshold`(0.92)를 건드리지 않는다.** 추출 텍스트가 바뀌면
  임계값 적정성도 달라질 수 있지만, 두 변수를 동시에 바꾸면 어느 쪽 효과인지
  분리할 수 없다. 이 스레드가 반복해서 피해온 실수다.
- `neos/agents/analysis_agents.py`를 손대거나 통합하지 않는다.
- search 관련성 문제(dead_end의 약 16%)는 별개 과제다.
- 차단된 출처(403, reCAPTCHA)는 추출기로 해결되지 않는다.
- 이 작업 중 어떤 live run도 실행하지 않는다.

---

## 4. ⚠️ baseline 단절

이 변경은 evidence 원문 텍스트를 바꾼다. 따라서:

**prompt v3(`20260723T124006Z`), entailment 평가(`20260725T081707Z`),
2026-07-29 run(`20260729T131543Z`)은 모두 구 추출기 기준이며, 이 변경 이후
산출물과 직접 비교할 수 없다.**

`docs/TODO_260729.md`와 이 문서에 단절 시점을 명시한다.
복원된 baseline 수치는 `docs/deep_analysis_funnel_baselines.json`에 남아 있다.

### 후속 순서

1. 추출기 교체 (이 문서)
2. 새 `mixed-v1` 5+1 run → **새 baseline** 확립
3. 그 다음에야 discard recall 재측정 (`2026-07-28-...-measurement.md` 플랜 재사용)

2번 없이 3번을 하면 안 된다. claim 생산량이 정상인 표본이어야 entailment가
무엇을 버리는지 측정할 수 있다.

---

## 5. 테스트

기존 불변식대로 **네트워크·LLM 없이** fixture HTML로만 검증한다.

- 네비게이션이 많은 페이지 + 본문 → trafilatura 결과가 쓰이고 네비게이션 텍스트가
  빠지는가
- trafilatura가 파싱 못 하는 입력 → `html_to_text` 결과로 fallback하는가
- **두 경로 모두 `normalize_evidence_text`를 통과하는가** (§2.2)
- PDF 분기와 non-2xx 분기가 그대로인가 (회귀)
- `html_to_text` 자체의 기존 테스트는 유지된다 — 여전히 fallback으로 쓰인다
