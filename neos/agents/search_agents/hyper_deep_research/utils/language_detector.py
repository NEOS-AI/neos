"""Language detection utility for HyperDeepResearch.

This module provides language detection functionality to determine the language
of user queries and ensure responses are generated in the same language.
"""

import re
from typing import Literal

LanguageCode = Literal["en", "ko", "ja"]


class LanguageDetector:
    """Detects the language of text input.

    Supports detection of:
    - English (en)
    - Korean (ko)
    - Japanese (ja)
    - Chinese (detected but defaults to English prompts)
    """

    # Language detection thresholds
    KOREAN_THRESHOLD = 0.3
    CJK_THRESHOLD = 0.5
    ENGLISH_THRESHOLD = 0.5

    @staticmethod
    def detect(text: str) -> LanguageCode:
        """Detect the language of the given text.

        Args:
            text: Input text to analyze

        Returns:
            Language code: 'en', 'ko', or 'ja'

        Algorithm:
            1. Korean: If Korean characters > 30% of total
            2. Japanese: If hiragana or katakana present
            3. Chinese: If CJK characters > 50% (returns 'en')
            4. English: If English characters > 50%
            5. Default: 'en'
        """
        if not text or not text.strip():
            return "en"

        # Count characters by type
        korean_chars = len(re.findall(r'[가-힣]', text))
        hiragana_chars = len(re.findall(r'[ぁ-ん]', text))
        katakana_chars = len(re.findall(r'[ァ-ヶー]', text))
        cjk_chars = len(re.findall(r'[一-龯]', text))
        english_chars = len(re.findall(r'[a-zA-Z]', text))

        total_chars = len(re.findall(r'\S', text))

        if total_chars == 0:
            return "en"

        # Priority: Korean > Japanese (kana) > Chinese (CJK only) > English

        # Korean detection
        if korean_chars / total_chars > LanguageDetector.KOREAN_THRESHOLD:
            return "ko"

        # Japanese detection (hiragana/katakana is distinctive)
        if hiragana_chars > 0 or katakana_chars > 0:
            return "ja"

        # Chinese detection (CJK without kana, use English prompts)
        if cjk_chars / total_chars > LanguageDetector.CJK_THRESHOLD:
            return "en"

        # English detection
        if english_chars / total_chars > LanguageDetector.ENGLISH_THRESHOLD:
            return "en"

        # Default to English
        return "en"

    @staticmethod
    def get_language_name(code: LanguageCode) -> str:
        """Get the full language name from code.

        Args:
            code: Language code ('en', 'ko', 'ja')

        Returns:
            Full language name
        """
        language_names = {
            "en": "English",
            "ko": "Korean",
            "ja": "Japanese"
        }
        return language_names.get(code, "English")
