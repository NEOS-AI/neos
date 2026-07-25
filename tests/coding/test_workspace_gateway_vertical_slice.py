from datetime import timedelta

from neos.coding.domain.phases import CodingCheckpoint
from neos.coding.domain.workspace_edits import WorkspaceEditStatus
from tests.coding.application.test_run_service import (
    ModelCheckpointLoop,
    NOW,
    make_run_service,
    run_fixture,
)
from tests.coding.application.test_workspace_service import Session, make_service
from tests.coding.fakes import InMemoryCodingRunRepository


async def test_user_edit_reaches_agent_once_without_public_content() -> None:
    session = Session(revision=1)
    workspace, edits = make_service(session)
    saved = await workspace.save_file(
        task_id="ct_1",
        owner_id="u1",
        edit_id="cwe_vertical",
        path="src/app.py",
        base_revision="1",
        content="def add(a, b): return a + b\n",
    )
    committed = edits.values[saved.edit_id]
    run = run_fixture("cr_1")
    repository = InMemoryCodingRunRepository(
        active_run=run,
        task_prompts={"ct_1": "Fix add"},
        workspace_edits=[committed],
    )
    repository.created_runs.append(run)
    repository.task_statuses["ct_1"] = "running"
    await repository.save_checkpoint(
        CodingCheckpoint(
            "cc_before_edit",
            "ct_1",
            "cr_1",
            1,
            {"current_instruction": "Fix add", "transcript": []},
            "1",
            NOW,
        )
    )
    loop = ModelCheckpointLoop()
    runs = await make_run_service(
        repository,
        loop=loop,
        execution_lease=timedelta(seconds=30),
    )

    first = await runs.advance_one_safe_point(
        task_id="ct_1", worker_id="worker-1"
    )
    second = await runs.advance_one_safe_point(
        task_id="ct_1", worker_id="worker-2"
    )

    assert saved.resulting_revision == "2"
    assert session.files["src/app.py"] == b"def add(a, b): return a + b\n"
    assert [edit.edit_id for edit in loop.inputs[0].workspace_edits] == [
        "cwe_vertical"
    ]
    assert all(not item.workspace_edits for item in loop.inputs[1:])
    assert (
        repository.workspace_edits["cwe_vertical"].status
        is WorkspaceEditStatus.APPLIED
    )
    assert first.type == "model.completed"
    assert second.type == "run.completed"
    public = repr(await runs._events.list_after("ct_1"))
    assert "def add" not in public
    assert committed.content_digest not in public
