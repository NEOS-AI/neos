"""Vendor-neutral model-turn collection, independent of DurableCodingLoop."""

from neos.coding.harness.turn import (
    ModelTurn,
    collect_model_turn,
    fold_model_event,
    iter_model_turn,
)

__all__ = [
    "ModelTurn",
    "collect_model_turn",
    "fold_model_event",
    "iter_model_turn",
]
