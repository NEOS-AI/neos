"""Unit tests for EvaluationPrompts module.

This test suite covers language-specific evaluation prompts for section quality assessment.

Tests:
1. Korean (ko) prompt structure and content
2. English (en) prompt structure and content
3. Japanese (ja) prompt structure and content
4. Fallback behavior for unsupported languages
5. Content inclusion and truncation
"""

import pytest

from neos.agents.search_agents.hyper_deep_research.prompts import EvaluationPrompts


# ============================================================================
# Korean Prompt Tests
# ============================================================================

class TestKoreanPrompts:
    """Test Korean (ko) evaluation prompts."""

    def test_korean_prompt_structure(self):
        """Test that Korean prompt contains expected Korean text."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="테스트 섹션",
            content="테스트 내용입니다.",
            language="ko"
        )

        # Should contain Korean text
        assert "일관성" in prompt  # Coherence
        assert "완성도" in prompt  # Completeness
        assert "명료성" in prompt  # Clarity

        # Should contain section title and content
        assert "테스트 섹션" in prompt
        assert "테스트 내용입니다." in prompt

    def test_korean_prompt_criteria(self):
        """Test that Korean prompt contains evaluation criteria."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Introduction",
            content="Content",
            language="ko"
        )

        # Should contain scoring tiers
        assert "0.9-1.0" in prompt
        assert "0.7-0.8" in prompt
        assert "0.5-0.6" in prompt
        assert "0.0-0.4" in prompt

        # Should contain evaluation dimensions
        assert "Coherence" in prompt or "일관성" in prompt
        assert "Completeness" in prompt or "완성도" in prompt
        assert "Clarity" in prompt or "명료성" in prompt

    def test_korean_prompt_examples(self):
        """Test that Korean prompt contains examples."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content="Content",
            language="ko"
        )

        # Should contain low and high quality examples
        assert "낮은 품질" in prompt or "Low quality" in prompt
        assert "높은 품질" in prompt or "High quality" in prompt

        # Should mention AI as example topic
        assert "AI" in prompt or "인공지능" in prompt

    def test_korean_prompt_output_format(self):
        """Test that Korean prompt specifies output format."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content="Content",
            language="ko"
        )

        # Should specify exact output format
        assert "coherence:" in prompt
        assert "completeness:" in prompt
        assert "clarity:" in prompt
        assert "X.XX" in prompt


# ============================================================================
# English Prompt Tests
# ============================================================================

class TestEnglishPrompts:
    """Test English (en) evaluation prompts."""

    def test_english_prompt_structure(self):
        """Test that English prompt contains expected English text."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test Section",
            content="Test content here.",
            language="en"
        )

        # Should contain English text
        assert "Coherence" in prompt
        assert "Completeness" in prompt
        assert "Clarity" in prompt

        # Should contain section title and content
        assert "Test Section" in prompt
        assert "Test content here." in prompt

    def test_english_prompt_criteria(self):
        """Test that English prompt contains evaluation criteria."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Introduction",
            content="Content",
            language="en"
        )

        # Should contain scoring tiers
        assert "0.9-1.0" in prompt
        assert "0.7-0.8" in prompt

        # Should contain descriptions
        assert "Logical flow" in prompt or "logical" in prompt.lower()
        assert "seamless" in prompt.lower() or "flow" in prompt.lower()

    def test_english_prompt_examples(self):
        """Test that English prompt contains examples."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content="Content",
            language="en"
        )

        # Should contain quality examples
        assert "Low quality" in prompt or "low quality" in prompt.lower()
        assert "High quality" in prompt or "high quality" in prompt.lower()

        # Should have AI business example
        assert "AI" in prompt or "artificial intelligence" in prompt.lower()
        assert "business" in prompt.lower() or "companies" in prompt.lower()

    def test_english_prompt_output_format(self):
        """Test that English prompt specifies output format."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content="Content",
            language="en"
        )

        # Should specify exact output format
        assert "coherence:" in prompt
        assert "completeness:" in prompt
        assert "clarity:" in prompt
        assert "0.85" in prompt or "X.XX" in prompt


# ============================================================================
# Japanese Prompt Tests
# ============================================================================

class TestJapanesePrompts:
    """Test Japanese (ja) evaluation prompts."""

    def test_japanese_prompt_structure(self):
        """Test that Japanese prompt contains expected Japanese text."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="テストセクション",
            content="テストコンテンツ。",
            language="ja"
        )

        # Should contain Japanese text
        assert "一貫性" in prompt  # Coherence
        assert "完全性" in prompt  # Completeness
        assert "明瞭性" in prompt  # Clarity

        # Should contain section title and content
        assert "テストセクション" in prompt
        assert "テストコンテンツ。" in prompt

    def test_japanese_prompt_criteria(self):
        """Test that Japanese prompt contains evaluation criteria."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Introduction",
            content="Content",
            language="ja"
        )

        # Should contain scoring tiers
        assert "0.9-1.0" in prompt
        assert "0.7-0.8" in prompt

        # Should contain Japanese criteria descriptions
        assert "論理的" in prompt or "ロジカル" in prompt

    def test_japanese_prompt_examples(self):
        """Test that Japanese prompt contains examples."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content="Content",
            language="ja"
        )

        # Should contain quality examples
        assert "低品質" in prompt or "低い品質" in prompt
        assert "高品質" in prompt or "高い品質" in prompt

    def test_japanese_prompt_output_format(self):
        """Test that Japanese prompt specifies output format."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content="Content",
            language="ja"
        )

        # Should specify exact output format (same as English)
        assert "coherence:" in prompt
        assert "completeness:" in prompt
        assert "clarity:" in prompt


# ============================================================================
# Fallback and Edge Cases
# ============================================================================

class TestPromptFallback:
    """Test fallback behavior and edge cases."""

    def test_unsupported_language_fallback(self):
        """Test that unsupported language falls back to English."""
        english_prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content="Content",
            language="en"
        )

        # Unsupported language (e.g., French)
        fallback_prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content="Content",
            language="fr"
        )

        # Should fall back to English prompt
        assert fallback_prompt == english_prompt

    def test_empty_language_fallback(self):
        """Test fallback when language is empty string."""
        english_prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content="Content",
            language="en"
        )

        fallback_prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content="Content",
            language=""
        )

        # Should fall back to English
        assert fallback_prompt == english_prompt

    def test_content_truncation(self):
        """Test that long content is truncated to 4000 characters."""
        # Create very long content (6000 characters)
        long_content = "A" * 6000

        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content=long_content,
            language="en"
        )

        # Should only include first 4000 characters
        # Count occurrences of "A" in prompt
        a_count = prompt.count("A")
        assert a_count == 4000

        # Should not contain all 6000 characters
        assert long_content not in prompt

    def test_content_short_not_truncated(self):
        """Test that short content is not truncated."""
        short_content = "This is short content."

        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content=short_content,
            language="en"
        )

        # Should contain full content
        assert short_content in prompt

    def test_special_characters_in_content(self):
        """Test handling of special characters in content."""
        special_content = 'Content with "quotes", <html>, and [brackets] & symbols!'

        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content=special_content,
            language="en"
        )

        # Should include content with special characters
        assert 'quotes' in prompt
        assert 'brackets' in prompt
        assert 'symbols' in prompt

    def test_special_characters_in_title(self):
        """Test handling of special characters in section title."""
        special_title = 'Section: "Test" <Part 1> [Draft]'

        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title=special_title,
            content="Content",
            language="en"
        )

        # Should include title with special characters
        assert 'Section:' in prompt or 'Test' in prompt

    def test_empty_content(self):
        """Test handling of empty content."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="Test",
            content="",
            language="en"
        )

        # Should still return valid prompt
        assert "Coherence" in prompt
        assert "Completeness" in prompt
        assert "Clarity" in prompt

    def test_empty_title(self):
        """Test handling of empty title."""
        prompt = EvaluationPrompts.get_quality_evaluation_prompt(
            section_title="",
            content="Content",
            language="en"
        )

        # Should still return valid prompt
        assert "Coherence" in prompt
        assert "Content" in prompt


# ============================================================================
# Cross-language Consistency Tests
# ============================================================================

class TestCrossLanguageConsistency:
    """Test consistency across different language prompts."""

    def test_all_languages_have_output_format(self):
        """Test that all languages specify the same output format."""
        for language in ["ko", "en", "ja"]:
            prompt = EvaluationPrompts.get_quality_evaluation_prompt(
                section_title="Test",
                content="Content",
                language=language
            )

            # All should specify same output format
            assert "coherence:" in prompt
            assert "completeness:" in prompt
            assert "clarity:" in prompt

    def test_all_languages_have_scoring_tiers(self):
        """Test that all languages have 4-tier scoring system."""
        for language in ["ko", "en", "ja"]:
            prompt = EvaluationPrompts.get_quality_evaluation_prompt(
                section_title="Test",
                content="Content",
                language=language
            )

            # All should have 4 scoring tiers
            assert "0.9-1.0" in prompt
            assert "0.7-0.8" in prompt
            assert "0.5-0.6" in prompt
            assert "0.0-0.4" in prompt

    def test_all_languages_have_examples(self):
        """Test that all languages provide quality examples."""
        for language in ["ko", "en", "ja"]:
            prompt = EvaluationPrompts.get_quality_evaluation_prompt(
                section_title="Test",
                content="Content",
                language=language
            )

            # Each language should have examples
            # Check for numbers that appear in example scores
            assert "0.4" in prompt or "0.3" in prompt  # Low quality scores
            assert "0.9" in prompt or "0.95" in prompt  # High quality scores

    def test_all_languages_include_content(self):
        """Test that all languages include the provided content."""
        test_content = "Unique test content 12345"

        for language in ["ko", "en", "ja"]:
            prompt = EvaluationPrompts.get_quality_evaluation_prompt(
                section_title="Test",
                content=test_content,
                language=language
            )

            # All should include the content
            assert test_content in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
