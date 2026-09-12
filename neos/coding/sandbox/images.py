"""Custom sandbox image allowlist. Empty allowlist denies extras."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from neos.coding.sandbox.base import SandboxPolicyViolation

RESERVED_IMAGE_KEYS = frozenset({"default", "python", "node"})


def validate_custom_images(
    custom: Mapping[str, str],
    *,
    pinned: str = "",
) -> None:
    for key in custom:
        if key in RESERVED_IMAGE_KEYS or (pinned and key == pinned):
            raise ValueError("custom sandbox image key shadows a reserved preset")


def resolve_sandbox_image(
    requested: str | None,
    *,
    pinned: str,
    allowlist: Sequence[str],
    custom: Mapping[str, str],
) -> str:
    name = (requested or "").strip() or "default"
    if name in {"default", pinned}:
        return pinned
    if name in RESERVED_IMAGE_KEYS:
        raise SandboxPolicyViolation("sandbox_image_reserved")
    if name not in allowlist:
        raise SandboxPolicyViolation("sandbox_image_not_allowlisted")
    resolved = custom.get(name)
    if not resolved:
        raise SandboxPolicyViolation("sandbox_image_unknown")
    return resolved
