"""Workspace image and PDF readers for dedicated coding tools."""

from __future__ import annotations

import io
from typing import Literal

ImageKind = Literal["image/jpeg", "image/png", "image/gif", "image/webp"]

_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp"})
_PDF_EXTENSIONS = frozenset({"pdf"})


class MediaError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def path_extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].casefold()


def is_image_path(path: str) -> bool:
    return path_extension(path) in _IMAGE_EXTENSIONS


def is_pdf_path(path: str) -> bool:
    return path_extension(path) in _PDF_EXTENSIONS


def sniff_image_type(data: bytes) -> ImageKind:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise MediaError("policy_image_unsupported")


def parse_page_spec(spec: str | None, *, page_count: int, max_pages: int) -> range:
    if page_count < 1:
        raise MediaError("policy_pdf_invalid")
    if spec is None or not str(spec).strip():
        end = min(page_count, max_pages)
        if page_count > max_pages:
            raise MediaError("policy_pdf_too_large")
        return range(1, end + 1)
    text = str(spec).strip()
    if "-" in text:
        start_text, end_text = text.split("-", 1)
        start = int(start_text)
        end = int(end_text)
    else:
        start = end = int(text)
    if start < 1 or end < start:
        raise MediaError("policy_pdf_invalid")
    if end > page_count:
        end = page_count
    if end - start + 1 > max_pages:
        raise MediaError("policy_pdf_too_large")
    return range(start, end + 1)


def extract_pdf_text(
    data: bytes, *, pages: str | None, max_pages: int
) -> tuple[tuple[dict[str, object], ...], int]:
    try:
        from PyPDF2 import PdfReader
    except ImportError as error:
        raise MediaError("policy_pdf_invalid") from error
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as error:
        raise MediaError("policy_pdf_invalid") from error
    if getattr(reader, "is_encrypted", False):
        raise MediaError("policy_pdf_encrypted")
    count = len(reader.pages)
    selected = parse_page_spec(pages, page_count=count, max_pages=max_pages)
    extracted: list[dict[str, object]] = []
    for number in selected:
        try:
            text = reader.pages[number - 1].extract_text() or ""
        except Exception as error:
            raise MediaError("policy_pdf_invalid") from error
        extracted.append({"page": number, "text": text})
    return tuple(extracted), count
