"""Topic complexity assessment for adaptive analysis depth.

Evaluates topic complexity to determine appropriate analysis iterations.
"""

from typing import Dict, Any, List
import re
import logging

logger = logging.getLogger(__name__)


class ComplexityAssessor:
    """Assesses topic complexity to adapt analysis depth."""

    # Domain-specific keywords indicating complexity
    TECHNICAL_DOMAINS = [
        "quantum", "neural", "algorithm", "cryptography", "genomics",
        "nanotechnology", "blockchain", "machine learning", "artificial intelligence",
        "biotechnology", "astrophysics", "thermodynamics", "topology",
    ]

    INTERDISCIPLINARY_KEYWORDS = [
        "interdisciplinary", "multidisciplinary", "cross-domain", "integrated",
        "systems", "ecosystem", "framework", "paradigm",
    ]

    COMPLEXITY_INDICATORS = [
        "complex", "complicated", "intricate", "sophisticated", "nuanced",
        "multifaceted", "comprehensive", "extensive", "in-depth",
    ]

    def __init__(self):
        """Initialize complexity assessor."""
        self.assessment_cache = {}

    async def assess_complexity(
        self,
        topic_analysis: Dict[str, Any],
        llm_callable: Any = None
    ) -> Dict[str, Any]:
        """Assess topic complexity and recommend analysis depth.

        Scoring (1-10):
        - 1-3: Simple (3 iterations)
        - 4-6: Moderate (5 iterations)
        - 7-8: Complex (7 iterations)
        - 9-10: Very Complex (10 iterations)

        Args:
            topic_analysis: Topic analysis dictionary
            llm_callable: Optional LLM for advanced assessment

        Returns:
            Assessment dictionary with score and recommendations
        """
        try:
            # Extract key information
            original_query = topic_analysis.get("original_query", "")
            full_analysis = topic_analysis.get("full_analysis", "")
            research_questions = topic_analysis.get("research_questions", [])

            # Calculate component scores
            question_complexity = self._assess_question_complexity(research_questions)
            domain_complexity = self._assess_domain_complexity(original_query, full_analysis)
            scope_complexity = self._assess_scope_complexity(full_analysis)
            perspective_complexity = self._assess_perspective_complexity(full_analysis)

            # Weighted combination
            total_score = (
                question_complexity * 0.30 +
                domain_complexity * 0.30 +
                scope_complexity * 0.20 +
                perspective_complexity * 0.20
            )

            # Normalize to 1-10
            final_score = min(max(total_score, 1), 10)

            # Determine iterations based on score
            iterations = self._score_to_iterations(final_score)

            # LLM-based refinement (if available)
            if llm_callable:
                llm_score = await self._llm_assessment(
                    original_query, full_analysis, llm_callable
                )
                if llm_score:
                    # Blend heuristic and LLM scores (70% heuristic, 30% LLM)
                    final_score = final_score * 0.7 + llm_score * 0.3
                    iterations = self._score_to_iterations(final_score)

            assessment = {
                "complexity_score": round(final_score, 2),
                "complexity_level": self._score_to_level(final_score),
                "recommended_iterations": iterations,
                "component_scores": {
                    "question_complexity": round(question_complexity, 2),
                    "domain_complexity": round(domain_complexity, 2),
                    "scope_complexity": round(scope_complexity, 2),
                    "perspective_complexity": round(perspective_complexity, 2),
                },
                "reasoning": self._generate_reasoning(final_score, research_questions),
            }

            logger.info(
                f"[ComplexityAssessor] Topic complexity: {assessment['complexity_level']} "
                f"(score: {final_score:.2f}, iterations: {iterations})"
            )

            return assessment

        except Exception as e:
            logger.error(f"[ComplexityAssessor] Assessment error: {e}")
            # Default to moderate complexity
            return {
                "complexity_score": 5.0,
                "complexity_level": "moderate",
                "recommended_iterations": 5,
                "component_scores": {},
                "reasoning": "Default assessment due to error",
            }

    def _assess_question_complexity(self, questions: List[str]) -> float:
        """Assess complexity based on research questions.

        Args:
            questions: List of research questions

        Returns:
            Score (1-10)
        """
        if not questions:
            return 3.0

        num_questions = len(questions)

        # Base score from number of questions
        if num_questions >= 10:
            score = 9.0
        elif num_questions >= 7:
            score = 7.0
        elif num_questions >= 5:
            score = 5.0
        elif num_questions >= 3:
            score = 4.0
        else:
            score = 3.0

        # Adjust for question diversity
        question_types = set()
        for q in questions:
            q_lower = q.lower()
            if any(word in q_lower for word in ["why", "how"]):
                question_types.add("causal")
            if any(word in q_lower for word in ["what", "which"]):
                question_types.add("descriptive")
            if any(word in q_lower for word in ["should", "would", "could"]):
                question_types.add("normative")
            if any(word in q_lower for word in ["compare", "contrast", "versus"]):
                question_types.add("comparative")

        # Bonus for diverse question types
        diversity_bonus = len(question_types) * 0.5

        return min(score + diversity_bonus, 10.0)

    def _assess_domain_complexity(self, query: str, analysis: str) -> float:
        """Assess domain complexity.

        Args:
            query: Original query
            analysis: Topic analysis text

        Returns:
            Score (1-10)
        """
        text = (query + " " + analysis).lower()
        score = 3.0  # Base score

        # Check for technical domains
        technical_count = sum(
            1 for keyword in self.TECHNICAL_DOMAINS
            if keyword in text
        )
        score += min(technical_count * 1.5, 4.0)

        # Check for interdisciplinary indicators
        interdisciplinary_count = sum(
            1 for keyword in self.INTERDISCIPLINARY_KEYWORDS
            if keyword in text
        )
        score += min(interdisciplinary_count * 1.0, 3.0)

        return min(score, 10.0)

    def _assess_scope_complexity(self, analysis: str) -> float:
        """Assess scope complexity from analysis text.

        Args:
            analysis: Topic analysis text

        Returns:
            Score (1-10)
        """
        score = 3.0
        text = analysis.lower()

        # Length indicator
        word_count = len(analysis.split())
        if word_count >= 1500:
            score += 3.0
        elif word_count >= 1000:
            score += 2.0
        elif word_count >= 500:
            score += 1.0

        # Complexity keywords
        complexity_count = sum(
            1 for keyword in self.COMPLEXITY_INDICATORS
            if keyword in text
        )
        score += min(complexity_count * 0.5, 2.0)

        # Scope indicators
        scope_keywords = [
            "global", "international", "worldwide", "comprehensive",
            "extensive", "broad", "wide-ranging", "multi-faceted"
        ]
        scope_count = sum(1 for kw in scope_keywords if kw in text)
        score += min(scope_count * 0.5, 2.0)

        return min(score, 10.0)

    def _assess_perspective_complexity(self, analysis: str) -> float:
        """Assess need for multiple perspectives.

        Args:
            analysis: Topic analysis text

        Returns:
            Score (1-10)
        """
        score = 3.0
        text = analysis.lower()

        # Perspective indicators
        perspective_keywords = [
            "perspective", "viewpoint", "angle", "dimension",
            "aspect", "facet", "lens", "framework", "approach"
        ]
        perspective_count = sum(1 for kw in perspective_keywords if kw in text)
        score += min(perspective_count * 1.0, 4.0)

        # Controversy/debate indicators
        controversy_keywords = [
            "debate", "controversy", "disagreement", "opposing",
            "conflicting", "disputed", "contentious", "polarizing"
        ]
        controversy_count = sum(1 for kw in controversy_keywords if kw in text)
        score += min(controversy_count * 1.5, 3.0)

        return min(score, 10.0)

    async def _llm_assessment(
        self,
        query: str,
        analysis: str,
        llm_callable: Any
    ) -> float:
        """Get LLM-based complexity assessment.

        Args:
            query: Original query
            analysis: Topic analysis
            llm_callable: Async LLM callable

        Returns:
            Complexity score (1-10) or None on error
        """
        try:
            prompt = f"""Assess the complexity of this research topic on a scale of 1-10.

Query: {query}

Analysis: {analysis[:1000]}

Consider:
1. Technical depth required
2. Number of domains involved
3. Breadth of scope
4. Need for multiple perspectives
5. Potential controversies or debates

Respond with ONLY a number from 1-10, no explanation.
"""
            from langchain_core.messages import HumanMessage
            response = await llm_callable([HumanMessage(content=prompt)])

            # Extract number from response
            score_match = re.search(r'(\d+(?:\.\d+)?)', response.content)
            if score_match:
                score = float(score_match.group(1))
                return min(max(score, 1), 10)

            return None

        except Exception as e:
            logger.warning(f"[ComplexityAssessor] LLM assessment failed: {e}")
            return None

    def _score_to_iterations(self, score: float) -> int:
        """Convert complexity score to iteration count.

        Args:
            score: Complexity score (1-10)

        Returns:
            Number of analysis iterations
        """
        if score >= 9:
            return 10
        elif score >= 7:
            return 7
        elif score >= 4:
            return 5
        else:
            return 3

    def _score_to_level(self, score: float) -> str:
        """Convert score to complexity level.

        Args:
            score: Complexity score (1-10)

        Returns:
            Complexity level string
        """
        if score >= 9:
            return "very_complex"
        elif score >= 7:
            return "complex"
        elif score >= 4:
            return "moderate"
        else:
            return "simple"

    def _generate_reasoning(self, score: float, questions: List[str]) -> str:
        """Generate reasoning for complexity assessment.

        Args:
            score: Final complexity score
            questions: Research questions

        Returns:
            Reasoning text
        """
        level = self._score_to_level(score)
        iterations = self._score_to_iterations(score)

        reasoning_map = {
            "simple": f"Simple topic with {len(questions)} research questions. "
                     f"Standard analysis depth ({iterations} iterations) is sufficient.",
            "moderate": f"Moderate complexity with {len(questions)} research questions. "
                       f"Requires balanced analysis ({iterations} iterations).",
            "complex": f"Complex topic with {len(questions)} diverse research questions. "
                      f"Requires deep analysis ({iterations} iterations) to cover all aspects.",
            "very_complex": f"Highly complex topic with {len(questions)} multifaceted questions. "
                           f"Requires extensive analysis ({iterations} iterations) for thorough coverage.",
        }

        return reasoning_map.get(level, "Assessment pending")
