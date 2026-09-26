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


class FakeToolPort:
    def __init__(self, names=None, results=None) -> None:
        self._names = tuple(names or ("read_file.v1", "search_text.v1", "execute.v1"))
        self.results = results or {}
        self.calls: list[tuple[str, dict]] = []

    def definitions(self):
        return self._names

    async def execute(self, name: str, input):
        self.calls.append((name, dict(input)))
        if name in self.results:
            return self.results[name]
        return {"ok": True, "path": input.get("path", name)}


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, payload) -> None:
        self.events.append((event_type, dict(payload)))
