"""테스트는 이름이 `_test` 로 끝나는 DB 에만 닿는다 -- `tests/conftest.py` 가 강제한다.

로드맵 §10.3: 스위트가 개발 원장(`neos`)에 쓰고 있었다.
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from tests.conftest import _test_database_url

pytestmark = pytest.mark.no_db


def test_the_session_points_at_a_test_database() -> None:
    import os

    assert make_url(os.environ["DATABASE_URL"]).database.endswith("_test")


def test_the_loaded_config_sees_the_test_database() -> None:
    """env 만 바꾸고 설정이 `.env` 를 먼저 읽으면 가드는 없는 것과 같다."""
    from neos.config.loader import load_app_config

    assert make_url(load_app_config().database.url).database.endswith("_test")


def test_a_development_name_is_renamed() -> None:
    url = _test_database_url("postgresql+asyncpg://u:p@localhost:5432/neos")
    assert make_url(url).database == "neos_test"


def test_the_rest_of_the_url_survives() -> None:
    url = make_url(_test_database_url("postgresql+asyncpg://u:s3cret@db:6543/neos"))
    assert (url.drivername, url.username, url.password, url.host, url.port) == (
        "postgresql+asyncpg",
        "u",
        "s3cret",
        "db",
        6543,
    )


def test_a_test_name_is_left_alone() -> None:
    url = "postgresql+asyncpg://u:p@localhost/neos_test"
    assert _test_database_url(url) == url
