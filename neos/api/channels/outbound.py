"""Outbound channel file path gate. Default-off; empty allow_dirs denies all."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence


def validate_outbound_path(
    path: str | os.PathLike[str],
    allow_dirs: Sequence[str | os.PathLike[str]] | None,
) -> Path | None:
    """Return the resolved path if it stays inside one allow dir; else None."""
    if not path or not allow_dirs:
        return None
    try:
        resolved = Path(path).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    for raw_allow in allow_dirs:
        if not raw_allow:
            continue
        try:
            allow = Path(raw_allow).resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        try:
            resolved.relative_to(allow)
        except ValueError:
            continue
        return resolved
    return None


def resolve_outbound_file(
    path: str | os.PathLike[str],
    allow_dirs: Sequence[str | os.PathLike[str]] | None = None,
) -> Path | None:
    """Fail-closed: flag off or path escape → do not send."""
    from neos.config.settings import settings

    if not settings.config.channels.outbound_files:
        return None
    return validate_outbound_path(path, allow_dirs or [])
