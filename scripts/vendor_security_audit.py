#!/usr/bin/env python3
"""Vendor the Cloudflare security-audit skill as a nested markdown pack.

Upstream SKILL.md is copied as-is. Companion markdown is also copied into
references/ so load_markdown(..., reference=) can resolve it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT.parent / "security-audit-skill"
DEST = REPO_ROOT / "skills" / "security-audit"
SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules"}


def vendor(source_root: Path, dest_root: Path) -> int:
    if not source_root.is_dir():
        raise SystemExit(f"security-audit source not found: {source_root}")
    source_skill = source_root / "skills" / "security-audit"
    if not source_skill.is_dir():
        raise SystemExit(f"security-audit skill directory not found: {source_skill}")
    dest_child = dest_root / "security-audit"
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True)
    shutil.copytree(
        source_skill,
        dest_child,
        ignore=shutil.ignore_patterns(*SKIP_DIR_NAMES),
    )
    refs = dest_child / "references"
    refs.mkdir(parents=True, exist_ok=True)
    for md in sorted(source_skill.glob("*.md")):
        if md.name == "SKILL.md":
            continue
        shutil.copy2(md, refs / md.name)
    license_src = source_root / "LICENSE"
    if license_src.is_file():
        shutil.copy2(license_src, dest_root / "LICENSE")
    (dest_root / "SOURCE.md").write_text(_source_md(source_root), encoding="utf-8")
    return 1


def _source_pin(source_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _source_md(source_root: Path) -> str:
    pin = _source_pin(source_root)
    return "\n".join(
        [
            "# security-audit pack source",
            "",
            "Vendored from sibling `../security-audit-skill` with `scripts/vendor_security_audit.py`.",
            f"Source commit: `{pin}`.",
            "One skill: `security-audit`. Companion markdown is copied beside SKILL.md and into `references/`.",
            "",
        ]
    )


def main(argv: list[str]) -> int:
    source = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_SOURCE
    count = vendor(source, DEST)
    print(f"vendored {count} skills into {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
