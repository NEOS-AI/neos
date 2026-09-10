# N8 — 첨부가 모델에 도달한다 (멀티모달 입력) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 붙인 이미지·PDF·문서가 실제로 모델 입력에 실리고, 실을 수 없을 때는 조용히 사라지는 대신 이유가 돌아온다.

**Architecture:** 정책 전부를 새 모듈 `neos/services/attachment_blocks.py` 하나에 넣는다. 비동기 해석(`resolve_attachments`)이 요청당 한 번 DB·스토리지를 때려 `AttachmentPlan`을 만들고, `chat_llm_service`의 **세 메시지 조립 사본**이 각자 순수 함수 `merge_into_content()`로 그 결과를 자기 형식(LangChain 표준 블록 / Anthropic 네이티브 블록)에 병합한다. 능력 게이트는 카탈로그의 새 `vision` 플래그를 읽는다.

**Tech Stack:** Python 3.12 · LangChain 1.5.6 (표준 content block + 프로바이더 번역기) · Anthropic SDK (raw 경로 2곳) · SQLAlchemy 2.0 async · pytest · Next.js/TypeScript(`node:test`)

**Spec:** `docs/superpowers/specs/2026-09-05-n8-attachment-multimodal-design.md`

## Global Constraints

- 신규 정책 모듈은 `neos/services/attachment_blocks.py` 하나. 정책(분류·게이트·상한·해석)은 여기 밖에 두지 않는다.
- 메시지 조립 사본은 셋이고 **셋 다** 배선한다: `_build_messages`(`neos/services/chat_llm_service.py:75`), `generate_response_stream_with_tools`(`:552-560`), `generate_response_stream_with_tool_search`(`:764-768`).
- 바이트 전달은 **base64만**. `storage_url`은 `s3://`/`file://`라 URL 전달은 불가능하다.
- 이미지 MIME 4종(`image/jpeg`·`image/png`·`image/gif`·`image/webp`), PDF(`application/pdf`), 텍스트 2종(`text/plain`·`text/markdown`)은 원본. Word 2종(`application/msword`·`application/vnd.openxmlformats-officedocument.wordprocessingml.document`)은 `parse_word()`로 텍스트 추출.
- 상한: 원본 바이트 합계 `MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024`, PDF `MAX_PDF_PAGES = 600`.
- 능력 플래그 이름은 `vision`. `ModelSpec`은 `StrictConfigModel`이라 YAML보다 스키마가 먼저다. `supports_video`는 건드리지 않는다.
- 거부 예외 이름은 `AttachmentNotSupportedError`. 스트림 이벤트 코드는 `"attachment_unsupported"`, 비스트림은 HTTP 422.
- 커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다.
- 검증 명령은 `.venv` 경로로 돈다: `.venv/bin/python -m pytest ...` (bare `pytest`는 asyncio 마커 수집에 실패한다).

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `neos/services/attachment_blocks.py` **(신규)** | 분류·게이트·해석·상한·렌더·병합. 이 계획의 본체 |
| `neos/config/model_config.py` (수정) | `ModelSpec.vision` 필드 + `supports_vision()` 헬퍼 |
| `neos/config/models.yaml` (수정) | 모델별 `vision` 사실 |
| `neos/services/chat_llm_service.py` (수정) | 세 조립 사본이 병합 함수를 부른다 + 거부를 이벤트/예외로 옮긴다 |
| `neos/api/handlers/chat_handlers.py` (수정) | 비스트림 경로의 422 매핑 |
| `web/lib/message-parts.ts` (수정) | `metadata.documentId` 보존 |
| `tests/config/test_model_catalog.py` (수정) | `vision` 파싱 고정 |
| `tests/services/test_attachment_blocks.py` **(신규)** | 분류·게이트·렌더·병합 (I/O 없음) |
| `tests/services/test_attachment_resolution.py` **(신규)** | 해석·상한·강등·해석 실패 (스토리지/DB는 목) |
| `tests/services/test_chat_llm_attachment_paths.py` **(신규)** | 세 경로 도달 + 사본 고정 |
| `web/tests/source/message-parts.test.ts` (수정) | `documentId` 보존 |

---

## Task 1: 카탈로그에 `vision` 플래그와 그 유일한 독자

**Files:**
- Modify: `neos/config/model_config.py:63-75` (`ModelSpec`), 파일 끝 모듈 함수 구역(`:488` 부근)
- Modify: `neos/config/models.yaml`
- Test: `tests/config/test_model_catalog.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: `ModelSpec.vision: bool` · `neos.config.model_config.supports_vision(model: str) -> bool` — 카탈로그에 없는 모델은 `False`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/config/test_model_catalog.py` 끝에 붙인다.

```python
def test_vision_flag_defaults_to_false_and_parses() -> None:
    from neos.config.model_config import ModelCatalog

    catalog = ModelCatalog.model_validate(
        {
            "models": {
                "seeing-model": {"provider": "anthropic", "vision": True},
                "blind-model": {"provider": "openai"},
            },
            "aliases": {},
            "defaults": {},
        }
    )

    assert catalog.models["seeing-model"].vision is True
    assert catalog.models["blind-model"].vision is False


def test_supports_vision_reads_the_live_catalog() -> None:
    from neos.config.model_config import supports_vision

    # 카탈로그에 없는 모델은 능력을 주장하지 않는다
    assert supports_vision("no-such-model-xyz") is False
    # 카탈로그가 True 로 적은 모델은 True 다
    assert supports_vision("claude-sonnet-5") is True
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/config/test_model_catalog.py -k vision -v
```

기대: `ValidationError`(`vision`은 `StrictConfigModel`이 모르는 키) 또는 `ImportError: cannot import name 'supports_vision'`.

- [ ] **Step 3: 스키마와 헬퍼를 넣는다**

`neos/config/model_config.py`의 `ModelSpec`에 한 줄:

```python
class ModelSpec(StrictConfigModel):
    provider: CatalogProvider
    tiers: list[Tier] = Field(default_factory=list)
    thinking: ThinkingContract = ThinkingContract.BUDGETED
    selectable: bool = True
    max_tokens: int | None = None
    description: str | None = None
    # 이미지·PDF 입력을 받는가. 유일한 독자는 첨부 게이트
    # (neos/services/attachment_blocks.py) — 읽는 곳 없이 스키마만
    # 늘리지 않기 위해 게이트와 같은 변경으로 들어왔다.
    vision: bool = False
    supports_video: bool = False
    dimension: int | None = None
    pricing: ModelPricing | None = None
```

모듈 함수 구역(`get_model_spec` 옆)에:

```python
def supports_vision(model: str) -> bool:
    """모델이 이미지·PDF 입력을 받는가. 카탈로그가 유일한 원천이다."""
    spec = model_config.catalog.get_model_spec(model)
    return bool(spec and spec.vision)
```

- [ ] **Step 4: YAML에 사실을 적는다**

`neos/config/models.yaml`의 각 모델에 `vision: true`를 더한다 — Anthropic `claude-opus-5`·`claude-opus-4-8`·`claude-sonnet-5`·`claude-haiku-4-5-20251001`, OpenAI `gpt-5.6-sol`·`gpt-5.6-terra`·`gpt-4o`, Gemini `gemini-1.5-pro-latest`·`gemini-2.0-flash-exp`. 나머지(임베딩 모델, Ollama 텍스트 모델)는 기본값 `false`를 그대로 둔다.

⚠️ 카탈로그의 실제 모델 목록을 먼저 읽고 그 목록에 맞춰 적는다:

```bash
.venv/bin/python -c "
from neos.config.model_config import model_config
for name, spec in model_config.catalog.models.items():
    print(f'{name:40} {spec.provider}')
"
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

```bash
.venv/bin/python -m pytest tests/config/test_model_catalog.py -v
```

기대: PASS (기존 테스트 포함 전부).

- [ ] **Step 6: 커밋**

```bash
git add neos/config/model_config.py neos/config/models.yaml tests/config/test_model_catalog.py
git commit -m "feat(config): add vision capability flag to the model catalog"
```

---

## Task 2: 분류와 게이트 — I/O 없는 순수 정책

**Files:**
- Create: `neos/services/attachment_blocks.py`
- Test: `tests/services/test_attachment_blocks.py`

**Interfaces:**
- Consumes: `neos.config.model_config.supports_vision` (Task 1)
- Produces:
  - `class AttachmentKind(str, Enum)`: `IMAGE` · `FILE` · `FILE_TEXT` · `EXTRACT`
  - `classify(mime_type: str) -> AttachmentKind | None` — 허용 9종 밖이면 `None`
  - `class AttachmentNotSupportedError(Exception)` — `.model: str`, `.items: list[dict]`(`{"name","mime","reason"}`), `.code = "attachment_unsupported"`, `.human_message() -> str`
  - `MAX_ATTACHMENT_BYTES` · `MAX_PDF_PAGES`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/services/test_attachment_blocks.py` (신규):

```python
import pytest

from neos.services.attachment_blocks import (
    AttachmentKind,
    AttachmentNotSupportedError,
    classify,
)


@pytest.mark.parametrize(
    "mime,expected",
    [
        ("image/jpeg", AttachmentKind.IMAGE),
        ("image/png", AttachmentKind.IMAGE),
        ("image/gif", AttachmentKind.IMAGE),
        ("image/webp", AttachmentKind.IMAGE),
        ("application/pdf", AttachmentKind.FILE),
        ("text/plain", AttachmentKind.FILE_TEXT),
        ("text/markdown", AttachmentKind.FILE_TEXT),
        ("application/msword", AttachmentKind.EXTRACT),
        (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document",
            AttachmentKind.EXTRACT,
        ),
    ],
)
def test_classify_covers_all_nine_allowed_mime_types(mime, expected) -> None:
    assert classify(mime) is expected


def test_classify_rejects_unknown_mime() -> None:
    assert classify("application/zip") is None


def test_error_names_every_blocked_attachment_and_the_model() -> None:
    err = AttachmentNotSupportedError(
        model="blind-model",
        items=[
            {"name": "scan.png", "mime": "image/png", "reason": "vision_unsupported"},
            {"name": "report.pdf", "mime": "application/pdf", "reason": "vision_unsupported"},
        ],
    )

    assert err.code == "attachment_unsupported"
    message = err.human_message()
    assert "blind-model" in message
    assert "scan.png" in message
    assert "report.pdf" in message
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_attachment_blocks.py -v
```

기대: `ModuleNotFoundError: No module named 'neos.services.attachment_blocks'`.

- [ ] **Step 3: 최소 구현**

`neos/services/attachment_blocks.py` (신규):

```python
"""첨부 → 모델 입력 블록.

N8. 정책(분류·게이트·상한·해석)은 전부 이 모듈에 있고, `chat_llm_service`의
세 메시지 조립 사본은 렌더 결과만 병합한다. 설계는
`docs/superpowers/specs/2026-09-05-n8-attachment-multimodal-design.md`.
"""

from __future__ import annotations

from enum import Enum

#: 원본 바이트 합계 상한. Anthropic 요청 한도 32MB 를 base64 팽창(약 1.37배)
#: 뒤에도 넘지 않도록 20MB 로 둔다.
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024

#: PDF 페이지 상한.
MAX_PDF_PAGES = 600

_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

_KIND_BY_MIME = {
    "image/jpeg": "IMAGE",
    "image/png": "IMAGE",
    "image/gif": "IMAGE",
    "image/webp": "IMAGE",
    "application/pdf": "FILE",
    "text/plain": "FILE_TEXT",
    "text/markdown": "FILE_TEXT",
    "application/msword": "EXTRACT",
    _DOCX_MIME: "EXTRACT",
}


class AttachmentKind(str, Enum):
    """첨부가 모델에 어떤 모양으로 가는가."""

    IMAGE = "IMAGE"          # 이미지 블록
    FILE = "FILE"            # 문서 블록 (PDF 원본)
    FILE_TEXT = "FILE_TEXT"  # 문서 블록 (텍스트 원본)
    EXTRACT = "EXTRACT"      # 텍스트로 추출해 본문에 붙인다


def classify(mime_type: str) -> AttachmentKind | None:
    """허용 9종을 종류로 가른다. 목록 밖이면 None."""
    kind = _KIND_BY_MIME.get((mime_type or "").lower())
    return AttachmentKind(kind) if kind else None


class AttachmentNotSupportedError(Exception):
    """첨부를 이 모델로 보낼 수 없다. 조용히 버리지 않는다."""

    code = "attachment_unsupported"

    def __init__(self, model: str, items: list[dict]) -> None:
        self.model = model
        self.items = items
        super().__init__(self.human_message())

    def human_message(self) -> str:
        names = ", ".join(item["name"] for item in self.items)
        return (
            f"{self.model}는 첨부 {len(self.items)}개({names})를 받지 않습니다. "
            "이미지·PDF를 보내려면 vision 지원 모델을 선택하세요."
        )
```

- [ ] **Step 4: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_attachment_blocks.py -v
```

기대: PASS.

- [ ] **Step 5: 게이트 테스트를 더한다**

같은 파일에 붙인다:

```python
def test_gate_blocks_image_for_a_model_without_vision(monkeypatch) -> None:
    from neos.services import attachment_blocks

    monkeypatch.setattr(attachment_blocks, "supports_vision", lambda model: False)

    with pytest.raises(AttachmentNotSupportedError) as excinfo:
        attachment_blocks.assert_model_accepts(
            model="blind-model",
            kinds=[(AttachmentKind.IMAGE, "scan.png", "image/png")],
        )

    assert excinfo.value.items[0]["reason"] == "vision_unsupported"


def test_gate_lets_extracted_text_through_without_vision(monkeypatch) -> None:
    from neos.services import attachment_blocks

    monkeypatch.setattr(attachment_blocks, "supports_vision", lambda model: False)

    # EXTRACT 는 결과가 텍스트라 vision 없는 모델도 받는다
    attachment_blocks.assert_model_accepts(
        model="blind-model",
        kinds=[(AttachmentKind.EXTRACT, "memo.docx", "application/msword")],
    )
```

- [ ] **Step 6: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_attachment_blocks.py -k gate -v
```

기대: FAIL — `assert_model_accepts` 없음.

- [ ] **Step 7: 게이트를 구현한다**

`attachment_blocks.py`의 import에 더한다:

```python
from neos.config.model_config import supports_vision
```

파일 끝에:

```python
#: vision 능력을 요구하는 종류. EXTRACT 는 텍스트가 되므로 빠진다.
_KINDS_REQUIRING_VISION = (AttachmentKind.IMAGE, AttachmentKind.FILE)


def assert_model_accepts(
    model: str, kinds: list[tuple[AttachmentKind, str, str]]
) -> None:
    """모델이 못 받는 첨부가 있으면 AttachmentNotSupportedError 를 올린다.

    Args:
        model: 이 턴이 쓰는 모델 식별자
        kinds: (종류, 파일명, MIME) 튜플 목록
    """
    if supports_vision(model):
        return

    blocked = [
        {"name": name, "mime": mime, "reason": "vision_unsupported"}
        for kind, name, mime in kinds
        if kind in _KINDS_REQUIRING_VISION
    ]
    if blocked:
        raise AttachmentNotSupportedError(model=model, items=blocked)
```

- [ ] **Step 8: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_attachment_blocks.py -v
```

기대: PASS 전부.

- [ ] **Step 9: 커밋**

```bash
git add neos/services/attachment_blocks.py tests/services/test_attachment_blocks.py
git commit -m "feat(attachments): classify the nine allowed MIME types and gate on model vision"
```

---

## Task 3: 렌더러 둘과 병합 — 여전히 I/O 없음

**Files:**
- Modify: `neos/services/attachment_blocks.py`
- Test: `tests/services/test_attachment_blocks.py`

**Interfaces:**
- Consumes: `AttachmentKind` (Task 2)
- Produces:
  - `@dataclass(frozen=True) class ResolvedAttachment`: `name: str`, `mime_type: str`, `kind: AttachmentKind`, `data: bytes | None`, `text: str | None`
  - `render_langchain(att: ResolvedAttachment) -> dict`
  - `render_anthropic(att: ResolvedAttachment) -> dict`
  - `merge_into_content(content: str, attachments: list[ResolvedAttachment], renderer) -> str | list[dict]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
import base64

from neos.services.attachment_blocks import (
    ResolvedAttachment,
    merge_into_content,
    render_anthropic,
    render_langchain,
)


def _image() -> ResolvedAttachment:
    return ResolvedAttachment(
        name="scan.png",
        mime_type="image/png",
        kind=AttachmentKind.IMAGE,
        data=b"\x89PNG-bytes",
        text=None,
    )


def test_render_langchain_emits_a_standard_image_block() -> None:
    block = render_langchain(_image())

    assert block == {
        "type": "image",
        "base64": base64.b64encode(b"\x89PNG-bytes").decode("ascii"),
        "mime_type": "image/png",
    }


def test_render_anthropic_emits_a_native_image_block() -> None:
    block = render_anthropic(_image())

    assert block == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(b"\x89PNG-bytes").decode("ascii"),
        },
    }


def test_render_anthropic_emits_a_document_block_for_pdf() -> None:
    pdf = ResolvedAttachment(
        name="report.pdf",
        mime_type="application/pdf",
        kind=AttachmentKind.FILE,
        data=b"%PDF-bytes",
        text=None,
    )

    assert render_anthropic(pdf)["type"] == "document"
    assert render_langchain(pdf)["type"] == "file"


def test_merge_returns_plain_text_when_there_are_no_attachments() -> None:
    assert merge_into_content("안녕", [], render_langchain) == "안녕"


def test_merge_puts_blocks_before_the_text() -> None:
    merged = merge_into_content("이 이미지 설명해줘", [_image()], render_langchain)

    assert isinstance(merged, list)
    assert merged[0]["type"] == "image"
    assert merged[-1] == {"type": "text", "text": "이 이미지 설명해줘"}


def test_extracted_text_joins_the_text_block_not_a_media_block() -> None:
    docx = ResolvedAttachment(
        name="memo.docx",
        mime_type="application/msword",
        kind=AttachmentKind.EXTRACT,
        data=None,
        text="분기 실적 요약",
    )

    merged = merge_into_content("요약해줘", [docx], render_langchain)

    assert merged == [
        {"type": "text", "text": "[첨부 memo.docx 의 텍스트]\n분기 실적 요약"},
        {"type": "text", "text": "요약해줘"},
    ]
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_attachment_blocks.py -k "render or merge or extracted" -v
```

기대: `ImportError: cannot import name 'ResolvedAttachment'`.

- [ ] **Step 3: 구현한다**

`attachment_blocks.py` import에 더한다:

```python
import base64
from dataclasses import dataclass
from typing import Callable
```

파일에 더한다:

```python
@dataclass(frozen=True)
class ResolvedAttachment:
    """해석이 끝난 첨부 하나. 렌더 직전 상태다."""

    name: str
    mime_type: str
    kind: AttachmentKind
    #: IMAGE·FILE·FILE_TEXT 의 원본 바이트
    data: bytes | None
    #: EXTRACT 의 추출 텍스트, 또는 상한/해석 실패로 강등된 첨부의 안내 문구
    text: str | None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def render_langchain(att: ResolvedAttachment) -> dict:
    """LangChain 표준 content block. 프로바이더 번역은 LangChain 이 한다."""
    block_type = "image" if att.kind is AttachmentKind.IMAGE else "file"
    return {
        "type": block_type,
        "base64": _b64(att.data or b""),
        "mime_type": att.mime_type,
    }


def render_anthropic(att: ResolvedAttachment) -> dict:
    """Anthropic 네이티브 block. raw SDK 를 쓰는 두 경로용이다."""
    if att.kind is AttachmentKind.IMAGE:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": att.mime_type,
                "data": _b64(att.data or b""),
            },
        }
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": att.mime_type,
            "data": _b64(att.data or b""),
        },
    }


def merge_into_content(
    content: str,
    attachments: list[ResolvedAttachment],
    renderer: Callable[[ResolvedAttachment], dict],
) -> str | list[dict]:
    """본문과 첨부를 하나의 content 로 합친다.

    첨부가 없으면 문자열을 그대로 돌려준다 — 기존 동작을 바꾸지 않기 위해서다.
    미디어 블록은 본문 앞에 온다(프로바이더 권장 순서).
    """
    if not attachments:
        return content

    blocks: list[dict] = []
    for att in attachments:
        if att.data is not None:
            blocks.append(renderer(att))
        elif att.text:
            blocks.append(
                {"type": "text", "text": f"[첨부 {att.name} 의 텍스트]\n{att.text}"}
            )

    blocks.append({"type": "text", "text": content})
    return blocks
```

- [ ] **Step 4: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_attachment_blocks.py -v
```

기대: PASS 전부.

- [ ] **Step 5: 커밋**

```bash
git add neos/services/attachment_blocks.py tests/services/test_attachment_blocks.py
git commit -m "feat(attachments): render standard and native blocks from one resolved shape"
```

---

## Task 4: 해석 — documentId·스토리지·DOCX 추출·상한·강등

**Files:**
- Modify: `neos/services/attachment_blocks.py`
- Test: `tests/services/test_attachment_resolution.py` (신규)

**Interfaces:**
- Consumes: `ResolvedAttachment`·`classify`·`assert_model_accepts`·`MAX_ATTACHMENT_BYTES` (Task 2·3)
- Produces:
  - `@dataclass(frozen=True) class AttachmentPlan`: `by_index: dict[int, list[ResolvedAttachment]]`, `notices: list[str]`
  - `async def resolve_attachments(conversation_messages: list[dict], *, model: str) -> AttachmentPlan`
  - 내부 이음매(테스트가 패치한다): `_load_document(...)`, `_download(...)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/services/test_attachment_resolution.py` (신규):

```python
import pytest

from neos.services import attachment_blocks
from neos.services.attachment_blocks import (
    AttachmentKind,
    AttachmentNotSupportedError,
    resolve_attachments,
)


class _Doc:
    """Document 행의 최소 대역."""

    def __init__(self, mime_type, storage_key="k", file_size=10, page_count=None):
        self.mime_type = mime_type
        self.storage_key = storage_key
        self.file_size = file_size
        self.page_count = page_count


def _message(content, attachments, role="user"):
    return {"role": role, "content": content, "attachments": attachments}


def _attachment(name, mime, document_id=1, url="s3://bucket/k"):
    return {
        "type": "file",
        "url": url,
        "name": name,
        "metadata": {"mediaType": mime, "documentId": document_id},
    }


@pytest.fixture
def stub_io(monkeypatch):
    """DB 와 스토리지를 이음매에서 끊는다."""
    docs = {}
    downloads = {}

    async def fake_load_document(*, document_id=None, storage_url=None):
        return docs.get(document_id)

    async def fake_download(storage_key):
        return downloads.get(storage_key, b"bytes")

    monkeypatch.setattr(attachment_blocks, "_load_document", fake_load_document)
    monkeypatch.setattr(attachment_blocks, "_download", fake_download)
    monkeypatch.setattr(attachment_blocks, "supports_vision", lambda model: True)
    return docs, downloads


@pytest.mark.asyncio
async def test_image_attachment_is_resolved_for_its_message(stub_io) -> None:
    docs, _ = stub_io
    docs[1] = _Doc("image/png")

    plan = await resolve_attachments(
        [_message("이 그림 봐줘", [_attachment("scan.png", "image/png")])],
        model="seeing-model",
    )

    resolved = plan.by_index[0][0]
    assert resolved.kind is AttachmentKind.IMAGE
    assert resolved.data == b"bytes"


@pytest.mark.asyncio
async def test_server_mime_wins_over_the_client_supplied_one(stub_io) -> None:
    docs, _ = stub_io
    docs[1] = _Doc("application/pdf")

    plan = await resolve_attachments(
        [_message("봐줘", [_attachment("f.pdf", "image/png")])],
        model="seeing-model",
    )

    assert plan.by_index[0][0].mime_type == "application/pdf"


@pytest.mark.asyncio
async def test_docx_is_extracted_to_text(stub_io, monkeypatch) -> None:
    docs, _ = stub_io
    docs[1] = _Doc("application/msword")

    async def fake_parse_word(file_content=None, file_path=None):
        return {"text": "분기 실적 요약"}

    monkeypatch.setattr(attachment_blocks, "parse_word", fake_parse_word)

    plan = await resolve_attachments(
        [_message("요약", [_attachment("memo.docx", "application/msword")])],
        model="seeing-model",
    )

    resolved = plan.by_index[0][0]
    assert resolved.kind is AttachmentKind.EXTRACT
    assert resolved.text == "분기 실적 요약"
    assert resolved.data is None


@pytest.mark.asyncio
async def test_gate_refuses_when_the_model_has_no_vision(stub_io, monkeypatch) -> None:
    docs, _ = stub_io
    docs[1] = _Doc("image/png")
    monkeypatch.setattr(attachment_blocks, "supports_vision", lambda model: False)

    with pytest.raises(AttachmentNotSupportedError):
        await resolve_attachments(
            [_message("봐줘", [_attachment("scan.png", "image/png")])],
            model="blind-model",
        )


@pytest.mark.asyncio
async def test_budget_fills_newest_first_and_demotes_the_rest(stub_io) -> None:
    docs, downloads = stub_io
    big = attachment_blocks.MAX_ATTACHMENT_BYTES
    docs[1] = _Doc("image/png", storage_key="old", file_size=big)
    docs[2] = _Doc("image/png", storage_key="new", file_size=big)
    downloads["old"] = b"o"
    downloads["new"] = b"n"

    plan = await resolve_attachments(
        [
            _message("옛 턴", [_attachment("old.png", "image/png", document_id=1)]),
            _message("새 턴", [_attachment("new.png", "image/png", document_id=2)]),
        ],
        model="seeing-model",
    )

    assert plan.by_index[1][0].data == b"n"          # 최신이 자리를 얻는다
    assert plan.by_index[0][0].data is None          # 오래된 것은 강등된다
    assert "old.png" in plan.by_index[0][0].text
    assert any("old.png" in notice for notice in plan.notices)


@pytest.mark.asyncio
async def test_unresolvable_attachment_is_refused_on_the_current_turn(stub_io) -> None:
    # docs 가 비어 있어 문서를 못 찾는다
    with pytest.raises(AttachmentNotSupportedError) as excinfo:
        await resolve_attachments(
            [_message("봐줘", [_attachment("gone.png", "image/png", document_id=99)])],
            model="seeing-model",
        )

    assert excinfo.value.items[0]["reason"] == "unresolved"


@pytest.mark.asyncio
async def test_unresolvable_attachment_is_demoted_on_an_older_turn(stub_io) -> None:
    docs, _ = stub_io
    docs[2] = _Doc("image/png")

    plan = await resolve_attachments(
        [
            _message("옛 턴", [_attachment("gone.png", "image/png", document_id=99)]),
            _message("새 턴", [_attachment("ok.png", "image/png", document_id=2)]),
        ],
        model="seeing-model",
    )

    assert plan.by_index[0][0].data is None
    assert "gone.png" in plan.by_index[0][0].text
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_attachment_resolution.py -v
```

기대: `ImportError: cannot import name 'resolve_attachments'`.

- [ ] **Step 3: 구현한다**

`attachment_blocks.py` import에 더한다:

```python
import logging

from sqlalchemy import select

from neos.config.settings import settings
from neos.database.connection import get_session
from neos.database.models import Document
from neos.storage.storage_service import StorageService
from neos.workflow.pipelines.word_parser import parse_word

logger = logging.getLogger(__name__)
```

파일에 더한다:

```python
@dataclass(frozen=True)
class AttachmentPlan:
    """요청 한 번 분의 해석 결과.

    `by_index` 는 `conversation_messages` 의 인덱스로 건다 — 메시지 dict 를
    변형하지 않아야 세 조립 사본이 각자 자기 형식으로 병합할 수 있다.
    """

    by_index: dict[int, list[ResolvedAttachment]]
    notices: list[str]


async def _load_document(*, document_id=None, storage_url=None):
    """documentId 우선, 없으면 storage_url 역조회. 못 찾으면 None."""
    async for session in get_session():
        if document_id is not None:
            result = await session.execute(
                select(Document).where(Document.id == int(document_id))
            )
            document = result.scalar_one_or_none()
            if document is not None:
                return document
        if storage_url:
            result = await session.execute(
                select(Document).where(Document.storage_url == storage_url)
            )
            return result.scalar_one_or_none()
        return None
    return None


async def _download(storage_key: str) -> bytes:
    provider = StorageService.create_provider(settings.STORAGE_PROVIDER)
    return await provider.download(storage_key)


def _demoted(name: str, mime_type: str, kind: AttachmentKind, why: str) -> ResolvedAttachment:
    return ResolvedAttachment(
        name=name,
        mime_type=mime_type,
        kind=kind,
        data=None,
        text=f"[첨부: {name} — {why}]",
    )


async def resolve_attachments(
    conversation_messages: list[dict], *, model: str
) -> AttachmentPlan:
    """첨부를 해석해 요청 한 번 분의 계획을 만든다.

    DB·스토리지 I/O 는 여기서 한 번만 일어난다. 조립 사본 셋은 결과만 쓴다.
    """
    indexed = [
        (index, message)
        for index, message in enumerate(conversation_messages)
        if message.get("role") == "user" and message.get("attachments")
    ]
    if not indexed:
        return AttachmentPlan(by_index={}, notices=[])

    current_index = indexed[-1][0]
    by_index: dict[int, list[ResolvedAttachment]] = {}
    notices: list[str] = []
    unresolved_now: list[dict] = []
    kinds_for_gate: list[tuple[AttachmentKind, str, str]] = []
    budget = MAX_ATTACHMENT_BYTES

    # 최신 메시지부터 예산을 채운다
    for index, message in reversed(indexed):
        resolved_here: list[ResolvedAttachment] = []

        for attachment in message.get("attachments") or []:
            metadata = attachment.get("metadata") or {}
            name = attachment.get("name") or "attachment"
            document = await _load_document(
                document_id=metadata.get("documentId"),
                storage_url=attachment.get("url"),
            )

            mime_type = (
                getattr(document, "mime_type", None)
                or metadata.get("mediaType")
                or ""
            )
            kind = classify(mime_type)

            if document is None or kind is None:
                if index == current_index:
                    unresolved_now.append(
                        {"name": name, "mime": mime_type, "reason": "unresolved"}
                    )
                else:
                    resolved_here.append(
                        _demoted(name, mime_type, AttachmentKind.EXTRACT, "해석할 수 없어 제외됨")
                    )
                    notices.append(f"{name}: 해석할 수 없어 제외됨")
                continue

            kinds_for_gate.append((kind, name, mime_type))

            page_count = getattr(document, "page_count", None)
            if kind is AttachmentKind.FILE and page_count and page_count > MAX_PDF_PAGES:
                resolved_here.append(
                    _demoted(name, mime_type, kind, f"{MAX_PDF_PAGES}페이지 상한 초과")
                )
                notices.append(f"{name}: 페이지 상한 초과로 제외됨")
                continue

            size = getattr(document, "file_size", None) or 0
            if kind is not AttachmentKind.EXTRACT and size > budget:
                resolved_here.append(
                    _demoted(name, mime_type, kind, "길이 상한으로 이번 요청에 포함되지 않음")
                )
                notices.append(f"{name}: 길이 상한으로 제외됨")
                continue

            data = await _download(document.storage_key)

            if kind is AttachmentKind.EXTRACT:
                parsed = await parse_word(file_content=data)
                resolved_here.append(
                    ResolvedAttachment(
                        name=name,
                        mime_type=mime_type,
                        kind=kind,
                        data=None,
                        text=parsed.get("text") or "",
                    )
                )
                continue

            budget -= len(data)
            resolved_here.append(
                ResolvedAttachment(
                    name=name, mime_type=mime_type, kind=kind, data=data, text=None
                )
            )

        if resolved_here:
            by_index[index] = list(reversed(resolved_here))

    if unresolved_now:
        raise AttachmentNotSupportedError(model=model, items=unresolved_now)

    assert_model_accepts(model=model, kinds=kinds_for_gate)

    return AttachmentPlan(by_index=by_index, notices=notices)
```

- [ ] **Step 4: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_attachment_resolution.py -v
```

기대: PASS 전부. `budget` 테스트에서 최신 것만 바이트를 얻고 오래된 것은 강등돼야 한다.

- [ ] **Step 5: 커밋**

```bash
git add neos/services/attachment_blocks.py tests/services/test_attachment_resolution.py
git commit -m "feat(attachments): resolve bytes, extract Word text, and apply the byte budget"
```

---

## Task 5: 세 조립 사본 배선 + 사본 고정 테스트

**Files:**
- Modify: `neos/services/chat_llm_service.py` (`_build_messages` `:75-99`, `generate_response` `:246`, `generate_response_stream` `:367`, `generate_response_stream_with_tools` `:552-560`, `generate_response_stream_with_tool_search` `:764-768`)
- Modify: `neos/api/handlers/chat_handlers.py:465` 부근 (비스트림 422)
- Test: `tests/services/test_chat_llm_attachment_paths.py` (신규)

**Interfaces:**
- Consumes: `resolve_attachments`·`merge_into_content`·`render_langchain`·`render_anthropic`·`AttachmentNotSupportedError`·`AttachmentPlan` (Task 2~4)
- Produces: `_build_messages(conversation_messages, system_prompt=None, plan=None)` — `plan`은 선택 인자라 기존 호출부가 깨지지 않는다

- [ ] **Step 1: 실패하는 테스트를 쓴다 — 사본 고정부터**

`tests/services/test_chat_llm_attachment_paths.py` (신규):

```python
import ast
import inspect

import pytest

from neos.services import chat_llm_service
from neos.services.attachment_blocks import (
    AttachmentKind,
    AttachmentPlan,
    ResolvedAttachment,
)

#: 대화 메시지를 각자 조립하는 지점. 넷째가 생기면 이 테스트가 빨개진다.
#: 개수가 아니라 이름으로 센다 — 개수는 누가 빠졌는지 말하지 않는다.
KNOWN_ASSEMBLERS = {
    "_build_messages",
    "generate_response_stream_with_tools",
    "generate_response_stream_with_tool_search",
}


MESSAGE_LIST_NAMES = {"conversation_messages", "optimized_messages"}


def _iterates_message_list(node: ast.For) -> bool:
    """`for … in messages:` 와 `for i, m in enumerate(messages):` 둘 다 센다.

    배선이 enumerate 를 도입하므로 Name 만 보면 사본을 놓친다.
    """
    target = node.iter
    if isinstance(target, ast.Call) and isinstance(target.func, ast.Name):
        if target.func.id != "enumerate" or not target.args:
            return False
        target = target.args[0]
    return isinstance(target, ast.Name) and target.id in MESSAGE_LIST_NAMES


def _functions_iterating_conversation_messages() -> set[str]:
    source = inspect.getsource(chat_llm_service)
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.For) and _iterates_message_list(inner):
                found.add(node.name)
    return found


def test_no_fourth_message_assembler_appears() -> None:
    found = _functions_iterating_conversation_messages()

    assert found == KNOWN_ASSEMBLERS, (
        "메시지 조립 사본이 바뀌었다. 새 사본이면 첨부 병합을 함께 배선하고 "
        f"KNOWN_ASSEMBLERS 에 이름을 더할 것. 실제: {sorted(found)}"
    )


def _plan_with_image(index: int) -> AttachmentPlan:
    return AttachmentPlan(
        by_index={
            index: [
                ResolvedAttachment(
                    name="scan.png",
                    mime_type="image/png",
                    kind=AttachmentKind.IMAGE,
                    data=b"png",
                    text=None,
                )
            ]
        },
        notices=[],
    )


def test_build_messages_carries_the_attachment_block() -> None:
    service = chat_llm_service.ChatLLMService()

    messages = service._build_messages(
        [{"role": "user", "content": "봐줘"}],
        None,
        plan=_plan_with_image(0),
    )

    content = messages[-1].content
    assert isinstance(content, list)
    assert content[0]["type"] == "image"
    assert content[-1] == {"type": "text", "text": "봐줘"}


def test_build_messages_without_a_plan_keeps_plain_strings() -> None:
    service = chat_llm_service.ChatLLMService()

    messages = service._build_messages([{"role": "user", "content": "안녕"}], None)

    assert messages[-1].content == "안녕"
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_chat_llm_attachment_paths.py -v
```

기대: `test_build_messages_carries_the_attachment_block`가
`TypeError: _build_messages() got an unexpected keyword argument 'plan'`로 실패.

사본 고정 테스트(`test_no_fourth_message_assembler_appears`)는 **이 시점에 이미 통과한다** —
배선 전에도 사본이 셋이기 때문이다. 그것이 맞는 상태다: 이 테스트는 새 기능을 이끄는
테스트가 아니라 **넷째가 생기는 것을 막는 가드**다. Step 3~6 의 배선 뒤에도 계속
통과해야 하고, 통과하지 않으면 배선이 사본을 하나 더 만들었다는 뜻이다.

- [ ] **Step 3: `_build_messages`를 배선한다**

`neos/services/chat_llm_service.py` import에 더한다:

```python
from neos.services.attachment_blocks import (
    AttachmentNotSupportedError,
    AttachmentPlan,
    merge_into_content,
    render_anthropic,
    render_langchain,
    resolve_attachments,
)
```

`_build_messages`를 고친다:

```python
    def _build_messages(
        self,
        conversation_messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        plan: Optional[AttachmentPlan] = None,
    ) -> List:
        """대화 메시지를 LangChain 메시지 형식으로 변환.

        `plan` 이 있으면 그 메시지의 첨부를 표준 content block 으로 병합한다.
        없으면 종전과 같이 문자열 content 를 만든다.
        """
        messages = []

        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))

        for index, msg in enumerate(conversation_messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                attachments = (plan.by_index.get(index) if plan else None) or []
                messages.append(
                    HumanMessage(
                        content=merge_into_content(
                            content, attachments, render_langchain
                        )
                    )
                )
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                messages.append(SystemMessage(content=content))

        return messages
```

- [ ] **Step 4: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_chat_llm_attachment_paths.py -v
```

기대: 네 테스트 전부 PASS.

- [ ] **Step 5: 두 호출부에서 계획을 만들어 넘긴다**

`generate_response`(`:246` 부근)와 `generate_response_stream`(`:367` 부근) 둘 다, `_build_messages` 호출 **직전**에 넣는다:

```python
            attachment_plan = await resolve_attachments(
                optimized_messages, model=model
            )
            messages = self._build_messages(
                optimized_messages, system_prompt, plan=attachment_plan
            )
```

- [ ] **Step 6: raw SDK 두 경로를 배선한다**

`generate_response_stream_with_tools`의 인라인 조립(`:552-560`)을 고친다:

```python
            attachment_plan = await resolve_attachments(
                conversation_messages, model=model
            )

            anthropic_messages = []
            for index, msg in enumerate(conversation_messages):
                role = msg.get("role", "user")
                content = msg.get("content", "")

                if role in ["user", "assistant"]:
                    attachments = (
                        attachment_plan.by_index.get(index) if role == "user" else None
                    ) or []
                    anthropic_messages.append({
                        "role": role,
                        "content": merge_into_content(
                            content, attachments, render_anthropic
                        ),
                    })
```

`generate_response_stream_with_tool_search`의 인라인 조립(`:764-768`)도 고친다. 원본이 한 줄로 압축돼 있으므로 아래를 그대로 쓴다:

```python
            attachment_plan = await resolve_attachments(
                conversation_messages, model=model
            )

            anthropic_messages = []
            for index, msg in enumerate(conversation_messages):
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ["user", "assistant"]:
                    attachments = (
                        attachment_plan.by_index.get(index) if role == "user" else None
                    ) or []
                    anthropic_messages.append({
                        "role": role,
                        "content": merge_into_content(
                            content, attachments, render_anthropic
                        ),
                    })
```

- [ ] **Step 7: 세 경로 도달 테스트를 더한다**

`tests/services/test_chat_llm_attachment_paths.py`에 붙인다:

```python
@pytest.mark.asyncio
async def test_tool_path_carries_the_attachment_block(monkeypatch) -> None:
    """raw SDK 경로도 첨부를 싣는다 — 여기가 비면 툴 대화에서만 조용히 사라진다."""
    captured = {}

    async def fake_resolve(messages, *, model):
        return _plan_with_image(0)

    def fake_normalize(model, kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop-after-assembly")

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)
    monkeypatch.setattr(chat_llm_service, "normalize_anthropic_request", fake_normalize)

    service = chat_llm_service.ChatLLMService()
    events = []
    async for event in service.generate_response_stream_with_tools(
        conversation_id="c",
        message_id="m",
        conversation_messages=[{"role": "user", "content": "봐줘"}],
        model_name="claude-sonnet-5",
    ):
        events.append(event)

    content = captured["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"


@pytest.mark.asyncio
async def test_stream_path_reports_a_refusal_as_an_error_event(monkeypatch) -> None:
    from neos.services.attachment_blocks import AttachmentNotSupportedError

    async def fake_resolve(messages, *, model):
        raise AttachmentNotSupportedError(
            model="blind-model",
            items=[{"name": "scan.png", "mime": "image/png", "reason": "vision_unsupported"}],
        )

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)

    service = chat_llm_service.ChatLLMService()
    events = [
        event
        async for event in service.generate_response_stream(
            conversation_id="c",
            message_id="m",
            conversation_messages=[{"role": "user", "content": "봐줘"}],
            model_name="blind-model",
        )
    ]

    error_events = [e for e in events if e.get("type") == "error"]
    assert error_events, f"오류 이벤트가 없다: {events}"
    assert error_events[0]["code"] == "attachment_unsupported"
    assert "scan.png" in error_events[0]["error"]


@pytest.mark.asyncio
async def test_tool_search_path_carries_the_attachment_block(monkeypatch) -> None:
    """세 번째 사본. 앞의 둘이 초록이어도 여기가 비면 tool search 대화에서 사라진다."""
    captured = {}

    async def fake_resolve(messages, *, model):
        return _plan_with_image(0)

    def fake_normalize(model, kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop-after-assembly")

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)
    monkeypatch.setattr(chat_llm_service, "normalize_anthropic_request", fake_normalize)

    service = chat_llm_service.ChatLLMService()
    async for _event in service.generate_response_stream_with_tool_search(
        conversation_id="c",
        message_id="m",
        conversation_messages=[{"role": "user", "content": "봐줘"}],
        model_name="claude-sonnet-5",
    ):
        pass

    content = captured["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
```

⚠️ 이 세 번째 테스트가 앞의 둘과 **따로** 있어야 하는 이유: 이 항목이 고치려는 실패가 정확히 "고침이 한 호출부에만 도착하는 것"이다. 한 테스트로 세 경로를 돌리면 어느 경로가 빠졌는지 말하지 못한다.

`fake_normalize`의 시그니처는 실제 호출부(`normalize_anthropic_request(model, {...})`)와 같아야 한다. 실제 서명은 이렇게 확인한다:

```bash
grep -n "def normalize_anthropic_request" -A 6 neos/utils/*.py neos/providers/*.py
```

- [ ] **Step 8: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_chat_llm_attachment_paths.py -v
```

기대: `test_stream_path_reports_a_refusal_as_an_error_event`가 실패한다 — 아직 `code` 키가 없다.

- [ ] **Step 9: 거부를 이벤트로 옮긴다**

세 스트림 생성기(`generate_response_stream`, `…_with_tools`, `…_with_tool_search`) 각각의 최상위 `except` 앞에 전용 절을 넣는다:

```python
        except AttachmentNotSupportedError as e:
            logger.info(f"[ChatLLM] 첨부 거부: {e.human_message()}")
            yield {
                "type": "error",
                "error": e.human_message(),
                "code": e.code,
            }
            return
```

- [ ] **Step 10: 비스트림 422 를 배선한다**

`neos/api/handlers/chat_handlers.py`의 `generate_response` 호출부(`:465`, `:654`)를 감싼다:

```python
        try:
            llm_response = await chat_llm_service.generate_response(...)
        except AttachmentNotSupportedError as e:
            raise HTTPException(status_code=422, detail=e.human_message()) from e
```

import를 파일 상단에 더한다:

```python
from neos.services.attachment_blocks import AttachmentNotSupportedError
```

- [ ] **Step 11: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/services/test_chat_llm_attachment_paths.py -v
.venv/bin/python -m pytest tests/services tests/api/services -v
```

기대: 신규 테스트 PASS, 기존 회귀 없음.

- [ ] **Step 12: 커밋**

```bash
git add neos/services/chat_llm_service.py neos/api/handlers/chat_handlers.py tests/services/test_chat_llm_attachment_paths.py
git commit -m "feat(chat): carry attachments into all three message assemblers, refuse loudly"
```

---

## Task 6: FE가 `documentId`를 보존한다

**Files:**
- Modify: `web/lib/message-parts.ts:81-116` (`extractAttachments`)
- Test: `web/tests/source/message-parts.test.ts`

**Interfaces:**
- Consumes: 없음 (BE는 `documentId` 없는 첨부도 계속 받는다 — Task 4의 역조회 폴백)
- Produces: `BackendAttachment.metadata.documentId?: string | number`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`web/tests/source/message-parts.test.ts`의 `describe` 안에 붙인다:

```typescript
  test("file 파트의 documentId가 metadata로 보존된다", () => {
    const attachments = extractAttachments([
      {
        type: "file",
        url: "s3://bucket/key",
        filename: "scan.png",
        mediaType: "image/png",
        documentId: 42,
      },
    ]);

    assert.equal(attachments.length, 1);
    assert.deepEqual(attachments[0].metadata, {
      mediaType: "image/png",
      documentId: 42,
    });
  });

  test("documentId가 없는 옛 형식도 그대로 통과한다", () => {
    const attachments = extractAttachments([
      { type: "file", url: "s3://bucket/key", filename: "old.png", mediaType: "image/png" },
    ]);

    assert.deepEqual(attachments[0].metadata, { mediaType: "image/png" });
  });
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd web && pnpm test:source
```

기대: `documentId` 테스트가 FAIL (metadata에 `mediaType`만 있다).

- [ ] **Step 3: 구현한다**

`web/lib/message-parts.ts`의 `AnyMessagePart` 중 file 갈래에 `documentId`를 더하고:

```typescript
  | {
      type: "file";
      url: string;
      filename: string;
      mediaType: string;
      documentId?: string | number;
    }
```

`extractAttachments`의 두 갈래에서 metadata를 조립한다:

```typescript
    if (part.type === "file") {
      const filePart = part as {
        url?: string;
        filename?: string;
        mediaType?: string;
        documentId?: string | number;
      };
      const metadata: Record<string, unknown> = {};
      if (filePart.mediaType) {
        metadata.mediaType = filePart.mediaType;
      }
      if (filePart.documentId !== undefined) {
        metadata.documentId = filePart.documentId;
      }
      attachments.push({
        type: "file",
        url: filePart.url ?? null,
        name: filePart.filename ?? null,
        metadata,
      });
      continue;
    }
```

`input_file` 갈래도 같은 모양으로 고친다 — `file.document_id`가 있으면 `metadata.documentId`에 넣는다:

```typescript
    if (part.type === "input_file") {
      const file = (
        part as {
          file?: {
            url?: string;
            name?: string;
            media_type?: string;
            document_id?: string | number;
          };
        }
      ).file;
      if (!file) {
        continue;
      }
      const metadata: Record<string, unknown> = {};
      if (file.media_type) {
        metadata.mediaType = file.media_type;
      }
      if (file.document_id !== undefined) {
        metadata.documentId = file.document_id;
      }
      attachments.push({
        type: "file",
        url: file.url ?? null,
        name: file.name ?? null,
        metadata,
      });
    }
```

- [ ] **Step 4: 업로드 응답의 `documentId`가 파트까지 오는지 확인한다**

업로드 라우트는 이미 `documentId`를 돌려준다(`web/app/(chat)/api/files/upload/route.ts` 응답의 `documentId` 필드). 그 값이 file 파트까지 오는지 확인한다:

```bash
grep -n "documentId\|contentType\|mediaType\|type: \"file\"" web/components/multimodal-input.tsx
```

파트를 만드는 자리에 `documentId`가 없으면 업로드 응답의 값을 그대로 실어준다:

```typescript
{
  type: "file",
  url: uploaded.url,
  filename: uploaded.name,
  mediaType: uploaded.contentType,
  documentId: uploaded.documentId,
}
```

변수명(`uploaded`)은 그 파일의 실제 이름을 따른다 — 위 grep 결과가 알려준다.

- [ ] **Step 5: 통과를 확인한다**

```bash
cd web && pnpm test:source && pnpm tsc --noEmit
```

기대: PASS, 타입 오류 없음.

- [ ] **Step 6: 커밋**

```bash
git add web/lib/message-parts.ts web/tests/source/message-parts.test.ts web/components/multimodal-input.tsx
git commit -m "feat(web): preserve documentId on attachments sent to the backend"
```

---

## 최종 검증

- [ ] **백엔드 전체**

```bash
.venv/bin/python -m pytest -q
```

기대: 신규 실패 0.

- [ ] **프론트 전체**

```bash
cd web && pnpm test:source && pnpm tsc --noEmit && pnpm build
```

- [ ] **원장 갱신**

`docs/ROADMAP.md` §N8을 종결로 옮기고, 실제로 닫힌 것과 남은 것을 적는다 — 고아 `/api/v1/multimodal/*`((b))과 죽은 `supports_video`((c))는 **닫히지 않았다.**
