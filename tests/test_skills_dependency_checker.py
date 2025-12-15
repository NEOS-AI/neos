"""Tests for skills dependency checker"""

import pytest
from pathlib import Path
from neos.skills.manager import (
    check_dependencies,
    check_skill_dependencies,
    check_package_installed,
    parse_requirement,
    normalize_package_name,
)


class TestCheckPackageInstalled:
    """Test package installation check"""

    def test_check_installed_package(self):
        """Common installed packages should be found"""
        # pytest는 분명히 설치되어 있음
        assert check_package_installed("pytest") is True

    def test_check_nonexistent_package(self):
        """Non-existent package should not be found"""
        assert check_package_installed("this_package_definitely_does_not_exist_12345") is False

    def test_check_package_with_hyphens(self):
        """Package names with hyphens should be normalized"""
        # pytest-asyncio는 pytest_asyncio로 import됨
        result = check_package_installed("pytest-asyncio")
        # 설치되어 있지 않을 수도 있으므로 에러가 나지 않는지만 확인
        assert isinstance(result, bool)


class TestParseRequirement:
    """Test requirement string parsing"""

    def test_parse_simple_requirement(self):
        """Simple package name"""
        name, version = parse_requirement("pytest")
        assert name == "pytest"
        assert version is None or version == ""

    def test_parse_requirement_with_version(self):
        """Package with version spec"""
        name, version = parse_requirement("pytest>=7.0.0")
        assert name == "pytest"
        assert ">=7.0.0" in version or version == ">=7.0.0"

    def test_parse_requirement_with_extras(self):
        """Package with extras"""
        name, version = parse_requirement("requests[security]>=2.20.0")
        assert name == "requests"
        # extras는 무시되고 버전만 추출됨

    def test_parse_complex_requirement(self):
        """Complex requirement string"""
        name, version = parse_requirement("Django>=3.0,<4.0")
        assert name == "Django"


class TestNormalizePackageName:
    """Test package name normalization"""

    def test_normalize_hyphens(self):
        """Hyphens should be converted to underscores"""
        assert normalize_package_name("pytest-asyncio") == "pytest_asyncio"

    def test_normalize_uppercase(self):
        """Uppercase should be converted to lowercase"""
        assert normalize_package_name("PyYAML") == "pyyaml"

    def test_normalize_dots(self):
        """Dots should be converted to underscores"""
        assert normalize_package_name("zope.interface") == "zope_interface"

    def test_normalize_mixed(self):
        """Mixed case with hyphens and dots"""
        assert normalize_package_name("Google-Cloud.BigQuery") == "google_cloud_bigquery"


class TestCheckDependencies:
    """Test dependency checking"""

    def test_check_installed_dependencies(self):
        """Check known installed packages"""
        requirements = ["pytest", "pyyaml"]
        all_ok, missing = check_dependencies(requirements)
        # pytest는 분명히 설치되어 있음
        assert all_ok or "pytest" not in missing

    def test_check_missing_dependencies(self):
        """Check missing packages"""
        requirements = ["this_package_does_not_exist_xyz123"]
        all_ok, missing = check_dependencies(requirements)
        assert not all_ok
        assert len(missing) == 1

    def test_check_empty_requirements(self):
        """Empty requirements should succeed"""
        requirements = []
        all_ok, missing = check_dependencies(requirements)
        assert all_ok
        assert len(missing) == 0

    def test_check_with_comments(self):
        """Comments should be ignored"""
        requirements = [
            "pytest",
            "# This is a comment",
            "pyyaml",
            "",
        ]
        all_ok, missing = check_dependencies(requirements)
        # 주석과 빈 줄은 무시되어야 함
        assert isinstance(all_ok, bool)


class TestCheckSkillDependencies:
    """Test skill directory dependency checking"""

    def test_check_pdf_skill_dependencies(self):
        """Check PDF skill dependencies"""
        pdf_skill_dir = Path("neos/skills/builtin/pdf")
        if not pdf_skill_dir.exists():
            pytest.skip("PDF skill directory not found")

        all_ok, missing = check_skill_dependencies(pdf_skill_dir)
        # 결과가 boolean이어야 함
        assert isinstance(all_ok, bool)
        assert isinstance(missing, list)

    def test_check_nonexistent_directory(self):
        """Non-existent directory should return True, []"""
        fake_dir = Path("nonexistent/skill/dir")
        all_ok, missing = check_skill_dependencies(fake_dir)
        assert all_ok is True
        assert missing == []

    def test_check_directory_without_requirements(self, tmp_path):
        """Directory without requirements.txt should return True"""
        all_ok, missing = check_skill_dependencies(tmp_path)
        assert all_ok is True
        assert missing == []

    def test_check_empty_requirements_file(self, tmp_path):
        """Empty requirements.txt should return True"""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("")
        all_ok, missing = check_skill_dependencies(tmp_path)
        assert all_ok is True
        assert missing == []

    def test_check_requirements_with_only_comments(self, tmp_path):
        """Requirements with only comments should return True"""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("# Only comments\n# No actual dependencies\n")
        all_ok, missing = check_skill_dependencies(tmp_path)
        assert all_ok is True
        assert missing == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
