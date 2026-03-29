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
