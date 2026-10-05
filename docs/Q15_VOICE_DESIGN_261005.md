# Q15 채널 음성 → 텍스트 — 설계

> **작성:** 2026-10-05 · **트랙:** Q15 (정본 [OPENAI_DOTS_ANALYSIS_260930.md](OPENAI_DOTS_ANALYSIS_260930.md) §4.2 의 Q15 행 · §4.1 원칙) · **계획:** `docs/superpowers/plans/2026-10-05-q9-q15-parallel.md` Track Q15
> **지위:** 설계다. 열린 질문 여섯 개 중 다섯은 2026-10-05 체크포인트 ①에서 닫혔고 하나(Slack 클립)는 켜기 게이트의 dry run 몫이다(§13). 코드가 착지하면 §11 단계표의 행을 "착지(커밋)"로 바꾼다. 설계와 코드가 어긋나면 코드가 이긴다.
> **근거 규칙:** 현재 상태 서술은 전부 2026-10-05 `dev`(`39055fe6`, `8d149f39` 의 자손 — 그 사이 두 커밋은 산출물 삭제·`.gitignore`)에서
> 코드로 확인했고 경로를 단다. 실호출로 확인하지 않은 서술은 **[코드 읽기]**, 플랫폼·공급자 문서로만 확인한 서술은 **[문서]** 로 표시한다.
> 공급자 사실(모델 id·형식·상한·가격)은 §4 에 출처 URL 과 조회일을 단다. 확인하지 못한 값은 **미확인** 이라고 쓰고 지어내지 않는다.

---

## 0. 한 줄

채널(Slack·Discord·Telegram)에서 **대화 게이트를 통과한** 음성 메시지 하나를 받아, 상한을 **먼저** 보고 OpenAI 전사 API 로
텍스트로 바꾼 뒤, 메시지 본문을 `"[voice] <전사>"` 로 바꿔 **기존 대화 경로에 그대로** 흘려보낸다. 워크플로우·스레드(Q8)·
워크플로우 첨부는 고치지 않는다. 전사 텍스트가 `query` 가 되므로 에이전트 DM 의 스레드 user 턴도 저절로 전사 텍스트가 된다.
오디오 바이트는 공급자 한 곳에만 가고, 워크플로우 첨부로는 가지 않는다.

## 1. 이미 내린 결정 (다시 열지 않는다)

| # | 결정 | 출처 |
|---|---|---|
| Q15-1 | STT 공급자 = **OpenAI 전사 API**. 모델 id 는 공식 문서로 확인해 카탈로그에 올린다(§4) | 계획 "이미 내린 결정" (2026-10-05 사람의 결정) |
| Q15-2 | 범위 = **채널 음성 전부**(Slack·Discord·Telegram). 웹 첨부(로드맵 N3 의 (a))는 이번에 하지 않는다 | 같은 곳 |
| — | 전부 플래그 off 로 착지한다. development 에서 켜는 것은 통합 단계(Phase C)에서 오케스트레이터가 한다 | 계획 Global Constraints |
| — | 모델 id·가격은 추측하지 않는다. 공식 문서로 확인한 값만 `neos/config/models.yaml` 에 올린다 | 계획 Global Constraints · 메모리 retire-stale-models |
| — | 새 의존성 없음(`openai>=3.8.0` 이 이미 있다 — `pyproject.toml` 19행, 잠금은 `uv.lock` 의 `openai 3.13.0`) | 계획 Tech Stack |
| Q15-3~8 | 체크포인트 ①의 결정 — §13 (OGG 그대로 · 켜기 게이트 · 25_000_000 · `empty` · 카탈로그 키 · 바인딩 세션 전사) | 2026-10-05 사람의 결정 |
| — | Phase C 머지 순서: `_route` 앞단에서 **전사 먼저, 그다음 Q9 답 판정**(음성으로 답할 수 있게) | 계획 Phase C |

## 2. 지금 코드 (2026-10-05 `39055fe6` 확인)

### 2.1 STT 는 스텁이고, 그 스텁에 닿는 경로가 없다

| 무엇 | 사실 | 근거 |
|---|---|---|
| `AudioPipeline._speech_to_text` | `"Speech-to-text not yet implemented"` 를 돌려주는 스텁. 상한 상수 `MAX_FILE_SIZE = 100MB`·`MAX_DURATION = 3600` 은 OpenAI 상한(§4)과 맞지 않는다 | `neos/workflow/pipelines/audio_pipeline.py` 38·41·172-189행 |
| `AudioPipeline` 을 부르는 곳 | `multimodal_workflow.py` 의 레지스트리 등록 하나뿐이다. 그 모듈은 HTTP 진입점이 2026-09-10 에 지워져 **어디에서도 import 되지 않는다**(모듈 머리 주석). `grep -rln multimodal_workflow neos tests scripts` → 0건 | `neos/workflow/multimodal_workflow.py` 1-5·54행 |
| 로드맵 | N3 "오디오 STT 완결"은 N8 이후 "함수 하나를 채워도 사용자가 닿을 경로가 없다", 진입점을 먼저 정해야 한다고 적혀 있다 | `docs/ROADMAP.md` §N3(289-312행) |

📌 **Q15 는 N3 의 진입점 질문에 대한 답이 아니다.** Q15 의 진입점은 채널이고(결정 Q15-2), N3 이 말한 (a) 챗 첨부 · (b) 오디오 엔드포인트 ·
(c) `multimodal_workflow` 부활은 전부 이번 범위 밖이다. Q15 가 만드는 `neos/services/speech_to_text.py` 는 나중에 N3 (a) 가 재사용할 수 있는
**공급자 경계**일 뿐이다(§10).

### 2.2 채널 미디어 수집 — 음성은 지금 수집되지 않는다

| 채널 | 지금 수집하는 것 | 음성은? | 근거 |
|---|---|---|---|
| 공통 | 플래그 `channels.inbound_media`(기본 false)일 때만. 크기 상한은 상수 `MAX_INBOUND_MEDIA_BYTES = 5 MiB` 하나이고, `download_inbound_media` 의 본문 검사와 `_default_fetch` 의 `response.read(MAX+1)` 에 **박혀 있다**(인자로 바꿀 수 없다). 다운로드는 https · 허용 호스트 5개 · 사설 IP 차단(SSRF fail-closed) · 리다이렉트 4회 · 소켓 타임아웃 10초 | — | `neos/api/channels/media.py` 16·18-26·88-113·136-155행 · `neos/config/schema.py` `ChannelConfig.inbound_media`(2539행) |
| Telegram | `document` → `photo`(가장 큰 것) → `video` 중 첫 하나 | **수집하지 않는다.** `collect_telegram_attachments` 가 `voice`·`audio` 를 보지 않는다. 게다가 핸들러 필터가 `TEXT·PHOTO·Document.ALL·CAPTION·VIDEO` 뿐이라 **캡션 없는 음성 메시지는 핸들러에 도착조차 하지 않는다.** 캡션 있는 음성은 `CAPTION` 필터로 들어와 캡션 텍스트만 처리된다 | `media.py` `collect_telegram_attachments`(298-355행) · `adapters/telegram.py` `telegram_inbound_filters`(39-47행) · `_handle_message` `has_media`(370-376행) |
| Slack | 메시지의 `files[]` 전부(`url_private`, `mimetype`, `size`). `file_shared` 이벤트 대체 경로는 **`video/*` 만** 처리한다 | `audio/*` 파일은 `inbound_media` 가 켜져 있으면 **보통 첨부로** 들어온다(5 MiB 이하). 음성으로 다뤄지지 않는다 | `media.py` `collect_slack_attachments`(202-221행) · `adapters/slack.py` `receive_message`(183-193행) · `_handle_file_shared`(473-520행, `mime.startswith("video/")`) |
| Discord | `attachments` 전부, `att.read()` 로만 읽는다(CDN URL 대체 금지) | 음성 메시지·오디오 첨부도 `inbound_media` 가 켜져 있으면 **보통 첨부로** 들어온다 | `media.py` `_read_discord_attachment_bytes`·`collect_discord_attachments`(244-295행) · `adapters/discord.py` `receive_message`(170-185행) |

📌 **크기 판단이 다운로드 전에 이미 한 번 있다.** 세 수집기 모두 플랫폼이 알려 준 크기(`size`/`file_size`)가 상한을 넘으면 내려받지 않는다
(`media.py` 185·250·332행). Q15b 는 이 모양을 그대로 따르되 상한을 `channels.voice.max_bytes` 로 바꿀 수 있어야 한다 — 지금 상수가
다운로드 함수에 박혀 있으므로 **상한 인자를 더하는 것**이 Q15b 의 첫 변경이다(기존 호출의 기본값은 5 MiB 그대로).

### 2.3 게이트웨이 — 첨부는 `query` 에 이름만 실린다

- `_attachment_prompt` 는 첨부를 `"\n\nUser attached files:\n- name (type, N bytes)"` 로 `query` 끝에 붙인다. 이름은
  `neutralize_untrusted_inline` 을 거친다(`neos/api/channels/gateway.py` 162-176행)
- `_channel_attachment_blocks` 는 `inbound_media` 가 켜져 있을 때 첨부를 워크플로우 입력 `channel_attachments` 로 넘긴다. 종류는
  `attachment_blocks.classify(mime)` 가 가르고, 이미지면 base64, 텍스트·추출이면 앞 8000자를 싣는다. **오디오 MIME 은 `classify` 가
  `None` 을 돌려주므로**(허용 9종 밖) 바이트 없이 이름·크기만 실린다(`gateway.py` 179-219행 · `neos/services/attachment_blocks.py` `classify` 62-65행)
- `_run_workflow` 의 순서: principals 매핑(비어 있지 않은데 미매핑이면 `_NO_OWNER` 로 끝) → `query = text + _attachment_prompt` →
  Q8b `open_turn(message, query)`(에이전트 DM 이면 스레드 user 턴을 쓰고 창을 읽는다) → 발신자 표지 → 워크플로우(`gateway.py` 454-541행)
- `dispatch` 는 **전사 전의 본문**으로 명령을 파싱해 잠금 우회·주차(park)를 정한다(382-394행). `_route` 는 다시 파싱해 갈래를 고른다(423-452행).
  주차된 메시지는 나중에 `_fold_parked` 가 `_route` 로 다시 보낸다(698-723행). 인바운드 멱등은 `dispatch` 가 `(session_id, idem)` 으로
  결과를 기억한다(376-407행)
- `ChannelMessage` 는 frozen 이 아닌 `@dataclass` 다 — `message.text` 를 바꿀 수 있다(`neos/api/channels/base.py` 15-24행)

### 2.4 대화 게이트는 어댑터에 있고, 미매핑 발신자 판정은 게이트웨이에 있다

- 어댑터 셋 모두 `evaluate_channel_gate(GateContext, policy)` 를 `receive_message`(= 다운로드) **전에** 부른다. 거절은 조용하다
  (`neos/api/channels/authz.py` 60-80행 · `adapters/slack.py` `_handle_message` 581-640행 · `adapters/telegram.py` `_handle_message` 355-430행 ·
  `adapters/discord.py` `_handle_message` 291-320행)
- 게이트 순서: 자기/봇 → **빈 텍스트(첨부 면제)** → 무시 채널 → 허용 채널 → 멘션(DM·바인딩 면제) → `allowed_users`(빈 목록 = 전부 거절)
- 첨부 면제는 `GateContext.has_attachment` 하나이고, 어댑터가 `inbound_media and <미디어 있음>` 으로 계산한다(slack 603 · telegram 375 ·
  discord 299행). Slack·Telegram 은 게이트 전에 `if not text.strip() and not has_attachment: return` 으로 한 번 더 버린다(slack 604 · telegram 376행)
- **미매핑 발신자**(`channels.principals` 가 있는데 매핑이 없는 사람)는 게이트가 아니라 게이트웨이 `_run_workflow` 가 `_NO_OWNER` 로 거절한다
  (`gateway.py` 464-474행). 게이트를 통과한 메시지도 미매핑일 수 있다
- 상시 에이전트 채널 트리거(Q4b) `observe_channel_message` 는 게이트 **전에** 돌고 `ctx.text` 만 본다(`neos/standing/channel_triggers.py` 114-128행)

📌 **비용 표면 규칙(권고)의 정확한 자리는 둘이다.** 무시·차단 채널과 봇은 어댑터 게이트가 막고(다운로드 전), 미매핑 발신자는 게이트웨이가
막는다. 그래서 전사 호출은 **게이트웨이 안, 미매핑 판정 뒤**에만 있을 수 있다(§8).

### 2.5 OpenAI SDK 가 전사를 어떻게 내놓나 (`openai 3.13.0`, 설치본 확인)

- `AsyncOpenAI().audio.transcriptions.create(*, file, model, response_format=..., language=..., timeout=...)` — 비동기 클래스
  `AsyncTranscriptions`(`.venv/.../openai/resources/audio/transcriptions.py` 547행). `timeout` 은 요청 단위 재정의(초)
- `file: FileTypes` — `(filename, bytes, content_type)` 튜플을 받는다. 독스트링: *"The request must include enough format metadata for the
  file to be identified. We recommend an extension-bearing filename and an appropriate content type."*
- `model: Union[str, AudioModel]`, `AudioModel = Literal["whisper-1", "gpt-transcribe", "gpt-4o-transcribe", "gpt-4o-mini-transcribe",
  "gpt-4o-mini-transcribe-2025-12-15", "gpt-4o-transcribe-diarize"]`(`openai/types/audio_model.py`)
- `response_format="json"` 의 반환 `Transcription`: `text: str` · `languages: list[TranscriptionLanguage(code)] | None`(*"Returned by
  `gpt-transcribe`. An empty array indicates that no language could be reliably detected."*) · `usage: UsageTokens | UsageDuration(seconds) | None`
  (`openai/types/audio/transcription.py` 66-88행). 단일 `language`·`duration` 필드는 `verbose_json`(`TranscriptionVerbose`)에만 있다
- 클라이언트를 짓는 곳은 하나다: `neos/utils/openai_client.py` `build_async_openai`(키는 `settings.OPENAI_API_KEY`). 새 모듈도 이것을 쓴다
- 저장소 안에 `audio.transcriptions` 를 부르는 곳은 0건이다(`grep -rn "audio.transcriptions\|transcriptions.create" neos`)

### 2.6 모델 카탈로그의 제약

- `ModelSpec.pricing` 은 **USD / 1M 토큰**뿐이다(`neos/config/models.yaml` 머리 주석 · `neos/config/model_config.py` `ModelPricing` 61행).
  분당 가격을 담을 필드가 없다
- 채팅이 아닌 모델의 선례: `text-embedding-3-*` 가 `selectable: false` · `thinking: none` 으로 있고, `aliases.embedding` / `defaults.embedding`
  이 그것을 고른다(`models.yaml` 303-322·446-463행). `aliases` 의 대상은 카탈로그 키여야 한다는 검증이 이미 있다(`model_config.py` 288-299행)
- `aux` 는 FE 생성물 `catalog.generated.ts` 로 나간다(`scripts/generate_catalog_fallback.py` 103행) — 백엔드 전용 슬롯을 `aux` 에 두면 FE 계약이 바뀐다.
  `aliases` 는 생성기가 읽지 않는다

## 3. 이름 (확정)

- 모듈 **`neos/services/speech_to_text.py`**
- 결과 **`Transcription(text: str, language: str | None, duration_seconds: float | None)`** — frozen dataclass
- 거절 **`TranscriptionRefused(reason)`** — 예외. `reason ∈ {too_large, too_long, unsupported_format, provider_error, timeout, empty}`
  (`empty` 는 계획이 설계에 맡긴 것 — §7.4 · §13 결정 3)
- 함수 **`async def transcribe(audio: bytes, *, filename: str, content_type: str, duration_seconds: float | None, config: ChannelVoiceConfig, client=None) -> Transcription`**
- 설정 **`channels.voice`** = `ChannelVoiceConfig(enabled: bool = False, max_bytes: int = 25_000_000, max_seconds: int = 600, timeout_seconds: float = 60)`
  — `neos/config/schema.py`, `ChannelConfig.voice`
- 모델: 카탈로그 키 **`gpt-transcribe`** 하나. 고르는 자리는 `aliases.transcription.openai: gpt-transcribe` + `defaults.transcription: openai`(§7.1)
- 카운터 **`channel_voice_transcriptions_total{outcome}`** — 저장소의 다른 카운터처럼 `neos_` 접두가 없다(`standing_thread_failures_total` 과 같다,
  `neos/observability/metrics.py` 311행)
- 수집 결과 **`ChannelMessage.metadata["voice"]`** = `{"bytes": bytes | None, "filename": str, "content_type": str, "duration_seconds": float | None, "refused": str | None}`
  — 메시지당 **하나**(첫 오디오). `refused` 는 다운로드 전에 거른 이유(§6.3)이고, 그때 `bytes` 는 `None` 이다. 계획 인터페이스에 `refused` 하나를 더했다(§12)

## 4. OpenAI 전사 API — 공식 문서로 확인한 사실 (조회 2026-10-05)

| 항목 | 값 | 출처 |
|---|---|---|
| 권장 모델 | `gpt-transcribe` — 가이드: *"Start with `gpt-transcribe`"*. 다른 선택지: `gpt-4o-transcribe-diarize`(화자 구분이 필요할 때만), `whisper-1`(타임스탬프·번역) | https://developers.openai.com/api/docs/guides/speech-to-text |
| 모델 id·스냅샷 | id `gpt-transcribe`, 스냅샷 `gpt-transcribe`(날짜 접미 없음). 엔드포인트 `v1/audio/transcriptions` · `v1/realtime/transcription_sessions` | https://developers.openai.com/api/docs/models/gpt-transcribe |
| `model` 파라미터 선택지 | *"`gpt-transcribe`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, `gpt-4o-mini-transcribe-2025-12-15`, `whisper-1` …, and `gpt-4o-transcribe-diarize`"* — 설치된 SDK 의 `AudioModel` 과 같다 | https://developers.openai.com/api/reference/python/resources/audio/subresources/transcriptions/methods/create |
| 입력 형식 | ⚠️ **문서끼리 다르다.** API 레퍼런스(`file` 파라미터): *"flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, or webm"*(9종, SDK 독스트링과 같다). 가이드: *"Supported input formats are `mp3`, `mp4`, `mpeg`, `mpga`, `m4a`, `wav`, and `webm`."*(7종 — **ogg·flac 없음**) | 위 레퍼런스 URL · 위 가이드 URL |
| 업로드 상한 | *"Files can be up to 25 MB."* 단위가 10진(25,000,000)인지 2진(26,214,400)인지 문서가 말하지 않는다 → 설정 기본값은 작은 쪽(§7.2) | 가이드 URL |
| 길이 상한 | **미확인.** 가이드는 길이 상한 없이 25 MB 를 넘으면 나누라고만 한다. 모델 페이지도 컨텍스트 창·최대 길이를 적지 않는다. `max_seconds: 600` 은 공급자 사실이 아니라 **우리 정책**이다 | 가이드 · 모델 페이지 URL |
| 가격 | `gpt-transcribe` **$0.0045 / 분**. (참고: `gpt-4o-transcribe` $0.006/분 추정, `gpt-4o-mini-transcribe` $0.003/분 추정, Whisper $0.006/분) | https://developers.openai.com/api/docs/models/gpt-transcribe · https://developers.openai.com/api/docs/pricing |
| 응답 | 가이드: *"The model returns the transcript and the detected languages as JSON"* — SDK `Transcription.languages` 와 맞다 | 가이드 URL |
| 레이트 리밋(Tier 1 기본) | 500 RPM · 200,000 TPM | 모델 페이지 URL |

📌 **ogg 불일치가 이 트랙의 가장 큰 미확인이다.** Telegram 음성 노트와 Discord 음성 메시지는 둘 다 OGG/Opus 다(§5). 파라미터 계약인 API
레퍼런스와 SDK 는 `ogg` 를 받는다고 하므로 **변환 없이 `.ogg` 로 보낸다**(새 의존성 없음). 다만 가이드가 빠뜨린 이유를 모르므로, development 에서
켜기 전에 **라이브 dry run 3/3**(OGG 하나 · webm 또는 m4a 하나 · 상한 초과 하나)을 사람이 돌린다(메모리 live-children-need-live-dry-runs).
`ogg` 가 거절되면 변환(ffmpeg 등)이 필요하고 그것은 새 의존성이라 멈추고 묻는다 — §13 결정 1.

## 5. 채널별 — 음성은 어떻게 도착하고, 크기·길이를 미리 아는가

| 채널 | 음성의 모양 | 크기를 다운로드 전에 아나 | 길이를 다운로드 전에 아나 | 근거 |
|---|---|---|---|---|
| Telegram | `Message.voice`(*"Message is a voice message"*) 또는 `Message.audio`(*"Message is an audio file"*). 음성 노트는 *".OGG file encoded with OPUS, or … .MP3 …, or … .M4A"*(sendVoice). 캡션 가능 | `file_size` — **Optional** [문서]. 없으면 모른다 | `duration` — **필수**, *"Duration of the audio in seconds as defined by the sender"* [문서] | https://core.telegram.org/bots/api (Voice · Audio · Message · sendVoice) |
| Telegram 다운로드 | `getFile` → `https://api.telegram.org/file/bot<token>/<file_path>`. *"For the moment, bots can download files of up to 20MB in size."* → **Telegram 의 실효 상한은 20 MB** 다 | | | 같은 URL, getFile · 현재 코드 `media.py` 336-354행 |
| Discord | 음성 메시지 = 플래그 `IS_VOICE_MESSAGE`(`1 << 13`). *"Only a single audio attachment is allowed. No content"* — **본문이 늘 비어 있다.** 첨부에 `duration_secs`·`waveform`. *"clients upload a 1 channel, 48000 Hz, 32kbps Opus stream in an OGG container"*(구현 세부, 바뀔 수 있다고 명시). 일반 오디오 첨부도 있다(`content_type` `audio/*`) | 첨부 `size` — **필수**(integer) [문서]. discord.py `Attachment.size` | 음성 메시지면 `duration_secs`(*"required for voice messages"*) — discord.py 2.7.1 `Attachment.duration`(`None` 이면 음성 메시지 아님), `Attachment.is_voice_message()`. 일반 오디오 첨부는 모른다 | https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx (Voice Messages · Attachment Object) · `.venv/.../discord/message.py` 197-261행 |
| Slack | 메시지 이벤트(`subtype: file_share`)의 `files[]` 중 `mimetype` 이 `audio/*` 인 파일. 앱 안 "오디오 클립"의 정확한 `mimetype`·도착 이벤트는 **미확인**(파일 객체 문서에 오디오·길이 항목이 없다) | `size` — *"The filesize in bytes"* [문서] | **모른다.** 파일 객체 문서에 길이 필드가 없다 → `duration_seconds = None`, `max_seconds` 를 적용하지 못한다 | https://docs.slack.dev/reference/objects/file-object · 현재 코드 `media.py` 202-221행 |

📌 **길이 상한은 길이를 아는 채널만 적용한다**(권고 그대로). Slack 과 Discord 의 일반 오디오 첨부는 `max_bytes` 만 본다. 다운로드 뒤 오디오를
디코딩해 길이를 재지 않는다 — 디코더는 새 의존성이다. 공급자 응답의 `usage`(`UsageDuration.seconds`)가 오면 `Transcription.duration_seconds` 에
싣지만, 그것은 사후 값이라 거절에 쓰지 않는다.

## 6. 수집 규칙 (Q15b)

### 6.1 언제 수집하나

- `channels.voice.enabled` 가 켜져 있을 때만. **`inbound_media` 와 별개다**(권고 그대로) — `inbound_media` 가 꺼져 있어도 음성은 수집한다
- 수집은 지금처럼 `receive_message` 안, 즉 **어댑터 게이트를 통과한 뒤**에만 일어난다(§2.4). 무시 채널·봇 메시지는 내려받지도 않는다
- 메시지당 **하나**: Telegram `voice` → `audio`, Discord 음성 메시지 첨부 → 첫 `audio/*` 첨부, Slack 첫 `audio/*` 파일
- Telegram `document` 의 `mime_type` 이 `audio/*` 여도 음성이 아니다(지금처럼 첨부). Telegram 은 음성·오디오를 별도 필드로 가르기 때문이다.
  Slack·Discord 에는 그런 구별이 없어 MIME 으로 가른다

### 6.2 게이트에 음성을 알리기

- 세 어댑터의 `has_attachment` 계산에 `voice.enabled and <오디오 있음>` 을 더한다. 그래야 본문 없는 음성(Discord 음성 메시지는 늘, Telegram·Slack
  은 캡션이 없을 때)이 `EMPTY_TEXT` 로 버려지지 않는다. `GateContext`·`evaluate_channel_gate` 는 바꾸지 않는다
- Telegram 은 `telegram_inbound_filters` 에 `filters.VOICE`·`filters.AUDIO` 를 **늘** 더한다(플래그는 메시지마다 읽는다 — Q8b 의 "늘 배선, 호출 때
  플래그"와 같다). 플래그 off 면 캡션 없는 음성은 `if not text.strip() and not has_attachment: return` 에서 지금처럼 버려지고, 캡션 있는 음성은
  지금처럼 캡션만 처리된다 — **off 동작이 바이트 동일**
- "오디오 있음" 판정은 어댑터마다 함수 하나로 두고, 게이트 계산과 수집이 같은 함수를 쓴다(Q8b `*_is_dm` 과 같은 이유 — 판정이 두 곳에서 갈라지지 않게)

### 6.3 다운로드 전 거절과 다운로드

- 플랫폼이 크기를 알려 주고 그것이 상한을 넘으면 **내려받지 않는다**: `metadata["voice"] = {..., "bytes": None, "refused": "too_large"}`.
  길이를 알려 주고 `max_seconds` 를 넘으면 같은 식으로 `"too_long"`. 조용히 버리지 않고 게이트웨이가 거절 문구로 답하게 넘긴다(§9) —
  지금 첨부 수집기는 상한 초과를 조용히 건너뛰지만(`media.py` 185·250·332행), 음성은 본문이 없는 경우가 많아 조용히 버리면 사용자는 아무 답도 못 받는다
- 상한 = `min(channels.voice.max_bytes, 플랫폼 다운로드 상한)`. 플랫폼 상한은 Telegram 의 20 MB(§5) 하나다. 크기를 모르는 채로 내려받은 본문이
  상한을 넘으면 그때 `too_large`(읽기는 상한+1 에서 끊는다 — `_default_fetch` 와 같은 모양)
- 다운로드 함수에 상한 인자를 더한다(`limit: int = MAX_INBOUND_MEDIA_BYTES`). 기존 첨부 호출은 인자를 넘기지 않아 5 MiB 그대로다. SSRF 규칙은 그대로 탄다
- 다운로드 실패(차단된 URL·HTTP 오류·Discord `att.read()` 실패)는 `"refused": "download_failed"`. Discord 는 지금처럼 CDN URL 로 대체하지 않는다
- **음성으로 잡힌 오디오는 `metadata["attachments"]` 에 넣지 않는다.** `inbound_media` 도 켜져 있으면 첨부 수집기는 음성으로 잡힌 그 파일을 건너뛴다
  (같은 바이트를 두 번 내려받지 않고, 오디오 바이트가 워크플로우 첨부로 가지 않게). 음성이 꺼져 있으면 오디오 파일은 지금처럼 첨부로 남는다
- 파일 이름: 플랫폼이 준 이름이 있으면 그것, 없으면 `voice.ogg`(Telegram voice — `mime_type` 이 없으면 `audio/ogg`) 같은 확장자 있는 이름. SDK 가
  확장자 있는 이름을 권한다(§2.5)

## 7. 전사 클라이언트 (Q15a)

### 7.1 모델 — 카탈로그 키 하나

```yaml
# neos/config/models.yaml (안)
  gpt-transcribe:
    provider: openai
    thinking: none
    selectable: false
    description: "OpenAI speech-to-text (channel voice, Q15)"
    # 가격 $0.0045 / 분 (https://developers.openai.com/api/docs/models/gpt-transcribe, 2026-10-05).
    # pricing 은 1M 토큰 단위만 받으므로 비워 둔다 — 비용 원장에 오르지 않는다(§13 결정 4).

aliases:
  transcription:
    openai: gpt-transcribe
defaults:
  transcription: openai
```

- 모델을 고르는 자리를 **설정이 아니라 카탈로그**에 둔다(메모리 model-catalog-single-source). 그래서 `ChannelVoiceConfig` 에 `model` 키가 없다
- `aux` 에 두지 않는다 — FE 생성물로 나간다(§2.6). `aliases` 는 생성기가 읽지 않고, 대상이 카탈로그 키인지 이미 검증된다
- Q15a 는 `scripts/generate_catalog_fallback.py` 를 돌려 `web/lib/ai/catalog.generated.ts` 에 diff 가 없음을 확인한다

### 7.2 상한을 먼저 본다 — 공급자에 보내기 전의 순서

`transcribe` 는 아래 순서로 보고, 하나라도 걸리면 **클라이언트를 만들지도, 부르지도 않고** `TranscriptionRefused` 를 던진다.

1. `len(audio) > config.max_bytes` → `too_large`
2. `duration_seconds is not None and duration_seconds > config.max_seconds` → `too_long`
3. 형식: `content_type` 또는 파일 확장자가 API 레퍼런스의 9종(`flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm`)에 들지 않으면 `unsupported_format`.
   `audio/ogg; codecs=opus` 처럼 매개변수가 붙은 MIME 은 매개변수를 떼고 본다. 확장자가 없으면 MIME 에서 확장자를 정해 파일 이름에 붙인다

그다음 `client.audio.transcriptions.create(file=(filename, audio, content_type), model=<카탈로그 해석>, response_format="json")` 를
`asyncio.wait_for(..., timeout=config.timeout_seconds)` 로 감싸 부른다.

- 시간 초과(`asyncio.TimeoutError` 또는 SDK 의 `APITimeoutError`) → `timeout`
- 그 밖의 예외(키 없음·4xx·5xx·연결 오류) → `provider_error`. 원인은 로그 한 줄(바이트·전사 내용은 로그에 남기지 않는다)
- `text.strip()` 이 비면 → `empty`
- 성공: `Transcription(text=text.strip(), language=languages[0].code 또는 None, duration_seconds=usage.seconds(UsageDuration 일 때) 또는 입력값 또는 None)`
- 재시도하지 않는다. SDK 의 기본 재시도도 `max_retries=0` 으로 끈다 — 시간 상한이 사용자 대기 시간과 같아야 하고, 재시도는 같은 오디오로 비용을 두 번 낸다
- `language` 힌트를 보내지 않는다(자동 감지). 프롬프트·키워드도 보내지 않는다

### 7.3 `max_bytes` 기본값과 검증

- 기본 **`25_000_000`**(10진 25 MB). 계획의 권고 "25 MiB"(26,214,400)는 문서의 "25 MB"를 2진으로 읽은 것인데, 문서가 단위를 밝히지 않으므로
  **작은 쪽**을 고른다. 25 MiB 로 두면 25,000,001~26,214,400 바이트 사이의 파일이 상한 검사를 통과하고 공급자에서 거절될 수 있다(§13 결정 2)
- 스키마 검증: `0 < max_bytes <= 25_000_000` · `max_seconds > 0` · `timeout_seconds > 0`. 공급자 상한보다 큰 값은 기동을 멈춘다(`extra="forbid"` 와 같은 원칙)
- `timeout_seconds` 기본 **60**(잠정). 공급자 문서에 지연 수치가 없다. 세션 잠금을 그만큼 쥐므로(§8) 더 길게 두지 않는다

### 7.4 빈 전사 = `empty` 거절

계획이 설계에 맡긴 항목이다. **거절한다.** 무음·잡음 녹음의 결과 `""` 를 `"[voice] "` 로 워크플로우에 보내면 빈 질문에 대한 답을 사고, 에이전트 DM 이면
빈 user 턴이 스레드에 남는다. reason 집합에 `empty` 가 하나 늘어난다(§13 결정 3).

## 8. 게이트웨이 배선 (Q15c)

**자리는 `_route` 의 맨 앞이다.** `dispatch` 가 아니다.

- `_route` 는 잠금을 쥔 뒤(`dispatch`)에도, 주차됐다 풀린 메시지(`_fold_parked`)에도 불린다(§2.3). 그래서 주차된 음성도 풀릴 때 전사되고, 덮어써진
  주차 메시지(`SessionInboundPark.put` 은 마지막 것만 남긴다)는 전사되지 않는다 — 버려질 메시지에 비용을 내지 않는다
- 인바운드 멱등(`dispatch` 의 claim/remember) 안쪽이므로, 플랫폼 재전송은 기억된 답을 받고 **다시 전사하지 않는다**
- Phase C 에서 Q9 의 답 가로채기가 같은 `_route` 앞단에 온다. 순서는 **전사 → 답 판정**(계획). 전사가 `message.text` 를 바꾸므로 답 판정은
  전사된 텍스트를 본다

```python
# neos/api/channels/gateway.py (안)
async def _route(self, message):
    refusal = await self._transcribe_voice(message)   # 음성이 없으면 None, 아무것도 안 한다
    if refusal is not None:
        return refusal                                  # 워크플로우·스레드 0회
    command = parse_channel_command(message.text)
    ...
```

`_transcribe_voice` 의 규칙:

1. `metadata["voice"]` 가 없거나 `channels.voice.enabled` 가 꺼져 있으면 → `None`(지금과 바이트 동일)
2. **캡션이 명령이면 음성을 무시한다.** `parse_channel_command(message.text)` 가 `CHAT` 이 아니면 전사하지 않고 `None` — 명령은 지금처럼 돈다.
   `dispatch` 가 이미 캡션으로 잠금 우회·주차를 정했으므로(§2.3) 전사 뒤에 갈래가 바뀌면 안 된다
3. **미매핑 발신자는 전사하지 않는다.** `channels.principals` 가 비어 있지 않은데 `resolve_channel_principal` 이 매핑을 못 찾으면 `_NO_OWNER` 를 돌려준다 —
   `_run_workflow` 가 어차피 같은 답을 하므로 사용자에게 보이는 결과는 같고, 공급자 호출만 0회가 된다. 매핑 판정은 `_run_workflow` 와 **같은 함수**를
   쓴다(헬퍼 하나로 뽑아 둘이 부른다 — 메모리 fixes-land-in-one-caller-only)
4. `refused` 가 있으면 공급자를 부르지 않고 그 거절 문구(§9)
5. `transcribe(...)` → 성공이면 `message.text = "[voice] " + transcript`, 원래 텍스트(캡션)가 있으면 `"\n\n" + caption` 을 **뒤에** 붙인다(권고 그대로).
   `TranscriptionRefused` 면 거절 문구
6. 어떤 경우에도 `metadata["voice"]["bytes"]` 를 지운다(`None`) — 오디오가 메시지 객체에 남아 이후 경로(주차·로그)로 흐르지 않게

결과로 생기는 성질 — 고치지 않아도 되는 것:

- **스레드(Q8b)는 바뀌지 않는다.** `_run_workflow` 가 `query = message.text + _attachment_prompt` 를 `open_turn` 에 넘기므로 에이전트 DM 의 스레드
  user 턴이 `[voice] …` 가 된다. 턴 `role` 은 늘리지 않는다(Q8 §10)
- **전사 텍스트는 명령이 되지 않는다.** `[voice]` 로 시작하므로 `parse_channel_command` 는 늘 `CHAT` 이다. "슬래시 뉴"라고 말해도 `/new` 가 아니다.
  사람이 말로 위험한 명령을 실수로 내지 않게 하는 성질이라 테스트로 고정한다
- **바인딩된 코딩 세션**에서도 같은 자리에서 전사되어, 조향(`_steer_bound_chat`)이 `[voice] …` 를 받는다(§13 결정 5)
- 서킷 브레이커: `_transcribe_voice` 는 던지지 않는다(거절은 문구로 돌아온다). 공급자 장애가 채널 브레이커를 열지 않는다
- 세션 잠금은 전사 동안(최대 `timeout_seconds`) 쥔다. 그동안 온 같은 세션의 메시지는 지금처럼 주차된다
- 상시 에이전트 채널 트리거(Q4b)는 **전사 텍스트를 보지 않는다** — 트리거는 게이트 전에 캡션만 본다(§2.4). 트리거를 위해 전사하면 게이트 밖 메시지를
  전사하게 되므로 바꾸지 않는다(§13)

## 9. 문구와 계측

| 경우 | 사용자에게 | 카운터 `outcome` | 공급자 호출 |
|---|---|---|---|
| 전사 성공 | (워크플로우의 답) | `ok` | 1 |
| 크기 초과(다운로드 전·후, 또는 `transcribe` 첫 검사) | `The voice message is too large to transcribe.` | `too_large` | 0 |
| 길이 초과 | `The voice message is too long to transcribe (limit: {max_seconds}s).` | `too_long` | 0 |
| 지원하지 않는 형식 | `This audio format can't be transcribed.` | `unsupported_format` | 0 |
| 다운로드 실패 | `Could not read the voice message.` | `download_failed` | 0 |
| 빈 전사 | `No speech was found in the voice message.` | `empty` | 1 |
| 공급자 실패 | `Could not transcribe the voice message.`(권고 문구 그대로) | `provider_error` | 1 |
| 시간 초과 | `Could not transcribe the voice message.` | `timeout` | 1 |

- 거절이면 **워크플로우를 돌리지 않고**, 스레드에도 쓰지 않는다
- 카운터는 게이트웨이 한 곳(`_transcribe_voice`)에서만 올린다 — 다운로드 전 거절과 `transcribe` 결과가 같은 카운터에 모인다. 계측 실패는 대화를 막지 않는다
  (`channel_threads._count_failure`(113행)와 같은 모양)
- 문구는 영어다 — 게이트웨이의 다른 채널 문구(`_NO_OWNER`·`_BUSY` 등, `gateway.py` 33-57행)와 같다
- 무시·차단 채널·봇·`allowed_users` 밖은 지금처럼 **조용히** 버려진다(카운터도 오르지 않는다). 미매핑 발신자는 `_NO_OWNER` 답을 받고 카운터는 오르지 않는다

## 10. `AudioPipeline._speech_to_text` 는 건드리지 않는다

**새 모듈만 만들고 `AudioPipeline` 은 그대로 둔다**(계획 권고 그대로).

- `AudioPipeline` 은 import 되지 않는 `multimodal_workflow` 에만 매달려 있다(§2.1). 채워도 사용자가 닿을 경로가 없고, 테스트할 독자도 없다
- 상한 상수(100 MB · 3600 초)가 공급자 상한과 어긋난다. 연결하면 그 상수를 고치는 일까지 딸려 온다
- N3 이 진입점을 정하면(예: (a) 챗 첨부) 그쪽이 `speech_to_text.transcribe` 를 부르면 된다. `ChannelVoiceConfig` 를 받는 시그니처가 채널 전용이라면
  그때 상한 묶음을 일반화한다 — 지금 일반화하지 않는다(독자 없는 일반화)
- 로드맵 N3 의 문구는 Phase C 에서 오케스트레이터가 "공급자 경계는 Q15 가 만들었다"로 고친다(공유 문서는 서브에이전트가 고치지 않는다)

## 11. 단계 — 전부 플래그 off 로 착지한다

마이그레이션은 **없다**(096 을 쓰지 않는다). 상태를 저장하지 않는다 — 전사 텍스트는 기존 경로가 저장하는 곳(체크포인터·Q8 스레드 턴)에만 남는다.

| 단계 | 무엇 | 테스트가 확인할 것 | 선행 |
|---|---|---|---|
| **Q15a** ✅ **착지(2026-10-05)** | `neos/services/speech_to_text.py`(`Transcription`·`TranscriptionRefused`·`transcribe`) · `models.yaml` 의 `gpt-transcribe` + `aliases/defaults.transcription` · `ChannelVoiceConfig`(`channels.voice`) · 카운터 `channel_voice_transcriptions_total{outcome}` 등록 | `tests/services/test_speech_to_text.py`, 가짜 클라이언트로: 정상 전사(text·language·duration) · **Review Focus 4: 크기 초과 → 클라이언트 호출 0회**(가짜 클라이언트의 호출 기록이 빈다) · 길이 초과 → 호출 0회 · 길이 `None` 이면 길이 검사를 건너뛴다 · 지원 안 하는 형식 → 호출 0회 · `audio/ogg; codecs=opus` 는 지원 · 시간 초과 → `timeout` · 공급자 예외 → `provider_error` · 빈/공백 전사 → `empty` · 모델 id 는 카탈로그(`defaults.transcription`)에서 온다 · 설정: 기본 off, `max_bytes > 25_000_000` 거절, 모르는 키 거절 · 카탈로그 생성물에 diff 없음 | — |
| **Q15b** ✅ **착지(2026-10-05)** | `media.py` 음성 수집(Telegram `voice`·`audio` · Slack `audio/*` · Discord 음성 메시지·`audio/*` 첨부)과 다운로드 상한 인자 · 어댑터 셋의 `has_attachment`·`receive_message` · Telegram 필터에 `VOICE`·`AUDIO` | `tests/api/channels/test_voice_collection.py`: 채널마다 음성 하나 → `metadata["voice"]`(bytes·filename·content_type·duration) · 둘 이상이면 첫 하나 · **플래그 off 면 수집 0, 다운로드 0**(off 동작 바이트 동일 — 캡션 없는 Telegram 음성은 핸들러에서 버려진다) · **크기를 아는 채널에서 상한 초과는 다운로드 전에 거른다**(fetch 호출 0회, `refused: "too_large"`) · Telegram 20 MB 상한이 `max_bytes` 보다 작으면 그것이 이긴다 · 길이를 아는 채널에서 `too_long` 도 다운로드 전 · `inbound_media` off 여도 음성은 수집 · `inbound_media` on 이면 음성 파일이 `attachments` 에 없다 · 본문 없는 음성이 게이트의 `EMPTY_TEXT` 에 걸리지 않는다 · 무시 채널·봇의 음성은 내려받지 않는다(fetch 0회) · 기존 첨부 상한(5 MiB)은 그대로 | Q15a(설정 키) |
| **Q15c** | `gateway._route` 앞단 `_transcribe_voice` · 매핑 판정 헬퍼(`_run_workflow` 와 공유) · `docs/CONFIGURATION.md` 영어 절 하나 · 이 문서 단계표 | `tests/api/channels/test_gateway_voice.py`, 실제 게이트웨이로: 전사가 워크플로우 `query` 에 `[voice] …`(캡션은 그 뒤) · 에이전트 DM 이면 스레드 user 턴도 `[voice] …` · 실패(공급자·시간 초과) → `Could not transcribe the voice message.`, **워크플로우 0회** · 다운로드 전 거절(`refused`) → 문구, 공급자 0회 · **Review Focus 4: 상한 넘는 음성 → 공급자 0회**(게이트웨이 수준에서도 한 번 더) · **Review Focus 5: 게이트 밖 → 공급자 0회** — 무시 채널·봇 메시지는 어댑터 테스트로(실제 `_handle_message` → 공급자 가짜의 호출 0), 미매핑 발신자는 게이트웨이 테스트로(`_NO_OWNER`, 공급자 0회) · 오디오 바이트가 워크플로우 입력(`channel_attachments` 포함) 어디에도 없다 · 캡션이 명령이면 전사하지 않는다 · 전사가 `/new` 로 시작하는 말이어도 명령이 아니다 · 같은 `idem` 재전송은 공급자를 다시 부르지 않는다 · 주차된 음성은 풀릴 때 전사된다 · 플래그 off 면 공급자 0회·동작 동일 · 카운터 `outcome` 이 표(§9)대로 오른다 | Q15a · Q15b |

- **Q15a 결과**(2026-10-05): 테스트 45(`tests/services/test_speech_to_text.py`) · 변이 21/21. 설계에서 바꾼 것: ① 형식 검사는 파일 확장자가
  9종 안이면 그것을 믿고 MIME 은 확장자에서 다시 정한다(`application/octet-stream` 인 `clip.m4a` 도 간다). 확장자가 없거나 목록 밖이면 MIME 에서
  확장자를 정해 붙인다(`audio/opus` → `.ogg`, `video/mp4`·`video/webm` 도 받는다 — 둘 다 레퍼런스 9종의 컨테이너다) ② 모델 해석은
  `transcription_model()` 하나이고 카탈로그의 `wire_id` 가 있으면 그것을 보낸다 ③ 기본 클라이언트는 `build_async_openai(max_retries=0)` ·
  SDK `timeout` 과 `asyncio.wait_for` 를 둘 다 건다 ④ 공급자 오류 로그에는 예외 **타입 이름만** 남긴다(본문에 오디오·전사 조각이 섞일 수 있다)
  ⑤ 상한 `OPENAI_TRANSCRIPTION_MAX_BYTES = 25_000_000` 은 `neos/config/schema.py` 의 상수다 · FE 카탈로그 생성물은 바뀌지 않는다(생성 후 diff 0)
- **Q15b 결과**(2026-10-05): 테스트 33(`tests/api/channels/test_voice_collection.py`, 실제 어댑터 `_handle_message` 로) · 변이 26/26.
  설계에서 바꾼 것: ① Telegram 상한 상수 `TELEGRAM_DOWNLOAD_MAX_BYTES = 20_000_000` — Bot API 의 "20MB" 도 단위를 밝히지 않아 OpenAI 와 같은
  규칙(작은 쪽, 10진)을 따랐다 ② 다운로드 함수는 공개 시그니처 `download_inbound_media(..., limit=MAX_INBOUND_MEDIA_BYTES)` 를 두고, 이유를 돌려주는
  내부 `_download` 를 새로 두었다 — 음성은 `too_large`(받은 본문이 상한 초과)와 `download_failed`(차단 URL·HTTP 오류·예외)를 가려야 한다
  ③ "오디오 있음" 판정 함수 `telegram_voice_media` · `slack_voice_file` · `discord_voice_attachment` 를 `media.py` 에 두고 어댑터의 게이트 계산과
  수집이 함께 쓴다 ④ 파일 이름이 없으면 `voice.ogg`(Telegram voice, MIME 없으면 `audio/ogg`) · `audio.mp3`(Telegram audio, MIME 없으면
  `audio/mpeg`) 처럼 MIME 에서 확장자를 붙인다 ⑤ Discord 음성 `read()` 실패는 `attachments_error`("Could not read the attached file.")가 아니라
  `voice.refused = "download_failed"` 다 — 문구는 Q15c 게이트웨이가 낸다 ⑥ Slack `file_shared` 대체 경로는 바꾸지 않았다(§13 결정 6, dry run 몫)
  ⑦ 테스트 헬퍼 `install_channel_settings` 에 `voice=` 인자를 더했다
- 각 단계: TDD → 변이 테스트(핵심 동작마다 하나, 전부 죽어야 한다) → 그 브랜치에서 전체 스위트 → 커밋(계획 Global Constraints)
- 실 DB 가 필요한 테스트는 없을 것으로 본다. 생기면 사용자 id 접두 `test_q15_`
- **development 에서도 off 로 둔다.** 켜기는 §13 "켜기 게이트"(라이브 dry run 3/3)가 통과한 뒤에만 — Phase C 에서 오케스트레이터가 한다

## 12. 계획의 권고 기본값과 다르게 정한 것

| 권고 | 이 설계 | 근거 |
|---|---|---|
| `channels.voice.max_bytes` 기본 **25 MiB** | **25_000_000 바이트** | 공식 가이드는 "25 MB"라고만 쓴다(§4). 단위를 모르므로 작은 쪽. 25 MiB 는 25,000,001~26,214,400 바이트를 통과시킨다 |
| (권고에 없음) Telegram 상한 | `min(max_bytes, 20 MB)` | Bot API `getFile`: *"bots can download files of up to 20MB in size"*(§5) |
| reason 5종 | **`empty` 를 더해 6종** | 계획 Task 1 Step 1 이 설계에 맡겼다. §7.4 |
| `metadata["voice"]` 4필드 | **`refused` 를 더해 5필드**, 거절 시 `bytes: None` | 다운로드 전 거절을 조용히 버리면 본문 없는 음성에 아무 답이 없다. 거절 문구를 게이트웨이 한 곳에서 내기 위해 이유를 실어 보낸다(§6.3) |
| 카운터 `outcome` | `ok` + reason 6종 + **`download_failed`** | 다운로드 실패는 전사 거절이 아니지만 사용자에게는 같은 "음성을 못 받았다"다 |
| "모델은 카탈로그 키 하나" | 키 `gpt-transcribe` + 고르는 자리 `aliases.transcription`·`defaults.transcription` | 설정에 모델 키를 두지 않기 위해. `aux` 는 FE 로 나간다(§2.6) |
| 실패 문구 하나 | 경우별 문구(§9) — 공급자 실패·시간 초과는 권고 문구 그대로 | 상한 초과·형식·빈 전사는 사용자가 고칠 수 있는 원인이라 따로 말한다 |

그 밖의 권고(수집이 `inbound_media` 와 별개 · `max_seconds` 600 은 길이를 아는 채널만 · `"[voice] <transcript>"` + 캡션 뒤 · 오디오를 워크플로우 첨부로
넘기지 않음 · 게이트 통과 메시지만 전사)는 그대로 따른다.

## 13. 결정 (2026-10-05, 체크포인트 ① — 사람의 결정)

열린 질문 여섯 개 중 다섯은 2026-10-05 체크포인트 ①에서 닫혔다(6 은 켜기 게이트 몫). §12 표와 §8 의 이탈 아홉 개(미매핑 판정을 전사 앞으로 끌어와 헬퍼 하나로 공유 ·
`metadata["voice"].refused` · outcome `download_failed` · 말한 "/new" 는 명령이 아니다 등)도 받아들여졌다.

1. ✅ **OGG 는 변환 없이 보낸다.** 단 문서가 갈리므로(§4) **`channels.voice.enabled` 는 development 에서도 꺼 둔다** — 통합 단계에서
   **라이브 dry run 3/3 이 통과해야** 켠다(아래 "켜기 게이트"). 거절되면 변환(새 의존성)을 다시 묻는다
2. ✅ **`max_bytes` 기본 `25_000_000`.** Telegram 실효 상한은 `min(max_bytes, 20 MB)`
3. ✅ **빈 전사는 `empty` 로 거절**하고 `No speech was found in the voice message.` 로 답한다
4. ✅ **모델은 카탈로그 키 `gpt-transcribe`**, 고르는 자리는 `aliases.transcription.openai` / `defaults.transcription`. `pricing` 은 비운다.
   **비용은 카운터로만 센다** — 전사 비용이 비용 원장에 없다는 사실은 로드맵 메모로 남긴다(Phase C, 오케스트레이터)
5. ✅ **바인딩된 코딩 세션의 음성도 전사**하고, 전사 텍스트가 조향 지시가 된다(`_route` 앞단에서 저절로)
6. ⏳ **Slack 앱 안 클립의 `mimetype`·도착 이벤트**는 열린 채로 남긴다 — 켜기 게이트의 dry run 에서 확인한다

### 켜기 게이트 (development)

`config/neos.development.yaml` 에 `channels.voice.enabled: true` 를 넣는 일은 **아래 셋이 실제 OpenAI 호출로 모두 통과한 뒤에만** 한다(메모리
live-children-need-live-dry-runs). 그 전에는 스키마 기본(off)이 development 에서도 그대로다.

| # | dry run | 통과 조건 |
|---|---|---|
| 1 | Telegram 또는 Discord 음성 메시지(OGG/Opus) | `ok` — 전사가 `[voice] …` 로 답에 반영된다 |
| 2 | Slack 오디오(앱 안 클립) | `ok` — 그리고 클립의 `mimetype`·도착 이벤트를 기록한다(결정 6) |
| 3 | 상한 초과 음성 | 거절 문구, **공급자 호출 0회**(카운터 `too_large`) |

## 14. 되돌리지 말 것

- 게이트(어댑터)나 미매핑 판정(게이트웨이) **전에** 전사하기 → 무시 채널·봇·남의 음성을 외부로 보내고 돈을 낸다(Review Focus 5)
- 상한을 공급자 호출 **뒤에** 보기(공급자의 413 에 기대기) → 25 MB 를 업로드하고 나서 거절당한다(Review Focus 4)
- 음성 바이트를 `metadata["attachments"]`·`channel_attachments` 로 흘리기 → 오디오가 워크플로우·LLM 첨부 경로로 간다
- 전사 텍스트를 명령으로 파싱하기(`[voice]` 접두 떼기) → 말로 `/new`·`/approve` 가 된다
- 트리거(Q4b)를 위해 게이트 전에 전사하기
- `AudioPipeline._speech_to_text` 를 "함수 하나만 채우면 된다"로 채우기 → 닿는 경로가 없다(§10)
- 모델 id 를 설정 키·코드 상수로 두기 → 카탈로그가 단일 원천이다
- 스키마에 키가 생기기 전에 development.yaml 에 `voice:` 를 넣기 → `extra="forbid"` 로 기동이 멈춘다
- 공급자 상한·가격을 문서 없이 적기 — 확인 못 한 값은 **미확인** 으로 둔다
