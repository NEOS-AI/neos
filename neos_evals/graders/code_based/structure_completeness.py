"""Structure Completeness Grader - Validates report structure.

This grader checks:
1. Presence of expected sections
2. Section ordering and organization
3. Report length and depth
4. Proper formatting (headers, paragraphs)
"""

import re
from typing import Dict, Any, List, Set
import logging

from ..base import BaseGrader, GraderResult, GraderError

logger = logging.getLogger(__name__)


class StructureCompletenessGrader(BaseGrader):
    """Grades report structure and completeness.

    Evaluates:
    - All expected sections present
    - Logical section organization
    - Adequate content depth
    - Proper markdown formatting

    Example:
        ```python
        grader = StructureCompletenessGrader()
        result = await grader.grade(task, trial)

        print(f"Missing sections: {result.details['missing_sections']}")
        print(f"Section count: {result.details['total_sections']}")
        ```
    """

    # Minimum characters per section for "adequate" depth
    MIN_SECTION_LENGTH = 200

    def __init__(self):
        """Initialize structure completeness grader."""
        super().__init__(
            grader_id="structure_completeness",
            grader_type="code",
            weight=0.15,
            description="Validates report structure and organization"
        )

    async def grade(
        self,
        task: Any,  # EvalTask
        trial: Any,  # EvalTrial
    ) -> GraderResult:
        """Grade report structure.

        Args:
            task: Evaluation task with expected_sections
            trial: Trial with report content

        Returns:
            GraderResult with structure score
        """
        try:
            report = trial.final_report

            if not report:
                return GraderResult(
                    grader_id=self.grader_id,
                    score=0.0,
                    passed=False,
                    feedback="No report content to grade",
                    details={"error": "empty_report"}
                )

            # Extract sections from report
            actual_sections = self._extract_sections(report)

            # Check for expected sections
            coverage_analysis = self._analyze_coverage(
                actual_sections,
                task.expected_sections
            )

            # Analyze section depth
            depth_analysis = self._analyze_depth(actual_sections, report)

            # Calculate scores
            coverage_score = coverage_analysis["coverage_score"]
            depth_score = depth_analysis["depth_score"]
            formatting_score = self._analyze_formatting(report)

            # Overall score (weighted)
            overall_score = (
                coverage_score * 0.5 +
                depth_score * 0.3 +
                formatting_score * 0.2
            )

            # Pass criteria
            passed = (
                len(coverage_analysis["missing_sections"]) == 0 and
                depth_score >= 0.7
            )

            # Generate feedback
            feedback = self._generate_feedback(
                coverage_analysis,
                depth_analysis,
                formatting_score
            )

            return GraderResult(
                grader_id=self.grader_id,
                score=overall_score,
                passed=passed,
                feedback=feedback,
                details={
                    "total_sections": len(actual_sections),
                    "expected_sections": len(task.expected_sections),
                    "matched_sections": len(coverage_analysis["matched_sections"]),
                    "missing_sections": coverage_analysis["missing_sections"],
                    "extra_sections": coverage_analysis["extra_sections"],
                    "coverage_score": coverage_score,
                    "depth_score": depth_score,
                    "formatting_score": formatting_score,
                    "section_lengths": depth_analysis["section_lengths"],
                }
            )

        except Exception as e:
            logger.error(f"Structure grading failed: {e}", exc_info=True)
            raise GraderError(f"Structure grading failed: {e}")

    def _extract_sections(self, report: str) -> List[Dict[str, Any]]:
        """Extract sections from report.

        Args:
            report: Report text

        Returns:
            List of section dictionaries with title and content
        """
        sections = []

        # Match markdown headers (## or #)
        header_pattern = r'^(#{1,3})\s+(.+)$'
        lines = report.split('\n')

        current_section = None
        current_content = []

        for line in lines:
            header_match = re.match(header_pattern, line)

            if header_match:
                # Save previous section
                if current_section:
                    sections.append({
                        "title": current_section,
                        "content": '\n'.join(current_content).strip(),
                        "length": len('\n'.join(current_content))
                    })

                # Start new section
                current_section = header_match.group(2).strip()
                current_content = []
            else:
                current_content.append(line)

        # Add last section
        if current_section:
            sections.append({
                "title": current_section,
                "content": '\n'.join(current_content).strip(),
                "length": len('\n'.join(current_content))
            })

        return sections

    def _analyze_coverage(
        self,
        actual_sections: List[Dict[str, Any]],
        expected_sections: List[str]
    ) -> Dict[str, Any]:
        """Analyze section coverage.

        Args:
            actual_sections: Extracted sections
            expected_sections: Expected section titles

        Returns:
            Coverage analysis results
        """
        actual_titles = {s["title"].lower() for s in actual_sections}
        expected_titles = {e.lower() for e in expected_sections}

        # Find matches (fuzzy matching)
        matched_sections = []
        missing_sections = []

        for expected in expected_sections:
            if self._section_matches(expected, actual_sections):
                matched_sections.append(expected)
            else:
                missing_sections.append(expected)

        # Find extra sections (not in expected)
        extra_sections = []
        for section in actual_sections:
            if not any(self._fuzzy_match(section["title"], exp) for exp in expected_sections):
                extra_sections.append(section["title"])

        # Calculate coverage score
        if expected_sections:
            coverage_score = len(matched_sections) / len(expected_sections)
        else:
            coverage_score = 1.0

        return {
            "matched_sections": matched_sections,
            "missing_sections": missing_sections,
            "extra_sections": extra_sections,
            "coverage_score": coverage_score,
        }

    def _section_matches(
        self,
        expected: str,
        actual_sections: List[Dict[str, Any]]
    ) -> bool:
        """Check if expected section matches any actual section.

        Args:
            expected: Expected section title
            actual_sections: List of actual sections

        Returns:
            True if match found
        """
        for section in actual_sections:
            if self._fuzzy_match(expected, section["title"]):
                return True
        return False

    def _fuzzy_match(self, str1: str, str2: str) -> bool:
        """Fuzzy match two section titles.

        Args:
            str1: First string
            str2: Second string

        Returns:
            True if strings match (case-insensitive, ignoring punctuation)
        """
        # Normalize strings
        norm1 = re.sub(r'[^\w\s]', '', str1.lower())
        norm2 = re.sub(r'[^\w\s]', '', str2.lower())

        # Check for substring match or close match
        return (
            norm1 == norm2 or
            norm1 in norm2 or
            norm2 in norm1 or
            self._levenshtein_similar(norm1, norm2, threshold=0.8)
        )

    def _levenshtein_similar(self, str1: str, str2: str, threshold: float) -> bool:
        """Check if strings are similar using Levenshtein distance.

        Args:
            str1: First string
            str2: Second string
            threshold: Similarity threshold (0.0 to 1.0)

        Returns:
            True if similarity >= threshold
        """
        if not str1 or not str2:
            return False

        # Simple implementation
        max_len = max(len(str1), len(str2))
        distance = self._levenshtein_distance(str1, str2)
        similarity = 1 - (distance / max_len)

        return similarity >= threshold

    def _levenshtein_distance(self, str1: str, str2: str) -> int:
        """Calculate Levenshtein distance between two strings.

        Args:
            str1: First string
            str2: Second string

        Returns:
            Edit distance
        """
        if len(str1) < len(str2):
            return self._levenshtein_distance(str2, str1)

        if len(str2) == 0:
            return len(str1)

        previous_row = range(len(str2) + 1)

        for i, char1 in enumerate(str1):
            current_row = [i + 1]

            for j, char2 in enumerate(str2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (char1 != char2)
                current_row.append(min(insertions, deletions, substitutions))

            previous_row = current_row

        return previous_row[-1]

    def _analyze_depth(
        self,
        sections: List[Dict[str, Any]],
        report: str
    ) -> Dict[str, Any]:
        """Analyze content depth of sections.

        Args:
            sections: Extracted sections
            report: Full report text

        Returns:
            Depth analysis results
        """
        section_lengths = {s["title"]: s["length"] for s in sections}

        # Count sections with adequate depth
        adequate_sections = sum(
            1 for s in sections
            if s["length"] >= self.MIN_SECTION_LENGTH
        )

        # Calculate depth score
        if sections:
            depth_score = adequate_sections / len(sections)
        else:
            depth_score = 0.0

        # Bonus for overall report length
        if len(report) >= 5000:
            depth_score = min(depth_score + 0.1, 1.0)

        return {
            "section_lengths": section_lengths,
            "adequate_sections": adequate_sections,
            "total_sections": len(sections),
            "depth_score": depth_score,
        }

    def _analyze_formatting(self, report: str) -> float:
        """Analyze markdown formatting quality.

        Args:
            report: Report text

        Returns:
            Formatting score (0.0 to 1.0)
        """
        score = 0.0

        # Check for headers
        if re.search(r'^#{1,3}\s+', report, re.MULTILINE):
            score += 0.3

        # Check for paragraphs (blank lines between content)
        paragraphs = re.split(r'\n\s*\n', report)
        if len(paragraphs) >= 5:
            score += 0.3

        # Check for lists
        if re.search(r'^\s*[-*+]\s+', report, re.MULTILINE):
            score += 0.2

        # Check for emphasis (bold/italic)
        if re.search(r'\*\*.+?\*\*|__.+?__|\*.+?\*|_.+?_', report):
            score += 0.2

        return min(score, 1.0)

    def _generate_feedback(
        self,
        coverage_analysis: Dict[str, Any],
        depth_analysis: Dict[str, Any],
        formatting_score: float
    ) -> str:
        """Generate human-readable feedback.

        Args:
            coverage_analysis: Coverage analysis results
            depth_analysis: Depth analysis results
            formatting_score: Formatting score

        Returns:
            Feedback string
        """
        feedback_parts = []

        # Coverage feedback
        matched = len(coverage_analysis["matched_sections"])
        missing = coverage_analysis["missing_sections"]

        if not missing:
            feedback_parts.append(f"All {matched} expected sections present")
        else:
            feedback_parts.append(
                f"{matched}/{matched + len(missing)} expected sections present; "
                f"missing: {', '.join(missing[:3])}"
                f"{'...' if len(missing) > 3 else ''}"
            )

        # Depth feedback
        adequate = depth_analysis["adequate_sections"]
        total = depth_analysis["total_sections"]

        if adequate == total:
            feedback_parts.append("All sections have adequate depth")
        elif adequate / total >= 0.7:
            feedback_parts.append(f"Good depth: {adequate}/{total} sections")
        else:
            feedback_parts.append(
                f"Insufficient depth: only {adequate}/{total} sections "
                f"have adequate content"
            )

        # Formatting feedback
        if formatting_score >= 0.9:
            feedback_parts.append("Excellent formatting")
        elif formatting_score >= 0.7:
            feedback_parts.append("Good formatting")

        return "; ".join(feedback_parts)
