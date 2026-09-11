"""Compatibility shim.

The durable coding loop is vendor-neutral. Import `DurableCodingLoop`
and `CodingLoopConfig` from `neos.coding.loop.durable`. These aliases
keep existing tests and callers working.
"""

from neos.coding.loop.durable import (
    AgentLoopState,
    CodingLoopConfig,
    CodingLoopFailure,
    CodingLoopWaitingApproval,
    DurableCodingLoop,
)

AnthropicLoopConfig = CodingLoopConfig
AnthropicCodingLoop = DurableCodingLoop

__all__ = [
    "AgentLoopState",
    "AnthropicCodingLoop",
    "AnthropicLoopConfig",
    "CodingLoopConfig",
    "CodingLoopFailure",
    "CodingLoopWaitingApproval",
    "DurableCodingLoop",
]
