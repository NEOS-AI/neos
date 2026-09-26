# Claude Fable 5.1 대응 — 멀티에이전트 하네스 변경 스펙

**출처**: [Prompting Claude Fable 5.1](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-1) (Claude Platform Docs)
**대상 모델**: `claude-fable-5-1` (Claude Mythos 5.1 동일 적용)
**적용 범위**: lead agent + subagent 구조의 코딩/도구호출 에이전트 하네스

> 본 스펙의 프롬프트 문구는 원문 요지를 재작성한 초안이다. 운영 투입 전 위 문서의 해당 섹션에서 공식 문구를 확인하고 최종본을 확정할 것.

---

## 0. 전제 및 우선순위

Fable 5 프롬프트는 대부분 수정 없이 동작한다. 아래 항목은 **행동 차이로 인해 멀티에이전트 루프에서 비용·지연·정합성 문제를 일으키는 부분**만 추린 것이다.

| ID | 항목 | 유형 | 우선순위 |
|---|---|---|---|
| R-01 | 대화 이력 append-only 보장 | 런타임 | P0 (미준수 시 400) |
| R-02 | turn-scoped system message 도입 | 런타임 | P0 |
| R-03 | subagent 비동기 실행 | 런타임 | P0 |
| R-04 | progress update 수신·렌더링 | 런타임 | P1 |
| R-05 | effort 설정 외부화 | 런타임 | P1 |
| R-06 | `stop_reason: "refusal"` 처리 | 런타임 | P1 |
| R-07 | 클라이언트 compaction 형태 변경 | 런타임 | P1 |
| R-08 | `max_tokens` 산정 | 런타임 | P2 |
| P-01 | 자율 완수(Finish the whole task) | 프롬프트 | P0 |
| P-02 | 변경/테스트 범위 제한 | 프롬프트 | P0 |
| P-03 | 도구 호출 배칭 넛지 | 프롬프트 | P1 |
| P-04 | 부분 편집 선호 | 프롬프트 | P1 |
| P-05 | compaction 요약 보존 지시 | 프롬프트 | P1 |
| P-06 | low effort 검색 유도 | 프롬프트 | P2 |
| P-07 | 기존 anti-formatting / 서술억제 문구 제거 | 프롬프트 | P2 |

---

## 1. 런타임 요구사항

### R-01. 대화 이력은 append-only로 유지한다

**배경**
2026-08-31 이후 생성된 계정에서 Fable 5.1의 thinking block은 **해당 블록을 생성한 정확한 대화에만 유효**하다. 시스템 프롬프트, tool 목록, 이전 메시지 중 무엇이든 바뀐 상태에서 thinking block을 재전송하면 요청이 400으로 실패한다. 향후 모델은 전 계정에 이 검증이 적용될 예정이므로 지금 맞춰둔다.

**변경 사항**
1. assistant 턴은 API가 반환한 형태 **그대로**(thinking block 포함) 이력에 append한다. 직렬화 시 필드 순서·공백까지 변형되지 않도록 원본 객체를 보관한다.
2. 아래 동작을 하네스에서 **전면 금지**한다.
   - 턴마다 리마인더 문구를 주입했다가 다음 턴에 제거하는 패턴
   - 오래된 턴을 요약본으로 in-place 치환
   - 세션 중간에 `system` 또는 `tools` 배열을 재작성
3. 위 목적은 각각 R-02(turn-scoped system message), mid-conversation system message, 서버사이드 compaction / context editing으로 대체한다.
4. 진단 모드: `thinking.block_binding.prefix_mismatch_behavior = "drop_block"`(beta 헤더 `thinking-binding-controls-2026-08-01`)로 한 세션을 돌려 `input_transformations`를 로깅하는 CLI 옵션을 추가한다.

**수용 기준**
- 연속 요청 2개를 캡처했을 때, 새로 append된 턴을 제외한 앞부분이 **byte 단위로 동일**함을 검증하는 테스트가 통과한다.
- drop_block 진단 모드 실행 시 `input_transformations`가 비어 있다.

---

### R-02. turn-scoped system message를 지원한다

**배경**
매 턴 반복 주입해야 하는 지시(배칭 넛지, UI 제약 안내 등)를 기존 방식으로 넣으면 R-01을 위반하고 prompt cache가 깨진다.

**변경 사항**
1. beta 헤더 `mid-conversation-system-clear-at-2026-08-21`를 활성화한다.
2. `messages` 배열에 `{"role": "system", "content": ..., "clear_at": "next_user_message"}` 항목을 넣을 수 있는 경로를 만든다.
3. 배치 위치: tool_result를 담은 user 턴을 append한 **직후**에 새 복사본을 append한다.
4. **이전 복사본은 삭제·수정하지 않고 배열에 그대로 둔다.** 이후 user 메시지가 생기면 API가 자동으로 clear하며, clear된 항목은 입력 토큰을 소비하지 않는다.
5. beta 미사용 fallback: 같은 user 메시지 안에서 `tool_result` 블록들 **뒤에** text 블록으로 동일 문구를 넣는다.

**수용 기준**
- 루프 3회 이상 진행 시 system 항목이 누적되지만 입력 토큰 증가가 없음을 로그로 확인한다.
- 이전 복사본을 제거하는 코드 경로가 존재하지 않는다.

---

### R-03. subagent는 비동기로 실행한다

**배경**
lead agent가 subagent 완료까지 블로킹하면 평균 완료 시간이 늘어난다. 논블로킹으로 두면 동일 품질·토큰·비용에서 시간이 줄어든다(모델이 스스로 기다리기를 택하는 경우도 많지만, 이어서 작업하는 실행분에서 이득이 발생).

**변경 사항**
1. `spawn_subagent` 계열 도구는 **즉시 리턴**한다. 반환값은 `subagent_id`와 상태만 포함한다.
2. subagent 결과는 준비된 시점에 **이후 `user` 메시지**로 lead에게 전달한다.
3. lead가 명시적으로 대기를 원할 때 호출하는 **별도 도구**(예: `await_subagent(subagent_id)` 또는 `await_any`)를 제공한다.
4. 도구 description에 "이 호출은 즉시 반환되며 결과는 나중에 전달된다"는 점을 명시한다.

**수용 기준**
- subagent 실행 중 lead가 다른 tool_use를 발행할 수 있다.
- 결과 전달 메시지가 R-01을 위반하지 않는다(append만 발생).

---

### R-04. progress update를 수신하고 렌더링한다

**배경**
Fable 5.1은 긴 도구 호출 턴 중 사용자 대면 텍스트를 Fable 5보다 적게 쓴다. effort가 높고 체인이 길수록 심해져, 수 분간 침묵하거나 마지막 단계만 요약하는 것처럼 보인다. 다만 모델의 중간 메모는 **progress-update thinking block**으로 나오며, 기본값 `thinking.display = "omitted"`에서는 비어 있다.

**변경 사항**
1. `thinking.display = "updates"` 설정(beta 헤더 `thinking-display-updates-2026-08-18`). 요약 reasoning도 함께 받으려면 `"summarized"`.
2. 비어 있지 않은 `thinking` 블록을 상태 라인으로 렌더링한다.
3. 기존 시스템 프롬프트에서 서술을 억제하는 문구(예: 최종 응답까지 결과를 모아두라는 지시)를 **먼저 제거**한다. 문구 추가는 그다음이다.
4. UI가 tool output을 접거나 숨긴다면, turn-scoped system message로 그 사실을 모델에 알린다. 그렇지 않으면 모델이 "사용자에게 보여주려고" 표시되지 않는 명령을 실행한다.

**프롬프트 초안 (human-in-the-loop 모드 전용)**

```
Say in one line what you're about to do before you start, and post brief
updates as you work. Finish with a short recap that stands alone: what you
found, what you changed, and what remains.
```

```
Only you can see this command's output; the user's view shows a few lines at
most. Anything they need to read must be in your reply.
```

**수용 기준**
- 도구 호출 5회 이상인 태스크에서 중간 상태 라인이 최소 2회 이상 렌더링된다.
- 자율 모드(비대면 실행)에서는 1·2번 문구를 적용하지 않는다(P-01과 충돌 방지).

---

### R-05. effort 레벨을 외부 설정으로 분리한다

**배경**
effort는 Fable 5.1에서 지능·지연·비용을 조절하는 **주 제어 수단**이다. 레벨 이름이 모델 간 동일한 사고량을 의미하지 않으므로, Fable 5에서 돌린 스윕 결과를 재사용할 수 없다.

**변경 사항**
1. 기본값 `high`. `low` / `medium` / `xhigh` / `max`를 에이전트 역할별(lead, subagent 종류별)로 지정 가능하게 한다.
2. 대화 중간 effort 변경(change effort mid-conversation) 경로를 지원한다 — 특정 턴만 상향해야 하는 경우(P-06 참조)에 사용한다.
3. 자체 eval 스윕을 돌릴 수 있도록 effort를 파라미터로 받는 벤치 러너를 추가한다.

**참고 기준선**
- `medium`: Fable 5 수준 결과를 더 낮은 비용으로.
- `low`: 비용 대비 성능이 Opus/Sonnet 대비 경쟁력 있음 — 기존에 더 작은 모델을 높은 effort로 돌리던 자리를 후보로 검토.
- `xhigh` / `max`: eval로 품질 향상이 측정된 경우에만. R-08 참조.

---

### R-06. `stop_reason: "refusal"`을 처리한다

**배경**
Fable 5.1은 안전 분류기를 거치며 차단 시 `stop_reason: "refusal"`을 반환한다. 오탐은 Fable 5 출시 시점보다 줄었고 소스 코드 취약점 탐색은 허용되지만, 여전히 발생한다.

**변경 사항**
1. 루프에서 `refusal`을 예외가 아닌 정상 종료 상태로 분기 처리하고, 해당 태스크를 실패로 마킹 후 사유를 로깅한다(무한 재시도 금지).
2. 오탐 유발 요인 제거:
   - **컴파일 확인 문구**: "이 프로그램이 에러 없이 컴파일되는가" 형태 대신 "이 프로그램에 버그가 있는가" 형태로 프롬프트 템플릿을 수정한다.
   - **비주류 언어**: 해당 언어의 문서를 컨텍스트나 도구로 제공한다.
   - **base64**: tool output에 base64 인코딩 데이터가 모델 컨텍스트로 들어가지 않도록 필터링한다(파일 경로·요약으로 대체).

**수용 기준**
- base64 payload가 tool_result에 포함되지 않음을 검사하는 미들웨어 테스트가 존재한다.

---

### R-07. 클라이언트 compaction 형태를 단순화한다

**배경**
클라이언트에서 부분 요약 후 나머지 이력을 재전송하면 thinking block 바인딩과 prompt cache가 동시에 깨진다.

**변경 사항**
1. 가능하면 서버사이드 compaction / context editing에 위임한다.
2. 클라이언트 compaction이 필요하면: **이력 전체를 요약 메시지 1건 + 새 user 턴으로 교체**하고 그 외에는 아무것도 재전송하지 않는다. thinking block이 하나도 넘어가지 않으므로 검증 실패가 발생하지 않는다.
3. compaction 시점을 설정값으로 뺀다. cache read 단가가 낮아졌으므로 **이른 compaction이 더 이상 비용 최적이 아닐 수 있다** — 늦은 시점부터 실험한다.

---

### R-08. `max_tokens`는 thinking + 응답을 합쳐 산정한다

**배경**
`xhigh`, 특히 `max`에서는 응답 작성 전 사고 시간이 길어진다. 긴 산출물(문서 전면 재작성, 대형 코드 파일 등)을 한 번에 요구하면 사고 단계에서 초안을 거의 다 쓴 뒤 응답에서 다시 쓰는 일이 생겨 대기 시간과 출력 토큰이 늘고 `max_tokens`에 걸린다.

**변경 사항**
1. 긴 산출물 요청은 기본 `high`로 라우팅한다.
2. `xhigh`/`max` 사용 시 `max_tokens`를 예상 응답 길이가 아니라 **사고 + 응답 합계** 기준으로 잡는다.
3. 아래 문구를 user 메시지 말미에 append하고 `[max_tokens]`를 실제 값으로 치환한다.

**프롬프트 초안**

```
Everything in this reply, including reasoning done before it, counts against a
single budget of about [max_tokens] tokens. If the budget runs out mid-reply the
user gets a truncated response and has to start over. Writing the full
deliverable once as reasoning and again as the reply doubles the turn for no
gain, so don't.

For long deliverables — a multi-section document, a large table, a complete code
file — use the reasoning space to understand the request, verify the inputs it
depends on, and settle the structure and the hard decisions. Then use the output
space to write the output. Drafting it more than once is usually unnecessary.
```

---

## 2. 프롬프트 요구사항

### P-01. 자율 완수 지시 (P0)

**배경**
가이드 없이도 매우 긴 태스크를 수행하지만, 비동기 워크로드에서 다음 단계를 **설명만 하고 턴을 끝내거나**("다음으로 ~하겠습니다"), 이미 요청에 포함된 작업에 대해 허가를 묻는 경우("적용할까요?")가 있다. 사용자가 "계속"을 입력해야 진행되므로 long-horizon 능력을 못 쓴다.

**변경 사항**
lead agent 시스템 프롬프트에 두 블록을 **함께** 추가한다. 길이 제약이 있으면 첫 번째만으로도 효과의 대부분이 유지된다. 첫 문장(사용자가 실시간으로 보고 있지 않다는 선언)이 효과의 핵심이므로 그대로 둔다.

**블록 1 초안 — 자율 실행**

```
You are operating autonomously. The user is not watching in real time and cannot
answer mid-task, so "Want me to…?" or "Shall I…?" just blocks the work. For
reversible actions that follow from the original request, proceed. Stop only for
destructive actions or a genuine scope change the user must decide. Offering
follow-ups after the work is done is fine; asking permission before doing it is
not.

Exception: when the user is describing a problem, asking a question, or thinking
out loud rather than requesting a change, the deliverable is your assessment.
Report findings and stop. Don't apply a fix until asked.

Before ending your turn, read your last paragraph. If it is a plan, an analysis,
a question, a list of next steps, or a promise about work you haven't done, do
that work now with tool calls — including retrying after errors and gathering
missing information yourself. A long context or session is not a reason to stop.
End the turn only when the task is complete or you are blocked on input only the
user can give.

Before any command that changes system state — restarts, deletes, config edits —
confirm the evidence supports that specific action. A signal that resembles a
known failure can have a different cause.
```

**블록 2 초안 — 산출물 범위**

```
# Delivering work
The request, or the plan the user approved, sets the scope, and the scope is the
deliverable: don't quietly narrow it, widen it, or swap it out. Read ambiguity
the way a careful colleague would — make routine calls yourself, and check in
only when the readings would lead to materially different work. If the task as
specified has a real problem, say so in a sentence or two and keep building under
stated assumptions; if the user hears the concern and reaffirms, deliver the full
request.

If a question comes up partway, first do everything that doesn't depend on the
answer, then state the assumption you made — or, when a wrong guess would be
unsafe or would waste the work, put the question at the end of a turn that also
delivers that progress. If one part is blocked, finish every other part and say
exactly what you left out and why. Scaling the task down is the user's call, not
yours. A step you have decided on is something to run, not to announce.

Keep changes to what the request needs. Cleanup, documentation, or edits to files
the task didn't call for are suggestions to raise at the end, not changes to make.
Anything clearly beyond the ask, and anything risky or destructive, still needs
the user's go-ahead.
```

**주의**
이 블록은 모호한 요청에 대한 질문 빈도도 함께 낮춘다. 자체 태스크에서 트레이드오프를 확인할 것. 특정 확인 절차가 필요한 제품이라면 첫 문단 뒤에 해당 항목을 나열한 문장을 추가한다.

**수용 기준**
- 비대면 태스크 샘플에서 "허가 요청으로 턴 종료" 비율이 도입 전 대비 유의하게 감소.

---

### P-02. 변경·테스트 범위 제한 (P0)

**배경**
개방형 기능 구현을 맡기면 요청 범위를 넘어 주변 코드를 고치거나, 언급되지 않은 동작을 확장하거나, 변경 규모에 비해 많은 테스트 파일을 커밋하는 경향이 있다. 명시적 제외 지시에 잘 반응하며, 원문 기준 태스크 성공률 변화 없이 불필요한 추가·테스트 커밋이 크게 줄었다.

**프롬프트 초안**

```
If you find a pre-existing bug, a performance concern, or behavior the task
doesn't mention, don't fix, optimize, or extend it in this change unless the
requested behavior cannot work without it — report it as a follow-up in your
summary. Where the task is ambiguous, implement the reading its wording and the
surrounding code most directly support, state that assumption in your summary,
and don't build for the other readings too. Verify however you like; scratch
scripts need not be kept. Commit tests only where the task asks for them or where
this repository already keeps tests for this kind of change, sized like the
neighboring test files — roughly one focused test per stated behavior — and don't
promote scratch checks into permanent test files. This concerns extras only:
implement every behavior the task does ask for, completely.
```

**적용 위치**: 코드를 수정하는 모든 에이전트(lead + coding subagent)의 시스템 프롬프트.

---

### P-03. 독립 도구 호출 배칭 넛지 (P1)

**배경**
요청이 여러 대상을 명시하면 병렬 호출을 정상적으로 발행한다. 문제는 **다음 호출이 태스크상 암시되기만 하는 코딩/컴퓨터 사용 루프**(커스텀 코딩 에이전트, bash+editor 하네스)다. 이 경우 턴당 한 개씩 호출해 응답 품질은 그대로지만 토큰·왕복·체감 시간이 늘어난다.

**프롬프트 초안**

```
First list privately what you need next, then request everything that doesn't
depend on another result in this single response.
```

**적용 방식**
R-02의 turn-scoped system message로 **매 tool_result 턴마다 새 복사본**을 붙인다. 이전 복사본은 손대지 않는다.

**수용 기준**
- 독립 파일 N개를 읽어야 하는 시나리오에서 턴 수가 N → 1로 감소.

---

### P-04. 부분 편집 선호 (P1)

**배경**
작은 변경에도 파일 전체를 다시 쓰는 경향이 Fable 5보다 강하다. 결과 파일은 대개 동일하지만, 파일이 짧거나 대부분이 바뀌는 경우가 아니면 출력 토큰과 시간이 낭비된다.

**프롬프트 초안** (시스템 프롬프트 또는 첫 user 메시지 말미)

```
Minimize the tokens spent editing files, all else equal. When it won't change the
end result, edit surgically rather than rewriting the whole file.
```

---

### P-05. compaction 요약 보존 지시 (P1)

**적용 조건**: R-07에 따라 클라이언트 compaction을 유지하는 경우에만. 서버사이드 compaction은 이미 동일한 처리를 한다.

**요약 프롬프트가 반드시 요구해야 하는 것** — `<summary></summary>` 태그로 감싸고, 새 컨텍스트 윈도우가 작업을 다시 하거나 제약을 다시 받지 않고 이어갈 수 있을 만큼 담을 것. 보존 대상 6가지:

1. 발생한 문제와 그 처리·해결 방식
2. 제시·시도·보류된 선택지와 그 이유
3. 요청·결정·합의·배제된 사항, 선호·제약·경계 — **원문 그대로**
4. 현재 상태: 다룬 것, 확정된 것, 완료된 것
5. 미해결·약속된 것·다음에 예상되는 것
6. 재구성이 어려운 구체값: 이름, 숫자, 날짜, 정확한 표현, 링크 — **그대로**

추가 규칙: 위 6항목은 길어지더라도 완전하게, 그 외는 간결하게. **사용자 발화는 원래 표현에 가깝게 보존**하고, 어시스턴트 자신의 설명·추론은 결론과 산출물 수준으로 압축한다(단 6항목을 누락하지 않는 선에서).

**공식 문구 (원문 대조 2026-09-25, "Tell the model what to preserve in compaction summaries" 절)** — 위 목록은 요지이고, 투입하는 것은 이 블록이다(`neos/coding/prompts/official.py`, 테스트가 바이트 일치를 건다):

```text
Summarize the transcript inside <summary></summary> tags. Include relevant information in the summary such that this conversation will be continued by a new context window without needing to redo work or be reprovided with relevant constraints or context. Be sure to preserve: (1) any difficulties or problems that came up, and how they were handled or resolved; (2) any possibilities, options, or approaches that were raised, tried, or set aside, and why; (3) anything that was asked for, decided, agreed, ruled out, or established as a preference, constraint, or boundary — stated exactly; (4) exactly where things stand now — what has been covered, settled, or completed so far; (5) anything still open, unresolved, promised, or expected to happen next; (6) specific details that would be hard to reconstruct — names, numbers, dates, exact wording, links or references — kept exactly. Be complete on these even at the cost of length; keep everything else concise. Weight the two voices differently: keep what the user said, asked for, shared, or established carefully and close to their own words; your own explanations and reasoning can be condensed much further, to what they concluded or produced — as long as nothing in the six items above is dropped.
```

> ⚠️ 원문 대조에서 발견: **P-02 초안도 공식 문구와 다르다**(공식은 "If, while working or testing, you find …" 로 시작하고 여러 곳의 표현이 다르다). P-02 를 투입할 때 같은 대조를 거친다.

---

### P-06. low effort에서의 검색 유도 (P2)

**배경**
`low` effort에서는 검색·검색증강 도구 호출 빈도가 Fable 5보다 낮고 기억에 의존해 답하는 경향이 있다.

**변경 사항**
1. 1차 대응: 해당 턴만 effort를 올린다(R-05의 mid-conversation 변경 사용). 전체 대화를 올리지 않는다.
2. 2차 대응: 시스템 프롬프트에 검증 넛지 추가.

**프롬프트 초안**

```
When a query centers on a name you don't confidently recognize — or recognize
from a fast-moving area like AI models and developer tools, where the landscape
shifts within months — the name itself is what needs verifying. Search before
answering, and include the name exactly as the user wrote it in at least one
query alongside any reformulations. Partial background is what makes a stale
answer sound authoritative, so familiarity is not a reason to skip the search.
```

---

### P-07. 기존 억제성 문구 제거 (P2)

**배경**
이전 모델들은 불릿·볼드를 과하게 쓰고 작업 중 보고를 과하게 했기 때문에, 이를 누르는 규칙이 프롬프트에 남아 있는 경우가 많다. Fable 5.1은 반대 방향으로 기울어 볼드·헤더·리스트·인용부호를 덜 쓴다.

**변경 사항**
1. 안티포매팅 문구를 제거하고, **언제 어떤 포맷이 적절한지** 규정하는 규칙으로 교체한다: 요청이 있거나 내용이 다면적이어서 명확성에 도움이 될 때 리스트를 쓰고, 최소 포맷을 명시적으로 요청받으면 그대로 따르며, 대화적·개인적 맥락에서는 평문을 유지.
2. 중간 보고를 금지하는 문구는 R-04에 따라 제거한다.
3. 산문이 조밀하게 느껴지는 경우(사용자 대면 리포트 생성 에이전트 등)에만 간단히: `Please remove all mannered prose.`
4. 문서 요약 에이전트가 있다면, 원문 표현을 인용 표시 없이 재현하는 경향이 있으므로 **올바른 응답 예시 1건**(사용자 요청 + 응답 + 왜 올바른지 설명)을 시스템 프롬프트에 넣는다. 예시 안의 도구 호출 표기는 **실제 도구 이름**으로 바꿔 모델이 템플릿으로 읽게 한다.

---

## 3. 비목표 (이번 변경에서 제외)

- Fable 5 → 5.1 프롬프트 전면 재작성. 기존 프롬프트는 대체로 그대로 동작한다.
- vision/차트 분석 경로. 해당 기능을 쓸 경우에만 별도 티켓으로: 원본 이미지와 PIL/OpenCV가 있는 컨테이너를 에이전트에 붙이거나, 최소한 지정 영역을 잘라 확대해 반환하는 crop 도구를 제공한다(대부분의 이득이 crop 도구만으로 확보됨).
- 모델 라우팅 정책 변경.

---

## 4. 최종 수용 체크리스트

- [ ] 연속 요청의 prefix가 byte-identical임을 검증하는 테스트 통과 (R-01)
- [ ] drop_block 진단 실행 시 `input_transformations` 없음 (R-01)
- [ ] turn-scoped system message 누적 시 입력 토큰 증가 없음 (R-02)
- [ ] subagent 실행 중 lead가 작업을 계속할 수 있음 (R-03)
- [ ] 비어 있지 않은 thinking 블록이 상태 라인으로 노출됨 (R-04)
- [ ] effort가 역할별 설정값으로 주입되고 기본값이 `high` (R-05)
- [ ] `refusal` 분기 처리 + base64 필터링 미들웨어 존재 (R-06)
- [ ] 클라이언트 compaction이 "요약 1건 + 새 user 턴" 형태 (R-07)
- [ ] `xhigh`/`max` 경로에서 `max_tokens` 여유 산정 및 note append (R-08)
- [ ] P-01, P-02 블록이 코드 수정 에이전트 시스템 프롬프트에 포함 (P-01, P-02)
- [ ] 배칭 넛지가 매 tool_result 턴에 새 복사본으로 append (P-03)
- [ ] 부분 편집 지시 포함 (P-04)
- [ ] 클라이언트 compaction 유지 시 6항목 보존 지시 적용 (P-05)
- [ ] 기존 안티포매팅·보고억제 문구 grep 후 제거 (P-07)
