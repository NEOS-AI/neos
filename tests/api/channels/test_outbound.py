from __future__ import annotations

from pathlib import Path

import pytest

from neos.api.channels.outbound import validate_outbound_path
from tests.api.channels.conftest import install_channel_settings
from tests.api.channels.test_slack_adapter import _make_adapter

pytestmark = pytest.mark.no_db


def test_validate_outbound_denies_empty_allow_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("x")
    assert validate_outbound_path(str(target), []) is None
    assert validate_outbound_path(str(target), None) is None


def test_validate_outbound_allows_path_inside_allow_dir(tmp_path: Path) -> None:
    allow = tmp_path / "out"
    allow.mkdir()
    target = allow / "ok.txt"
    target.write_text("yes")
    assert validate_outbound_path(str(target), [str(allow)]) == target.resolve()


def test_validate_outbound_denies_dotdot_escape(tmp_path: Path) -> None:
    allow = tmp_path / "out"
    allow.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("no")
    escaped = allow / ".." / "secret.txt"
    assert validate_outbound_path(str(escaped), [str(allow)]) is None
    assert validate_outbound_path(str(allow / ".." / ".." / "etc" / "passwd"), [str(allow)]) is None


def test_validate_outbound_denies_sibling_prefix_trick(tmp_path: Path) -> None:
    allow = tmp_path / "out"
    allow.mkdir()
    sibling = tmp_path / "out_evil"
    sibling.mkdir()
    target = sibling / "secret.txt"
    target.write_text("no")
    assert validate_outbound_path(str(target), [str(allow)]) is None


async def test_send_file_is_noop_when_flag_off_or_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow = tmp_path / "out"
    allow.mkdir()
    ok = allow / "ok.txt"
    ok.write_text("yes")
    adapter, _gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    sent: list[str] = []

    async def _upload(*_args: object, **_kwargs: object) -> None:
        sent.append("uploaded")

    adapter._app = type("App", (), {"client": type("C", (), {"files_upload": _upload})()})()
    await adapter.send_file("C_general", str(ok), allow_dirs=[str(allow)])
    assert sent == []

    install_channel_settings(
        monkeypatch, allowed_users=["U_alice"], outbound_files=True
    )
    escaped = allow / ".." / "secret.txt"
    escaped.write_text("no")
    await adapter.send_file("C_general", str(escaped), allow_dirs=[str(allow)])
    assert sent == []
