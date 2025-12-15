"""Tests for skills metadata parser"""

import pytest
from pathlib import Path
from neos.skills.base import (
    parse_skill_metadata,
    validate_metadata,
    extract_frontmatter,
    SkillMetadataError,
)


class TestExtractFrontmatter:
    """Test frontmatter extraction"""

    def test_extract_valid_frontmatter(self):
        """Valid YAML frontmatter should be extracted"""
        content = """---
name: test_skill
type: custom
---

# Test Skill
"""
        result = extract_frontmatter(content)
        assert result is not None
        assert "name: test_skill" in result
        assert "type: custom" in result

    def test_extract_no_frontmatter(self):
        """Content without frontmatter should return None"""
        content = "# Test Skill\n\nNo frontmatter here"
        result = extract_frontmatter(content)
        assert result is None

    def test_extract_invalid_frontmatter(self):
        """Frontmatter not at start should return None"""
        content = """
Some text before

---
name: test_skill
---
"""
        result = extract_frontmatter(content)
        assert result is None


class TestValidateMetadata:
    """Test metadata validation"""

    def test_validate_complete_metadata(self):
        """Complete metadata should pass validation"""
        metadata = {
            "name": "test_skill",
            "type": "custom",
            "description": "Test description",
            "capabilities": ["cap1", "cap2"],
            "version": "1.0.0",
            "dependencies": ["package1>=1.0.0"],
        }
        assert validate_metadata(metadata) is True

    def test_validate_minimal_metadata(self):
        """Minimal required metadata should pass"""
        metadata = {
            "name": "test_skill",
            "type": "custom",
            "description": "Test description",
            "capabilities": ["cap1"],
        }
        assert validate_metadata(metadata) is True

    def test_validate_missing_name(self):
        """Missing name should raise error"""
        metadata = {
            "type": "custom",
            "description": "Test",
            "capabilities": ["cap1"],
        }
        with pytest.raises(SkillMetadataError, match="Required field 'name' missing"):
            validate_metadata(metadata)

    def test_validate_empty_name(self):
        """Empty name should raise error"""
        metadata = {
            "name": "",
            "type": "custom",
            "description": "Test",
            "capabilities": ["cap1"],
        }
        with pytest.raises(SkillMetadataError, match="Field 'name' cannot be empty"):
            validate_metadata(metadata)

    def test_validate_invalid_type(self):
        """Invalid type should raise error"""
        metadata = {
            "name": "test",
            "type": "invalid_type",
            "description": "Test",
            "capabilities": ["cap1"],
        }
        with pytest.raises(SkillMetadataError, match="Field 'type' must be one of"):
            validate_metadata(metadata)

    def test_validate_empty_capabilities(self):
        """Empty capabilities should raise error"""
        metadata = {
            "name": "test",
            "type": "custom",
            "description": "Test",
            "capabilities": [],
        }
        with pytest.raises(SkillMetadataError, match="Field 'capabilities' cannot be empty"):
            validate_metadata(metadata)

    def test_validate_invalid_capability_type(self):
        """Non-string capabilities should raise error"""
        metadata = {
            "name": "test",
            "type": "custom",
            "description": "Test",
            "capabilities": ["cap1", 123],
        }
        with pytest.raises(SkillMetadataError, match="All capabilities must be strings"):
            validate_metadata(metadata)


class TestParseSkillMetadata:
    """Test skill metadata parsing"""

    def test_parse_pdf_skill_metadata(self):
        """Parse PDF skill metadata"""
        pdf_skill_dir = Path("neos/skills/builtin/pdf")
        if not pdf_skill_dir.exists():
            pytest.skip("PDF skill directory not found")

        metadata = parse_skill_metadata(pdf_skill_dir)

        assert metadata["name"] == "pdf"
        assert metadata["type"] == "document"
        assert metadata["version"] == "1.0.0"
        assert "document_reading" in metadata["capabilities"]
        assert len(metadata["dependencies"]) > 0

    def test_parse_nonexistent_directory(self):
        """Parsing non-existent directory should raise error"""
        fake_dir = Path("nonexistent/skill/dir")
        with pytest.raises(SkillMetadataError, match="SKILL.md not found"):
            parse_skill_metadata(fake_dir)

    def test_parse_directory_without_skillmd(self, tmp_path):
        """Directory without SKILL.md should raise error"""
        with pytest.raises(SkillMetadataError, match="SKILL.md not found"):
            parse_skill_metadata(tmp_path)

    def test_parse_invalid_yaml(self, tmp_path):
        """Invalid YAML should raise error"""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("""---
name: test
type: custom
description: Test
capabilities:
  - cap1
invalid yaml here: [[[
---
""")
        with pytest.raises(SkillMetadataError, match="Invalid YAML"):
            parse_skill_metadata(tmp_path)

    def test_parse_missing_frontmatter(self, tmp_path):
        """Missing frontmatter should raise error"""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("# Test Skill\n\nNo frontmatter")
        with pytest.raises(SkillMetadataError, match="No YAML frontmatter found"):
            parse_skill_metadata(tmp_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
