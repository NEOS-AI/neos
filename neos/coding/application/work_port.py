"""코딩 태스크 → 작업 기록 포트 (spec 2026-10-13 §4.4, 결정 B).

`neos.coding` 은 채팅 워크플로 런타임을 import 하지 않는다(가드). 그래서 코딩 쪽은 이 포트만
정의하고, 구현(`neos.workflow.runtime.coding_link`)은 앱·워커 시작 때 꽂힌다. 포트가 없거나
실패해도 태스크 생성·완료는 그대로다 -- 로그 한 줄만 남긴다(Q13f 완료 훅과 같은 규율).
"""

from __future__ import annotations

import logging
from typing import Protocol

from neos.coding.domain.models import CodingTask

logger = logging.getLogger(__name__)


class WorkPort(Protocol):
    async def coding_task_created(self, task: CodingTask) -> None: ...

    async def coding_task_completed(self, task: CodingTask) -> None: ...


_port: WorkPort | None = None


def set_work_port(port: WorkPort | None) -> None:
    global _port
    _port = port


async def notify_task_created(task: CodingTask) -> None:
    if _port is None:
        return
    try:
        await _port.coding_task_created(task)
    except Exception:  # noqa: BLE001 -- 기록 실패가 태스크 생성을 막지 않는다
        logger.exception("work record for coding task creation failed task_id=%s", task.task_id)


async def notify_task_completed(task: CodingTask) -> None:
    if _port is None:
        return
    try:
        await _port.coding_task_completed(task)
    except Exception:  # noqa: BLE001
        logger.exception("work record for coding task completion failed task_id=%s", task.task_id)
