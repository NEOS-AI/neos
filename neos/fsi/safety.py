from __future__ import annotations

BINDING_ACTIONS = frozenset(
    {
        "ledger_post",
        "post_je",
        "kyc_approve",
        "account_open",
        "publish",
        "send",
        "trade_execute",
        "bind_risk",
    }
)
SUCCESS_ARTIFACT_STATUS = "staged_for_signoff"
SUCCESS_HARNESS_VERDICT = "pass"


def policy_binding_denied(action: str) -> bool:
    return action in BINDING_ACTIONS


def binding_error(action: str) -> dict[str, str]:
    return {"error": "policy_binding_denied", "action": action}


def quoted_json_is_handoff(text: str) -> bool:
    return False
