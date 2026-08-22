"""원장에서 런 구성을 되읽는다.

판독 규칙(설계 §3.4): 재개하면 `run_manifest` 가 두 번째로 append 되므로,
런 전체의 "유효 구성" 을 물으면 **마지막** 매니페스트를 준다. 특정 이벤트
seq 시점의 구성이 필요해지면 그때 seq 인자를 받는 함수를 따로 만든다 --
지금 필요한 것은 표본 게이트와 아티팩트 층뿐이고 둘 다 런 단위다.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from sqlalchemy import select

from neos.database.deep_analysis_models import DAEvent

from .manifest import MANIFEST_KIND


async def manifests_for(
    session, run_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    if not run_ids:
        return {}
    result = await session.execute(
        select(DAEvent.run_id, DAEvent.payload)
        .where(
            DAEvent.run_id.in_(list(run_ids)),
            DAEvent.kind == MANIFEST_KIND,
        )
        .order_by(DAEvent.seq)
    )
    found: dict[str, dict[str, Any]] = {}
    for run_id, payload in result.all():
        try:
            parsed = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            # seq 오름차순이므로 마지막 것이 남는다.
            found[run_id] = parsed
    return found


async def runs_without_manifest(
    session, run_ids: Sequence[str]
) -> list[str]:
    found = await manifests_for(session, run_ids)
    return [run_id for run_id in run_ids if run_id not in found]
