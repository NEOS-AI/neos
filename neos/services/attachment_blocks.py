"""첨부 → 모델 입력 블록.

N8. 정책(분류·게이트·상한·해석)은 전부 이 모듈에 있고, `chat_llm_service`의
세 메시지 조립 사본은 렌더 결과만 병합한다. 설계는
`docs/superpowers/specs/2026-09-05-n8-attachment-multimodal-design.md`.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from sqlalchemy import select

from neos.config.model_config import supports_vision
from neos.config.settings import settings
from neos.database.connection import get_session
from neos.database.models import Document
from neos.storage.storage_service import StorageService
from neos.workflow.pipelines.word_parser import parse_word

logger = logging.getLogger(__name__)

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


def _demoted(
    name: str, mime_type: str, kind: AttachmentKind, why: str
) -> ResolvedAttachment:
    return ResolvedAttachment(
        name=name,
        mime_type=mime_type,
        kind=kind,
        data=None,
        text=f"[첨부: {name} — {why}]",
    )


@dataclass(frozen=True)
class _Prepared:
    """1패스의 산출. 게이트를 통과한 뒤에만 2패스가 이것을 소비한다."""

    index: int
    name: str
    mime_type: str
    #: None 이면 해석 실패 — 과거 턴이므로 강등 대상이다
    kind: AttachmentKind | None
    document: object | None


async def resolve_attachments(
    conversation_messages: list[dict], *, model: str
) -> AttachmentPlan:
    """첨부를 해석해 요청 한 번 분의 계획을 만든다.

    1패스가 DB 만 보고 게이트를 세운 뒤에야 2패스가 스토리지를 연다 — 거부될
    턴에서 스토리지 오류가 거부 메시지를 가리지 않게 하기 위해서다.
    """
    indexed = [
        (index, message)
        for index, message in enumerate(conversation_messages)
        if message.get("role") == "user" and message.get("attachments")
    ]
    if not indexed:
        return AttachmentPlan(by_index={}, notices=[])

    current_index = indexed[-1][0]

    # ---- 1패스: 조회와 분류 (DB 만) ----
    prepared: list[_Prepared] = []
    unresolved_now: list[dict] = []
    kinds_for_gate: list[tuple[AttachmentKind, str, str]] = []

    # 최신 메시지부터 본다 — 2패스의 예산이 같은 순서로 채워진다
    for index, message in reversed(indexed):
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
                    prepared.append(
                        _Prepared(index, name, mime_type, None, None)
                    )
                continue

            kinds_for_gate.append((kind, name, mime_type))
            prepared.append(_Prepared(index, name, mime_type, kind, document))

    # ---- 게이트: 스토리지를 열기 전에 거부를 확정한다 ----
    if unresolved_now:
        raise AttachmentNotSupportedError(model=model, items=unresolved_now)

    assert_model_accepts(model=model, kinds=kinds_for_gate)

    # ---- 2패스: 다운로드 · 추출 · 상한 ----
    by_index: dict[int, list[ResolvedAttachment]] = {}
    notices: list[str] = []
    budget = MAX_ATTACHMENT_BYTES

    for item in prepared:
        resolved: ResolvedAttachment

        if item.kind is None:
            resolved = _demoted(
                item.name, item.mime_type, AttachmentKind.EXTRACT, "해석할 수 없어 제외됨"
            )
            notices.append(f"{item.name}: 해석할 수 없어 제외됨")
        else:
            page_count = getattr(item.document, "page_count", None)
            size = getattr(item.document, "file_size", None) or 0

            if (
                item.kind is AttachmentKind.FILE
                and page_count
                and page_count > MAX_PDF_PAGES
            ):
                resolved = _demoted(
                    item.name,
                    item.mime_type,
                    item.kind,
                    f"{MAX_PDF_PAGES}페이지 상한 초과",
                )
                notices.append(f"{item.name}: 페이지 상한 초과로 제외됨")
            elif item.kind is not AttachmentKind.EXTRACT and size > budget:
                resolved = _demoted(
                    item.name,
                    item.mime_type,
                    item.kind,
                    "길이 상한으로 이번 요청에 포함되지 않음",
                )
                notices.append(f"{item.name}: 길이 상한으로 제외됨")
            else:
                data = await _download(item.document.storage_key)

                if item.kind is AttachmentKind.EXTRACT:
                    parsed = await parse_word(file_content=data)
                    resolved = ResolvedAttachment(
                        name=item.name,
                        mime_type=item.mime_type,
                        kind=item.kind,
                        data=None,
                        text=parsed.get("text") or "",
                    )
                else:
                    budget -= len(data)
                    resolved = ResolvedAttachment(
                        name=item.name,
                        mime_type=item.mime_type,
                        kind=item.kind,
                        data=data,
                        text=None,
                    )

        by_index.setdefault(item.index, []).append(resolved)

    # 1패스가 최신 메시지부터 돌았으므로 메시지 안의 순서를 되돌린다
    for index in by_index:
        by_index[index].reverse()

    return AttachmentPlan(by_index=by_index, notices=notices)
