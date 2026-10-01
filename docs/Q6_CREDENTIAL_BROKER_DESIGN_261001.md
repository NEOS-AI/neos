# Q6 자격증명 브로커 — 설계 (2026-10-01)

> **지위:** Q6a 착지(플래그 off). 설계와 코드가 어긋나면 코드가 이긴다.
> 상위: [로드맵 §1 Q 행](DEEP_ANALYSIS_HARNESS_ROADMAP.md) · [dots 분석 §4.2 Q6](OPENAI_DOTS_ANALYSIS_260930.md).
> 결정 S1~S9 는 위임받아 Claude 가 골랐다(Q2·Q4b 와 같은 방식). 사람이 뒤집을 수 있다.

## 1. 무엇을 사는가

dots F13 — "저장된 비밀을 **모델에 보이지 않고** 쓴다". 지금 NEOS 에는 비밀 참조가 없다. `redact.py` 는
**저장 전** 값을 가리는 것이지 모델 앞의 차단이 아니다.

Q6 은 Q11(MCP)·Q14(브라우저)·Q16(기기 브리지)의 공통 선행이다. 그래서 Q6a 가 착지시키는 것은
**재사용할 부품**과 **첫 소비자 하나**다:

| 부품 | 자리 | 뒤의 소비자가 쓰는 법 |
|---|---|---|
| 참조 문법 `secret://<name>` | `neos/coding/secrets.py` `secret_ref_name` | 자기 도구 인자에서 같은 함수로 찾는다 |
| 사용자 금고(봉인 저장) | `SecretStore` — 메모리·Postgres 가 같은 계약 | `resolve(owner_id, names)` |
| 풀린 값의 수명 | `ResolvedSecrets` — 실행기 지역 변수, `scrub_*` 로 결과를 가린다 | 실행 직전에 풀고 결과를 돌려주기 전에 가린다 |
| 게이트 규칙 | `carries_secret_refs` → 사람 승인 또는 소유자 allow | 같은 판정 자리를 탄다 |
| 첫 소비자 | `execute.v1` 의 `env` 값 | — |

## 2. 결정

| # | 결정 | 이유 |
|---|---|---|
| **S1** | 참조는 **값 전체**여야 한다(`secret://github`). 문자열 안에 끼운 참조(`token=secret://x`)는 풀지 않는다 | 부분 치환은 어디까지가 비밀인지를 실행기가 추측하게 만든다. 가리기(S6)도 값 단위가 정확하다 |
| **S2** | 첫 소비자는 `execute.v1` 의 **`env` 값만**이다. argv·stdin·파일 내용의 참조는 **풀지 않고 문자 그대로** 간다 | argv 는 승인 화면·감사·프로세스 목록에 남는다. 환경변수는 셋 다 피한다. 문자 그대로의 `secret://x` 는 평문이 아니므로 새는 것이 없다 |
| **S3** | 비밀마다 **묶인 환경변수 이름**(`env_name`)이 하나 있고, 다른 이름에 넣으면 거절한다(`secret_env_name_mismatch`) | 모델이 비밀을 `GIT_SSH_COMMAND`·`NODE_OPTIONS` 같은 **해석되는** 변수로 옮기는 길을 막는다. 어디에 쓸지는 비밀의 주인이 정한다 |
| **S4** | 금고는 **사용자** 키(`user_id`)다. 에이전트가 연 태스크도 소유자의 금고를 쓴다 | Q2 규칙과 같다 — Q13 설계 §5 "에이전트 권한은 소유자의 부분집합". 에이전트별 부여(grant)는 Q17 조직 에이전트와 함께 연다. 📌 금고는 "에이전트에 딸린 데이터"가 아니라 사용자의 것이므로 `agent_id` 규칙(Q13)에 어긋나지 않는다 |
| **S5** | 값은 AES-GCM 으로 봉인한다. 키는 `NEOS_SECRET_BROKER_KEY` 에서 HMAC 으로 파생하고, AAD 는 `user_id:name` 이다 | 원장·DB 덤프가 새도 값이 없다. AAD 가 다른 사용자·다른 이름의 행을 가져다 쓰는 것을 막는다. 암호는 `managed/crypto.py` 의 것을 **그대로** 쓴다(사본 없음) |
| **S6** | 결과(stdout·stderr)는 돌려주기 전에 **풀린 값 자체**를 `<redacted:secret://name>` 으로 바꾸고, 그 위에 `redact.py` 규칙을 건다. 잘린 출력의 **끝에 걸친 접두**(4자 이상)도 가린다 | 정규식은 모르는 모양의 비밀을 놓친다. 값을 아는 자리는 실행기뿐이다. 잘림 경계에 걸친 앞부분도 비밀의 일부다 |
| **S7** | 참조를 실은 호출은 **사람 승인 또는 소유자의 allow 규칙**으로만 돈다. 운영자 allow 목록·"항상 허용" 기억·auto 모드는 넘지 못한다. unattended(autonomous)에서는 D-L1 접기로 DENY — 소유자 allow 가 있으면 돈다 | dots Q6 행: "참조 사용은 Q2 규칙의 대상이다". 사용자 require 와 같은 자리(운영자 allow 앞)에 둔다 — 좁히기만 |
| **S8** | **자식은 비밀을 못 쓴다**(`policy_secret_ref_child`) | 자식은 승인할 사람에게 닿지 못하고(CHILD-GATE), 포트에는 풀 소유자 맥락이 없다. 최소 권한 |
| **S9** | 플래그 off 면 **오늘과 바이트가 같다** — 검증기는 비허용 env 이름을 그대로 거절하고 게이트·실행기는 참조를 모른다 | S9(트랙 I 의 방법): 켜는 커밋만 경계가 된다 |

### 거절·실패 코드

| 코드 | 언제 | 성격 |
|---|---|---|
| `policy_secret_ref_child` | 자식 호출에 참조가 있다 | 게이트 DENY(자식 원장 `tool.denied`) |
| `secret_not_found` | 소유자 금고에 그 이름이 없다 | 도구 결과 `denied` — 모델이 사용자에게 등록을 부탁할 수 있다 |
| `secret_env_name_mismatch` | 비밀의 `env_name` 과 다른 변수에 넣었다 | 도구 결과 `denied` |
| `secret_store_unavailable` | 금고를 읽지 못했다 | 도구 결과 `error`. 풀지 못한 값으로 **돌리지 않는다** |
| `secret_env_unsupported` | 그 샌드박스 provider 가 비밀 env 를 못 싣는다(sandboxd·managed) | 도구 결과 `denied` — 아래 §3 |

## 3. 샌드박스 경계

`CommandRequest.secret_env` 는 `env` 와 **다른 필드**다(`repr=False`). `env` 의 이름 허용 목록을 건드리지 않고,
비밀만 따로 싣는다.

| provider | 싣는 법 | 상태 |
|---|---|---|
| memory(development) | 자식 프로세스 환경에 직접 | ✅ |
| Docker | `docker exec --env NAME`(값 없이) + docker CLI 프로세스의 환경에 값 — **호스트 `ps` 에 값이 보이지 않는다** | ✅ |
| sandboxd · managed | 거절 `secret_env_unsupported` | 📐 RPC 에 비밀 채널을 더할 때 연다 |

> ⚠️ 오늘 `execute.v1` 은 네트워크 클라이언트를 막고 Docker 는 `network=none` 이다. 그래서 첫 소비자의 실용은 좁다
> (오프라인 라이선스 키·로컬 서명 도구 정도). **Q6a 의 값은 부품이다** — Q11 의 MCP 커넥터 인증, Q14 의 로그인,
> Q16 의 브리지가 같은 `resolve → 실행 → scrub` 를 쓴다.

## 4. 표면

- 설정: `coding_model.secret_broker`(기본 `False`) · `coding_model.secret_broker_max`(사용자당 상한, 기본 50) ·
  `secrets.secret_broker_key`(`NEOS_SECRET_BROKER_KEY`, 32자 이상 — 켰는데 없으면 시작하지 않는다)
- 마이그레이션 077 `user_secrets`(user_id · name · env_name · ciphertext · created_at · updated_at, `(user_id, name)` 유일)
- API(꺼져 있으면 라우트가 **없다**):

  ```
  GET    /api/v1/coding/secrets            # 이름·env_name·시각만. 값은 어떤 응답에도 없다
  PUT    /api/v1/coding/secrets/{name}     # {value, env_name} — 만들거나 바꾼다
  DELETE /api/v1/coding/secrets/{name}
  ```
- 모델에게 알리는 법: Q6a 는 프롬프트를 바꾸지 않는다(S9). 사용자가 지시에 "GH_TOKEN 은 `secret://github`" 라고
  적는다. 이름 목록을 프롬프트에 싣는 것은 켠 뒤의 결정이다

## 5. 남은 것

- **Q6b** sandboxd·managed 의 비밀 채널 · 에이전트별 부여(Q17 과 함께) · 프롬프트에 이름 목록
- **Q11·Q14·Q16** 이 이 부품을 소비한다 — 각자의 실행기 자리에서 `resolve → 실행 → scrub`
