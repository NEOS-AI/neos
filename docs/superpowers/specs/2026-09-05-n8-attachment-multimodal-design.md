# N8 — 첨부가 모델에 도달한다 (멀티모달 입력) · 설계

- **일자:** 2026-09-05
- **원장 항목:** `docs/ROADMAP.md` §N8 (우선순위 7위)
- **선행 실측:** 커밋 `6e2619ed` — N8 항목의 (a)~(d)
- **상태:** 설계 확정. 구현 계획은 별도 문서(`docs/superpowers/plans/`)

---

## 1. 문제

사용자가 붙인 파일은 저장되고 화면에도 뜨지만 **모델은 한 번도 본 적이 없다.**
`chat_llm_service._build_messages`(`neos/services/chat_llm_service.py:88-97`)가 각
메시지에서 `role`과 `content`만 읽고 나머지를 버린다.

이 설계는 그 마지막 한 홉을 잇는다. 왕복의 나머지(업로드 → 저장 → 복원 → 편집 시
보존)는 이미 닫혀 있다 — `2026-09-03-history-tail-and-attachment-roundtrip.md`,
`2026-09-04-llm-input-correctness-and-attachment-edit.md`.

---

## 2. 실측이 이미 정한 것 — 설계 결정 다섯 중 둘은 선택지가 없다

### 2.1 프로바이더별 content block 조립은 하지 않는다

`ModelProviderBase.create_llm()`이 LangChain `BaseLanguageModel`을 반환한다
(`neos/providers/base.py:29-49`). 설치된 `langchain-core 1.5.6`은 표준 content block
(`ImageContentBlock`·`FileContentBlock`: `type` + `url|base64|file_id` + `mime_type`)을
갖고, `langchain_anthropic.chat_models._format_data_content_block`
(`:356`)이 그것을 Anthropic `image`/`document` 블록으로,
`langchain_openai.chat_models.base._format_message_content`(`:317`, 이미지 분기 `:361-385`)가
OpenAI `image_url`/`input_file`로 각각 번역한다.

→ **표준 블록 하나를 만들면 된다.** `neos/workflow/pipelines/vision/`의 세 SDK
직호출 구현((a))은 자기 용도로 남는다 — 챗 경로로 끌어오지 않는다.

⚠️ **번역기는 MIME 지원 여부를 검증하지 않는다.** `.docx`를 넣으면 그대로 실어
보내고 API가 400을 낸다. 검증은 우리 몫이다(§4.3 게이트).

### 2.2 URL이 아니라 base64다

`storage_url`은 HTTP URL이 아니라 `s3://bucket/key`(S3/RustFS) 또는
`file:///path`(로컬)다(`neos/storage/storage_service.py:165,264`). 어느 프로바이더도
가져갈 수 없다. presigned URL은 S3에서만 되고 로컬은 `file://`를 돌려주므로
**전 환경에서 동작하는 경로는 base64 하나뿐이다.**

---

## 3. 확정한 결정 다섯

| # | 결정 | 근거 |
|---|---|---|
| 1 | content block은 **LangChain 표준 블록** 하나 (+ raw SDK 경로용 네이티브 렌더러) | §2.1 |
| 2 | 능력 플래그는 `models.yaml`의 모델별 `vision: bool`, **읽는 곳은 거부 게이트** | 카탈로그가 모델 사실의 단일 원천. (c)의 교훈 — 읽는 곳 없는 플래그를 또 만들지 않는다 |
| 3 | 이미지 4종·PDF·TXT·MD는 **원본**, DOC/DOCX는 `word_parser`로 **텍스트 추출** | 프로바이더가 문서 블록으로 받는 것은 PDF와 텍스트뿐이다. Word 계열은 어느 쪽도 받지 않는다 |
| 4 | 바이트는 **base64**, 출처는 `documentId` → `Document` 조회 | §2.2. FE가 이미 `documentId`를 갖고 있다(업로드 응답) |
| 5 | vision 미지원 모델 + 이미지/PDF 첨부 → **거부하고 이유를 돌려준다** | 조용한 실패 금지. N8의 증상이 정확히 "조용히 사라짐"이었다 |

---

## 4. 설계

### 4.1 구성 요소

| 단위 | 책임 | 의존 |
|---|---|---|
| `neos/services/attachment_blocks.py` **(신규)** | 정책 전부 — 해석·분류·추출·상한·게이트 | `StorageService`, `word_parser`, `model_config`, `ChatRepository`/`Document` |
| ↳ `build_attachment_blocks(attachments, *, model, renderer) -> list[dict]` | 공개 진입점 | — |
| ↳ `_render_langchain(part) -> dict` | 표준 블록 | — |
| ↳ `_render_anthropic(part) -> dict` | 네이티브 블록 | — |
| `chat_llm_service._build_messages` | 한 줄 호출 (LangChain 경로) | 위 |
| `chat_llm_service.generate_response_stream_with_tools` | 한 줄 호출 (raw SDK 경로) | 위 |
| `chat_llm_service.generate_response_stream_with_tool_search` | 한 줄 호출 (raw SDK 경로) | 위 |
| `neos/config/model_config.py` `ModelSpec` | `vision: bool = False` 추가 | — |
| `neos/config/models.yaml` | 모델별 `vision` 사실 | — |
| `web/lib/message-parts.ts` `extractAttachments` | `metadata.documentId` 추가 | — |

**경계:** 렌더러 둘은 *모양*만 다르다. "무엇을 보낼 수 있는가"는 전부 렌더 앞단에
있고, 세 경로가 같은 판정을 받는다.

### 4.2 사본이 셋이라는 사실 (이 설계의 중심)

`chat_llm_service`는 대화 메시지를 **세 곳에서 각자 조립한다**:

1. `_build_messages`(`:75`) — LangChain 경로. `generate_response`(`:246`)와
   `generate_response_stream`(`:367`)이 쓴다
2. `generate_response_stream_with_tools`(`:552-560`) — **raw Anthropic SDK**,
   `anthropic_messages`를 인라인으로 조립
3. `generate_response_stream_with_tool_search`(`:764-768`) — 또 하나의 인라인 사본

`neos/api/services/chat_stream_strategy.py`가 툴 정책에 따라 셋 중 하나를 고르므로
**FE 챗 한 턴이 셋 중 어디로든 간다.** `_build_messages`에만 고치면 툴 경로에서
첨부가 다시 사라진다 — "고침이 한 호출부에만 도착하는" 실패의 재현이다.

이 설계는 사본을 합치지 않는다(§6). 대신 셋이 **같은 빌더**를 부르고, 넷째 사본이
생기면 테스트가 빨개진다(§5).

### 4.3 한 턴의 흐름

```
attachments[{url:"s3://…", name, metadata:{mediaType, documentId}}]
  ↓ resolve()    documentId → Document(storage_key, mime_type, file_size, page_count)
  │              ↳ documentId 없음(옛 메시지) → storage_url 로 Document 역조회
  │              ↳ 둘 다 실패 → §4.5 해석 실패 규칙
  ↓ classify()   image/jpeg·png·gif·webp        → IMAGE
  │              application/pdf                 → FILE
  │              text/plain, text/markdown       → FILE(text)
  │              application/msword, …docx       → EXTRACT (word_parser → 텍스트)
  ↓ gate()       spec.vision == False 이고 IMAGE|FILE 이 있으면 → 거부 (§4.6)
  ↓ budget()     원본 바이트 합계 상한 적용 (§4.4)
  ↓ fetch()      StorageService.download(storage_key) → base64
  ↓ render()     LangChain 표준 블록 | Anthropic 네이티브 블록
```

`EXTRACT`는 게이트를 통과한다 — 결과가 텍스트라 vision 없는 모델도 받는다.
MIME 판정은 **서버가 아는 값**(`Document.mime_type`)을 우선하고, 없을 때만
FE가 준 `metadata.mediaType`을 쓴다.

### 4.4 무엇을 싣는가 — 히스토리와 상한

첨부는 현재 턴에만 있는 것이 아니다. 대화가 길어지면 과거 턴의 이미지가 매 요청마다
다시 실려 비용이 선형으로 는다.

**규칙:** 모든 `user` 메시지의 첨부를 싣되, **원본 바이트 합계 20MB**를 상한으로 두고
**최신 메시지부터 채운다.** 상한을 넘겨 못 실은 첨부는 버리지 않고
`[첨부: {파일명} — 길이 상한으로 이번 요청에 포함되지 않음]` 텍스트로 강등하고,
그 사실을 응답 메타데이터에 남긴다.

상한 20MB의 근거: Anthropic 요청 한도가 32MB이고 base64가 약 1.37배로 부풀므로
20MB × 1.37 ≈ 27MB로 한도 아래에 머문다. FE 업로드 상한(파일당 50MB)보다 낮으므로
**단일 파일이 20MB를 넘으면 그 자체로 강등 대상**이다.

PDF 페이지 상한은 600으로 둔다(`Document.page_count`가 있을 때만 검사).

### 4.5 해석 실패 규칙 — 옛 메시지 대 현재 턴

`documentId`도 없고 `storage_url` 역조회도 실패하는 첨부가 있을 수 있다(이 변경 전에
저장된 메시지, 삭제된 문서).

- **현재 턴(마지막 user 메시지)의 첨부**가 해석되지 않으면 → **거부**한다.
  사용자가 방금 붙인 파일이 조용히 사라지는 것이 N8이 고치려는 바로 그 증상이다.
- **과거 턴의 첨부**가 해석되지 않으면 → 그 첨부만 §4.4의 텍스트 강등으로 처리하고
  턴은 진행한다. 과거 첨부는 맥락이지 사용자의 현재 행위가 아니며, 거부하면 옛
  대화를 이어갈 수 없게 된다.

두 경우 모두 사유가 남는다 — 어느 쪽도 조용하지 않다.

### 4.6 거부 계약

빌더가 `AttachmentNotSupportedError(model, unsupported=[{name, mime, reason}])`를
올린다. 세 경로가 각자 옮긴다:

- 스트림 둘: 기존 이벤트 계약을 유지한 채
  `{"type": "error", "error": <사람이 읽는 문장>, "code": "attachment_unsupported"}`
- 비스트림(`generate_response`): 핸들러에서 **422**로 변환

사람이 읽는 문장은 무엇이 왜 막혔는지 말한다 — 예:
`"gpt-4o-mini는 이미지를 받지 않습니다. 첨부 2개(scan.png, report.pdf)를 보내려면 vision 지원 모델을 선택하세요."`

### 4.7 카탈로그 스키마

`ModelSpec`(`neos/config/model_config.py:63`)은 `StrictConfigModel`이라 YAML에 새
키를 쓰려면 스키마에 먼저 있어야 한다. `vision: bool = False`를 더하고 각 모델에
사실을 적는다.

**PDF도 이 플래그로 가른다** — Anthropic은 PDF 페이지를 이미지로 렌더하므로 vision과
같은 조건이다. 플래그를 둘로 쪼개지 않는 이유는 지금 그 둘을 가르는 모델이 카탈로그에
없기 때문이다. 갈리는 모델이 생기면 그때 쪼갠다.

`supports_video`(`models.yaml:178`)는 **건드리지 않는다.** (c)에서 죽은 필드로
지목했지만 되살리는 것은 N8의 범위가 아니다. 새 `vision`은 처음부터 읽는 곳과 함께
들어간다 — 게이트가 그 유일한 소비자이고, 게이트 테스트가 그것을 고정한다.

### 4.8 FE 변경

`extractAttachments`(`web/lib/message-parts.ts:81`)가 `metadata`에 `documentId`를
싣는다. 업로드 라우트가 이미 응답으로 돌려주고 있으므로(`route.ts` — `documentId`)
FE 파트에 그 값을 보존하는 것이 전부다.

BE는 `documentId` 없는 첨부도 계속 받는다(§4.5) — 배포 순서에 의존하지 않는다.

---

## 5. 테스트 전략

TDD. 게이트·분류·상한·거부는 스토리지와 LLM 없이 단위로 검증된다.

1. **사본 고정 테스트** — `chat_llm_service`에서 `conversation_messages`를 순회해
   메시지를 조립하는 지점을 **이름으로** 열거하고, 목록에 없는 넷째가 생기면 빨개진다.
   개수만 세면 누가 빠졌는지 말하지 못한다.
2. **경로별 도달 테스트** — 세 경로 각각에 "이미지 첨부 → 블록이 실제로 실린다"와
   "vision=False 모델 → 거부"를 **따로** 건다. 한 경로만 통과하는 고침이 이 항목의
   실패 모양이다.
3. **렌더러 골든** — 표준 블록과 Anthropic 네이티브 블록의 정확한 모양을 고정한다.
4. **분류·게이트 단위** — MIME 9종 각각이 IMAGE/FILE/EXTRACT 중 어디로 가는지,
   DOCX가 텍스트로 내려오는지, 게이트가 EXTRACT는 통과시키는지.
5. **상한·강등** — 20MB를 넘길 때 최신부터 채우고 나머지가 텍스트로 강등되는지.
6. **해석 실패** — 현재 턴은 거부, 과거 턴은 강등.
7. **FE** — `extractAttachments`가 `documentId`를 보존하고, 없던 형식도 계속 통과하는지
   (`web/tests/source/`).

검증 명령은 `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §10.4를 따른다.

---

## 6. 하지 않는 것

- raw SDK 두 경로를 LangChain으로 통합하지 않는다 — tool calling·beta tool search·
  `pause_turn` 처리가 걸려 있어 회귀 위험이 N8의 값을 넘는다
- `neos/workflow/pipelines/vision/`을 건드리지 않는다
- 고아 `/api/v1/multimodal/*`를 챗에 연결하지 않는다 — (b)의 별도 항목
- 오디오(N3)·비디오를 다루지 않는다
- presigned URL을 만들지 않는다
- FE 허용 MIME 목록을 바꾸지 않는다
- `supports_video`를 되살리지 않는다

---

## 7. 참조

- `docs/ROADMAP.md` §N8 — 원장 항목과 (a)~(d)
- `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §7 WORKSPACE1 — 사본을 하나로 모으는 선례
- `docs/superpowers/plans/2026-09-03-history-tail-and-attachment-roundtrip.md`
- `docs/superpowers/plans/2026-09-04-llm-input-correctness-and-attachment-edit.md`
