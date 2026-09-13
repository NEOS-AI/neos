import json

import pytest

from neos.coding.tools.executor import SandboxToolExecutor, _web_fetch_ip_blocked
from tests.coding.tools.test_executor import (
    FakeSession,
    _allow_web_fetch_host,
    _resolve_web_fetch_ips,
    call,
)

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("nat64", "embedded"),
    [
        ("64:ff9b::c0a8:1", "192.168.0.1"),
        ("64:ff9b::7f00:1", "127.0.0.1"),
        ("64:ff9b::a9fe:a9fe", "169.254.169.254"),
        ("64:ff9b::10.0.0.1", "10.0.0.1"),
        ("64:ff9b::ac10:1", "172.16.0.1"),
    ],
)
def test_nat64_unwraps_to_embedded_private_ipv4(nat64: str, embedded: str) -> None:
    assert _web_fetch_ip_blocked(nat64) is True
    assert _web_fetch_ip_blocked(embedded) is True


def test_nat64_public_ipv4_is_not_blocked() -> None:
    assert _web_fetch_ip_blocked("64:ff9b::808:808") is False
    assert _web_fetch_ip_blocked("64:ff9b::1.2.3.4") is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ip",
    [
        "64:ff9b::c0a8:1",
        "64:ff9b::7f00:1",
        "64:ff9b::a9fe:a9fe",
        "64:ff9b::10.0.0.1",
    ],
)
async def test_web_fetch_blocks_nat64_embedded_private_ip(
    monkeypatch, ip: str
) -> None:
    _allow_web_fetch_host(monkeypatch)
    _resolve_web_fetch_ips(monkeypatch, ip)
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://docs.example.com/doc"}),
    )
    payload = json.dumps(result.to_mapping())
    assert result.status == "error"
    assert result.reason_code == "web_fetch_ssrf"
    assert ip not in payload
