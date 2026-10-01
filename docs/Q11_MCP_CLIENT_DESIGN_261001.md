# Q11 실제 MCP 클라이언트 — 설계 (2026-10-01)

> **지위:** Q11a 착지(플래그 off). 설계와 코드가 어긋나면 코드가 이긴다.
> 상위: [로드맵 §1 Q 행](DEEP_ANALYSIS_HARNESS_ROADMAP.md) · [dots 분석 §4.2 Q11](OPENAI_DOTS_ANALYSIS_260930.md).
> 선행: [Q2 사용자 규칙](Q2_Q4B_RULES_CHANNEL_TRIGGERS_DESIGN_261001.md) · [Q6 자격증명 브로커](Q6_CREDENTIAL_BROKER_DESIGN_261001.md).
> 결정 M1~M15 는 위임받아 Claude 가 골랐다(Q2·Q6 와 같은 방식). 사람이 뒤집을 수 있다.

## 1. 무엇을 사는가

dots 행: "커넥터의 표준 입구. 연결된 앱 도구도 `ToolRisk` 를 **선언**해야 등록된다 — 선언 없으면 READ_ONLY 가
아니다(fail-closed)". 오늘 NEOS 에는 MCP 를 말하는 코드가 **없다** — 이름에 MCP 가 붙은 모듈 넷은 모두 자체
도구 클래스이거나 DB 행 관리자이거나 스텁이다(M1).

Q11a 가 착지시키는 것:

| 부품 | 자리 | 하는 일 |
|---|---|---|
| JSON-RPC 세션 · 두 전송 | `neos/coding/connectors/protocol.py` | `initialize` → `tools/list`(페이지) · `tools/call`. stdio 와 streamable HTTP |
| 선언 필터 | `neos/coding/connectors/catalog.py` `declare_tools` | 운영자가 위험을 선언한 도구만 `mcp__<server>__<tool>` 로 |
| 호출 한 번 | `neos/coding/connectors/runner.py` | 금고에서 풀고 → 부르고 → 가리고 → 자르고 → 감싼다(Q6 의 세 걸음) |
| 게이트 | 기존 그대로 | 위험은 선언값, 서버 자격증명은 S7 비밀, 자식은 거절 |

## 2. 결정

| # | 결정 | 이유 |
|---|---|---|
| **M1** | **이름 충돌은 이름을 바꾸지 않고 신고로 푼다.** 옛 모듈 넷(`neos/tools/mcp_integration.py` · `mcp_server_manager.py` · `manager/mcp_manager.py` · `neos/fsi/mcp_attach.py`)의 머리말에 "이름만 MCP 다"를 적고, 진짜 클라이언트는 **`neos/coding/connectors/`** 에 둔다 | 코드로 확인했다 — 넷 다 JSON-RPC 가 없다(자체 `MCPTool` 클래스 · `MCPServer` DB 행 · FSI 스텁). 반면 임포트하는 모듈이 10개(`cli.py` · `workflow/builder/executors.py` · `fsi/ports.py` …)라 이름 변경은 소란만 크다. 새 패키지 이름에 "mcp" 를 또 넣지 않은 것도 같은 이유 — dots 의 말("커넥터")을 쓴다 |
| **M2** | **서버는 운영자 설정에만 있다.** 모델은 명령도 URL 도 고르지 않고, 서버를 더하는 API 도 없다 | dots 행의 "표준 입구"는 입구가 하나라는 뜻이다. 모델이 고를 수 있는 순간 커넥터는 임의 실행이 된다 |
| **M3** | **SDK 를 쓰지 않고 최소 JSON-RPC 클라이언트를 직접 둔다.** 판은 `2025-06-18` 을 내밀고, 서버가 답한 판이 아는 집합(`2024-11-05`~`2025-11-25`) 밖이면 연결을 버린다 | 인덱스로 확인한 실제 패키지는 `mcp`(2.2.0, modelcontextprotocol/python-sdk)다. 그런데 `starlette>=0.27` · `sse-starlette>=3.0`(새로 들어온다) · `uvicorn` · `pydantic>=2.12` 를 요구한다 — 지금 판을 올리지는 않지만 Phoenix 가 붙잡고 있는 웹 스택에 새 제약을 얹는다. 저장소 루트의 `mcp/` 빈 디렉터리(namespace 패키지)와 이름이 겹치는 것도 덤이다. 쓰는 메서드는 넷이고 stdio 틀은 줄 하나 = 메시지 하나다 |
| **M4** | **위험은 선언해야 등록된다.** `tool_risks[tool]` → 서버의 `risk` → 없으면 **미등록**. 서버가 다는 `annotations.readOnlyHint` 는 보지 않는다. 선언할 수 있는 값은 `read_only` · `workspace_write` · `command` | fail-closed 는 "모르면 READ_ONLY" 의 반대다. 위험을 정하는 것은 도구를 파는 쪽이 아니라 쓰는 쪽이다. USER_QUESTION 은 사람에게 묻는 도구의 것이라 없다 |
| **M5** | 노출 이름은 **`mcp__<server>__<tool>`**. 서버 이름에는 밑줄이 없고(`[a-z0-9-]`), 도구 이름은 `[A-Za-z0-9_-]{1,64}`, 합쳐 64자 안 — 못 맞추면 미등록 | Q2 사용자 규칙의 `_TOOL_RE` 가 이미 받는 모양이라 소유자가 커넥터 도구에 allow/require/block 을 쓸 수 있다. 서버 이름에 밑줄을 막아야 `mcp__a___b` 가 모호하지 않다. 내장 도구는 `mcp__` 로 시작하지 않는다(테스트로 고정) |
| **M6** | **발견은 프로세스가 루프를 만들 때 한 번이고, 그 뒤로 고정이다.** 서버마다 따로 실패한다 — 죽은 서버는 도구가 없을 뿐 시작을 막지 않는다. 그 순간엔 소유자가 없으므로 `secret://` 값은 **빼고** 연결한다 | 도구 배열과 시스템 프롬프트가 턴 사이에 바뀌면 사고 블록 재사용이 깨진다(K2b 와 같은 이유). 참조를 빼는 대신 문자 그대로 보내면 `secret://x` 가 서버 로그에 남는다 |
| **M7** | **서버 자격증명은 Q6 의 비밀이다.** `env` · `headers` · `bearer_token` 값이 값 전체로 `secret://<name>`(S1)이면 **태스크 소유자의** 금고에서 호출 때 푼다. 검증기가 `ValidatedToolCall.secret_refs` 에 이름을 싣고, 게이트는 `carries_secret_refs` **한 판정**으로 S7 을 건다 — READ_ONLY 여도 사람 승인 또는 소유자 allow 만 넘는다. stdio env 는 소유자가 묶은 이름이어야 한다(S3, `secret_env_name_mismatch`). 브로커가 꺼진 채 참조를 쓰면 **시작하지 않는다** | 부모 게이트와 자식 게이트가 같은 판정을 쓰게 하려고 입력 밖의 참조를 호출 객체에 싣는다 — 판정을 복사하면 고침이 한쪽에만 도착한다. `Bearer <token>` 은 S1(값 전체)과 맞지 않으므로 `bearer_token` 칸을 따로 둔다(`Authorization` 헤더는 설정으로 쓸 수 없다) |
| **M8** | **연결은 호출마다 새로 연다.** stdio 서버 프로세스는 워커 환경을 물려받지 않는다(`PATH` · `HOME` · `LANG` · `LC_ALL` · `TMPDIR` · `SYSTEMROOT` 만) · stderr 는 버린다 · 닫을 때 프로세스 그룹째 끈다. HTTP 는 리다이렉트를 따르지 않고 환경의 프록시·`.netrc` 를 줍지 않는다(`trust_env=False`) | 자격증명이 소유자마다 다르므로 연결을 나누면 한 소유자의 토큰이 다른 소유자의 호출에 실린다. 워커 환경에는 `NEOS_SECRET_BROKER_KEY` 와 프로바이더 키가 다 있다. stderr 는 풀린 값을 되풀이할 수 있다. 리다이렉트는 인증 헤더를 다른 호스트로 보낸다 |
| **M9** | **결과는 신뢰하지 않는 글이다.** 텍스트만 싣고(이미지 등은 자리표시) → 풀린 값 자체를 **자르기 전에** 가리고(S6) → 자르고 → `redact.py` 규칙 → `wrap_untrusted_document`(univer 의 것을 재사용, 사본 없음) → 루프가 `redact_sensitive` 를 한 번 더. 서버의 도구 **설명**도 신뢰하지 않는다 — 한 줄로 접고 300자에서 자르고 `[MCP connector <server>, risk <risk>]` 를 앞에 단다 | 설명은 시스템 프롬프트의 Tools 절에 실린다 — 줄바꿈을 허용하면 서버가 `## System` 절을 지어낼 수 있다. 자른 뒤에 가리면 잘린 꼬리에 비밀의 앞부분이 남는다 |
| **M10** | 플래그 off 면 **오늘과 바이트가 같다** — 도구 목록·프롬프트·이벤트 어휘. 켜도 선언된 도구가 0 이면 같다. off 에서는 발견조차 하지 않는다 | S9 와 같은 방법: 켜는 커밋만 경계가 된다 |
| **M11** | **자식은 커넥터를 못 쓴다**(`policy_connector_child`). 세 겹이다 — spec 의 `allowed_tools`(정적 이름 목록) · 포트 · CHILD-GATE 의 이름 검사 | 커넥터는 바깥 세상에 닿고 자식은 승인할 사람에게 닿지 못한다. 앞의 두 겹은 목록이 넓어지는 날 열리므로 게이트가 이름으로 한 번 더 닫는다(테스트는 두 목록을 일부러 넓혀서 마지막 겹을 문다) |
| **M12** | 커넥터 도구는 **단계로 숨기지 않는다.** `workspace_write` 로 선언하면 `write_risk_blocked` 가 그대로 막는다 | 단계(explore/plan/verify)는 워크스페이스의 개념이다. 바깥 세상에 닿는 위험은 게이트가 위험 등급으로 본다 |
| **M13** | **비밀을 푸는 호출은 앞질러 돌리지 않는다**(읽기 배치 · 스트리밍 중 프리페치). 두 자리가 `speculation_safe` 한 술어를 쓴다 | 일하다 찾았다 — Q6 의 금고 바인딩(`owner_id`)은 `_dispatch_call` 한 자리에만 있고 배치·프리페치는 금고 없이 실행기를 부른다. `execute.v1` 은 COMMAND 라 앞질러진 적이 없어 드러나지 않았다. READ_ONLY 커넥터가 처음으로 그 길에 들어선다 |
| **M14** | **딥 분석 경로에는 붙이지 않는다.** `research_session` 의 레지스트리는 커넥터를 받지 않는다 | dots §5 D6(Q14 와 같은 이유) — DA 의 조사 도구 집합은 표본 경계다 |
| **M15** | **마이그레이션도 새 이벤트 종류도 없다**(예약 번호 078 은 쓰지 않았다). 승인 카드는 인자(가린 것, 40줄·2000자)와 비밀 **이름**을 보이고, 승인 이벤트에는 인자를 싣지 않는다 | 서버 목록은 설정이고 발견 결과는 프로세스 메모리다. 승인하는 사람은 무엇이 나가는지 봐야 한다 — 내장 도구는 `path`·`argv` 를 보이는데 커넥터는 이름만 보이면 승인이 빈 서명이 된다 |

### 거절·실패 코드

| 코드 | 언제 | 성격 |
|---|---|---|
| `policy_unknown_tool` | 선언되지 않았거나 발견되지 않은 `mcp__…` 이름 | 검증 거절 — 등록되지 않은 도구는 없는 도구다 |
| `policy_schema_invalid` | 서버의 `inputSchema` 에 맞지 않는 인자 · 64KB 초과 | 검증 거절 |
| `policy_connector_child` | 자식 호출이 커넥터다 | 게이트 DENY(자식 원장 `tool.denied`) |
| `policy_secret_ref_unapproved` | 비밀을 쓰는 서버, unattended, 소유자 allow 없음 | 게이트 DENY(Q6 그대로) |
| `connector_unavailable` | 실행 실패 · 연결 거부 · 비 2xx · 리다이렉트 · 프로세스 종료 | 도구 결과 `error` |
| `connector_timeout` | `call_timeout_sec` 초과 | `error` |
| `connector_message_too_large` | 프로토콜 메시지가 `max_message_bytes` 초과 | `error` — 결과를 버린다 |
| `connector_protocol_error` | JSON 이 아니다 · 모르는 판 · 응답 없음 | `error` |
| `connector_call_failed` | `tools/call` 이 JSON-RPC 오류로 답했다 | `error` — 서버 문구는 가리고 감싸서 싣는다 |
| `connector_tool_error` | 결과의 `isError: true` | `error` — 본문은 감싸서 싣는다 |
| `secret_not_found` · `secret_env_name_mismatch` · `secret_store_unavailable` | Q6 그대로 | 연결하지 않는다 |

## 3. 표면

- 설정(`coding_model.mcp`, 기본 off): `enabled` · `servers[]`(`name` · `transport: stdio|http` · `command`/`cwd`/`env` 또는
  `url`/`headers`/`bearer_token` · `risk` · `tool_risks`) · `discovery_timeout_sec`(15) · `call_timeout_sec`(30) ·
  `max_message_bytes`(1 MiB) · `max_output_bytes`(64 KiB) · `max_tools_per_server`(64). 새 env 키는 없다.
  `docs/CONFIGURATION.md` "Coding MCP connectors (track Q11a)"
- 시작 검사: 같은 서버 이름 금지 · stdio 는 argv 필수 · http 는 https(평문은 loopback 만) · URL 에 자격증명 금지 ·
  예약 헤더(`Authorization` · `Mcp-Session-Id` …) 금지 · `secret://` 를 쓰면 `coding_model.secret_broker` 필수 ·
  모양이 틀린 참조는 시작 실패
- API·라우트·마이그레이션·이벤트 종류: 없다
- 운영 로그: 서버별 발견 실패(사유 코드만), 선언되지 않아 빠진 도구 이름 — 운영자가 무엇을 선언할지 안다

> ⚠️ stdio 서버는 **샌드박스 밖**, 워커의 OS 사용자로 돈다. 운영자가 직접 돌릴 명령만 적는다.

## 4. 남은 것

- **Q11b** 소유자 범위의 발견 — 사용자 자격증명이 있어야 `tools/list` 를 주는 서버(대부분의 SaaS)는 지금 발견되지
  않는다. 후보: 운영자가 도구 목록(이름·설명·스키마)을 설정에 고정하는 매니페스트, 또는 소유자별 발견 캐시
- stdio 서버를 샌드박스 안에서 돌리기(Q6b 의 비밀 채널과 함께)
- 도구가 많은 서버의 지연 로딩 — 지금은 선언한 도구가 전부 배열에 실린다(`search_tools.v1` 경로로 옮기기)
- `resources` · `prompts` · `sampling` · `elicitation` · `outputSchema` — 지금은 `tools` 만
- 연결 재사용(소유자 범위) · 서버 건강 지표 · FE 표시 · 에이전트별 부여(Q17)
