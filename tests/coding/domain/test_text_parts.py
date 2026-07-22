from dataclasses import replace
from datetime import UTC, datetime

import pytest

from neos.coding.domain.text_parts import CodingTextPart, TextPartStatus

NOW = datetime(2026, 7, 22, tzinfo=UTC)


def part(**overrides) -> CodingTextPart:
    values = {
        "part_id": "ctp_1", "task_id": "ct_1", "run_id": "cr_1",
        "turn_id": "turn_1", "first_seq": 1, "last_seq": 2,
        "status": TextPartStatus.STREAMING, "content": "안녕",
        "content_bytes": 6, "created_at": NOW, "updated_at": NOW,
    }
    values.update(overrides)
    return CodingTextPart(**values)


def test_text_part_tracks_utf8_bytes_and_sequence_range() -> None:
    assert part().content_bytes == 6
    assert replace(part(), status=TextPartStatus.COMPLETED).status.value == "completed"
    assert replace(part(), status=TextPartStatus.INTERRUPTED).status.value == "interrupted"


@pytest.mark.parametrize(
    "overrides",
    [
        {"part_id": ""},
        {"first_seq": 0},
        {"first_seq": 3, "last_seq": 2},
        {"content_bytes": 2},
    ],
)
def test_text_part_rejects_invalid_identity_sequence_or_byte_count(overrides) -> None:
    with pytest.raises(ValueError):
        part(**overrides)
