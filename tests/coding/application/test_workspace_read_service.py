import pytest

from neos.coding.domain.workspace_edits import WorkspaceEditConflict
from tests.coding.application.test_workspace_service import (
    Session,
    make_service,
)


async def test_read_file_returns_revision_and_utf8_text() -> None:
    session = Session()
    session.files["src/app.py"] = "안녕\n".encode()
    service, _ = make_service(session)

    result = await service.read_file(
        task_id="ct_1", owner_id="u1", path="src/app.py"
    )

    assert result.content == "안녕\n"
    assert result.workspace_revision == "12"
    assert result.binary is False
    assert result.size == len("안녕\n".encode())


async def test_binary_file_returns_metadata_without_inline_content() -> None:
    session = Session()
    session.files["asset.bin"] = b"\xff\x00"
    service, _ = make_service(session)

    result = await service.read_file(
        task_id="ct_1", owner_id="u1", path="asset.bin"
    )

    assert result.binary is True
    assert result.content is None
    assert result.size == 2


async def test_tree_is_sorted_and_bounded() -> None:
    session = Session()
    session.files = {"z.py": b"z", "a.py": b"a"}
    service, _ = make_service(session)

    result = await service.list_tree(task_id="ct_1", owner_id="u1")

    assert [entry.path for entry in result.entries] == ["a.py", "z.py"]
    assert result.workspace_revision == "12"


async def test_oversized_file_is_rejected_before_content_is_returned() -> None:
    session = Session()
    session.files["large.txt"] = b"x" * 129
    service, _ = make_service(session)

    with pytest.raises(WorkspaceEditConflict, match="workspace_file_too_large"):
        await service.read_file(
            task_id="ct_1", owner_id="u1", path="large.txt"
        )


async def test_diff_is_truncated_at_utf8_boundary() -> None:
    session = Session()
    session.diff = ("가" * 10).encode()
    service, _ = make_service(session)

    result = await service.git_diff(task_id="ct_1", owner_id="u1")

    assert result.truncated is True
    assert len(result.content.encode()) <= 16
    assert result.workspace_revision == "12"
