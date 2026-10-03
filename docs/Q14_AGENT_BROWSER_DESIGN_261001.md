# Q14 에이전트 브라우저 — 설계 (2026-10-01)

> **지위:** Q14a 착지 · **Q14b 착지**(2026-10-02 — 비밀별 출처 묶임 + 견고성 셋, §7) ·
> **Q14c 부분 착지**(2026-10-02 — 관리형 샌드박스 안의 브라우저: 드라이버·선 규약·guest·설정 검증, 플래그 off ·
> **아직 켤 수 없다**: guest 채널 배선이 B2 에 묶여 있다, §8). 플래그 off, development 전용.
> 설계와 코드가 어긋나면 코드가 이긴다.
> 상위: [로드맵 §1 Q 행](DEEP_ANALYSIS_HARNESS_ROADMAP.md) · [dots 분석 §4.2 Q14 · §5 D6](OPENAI_DOTS_ANALYSIS_260930.md).
> 결정 W1~W12(Q14a)·X1~X7(Q14b)·MB1~MB8(Q14c)은 위임받아 Claude 가 골랐다(Q2·Q4b·Q6 과 같은 방식). 사람이 뒤집을 수 있다.
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
| Q6 금고를 통한 로그인(값은 모델에 보이지 않는다) | 비밀별 출처 묶임(Q14b, 마이그레이션 필요) → **Q14b 착지**(§7 X1) |
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
| **W7** | **로그인은 Q6 경유만.** `browser_fill_secret.v1 {ref, secret: "secret://name", origin}` — 소유자 금고에서 풀어(루프의 `_secret_lookup` 그대로) 칸에 넣고, 값은 돌려주지 않는다. 게이트는 Q6 의 판정 **하나**(`carries_secret_refs`)를 이 도구까지 넓혀 S7(사람 승인 또는 **`browser_fill_secret.v1` 에 대한** 소유자 allow)·S8(자식 거절)을 그대로 탄다. 브로커가 꺼져 있으면 검증기가 거절한다. `origin` 은 지금 페이지의 출처 · 그 칸이 사는 문서의 출처 · 허용 호스트, 셋 다와 같아야 한다 | 판정을 복사하면 한쪽만 고쳐진다. 승인 카드는 `origin` 과 `secret_ref` 를 보여 준다 — 사람이 **어디에** 넣는지를 승인한다. Q6 의 `env_name` 묶임(S3)은 브라우저에 쓰지 않는다: 그 자리에 해당하는 것은 출처 묶임이고, 그것은 금고 스키마가 바뀌어야 한다(Q14b) → **081 로 착지**(§7 X1) |
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
| `secret_origin_mismatch` | 비밀의 `browser_origins` 에 그 출처가 없다(비었으면 늘) — Q14b X1 | `denied` |
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
  (Q14b 가 금고에 컬럼 하나 — 081 `user_secrets.browser_origins` — 와 금고 API 필드 하나를 더했다. 이벤트 kind 는 여전히 없다)
- 실행 조건: `playwright install chromium`(Playwright 1.61 의 빌드). 없으면 `browser_unavailable`.

## 5. 남은 것

- ~~**Q14b** — 비밀별 출처 묶임~~ → **착지**(§7). 남은 것(Q14c 이후 또는 증분): 소유자 allow 규칙을 출처까지 좁히기(X7 —
  Q2 규칙 테이블 변경) · 프롬프트에 비밀 이름 목록 · 콘솔 요약 · 스크린샷(비전) · PUT/PATCH/DELETE · 여러 탭 · 다운로드·업로드
- **Q14c (B2 의존)** — 착지한 것과 남은 것은 **§8**. 아래는 Q14a 때 적은 원래 문장이다.
  브라우저를 **관리형 샌드박스 안으로** 옮긴다. 필요한 것: B2 게이트(할당 평면 배선 ·
  게스트 이미지 · 실계정 smoke · 보안 검토, B2 메모 "남은 일") + 관리형 profile 의 egress 를 이 출구(W2)와 같은
  판정으로 여는 길 + sandboxd 의 비밀 채널(Q6b). 그때 `allow_outside_development` 를 지우고 운영 경계를
  B2 로 옮긴다. **그 전까지 운영 브라우징은 닫혀 있다**
- 알려진 한계(경계가 아니다): 출구는 HTTP/1.1 단일 홉이라 느리다 · 응답을 통째로 받아 fulfill 한다(스트리밍 없음) ·
  W8 은 변형된 값을 모른다 · 세션은 프로세스 지역이라 **다른 워커**가 실패·취소를 처리하면 그 세션은 sweep 이 닫는다(X5).
  Q14a 가 적었던 셋 — 여러 `Set-Cookie`(X4, 실제 Chromium 으로 확인) · 실패·취소 세션(X5) · 메인 프레임만 가리기(X6) — 은 §7 에서 닫았다

## 6. 검증

- `tests/coding/test_agent_browser.py`(가짜 드라이버) · `tests/coding/loop/test_agent_browser_loop.py`(실제 루프)
- `tests/coding/test_agent_browser_smoke.py` — 실제 Chromium. `NEOS_BROWSER_SMOKE=1` 일 때만. 네트워크를 쓰지 않는다:
  호스트 쪽 fetch 는 통조림 사이트이고 Chromium 은 이름을 풀지 못한다. 2026-10-01 로컬에서 Playwright 1.61 + 설치돼
  있던 Chromium 빌드 1194(`NEOS_BROWSER_SMOKE_CHROMIUM`)로, Chromium 샌드박스 on·off 둘 다 통과: fulfill 로 페이지가
  뜬다 · `aria-ref` 로 칸을 채운다 · 로그인 POST 가 호스트를 거친다 · `10.0.0.1` 이미지는 막힌다 · 비밀번호는
  어느 결과에도 없다. Playwright 1.61 자신의 빌드(1228)로는 아직 돌리지 않았다
- Q14b(2026-10-02, 같은 Chromium 1194, Chromium 샌드박스 on·off 둘 다): 위 하나 + **쿠키 둘 로그인**(`Set-Cookie` 두 줄이
  `_response_headers` → fulfill 을 지나 다음 요청에 둘 다 실린다) · **iframe 안 비밀번호 가리기** 셋 다 통과.
  `tests/coding/test_agent_browser_origins.py`(가짜 드라이버·run service) · `tests/coding/test_secret_store_origins.py`(Postgres·081)

## 7. Q14b — 비밀별 출처 묶임과 견고성 (2026-10-02)

결정 X1~X7 은 위임받아 Claude 가 골랐다. Q14a 의 "남은 것" 중 금고 스키마가 필요한 하나와, Q14a 보고가 남긴
견고성 셋을 닫는다.

| # | 결정 | 이유 |
|---|---|---|
| **X1** | **비밀마다 입력될 수 있는 https 출처 목록**(`user_secrets.browser_origins TEXT[]`, 081, 최대 8). `browser_fill_secret.v1` 은 금고에서 푼 **뒤**, 입력하기 **전에** `origin ∈ browser_origins` 를 본다 — 아니면 `secret_origin_mismatch`(denied). **기본은 빈 배열이고 빈 배열은 어디에도 아니다**(fail closed): 077 의 기존 행은 브라우저에서 쓰이지 않는다. 출처는 도구 입력의 `origin` 과 **같은 함수**(`registry.browser_origin`)로 정규화하고 DNS 이름만 받는다(IP·와일드카드·한 단계 이름 거절) | S3 의 브라우저판 — 어디에 쓸지는 **비밀의 주인**이 정한다. W7 의 출처 검사(페이지·칸·허용 호스트)는 "모델이 말한 출처가 진짜인가"이고, X1 은 "주인이 거기를 허락했는가"다. 허용 목록에 호스트가 둘 이상이면 W7 만으로는 GitHub 비밀번호가 docs 사이트 로그인 칸에 들어갈 수 있다. 같은 정규화 함수라 비교가 문자열 같음 하나다. `env_name`(S3)은 그대로라 `execute.v1`·Q11 커넥터는 바뀌지 않는다 |
| **X2** | **`PUT /coding/secrets/{name}` 은 행을 통째로 바꾼다** — `browser_origins` 를 빼면 묶임이 비워진다. `GET` 이 출처를 돌려준다(값은 여전히 없다) | PUT 의 뜻 그대로. 값을 바꾸는(회전) 사람이 출처를 다시 말하게 한다 — 빠뜨리면 닫히는 쪽이다(fail closed). 부분 갱신(PATCH)은 필요가 생기면 연다 |
| **X3** | **출처를 AAD 에 싣는다** — 비어 있지 않으면 `neos-secret:{user}:{name}:origins=a,b`. 비면 077 의 AAD 그대로 | 키 없이 DB 만 쓸 수 있는 쪽이 자기 출처를 끼워 넣으면 그 비밀은 **풀리지 않는다**(S5 의 "행을 옮기면 안 열린다"를 출처까지). 빈 경우를 그대로 두어 기존 행을 다시 봉인하지 않는다 — 081 은 컬럼만 더한다 |
| **X4** | **여러 `Set-Cookie` 는 지금처럼 줄바꿈으로 잇는다 — 실제 API 를 확인했다.** Python `route.fulfill(headers=)` 는 `Dict[str, str]` 만 받고(배열 형식 없음), Playwright 1.61 드라이버의 Chromium 라우트(`crNetworkManager.fulfill`)가 `splitSetCookieHeader` 로 `\n` 을 쿠키 한 줄씩으로 되돌린다. 실제 Chromium 스모크가 쿠키 둘 로그인 뒤 다음 요청에 둘 다 실리는 것을 확인한다 | "가짜는 없는 필드를 지어낼 수 있다" — 추측하지 않고 설치된 드라이버 소스를 읽었다. 변이(`, ` 로 잇기)는 쿠키 하나만 남겨 스모크가 잡는다. ⚠️ 드라이버를 올리면 이 스모크를 다시 돌린다 |
| **X5** | **실패·취소는 그 자리에서 세션을 닫는다.** run service 의 `fail_active_run` 과 `_cancel_active_run`(정지·safe point 취소·실행 중 취소 셋이 모두 지난다)이 `loop.close_task_browser(task_id)` 를 부른다(`cancel_active_child_for_task` 와 같은 `getattr` 모양). 닫기 실패는 실패·취소를 막지 않는다. INTERRUPT_NOW 는 terminal 이 아니므로 닫지 않는다 | Q14a 는 다음 루프 단계의 sweep 에 기댔고, 루프가 다시 돌지 않는 태스크(실패·취소)의 세션 — 로그인한 쿠키 — 이 `idle_timeout_sec` 까지 살았다. 세션은 **프로세스 지역**이라 이 훅은 그 세션을 든 워커에서만 닿는다; 다른 프로세스(API 의 정지 요청 등)가 처리하면 그 워커의 sweep 이 여전히 상한이다 — 그래서 sweep 은 지우지 않는다 |
| **X6** | **비밀번호 칸 가리기는 모든 프레임을 본다**(`page.frames` 마다 `frame.eval_on_selector_all`). 한 프레임이라도 읽지 못하면 스냅샷이 `browser_action_failed` 다 | 로그인 칸이 iframe 에 있는 사이트가 흔하다. `aria_snapshot(mode="ai")` 는 iframe 내용도 싣는다(스모크가 확인). 못 읽은 프레임을 "가렸다"고 치지 않는다 — W9 와 같은 쪽 |
| **X7** | **소유자 allow 규칙을 출처까지 좁히기는 하지 않았다.** Q2 규칙은 `(effect, tool, argv_prefix)` 로 유일하고 `argv_prefix` 는 `execute.v1` 전용이다. 출처를 실으려면 규칙 테이블에 칸(과 유일 인덱스)을 더해야 한다 — 남은 것 | `argv_prefix` 에 출처를 끼우는 것은 뜻을 겹친다. 그리고 X1 이 이미 대부분을 산다: `browser_fill_secret.v1` allow 규칙이 있어도 각 비밀은 주인이 적은 출처에만 들어간다 |

**꺼져 있으면:** 도구 표면 · 검증 사유 · 루프 호출 모양 · 이벤트 어휘는 Q14a 와 같다(W11 테스트 그대로 + Q14b 가 도구 입력
필드를 더하지 않았음을 고정). 브라우저가 꺼져 있으면 `close_task_browser` 는 아무 일도 하지 않는다. 081 은 브라우저 플래그와
상관없이 적용되는 **컬럼 하나**이고 `execute.v1`·커넥터 경로의 동작은 바꾸지 않는다. 자식·DA 경로는 여전히 브라우저가 없다(W12).

**변이 12/12** — 묶임 없는 비밀 거절 · 다른 출처 거절 · 소유자 교차(메모리·Postgres) · 081 기본값 · AAD 의 출처 ·
PUT 이 비운다 · 실패/취소 훅 · 정규화 · `Set-Cookie` 잇기(실제 Chromium) · 메인 프레임만(실제 Chromium).

## 8. Q14c — 관리형 샌드박스 안의 브라우저 (2026-10-02)

결정 MB1~MB8 은 위임받아 Claude 가 골랐다. 사람이 뒤집을 수 있다.

**목적.** W1 이 정직하게 적은 구멍 — 렌더러 탈출이 **백엔드 호스트**에 닿는다 — 을 닫는 길을 연다. Chromium 을
태스크의 관리형 샌드박스(벤더 VM) 안에서 띄우면 탈출은 그 VM 에 닿는다.

**증거부터.** 이 트랙은 벤더 계정 없이 했다. 저장소에는 E2B·Modal SDK 바인딩이 없고(Protocol 만, Q6b C1),
관리형 코딩 provider 의 runtime 배선(`prepare_coding_intent` 호출자 · 어댑터 등록)도 아직 없어 factory 가
거절한다([B2 메모](MANAGED_SANDBOX_B2_DESIGN_260915.md) "남은 일"). 그래서 착지한 것은 **벤더와 무관한 절반**이다:
드라이버 · 선 위 규약 · 샌드박스 쪽 guest · 설정 검증 · 가드 동등성 시험 · 로컬 프로세스 + 실제 Chromium 스모크.
**벤더 위에서 돈다는 증거는 없다** — 아래 점검표(§8.4)가 그 증거를 만드는 순서다.

### 8.1 결정

| # | 결정 | 이유 |
|---|---|---|
| **MB1** | **샌드박스에도 네트워크를 열지 않는다. guest 가 페이지의 모든 요청을 선 위로 호스트에 넘기고, 호스트가 세션의 `serve` — W2 의 판정(`egress_refusal` → `_web_fetch_safety_reason`)과 IP 고정 한 홉 — 로 답한다.** 관리형 profile 은 `DENY_ALL` 그대로다. guest 는 **판정하지 않는다**: Chromium 은 샌드박스 안에서도 같은 `playwright_driver`(이름 풀이 실패 · 죽은 프록시 · 웹소켓 닫기)로 뜨고, route 마다 호스트에 묻는다. 답이 없거나 채널이 끊기면 `route.abort()`. **guest 는 페이지와 같은 신뢰 등급이다** — 렌더러를 쥔 공격자가 guest 도 쥔다고 본다. 그래서 guest 가 보낸 route 프레임은 모양을 검사한 뒤(깨진 base64 · 이상한 메서드 · 큰 머리 → abort) 페이지 요청과 **똑같이** 판정받고, guest 가 말하는 URL·출처·비밀번호 값은 가리기의 재료일 뿐 권한의 근거가 아니다(답의 타입이 틀리면 `browser_action_failed`) | 버린 대안: 관리형 profile 의 egress 를 허용 목록으로 열기(`outbound: allowlist`). (1) 벤더의 허용 목록은 이름 단위라 W2 가 하는 것 — 풀린 주소 전부 공개 · 사용자 정보 · 비밀 이름 질의 · 리다이렉트 매 홉 재판정 · DNS rebinding 을 막는 IP 고정 · 입력한 비밀의 출구(W8) — 을 표현하지 못한다. 판정이 둘이 되면 "고침은 한 호출부에만 도착한다". (2) 샌드박스에 네트워크를 여는 것은 D6·§9("샌드박스 코드는 네트워크 없음")와 부딪힌다 — 같은 샌드박스의 `execute.v1` 도 그 네트워크를 얻는다. (3) `profiles.py` 는 allowlist 를 쓰려면 벤더의 readback 을 요구하고 그 증거도 없다. 대가: 요청마다 벤더 중계 왕복이 하나 더 붙는다(느리다, §8.4 f) |
| **MB2** | **대신 돌지 않는다.** 샌드박스에 닿지 못하면(할당 없음 · 채널 실패 · hello 불일치 · 응답 없음) `browser_unavailable` 이다 — 호스트 Chromium 으로 내려가지 않는다. 팩토리는 `provider: managed` 인데 채널 opener 가 주입되지 않았으면 **기동을 거절한다**. 드라이버는 주인 태스크 없는 컨텍스트를 열지 않는다 | W1 의 "다른 경로로 대신 돌지 않는다"와 같다. 운영자가 managed 라고 적었는데 호스트에서 돌면 이 트랙의 목적이 조용히 사라진다 |
| **MB3** | **설정: `coding_model.browser.provider: host \| managed`, 기본 `host`.** `managed` 는 `sandbox.provider: managed` + `sandbox.managed.enabled` 를 요구하고, 본문 상한(`max_response_bytes`·`max_request_body_bytes`)을 8 MiB 로 묶는다(base64 + sandboxd 프레임 16 MiB). **W3 는 풀지 않는다** — development 밖에서는 managed 여도 `allow_outside_development` 가 필요하다. 팩토리가 평면 조건을 다시 본다 | 좁히기만. W3 를 지우는 것은 §5 대로 **B2 게이트를 통과한 뒤** 별도 커밋이다 — 오늘 managed 는 켤 수조차 없으므로 풀 이유도 없다. 기본값이 `host` 라 플래그가 꺼져 있거나 `provider` 를 적지 않은 배포는 오늘과 같다 |
| **MB4** | **관리형 브라우저에서 `browser_fill_secret.v1` 은 금고를 열기 전에 `browser_secret_channel_unavailable`(denied) 로 거절한다.** 드라이버가 `confidential_channel` 을 선언한다 — 호스트 `PlaywrightDriver` 는 참(값은 워커 메모리에서 같은 기계의 Playwright 파이프로만 간다), `ManagedBrowserDriver` 는 **거짓 고정**(설정 키 없음), 선언하지 않은 구현은 거짓으로 읽는다(`getattr(..., False)`). `type` 의 평문 입력은 그대로 된다 | 비밀을 넣으면 값이 `fill` 프레임에 실려 **벤더 exec 의 stdio 중계**를 지난다 — Q6b C1 이 sandboxd 에 대해 막은 바로 그 운반로다. 판정을 복사하지 않고 같은 규칙(운반로의 `confidential_channel`, fail closed, 여는 것은 증거를 단 코드 변경)을 드라이버에 적용했다. 금고를 열기 **전에** 거절하므로 복호화도 없다. 관리형 비밀 채널은 다른 트랙이 다룬다 — 이 트랙은 그것을 구현하지 않았다. ⚠️ 비밀이 아니어도 채널을 지나는 것: 페이지 본문 · 사이트가 준 쿠키(=세션 자격증명) · 모델이 `type` 한 평문. 관리형에서 이것들은 벤더 중계를 지난다 — 잔류 위험으로 §8.4 g 에 적었다 |
| **MB5** | **hello 가 먼저다.** guest 는 연결하자마자 `{"hello": {"protocol": 1, "bundle_digest": ..}}` 를 보내고, 호스트는 버전과 **guest bundle digest**(드라이버 계약 · guest · Playwright 드라이버 · 선 규약 · sandboxd 프레임 코덱, 다섯 파일의 바이트)가 자기 것과 같을 때만 무엇이든 보낸다. 다르거나 조용하면 `browser_unavailable` | sandboxd 의 bundle digest 와 같은 방식이다. 이것은 **버전 어긋남**을 잡는 것이지 보안 경계가 아니다 — guest 는 거짓말할 수 있다. 보안 쪽 고정은 B2 의 이미지 digest(`managed_image_unpinned`)다 |
| **MB6** | **선 위 규약: sandboxd 의 프레임 코덱을 그대로**(4바이트 길이 + JSON, 16 MiB) 쓰고, 채널은 **태스크마다 하나 = 컨텍스트 하나 = 페이지 하나**. 호스트 → guest 호출은 `driver.py` 메서드 하나씩(`open` · `goto` · `snapshot` · `password_values` · `element_origin` · `click` · `fill` · `press_enter` · `title` · `close`), guest → 호스트는 route 프레임. 답은 지금 페이지 URL 을 싣는다(계약의 `page.url` 이 동기라서). 오류는 `timeout`·`failed` **코드만**. guest 진입점은 `python3 -m neos.coding.browser.guest`(`BROWSER_GUEST_ARGV`) — 벤더 `open_stdio(ref, argv)` 로 sandboxd 와 **별개의** stdio 를 연다 | sandboxd 의 `exec` 은 한 번 돌고 끝나는 호출이라 오래 사는 브라우저를 싣지 못하고, 장기 프로세스 op(Q6b §5 의 가칭 `proc.*`)는 없다. 벤더 SDK 의 `open_stdio` 는 이미 argv 를 받으므로 두 번째 stdio 가 가장 작은 길이다. 코덱을 다시 쓰지 않은 것은 "고침은 한 호출부에만" 때문이다 |
| **MB7** | **수명은 세션이 정한다(W6·X5 그대로).** `sessions.close` → guest 에 `close` 호출 → 컨텍스트 닫힘 → guest 프로세스 종료. sweep 도 같은 길이다. 채널이 끊기면 기다리던 호출은 **그 자리에서** `browser_action_failed` 이고(시간 초과까지 기다리지 않는다) guest 는 답할 상대가 없는 호출을 취소하고 끝난다. 브라우저는 샌드박스를 **만들지도 지우지도 않는다** — 그것은 할당 평면의 일이다 | 브라우저 세션이 샌드박스 수명을 쥐면 두 번째 할당 원장이 생긴다(B2 메모가 한 번 되돌린 실수). 세션은 체크포인트에 싣지 않는다(W6) — 다른 워커가 이어받으면 페이지가 없다, 오늘과 같다 |
| **MB8** | **가드는 드라이버 밑으로 내려가지 않는다.** 출구 판정 · 비밀 출처 묶임(W7·X1) · 비밀 출구(W8) · 가리기(W9·X6) · 실패·취소 때 닫기(X5) · 자식·DA 거절(W12) · background 천장(W4) 은 세션·실행기·게이트에 있고, 드라이버는 그것들을 모른다. 그래서 동등성 시험은 같은 시나리오를 `host`(가짜 드라이버를 세션 바로 밑에)와 `managed`(같은 가짜를 선 너머 실제 guest 밑에) 둘로 돌려 **같은 답**을 요구한다 | 관리형 경로에 가드를 다시 쓰면 둘이 갈라진다. 드라이버 계약에 생긴 변화는 둘뿐이다: `new_context(serve, *, task_id)` 와 `confidential_channel` 선언 |

**거절·실패 코드 (새 코드 하나):** `browser_secret_channel_unavailable` — 드라이버의 채널이 비밀을 실을 만큼 사적이라고
선언하지 않았다(관리형) · `denied`. 나머지(`browser_unavailable` 등)는 §2 표 그대로다.

**꺼져 있으면:** `provider` 기본값이 `host` 이고 호스트 드라이버의 동작 · 도구 목록 · 검증 사유 · 이벤트 어휘 · 프롬프트는
Q14b 와 같다(W11 시험이 그대로 통과한다). 드라이버 계약의 `new_context` 가 `task_id` 키워드를 받게 됐고 호스트
드라이버는 그것을 쓰지 않는다. 마이그레이션 · API · 이벤트 kind: **없다**(예약 088 은 쓰지 않았다).

### 8.2 구조

```text
BrowserSessions (호스트, 가드 전부) ──new_context(serve, task_id)──▶ ManagedBrowserDriver
        ▲                                                              │ opener.open(task_id)  ← B2 배선(없음)
        │ serve(request) = web_fetch 판정 + IP 고정 한 홉                 ▼
        └──────────── route 프레임 ◀── 벤더 exec stdio (open_stdio, BROWSER_GUEST_ARGV) ──▶ 호출 프레임
                                                              │
                                     샌드박스: neos.coding.browser.guest ─ PlaywrightDriver ─ Chromium (네트워크 없음)
```

코드: `neos/coding/browser/wire.py`(규약·digest) · `guest.py`(샌드박스 쪽) · `managed_driver.py`(호스트 쪽) ·
`session.py`(MB4 판정 · 팩토리) · `neos/config/schema.py`(`provider` · 검증).

### 8.3 검증

- `tests/coding/test_agent_browser_managed.py` — 68개. 메모리 파이프 위의 **실제 `BrowserGuest`** 가 Q14a 의 가짜
  드라이버를 부린다. 출구 판정(6 사유) · 최상위 navigate 거절 · 비밀번호 가리기 · 실패를 코드로 · 닫기 · sweep 은
  `host`/`managed` 둘 다 같은 답. 그 위에 관리형만의 것: guest 의 다른 메서드 · 깨진 route 프레임 거절 · 로그인 거절과
  금고 미개봉(선 위 바이트 전체에서 비밀번호와 `fill` 이 없음) · hello 의 버전·digest · 조용한 guest · 할당 없음 ·
  거짓말하는 guest · 끊긴 채널 · 태스크마다 채널 하나와 상한 · 설정 · 팩토리.
- `tests/coding/test_agent_browser_managed_smoke.py` — 실제 Chromium, `NEOS_BROWSER_SMOKE=1` 일 때만. 벤더 대신
  **로컬 자식 프로세스**(`python -m neos.coding.browser.guest`)의 stdin/stdout 이 채널이다. 2026-10-02 로컬에서
  Playwright 1.61 + Chromium 1194(`NEOS_BROWSER_SMOKE_CHROMIUM`), Chromium 샌드박스 on·off 둘 다 통과: 선을 건너온
  fulfill 로 페이지가 뜬다 · `10.0.0.1` 이미지는 호스트가 막는다 · PUT 은 나가지 않는다 · 평문 `type` + submit 의
  POST 가 호스트를 지난다 · `browser_fill_secret.v1` 은 금고를 열지 않고 거절된다 · `close` 뒤 guest 가 0 으로 끝난다.
  📌 이것이 증명하지 **않는** 것: E2B·Modal 어느 것에 대해서도 아무것도.
- **변이 17/17** — 세션의 채널 판정 · 선언 없는 드라이버 · 관리형 고정값 · hello digest · hello 버전 · 원격 닫기 ·
  guest 오류 문구 · 원격 비밀번호 값 · 설정 평면 검사 · 설정 본문 상한 · 팩토리 대체 · 팩토리 평면 재확인 · bundle
  파일 목록 · base64 엄격 검사 · 끊긴 채널의 대기 호출 · 주인 없는 컨텍스트 · guest 의 취소. 처음 돌렸을 때 넷(버전 ·
  base64 · 대기 호출 · 주인)이 살아남아 시험을 더했다.

### 8.4 실계정 smoke 점검표 (벤더마다, 순서대로)

선행: B2 runtime 배선(할당 평면이 태스크에 allocation 을 붙이고 코딩 provider 가 그것에 붙는다)과 그 위의
**opener 구현** — 태스크의 살아 있는 runtime 을 소유권 검증(`_running_record`) 뒤 찾고 벤더 SDK `open_stdio(ref,
BROWSER_GUEST_ARGV)` 를 부른다. 클라이언트 프로토콜(`SandboxProviderClient`)에 메서드 하나가 더 필요하다 — 바인딩이
없어 쓰지 않았다. 각 항목은 날짜 · 벤더 · SDK 버전 · 이미지 digest 와 함께 이 절에 적는다.

| # | 무엇을 | 통과 조건 |
|---|---|---|
| a | **guest 이미지** — Python · Playwright(호스트와 같은 핀) · 그 Playwright 의 Chromium 빌드 · guest bundle 다섯 파일을 담고 digest 로 고정 | hello 의 `bundle_digest` 가 호스트의 `guest_bundle_digest()` 와 같다. 이미지 digest 가 B2 의 핀(`managed_image_unpinned` 검사)을 통과한다 |
| b | **샌드박스에 네트워크가 없다** — 브라우저가 떠 있는 동안 | profile readback(`verify_applied_network`)이 `DENY_ALL`. 샌드박스 안에서 공개 IP · 벤더 메타데이터 주소로 TCP 연결이 실패한다. route 를 끈 Chromium 이 아무 페이지도 못 띄운다 |
| c | **스모크 시나리오**를 벤더 opener 로 — `test_agent_browser_managed_smoke.py` 의 로컬 프로세스 자리에 벤더 채널 | 같은 단언이 전부 통과: 호스트 fetch 기록은 허용된 URL 뿐 · `10.0.0.1` 차단 · PUT 없음 · 평문 POST 는 호스트를 지난다 · 로그인 거절 |
| d | **Chromium 자신의 샌드박스** — 벤더 VM 안에서 `chromium_sandbox=True` 로 뜨는가 | 뜨면 그대로. 안 뜨면 `--no-chromium-sandbox` 를 운영에 쓸지 **사람이 결정**하고 여기 적는다(그 경우 렌더러 탈출 = guest 프로세스 권한 = 샌드박스 전체) |
| e | **닫기 · 취소 · 장애** | `close`/sweep/X5 뒤 guest 프로세스가 벤더 프로세스 목록에서 사라진다 · 탐색 중 샌드박스를 죽이면 수 초 안에 `browser_action_failed`(timeout 아님) · 할당 정리 SLO 안에 orphan 0 |
| f | **지연 · 크기** | 벤더 중계 왕복이 붙은 페이지 로드 시간 측정(하위 리소스 수 × 왕복) · 8 MiB 본문 왕복 · `max_requests` 근처에서 프레임 폭주 시 호스트 메모리 |
| g | **벤더 쪽 기록** — 채널을 지나는 페이지 본문 · 쿠키 · 평문 입력이 벤더 exec 로그 · 대시보드 · 지원 도구에 남는가 | 문서 · 계약 근거(링크 · 날짜). 남는다면 B2 #5(residency · data flow) 검토로 넘긴다 — 비밀이 아니어도 사용자 데이터다 |
| h | **비용 상한** | 브라우저가 붙은 샌드박스 수명 ≤ `max_lifetime_sec`, `max_contexts` 와 할당 쿼터가 같은 방향 |

**로그인을 여는 것(MB4 뒤집기)** 은 위에 더해 Q6b §4 의 1~4 를 **그대로** 단다(벤더 바인딩의 TLS 검증 고정 ·
exec stdin 비보존 근거 · 실계정 smoke · provider 이름으로 판정) — 그리고 브라우저 고유의 하나: `fill` 프레임의 값이
벤더 로그 · 추적 어디에도 없음을 g 와 같은 방법으로 확인한다. 설정 키로 대신하지 않는다.

### 8.5 남은 것

- 벤더 위 증거 전부(§8.4) — 실계정이 필요하다
- opener 구현 + `SandboxProviderClient` 의 브라우저 stdio 메서드 — B2 runtime 배선 뒤
- MB3 의 W3 제거 — B2 게이트 통과 뒤 별도 커밋
- 관리형 로그인 — 관리형 비밀 채널(다른 트랙)과 §8.4 의 추가 항목 뒤
