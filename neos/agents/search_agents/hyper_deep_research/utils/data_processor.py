"""Data processing utilities for HyperDeepResearch.

This module provides helper functions for processing research data,
including deduplication, domain extraction, and text extraction.
"""

from typing import Dict, List, Any
from urllib.parse import urlparse


class DataProcessor:
    """Processes and transforms research data."""

    @staticmethod
    def deduplicate_sources(results: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Remove duplicate sources based on URL.

        Args:
            results: List of result lists containing source dictionaries

        Returns:
            List of unique sources
        """
        seen_urls = set()
        unique = []

        for result_list in results:
            # Validate result_list is a list
            if not isinstance(result_list, list):
                continue

            for item in result_list:
                # Validate item is a dictionary
                if not isinstance(item, dict):
                    continue

                url = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique.append(item)

        return unique

    @staticmethod
    def extract_domain(url: str) -> str:
        """Extract domain from URL.

        Args:
            url: Full URL string

        Returns:
            Domain name or 'unknown' if parsing fails
        """
        try:
            parsed = urlparse(url)
            return parsed.netloc
        except Exception:
            return "unknown"

    @staticmethod
    def extract_research_questions(text: str, max_questions: int = 15) -> List[str]:
        """Extract research questions from text.

        Args:
            text: Text containing research questions
            max_questions: Maximum number of questions to extract

        Returns:
            List of extracted research questions
        """
        questions = []
        lines = text.split('\n')

        question_indicators = ['?', 'what', 'why', 'how', 'when', 'where', 'who']

        for line in lines:
            line_lower = line.lower()
            if '?' in line or any(q in line_lower for q in question_indicators):
                clean = line.strip().lstrip('-•*123456789. ')
                if len(clean) > 10:
                    questions.append(clean)

        return questions[:max_questions]

    @staticmethod
    def extract_search_strategies(text: str) -> List[str]:
        """Extract search strategies from text.

        Args:
            text: Text containing search strategies

        Returns:
            List of extracted search strategies
        """
        strategies = []
        lines = text.split('\n')

        keywords = ['keyword', 'query', 'search', '검색', 'キーワード']

        for line in lines:
            if any(keyword in line.lower() for keyword in keywords):
                clean = line.strip().lstrip('-•*123456789. ')
                if len(clean) > 5:
                    strategies.append(clean)

        return strategies

    @staticmethod
    def extract_unique_domains(sources: List[Dict[str, Any]]) -> set:
        """Extract unique domains from sources.

        Args:
            sources: List of source dictionaries with 'url' key

        Returns:
            Set of unique domain names
        """
        domains = set()
        for source in sources:
            if "url" in source:
                domain = DataProcessor.extract_domain(source["url"])
                domains.add(domain)
        return domains
