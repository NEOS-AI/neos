from datetime import UTC, datetime

import pytest

from neos.coding.domain.phases import (
    CodingPhaseKind,
    CodingPhaseStatus,
    next_phase_attempt,
)


NOW = datetime(2026, 7, 19, tzinfo=UTC)


def test_reentering_phase_appends_attempt_instead_of_rewriting_history() -> None:
    phases = [
        (CodingPhaseKind.UNDERSTAND, 1),
        (CodingPhaseKind.PLAN, 1),
        (CodingPhaseKind.IMPLEMENT, 1),
    ]

    phase = next_phase_attempt(
        task_id="ct_1",
        run_id="cr_1",
        kind=CodingPhaseKind.UNDERSTAND,
        existing=phases,
        now=NOW,
    )

    assert phase.attempt == 2
    assert phase.status is CodingPhaseStatus.ACTIVE


def test_phase_attempt_must_be_positive() -> None:
    with pytest.raises(ValueError, match="attempt"):
        next_phase_attempt(
            task_id="ct_1",
            run_id="cr_1",
            kind=CodingPhaseKind.PLAN,
            existing=[(CodingPhaseKind.PLAN, 0)],
            now=NOW,
        )
