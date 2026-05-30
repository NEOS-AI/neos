from __future__ import annotations

from typing import Any


def should_cache_harness_result(
    result: dict[str, Any],
    *,
    cache_policy: str = "passed_only",
) -> bool:
    metadata = result.get("metadata") or {}
    harness = metadata.get("harness") or {}
    verdict = harness.get("verdict")
    mode = harness.get("mode")

    if not verdict:
        return True
    if verdict in {"pass", "advisory_pass", "skipped"}:
        return True
    if mode == "advisory" and verdict == "fail":
        return cache_policy == "allow_advisory_fail"
    return False

