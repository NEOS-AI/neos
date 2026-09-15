"""Managed coding sandboxes attached to the managed allocation plane.

See `provider.py` for the structure, `adapter.py` for the allocation-plane side,
and docs/MANAGED_SANDBOX_B2_DESIGN_260915.md for the design decisions.
"""

from neos.coding.sandbox.managed.adapter import (
    ManagedCodingAllocationAdapter,
    prepare_coding_intent,
)
from neos.coding.sandbox.managed.provider import (
    SERVABLE_PROVIDERS,
    ManagedBackend,
    ManagedSandboxProvider,
    create_managed_coding_adapter,
    create_managed_sandbox_provider,
)

__all__ = [
    "SERVABLE_PROVIDERS",
    "ManagedBackend",
    "ManagedCodingAllocationAdapter",
    "ManagedSandboxProvider",
    "create_managed_coding_adapter",
    "create_managed_sandbox_provider",
    "prepare_coding_intent",
]
