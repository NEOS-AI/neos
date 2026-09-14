from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.media import extract_pdf_text, sniff_image_type
from neos.coding.tools.notebook import apply_notebook_edit
from neos.coding.tools.registry import CodingToolRegistry, ToolValidationError
from neos.coding.tools.web_search import wrap_search_text
from tests.coding.tools.test_executor import FakeSession, call

pytestmark = pytest.mark.no_db

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc``\x00\x00"
    b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)
NOW = datetime(2026, 7, 19, tzinfo=UTC)


def _registry() -> CodingToolRegistry:
    return CodingToolRegistry.default(
        command_allowlist=frozenset({"pytest"}),
        max_command_timeout_sec=30,
        max_command_output_bytes=4096,
        max_command_stdin_bytes=8,
    )


def _enable(monkeypatch, **flags: bool) -> None:
    names = {
        "notebook_edit.v1": flags.get("notebook_edit", False),
        "read_image.v1": flags.get("image_tool", False),
        "read_pdf.v1": flags.get("pdf_tool", False),
        "web_search.v1": flags.get("web_search", False),
    }

    def _enabled(name: str) -> bool:
        return bool(names.get(name))

    monkeypatch.setattr(
        "neos.coding.tools.registry.optional_tool_enabled", _enabled
    )
    monkeypatch.setattr(
        "neos.coding.tools.executor.optional_tool_enabled", _enabled
    )


def _notebook() -> bytes:
    return json.dumps(
        {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"kernelspec": {"language": "python", "name": "python3"}},
            "cells": [
                {
                    "id": "intro",
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": ["# hi\n"],
                }
            ],
        }
    ).encode("utf-8")


def test_optional_tools_are_hidden_when_flags_are_off() -> None:
    names = [item.name for item in _registry().definitions()]

    assert "notebook_edit.v1" not in names
    assert "read_image.v1" not in names
    assert "read_pdf.v1" not in names
    assert "web_search.v1" not in names


def test_optional_tools_are_hidden_even_when_revealed(monkeypatch) -> None:
    revealed = _registry().definitions(
        revealed=frozenset(
            {
                "notebook_edit.v1",
                "read_image.v1",
                "read_pdf.v1",
                "web_search.v1",
            }
        )
    )
    names = [item.name for item in revealed]
    assert "web_search.v1" not in names


def test_enabled_optional_tools_are_advertised(monkeypatch) -> None:
    _enable(
        monkeypatch,
        notebook_edit=True,
        image_tool=True,
        pdf_tool=True,
        web_search=True,
    )
    names = [item.name for item in _registry().definitions()]
    assert "notebook_edit.v1" in names
    assert "read_image.v1" in names
    assert "read_pdf.v1" in names
    assert "web_search.v1" in names
    explore = [item.name for item in _registry().definitions(phase="explore")]
    assert "notebook_edit.v1" not in explore
    assert "read_image.v1" in explore


def test_disabled_optional_tool_fails_closed() -> None:
    with pytest.raises(ToolValidationError, match="policy_media_tool_disabled"):
        _registry().validate("web_search.v1", {"query": "neos coding"})


@pytest.mark.asyncio
async def test_read_image_returns_base64(monkeypatch) -> None:
    _enable(monkeypatch, image_tool=True)
    session = FakeSession()
    session.files["icon.png"] = PNG_1X1
    result = await SandboxToolExecutor(64, 10).execute(
        session, call("read_image.v1", {"path": "icon.png"})
    )
    assert result.status == "ok"
    assert result.entries[0]["media_type"] == "image/png"
    assert result.entries[0]["data_b64"]
    assert sniff_image_type(PNG_1X1) == "image/png"


@pytest.mark.asyncio
async def test_read_image_rejects_wrong_bytes(monkeypatch) -> None:
    _enable(monkeypatch, image_tool=True)
    session = FakeSession()
    session.files["icon.png"] = b"not-an-image"
    result = await SandboxToolExecutor(64, 10).execute(
        session, call("read_image.v1", {"path": "icon.png"})
    )
    assert result.status == "denied"
    assert result.reason_code == "policy_image_unsupported"


@pytest.mark.asyncio
async def test_read_pdf_extracts_selected_pages(monkeypatch) -> None:
    _enable(monkeypatch, pdf_tool=True)
    from PyPDF2 import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    session = FakeSession()
    session.files["doc.pdf"] = buffer.getvalue()
    result = await SandboxToolExecutor(64, 10).execute(
        session, call("read_pdf.v1", {"path": "doc.pdf", "pages": "1"})
    )
    assert result.status == "ok"
    assert result.entries[0]["page_count"] == 2
    assert result.entries[0]["pages"][0]["page"] == 1
    pages, count = extract_pdf_text(buffer.getvalue(), pages="1-2", max_pages=20)
    assert count == 2
    assert len(pages) == 2


@pytest.mark.asyncio
async def test_notebook_edit_replaces_and_inserts(monkeypatch) -> None:
    _enable(monkeypatch, notebook_edit=True)
    session = FakeSession()
    session.files["n.ipynb"] = _notebook()
    session.modified["n.ipynb"] = NOW
    executor = SandboxToolExecutor(64, 10)
    replaced = await executor.execute(
        session,
        call(
            "notebook_edit.v1",
            {
                "path": "n.ipynb",
                "cell_id": "intro",
                "new_source": "# titled\n",
                "edit_mode": "replace",
            },
        ),
    )
    inserted = await executor.execute(
        session,
        call(
            "notebook_edit.v1",
            {
                "path": "n.ipynb",
                "cell_id": "intro",
                "new_source": "print(1)",
                "cell_type": "code",
                "edit_mode": "insert",
            },
        ),
    )
    assert replaced.status == "ok"
    assert inserted.status == "ok"
    notebook = json.loads(session.files["n.ipynb"])
    assert notebook["cells"][0]["source"] == ["# titled\n"]
    assert notebook["cells"][1]["cell_type"] == "code"


@pytest.mark.asyncio
async def test_notebook_insert_creates_missing_file(monkeypatch) -> None:
    _enable(monkeypatch, notebook_edit=True)
    session = FakeSession()
    result = await SandboxToolExecutor(64, 10).execute(
        session,
        call(
            "notebook_edit.v1",
            {
                "path": "new.ipynb",
                "new_source": "print(2)",
                "cell_type": "code",
                "edit_mode": "insert",
            },
        ),
    )
    assert result.status == "ok"
    assert "new.ipynb" in session.files
    created = json.loads(session.files["new.ipynb"])
    assert created["cells"][0]["cell_type"] == "code"


@pytest.mark.asyncio
async def test_edit_file_on_notebook_is_denied(monkeypatch) -> None:
    _enable(monkeypatch, notebook_edit=True)
    session = FakeSession()
    session.files["n.ipynb"] = _notebook()
    result = await SandboxToolExecutor(64, 10).execute(
        session,
        call(
            "edit_file.v1",
            {"path": "n.ipynb", "old_string": "# hi", "new_string": "# no"},
        ),
    )
    assert result.status == "denied"
    assert result.reason_code == "policy_notebook_required"


@pytest.mark.asyncio
async def test_web_search_wraps_untrusted_snippets(monkeypatch) -> None:
    _enable(monkeypatch, web_search=True)
    monkeypatch.setattr(
        "neos.coding.tools.executor.tavily_search",
        lambda query, **kwargs: (
            {
                "title": "Hit",
                "url": "https://example.com",
                "snippet": wrap_search_text("hello"),
            },
        ),
    )
    monkeypatch.setattr(
        "neos.coding.tools.executor._coding_model",
        lambda: type("C", (), {"web_search_max_results": 5})(),
    )
    from neos.config import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "TAVILY_API_KEY", "tvly-test")
    result = await SandboxToolExecutor(64, 10).execute(
        FakeSession(), call("web_search.v1", {"query": "neos coding loop"})
    )
    assert result.status == "ok"
    snippet = str(result.entries[0]["snippet"])
    assert "begin untrusted web search" in snippet
    assert apply_notebook_edit(_notebook(), edit_mode="delete", new_source="", cell_id="intro", cell_type=None)[1]["edit_mode"] == "delete"


def _media_config(*, image_max_bytes: int = 4096, pdf_max_bytes: int = 4096):
    return type(
        "C",
        (),
        {
            "image_max_bytes": image_max_bytes,
            "pdf_max_bytes": pdf_max_bytes,
            "pdf_max_pages": 20,
        },
    )()


@pytest.mark.asyncio
async def test_read_image_ignores_text_output_byte_cap(
    monkeypatch, tmp_path: Path
) -> None:
    _enable(monkeypatch, image_tool=True)
    monkeypatch.setattr(
        "neos.coding.tools.executor._coding_model",
        lambda: _media_config(image_max_bytes=4096),
    )
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=replace(SandboxLimits.safe_defaults(), max_output_bytes=32),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    payload = b"\xff\xd8\xff" + b"x" * 200
    await session.write_file("shot.jpg", payload)

    result = await SandboxToolExecutor(64, 10).execute(
        session, call("read_image.v1", {"path": "shot.jpg"})
    )

    assert result.status == "ok"
    assert result.original_bytes == len(payload)
    assert result.entries[0]["media_type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_read_image_maps_media_cap_to_too_large(
    monkeypatch, tmp_path: Path
) -> None:
    _enable(monkeypatch, image_tool=True)
    monkeypatch.setattr(
        "neos.coding.tools.executor._coding_model",
        lambda: _media_config(image_max_bytes=64),
    )
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=replace(SandboxLimits.safe_defaults(), max_output_bytes=32),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("shot.jpg", b"\xff\xd8\xff" + b"x" * 200)

    result = await SandboxToolExecutor(64, 10).execute(
        session, call("read_image.v1", {"path": "shot.jpg"})
    )

    assert result.status == "denied"
    assert result.reason_code == "policy_image_too_large"


@pytest.mark.asyncio
async def test_read_pdf_ignores_text_output_byte_cap(
    monkeypatch, tmp_path: Path
) -> None:
    _enable(monkeypatch, pdf_tool=True)
    monkeypatch.setattr(
        "neos.coding.tools.executor._coding_model",
        lambda: _media_config(pdf_max_bytes=64_000),
    )
    from PyPDF2 import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    payload = buffer.getvalue()
    assert len(payload) > 32

    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=replace(SandboxLimits.safe_defaults(), max_output_bytes=32),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("doc.pdf", payload)

    result = await SandboxToolExecutor(64, 10).execute(
        session, call("read_pdf.v1", {"path": "doc.pdf", "pages": "1"})
    )

    assert result.status == "ok"
    assert result.entries[0]["page_count"] == 1
