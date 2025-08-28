from __future__ import annotations

from neos.core.config.condenser_config import NoOpCondenserConfig
from neos.llm.llm_registry import LLMRegistry
from neos.memory.condenser.condenser import Condensation, Condenser, View


class NoOpCondenser(Condenser):
    """A condenser that does nothing to the event sequence."""

    def condense(self, view: View) -> View | Condensation:
        """Returns the list of events unchanged."""
        return view

    @classmethod
    def from_config(
        cls, config: NoOpCondenserConfig, llm_registry: LLMRegistry
    ) -> NoOpCondenser:
        return NoOpCondenser()


NoOpCondenser.register_config(NoOpCondenserConfig)
