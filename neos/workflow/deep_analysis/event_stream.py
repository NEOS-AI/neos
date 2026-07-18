"""append-only deep_analysis 이벤트 로그에 대한 읽기 전용 커서 리더.

`DAEvent.seq`는 BigInteger autoincrement PK라 **그 자체가 단조 커서**다 --
별도 컬럼이 필요 없다. 커서를 0에서 시작하면 run의 전체 이력이 재생되므로,
진행 중인 run에 늦게 접속한 구독자도 처음부터 받는다(스펙 §5.5 AC6).

이 경로가 프로세스 경계를 넘는 유일한 이유는 매체가 **DB**이기 때문이다.
`neos/workflow/stream_manager.py:99`의 세션 레지스트리는 프로세스 내
dict라 Celery 워커가 넣은 이벤트를 API 프로세스가 볼 수 없다.

seq 폴링이 행을 건너뛰지 않는 근거는 P2(단일 작성자)다: run당 작성자가
하나면 seq 할당 순서가 곧 커밋 순서이므로, 이미 읽은 커서보다 작은 seq가
나중에 커밋되는 일이 없다. 이 모듈은 절대 쓰지 않는다(D8).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from neos.database.deep_analysis_models import DAEvent, DARun

DEFAULT_EVENT_BATCH = 200


def _decode(payload: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(payload)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


async def read_events_after(
    session,
    run_id: str,
    after_seq: int = 0,
    limit: int = DEFAULT_EVENT_BATCH,
) -> list[dict[str, Any]]:
    """`after_seq`보다 큰 seq의 이벤트를 seq 오름차순으로 최대 `limit`개."""
    result = await session.execute(
        select(DAEvent)
        .where(DAEvent.run_id == run_id, DAEvent.seq > after_seq)
        .order_by(DAEvent.seq)
        .limit(limit)
    )
    return [
        {
            "seq": int(row.seq),
            "type": row.kind,
            "qid": row.qid,
            "payload": _decode(row.payload),
        }
        for row in result.scalars()
    ]


async def get_run_owner(session, run_id: str) -> tuple[str | None, str] | None:
    """`(user_id, status)` 또는 run이 없으면 None. 소유권 검사용."""
    run = await session.get(DARun, run_id)
    if run is None:
        return None
    return run.user_id, run.status
