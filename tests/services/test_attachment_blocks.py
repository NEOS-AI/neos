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
