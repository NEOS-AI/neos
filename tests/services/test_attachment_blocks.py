import base64

import pytest

from neos.services.attachment_blocks import (
    AttachmentKind,
    AttachmentNotSupportedError,
    ResolvedAttachment,
    classify,
    merge_into_content,
    render_anthropic,
    render_langchain,
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


#: 카탈로그가 아는, vision 을 갖지 않는 실제 모델. 스텁 대신 실물을 쓰면
#: 게이트가 카탈로그와 어긋나는 순간 테스트가 알려준다.
KNOWN_BLIND_MODEL = "gpt-3.5-turbo"

#: 카탈로그가 아는, vision 을 갖는 실제 모델.
KNOWN_SEEING_MODEL = "claude-sonnet-5"

#: 카탈로그에 없는 모델. Ollama 처럼 list_models() 가 라이브 서버를 조회하는
#: 프로바이더에서는 이런 이름이 실제로 선택될 수 있다.
UNKNOWN_MODEL = "llava:13b-not-in-catalog"


def test_gate_blocks_image_for_a_model_the_catalog_says_has_no_vision() -> None:
    from neos.services import attachment_blocks

    with pytest.raises(AttachmentNotSupportedError) as excinfo:
        attachment_blocks.assert_model_accepts(
            model=KNOWN_BLIND_MODEL,
            kinds=[(AttachmentKind.IMAGE, "scan.png", "image/png")],
        )

    assert excinfo.value.items[0]["reason"] == "vision_unsupported"


def test_gate_lets_extracted_text_through_without_vision() -> None:
    from neos.services import attachment_blocks

    # EXTRACT 는 결과가 텍스트라 vision 없는 모델도 받는다
    attachment_blocks.assert_model_accepts(
        model=KNOWN_BLIND_MODEL,
        kinds=[(AttachmentKind.EXTRACT, "memo.docx", "application/msword")],
    )


def test_gate_passes_a_model_the_catalog_knows_has_vision() -> None:
    from neos.services import attachment_blocks

    attachment_blocks.assert_model_accepts(
        model=KNOWN_SEEING_MODEL,
        kinds=[(AttachmentKind.IMAGE, "scan.png", "image/png")],
    )


def test_gate_does_not_refuse_a_model_the_catalog_does_not_know() -> None:
    """모르는 것과 못 하는 것은 다르다.

    Ollama 의 list_models() 는 라이브 서버를 조회하므로 로컬에 설치한 vision
    모델이 선택될 수 있는데, 그 이름은 models.yaml 에 없다. 예전 게이트는
    "카탈로그에 없음 = vision 없음" 으로 보고 볼 수 있는 모델을 거부했다.
    """
    from neos.services import attachment_blocks

    attachment_blocks.assert_model_accepts(
        model=UNKNOWN_MODEL,
        kinds=[(AttachmentKind.IMAGE, "scan.png", "image/png")],
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


def test_render_langchain_emits_filename_for_pdf_so_openai_does_not_autoname_it() -> None:
    # Finding 6 — langchain_openai substitutes "LC_AUTOGENERATED" (and warns)
    # when a file block has no "filename" key.
    pdf = ResolvedAttachment(
        name="report.pdf",
        mime_type="application/pdf",
        kind=AttachmentKind.FILE,
        data=b"%PDF-bytes",
        text=None,
    )

    block = render_langchain(pdf)

    assert block["filename"] == "report.pdf"


@pytest.mark.parametrize("mime", ["text/plain", "text/markdown"])
def test_render_langchain_renders_file_text_as_a_plain_text_block(mime) -> None:
    # Finding 2 — Anthropic's document base64 source only accepts
    # application/pdf, and OpenAI's input_file is PDF-only too; text/plain and
    # text/markdown must not be sent as a document/file block.
    att = ResolvedAttachment(
        name="notes.txt" if mime == "text/plain" else "notes.md",
        mime_type=mime,
        kind=AttachmentKind.FILE_TEXT,
        data="분기 실적 요약".encode("utf-8"),
        text=None,
    )

    block = render_langchain(att)

    assert block == {
        "type": "text",
        "text": f"[첨부 {att.name} 의 내용]\n분기 실적 요약",
    }


@pytest.mark.parametrize("mime", ["text/plain", "text/markdown"])
def test_render_anthropic_renders_file_text_as_a_plain_text_block(mime) -> None:
    att = ResolvedAttachment(
        name="notes.txt" if mime == "text/plain" else "notes.md",
        mime_type=mime,
        kind=AttachmentKind.FILE_TEXT,
        data="분기 실적 요약".encode("utf-8"),
        text=None,
    )

    block = render_anthropic(att)

    assert block == {
        "type": "text",
        "text": f"[첨부 {att.name} 의 내용]\n분기 실적 요약",
    }


def test_render_file_text_replaces_undecodable_bytes_instead_of_raising() -> None:
    att = ResolvedAttachment(
        name="notes.txt",
        mime_type="text/plain",
        kind=AttachmentKind.FILE_TEXT,
        data=b"\xff\xfe not valid utf-8",
        text=None,
    )

    block = render_langchain(att)

    assert block["type"] == "text"
    assert "notes.txt" in block["text"]


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
