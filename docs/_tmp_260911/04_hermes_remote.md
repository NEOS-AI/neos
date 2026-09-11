# Hermes Remote (Slack/Discord) → NEOS 갭 분석

Hermes 게이트웨이는 **개인 코딩 에이전트를 채팅에서 원격 조종**하는 런타임이다. NEOS `ChannelGateway`는 **이미 있는 OpenClaw 스타일 채널 레이어**로, 같은 프로세스에서 `MultiAgentWorkflow.execute_workflow()`만 호출한다. 교체가 아니라 보강 대상이다.

코딩 에이전트(`neos/coding/`, `POST /api/v1/coding/tasks`)는 채널 경로에 **전혀 연결되지 않았다**. Slack/Discord에서 코딩 루프를 띄울 수 없다.

작성: explore 서브에이전트 `Analyze Hermes remote channels` (2026-09-11). 메인 에이전트가 파일로 고정.

## 1. Hermes Gateway + 채널 아키텍처

```
플랫폼 소켓 (Slack Socket Mode / Discord Gateway)
        │  adapter.connect() + Bolt/discord.py listeners
        ▼
adapter._handle_*  (mention/allow/ignore/dedup/media)
        │  BasePlatformAdapter.handle_message(MessageEvent)
        ▼
GatewayInboundMixin._hm_admit_event
  ignored-channel → startup queue → plugin hook → authz/pairing
        ▼
session bind: build_session_key(SessionSource) + SessionStore
        ▼
busy/lease (run_busy.py / turn_lease.py)
        ▼
slash? → GatewaySlashCommandsMixin
else    → GatewayTurnMixin + TurnRunner (agent turn)
        ▼
stream_consumer / send_draft / reactions / Block Kit
        ▼
DeliveryRouter (origin / home / explicit)
```

핵심 파일 (Hermes `/Users/yeonwoosung/Desktop/hermes-agent`):

| 역할 | 경로 | 심볼 |
|------|------|------|
| 엔트리 | `gateway/run.py` | `GatewayRunner`, `start_gateway()` |
| 인바운드 | `gateway/run_inbound.py` | `GatewayInboundMixin._hm_admit_event` |
| 턴 | `gateway/run_turn.py`, `run_turn_runner.py` | `GatewayTurnMixin`, `TurnRunner` |
| 세션 | `gateway/session.py` | `SessionSource`, `build_session_key` |
| 지속성 | `gateway/session_persistence.py`, `session_recovery.py` | `resume_pending` |
| 권한 | `gateway/authz_mixin.py`, `pairing.py` | `_is_user_authorized`, `PairingStore` |
| 바쁨 | `gateway/run_busy.py`, `turn_lease.py` | `GatewayBusySessionMixin`, `SessionTurnLeaseRegistry` |
| 슬래시 | `gateway/slash_commands.py` | `GatewaySlashCommandsMixin` |
| 배달 | `gateway/delivery.py` | `DeliveryRouter` |
| Slack | `plugins/platforms/slack/{adapter,block_kit,plugin.yaml}` | `SlackAdapter` |
| Discord | `plugins/platforms/discord/{adapter,recovery}.py` | `DiscordAdapter` |
| 계약 | `gateway/platforms/base.py`, `ADDING_A_PLATFORM.md` | `handle_message`, `send_exec_approval` |

NEOS 대응:

```
main.py lifespan
  → SlackAdapter / DiscordAdapter / TelegramAdapter.start()
  → receive_message() → ChannelMessage
  → ChannelGateway.dispatch()
  → MultiAgentWorkflow.execute_workflow(use_checkpointer=True)
  → send_response(channel_id, text)
```

`ChannelGateway`는 채널별 `CircuitBreaker` + 워크플로 직접 호출만 한다. 세션 키·AuthZ·슬래시·승인 카드·미디어·busy lock이 없다.

## 2. 핵심 요소 카탈로그

성숙도: **H** = Hermes 실사용급 / **N0** = NEOS 없음 / **N1** = 골격만 / **N2** = 동작하나 정책 없음

| 요소 | Hermes 파일 | 동작 | NEOS 대응 | 성숙도 |
|------|-------------|------|-----------|--------|
| 인바운드 정규화 | `platforms/event.py` `MessageEvent` | text/command/media/reply/thread | `ChannelMessage` | H / N1 |
| 세션 키 | `session.build_session_key` | platform+chat+thread+user | `slack_{channel}` / `discord_{channel}` | H / N1 |
| 유저 매핑 | `SessionSource.user_id` | 플랫폼 유저 = principal | 전원 `CHANNEL_BOT_USER_ID` | H / N0 |
| Allowlist | `authz_mixin._is_user_authorized` | env ∪ pairing ∪ roles | 없음 | H / N0 |
| Pairing | `pairing.py` | DM 8자 코드 | 없음 | H / N0 |
| Mention gate | Slack/Discord `_handle_message` | 기본 채널은 @멘션 필요 | 없음 | H / N0 |
| Ignored/allowed channels | 어댑터 설정 | 게이트 최우선 drop | 없음 | H / N0 |
| Thread affinity | Slack `thread_ts`; Discord auto-thread | 스레드 = 세션 | 채널 단위만 | H / N0 |
| Busy/queue | `run_busy.py` | interrupt/queue/steer | 동시 메시지 각각 워크플로 | H / N0 |
| Turn lease | `turn_lease.py` | session_id 직렬화 | 없음 | H / N0 |
| 재시작 재개 | `session_recovery` + `resume_pending` | dirty shutdown 시 auto-continue | LangGraph checkpointer만 | H / N1 |
| Reaction ACK | `on_processing_start/complete` | 👀 → ✅/❌ | 없음 | H / N0 |
| Streaming | `send_draft` | 메시지 edit | 채널은 최종 텍스트만 | H / N0 |
| Slash | `slash_commands*.py` | `/stop /approve /model /reset` | 없음 | H / N0 |
| 채팅 승인 | `send_exec_approval` | 버튼 또는 `/approve` | HTTP approval API만 | H / N1 |
| Media in/out | files.info / attachments | 캐시 후 주입 / 업로드 | 텍스트만 | H / N0 |
| Home channel | `*_HOME_CHANNEL` + DeliveryRouter | cron/알림 목적지 | 없음 | H / N0 |
| 코딩 에이전트 원격 | Hermes 자체가 그 에이전트 | 채팅 = 코딩 루프 | 채널→워크플로만 | H / N0 |
| Voice | Discord `VoiceReceiver` | STT/TTS | 없음 | extra |
| Tests | Hermes 다수 | 게이트/세션 회귀 | 채널 어댑터 테스트 **없음** | H / N0 |

## 3. Slack 상세

**전송:** Socket Mode만 (`SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN`). HTTP Events API 서버는 구현되어 있지 않다.

**리스너:** `message`, `app_mention`(ts 중복 제거), `file_shared`, `reaction_*`, Assistant 수명주기, catch-all ack.

**스레드:** 세션 키에 `thread_ts` + workspace `scope_id`. @mention한 스레드는 이후 멘션 없이 wake. `SLACK_THREAD_REQUIRE_MENTION` / `SLACK_STRICT_MENTION`으로 끔.

**Mention 정책 (기본 require_mention=true):**
- 1:1 IM만 멘션 면제. MPIM은 채널 게이트.
- `allowed_channels` 밖이면 침묵.
- `free_response_channels` 또는 require_mention=false면 자유 응답.
- 타인 선두 `@`면 무시.

**ACK:** 처리 시작 `:eyes:`, 완료 `:white_check_mark:` / `:x:`.

**Block Kit:** opt-in. 50블록/3000자 초과 시 평문. 승인/clarify/model picker는 action handler.

**NEOS Slack:** Socket Mode + `@app.message()`만. `session_id=slack_{channel}`, 스레드/`thread_ts` 미사용, 멘션/allowlist/리액션/슬래시/파일 없음. 응답은 `chat_postMessage` 3000자 분할, 스레드 미고정.

교차검증: `neos/api/channels/adapters/slack.py`에 `REQUIRE_MENTION`/`thread_ts`/`allowed_users` 문자열 없음.

## 4. Discord 상세

**전송:** discord.py Gateway. Intents: `message_content`, DM/guild messages, allowlist 시 `members`, **항상 `voice_states`**.

**Admission:** self/비-default 타입 drop. 기본 fail-closed + 경고. 서버는 `DISCORD_REQUIRE_MENTION=true`. `ignored_channels`는 멘션이 있어도 침묵.

**스레드:** 기본 `DISCORD_AUTO_THREAD=true` — 채널 @멘션마다 스레드 생성. 실패 시 부모 채널에 답하지 않음.

**슬래시:** on_message와 동일 게이트. 거부 시 ephemeral.

**Voice:** 코어 원격 호출이 아님. 가져오지 말 것.

**NEOS Discord:** `Intents.default()` + `message_content`만. `session_id=discord_{channel_id}`. 멘션/길드 스코프/스레드/슬래시/첨부 없음. 응답은 채널 top-level `send`.

## 5. 세션 / 권한 / 장기실행 — NEOS와 차이

### 세션
Hermes: 스레드 공유가 기본, 그룹은 per-user 분리 가능. `/new` `/reset` `/resume`, 크래시 후 같은 transcript 재개.

NEOS: `session_id = "{channel}_{channel_id}"`. 스레드·유저 미구분. 전원 동일 `CHANNEL_BOT_USER_ID`. 재시작 후 채널 메시지 재처리 없음.

### 권한
Hermes: chat-scoped grant → allow-all → Discord role → pairing → env allowlist → deny. 미인가 DM은 pairing 코드.

NEOS: 게이트 없음. 토큰만 있으면 워크스페이스/길드 전 메시지가 서비스 계정으로 워크플로 실행.

### 장기 실행
Hermes: 세션 busy 슬롯 + FIFO overflow. turn lease로 session_id 직렬화. drain 중 inbound 큐.

NEOS: 메시지마다 `execute_workflow`. 동시성 직렬화·진행 메시지·재시작 continue 없음. 승인 interrupt는 웹 SSE 전제. 채널 경로에서 승인 카드/재개 **코드상 연결 없음**.

## 6. 갭과 병합 후보

### A. 일반 워크플로 원격 (ChannelGateway 보강)

| 우선 | 항목 | 붙일 경로 | 작업량 | 리스크 |
|------|------|-----------|--------|--------|
| P0 | Mention + ignored/allowed 채널 | adapters slack/discord `_handle_message` | S | 없으면 채널 스팸 = 비용 |
| P0 | 유저 allowlist (최소 env CSV) | 새 `channels/authz.py` | S | principal을 플랫폼 user로 바꿔야 함 |
| P0 | 스레드 세션 + 응답 thread_ts / Discord reply | `ChannelMessage.session_id` + send metadata | M | 기존 세션 키 호환 → 버전 prefix |
| P0 | 자기/봇 메시지·중복 이벤트 강화 | Slack subtype/dedup, Discord type filter | S | 자기 응답 재진입 |
| P1 | 세션당 in-flight 1개 + 👀 ACK | `ChannelGateway` + adapter hooks | M | 큐 vs drop 정책 |
| P1 | 승인 결과를 채팅 버튼/`!approve`로 | `approval_handlers`를 채널 콜백에서 호출 | M | 웹 SSE와 이중 재개 레이스 |
| P1 | 이미지/파일 in | `receive_message` metadata | M | SSRF, Slack private CDN |
| P2 | 초안 스트리밍(edit) | Slack `chat.update`, Discord `edit` | L | rate limit |
| P2 | Block Kit / Discord 컴포넌트 | 새 renderer. 아이디어만 | L | |
| P2 | Pairing + home channel | 엔터프라이즈는 SSO/allowlist가 맞음 | L | 멀티테넌트 오인 |

### B. 코딩 에이전트 원격 (신규 경로 — 워크플로와 **분리**)

`docs/NEOS_CODING.md`가 chat과 coding 수명주기 분리를 못 박았다. **`ChannelGateway.dispatch`에 코딩 루프를 넣지 말 것.**

| 우선 | 항목 | 붙일 경로 | 작업량 | 리스크 |
|------|------|-----------|--------|--------|
| P0 | `!code` / `/code` 만 coding API로 | gateway에 얇은 router | M | 모든 Slack 메시지가 sandbox task가 됨 |
| P0 | in-process `coding/tasks` + task_id를 스레드에 바인딩 | 기존 핸들러 재사용 | M | 채널 유저 ≠ 프로젝트 멤버 |
| P1 | 진행 요약, `/stop` → cancel | coding commands API | M | 장시간 턴 vs Slack 3s ack |
| P1 | 위험 터미널/푸시 승인을 같은 스레드 버튼으로 | coding approval expire beat | M | 잘못된 유저가 Approve |
| P2 | diff/로그 파일 업로드, resume 카드 | snapshot + recovery 아이디어만 | L | |

## 7. 권장 구현 순서

1. 안전 게이트 (allowlist + mention + ignored + bot-loop). 테스트 먼저 (`tests/api/channels/` 신설).
2. 세션 키 v2: `{channel}:{workspace/guild}:{chat}:{thread}` (+ 옵션 user).
3. in-flight lock + 👀 ACK.
4. 승인 브리지 (워크플로): 채널 버튼 → 기존 `approval_handlers`.
5. 코딩은 명시적 커맨드만: `/code` → `neos.coding` task.
6. 미디어 in, 그다음 slash `/stop /status`. COMMAND_REGISTRY 전체 이식 금지.
7. Pairing, Block Kit, draft streaming, Discord auto-thread는 위가 안정된 뒤.

## 8. 가져오면 안 되는 것

- 플랫폼 폭주 (WhatsApp/Signal/Matrix/Teams/Feishu/WeCom/QQ)
- Relay connector / multiplexing profiles
- Discord voice / TTS mixer
- Slack Assistant suggested prompts, Agent view
- 펫/페르소나/status_phrases, kanban, hosted rooms
- Hermes `SessionStore` + `state.db` 통째 이식
- ChannelGateway를 Hermes식 에이전트 루프로 교체
- 모든 채널 메시지를 코딩 태스크로

Telegram 대비: 세 어댑터를 같이 보강하는 편이 Hermes TG를 복사하는 것보다 맞다.

## 9. 근거 파일 목록

Hermes: `gateway/{run,run_inbound,run_turn,run_turn_runner,run_busy,session,session_persistence,authz_mixin,pairing,turn_lease,delivery,slash_commands,channel_directory}.py`, `gateway/platforms/{base.py,ADDING_A_PLATFORM.md}`, `plugins/platforms/{slack,discord,telegram}/`, `docs/session-lifecycle.md`, `docs/design/multiplexing-gateway.md`.

NEOS: `neos/api/channels/{base,gateway}.py`, `adapters/{slack,discord,telegram}.py`, `neos/main.py`, `neos/config/settings.py`, `docs/NEOS_OPENCLAW.md`, `docs/NEOS_CODING.md`, `neos/workflow/autonomy/policy.py`, `neos/api/handlers/approval_handlers.py`, `db/migrations/021_add_channel_source.sql`, `022_add_tool_approval_allowlist.sql`. 채널 어댑터 단위 테스트: **없음**.
