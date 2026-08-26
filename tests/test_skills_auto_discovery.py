"""Tests for skills auto-discovery"""

import pytest
from pathlib import Path
from neos.skills.manager.auto_discovery import (
    discover_skills,
    discover_single_skill,
    list_potential_skill_directories,
    validate_skill_directory,
)
from neos.skills.base import BaseSkill


class TestDiscoverSkills:
    """Test skill discovery"""

    def test_discover_builtin_skills(self):
        """Discover builtin skills"""
        builtin_dir = Path("neos/skills/builtin")
        if not builtin_dir.exists():
            pytest.skip("Builtin skills directory not found")

        discovered = discover_skills(builtin_dir, check_deps=False)

        # 최소한 몇 개의 스킬은 발견되어야 함
        assert len(discovered) > 0

        # 각 스킬이 SkillInfo 타입이어야 함
        for skill_info in discovered:
            assert hasattr(skill_info, "name")
            assert hasattr(skill_info, "skill_class")
            assert hasattr(skill_info, "skill_type")
            assert hasattr(skill_info, "capabilities")

        # PDF 스킬이 발견되어야 함
        skill_names = [s.name for s in discovered]
        assert "pdf" in skill_names

    def test_discover_nonexistent_directory(self):
        """Non-existent directory should return empty list"""
        fake_dir = Path("nonexistent/skills/directory")
        discovered = discover_skills(fake_dir, check_deps=False)
        assert discovered == []

    def test_discover_empty_directory(self, tmp_path):
        """Empty directory should return empty list"""
        discovered = discover_skills(tmp_path, check_deps=False)
        assert discovered == []

    def test_discover_with_invalid_skill(self, tmp_path):
        """Directory with invalid skill should skip it"""
        # 불완전한 스킬 디렉토리 생성
        invalid_skill_dir = tmp_path / "invalid_skill"
        invalid_skill_dir.mkdir()

        # SKILL.md만 있고 skill.py는 없음
        (invalid_skill_dir / "SKILL.md").write_text("""---
name: invalid
type: custom
description: Test
capabilities:
  - test
---
# Invalid Skill
""")

        discovered = discover_skills(tmp_path, check_deps=False)
        # 유효하지 않은 스킬은 스킵되어야 함
        assert len(discovered) == 0


class TestDiscoverSingleSkill:
    """Test single skill discovery"""

    def test_discover_pdf_skill(self):
        """Discover PDF skill"""
        pdf_skill_dir = Path("neos/skills/builtin/pdf")
        if not pdf_skill_dir.exists():
            pytest.skip("PDF skill directory not found")

        skill_info = discover_single_skill(pdf_skill_dir, check_deps=False)

        assert skill_info is not None
        assert skill_info.name == "pdf"
        assert skill_info.skill_type.value == "document"
        assert len(skill_info.capabilities) > 0
        assert issubclass(skill_info.skill_class, BaseSkill)

    def test_discover_skill_without_skillmd(self, tmp_path):
        """Skill without SKILL.md should return None"""
        skill_info = discover_single_skill(tmp_path, check_deps=False)
        assert skill_info is None

    def test_discover_skill_without_skillpy(self, tmp_path):
        """Skill without skill.py should return None"""
        # SKILL.md만 생성
        (tmp_path / "SKILL.md").write_text("""---
name: test
type: custom
description: Test
capabilities:
  - test
---
# Test
""")

        skill_info = discover_single_skill(tmp_path, check_deps=False)
        assert skill_info is None


class TestListPotentialSkillDirectories:
    """Test listing potential skill directories"""

    def test_list_builtin_directories(self):
        """List builtin skill directories"""
        builtin_dir = Path("neos/skills/builtin")
        if not builtin_dir.exists():
            pytest.skip("Builtin skills directory not found")

        potential_dirs = list_potential_skill_directories(builtin_dir)

        # 최소한 몇 개는 있어야 함
        assert len(potential_dirs) > 0

        # 각 디렉토리가 Path 타입이어야 함
        for dir_path in potential_dirs:
            assert isinstance(dir_path, Path)
            assert dir_path.is_dir()

    def test_list_empty_directory(self, tmp_path):
        """Empty directory should return empty list"""
        potential_dirs = list_potential_skill_directories(tmp_path)
        assert potential_dirs == []

    def test_list_nonexistent_directory(self):
        """Non-existent directory should return empty list"""
        fake_dir = Path("nonexistent/directory")
        potential_dirs = list_potential_skill_directories(fake_dir)
        assert potential_dirs == []


class TestValidateSkillDirectory:
    """Test skill directory validation"""

    def test_validate_pdf_skill(self):
        """PDF skill directory should be valid"""
        pdf_skill_dir = Path("neos/skills/builtin/pdf")
        if not pdf_skill_dir.exists():
            pytest.skip("PDF skill directory not found")

        is_valid, message = validate_skill_directory(pdf_skill_dir)

        assert is_valid is True
        assert "valid" in message.lower() or message == "Valid skill directory"

    def test_validate_nonexistent_directory(self):
        """Non-existent directory should be invalid"""
        fake_dir = Path("nonexistent/skill/dir")
        is_valid, message = validate_skill_directory(fake_dir)

        assert is_valid is False
        assert "not exist" in message.lower()

    def test_validate_directory_without_skillmd(self, tmp_path):
        """Directory without SKILL.md should be invalid"""
        is_valid, message = validate_skill_directory(tmp_path)

        assert is_valid is False
        assert "SKILL.md" in message

    def test_validate_directory_without_skillpy(self, tmp_path):
        """Directory without skill.py should be invalid"""
        # SKILL.md만 생성
        (tmp_path / "SKILL.md").write_text("""---
name: test
type: custom
description: Test
capabilities:
  - test
---
# Test
""")

        is_valid, message = validate_skill_directory(tmp_path)

        assert is_valid is False
        assert "skill.py" in message


class TestIntegration:
    """Integration tests"""

    def test_full_discovery_workflow(self):
        """Test complete discovery workflow"""
        builtin_dir = Path("neos/skills/builtin")
        if not builtin_dir.exists():
            pytest.skip("Builtin skills directory not found")

        # 1. List potential directories
        potential_dirs = list_potential_skill_directories(builtin_dir)
        assert len(potential_dirs) > 0

        # 2. Validate each directory
        valid_count = 0
        for skill_dir in potential_dirs:
            is_valid, _ = validate_skill_directory(skill_dir)
            if is_valid:
                valid_count += 1

        assert valid_count > 0

        # 3. Discover all skills
        discovered = discover_skills(builtin_dir, check_deps=False)
        assert len(discovered) == valid_count


class TestSkillNamingRule:
    """스킬 이름은 kebab-case로 통일한다.

    validator.validate_skill_name이 유니코드 문자 + 하이픈만 허용하고,
    디렉터리 이름이 스킬 이름과 일치할 것을 요구한다. 언더스코어를 쓰면
    auto_discovery에서 조용히 건너뛰어져 스킬이 영영 등록되지 않는다.
    """

    def test_builtin_skill_directories_use_kebab_case(self):
        builtin_dir = Path("neos/skills/builtin")
        if not builtin_dir.exists():
            pytest.skip("Builtin skills directory not found")

        offenders = [
            d.name
            for d in builtin_dir.iterdir()
            if d.is_dir() and not d.name.startswith("__") and "_" in d.name
        ]

        assert offenders == [], (
            f"kebab-case를 쓰지 않는 스킬 디렉터리: {offenders}. "
            "언더스코어는 validate_skill_name을 통과하지 못한다."
        )

    def test_every_builtin_skill_md_validates(self):
        from neos.skills.base.metadata_parser import parse_skill_metadata

        builtin_dir = Path("neos/skills/builtin")
        if not builtin_dir.exists():
            pytest.skip("Builtin skills directory not found")

        failures = {}
        for skill_dir in sorted(builtin_dir.iterdir()):
            if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
                continue
            try:
                parse_skill_metadata(skill_dir)
            except Exception as exc:  # noqa: BLE001 - 어떤 실패든 보고한다
                failures[skill_dir.name] = str(exc)

        assert failures == {}, f"검증에 실패하는 빌트인 스킬: {failures}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# --- 상대 import 를 쓰는 스킬 (2026-08-24) ------------------------------------
#
# `cron` 은 헬퍼 모듈(`parser.py`)을 가진 유일한 스킬이라 `from .parser import ...`
# 를 쓰는 유일한 스킬이기도 하다. `load_skill_class` 가 `skill.py` 를
# `spec_from_file_location` 으로 **독립 모듈** 로 로드하면 `__package__` 가 잡히지
# 않아 그 import 가 깨진다 -- `import neos.skills.builtin.cron.skill` 은 성공하는데
# discovery 경로에서만 실패한다.
#
# SKILL.md 를 여섯 개 추가했을 때 다섯만 등록되고 이것만 빠졌다. **카운트가 아니라
# 이름 집합으로 검증했기 때문에 잡혔다** -- 카운트는 "5개 늘었다" 만 말한다.

def _forget(module_name: str) -> None:
    """`sys.modules` 에서 모듈을 지운다.

    🔴 **이것이 없으면 테스트가 거짓으로 통과한다.** `load_skill_class` 는 "이미
    로드된 모듈이면 재사용" 분기를 갖고 있어서, 수집 중 다른 곳이 이 스킬을 정상
    import 해 두면 로더가 file-location 경로를 **아예 타지 않는다.** 프로덕션
    discovery 는 깨끗한 프로세스에서 도므로 그 분기를 반드시 지나간다."""

    import sys

    sys.modules.pop(module_name, None)


def test_a_skill_with_a_relative_import_is_discovered() -> None:
    """헬퍼 모듈을 상대 import 하는 스킬도 발견돼야 한다.

    `cron/skill.py` 의 `from .parser import ...` 는 정상적인 파이썬이다.
    그것을 다루지 못하는 쪽이 로더이므로, 스킬이 아니라 로더가 고쳐진다."""

    from pathlib import Path

    from neos.skills.manager.auto_discovery import discover_skills

    _forget("neos.skills.builtin.cron.skill")
    infos = discover_skills(Path("neos/skills/builtin"))
    names = {info.name for info in infos}
    assert "cron" in names, (
        "cron 이 발견되지 않았다 -- load_skill_class 가 상대 import 를 가진 "
        f"skill.py 를 로드하지 못한다. 발견된 것: {sorted(names)}"
    )


def test_discovering_a_relative_import_skill_does_not_drop_the_others() -> None:
    """§4.1 의 사고 재발 방지: 깨진 스킬 하나가 discovery 전체를 중단시킨 적이 있다.
    한 스킬을 살리는 변경이 나머지를 떨어뜨리지 않는지 이름으로 확인한다."""

    from pathlib import Path

    from neos.skills.manager.auto_discovery import discover_skills

    names = {info.name for info in discover_skills(Path("neos/skills/builtin"))}
    for expected in (
        "arxiv", "github-search", "google-scholar", "news-api",
        "openalex", "pubmed", "reddit", "sec-edgar",
        "semantic-scholar", "wikipedia",
    ):
        assert expected in names, f"{expected} 가 사라졌다: {sorted(names)}"
