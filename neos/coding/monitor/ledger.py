"""감시자의 원장 꼬리 -- 트랙 Q5b (docs/Q5B_MONITOR_PAUSE_DESIGN_261002.md MP6).

섀도 착지(Q5)는 판정이 없는 턴에도 원장을 **앞에서부터 끝까지** 읽었다. 감시자가
멈추게 하는 길(Q5b)을 켜기 전에 그것을 커서로 바꾼다: 태스크마다 마지막으로 본
`seq` 와 최근 `max_events` 개를 기억하고, 다음 턴에는 그 뒤만 읽는다.

커서가 옳은 이유는 하나다. 태스크 원장의 `seq` 는 `coding_tasks.last_seq + 1` 을
`UPDATE ... RETURNING` 으로 받는다 -- 그 행 잠금이 커밋까지 가므로 한 태스크 안에서
**seq 순서가 커밋 순서다**. 늦게 커밋된 낮은 seq 가 커서 뒤에 나타나는 일이 없다
(합친 원장의 `created_at` 커서와 다르다). 원장은 지우거나 고치지 않는다(append-only).
그래서 기억한 꼬리는 다른 워커가 그 사이에 쓴 것이 있어도 언제나 옳은 앞부분이다.

프로세스를 넘는 상태가 아니다. 워커가 바뀌면 처음 한 번은 앞에서부터 읽는다 --
그 값은 섀도 착지의 매 턴 값과 같다.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from typing import Any

#: `list_after` 한 번에 가져오는 쪽 크기. 섀도 착지의 `_read_ledger` 와 같다.
_PAGE = 500

#: 기억하는 태스크 수. 한 워커 프로세스가 동시에 모는 태스크 수보다 넉넉하면 된다 --
#: 넘치면 가장 오래 안 본 태스크를 잊고, 그 태스크는 다음에 앞에서부터 다시 읽는다
#: (값이 아니라 비용만 바뀐다). 판정 기준이 아니라 메모리 상한이라 설정이 아니다.
_TASKS = 64

Reader = Callable[..., Awaitable[list[Any]]]


class LedgerTail:
    """태스크마다 원장의 최근 `max_events` 개를 커서로 이어 읽는다."""

    def __init__(self, *, max_events: int, max_tasks: int = _TASKS) -> None:
        if max_events < 1 or max_tasks < 1:
            raise ValueError("max_events 와 max_tasks 는 1 이상이어야 한다")
        self.max_events = max_events
        self._max_tasks = max_tasks
        self._tails: OrderedDict[str, tuple[int, deque]] = OrderedDict()

    async def read(self, reader: Reader, task_id: str) -> list[Any]:
        """마지막으로 본 seq 뒤만 읽어 꼬리에 잇고, 최근 `max_events` 개를 돌려준다."""
        after, tail = self._tails.pop(task_id, (0, deque(maxlen=self.max_events)))
        try:
            while True:
                page = await reader(task_id, after_seq=after, limit=_PAGE)
                if not page:
                    break
                for event in page:
                    # 같은 태스크를 두 코루틴이 겹쳐 읽어도 한 이벤트는 한 번만 잇는다.
                    if event.seq > after:
                        tail.append(event)
                        after = event.seq
                if len(page) < _PAGE:
                    break
        finally:
            # 읽다 실패해도 이미 이은 앞부분은 옳다 -- 버리지 않는다.
            self._tails[task_id] = (after, tail)
            while len(self._tails) > self._max_tasks:
                self._tails.popitem(last=False)
        return list(tail)
