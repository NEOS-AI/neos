# Q14 에이전트 브라우저 — 설계 (2026-10-01)

> **지위:** Q14a 착지(플래그 off, development 전용). 설계와 코드가 어긋나면 코드가 이긴다.
> 상위: [로드맵 §1 Q 행](DEEP_ANALYSIS_HARNESS_ROADMAP.md) · [dots 분석 §4.2 Q14 · §5 D6](OPENAI_DOTS_ANALYSIS_260930.md).
> 결정 W1~W12 는 위임받아 Claude 가 골랐다(Q2·Q4b·Q6 과 같은 방식). 사람이 뒤집을 수 있다.
> ⚠️ **선행 둘 중 하나가 닫혀 있다.** Q6 은 착지했지만 관리형 샌드박스 **B2 게이트는 통과하지 않았다**
> ([B2 설계 메모](MANAGED_SANDBOX_B2_DESIGN_260915.md)). 그래서 Q14a 는 브라우저를 샌드박스 안이 아니라
> **백엔드 호스트**에 두고, 그 대가로 development 밖에서는 열리지 않는다(W1·W3).

## 1. 무엇을 사는가 — 그리고 사지 않는 것

dots F1 — "에이전트의 컴퓨터에는 브라우저가 있다". 오늘 코딩 에이전트는 `web_fetch.v1`(허용 호스트의 GET 한 번,
텍스트만)뿐이다. JS 로 그려지는 페이지·폼·로그인 뒤의 페이지는 읽지 못한다. Playwright 는 CLI 의
`WebLookUpAgent` 에만 있다.

Q14a 가 착지시키는 것은 **계약과 가드**다:

| 산다 | 사지 않는다 |
|---|---|
| 도구 둘(`browser.v1` · `browser_fill_secret.v1`)과 그 게이트·위험 등급 | 운영(production) 브라우징 — B2 전에는 열지 않는다 |
| 페이지가 내는 **모든 요청**에 `web_fetch.v1` 의 판정을 거는 출구 | 임의 호스트 브라우징 — 허용 목록은 `web_fetch_hosts` 그대로 |
| Q6 금고를 통한 로그인(값은 모델에 보이지 않는다) | 비밀별 출처 묶임(Q14b, 마이그레이션 필요) |
| 태스크마다 휘발 세션 · 상한 · 정리 | 스크린샷·비전 · 다운로드·업로드 · 여러 탭 · 콘솔 |
| 꺼져 있으면 오늘과 바이트가 같다 | DA 조사 경로의 브라우저 — **D6 이 막는다**(§5) |

## 2. 결정

| # | 결정 | 이유 |
|---|---|---|
| **W1** | **어디서 도는가: 백엔드(코딩 워커) 프로세스의 headless Chromium.** 샌드박스 안이 아니다. 브라우저가 없거나 뜨지 않으면 `browser_unavailable` 이고, 다른 경로(예: `web_fetch`)로 대신 돌지 않는다 | Docker 샌드박스는 `network=none` 이고 관리형(B2)은 게이트 전이다. 샌드박스에 네트워크를 여는 것은 D6·§9("샌드박스 코드는 네트워크 없음")와 부딪힌다. 호스트에 두고 **브라우저 쪽 네트워크를 끊는**(W2) 편이 경계를 하나로 만든다. 📌 **신뢰 경계를 정직하게 적는다:** 렌더러 탈출 취약점은 백엔드 호스트 사용자 권한에 닿는다. Chromium 샌드박스는 켠다(`chromium_sandbox=True` — 못 켜면 브라우저가 없다). 이것이 W3 의 이유다 |
| **W2** | **Chromium 에는 네트워크가 없다. 호스트가 모든 요청을 대신 받는다.** `context.route("**/*")` 로 하위 리소스·리다이렉트·폼 제출까지 전부 받아 `web_fetch.v1` 의 판정 함수(`_web_fetch_safety_reason` — 허용 호스트 · 사용자 정보 · 비밀 이름 질의 · 풀린 주소 전부 공개)를 **그대로** 부르고(사본 없음), 통과하면 `_PinnedHTTPSHandler` 로 IP 를 고정해 **한 홉만** 가져와 `route.fulfill` 한다. 3xx 는 따라가지 않고 브라우저에 준다 — 다음 요청이 다시 판정받는다. 심층 방어: `--host-resolver-rules=MAP * ~NOTFOUND` · 죽은 프록시(`127.0.0.1:9`) · 웹소켓은 서버에 잇지 않고 닫는다 · 서비스 워커 차단 · 다운로드 off · 팝업은 열리는 대로 닫고 대화상자는 dismiss | `web_fetch` 보다 **약하지 않게**: 같은 함수, 같은 IP 고정, 리다이렉트 매 홉 재판정. `route.continue_()` 를 쓰면 Chromium 이 이름을 다시 풀어 DNS rebinding 틈이 생긴다 — fulfill 은 그 틈이 없다. 실제 Chromium 스모크(§6)가 이름 풀이 없는 브라우저에 fulfill 로 페이지가 뜨고, `10.0.0.1` 이미지가 막히는 것을 확인했다 |
| **W3** | **development 밖에서는 `coding_model.browser.allow_outside_development` 를 운영자가 명시해야 켜진다.** 어디서든 허용 호스트가 비었거나, IP 리터럴·와일드카드·한 단계 접미(`.com`)가 있거나, 운영자 allow 목록(`approval_allow_tools`·`approval_always_allow`)이 브라우저 도구를 담으면 **기동하지 않는다.** 팩토리(`build_browser_sessions`)가 환경 조건을 다시 본다 | S10·I7 과 같은 fail-closed 모양 — B2 가 없다는 사실을 설정 이름이 말하게 한다. 허용 목록은 `web_fetch_hosts` **하나를 같이 쓴다** — 검토자가 하나다 |
| **W4** | **도구 둘, 둘 다 `COMMAND`.** `browser.v1`(action: navigate · snapshot · click · type · close) · `browser_fill_secret.v1`. background(Q1)에서는 천장이 `policy_mode_ceiling` 으로 DENY 한다. 목록에서 숨기지는 않는다 | 나눈 이유는 **Q2 사용자 규칙이 도구 이름으로 맞추기 때문**이다 — 소유자가 탐색은 allow 하고 로그인은 계속 승인받게 할 수 있어야 한다(`execute.v1` 에는 argv 접두가 있지만 브라우저에는 없다). 스냅샷도 COMMAND 인 것은 dots Q14 행("COMMAND 이상")과 이름 하나에 위험 하나라는 레지스트리 규칙 때문이다. 숨기지 않는 것은 Q1 이 background 전용 도구 목록·오버레이를 두지 않은 결정(K9 규율)을 따른 것이다 — `execute.v1` 과 같은 대우 |
| **W5** | https 만, 메서드는 **GET·HEAD·POST 만**. 요청 본문(`max_request_body_bytes`)·응답(`max_response_bytes`)·컨텍스트당 요청 수(`max_requests`)에 상한 | 로그인 폼은 POST 다. PUT·DELETE·PATCH 는 사이트를 바꾸는 API 호출이고 Q14a 에서 필요한 근거가 없다 — 넓히는 것은 증분으로(Q16 의 위협 모델 방식) |
| **W6** | **태스크마다 휘발 컨텍스트 하나**(`browser.new_context()` — 프로필·쿠키 없음), 페이지 하나. 루프가 terminal 에서 닫고, 루프의 매 단계와 매 브라우저 호출이 `sweep` 으로 쉬었거나(`idle_timeout_sec`) 오래 산(`max_lifetime_sec`) 세션을 닫는다. 프로세스당 `max_contexts`, 태스크당 `max_navigations`. 세션은 **체크포인트에 싣지 않는다** — 다른 워커가 이어받거나 재시작하면 페이지가 없다(`browser_no_page` → 다시 navigate) | 쿠키가 태스크를 건너면 한 태스크의 로그인이 다음 태스크의 것이 된다. 내구 상태로 만들면 쿠키(=자격증명)가 체크포인트에 들어간다 |
| **W7** | **로그인은 Q6 경유만.** `browser_fill_secret.v1 {ref, secret: "secret://name", origin}` — 소유자 금고에서 풀어(루프의 `_secret_lookup` 그대로) 칸에 넣고, 값은 돌려주지 않는다. 게이트는 Q6 의 판정 **하나**(`carries_secret_refs`)를 이 도구까지 넓혀 S7(사람 승인 또는 **`browser_fill_secret.v1` 에 대한** 소유자 allow)·S8(자식 거절)을 그대로 탄다. 브로커가 꺼져 있으면 검증기가 거절한다. `origin` 은 지금 페이지의 출처 · 그 칸이 사는 문서의 출처 · 허용 호스트, 셋 다와 같아야 한다 | 판정을 복사하면 한쪽만 고쳐진다. 승인 카드는 `origin` 과 `secret_ref` 를 보여 준다 — 사람이 **어디에** 넣는지를 승인한다. Q6 의 `env_name` 묶임(S3)은 브라우저에 쓰지 않는다: 그 자리에 해당하는 것은 출처 묶임이고, 그것은 금고 스키마가 바뀌어야 한다(Q14b) |
| **W8** | **입력한 비밀은 그 출처 밖으로 나가지 못한다.** 세션이 입력한 값이 다른 출처로 가는 요청의 URL·본문(원문 · URL 인코딩 · JSON 이스케이프 · 폼 디코딩)에 있으면 막는다(`browser_secret_egress_denied`). 같은 출처로의 POST 는 로그인 그 자체라 통과한다 | 페이지 스크립트가 비밀번호 칸을 읽어 다른 허용 호스트로 보내는 길. 허용 목록이 1차 경계이고 이것은 2차다. ⚠️ 스크립트가 값을 변형(base64·해시·쪼개기)하면 놓친다 — 그 경우의 경계는 허용 목록뿐이다 |
| **W9** | **모델에게 가는 모든 문자열을 가린다.** 스냅샷 · 제목 · URL 을 (a) 세션이 입력한 값(`ResolvedSecrets.scrub_text` — 값 자체 + `redact.py` 규칙)과 (b) 페이지의 비밀번호 칸 값(4자 이상, `<masked:password>`)으로 가린 **뒤** 자른다. 오류는 **코드만** 싣고 드라이버·페이지 문구는 버린다. 콘솔 메시지는 돌려주지 않는다. 입력한 값은 컨텍스트가 닫힐 때까지 **프로세스 메모리에만** 산다(체크포인트·원장·이벤트에 없음) | Q6 의 "한 호출 동안만"을 넓힌 것이다: 값은 이미 페이지(DOM)가 들고 있으므로 다음 스냅샷도 그것으로 가려야 한다. 가린 뒤 자르므로 경계에 걸친 비밀이 없다. Chromium 은 접근성 트리에서 비밀번호 값을 이미 가린다 — (b)는 심층 방어다 |
| **W10** | 페이지 텍스트는 untrusted 다. `aria_snapshot(mode="ai")` 를 `snapshot_max_chars` 로 자르고 `_wrap_untrusted_web_content` 로 감싼다(페이지가 구분자를 흉내 내면 중화된다). 요소는 스냅샷의 `[ref=eN]` 으로만 가리킨다 — CSS·XPath 선택자는 받지 않는다 | `web_fetch` 와 같은 감싸기 하나. 선택자 문자열을 받지 않으면 모델(=페이지에 조종될 수 있는 쪽)이 `aria-ref=` 밖의 선택자 엔진을 부를 수 없다 |
| **W11** | **꺼져 있으면 오늘과 바이트가 같다.** 도구 목록(모든 phase · deferred 선언 · `search_tools.v1`) · 레지스트리 이름 · 검증 사유(`policy_unknown_tool`) · 루프가 실행기를 부르는 모양(`browser` 인자 없음) · 이벤트 어휘(새 kind 없음) · 프롬프트(바뀐 줄 없음). 마이그레이션도 없다(079 는 쓰지 않았다) | S9(트랙 I 의 방법) — 켜는 커밋만 경계가 된다. 테스트는 브라우저 스펙을 뺀 레지스트리와 표면 전체를 JSON 으로 비교한다 |
| **W12** | **자식과 DA 조사 경로에는 없다.** 실행기는 **부모 루프가 넘긴 손잡이**(`BoundBrowser`, 그 태스크의 세션에만 닿는다)로만 브라우저에 닿는다. 자식 포트 · DA 조사 포트 · 추측 실행(prefetch) · 읽기 전용 배치는 손잡이를 넘기지 않으므로 거기서는 `browser_unavailable` 이다. 그 위에 서브에이전트 스펙과 `research_gate.CODING_TOOLS` 어디에도 이름이 없다(테스트가 플래그 on 에서 고정) | 자식은 승인할 사람에게 닿지 못하고(CHILD-GATE), 세션은 부모 태스크의 것이다 — 자식이 쓰면 부모가 로그인한 쿠키에 닿는다. DA 는 **D6**: retrieval 은 `fetch.py` 독점이다. DA 가 에이전트 산출물을 쓸 때도 바이트는 `fetch.py` 로 다시 들어온다(dots §5) |

### 거절·실패 코드

| 코드 | 언제 | 성격 |
|---|---|---|
| `policy_unknown_tool` | 플래그가 꺼져 있다 — 오늘과 같은 사유(W11) | 검증 거절 |
| `policy_browser_secret_disabled` | 브로커(`coding_model.secret_broker`)가 꺼진 채 `browser_fill_secret.v1` | 검증 거절 |
| `policy_browser_use_fill_secret` | `type` 의 text 가 `secret://` 참조다 | 검증 거절 |
| `policy_mode_ceiling` | background 태스크(Q1) | 게이트 DENY |
| `policy_secret_ref_unapproved` · `policy_secret_ref_child` | Q6 S7 · S8 그대로 | 게이트 DENY |
| `policy_web_fetch_host_denied` | 최상위 navigate 가 허용 목록 밖 · fill 출처가 허용 목록 밖 | 도구 결과 `denied` |
| `web_fetch_ssrf` · `web_fetch_userinfo` · `web_fetch_blocked` | 최상위 navigate 가 web_fetch 판정에 걸렸다 | 도구 결과 `error` |
| `browser_unavailable` | 손잡이가 없다(자식·DA·prefetch) · Chromium 이 뜨지 않는다 | `denied` / `error` |
| `browser_no_page` | 아직(또는 다시) navigate 하지 않았다 | `denied` |
| `browser_navigation_cap` · `browser_capacity` | 태스크당 navigate 상한 · 프로세스당 세션 상한 | `denied` |
| `browser_secret_origin_mismatch` · `browser_secret_unavailable` · `secret_not_found` · `secret_store_unavailable` | W7 | `denied`(마지막만 `error`) |
| `browser_timeout` · `browser_action_failed` | 드라이버 실패 — 문구 없이 코드만(W9) | `error` |

페이지가 낸 요청이 막힌 것은 도구를 실패시키지 않는다. 결과의 `blocked_requests` 에 **사유 코드별 개수만** 싣는다
(막힌 URL 은 페이지가 고른 문자열이므로 싣지 않는다): `policy_web_fetch_host_denied` · `web_fetch_ssrf` ·
`web_fetch_userinfo` · `web_fetch_blocked` · `browser_scheme_denied` · `browser_method_denied` ·
`browser_request_too_large` · `browser_response_too_large` · `browser_secret_egress_denied` · `browser_request_cap` ·
`browser_fetch_failed`.

## 3. 구조

```text
DurableCodingLoop ──(부모의 도구 단계만)── executor.execute(..., browser=sessions.bind(task_id), secrets=lookup)
                                              │
                         neos/coding/browser/session.py  BrowserSessions ─ 태스크당 _Session(컨텍스트·페이지·입력한 비밀)
                                              │                 │
                         playwright_driver.py (Chromium, 네트워크 없음)   egress.py ─ 요청마다 web_fetch 판정 → IP 고정 한 홉
                                              └── context.route ──────────┘
```

드라이버 계약(`driver.py`)의 메서드는 Playwright **실제 호출 하나씩**에 대응한다(각 줄 주석). 테스트의 가짜는
그 계약만 구현한다 — 실제 API 에 없는 필드를 지어내지 않게("가짜는 없는 필드를 지어낼 수 있다").

## 4. 표면

- 설정(`coding_model.browser`, 기본 전부 off):

  ```yaml
  coding_model:
    web_fetch_hosts: [docs.example.com]   # 브라우저도 이것 하나를 쓴다 -- 비면 켜지 않는다
    browser:
      enabled: false
      allow_outside_development: false    # B2 전 운영자 동의. development 면 필요 없다
      navigation_timeout_sec: 15
      action_timeout_sec: 10
      max_navigations: 30                 # 태스크당
      max_requests: 500                   # 컨텍스트당(하위 리소스 포함)
      max_response_bytes: 5242880
      max_request_body_bytes: 1048576
      snapshot_max_chars: 20000
      idle_timeout_sec: 300
      max_lifetime_sec: 1800
      max_contexts: 2                     # 프로세스당
  ```
- 로그인: `coding_model.secret_broker` 와 `NEOS_SECRET_BROKER_KEY`(Q6). 새 환경 키는 없다.
- API·마이그레이션·이벤트 kind: **없다.** 도구 결과는 기존 `tool.completed` 에 실린다.
- 실행 조건: `playwright install chromium`(Playwright 1.61 의 빌드). 없으면 `browser_unavailable`.

## 5. 남은 것

- **Q14b** — 비밀별 **출처 묶임**(금고 행에 허용 출처, 마이그레이션) · 소유자 allow 규칙을 출처까지 좁히기 ·
  프롬프트에 비밀 이름 목록 · 콘솔 요약 · 스크린샷(비전) · PUT/PATCH/DELETE · 여러 탭 · 다운로드·업로드
- **Q14c (B2 의존)** — 브라우저를 **관리형 샌드박스 안으로** 옮긴다. 필요한 것: B2 게이트(할당 평면 배선 ·
  게스트 이미지 · 실계정 smoke · 보안 검토, B2 메모 "남은 일") + 관리형 profile 의 egress 를 이 출구(W2)와 같은
  판정으로 여는 길 + sandboxd 의 비밀 채널(Q6b). 그때 `allow_outside_development` 를 지우고 운영 경계를
  B2 로 옮긴다. **그 전까지 운영 브라우징은 닫혀 있다**
- 알려진 한계(경계가 아니다): 출구는 HTTP/1.1 단일 홉이라 느리다 · 응답을 통째로 받아 fulfill 한다(스트리밍 없음) ·
  여러 `Set-Cookie` 는 줄바꿈으로 이어 넘긴다(스모크는 쿠키 로그인을 확인하지 않았다) · 실패·취소된 태스크의 세션은
  terminal 이 아니라 sweep 이 닫는다 — 루프가 한 단계도 돌지 않으면 프로세스 종료까지 산다(`max_contexts` 가 상한) ·
  비밀번호 칸 가리기는 메인 프레임만 본다 · W8 은 변형된 값을 모른다

## 6. 검증

- `tests/coding/test_agent_browser.py`(가짜 드라이버) · `tests/coding/loop/test_agent_browser_loop.py`(실제 루프)
- `tests/coding/test_agent_browser_smoke.py` — 실제 Chromium. `NEOS_BROWSER_SMOKE=1` 일 때만. 네트워크를 쓰지 않는다:
  호스트 쪽 fetch 는 통조림 사이트이고 Chromium 은 이름을 풀지 못한다. 2026-10-01 로컬에서 Playwright 1.61 + 설치돼
  있던 Chromium 빌드 1194(`NEOS_BROWSER_SMOKE_CHROMIUM`)로, Chromium 샌드박스 on·off 둘 다 통과: fulfill 로 페이지가
  뜬다 · `aria-ref` 로 칸을 채운다 · 로그인 POST 가 호스트를 거친다 · `10.0.0.1` 이미지는 막힌다 · 비밀번호는
  어느 결과에도 없다. Playwright 1.61 자신의 빌드(1228)로는 아직 돌리지 않았다
