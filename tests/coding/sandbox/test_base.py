from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.sandbox.base import (
    CommandRequest,
    Sandbox,
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxState,
    SandboxStateConflict,
)


NOW = datetime(2026, 7, 19, tzinfo=UTC)


def test_sandbox_allows_declared_lifecycle_transitions() -> None:
    sandbox = Sandbox.creating(
        "sb_1",
        "user_1",
        SandboxLimits.safe_defaults(),
        NOW,
    )

    running = sandbox.transition(SandboxState.RUNNING, NOW)
    suspended = running.transition(
        SandboxState.SUSPENDED,
        NOW + timedelta(seconds=1),
    )
    resumed = suspended.transition(
        SandboxState.RUNNING,
        NOW + timedelta(seconds=2),
    )

    assert resumed.state is SandboxState.RUNNING


def test_sandbox_rejects_undeclared_lifecycle_transition() -> None:
    sandbox = Sandbox.creating(
        "sb_1",
        "user_1",
        SandboxLimits.safe_defaults(),
        NOW,
    )

    with pytest.raises(SandboxStateConflict, match="creating->suspended"):
        sandbox.transition(SandboxState.SUSPENDED, NOW)


@pytest.mark.parametrize(
    "argv",
    [
        (),
        ("sh", "-c", "echo unsafe"),
        ("bash", "-c", "echo unsafe"),
        ("zsh", "-c", "echo unsafe"),
    ],
)
def test_command_request_rejects_empty_or_shell_commands(
    argv: tuple[str, ...],
) -> None:
    with pytest.raises(SandboxPolicyViolation):
        CommandRequest(argv=argv)


def test_command_request_preserves_bounded_argv() -> None:
    request = CommandRequest(argv=("python", "-V"), timeout_sec=5)

    assert request.argv == ("python", "-V")
    assert request.timeout_sec == 5
