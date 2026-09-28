"""In-tree GEPA kernel. PR1 is types and strict-sum acceptance only."""

from neos.gepa_opt.acceptance import accept_strict_minibatch_sum
from neos.gepa_opt.types import (
    Candidate,
    EngineConfig,
    EngineLabel,
    OverlayStatus,
    ProposerView,
    SplitName,
    validate_candidate,
    validate_overlay_status,
)

__all__ = [
    "Candidate",
    "EngineConfig",
    "EngineLabel",
    "OverlayStatus",
    "ProposerView",
    "SplitName",
    "accept_strict_minibatch_sum",
    "validate_candidate",
    "validate_overlay_status",
]
