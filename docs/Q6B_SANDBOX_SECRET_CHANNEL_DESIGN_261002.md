# Q6b sandboxd 비밀 채널 — 설계 (2026-10-02)

> **지위:** Q6b 착지(Q6 플래그 `coding_model.secret_broker` 아래, 새 플래그 없음). 설계와 코드가 어긋나면 코드가 이긴다.
> 상위: [Q6 설계 §3](Q6_CREDENTIAL_BROKER_DESIGN_261001.md) · [로드맵 §1 Q 행](DEEP_ANALYSIS_HARNESS_ROADMAP.md) ·
> [dots 분석 §4.2 Q6](OPENAI_DOTS_ANALYSIS_260930.md) · 관리형 신뢰 모델 [B2 설계](MANAGED_SANDBOX_B2_DESIGN_260915.md).
> 결정 C1~C8 은 위임받아 Claude 가 골랐다(Q6 의 S1~S9 와 같은 방식). 사람이 뒤집을 수 있다.

## 1. 무엇을 사는가

Q6a 는 `CommandRequest.secret_env` 를 memory·Docker 에만 실었고 sandboxd 는 `secret_env_unsupported` 로 거절했다.
Q6b 는 **sandboxd RPC 에 비밀 채널**을 더한다 — 평문이 RPC 추적·로그, guest 로그, 오류 메시지, 어떤 프로세스의 argv,
원장, 저장되는 어떤 것에도 나타나지 않게.

그리고 **어느 운반로에 그 채널을 열지**를 정한다. 결론부터:

| provider | 운반로 | 비밀 |
|---|---|---|
| memory · Docker | (Q6a) | ✅ 그대로 |
| sandboxd — `LocalSandboxd` | AF_UNIX 소켓, 0600, `mkdtemp`(0700) 안 | ✅ 실린다 — 다만 **테스트 대역**이다. factory 가 고를 수 없다 |
| managed — E2B · Modal | 벤더 exec 의 stdio 중계(`open_stdio`) | ❌ `secret_env_unsupported` 유지(C1) |

즉 **운영에서 새로 비밀을 싣는 provider 는 없다.** 착지하는 것은 채널(프레임 필드·협상·guest 주입·거절 경로)과
그것을 관리형에 열 때 필요한 증거의 목록이다. Q11 샌드박스 안 stdio·Q14c 가 이 채널 위에 선다(§5).

## 2. 오늘 무엇이 기록되는가 (확인한 것)

- **sandboxd 호스트 경로**(`sandboxd/client.py` · `session.py`)와 **guest**(`guest.py`)에는 로거도 추적 훅도 없다.
  RPC 인자를 남기는 곳이 없다. guest 의 실패는 `(kind, code)` 상수뿐이고 `_dispatch` 는 예외 문구를 싣지 않는다.
- **관리형 provider**(`sandbox/managed/*`)도 로깅하지 않는다. 원장은 revision·stream cursor 만 커밋한다.
- **코딩 관측**(`sandbox/observability.py`)은 env **이름**만 적는다(`environment_names`). 값은 없다.
- `CommandRequest.__repr__` 는 `env` 를 보이고 `secret_env` 는 감춘다(`repr=False`, Q6a).
- guest `state_dir` 에는 revision 파일 하나. PTY·watch journal 은 메모리, exec 인자는 어디에도 저장되지 않는다.

그러니 "env 가 오늘 로그에 찍힌다"는 사실이 아니다. 그래도 `env` 에 섞지 않는 이유는 C2 에 적었다.

## 3. 결정

| # | 결정 | 이유 |
|---|---|---|
| **C1** | **운반로 기밀성.** 비밀은 attachment 가 `confidential_channel` 을 참으로 선언할 때만 싣는다. 선언하지 않은 구현은 거짓으로 읽는다(`getattr(..., False)`). `LocalSandboxd` 는 참(AF_UNIX 0600 + 0700 디렉터리, 네트워크 홉·중계 프로세스 없음). **관리형 `_Attachment` 는 거짓 고정** — 스위치·설정 키를 두지 않는다 | 관리형 채널은 벤더 SDK 의 exec stdin/stdout 이다(`E2BSdk.open_stdio` · `ModalSdk.open_stdio`). 그 SDK 바인딩이 **저장소에 없다**(Protocol 만 있다). 그래서 (1) TLS 검증이 켜져 있는지, (2) 벤더가 exec stdin 을 보존·로깅하지 않는지 둘 다 보일 수 없다. 보일 수 없는 운반로는 연다고 적지 않는다. `profiles.py` 의 규칙 "켤 수 있는 스위치는 언젠가 켜진다"를 따라 여는 일은 **증거를 단 코드 변경**이어야 한다(§4) |
| **C2** | `exec` 요청에 **별도 필드 `secret_env`**(같은 프레임). 호스트에서 `env` 에 합치지 않는다. 비밀이 없으면 키 자체를 싣지 않는다 — 플래그 off 의 프레임은 오늘과 **바이트가 같다**(S9) | §2 대로 오늘 `env` 를 찍는 곳은 없다. 그래도 나누는 것은 (a) `env` 는 운영자 허용 목록·`repr`·관측 이름 목록이 보는 **평범한** 필드라 앞으로 붙을 추적이 그대로 비밀을 집는다, (b) guest 가 어느 값이 비밀인지 알아야 거기서도 되돌려 보내지 않는다, (c) 필드를 모르는 guest 를 가려낼 수 있다(C3) |
| **C3** | **협상은 hello 의 capability `exec.secret_env.v1`.** handshake 에서는 요구하지 않는다(`OPTIONAL_CAPABILITIES`) — 세션이 **lease 마다** `client.supports()` 로 보고, 없으면 **보내기 전에** `secret_env_unsupported`. 프로토콜 버전은 올리지 않는다 | 옛 guest 의 `op_exec` 는 `args.get` 으로 아는 키만 읽는다 — 새 필드를 **조용히 버리고 비밀 없이 명령을 돌린다**. 그러니 판정은 호스트가 해야 한다. handshake 에서 요구하거나 버전을 올리면 `managed.sandboxd_digest` 로 옛 이미지를 고정한 배포가 **모든 기능**을 잃는다. lease 마다 보는 것은 판정을 **그 연결의 hello** 에 묶으려는 것이다 — 연결 밖에 캐시한 판정은 재접속(Modal cold resume) 뒤에 근거가 없다. capability 목록은 digest 로 고정된 bundle 의 바이트에서 나오므로 옛 guest 가 거짓으로 주장할 수 없다 |
| **C4** | guest 는 `secret_env` 를 `env` 와 **같은 검증**(`_validate_env`)과 **같은 예약 이름 거르기**(`guest_env` 의 한 반복문)로 받는다. 예약 이름(PATH·HOME·TMPDIR)은 조용히 떨어진다. 호스트도 같은 이름을 먼저 거른다(memory·Docker 와 같다). `env` 다음에 덮는다 | 메모리 노트 "고침은 한 호출부에만 도착한다" — `{PATH, HOME, TMPDIR}` 는 오늘 **다섯 벌**이다(memory · helper_session · sandboxd session · guest · 금고의 넓은 8개). 여섯째를 만들지 않고 guest 의 기존 반복문에 층 하나를 더했다. 금고가 이미 예약 이름을 거절하므로(`secret_env_name_allowed`) 이 층은 마지막 방어선이다 — 호스트 거르기를 건너뛰는 raw 클라이언트 테스트가 guest 쪽을 따로 문다 |
| **C5** | **오류 경로는 코드만.** 잘못된 `secret_env` 는 `command_environment_invalid`·`request_invalid`, 실행 실패는 `command_not_found` 등 기존 상수. 결과 가리기는 실행기(`ResolvedSecrets.scrub_bytes`)에만 둔다 — guest 에 사본을 두지 않는다 | guest 는 값을 모르는 척하는 것이 아니라 값을 **말할 자리가 없다**: `GuestError` 는 `(kind, code)` 만 싣고 `_dispatch` 의 나머지 분기도 상수다. 가리기를 guest 에 복제하면 두 규칙이 갈라진다 |
| **C6** | 저장 없음 · **마이그레이션 없음**(예약 084 는 쓰지 않았다) | guest 는 exec 인자를 저장하지 않고 원장은 revision 만 쓴다(§2) |
| **C7** | 새 플래그 없음. Q6 의 `coding_model.secret_broker` 가 꺼져 있으면 실행기가 `secret_env` 를 채우지 않으므로 RPC 는 오늘과 같다 | S9. 관리형은 C1 로 계속 거절하므로 켜도 운영 행동이 바뀌는 곳이 없다 |
| **C8** | PTY 는 비밀을 받지 않는다(`pty.create` 에 env 가 없다, 그대로) | 터미널 출력은 실행기의 가리기를 지나지 않는 스트림이다. 범위 밖 |

📌 `guest.py` 가 바뀌었으므로 **bundle digest 가 바뀐다.** `SandboxdExpectation.bundled()` 는 저절로 따라간다.
`managed.sandboxd_digest` 로 옛 digest 를 고정한 배포는 그대로 돌고(C3), 비밀만 거절된다.

### 거절 코드 (새 코드 없음)

| 코드 | 언제 |
|---|---|
| `secret_env_unsupported` | attachment 가 기밀 채널을 선언하지 않았다(C1) · guest 가 `exec.secret_env.v1` 을 광고하지 않았다(C3) |
| `command_environment_invalid` · `request_invalid` | guest 가 받은 `secret_env` 의 모양이 틀렸다(C4·C5) |

## 4. 관리형을 열려면 (증거 목록)

> 📌 **상태 (2026-10-02, [Q6c](Q6C_MANAGED_SECRET_CHANNEL_DESIGN_261002.md) MS2·MS3):** 이 목록을 **코드로 옮겼다.**
> 1~3 은 바인딩이 다는 `StdioRelayEvidence(tls_verified, stdin_retention_source, smoke_record)` 가 되었고, 4 는
> `_Attachment.confidential_channel = (provider 별 opt-in sandbox.managed.secret_env_providers) AND (증거)` 가 되었다.
> 설정만으로는 열리지 않는다는 C1 의 뜻은 그대로다 — 증거 없는 opt-in 은 provider 가 시작하지 않는다.
> **1~3 은 여전히 하나도 충족되지 않았다**(벤더 SDK 가 venv 에도 저장소에도 없다). 실계정 smoke 체크리스트는 Q6c §5,
> 아무도 돌리지 않았다. 그래서 E2B·Modal 은 오늘도 `secret_env_unsupported` 다.

C1 을 provider 하나에 대해 뒤집는 커밋은 아래를 **같이** 단다. 설정 키로 대신하지 않는다.

1. 그 벤더의 **SDK 바인딩이 저장소에 있다** — `open_stdio` 가 쓰는 전송이 TLS 이고 인증서 검증을 끄는 경로가 없음을 테스트가 고정
2. 벤더 문서 또는 계약으로 **exec stdin 이 보존·로깅되지 않는다**는 근거(링크·날짜). 없으면 열지 않는다
3. 실계정 smoke — B2 게이트(설계 "남은 일")의 보안 검토 항목과 함께
4. 그 provider 의 `_Attachment.confidential_channel` 을 provider 이름으로 판정 + 이 문서 표 갱신

> ⚠️ 벤더는 sandbox 안의 프로세스 환경을 어차피 볼 수 있다. 관리형의 기밀성 질문은 "벤더로부터"가 아니라
> **"벤더의 전송·로그를 거쳐 제3자에게"**다. 그래서 위 2 가 핵심이다.

## 5. 뒤의 소비자가 쓰는 법

- **Q11 — stdio MCP 서버를 샌드박스 안에서.** `exec` 은 한 번 돌고 끝나는 호출이라 장기 stdio 서버를 싣지 못한다.
  필요한 것은 장기 프로세스 op(가칭 `proc.*`)이고, 그 op 는 **같은 규칙**을 따른다: 별도 `secret_env` 필드 ·
  `guest_env` 의 같은 층 · 자기 capability(`proc.secret_env.v1`)를 handshake 가 아니라 lease 마다 확인 ·
  attachment 의 `confidential_channel`. 서버 출력은 MCP 러너가 이미 가린다(Q11 M9).
- **Q14c — 관리형 샌드박스 안의 브라우저.** 관리형이므로 §4 가 먼저다. 그 전까지 Q14c 의 로그인은 C1 에서 멈춘다.
- **Q16** 은 샌드박스를 거치지 않는다(브리지는 비밀을 받지 않는다, Q16 B8). 해당 없음.

## 6. 표면

- 코드: `neos/coding/sandboxd/guest.py`(`SECRET_ENV_CAPABILITY`, `guest_env` 층) ·
  `sandboxd/client.py`(`OPTIONAL_CAPABILITIES`, `SandboxdClient.supports`) ·
  `sandboxd/session.py`(C1·C3 판정, 필드) · `sandbox/managed/provider.py`(`confidential_channel = False`) ·
  `sandboxd/local.py`(`confidential_channel`, 테스트용 `guest_path`·`stderr_path`)
- 테스트: `tests/coding/sandbox/test_sandboxd_secret_channel.py` — 왕복은 **녹음 채널**로 오간 바이트 전체에서
  값을 찾는다(로그 포매터가 아니라 선 위에서). 옛 guest 는 지금 guest 에서 광고 한 줄만 뺀 파생본이다 —
  메모리 노트 "가짜는 없는 필드를 지어낼 수 있다"를 따라 진짜가 하지 않는 일을 하는 가짜를 만들지 않았다
- 설정·API·이벤트 kind·마이그레이션: **없다**

## 7. 남은 것

- 관리형 열기(§4) — 판정 자리는 Q6c 가 놓았다. 남은 것은 벤더 바인딩·근거·실계정 smoke([Q6c §5·§7](Q6C_MANAGED_SECRET_CHANNEL_DESIGN_261002.md))
- Q11 장기 프로세스 op(§5)
- 에이전트별 부여(Q17) · 프롬프트에 이름 목록 — Q6 §5 그대로
