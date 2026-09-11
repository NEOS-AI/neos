import pytest

from neos.api.channels.lifecycle import (
    format_lifecycle_card,
    push_bound_lifecycle,
)
from neos.api.channels.session_bind import InMemoryChannelCodingBindStore

pytestmark = pytest.mark.no_db


def test_lifecycle_card_omits_housekeeping_and_running() -> None:
    assert format_lifecycle_card("ct_1", "running") is None
    assert (
        format_lifecycle_card(
            "ct_1", "waiting_approval", approval_id="ca_1", tool_name="todo_write.v1"
        )
        is None
    )
    assert (
        format_lifecycle_card(
            "ct_1", "waiting_approval", approval_id="ca_9", tool_name="write_file.v1"
        )
        == "ct_1 waiting_approval ca_9 write_file.v1"
    )
    assert format_lifecycle_card("ct_1", "completed") == "ct_1 completed"


async def test_push_uses_task_bind_and_skips_unbound() -> None:
    store = InMemoryChannelCodingBindStore()
    await store.bind("v2:slack:T:C:1", "ct_1", "u_owner")
    published: list[tuple[str, str]] = []

    class Sink:
        async def publish(self, binding, text) -> None:
            published.append((binding.session_id, text))

    text = await push_bound_lifecycle(
        get_binding=store.get_by_task,
        sink=Sink(),
        task_id="ct_1",
        status="completed",
    )
    missing = await push_bound_lifecycle(
        get_binding=store.get_by_task,
        sink=Sink(),
        task_id="ct_missing",
        status="completed",
    )

    assert text == "ct_1 completed"
    assert published == [("v2:slack:T:C:1", "ct_1 completed")]
    assert missing is None
