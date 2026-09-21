"""Binary tool payloads never enter the replayed transcript (roadmap K6).

`read_image.v1` answers with a base64 blob. Nothing in the coding path ever
turns it into an image block, so the model cannot decode it; it is only
replayed, every turn, for as long as the conversation lives.

The parent clipped it to 400 characters via `redact_sensitive`, which left a
fragment that still reads as data and sits beside a now-false `truncated:
False`. The child port applied no redaction at all and would have carried the
whole blob. One helper, both call sites: a fix that reaches only one of them is
the failure this repository keeps relearning.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from neos.coding.redact import strip_binary_payloads
from neos.coding.subagent_port import CodingToolPort
from neos.coding.tools.executor import ToolResult
from neos.coding.tools.registry import ToolRisk

pytestmark = pytest.mark.no_db

BLOB = "QUJDRA" * 2000


def _image_result() -> ToolResult:
    return ToolResult(
        status="ok",
        reason_code="ok",
        preview="image/png 9000 bytes",
        original_bytes=9000,
        truncated=False,
        checksum="abc",
        workspace_revision="3",
        entries=(
            {
                "path": "a.png",
                "kind": "image",
                "media_type": "image/png",
                "data_b64": BLOB,
            },
        ),
    )


def test_the_blob_is_dropped_and_its_absence_is_stated() -> None:
    stripped = strip_binary_payloads(dict(_image_result().to_mapping()))
    entry = stripped["entries"][0]

    assert "data_b64" not in entry
    assert entry["data_b64_omitted"] is True


def test_what_survives_still_identifies_the_file() -> None:
    entry = strip_binary_payloads(dict(_image_result().to_mapping()))["entries"][0]

    assert entry["path"] == "a.png"
    assert entry["media_type"] == "image/png"
    assert entry["kind"] == "image"


def test_results_without_a_blob_are_returned_unchanged() -> None:
    plain = {"status": "ok", "entries": ({"path": "a.txt", "text": "hello"},)}

    assert strip_binary_payloads(dict(plain)) == plain


def test_a_clipped_fragment_is_dropped_too() -> None:
    """The parent's 400-char clip left a fragment that still read as data."""
    clipped = {"entries": ({"path": "a.png", "data_b64": "QUJD" * 100 + "…"},)}

    entry = strip_binary_payloads(dict(clipped))["entries"][0]

    assert "data_b64" not in entry


class _Registry:
    def validate(self, name, input):
        return SimpleNamespace(name=name, input=input, risk=ToolRisk.READ_ONLY)


class _Executor:
    async def execute(self, session, validated):
        return _image_result()


@pytest.mark.asyncio
async def test_the_child_port_strips_the_blob_as_well(monkeypatch) -> None:
    """No spec lists a media tool today, so this guards the next one that does."""
    monkeypatch.setattr(
        "neos.coding.subagent_port.lookup_spec",
        lambda _name: SimpleNamespace(
            allowed_tools=frozenset({"read_image.v1"}),
            sandbox_mode=None,
        ),
    )
    port = CodingToolPort(registry=_Registry(), executor=_Executor())
    port.bind(session=object())

    result = await port.execute("read_image.v1", {"path": "a.png"})

    assert BLOB not in json.dumps(result, default=str)
    assert result["entries"][0]["data_b64_omitted"] is True
