# Q6c 관리형 샌드박스 비밀 채널 — 설계 (2026-10-02)

> **지위:** Q6c 착지 — **플래그 off · provider 별 opt-in · 증거 없이는 열리지 않음.** 실계정 smoke 는 **돌리지 않았다**(§5).
> 설계와 코드가 어긋나면 코드가 이긴다.
> 상위: [Q6 설계 §3](Q6_CREDENTIAL_BROKER_DESIGN_261001.md) · [Q6b 설계 C1·§4](Q6B_SANDBOX_SECRET_CHANNEL_DESIGN_261002.md) ·
> 관리형 신뢰 모델 [B2 설계](MANAGED_SANDBOX_B2_DESIGN_260915.md).
> 결정 MS1~MS8 은 위임받아 Claude 가 골랐다(Q6 의 S1~S9, Q6b 의 C1~C8 과 같은 방식). 사람이 뒤집을 수 있다.

## 1. 무엇을 사는가

Q6b 는 sandboxd `exec` 에 별도 `secret_env` 필드를 만들고, 관리형(E2B·Modal)은 C1 로 막았다 —
"벤더 exec stdio 중계가 사적이라는 증거가 저장소에 없다". Q6b §4 는 여는 데 필요한 증거 넷을 적었다.

Q6c 는 **그 §4 를 코드로 옮긴다.** 즉 증거가 생겼을 때 관리형 provider 하나를 여는 일이
"C1 을 고치는 코드 변경"이 아니라 **"바인딩이 증거를 달고 운영자가 그 provider 이름을 적는 일"**이 되게 한다.
오늘 저장소에는 벤더 SDK 바인딩이 없으므로 **운영에서 새로 비밀을 싣는 provider 는 여전히 없다.**

| provider | 기본(오늘) | 열리는 조건 |
|---|---|---|
| memory · Docker · sandboxd(`LocalSandboxd`) | (Q6a·Q6b) | 그대로 |
| managed — E2B | ❌ `secret_env_unsupported` | `secret_env_providers: [e2b]` **그리고** E2B 바인딩의 `StdioRelayEvidence` |
| managed — Modal | ❌ `secret_env_unsupported` | `secret_env_providers: [modal]` **그리고** Modal 바인딩의 `StdioRelayEvidence` |

## 2. 확인한 것 · 확인하지 못한 것

- **벤더 SDK 가 공유 venv 에 없다.** `/Users/ywsung/Desktop/neos/.venv/lib/python3.12/site-packages/` 에
  `e2b`·`modal` 패키지가 없고(`import e2b` · `import modal` 모두 `ModuleNotFoundError`, 2026-10-02),
  `pyproject.toml`·`uv.lock` 에도 없다. 그래서 **벤더 exec API 의 실제 인자(per-exec env, Secret 객체, stdin 스트림)를
  이 저장소에서 읽어 확인한 것은 없다.** 아래 §3 에서 벤더 표면을 말할 때는 "공개 문서에 있다고 알려진 모양"이고
  버전·이름을 인용하지 않는다 — 바인딩 PR 이 설치된 SDK 의 파일·버전으로 다시 확인해야 한다.
- 저장소에 있는 것은 **NEOS 가 요구하는 좁은 Protocol**(`E2BSdk` · `ModalSdk`, `sandbox/managed/clients/`)이다.
  NEOS 가 벤더에 보내는 것은 그 Protocol 의 인자뿐이고, 비밀과 관련된 것은 `open_stdio(ref, SANDBOXD_CONNECT_ARGV)`
  하나다 — 고정 argv 로 guest relay 를 열고, 이후 모든 요청은 그 프로세스의 **stdin 프레임**으로 간다.
- 관리형 provider·sandboxd 호스트 경로·guest 는 로깅하지 않는다(Q6b §2 그대로). 원장은 revision·cursor 만 적는다.

## 3. 운반로 — 벤더별 선택과 남는 위험

### 3.1 후보

| 후보 | 값이 지나는 곳 | 범위 | 판정 |
|---|---|---|---|
| **(a) sandboxd `exec` 프레임의 `secret_env`** — relay stdin | 벤더 exec **데이터 평면**(stdin 스트림) → guest relay → guest → 자식 프로세스 환경 | **명령 하나** | ✅ 채택(MS1) |
| (b) 벤더 per-exec env 필드(벤더 exec 호출의 env 인자) | 벤더 **제어 평면** 요청 본문 | relay 프로세스의 수명 = 채널의 수명 | ❌ |
| (c) 벤더 Secret 객체(벤더 쪽에 이름 붙여 저장) | 벤더 저장소 | 저장된 동안 | ❌ |

(b) 를 버린 이유: NEOS 는 명령마다 벤더 exec 을 부르지 않는다 — 벤더 exec 은 **relay 를 여는 한 번**뿐이다.
그 호출에 env 를 실으면 값은 relay 프로세스의 환경에 **채널이 사는 내내** 남고(guest 안 `/proc/<pid>/environ`),
그 채널로 도는 **모든** 명령이 물려받을 수 있는 자리에 놓인다. 게다가 제어 평면 요청(어떤 명령을 어떤 env 로 열었나)은
데이터 평면 바이트보다 벤더의 감사·대시보드에 남을 가능성이 높다 — 이것도 확인하지 못했다.
(c) 를 버린 이유: 벤더에 **저장**된다. Q6 의 금고는 NEOS 의 것(S5 봉인)이고, 벤더 쪽 사본은 회전·삭제를 두 곳에서 해야 한다.

### 3.2 남는 위험 (두 벤더 공통)

- **벤더는 값을 본다.** TLS 는 NEOS→벤더 엣지까지다. 벤더는 relay stdin 을 풀어 VM 안 에이전트로 넘긴다.
  Q6b §4 의 경고 그대로 — 질문은 "벤더로부터"가 아니라 **"벤더의 전송·로그를 거쳐 제3자에게"**다. 그 답(stdin 비보존)이
  `StdioRelayEvidence.stdin_retention_source` 이고, 지금 **없다.**
- **sandbox 안에서:** 값은 자식 프로세스의 환경에 있다 — 같은 uid 의 다른 프로세스가 `/proc/<pid>/environ` 을 읽을 수 있다
  (Docker·memory 와 같은 성질). guest(Python)의 메모리에는 값이 해제 뒤에도 0 으로 지워지지 않고 남을 수 있다.
- **argv·프로세스 목록:** 값은 어떤 argv 에도 없다 — 벤더가 보이는 exec 명령은 `SANDBOXD_CONNECT_ARGV` 고정이고,
  guest 는 자식에게 env 로 넘긴다. 벤더 대시보드의 "실행한 명령"에 보일 것은 relay argv 뿐이어야 한다(§5 에서 확인할 항목).

### 3.3 벤더별

| | E2B | Modal |
|---|---|---|
| 운반로 | (a) — `E2BSdk.open_stdio` 가 연 relay 의 stdin | (a) — `ModalSdk.open_stdio` 가 연 relay 의 stdin |
| 벤더 쪽 지속 | ⚠️ **pause 는 메모리를 보존한다**(`suspend_preserves_processes=True`). pause·snapshot 시점에 guest·자식 메모리에 남은 값의 잔재가 벤더 저장소의 메모리 스냅숏에 실릴 수 있다. 코드로 막을 수 없다 — §5 의 확인 항목이고, 열 때 사람이 받아들일 위험으로 적는다 | 스냅숏은 **파일시스템만**(`suspend_preserves_processes=False`). guest 는 exec 인자를 디스크에 쓰지 않는다(Q6b §2). 명령 자신이 값을 파일로 쓰는 것은 사용자 명령의 행동이다(Docker 와 같다) |
| 확인 못 한 것 | relay stdin 전송의 TLS 검증 경로 · stdin 보존/로깅 여부 · 대시보드의 exec 표시 | 같은 셋 |

## 4. 결정

| # | 결정 | 이유 |
|---|---|---|
| **MS1** | **운반로는 Q6b 의 sandboxd `exec` 프레임 `secret_env` 그대로**(relay stdin). 벤더 per-exec env·벤더 Secret 객체는 쓰지 않는다. 벤더 SDK Protocol 에 비밀 인자를 더하지 않는다 | §3.1. 범위가 명령 하나이고, 벤더 제어 평면·저장소에 값이 가지 않는다. guest 쪽 주입·예약 이름 거르기·C3 capability 판정(Q6b)을 그대로 쓴다 — 새 경로가 없으니 "고침은 한 호출부에만 도착한다"가 생길 자리도 없다 |
| **MS2** | **증거는 바인딩 코드가 단다.** `clients/base.py` 의 `StdioRelayEvidence(vendor, tls_verified, stdin_retention_source, smoke_record)` 를 SDK 바인딩이 `sdk.stdio_relay_evidence` 로 선언한다. `proves()` 는 vendor 일치 · `tls_verified is True` · 근거가 `https://` · smoke 기록이 비지 않음을 **모두** 요구한다. 그 타입이 아닌 것(dict·`True`)은 증거가 아니다. client 는 `secret_relay_evidence` 로 내보이고 `secret_relay_proven(client)` 가 판정한다 — 속성이 없는 client 는 거짓 | Q6b §4 의 1~3 을 필드로 옮겼다. "켤 수 있는 스위치는 언젠가 켜진다"(`profiles.py`) — 그래서 증거는 **설정이 아니라 리뷰를 거치는 바인딩 코드**에 산다. 바인딩이 없는 오늘은 이 값을 내는 운영 코드가 없다 |
| **MS3** | **운영자 opt-in 은 provider 별 명시 목록** `sandbox.managed.secret_env_providers`(기본 `()`). 값은 `e2b`·`modal` 만, 중복 거절, `coding_model.secret_broker` 가 꺼져 있으면 시작 거절. 이름을 적었는데 바인딩이 증거를 달지 않았으면 **provider 가 시작하지 않는다**(`managed_secret_channel_unproven:<name>`) | 증거와 opt-in 은 **AND** 다 — 증거만 있으면 운영자가 모르는 사이 열리고, opt-in 만 있으면 Q6b C1 이 금지한 "설정으로 여는 스위치"가 된다. 증거 없는 opt-in 을 조용히 거절로 남기면 "켜져 있다"고 적힌 채 아무것도 하지 않는 낡은 플래그가 된다(메모리 노트 "낡은 면제 플래그는 가드를 조용히 끈다") — 그래서 시끄럽게 실패한다. 브로커 없는 opt-in 도 같은 이유로 거절한다 |
| **MS4** | 판정은 두 번: **생성자**(`ManagedSandboxProvider.__init__`, `for_lease` 뷰도 같은 생성자를 지난다)와 **execute 마다** `_Attachment.confidential_channel`(`opt-in and secret_relay_proven(client)`). C3(guest 가 `exec.secret_env.v1` 을 광고하는가)는 그 뒤에 그대로 lease 마다 본다 | 생성자만 보면 바인딩이 증거를 거둔 뒤에도 열린 채다. attachment 만 보면 증거 없는 opt-in 이 조용해진다(MS3). `for_lease` 가 opt-in 을 잊으면 실행 lease 의 뷰가 거절한다 — 테스트가 문다 |
| **MS5** | **플래그 off 는 오늘과 바이트가 같다.** 같은 코드 `secret_env_unsupported`, 같은 자리(연결·프레임 전), 비밀 없는 `exec` 프레임의 키 집합도 같다 | S9 · Q6b C7. 켜는 커밋(바인딩 + 설정)만 경계가 된다 |
| **MS6** | Q6 의 보증은 **코드를 바꾸지 않고** 그대로다: 값은 argv·전사·원장·이벤트·체크포인트·로그·repr 에 없다 · 출력은 실행기가 가린다(값 자체 + 잘린 끝 접두, S6) · S7 승인 게이트 · S8 자식 거절 | Q6c 는 sandbox 경계의 판정만 바꾼다. 실행기·게이트·레지스트리·자식 경로는 손대지 않았다. 관리형 위에서 S6 가 그대로인지는 테스트가 relay 를 지난 출력으로 다시 확인한다 |
| **MS7** | 마이그레이션·이벤트 kind·API·프롬프트 변경 **없음**(예약 089 는 쓰지 않았다) | 저장하는 것이 없다 |
| **MS8** | **실계정 smoke 전에는 열지 않는다.** smoke 는 사람이 §5 체크리스트로 돌리고, 그 기록 id 가 `smoke_record` 가 된다. E2B 의 pause 메모리 잔재(§3.3)는 smoke 가 **배제할 수 없는** 위험이다 — E2B 를 열 때는 그 위험을 받아들인다는 사람의 결정이 같이 있어야 한다 | Claude 는 실계정을 돌릴 수 없다. 돌려보지 않은 벤더 호출은 구현된 것처럼 보일 뿐이다(`clients/base.py` docstring) |

### 거절·실패 코드

| 코드 | 언제 | 성격 |
|---|---|---|
| `secret_env_unsupported` | 관리형인데 opt-in 이 없다 · 증거가 없다(또는 시작 뒤 거둬졌다) · guest 가 capability 를 광고하지 않는다 | 도구 결과 `denied` (Q6 그대로) |
| `managed_secret_channel_unproven:<name>` | opt-in 했는데 그 provider 의 바인딩이 증거를 달지 않았다 | provider 생성 실패(`SandboxUnavailable`) — **새 코드** |

## 5. 실계정 smoke 체크리스트 (사람이 돌린다 — 미실행)

> 이 문서를 쓴 시점(2026-10-02)에 **아무도 돌리지 않았다.** 결과를 이 절 아래에 날짜와 함께 적는다.
> 한 항목이라도 FAIL 이면 그 provider 를 열지 않는다(`secret_env_providers` 에 적지 않는다).

### 5.0 준비

1. **바인딩 PR**(별도) — 그 벤더 SDK 를 `pyproject.toml` 에 고정하고(패키지 이름은 인덱스에서 확인한다), `E2BSdk`/`ModalSdk`
   를 구현한다. 그 PR 은 설치된 SDK 의 파일·버전을 인용해 `open_stdio` 가 쓰는 전송을 적는다.
2. 바인딩 PR 의 테스트가 **TLS 검증을 고정**한다: SDK 의 HTTP/gRPC 클라이언트가 인증서 검증을 켠 채 만들어지고,
   검증을 끄는 인자·환경 변수 경로가 없음을. (`tls_verified=True` 의 근거)
3. 벤더 문서·계약에서 **exec stdin 을 보존·로깅하지 않는다**는 문장을 찾아 링크와 확인 날짜를 적는다. 없으면 벤더에
   서면으로 묻고 답을 보관한다. 답이 없으면 **여기서 멈춘다.** (`stdin_retention_source` 의 근거)
4. staging 계정·staging NEOS 배포. 운영 계정·운영 사용자 금고는 쓰지 않는다.
5. canary 값 하나: `q6c-canary-$(openssl rand -hex 16)`. 다른 어디에도 쓰지 않은 값이어야 검색이 뜻을 갖는다.
   staging 사용자 금고에 `PUT /api/v1/coding/secrets/q6c_canary {"env_name": "CANARY_TOKEN", "value": "<canary>"}`.
   (`CANARY_TOKEN` 이 금고 규칙상 허용 이름인지 먼저 확인한다)

### 5.1 설정

```yaml
sandbox:
  provider: managed
  managed:
    enabled: true
    provider: e2b                 # 또는 modal — 한 번에 하나
    secret_env_providers: [e2b]
coding_model:
  secret_broker: true
```

바인딩의 `smoke_record` 에는 **지금 돌리는 smoke 의 식별자**(예: `smoke-q6c-e2b-2026-10-XX-<이름>`)를 넣는다. FAIL 이면
그 바인딩 커밋은 병합하지 않는다 — 기록이 PASS 한 run 만 가리키게.

- [ ] `secret_env_providers` 를 비운 채 시작하면 같은 호출이 `secret_env_unsupported` 로 거절된다(플래그 off 확인)
- [ ] `smoke_record=""` 로 바꾸고 시작하면 `managed_secret_channel_unproven:<name>` 으로 시작하지 않는다

### 5.2 실행

코딩 태스크 하나에서 사람이 승인해(S7) 다음을 돌린다. 워크스페이스에 `q6c.py`:

```python
import hashlib, os, sys
print(hashlib.sha256(os.environ["CANARY_TOKEN"].encode()).hexdigest())
print(os.environ["CANARY_TOKEN"])
print(os.environ["CANARY_TOKEN"], file=sys.stderr)
```

`execute.v1 {"argv": ["python3", "q6c.py"], "env": {"CANARY_TOKEN": "secret://q6c_canary"}}`

| # | 볼 곳 | PASS 조건 |
|---|---|---|
| R1 | 도구 결과 | 첫 줄이 canary 의 sha256 과 같다(값이 도착했다). 둘째 줄·stderr 는 `<redacted:secret://q6c_canary>` |
| R2 | 잘림 | 출력 상한 바로 앞에 canary 가 걸리게 한 번 더 돌린다(`'A' * (max_output_bytes - 10)` + canary) — 미리보기 끝이 `<redacted:…>` |
| R3 | NEOS DB | 코딩 원장·도구 호출·이벤트·체크포인트·관리형 원장(057)·할당(045) 테이블 덤프를 canary 로 `grep` → **0건** |
| R4 | NEOS 로그·추적 | 앱 로그, OTel/Phoenix 스팬, Celery 로그를 canary 로 검색 → **0건** |
| R5 | 벤더 대시보드 — 실행 명령 | sandbox 의 프로세스/명령 기록에 보이는 것은 `/opt/neos/neos-sandboxd connect --socket /run/neos/sandboxd.sock` 뿐. canary 없음 |
| R6 | 벤더 대시보드·로그 — 전부 | sandbox 로그, 앱 로그, 감사 로그, 사용량 화면, 지원용 이벤트 뷰를 canary 로 검색 → **0건**. 벤더 API 의 sandbox 목록·메타데이터/태그 응답도 → **0건** |
| R7 | TLS | 바인딩을 신뢰하지 않는 CA 의 가로채기 프록시(mitmproxy 등) 뒤에서 `open_stdio` → **연결이 실패해야** PASS |
| R8 | sandbox 안 잔재 | 명령이 끝난 뒤 같은 sandbox 에서 `grep -l <canary> /proc/*/environ` → 0건(값을 쥔 프로세스가 남지 않았다) |
| R9 | E2B 만 — pause | pause → resume 뒤 R8 반복. **메모리 스냅숏 안의 잔재는 밖에서 확인할 수 없다** — 결과와 함께 "받아들임/거절"을 사람이 적는다(MS8) |
| R10 | Modal 만 — 스냅숏 | `snapshot_filesystem` → 그 이미지로 새 sandbox → 파일시스템 전체 `grep -r <canary> /` → 0건 |
| R11 | 거둬들임 | 바인딩에서 증거를 빼고 재배포 → 같은 호출이 `secret_env_unsupported` |

마친 뒤: canary 비밀을 `DELETE` 하고, 벤더 staging sandbox 를 모두 지운다.

### 5.3 기록

```
<날짜> <provider> <SDK 버전> <돌린 사람> — R1..R11: PASS/FAIL, R9 결정, stdin 근거 링크
```

## 6. 표면

- 코드: `neos/coding/sandbox/managed/clients/base.py`(`StdioRelayEvidence` · `declared_relay_evidence` ·
  `secret_relay_proven`) · `clients/e2b.py`·`clients/modal.py`(`secret_relay_evidence`) ·
  `sandbox/managed/provider.py`(`secret_channel` 인자, 생성자 판정, `_Attachment.confidential_channel`, `for_lease` 전파,
  factory 의 provider 별 opt-in)
- 설정: `sandbox.managed.secret_env_providers`(기본 `()`) + `AppConfig.validate_managed_secret_channel`
- 테스트: `tests/coding/sandbox/test_managed_secret_channel.py` — 가짜 벤더 SDK 를 **기록 proxy** 로 감싸 벤더 SDK 에 간
  모든 호출의 인자와 relay 를 오간 바이트 전부에서 값을 찾는다. 값은 relay stdin 의 `exec` 프레임 `secret_env` 에만 있어야 한다
- 마이그레이션·API·이벤트 kind: **없다**

## 7. 남은 것

- **벤더 SDK 바인딩**(E2B·Modal 각각) — §5.0 의 1·2. 그 전에는 어느 provider 도 열 수 없다
- 벤더의 stdin 비보존 근거(§5.0 의 3)와 실계정 smoke(§5.1~5.3) — 사람
- E2B pause 메모리 잔재를 받아들일지의 결정(MS8)
- Q11 장기 프로세스 op · Q14c 관리형 브라우저는 같은 `confidential_channel` 판정 위에 선다(Q6b §5)
