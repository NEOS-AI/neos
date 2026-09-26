#!/usr/bin/env python3
"""Compose the Neos k-skill pack from a sibling NomaDamas/k-skill clone.

Source of truth for each skill is skill.json + instruction.md.
Generated CLI stubs are not copied as SKILL.md.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT.parent / "k-skill"
DEST = REPO_ROOT / "skills" / "k-skill"
EXCLUDED = frozenset({"k-skill-setup", "k-skill-cleaner"})
COPY_DIR_NAMES = (
    "scripts",
    "references",
    "reference",
    "templates",
    "tests",
    "assets",
)
COPY_FILE_NAMES = (
    "skill.json",
    "instruction.md",
    "LICENSE.upstream",
    "NOTICE",
    "requirements.txt",
    "TROUBLESHOOTING.md",
)
SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", ".venv"}


def _is_skill_dir(path: Path) -> bool:
    return path.is_dir() and (path / "skill.json").is_file() and (path / "instruction.md").is_file()


def _compose_skill_md(source: Path) -> str:
    data = json.loads((source / "skill.json").read_text(encoding="utf-8"))
    frontmatter = str(data.get("frontmatter") or "").strip()
    if not frontmatter:
        name = str(data.get("name") or source.name).strip()
        description = str(data.get("description") or "").strip()
        frontmatter = f"name: {name}\ndescription: {description}"
    instruction = (source / "instruction.md").read_text(encoding="utf-8")
    if instruction.startswith("---"):
        rest = instruction.split("---", 2)
        if len(rest) == 3:
            instruction = rest[2].lstrip("\n")
    return f"---\n{frontmatter}\n---\n\n{instruction.rstrip()}\n"


def vendor(source_root: Path, dest_root: Path) -> int:
    if not source_root.is_dir():
        raise SystemExit(f"k-skill source not found: {source_root}")
    dest_root.mkdir(parents=True, exist_ok=True)
    count = 0
    for child in sorted(source_root.iterdir()):
        if child.name in EXCLUDED or not _is_skill_dir(child):
            continue
        dest = dest_root / child.name
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text(_compose_skill_md(child), encoding="utf-8")
        for name in COPY_FILE_NAMES:
            src = child / name
            if src.is_file():
                shutil.copy2(src, dest / name)
        for name in COPY_DIR_NAMES:
            src = child / name
            if src.is_dir():
                shutil.copytree(
                    src,
                    dest / name,
                    ignore=shutil.ignore_patterns(*SKIP_DIR_NAMES),
                )
        count += 1
    license_src = source_root / "LICENSE"
    if license_src.is_file():
        shutil.copy2(license_src, dest_root / "LICENSE")
    (dest_root / "SOURCE.md").write_text(
        "\n".join(
            [
                "# k-skill pack source",
                "",
                f"Vendored from `{source_root}` with `scripts/vendor_k_skill.py`.",
                "Each `SKILL.md` is `skill.json` frontmatter plus `instruction.md`.",
                "Excluded: `k-skill-setup`, `k-skill-cleaner`.",
                "Do not copy `packages/` or `k-skill-proxy`.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return count


def main(argv: list[str]) -> int:
    source = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_SOURCE
    count = vendor(source, DEST)
    print(f"vendored {count} skills into {DEST}")
    if count != 125:
        print(f"warning: expected 125, got {count}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
