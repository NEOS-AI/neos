import pytest

from neos.coding.sandbox.base import SandboxPolicyViolation
from neos.coding.sandbox.images import resolve_sandbox_image, validate_custom_images

pytestmark = pytest.mark.no_db


def test_empty_allowlist_denies_custom_and_keeps_pinned_default() -> None:
    assert (
        resolve_sandbox_image(
            None,
            pinned="neos/sandbox@sha256:abc",
            allowlist=(),
            custom={"team": "ghcr.io/team/img:1"},
        )
        == "neos/sandbox@sha256:abc"
    )
    with pytest.raises(SandboxPolicyViolation, match="sandbox_image_not_allowlisted"):
        resolve_sandbox_image(
            "team",
            pinned="neos/sandbox@sha256:abc",
            allowlist=(),
            custom={"team": "ghcr.io/team/img:1"},
        )


def test_custom_key_cannot_shadow_preset() -> None:
    with pytest.raises(ValueError, match="reserved"):
        validate_custom_images({"python": "evil:latest"})
    with pytest.raises(ValueError, match="reserved"):
        validate_custom_images(
            {"neos/sandbox@sha256:abc": "evil:latest"},
            pinned="neos/sandbox@sha256:abc",
        )


def test_allowlisted_custom_image_resolves() -> None:
    assert (
        resolve_sandbox_image(
            "team",
            pinned="neos/sandbox@sha256:abc",
            allowlist=("team",),
            custom={"team": "ghcr.io/team/img:1"},
        )
        == "ghcr.io/team/img:1"
    )
    with pytest.raises(SandboxPolicyViolation, match="sandbox_image_reserved"):
        resolve_sandbox_image(
            "python",
            pinned="neos/sandbox@sha256:abc",
            allowlist=("python",),
            custom={},
        )
