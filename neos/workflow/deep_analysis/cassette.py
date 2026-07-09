"""Deterministic record/replay storage for LLM, search, and fetch calls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal


CassetteMode = Literal["record", "replay", "off"]
Producer = Callable[[], Awaitable[Any]]


class Cassette:
    def __init__(
        self,
        path: str | Path,
        mode: CassetteMode = "off",
    ) -> None:
        if mode not in {"record", "replay", "off"}:
            raise ValueError(f"unsupported cassette mode: {mode}")
        self.path = Path(path)
        self.mode = mode
        self._data: dict[str, Any] = {}
        if self.mode == "replay":
            self.load()

    def key(self, kind: str, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"kind": kind, "payload": payload},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("cassette root must be a JSON object")
        self._data = loaded

    def save(self) -> None:
        if self.mode != "record":
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(
                self._data,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    async def remember(
        self,
        kind: str,
        payload: dict[str, Any],
        producer: Producer,
    ) -> Any:
        if self.mode == "off":
            return await producer()

        key = self.key(kind, payload)
        if self.mode == "replay":
            if key not in self._data:
                raise KeyError(f"cassette miss: {kind} {payload}")
            return self._data[key]

        result = await producer()
        # Validate serializability at the boundary, not later during save().
        json.dumps(result, ensure_ascii=False)
        self._data[key] = result
        return result
