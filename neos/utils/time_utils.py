"""시간 유틸리티 함수

PostgreSQL TIMESTAMP WITHOUT TIME ZONE 컬럼 저장용 naive UTC datetime 헬퍼.
"""
from datetime import datetime, timezone


def utc_now_naive() -> datetime:
    """현재 UTC 시각을 naive datetime으로 반환한다 (DB 저장용).

    Returns:
        tzinfo=None인 UTC 현재 시각
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime) -> datetime:
    """aware datetime을 naive UTC로 정규화한다 (naive 값은 그대로 반환).

    ``timestamp without time zone`` 컬럼과 비교/바인딩할 때 asyncpg가 aware
    datetime을 거부하므로, 경계값을 naive UTC로 맞춘다.
    """
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value
