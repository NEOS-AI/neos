"""런타임 선택 -- 한 곳 (spec 2026-10-13 §6.1 단계 3).

`workflow.runtime` 이 `native` 일 때만 네이티브 저장소를 만든다. 테스트는 `set_native_turns` 로
메모리 저장소를 꽂는다.
"""

from __future__ import annotations

from neos.workflow.runtime.turns import NativeTurns

_turns: NativeTurns | None = None


def runtime_name() -> str:
    from neos.config.settings import settings

    return settings.config.workflow.runtime


def native_turns() -> NativeTurns:
    global _turns
    if _turns is None:
        from neos.config.settings import settings
        from neos.database.connection import db_manager
        from neos.workflow.runtime.sessions import PostgresSessionStore
        from neos.workflow.runtime.work import PostgresWorkStore, WorkLifecycle

        _turns = NativeTurns(
            PostgresSessionStore(db_manager.get_session),
            WorkLifecycle(PostgresWorkStore(db_manager.get_session)),
            max_carried_items=settings.config.workflow.session.max_carried_items,
        )
    return _turns


def set_native_turns(turns: NativeTurns | None) -> None:
    global _turns
    _turns = turns
