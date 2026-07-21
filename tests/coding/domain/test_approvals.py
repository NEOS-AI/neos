import json

from neos.coding.domain.approvals import (
    ApprovalPolicyOutcome,
    ApprovalStatus,
    approval_display_summary,
    canonical_approval_hash,
    evaluate_approval,
)
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall


def call(
    name: str,
    input: dict[str, object],
    risk: ToolRisk,
) -> ValidatedToolCall:
    return ValidatedToolCall(name=name, input=input, risk=risk)


def binding(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "task_id": "ct_1",
        "run_id": "cr_1",
        "tool_call_id": "tool_1",
        "tool_name": "write_file.v1",
        "normalized_input": {"path": "src/main.py", "content": "value"},
        "checkpoint_id": "cc_1",
        "workspace_revision": "rev-1",
    }
    value.update(overrides)
    return value


def test_policy_allows_reads_and_requires_exact_approval_for_mutations() -> None:
    read = call("read_file.v1", {"path": "README.md"}, ToolRisk.READ_ONLY)
    write = call(
        "write_file.v1",
        {"path": "src/main.py", "content": "value"},
        ToolRisk.WORKSPACE_WRITE,
    )
    command = call("execute.v1", {"argv": ["pytest"]}, ToolRisk.COMMAND)

    assert evaluate_approval(read) is ApprovalPolicyOutcome.ALLOW
    assert evaluate_approval(write) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(command) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_canonical_hash_is_deterministic_and_binding_sensitive() -> None:
    first = canonical_approval_hash(binding())
    reordered = canonical_approval_hash(dict(reversed(tuple(binding().items()))))

    assert first == reordered
    assert first != canonical_approval_hash(binding(workspace_revision="rev-2"))
    assert first != canonical_approval_hash(
        binding(normalized_input={"path": "src/main.py", "content": "other"})
    )
    assert len(first) == 64


def test_write_summary_exposes_path_but_never_content() -> None:
    summary = approval_display_summary(
        call(
            "write_file.v1",
            {"path": "src/main.py", "content": "raw-secret-content"},
            ToolRisk.WORKSPACE_WRITE,
        )
    )

    encoded = json.dumps(summary)
    assert summary == {"path": "src/main.py"}
    assert "raw-secret-content" not in encoded


def test_command_summary_exposes_executable_and_count_but_not_values() -> None:
    summary = approval_display_summary(
        call(
            "execute.v1",
            {
                "argv": ["pytest", "tests/private_test.py", "-q"],
                "env": {"TOKEN": "raw-secret-token"},
                "stdin": "raw-secret-stdin",
                "cwd": ".",
            },
            ToolRisk.COMMAND,
        )
    )

    encoded = json.dumps(summary)
    assert summary == {"executable": "pytest", "argument_count": 2}
    assert "private_test.py" not in encoded
    assert "raw-secret-token" not in encoded
    assert "raw-secret-stdin" not in encoded


def test_approval_status_has_only_durable_contract_values() -> None:
    assert {status.value for status in ApprovalStatus} == {
        "pending",
        "approved",
        "denied",
        "expired",
        "invalidated",
    }
