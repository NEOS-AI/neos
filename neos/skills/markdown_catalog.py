"""Markdown-only Agent Skill catalog.

Indexes SKILL.md (and coding *.md) by name + description without requiring
skill.py. Bodies load on demand. Entries are never executed as BaseSkill.

The default catalog is the coding index (``neos/coding/skills/``). Repo-root
``skills/`` and builtin ``skill.py`` skills stay on the research SkillManager.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from neos.skills.base.metadata_parser import extract_frontmatter

logger = logging.getLogger(__name__)

SkillSource = Literal["repo", "coding", "builtin"]

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class MarkdownSkill:
    name: str
    description: str
    path: Path
    source: SkillSource
    disable_model_invocation: bool = False
    allowed_tools: tuple[str, ...] = ()
    when_to_use: str = ""
    user_invocable: bool = True


def default_skill_roots() -> tuple[tuple[SkillSource, Path], ...]:
    """Coding catalog roots. Repo-root ``skills/`` is research-only."""
    return (("coding", _REPO_ROOT / "neos" / "coding" / "skills"),)


def research_skill_roots() -> tuple[tuple[SkillSource, Path], ...]:
    """Research/chat markdown index. Not used by load_skill.v1."""
    return (
        ("repo", _REPO_ROOT / "skills"),
        ("builtin", _REPO_ROOT / "neos" / "skills" / "builtin"),
    )


_REQUIRED_SECTION_HEADINGS = ("## When to Use", "## Boundaries")


def _has_required_sections(content: str) -> bool:
    """Loose substring check. Research catalogs warn-only with this."""
    lowered = content.lower()
    return "## when to use" in lowered and "## boundaries" in lowered


def _atx_h2_heading(line: str) -> str | None:
    heading = line.rstrip()
    if heading.startswith("## ") and not heading.startswith("###"):
        return heading
    return None


def _coding_sections_valid(content: str) -> bool:
    """Exact ATX ``## When to Use`` / ``## Boundaries`` with non-empty bodies."""
    wanted = set(_REQUIRED_SECTION_HEADINGS)
    found: set[str] = set()
    current: str | None = None
    has_body = False

    def close_section() -> bool:
        nonlocal current, has_body
        if current is None:
            return True
        if not has_body:
            return False
        found.add(current)
        current = None
        has_body = False
        return True

    for line in content.splitlines():
        heading = _atx_h2_heading(line)
        if heading is not None:
            if not close_section():
                return False
            if heading in wanted:
                current = heading
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            has_body = True

    if not close_section():
        return False
    return found == wanted


def _is_safe_name(name: str) -> bool:
    if not name or name != name.strip():
        return False
    if "\0" in name or "/" in name or "\\" in name:
        return False
    if name in {".", ".."} or ".." in name:
        return False
    return True


def _frontmatter_str(parsed: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _frontmatter_bool(
    parsed: dict, keys: tuple[str, ...], *, default: bool
) -> bool:
    for key in keys:
        if key not in parsed:
            continue
        value = parsed[key]
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        if isinstance(value, (int, float)) and value in {0, 1}:
            return bool(value)
    return default


def _frontmatter_tools(parsed: dict) -> tuple[str, ...]:
    value = parsed.get("allowed-tools", parsed.get("allowed_tools"))
    if isinstance(value, str):
        return tuple(part for part in re.split(r"[\s,]+", value) if part)
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                names.append(item.strip())
        return tuple(names)
    return ()


def _fallback_description(content: str) -> str:
    heading = ""
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if not heading:
                heading = stripped.lstrip("#").strip()
            continue
        return stripped
    return heading


def _parse_markdown_skill(
    path: Path,
    source: SkillSource,
    fallback_name: str,
) -> MarkdownSkill | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Skipping unreadable skill file %s: %s", path, exc)
        return None

    name = fallback_name
    description = ""
    disable_model_invocation = False
    allowed_tools: tuple[str, ...] = ()
    when_to_use = ""
    user_invocable = True
    frontmatter, body = extract_frontmatter(content)
    if frontmatter is not None:
        try:
            parsed = yaml.safe_load(frontmatter)
        except yaml.YAMLError as exc:
            logger.warning("Skipping skill with invalid YAML %s: %s", path, exc)
            return None
        if isinstance(parsed, dict):
            raw_name = parsed.get("name")
            if isinstance(raw_name, str) and raw_name.strip():
                name = raw_name.strip()
                if source == "coding" and name != fallback_name:
                    logger.warning(
                        "Skipping coding skill %r whose name does not match %r at %s",
                        name,
                        fallback_name,
                        path,
                    )
                    return None
            raw_desc = parsed.get("description")
            if isinstance(raw_desc, str):
                description = raw_desc.strip()
            disable_model_invocation = _frontmatter_bool(
                parsed,
                ("disable-model-invocation", "disable_model_invocation"),
                default=False,
            )
            allowed_tools = _frontmatter_tools(parsed)
            when_to_use = _frontmatter_str(
                parsed, ("when_to_use", "when-to-use")
            )
            user_invocable = _frontmatter_bool(
                parsed,
                ("user_invocable", "user-invocable"),
                default=True,
            )
        elif parsed is not None:
            logger.warning("Skipping skill with non-mapping frontmatter %s", path)
            return None

    if not description:
        description = _fallback_description(body if body is not None else content)

    if not _is_safe_name(name):
        logger.warning("Skipping skill with unsafe name %r at %s", name, path)
        return None

    body_text = body if body is not None else content
    if source == "coding":
        if not _coding_sections_valid(body_text):
            logger.warning(
                "Skipping coding skill %r without When to Use / Boundaries at %s",
                name,
                path,
            )
            return None
    elif not _has_required_sections(body_text):
        logger.warning(
            "Skill %r is missing When to Use / Boundaries at %s",
            name,
            path,
        )

    try:
        resolved = path.resolve()
    except OSError as exc:
        logger.warning("Skipping unresolvable skill path %s: %s", path, exc)
        return None

    return MarkdownSkill(
        name=name,
        description=description,
        path=resolved,
        source=source,
        disable_model_invocation=disable_model_invocation,
        allowed_tools=allowed_tools,
        when_to_use=when_to_use,
        user_invocable=user_invocable,
    )


class MarkdownSkillCatalog:
    """Cached index of markdown skills under allowed roots."""

    def __init__(
        self,
        roots: tuple[tuple[SkillSource, Path], ...] | None = None,
    ) -> None:
        raw = roots if roots is not None else default_skill_roots()
        self._roots = tuple((source, Path(path).resolve()) for source, path in raw)
        self._index: dict[str, MarkdownSkill] | None = None

    def reload(self) -> None:
        self._index = self._scan()

    def list_skills(
        self, *, include_disabled: bool = False
    ) -> tuple[MarkdownSkill, ...]:
        index = self._ensure_index()
        return tuple(
            index[name]
            for name in sorted(index)
            if include_disabled or not index[name].disable_model_invocation
        )

    def get(self, name: str) -> MarkdownSkill | None:
        if not _is_safe_name(name):
            return None
        return self._ensure_index().get(name)

    def load_markdown(self, name: str) -> str | None:
        skill = self.get(name)
        if skill is None:
            return None
        if not self._path_allowed(skill.path):
            logger.warning("Refusing to load skill %r outside catalog roots", name)
            return None
        try:
            if not skill.path.is_file():
                return None
            return skill.path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read skill %r at %s: %s", name, skill.path, exc)
            return None

    def _ensure_index(self) -> dict[str, MarkdownSkill]:
        if self._index is None:
            self.reload()
        assert self._index is not None
        return self._index

    def _path_allowed(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        return any(resolved.is_relative_to(root) for _source, root in self._roots)

    def _scan(self) -> dict[str, MarkdownSkill]:
        index: dict[str, MarkdownSkill] = {}
        for source, root in self._roots:
            if not root.is_dir():
                continue
            if source == "coding":
                self._index_flat_markdown(index, root, source)
            self._index_skill_directories(index, root, source)
        return index

    def _index_flat_markdown(
        self,
        index: dict[str, MarkdownSkill],
        root: Path,
        source: SkillSource,
    ) -> None:
        for path in sorted(root.glob("*.md")):
            if not path.is_file():
                continue
            skill = _parse_markdown_skill(path, source, fallback_name=path.stem)
            self._put(index, skill, root=root)

    def _index_skill_directories(
        self,
        index: dict[str, MarkdownSkill],
        root: Path,
        source: SkillSource,
    ) -> None:
        try:
            children = sorted(root.iterdir())
        except OSError as exc:
            logger.warning("Failed to scan skill root %s: %s", root, exc)
            return
        for child in children:
            if not child.is_dir() or child.name.startswith(("_", ".")):
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue
            skill = _parse_markdown_skill(
                skill_md, source, fallback_name=child.name
            )
            self._put(index, skill, root=root)

    def _put(
        self,
        index: dict[str, MarkdownSkill],
        skill: MarkdownSkill | None,
        *,
        root: Path,
    ) -> None:
        if skill is None:
            return
        if not skill.path.is_relative_to(root):
            logger.warning(
                "Skipping skill %r whose path %s is outside %s",
                skill.name,
                skill.path,
                root,
            )
            return
        existing = index.get(skill.name)
        if existing is not None:
            logger.debug(
                "Skipping duplicate markdown skill %s from %s (kept %s)",
                skill.name,
                skill.path,
                existing.path,
            )
            return
        index[skill.name] = skill


_DEFAULT_CATALOG: MarkdownSkillCatalog | None = None


def default_catalog() -> MarkdownSkillCatalog:
    global _DEFAULT_CATALOG
    if _DEFAULT_CATALOG is None:
        _DEFAULT_CATALOG = MarkdownSkillCatalog()
    return _DEFAULT_CATALOG


def list_skills() -> tuple[MarkdownSkill, ...]:
    return default_catalog().list_skills()


def get(name: str) -> MarkdownSkill | None:
    return default_catalog().get(name)


def load_markdown(name: str) -> str | None:
    return default_catalog().load_markdown(name)


def reload() -> None:
    default_catalog().reload()
