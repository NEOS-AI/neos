"""첨부 → 모델 입력 블록.

N8. 정책(분류·게이트·상한·해석)은 전부 이 모듈에 있고, `chat_llm_service`의
세 메시지 조립 사본은 렌더 결과만 병합한다. 설계는
`docs/superpowers/specs/2026-09-05-n8-attachment-multimodal-design.md`.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from neos.config.model_config import supports_vision

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
