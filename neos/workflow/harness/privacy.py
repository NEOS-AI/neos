from __future__ import annotations

import copy
import hashlib
from typing import Any
from urllib.parse import urlparse

from neos.workflow.harness.models import HarnessCheckResult


SENSITIVE_TEXT_KEYS = {"text", "claim", "content", "snippet", "source_text"}


def sanitize_check_result(
    check: HarnessCheckResult,
    *,
    policy: str,
) -> HarnessCheckResult:
    policy = policy if policy in {"summary_only", "redacted", "full"} else "summary_only"
    safe_check = copy.deepcopy(check)
    if policy == "full":
        return safe_check
    if policy == "summary_only":
        safe_check.evidence = []
        safe_check.failed_items = (
            [{"count": len(check.failed_items)}] if check.failed_items else []
        )
        return safe_check
    safe_check.evidence = sanitize_items(check.evidence, policy=policy)
    safe_check.failed_items = sanitize_items(check.failed_items, policy=policy)
    return safe_check


def sanitize_items(items: list[dict[str, Any]], *, policy: str) -> list[dict[str, Any]]:
    if policy == "full":
        return copy.deepcopy(items)
    if policy == "summary_only":
        return [{"count": len(items)}] if items else []
    return [_redact_item(item) for item in items if isinstance(item, dict)]


def _redact_item(item: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in item.items():
        if key in SENSITIVE_TEXT_KEYS and value is not None:
            text = str(value)
            redacted[f"{key}_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            redacted[f"{key}_length"] = len(text)
            continue
        if key == "url" and value is not None:
            redacted["url_domain"] = urlparse(str(value)).netloc or str(value)
            continue
        if isinstance(value, dict):
            redacted[key] = _redact_item(value)
            continue
        if isinstance(value, list):
            redacted[key] = [
                _redact_item(entry) if isinstance(entry, dict) else entry
                for entry in value
            ]
            continue
        redacted[key] = value
    return redacted
