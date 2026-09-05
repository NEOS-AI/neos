"""첨부 → 모델 입력 블록.

N8. 정책(분류·게이트·상한·해석)은 전부 이 모듈에 있고, `chat_llm_service`의
세 메시지 조립 사본은 렌더 결과만 병합한다. 설계는
`docs/superpowers/specs/2026-09-05-n8-attachment-multimodal-design.md`.
"""

from __future__ import annotations

from enum import Enum

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
