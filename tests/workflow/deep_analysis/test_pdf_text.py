import sys
from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis.pdf_text import (
    PDFExtractionError,
    pdf_bytes_to_text,
)


pytestmark = pytest.mark.no_db


class FakePage:
    def __init__(self, text: str | Exception) -> None:
        self.text = text

    def get_text(self) -> str:
        if isinstance(self.text, Exception):
            raise self.text
        return self.text


class FakeDocument:
    def __init__(self, pages: list[str | Exception]) -> None:
        self.pages = [FakePage(page) for page in pages]
        self.closed = False

    def __iter__(self):
        return iter(self.pages)

    def close(self) -> None:
        self.closed = True


def test_pdf_bytes_to_text_normalizes_pages_and_closes(monkeypatch) -> None:
    document = FakeDocument(["  First\npage  ", "cafe\u0301\tsecond"])

    def open_pdf(**kwargs):
        return document

    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=open_pdf))

    text = pdf_bytes_to_text(b"%PDF-fake")

    assert text == "First page café second"
    assert document.closed is True


def test_pdf_bytes_to_text_returns_empty_for_empty_document(monkeypatch) -> None:
    document = FakeDocument([])
    monkeypatch.setitem(
        sys.modules,
        "fitz",
        SimpleNamespace(open=lambda **kwargs: document),
    )

    assert pdf_bytes_to_text(b"%PDF-empty") == ""
    assert document.closed is True


def test_pdf_bytes_to_text_wraps_open_failure_without_payload(
    monkeypatch,
) -> None:
    def fail_open(**kwargs):
        raise ValueError("secret parser payload")

    monkeypatch.setitem(
        sys.modules,
        "fitz",
        SimpleNamespace(open=fail_open),
    )

    with pytest.raises(PDFExtractionError) as exc:
        pdf_bytes_to_text(b"%PDF-broken")

    assert str(exc.value) == "Unable to extract PDF text"
    assert "secret parser payload" not in str(exc.value)


def test_pdf_bytes_to_text_closes_after_page_failure(monkeypatch) -> None:
    document = FakeDocument([ValueError("secret page payload")])
    monkeypatch.setitem(
        sys.modules,
        "fitz",
        SimpleNamespace(open=lambda **kwargs: document),
    )

    with pytest.raises(
        PDFExtractionError,
        match="Unable to extract PDF text",
    ):
        pdf_bytes_to_text(b"%PDF-broken-page")

    assert document.closed is True


def test_pdf_bytes_to_text_wraps_missing_dependency(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "fitz", None)

    with pytest.raises(
        PDFExtractionError,
        match="Unable to extract PDF text",
    ):
        pdf_bytes_to_text(b"%PDF-no-parser")
