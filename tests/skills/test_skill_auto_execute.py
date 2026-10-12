"""자동 실행 후보는 SKILL.md 의 `auto_execute: true` 로만 정해진다 (spec §3.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from neos.skills.base.errors import SkillValidationError
from neos.skills.base.metadata_parser import parse_skill_metadata
from neos.skills.manager.auto_discovery import discover_skills

pytestmark = pytest.mark.no_db

BUILTIN_DIR = Path(__file__).resolve().parents[2] / "neos" / "skills" / "builtin"

AUTO_EXECUTE = frozenset(
    {
        "arxiv",
        "pubmed",
        "wikipedia",
        "openalex",
        "semantic-scholar",
        "google-scholar",
        "sec-edgar",
        "github-search",
        "reddit",
        "news-api",
        "research-assistant",
    }
)
NOT_AUTO = frozenset({"docx", "pdf", "cron", "canvas"})


def _write_skill(root: Path, extra: str) -> Path:
    skill_dir = root / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: demo\n"
        "type: research\n"
        "description: demo skill\n"
        "capabilities:\n"
        "  - demo\n"
        f"{extra}"
        "---\n\n# demo\n",
        encoding="utf-8",
    )
    return skill_dir


def test_builtin_candidates_are_exactly_the_eleven_by_name() -> None:
    infos = {info.name: info for info in discover_skills(BUILTIN_DIR, check_deps=False)}
    assert {name for name, info in infos.items() if info.auto_execute} == AUTO_EXECUTE
    assert NOT_AUTO <= set(infos)
    assert not {name for name in NOT_AUTO if infos[name].auto_execute}


def test_auto_execute_defaults_to_false(tmp_path: Path) -> None:
    metadata = parse_skill_metadata(_write_skill(tmp_path, ""))
    assert metadata["auto_execute"] is False


def test_auto_execute_must_be_a_boolean(tmp_path: Path) -> None:
    with pytest.raises(SkillValidationError):
        parse_skill_metadata(_write_skill(tmp_path, 'auto_execute: "yes"\n'))


def test_registration_has_one_path_and_finds_skills_the_old_manual_list_missed() -> None:
    from neos.skills.manager.skill_manager import SkillManager

    manager = SkillManager()
    manager.register_builtin_skills()
    names = {info.name for info in manager.registry.list_skills()}
    # 옛 수동 목록(6개)에는 없던 이름들이다 -- 개수가 아니라 이름으로 본다.
    assert {"openalex", "sec-edgar", "github-search", "reddit"} <= names


def test_available_skills_report_auto_execute() -> None:
    from neos.skills.manager.skill_manager import SkillManager

    manager = SkillManager()
    manager.register_builtin_skills()
    flags = {item["name"]: item["auto_execute"] for item in manager.get_available_skills()}
    assert flags["arxiv"] is True
    assert flags["cron"] is False
