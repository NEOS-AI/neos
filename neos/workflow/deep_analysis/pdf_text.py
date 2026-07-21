"""Minimal PDF text extraction for deep-analysis evidence fetching."""

from __future__ import annotations

from .text_norm import normalize_evidence_text


class PDFExtractionError(Exception):
    """Raised when a PDF cannot be converted into evidence text."""


def pdf_bytes_to_text(content: bytes) -> str:
    """Extract normalized page text from PDF bytes."""
    try:
        import fitz

        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise PDFExtractionError("Unable to extract PDF text") from exc

    try:
        return normalize_evidence_text(
            "\n".join(page.get_text() for page in document)
        )
    except Exception as exc:
        raise PDFExtractionError("Unable to extract PDF text") from exc
    finally:
        document.close()
