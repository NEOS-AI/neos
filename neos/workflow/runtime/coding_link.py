"""코딩 태스크 포트의 구현 (spec 2026-10-13 §4.4, 결정 B).

트리거(에이전트 있음)로 열린 태스크는 entry=trigger, 그 밖은 api. 전달은 코딩 태스크의 기존 알림
경로(Q10b)가 그대로 맡으므로 `delivery={"kind": "none"}` -- 여기서는 같은 ID 체계와 결과 위치만 준다.
"""

from __future__ import annotations

from typing import Any

from neos.workflow.runtime.work import WorkConflict, WorkLifecycle


class CodingWorkLink:
    def __init__(self, lifecycle: WorkLifecycle) -> None:
        self._lifecycle = lifecycle

    async def coding_task_created(self, task: Any) -> None:
        await self._lifecycle.start(
            "trigger" if task.agent_id else "api",
            "coding",
            user_id=task.owner_id,
            session_id=None,
            delivery={"kind": "none"},
            ref_id=task.task_id,
        )

    async def coding_task_completed(self, task: Any) -> None:
        record = await self._lifecycle.store.by_ref("coding", task.task_id)
        if record is None or record.status != "running":
            return
        try:
            await self._lifecycle.complete(record.work_id, {"final_response": None, "author": None, "verified_by": None})
        except WorkConflict:
            return


def install_coding_link() -> bool:
    """네이티브 런타임일 때만 포트를 꽂는다 -- 기본 런타임의 동작은 바뀌지 않는다."""
    from neos.coding.application.work_port import set_work_port
    from neos.workflow.runtime.select import native_turns, runtime_name

    if runtime_name() != "native":
        return False
    set_work_port(CodingWorkLink(native_turns().lifecycle))
    return True
