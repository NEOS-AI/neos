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

    # 게이트는 스토리지를 열기 전에 선다 — 거부될 턴에서 스토리지 오류가
    # 거부 메시지를 가리면 안 된다 (컨트롤러 판정)
    calls = []

    async def tracking_download(storage_key):
        calls.append(storage_key)
        return b"bytes"

    monkeypatch.setattr(attachment_blocks, "_download", tracking_download)

    with pytest.raises(AttachmentNotSupportedError):
        await resolve_attachments(
            [_message("봐줘", [_attachment("scan.png", "image/png")])],
            model="blind-model",
        )

    assert calls == [], "거부될 턴인데 스토리지를 열었다"


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
