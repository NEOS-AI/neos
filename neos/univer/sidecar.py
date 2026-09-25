from __future__ import annotations

import shutil
from pathlib import Path


def node_binary() -> Path | None:
    found = shutil.which("node")
    return Path(found) if found else None


class SidecarClient:
    def __init__(self, *, node: Path | None = None) -> None:
        self._node = node

    @property
    def node(self) -> Path | None:
        return self._node

    def unavailable_error(self) -> str:
        if self._node is None:
            return "node_missing"
        return "sidecar_unavailable"
