# Q16 사용자 기기 브리지 — 설계 (2026-10-01)

> **지위:** Q16a 착지(플래그 off) · **Q16b 착지**(쓰기 도구 하나, 자격증명·클라이언트 두 열쇠 모두 기본 off — §6). 설계와 코드가 어긋나면 코드가 이긴다.
> 상위: [로드맵 §1 Q 행](DEEP_ANALYSIS_HARNESS_ROADMAP.md) · [dots 분석 §4.2 Q16](OPENAI_DOTS_ANALYSIS_260930.md).
> 위협 모델: [Q16_DEVICE_BRIDGE_THREAT_MODEL.md](Q16_DEVICE_BRIDGE_THREAT_MODEL.md) — 등급을 넓힐 때마다 한 줄씩.
> 결정 B1~B13 은 위임받아 Claude 가 골랐다(Q2·Q4b·Q6 과 같은 방식). 사람이 뒤집을 수 있다.

## 1. 무엇을 사는가

dots F4 — "에이전트가 **사용자의 기기**에서 일한다". NEOS 의 코딩 루프는 지금 샌드박스 안만 본다.
Q16 은 샌드박스 경계를 넓히지 않는다. 대신 **별도 실행 표면**을 하나 둔다: 사용자가 자기 기기에서
돌리는 로컬 브리지가 NEOS 로 밖으로 소켓을 열고, 에이전트의 도구 호출을 받아 답한다.

dots §4 의 결정(2026-09-30)대로 **위협 모델은 지속적 개선**이다. 완성된 문서를 착수 조건으로 두지 않고,
브리지는 **READ_ONLY 도구만으로 시작**한다. 등급을 한 단계 넓힐 때마다 위협 모델 문서에 증분 한 줄이 먼저다.

Q16a 가 착지시키는 것:

| 부품 | 자리 | 무엇 |
|---|---|---|
| 도구 카탈로그 · 선언 검사 · 결과 모양 · 무인 규칙 | `neos/coding/bridge/catalog.py` | 서버가 정한 세 도구, READ_ONLY 만 받는 선언 검사 |
| 페어링 자격증명 | `neos/coding/bridge/credentials.py` · 마이그레이션 080 | 토큰 1회 노출, 해시만 저장 |
| 중계 | `neos/coding/bridge/relay.py` | 소켓 프로세스 ↔ 루프 프로세스(Redis), 테스트용 in-process |
| 소켓 세션 | `neos/coding/bridge/session.py` · `api/handlers/device_bridge_ws_handlers.py` | 인증 · 선언 · 호출 전달 · 재검사 |
| 루프 쪽 서비스 | `neos/coding/bridge/service.py` | 소유자의 브리지를 보고, 호출하고, 결과를 감싼다 |
| 참조 클라이언트 | `neos/bridge/` (`python -m neos.bridge`) | 명시한 폴더 하나, READ_ONLY, 실행 없음 |

## 2. 결정

| # | 결정 | 이유 |
|---|---|---|
| **B1** | **페어링 = 토큰 하나.** `POST /coding/device-bridges` 가 `ndb_<256비트>` 를 **한 번만** 돌려주고 DB 에는 SHA-256 만 남는다(080 `device_bridges`, `ON DELETE CASCADE`). 폐기는 행 삭제다. 키는 **`user_id`** 다 | 고엔트로피 난수라 솔트·느린 해시가 필요 없다 — 코딩 소켓 티켓이 Redis 키를 잡는 방법과 같다(새 암호 없음). 📌 Q13 규칙("에이전트에 딸린 것은 `agent_id`")과 어긋나지 않는다: 기기는 **사람의 것**이지 에이전트의 것이 아니다(Q6 S4 금고와 같은 논리). 에이전트가 하나에서 여럿이 돼도 이 표는 바뀌지 않는다 — 에이전트별 접근은 따로 **부여(grant)** 표로 연다(Q17 과 함께) |
| **B2** | **도구의 이름·설명·스키마는 서버가 정한다.** 브리지는 카탈로그(`list_dir`·`stat`·`read_file`)에서 무엇을 내놓는지와 위험 등급만 선언한다. 모델에게는 `device_<도구>.v1` 로 보인다 | 기기에서 온 설명 문구가 모델 앞에 서면 그것이 곧 프롬프트 주입 표면이다. 이름은 사용자 규칙의 도구 모양(`_TOOL_RE`)에 맞아 Q2 의 block/require/allow 가 그대로 걸린다 |
| **B3** | **READ_ONLY 만 받는다.** 선언에 하나라도 다른 등급·모르는 이름·**빠진 등급**이 있으면 등록 **전체**를 거절한다(`device_tool_risk_refused`, 4403). 받는 등급 집합은 코드 상수 `ALLOWED_DEVICE_RISKS` 하나다 | 선언 없는 등급은 READ_ONLY 가 아니다(fail-closed, Q11 행과 같은 규칙). 어긋난 것만 빼고 나머지를 받으면 브리지는 자기가 무엇을 열었는지 모른다. 등급을 넓히는 커밋은 이 상수와 위협 모델 한 줄을 함께 바꾼다 |
| **B4** | **노출은 소유자의 연결된 브리지가 있을 때만.** 루프가 매 단계 연결 표시를 새로 읽어 상태에 싣고(체크포인트에 싣지 않는다 — Q2 `user_rules` 와 같은 자리), 도구 배열 **끝에** 덧붙인다. 소유자 격리는 세 겹: 연결 표시의 키가 소유자 `user_id` · 소켓은 요청의 `user_id` 가 자기 것과 다르면 거절 · 루프는 답의 `id`·`user_id` 를 다시 맞춘다 | 붙고 끊길 때 배열이 바뀌는 것은 `_guard_thinking_prefix` 가 사고 블록을 한 번 벗겨 받는다(새 장치 없음). 연결 표시를 못 읽으면 **브리지가 없는 것** — 도구가 사라지는 쪽은 좁히는 쪽이라 Q2 규칙 읽기 실패처럼 재시도로 만들지 않는다 |
| **B5** | **사용자당 동시 연결 하나, 최신이 이긴다.** 새 연결이 연결 표시를 덮고, 옛 연결은 다음 갱신(compare-and-refresh)에서 밀려났음을 알고 4409 로 닫힌다. 참조 클라이언트는 4409 에서 다시 붙지 않는다 | 네트워크가 바뀐 뒤 서버가 옛 소켓의 죽음을 아직 모를 때 다시 붙을 수 있어야 한다. 둘이 서로 밀어내는 핑퐁은 4409 에서 멈추는 것으로 끊는다. 어느 기기가 답하는지가 늘 하나로 정해진다 |
| **B6** | **다중 워커: Redis 중계.** 소켓은 API 프로세스(uvicorn 워커 중 하나)에, 코딩 루프는 Celery 워커에 있다 — **같은 프로세스인 배포가 없다**(dev 의 진짜 루프도 Celery 로 돈다). 연결 표시 `presence:{user_id}`(TTL, 자기 값일 때만 갱신·해제하는 Lua) · 호출은 `conn:{conn_id}` 채널 PUBLISH + `reply:{request_id}` BLPOP(구독자 0 이면 즉시 `device_bridge_unavailable`) · 답 목록은 60초 뒤 사라진다. 루프 쪽은 연산마다 클라이언트를 연다(Celery 태스크마다 이벤트 루프가 새로 선다). `InProcessDeviceBridgeRelay` 는 같은 계약의 **테스트용**이다 | "개발 단일 프로세스만, 나머지는 거절"은 이 저장소에서는 기능이 어디서도 돌지 않는다는 뜻이었다. Redis 는 코딩 소켓 티켓·이벤트 팬아웃이 이미 요구한다(새 인프라 없음). 실패는 전부 닫힌 쪽이다: 표시가 없으면 도구가 없고, 늦으면 `device_bridge_timeout` |
| **B7** | **무인 읽기는 브리지가 허락해야 한다.** 브리지마다 `allow_unattended`(기본 **false**). 아무도 보지 않는 런(autonomous·background, 또는 운영자 `approval_unattended`)에서 허락 없는 브리지의 도구는 **보이지 않고**, 이름으로 불러도 게이트가 `policy_device_unattended` 로 거절하며, 소켓은 **지금의** 설정으로 한 번 더 본다. 세 자리가 `device_unattended_refused` **한 함수**를 쓴다. 게이트에서는 Q1 천장 바로 뒤 — 운영자 allow·auto 모드·사용자 allow 어느 것도 넘지 못한다 | READ_ONLY 는 Q1 천장을 지나지만, 사람의 기기를 사람이 없을 때 읽는 것은 별개의 사생활 단계다. 좁히기만 한다(§4.1). 설정을 바꾸면(`PATCH`) 붙어 있는 연결을 끊어 새 설정으로 다시 붙게 하고, 소켓은 갱신마다 자격증명을 다시 읽어 끊김을 놓쳐도 닫는다 |
| **B8** | **브리지는 비밀을 받지 않는다.** 인자 어디에든 `secret://` 가 있으면(대소문자 무시, 경로 정규화 **전**에) 검증기가 `policy_device_secret_ref` 로 거절한다 — 브로커가 꺼져 있어도 같다. 결과에서 금고 값을 가리는 단계(Q6 S6)는 없다: 풀린 값이 없으므로 가릴 것도 없다. `redact_sensitive` 는 다른 도구 결과처럼 걸린다 | 브리지에는 금고가 없고, 풀린 값이 기기로 가는 길을 만들지 않는다. 문자 그대로의 참조도 보내지 않는다 — 기기 쪽 로그·도구가 그것을 무엇으로 해석할지 서버는 모른다. 판정은 검증기 하나라 부모·자식이 같은 것을 쓴다. 📌 경로 정규화(`PurePosixPath`)가 `secret://x` 를 `secret:/x` 로 접는다 — 처음엔 정규화 뒤에 봐서 놓쳤고 테스트가 잡았다 |
| **B9** | **결과는 untrusted 다.** 서버가 모양을 검사하고(어긋나면 `device_result_invalid`), 본문을 **먼저 자르고 그다음 감싼다**(`untrusted device content` 경계 — 자르기가 끝 경계를 지우지 않게), 파일 이름의 제어 문자를 지워 줄 위조를 막는다. 이유 코드는 서버 목록에서만 나온다 — 기기가 보낸 문자열은 `device_error` 하나가 된다. 원장에는 다른 도구처럼 `tool.completed` 로 남는다. **새 이벤트 kind 없음** | 기기에서 온 것은 전부 주입 표면이다(web_fetch 와 같은 대우). 원장의 이유 코드·메트릭 라벨에 기기 문자열이 들어가면 그것도 표면이다. 기기 호출은 평범한 도구 호출이라 이벤트 어휘를 넓힐 이유가 없다 |
| **B10** | **참조 클라이언트는 명시한 폴더 하나, 읽기만, 실행 없음.** 파일시스템 루트·홈 폴더 자체는 거절 · 상대 경로만(절대·드라이브 문자·`~`·`..`·NUL 은 `path_escape`) · 실경로를 다시 봐서 링크 탈출 차단 · 비밀 경로는 서버와 **같은 함수**(`is_denied_secret_path`)로 거절하고 목록에서 숨긴다(링크를 따라간 실경로도) · `O_NOFOLLOW|O_NONBLOCK` 으로 열어 FIFO·바뀐 링크를 막는다 · 바이너리는 `binary_file` · 상한 · 토큰은 환경변수로만 · `wss://`(또는 `ws://localhost`)만 | 기기는 사용자의 것이고 NEOS 가 거기서 무엇을 할 수 있는지는 이 파일이 정한다. "실행하지 않는다"는 소스 스캔 테스트(프로세스·셸·exec·eval 0건)가 이름으로 고정한다 |
| **B11** | **자식은 기기에 닿지 않는다.** 세 겹: 포트의 `definitions()` 에 브리지 도구가 없다 · 어떤 서브에이전트 스펙도 브리지 도구를 나열하지 않는다 · 자식 게이트가 `policy_device_child` 로 거절한다(스펙을 넓혀도) | 자식은 승인할 사람에게 닿지 못하고(CHILD-GATE), 포트에는 소유자·무인 맥락이 없다(Q6 S8 과 같은 이유). 최소 권한 — 자식이 기기를 읽어야 하면 부모에게 돌려준다 |
| **B12** | **플래그 off 면 오늘과 바이트가 같다.** 라우트가 마운트되지 않고(소켓도), 레지스트리는 브리지 도구를 모르며(`policy_unknown_tool`), 루프는 연결 표시를 읽지 않는다. 켜도 브리지가 없으면 도구 목록·시스템 프롬프트가 off 와 같다 | S9(트랙 I 의 방법): 켜는 커밋만 경계가 된다 |
| **B13** | **기기 호출은 투기적으로 돌지 않는다.** 읽기 전용 배치·선읽기(prefetch)에서 뺀다 | 두 경로는 소유자·무인 여부를 싣지 않는다(배치 경로에는 `owner_id` 가 없다). 사람의 기기를 게이트의 본 판정 전에 읽지 않는다 |

### 거절·실패 코드

| 코드 | 언제 | 성격 |
|---|---|---|
| `device_tool_risk_refused` · `device_tool_unknown` · `device_declaration_invalid` | 선언이 어긋났다 | 소켓 4403, 등록 없음 |
| `policy_device_secret_ref` | 인자에 `secret://` | 검증 거절(`tool.denied`) |
| `policy_device_unattended` | 무인 런 + 허락 없는 브리지 | 게이트 DENY / 소켓 재검사 |
| `policy_device_child` | 자식이 불렀다 | 자식 게이트 DENY |
| `device_bridge_unavailable` · `device_bridge_timeout` · `device_bridge_busy` · `device_bridge_disconnected` | 연결 없음 · 늦음 · 상한 · 끊김 | 도구 결과 `error` |
| `device_result_too_large` · `device_result_invalid` · `device_bridge_owner_mismatch` | 답이 크다 · 모양이 틀렸다 · 다른 요청·사용자의 답 | 도구 결과 `error` |
| `device_path_escape` · `policy_secret_path_denied` · `policy_binary_file` | 기기 쪽 경계 | 도구 결과 `denied` |
| `device_not_found` · `device_not_a_file` · `device_not_a_directory` · `device_permission_denied` · `device_error` | 기기 쪽 실패 | 도구 결과 `error` |

### 소켓 닫는 코드

| 코드 | 뜻 | 참조 클라이언트 |
|---|---|---|
| 4401 | 인증 실패 · 폐기됨. 📌 accept **전** 거절(4401·4406)은 실제 ASGI 서버에서 HTTP 403 으로 도착한다 — 클라이언트는 401/403 핸드셰이크 거절도 끝으로 읽는다 | 끝낸다 |
| 4403 | 선언 거절 | 끝낸다 |
| 4406 | subprotocol 아님 | 끝낸다 |
| 4409 | 다른 연결에 밀렸다(B5) | 끝낸다 |
| 4001 | 설정이 바뀜 · 연결 표시를 잃음 | 물러섰다가 다시 붙는다 |
| 4408 | hello 를 기다리다 시간 초과 | 다시 붙는다 |
| 1009 | 메시지가 상한을 넘었다 | 다시 붙는다 |
| 1013 | 중계(Redis)가 없다 | 다시 붙는다 |

## 3. 흐름

```
기기                                API 워커 (소켓)                    Redis                    Celery 워커 (코딩 루프)
python -m neos.bridge ──wss──> /coding/device-bridge/ws
  Authorization: Bearer ndb_…    authenticate(sha256) ─ device_bridges
  hello{tools,risk}         ───> parse_declaration (READ_ONLY 만)
                            <─── ready                ── SET presence:{user} (TTL)
                                                                                    단계 시작: GET presence:{owner} → 도구 노출
                                                                                    게이트(USER_ONLY → 천장 → B7 → … → 사용자 규칙)
                                 deliver ←─── PUBLISH conn:{conn_id} {id,user_id,tool,args,unattended}
  call{id,tool,args}        <─── (user_id·무인·상한 재검사)
  result{id,ok,result}      ───> RPUSH reply:{id} ───────────────────────────────> BLPOP → 모양 검사 · 자르기 · 감싸기
                                 매 TTL/3: compare-and-refresh + 자격증명 재읽기                  → redact → tool.completed
```

## 4. 표면

- 설정: `coding_model.device_bridge.*`(기본 `enabled: false`) — [CONFIGURATION.md](CONFIGURATION.md) "Coding device bridge (track Q16a)". 새 환경변수 없음(`REDIS_URL` 을 쓴다)
- 마이그레이션 080 `device_bridges`(bridge_id · user_id · name · token_hash · allow_unattended · created_at · last_connected_at; `(user_id, name)` 유일, `token_hash` 유일)
- API(꺼져 있으면 라우트가 **없다**):

  ```
  GET    /api/v1/coding/device-bridges
  POST   /api/v1/coding/device-bridges                 # 토큰은 이 응답에만
  PATCH  /api/v1/coding/device-bridges/{bridge_id}     # allow_unattended
  DELETE /api/v1/coding/device-bridges/{bridge_id}
  WS     /api/v1/coding/device-bridge/ws               # neos.device-bridge.v1
  ```
- nginx: 소켓 전용 업그레이드 location(`/api/` 블록의 `Connection ""` 이 업그레이드를 떨군다 — 2026-09-27 코딩 소켓과 같은 이유)
- 모델에게 알리는 법: 도구 설명뿐이다. 프롬프트는 바꾸지 않는다(B12)

📌 이 작업에서 찾은 것: `tests/api/test_retired_routes._routes()` 는 **포함된 라우터의 WebSocket 경로를 빈 문자열로** 읽었다 — 소켓의 부재 검사가 공허했다. 원래 라우터에서 prefix 를 붙여 읽도록 고치고, 이웃 소켓(`/api/v1/coding/ws`)이 보이는지 확인하는 테스트를 더했다.

## 5. 남은 것

- ~~**Q16b** 쓰기 등급(WORKSPACE_WRITE)~~ — 착지(§6)
- **Q16c** 명령 실행(COMMAND) — 기기 쪽 샌드박스·허용 목록·USER_ONLY 와의 관계를 먼저 정한다
- 에이전트별 부여(Q17 과 함께) · 여러 기기 동시 연결(지금은 하나) · 웹 UI 의 페어링 화면 · 패키지로 배포하는 클라이언트(지금은 저장소에서 `python -m`)
- ~~Redis 중계의 실 Redis 통합 시험~~ — Q16b 에서 더했다(§6 BW10). CI 에는 Redis 가 없어 `NEOS_TEST_REDIS_URL` 이 있을 때만 돈다 — CI 서비스 컨테이너로 올리는 것은 남았다
- 소켓마다 구독 연결이 하나다(API 프로세스의 Redis 풀을 쓴다). 브리지가 많아지면 워커당 패턴 구독 하나로 묶는다
- 호출 시간 제한(`call_timeout_seconds`, 기본 20초)은 도구 claim TTL(기본 30초)보다 짧아야 한다 — 길면 claim 이 먼저 끝나 같은 읽기가 한 번 더 돈다(READ_ONLY 라 해는 없지만 낭비다). 지금은 검사하지 않는다. 쓰기는 다시 돌지 않는다: 루프가 READ_ONLY 아닌 재획득 claim 을 `tool_outcome_unknown` 으로 끝내고, 그래도 돈다면 다이제스트가 이미 바뀌어 stale 이다(BW5)

## 6. Q16b — 쓰기 등급 (2026-10-02)

위협 모델 §3 의 Q16b 줄과 §4 의 표가 **먼저** 들어갔다(같은 커밋). 결정 BW1~BW11 은 위임받아 Claude 가 골랐다. 사람이 뒤집을 수 있다.

| # | 결정 | 이유 |
|---|---|---|
| **BW1** | **쓰기 도구는 하나 — `device_write_file.v1`(파일 전체 쓰기).** `edit`·`mkdir`·`rm`·`mv`·`chmod` 는 열지 않는다 | 다이제스트를 낀 전체 쓰기 하나로 "만들기"와 "고치기"가 다 된다. 도구가 늘수록 위협 모델의 줄이 는다 — 지우기·옮기기는 되돌릴 수 없는 정도가 한 단계 더 크다. 부분 편집은 같은 등급이라 나중에 줄 없이 더할 수 있다 |
| **BW2** | **두 열쇠, 둘 다 기본 off.** 자격증명 `allow_writes`(083, `allow_unattended` 와 따로) **와** 클라이언트 `--allow-writes`. 쓰기를 선언했는데 자격증명이 꺼져 있으면 쓰기만 빼지 않고 **등록 전체**를 거절한다(`device_writes_not_enabled`, 4403). 켜고 끄면 붙은 연결을 끊고, 소켓은 갱신마다 + **쓰기마다** 자격증명을 다시 읽는다(`device_writes_off`) | 기기 쪽 열쇠는 "이 폴더에 쓰게 하겠다", 서버 쪽 열쇠는 "이 브리지에 쓰기를 맡기겠다"다 — 한쪽만으로 열리면 다른 쪽의 사람이 모른다. 일부만 받는 등록은 B3 과 같은 이유로 거절(브리지가 자기가 무엇을 열었는지 모른다). 쓰기는 드물고 사람이 승인하므로 DB 한 번 더 읽는 값이 싸다 |
| **BW3** | **쓰기마다 사람 승인.** 게이트에서 비밀 참조(Q6 S7)와 같은 자리: 운영자 allow 목록·auto 모드·"항상 허용" 기억은 넘지 못하고, **소유자의 allow 규칙만** 넘는다. 지시 파일(`AGENTS.md` 등)·민감 설정은 그 allow 도 넘지 못한다(`_INSTRUCTION_WRITE_TOOLS` 에 더했다). 승인 화면에 경로·본문 미리보기·덮는지/새로 만드는지가 실린다(이벤트에는 본문이 없다 — `write_file.v1` 과 같다) | 기기는 사람의 것이라(B1) 그것을 바꾸는 허락을 줄 수 있는 것도 그 사람뿐이다. 운영자 설정은 모든 사용자에게 걸린다 |
| **BW4** | **무인 쓰기는 늘 거절** — 브리지의 `allow_unattended` 와 **어떤 allow 로도**. `device_unattended_refusal` 하나가 이유 코드(`policy_device_write_unattended`)를 돌려주고 노출 · 게이트(Q1 천장 바로 뒤) · 소켓 · 서비스가 그것을 쓴다(📌 "고침은 한 호출부에만 도착한다" — 함수가 하나라 부모·자식·소켓이 같은 판정). background 는 Q1 천장이 먼저 막는다(`policy_mode_ceiling`, 손대지 않았다). 쓰기를 막는 단계(EXPLORE·PLAN·VERIFY)에서는 도구 목록에서도 빠진다 | `allow_unattended` 는 **읽기**에 대한 허락이다. 사람의 기기를 사람 없이 바꾸는 허락은 이 슬라이스에 없다 — 좁히기만 한다 |
| **BW5** | **read-before-write 는 다이제스트로.** 덮을 때는 `base_sha256` = 그 파일을 **온전히** 읽었을 때의 SHA-256, 새로 만들 때는 없음. 기기가 지금 파일을 해시해서 다르면 `precondition_stale_read`, 있는 파일에 없으면 `precondition_read_required`(샌드박스 쓰기와 같은 이름). 다이제스트는 `device_read_file.v1` 결과의 untrusted 경계 **밖** 한 줄로 보이고(서버가 16진 64자인지 확인), 잘린 읽기에는 없으며, 브리지가 쓰기를 내놓았을 때만 붙는다. rename 직전에 한 번 더 해시한다 | 상태가 없다: 루프 상태·체크포인트·워커를 넘나드는 "읽은 파일" 기록이 필요 없고, 다이제스트를 아는 것 자체가 지금 내용을 안다는 증명이다(주입된 글이 파일 자신의 해시를 지어낼 수는 없다). 다시 돈 쓰기·늦은 답 뒤의 재시도는 다이제스트가 이미 바뀌어 stale 이다. 쓰기가 없는 브리지의 읽기 결과는 Q16a 와 바이트가 같다 |
| **BW6** | **기기 쪽 경계(쓰기).** 읽기의 경계(B10) + 링크가 **하나도 없는** 경로(루트부터 성분마다 `O_NOFOLLOW|O_DIRECTORY` 디렉터리 fd, 마지막 성분도 그 fd 안에서 `lstat`) · dot 성분 전부 거절(`.git/`·`.github/`·`.vscode/`·셸 rc·`.envrc`…) · OS 가 열면 실행하는 확장자 거절 · 부모가 있어야 한다(만들지 않는다) · 텍스트만 · 새 파일 `0644 & ~umask` · 실행 비트가 선 파일은 덮지 않는다(`policy_device_write_executable`) · 덮을 때 원래 권한 유지 | 루트 안이라도 링크를 따라 쓰면 쓰는 곳이 승인 화면의 경로와 다르다. fd 를 쥐고 내려가면 검사와 쓰기 사이에 중간 디렉터리를 바꿔치는 경쟁이 닫힌다(B10 의 남는 위험이 쓰기에서는 닫혔다). 실행 비트·자동 실행 위치·dotfile 이 "쓰기"를 "실행"으로 바꾸는 길이다 |
| **BW7** | **원자적 쓰기.** 같은 디렉터리 임시 파일(`O_CREAT|O_EXCL|O_NOFOLLOW`) → fsync → 덮기는 `rename`, 새로 만들기는 `link`(있으면 실패 — 그 사이 생긴 파일을 덮지 않는다) → 디렉터리 fsync. 어떤 실패든 임시 파일을 지운다. 공간 부족은 `device_no_space` | 반쯤 쓴 파일이 남지 않는다. rename 은 디렉터리 항목을 바꾸므로 다른 곳의 하드 링크로 내용이 새지 않는다. POSIX(`openat`) 가 없는 기기는 쓰기 클라이언트를 만들지 않는다 |
| **BW8** | **경로 규칙은 함수 하나** — `neos/coding/bridge/write_policy.py:device_write_refusal`. 서버 검증기(`policy_device_write_path`)와 클라이언트가 같은 것을 import 한다(무거운 import 없음) | B10 의 `is_denied_secret_path` 와 같은 이유: 사본이 둘이면 한쪽만 새 이름을 안다 |
| **BW9** | **쓰기 결과는 서버가 만든 한 줄** — 새로/덮음 · 바이트 수 · 검증한 다이제스트. 기기 문자열이 없어 untrusted 경계도 필요 없다. 이유 코드는 여전히 서버 목록에서만 | 다음 쓰기의 `base_sha256` 이 여기서 나온다. B9 그대로 |
| **BW10** | **실 Redis 시험** — `tests/coding/test_device_bridge_relay_redis.py`, `NEOS_TEST_REDIS_URL` 이 있을 때만. API 쪽은 `cache_manager` 와 같은 풀(바이트·health check), 워커 쪽은 연산마다 새 클라이언트. presence TTL·compare-and-refresh(진 쪽이 TTL 을 늘리지 못한다)·자기 값만 지우는 release·연결별 채널·답 목록 TTL·시간 초과·구독자 없음·깨진 답·kick·소켓 세션 ↔ 서비스 끝까지(쓰기 포함)·밀려난 소켓 4409 | 계약 가짜는 Lua 를 문자열로 흉내 낸다 — 진짜 Redis 에서 한 번은 돌아야 했다(2026-10-02 `redis:7-alpine` 로컬 7/7 통과, 가짜가 숨긴 결함은 찾지 못했다) |
| **BW11** | **크기 상한** `device_bridge.max_write_bytes`(기본 256 KiB, 1 KiB~4 MiB). 서비스가 보내기 전에 보고(`device_write_too_large`), 기기에 같은 값을 넘겨 기기도 자기 상한과 함께 본다. 스키마 절대 상한 4 MiB | 디스크 채우기·거대한 메시지를 양쪽에서 막는다. 쓰기마다 사람 승인이 곧 속도 제한이라 별도 횟수 상한은 두지 않았다 |

**변하지 않은 것:** B8(비밀 참조는 본문까지 어디에든 있으면 거절) · B11(자식 거절 — 이름으로 보므로 쓰기도 같다) · B12(플래그 off, 그리고 **켜도 쓰기가 없는 브리지**면 도구 목록·시스템 프롬프트·읽기 결과·이벤트가 `01968004` 와 바이트가 같다 — 로컬에서 두 트리를 덤프해 비교했다) · B13(기기 호출은 투기적으로 돌지 않는다).

**표면:** 083 `device_bridges.allow_writes`(BOOLEAN NOT NULL DEFAULT FALSE, 두 번 적용해도 같다) · `POST`/`PATCH` 에 `allow_writes` · `python -m neos.bridge --allow-writes [--max-write-bytes N]` · 새 이벤트 kind 없음 · 새 환경변수 없음(시험용 `NEOS_TEST_REDIS_URL` 만).

**남은 것(Q16b 뒤):** Q16c 명령 실행(COMMAND) · 부분 편집 도구(같은 등급) · 지우기·옮기기(다음 증분 — 위협 모델 줄이 먼저) · 무인 쓰기는 지금 닫혀 있다 — 연다면 별도 증분과 줄 · 실 Redis 시험을 CI 서비스 컨테이너로 · 임시 파일(`.neos-bridge-*.tmp`)이 클라이언트가 죽으면 남는다(dot 파일이라 목록에는 보인다 — 시작할 때 청소하는 것은 남았다)
