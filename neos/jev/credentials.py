"""TypeSafe 키를 어디서 찾는가.

`.env` 를 직접 파싱하지 않는다. `neos.config.loader.load_dotenv_file` 을 그대로
쓰는 것이 요점이다 -- 파싱 사본을 만들면 형식이나 경로 규칙이 바뀐 날 고침이
한쪽에만 도착하고, 나머지는 *검사가 있다는 믿음과 함께* 그대로 돈다.

우선순위도 저장소의 다른 시크릿과 같다: **프로세스 환경이 `.env` 를 이긴다**
(`loader.apply_secret_overrides` 의 `{**dotenv_env, **process_env}`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from typesafe_sdk import constants

from neos.config.loader import DEFAULT_DOTENV_PATH, load_dotenv_file


class MissingTypeSafeKey(RuntimeError):
    """키가 없다. **없는 것과 틀린 것은 다른 사건**이므로 따로 세운다."""


def resolve_typesafe_key(
    process_env: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> str:
    """프로세스 환경 → `.env` 순으로 찾는다. 없으면 어디에 넣어야 하는지 말한다.

    공백만 있는 값은 **없는 것으로 친다.** `.env.template` 을 복사만 하면
    `TYPESAFE_API_KEY=` 가 그대로 남고, 그 빈 값을 키로 넘기면 첫 실호출에서
    401 이 난다 -- 그리고 그 401 은 "키가 틀렸다"로 읽힌다. 실제로는 아직
    넣지 않은 것이다.
    """
    env = os.environ if process_env is None else process_env
    path = DEFAULT_DOTENV_PATH if dotenv_path is None else dotenv_path

    for value in (env.get(constants.API_KEY_ENV), load_dotenv_file(path).get(constants.API_KEY_ENV)):
        if value and value.strip():
            return value.strip()

    raise MissingTypeSafeKey(
        f"{constants.API_KEY_ENV} 가 없다. `.env` 에 적거나 환경변수로 내보내라. "
        "키를 실제로 불러 보기 전에는 L0 도 L1 도 표본이 아니다."
    )
