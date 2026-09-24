"""키를 어디서 찾는가 -- 저장소의 로딩 경로를 **공유**한다.

`.env` 를 직접 파싱하는 사본을 만들면, 형식이나 경로 규칙이 바뀐 날 고침이
한쪽에만 도착한다. 그래서 `loader.load_dotenv_file` 을 그대로 쓴다.

우선순위는 저장소의 다른 시크릿과 같다: **프로세스 환경이 `.env` 를 이긴다**
(`loader.apply_secret_overrides` 의 `{**dotenv_env, **process_env}`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from neos.jev.credentials import MissingTypeSafeKey, resolve_typesafe_key

pytestmark = pytest.mark.no_db


def dotenv(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_key_is_read_from_the_dotenv_file(tmp_path: Path) -> None:
    path = dotenv(tmp_path, "TYPESAFE_API_KEY=from-dotenv\n")
    assert resolve_typesafe_key(process_env={}, dotenv_path=path) == "from-dotenv"


def test_the_process_environment_wins(tmp_path: Path) -> None:
    path = dotenv(tmp_path, "TYPESAFE_API_KEY=from-dotenv\n")
    resolved = resolve_typesafe_key(
        process_env={"TYPESAFE_API_KEY": "from-process"}, dotenv_path=path
    )
    assert resolved == "from-process"


def test_a_blank_value_counts_as_missing(tmp_path: Path) -> None:
    """`.env.template` 을 복사만 하면 `TYPESAFE_API_KEY=` 가 그대로 남는다.

    빈 값을 키로 읽으면 첫 실호출에서 401 이 나고, 그 401 은 "키가 틀렸다"로
    읽힌다 -- 실제로는 아직 넣지 않은 것이다.
    """
    path = dotenv(tmp_path, "TYPESAFE_API_KEY=\n")
    with pytest.raises(MissingTypeSafeKey):
        resolve_typesafe_key(process_env={}, dotenv_path=path)


def test_a_missing_file_is_not_an_error_by_itself(tmp_path: Path) -> None:
    """`.env` 가 없어도 프로세스 환경에 있으면 된다."""
    resolved = resolve_typesafe_key(
        process_env={"TYPESAFE_API_KEY": "from-process"},
        dotenv_path=tmp_path / "absent",
    )
    assert resolved == "from-process"


def test_nowhere_at_all_says_where_to_put_it(tmp_path: Path) -> None:
    with pytest.raises(MissingTypeSafeKey, match=".env"):
        resolve_typesafe_key(process_env={}, dotenv_path=tmp_path / "absent")
