import pytest

from neos.api.channels.inflight import SessionInflightLock

pytestmark = pytest.mark.no_db


def test_second_acquire_on_same_session_is_rejected() -> None:
    lock = SessionInflightLock()
    assert lock.acquire("v2:slack:T:C:-") is True
    assert lock.acquire("v2:slack:T:C:-") is False
    lock.release("v2:slack:T:C:-")
    assert lock.acquire("v2:slack:T:C:-") is True
