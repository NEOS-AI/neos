import pytest

from neos.api.channels.inflight import SessionInboundPark, SessionInflightLock

pytestmark = pytest.mark.no_db


def test_second_acquire_on_same_session_is_rejected() -> None:
    lock = SessionInflightLock()
    assert lock.acquire("v2:slack:T:C:-") is True
    assert lock.acquire("v2:slack:T:C:-") is False
    lock.release("v2:slack:T:C:-")
    assert lock.acquire("v2:slack:T:C:-") is True


def test_park_latest_wins_and_is_single_slot() -> None:
    park = SessionInboundPark[str]()
    park.put("sess", "first")
    park.put("sess", "second")
    assert park.peek("sess") == "second"
    assert park.take("sess") == "second"
    assert park.take("sess") is None
    park.put("sess", "again")
    park.clear("sess")
    assert park.peek("sess") is None
