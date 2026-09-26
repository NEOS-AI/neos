from __future__ import annotations

from neos.coding.model.errors import CodingModelError


class ScriptedCodingModel:
    def __init__(self, script) -> None:
        self.script = [tuple(turn) for turn in script]
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        if not self.script:
            raise CodingModelError("model_script_exhausted", retryable=False)
        for event in self.script.pop(0):
            yield event
