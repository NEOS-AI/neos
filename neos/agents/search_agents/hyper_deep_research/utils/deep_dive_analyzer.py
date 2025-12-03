"""Recursive Deep Dive Analysis System.

Identifies important insights and recursively explores them in depth.
"""

from typing import Dict, Any, List, Callable
import logging


logger = logging.getLogger(__name__)


class DeepDiveAnalyzer:
    """Performs recursive deep dive on important insights."""

    def __init__(
        self,
        max_depth: int = 2,
        min_importance_score: float = 8.0,
        max_insights_per_level: int = 3,
    ):
        """Initialize deep dive analyzer.

        Args:
            max_depth: Maximum recursion depth
            min_importance_score: Minimum score (0-10) for deep dive
            max_insights_per_level: Maximum insights to explore per level
        """
        self.max_depth = max_depth
        self.min_importance_score = min_importance_score
        self.max_insights_per_level = max_insights_per_level

        self.stats = {
            "total_insights_identified": 0,
            "insights_explored": 0,
            "max_depth_reached": 0,
            "total_sources_collected": 0,
        }


    async def perform_deep_dive(
        self,
        analysis_text: str,
        original_query: str,
        search_function: Callable,
        llm_callable: Callable,
        session_id: str,
        user_id: str,
        language: str,
        current_depth: int = 0,
    ) -> Dict[str, Any]:
        """Perform recursive deep dive on analysis.

        Args:
            analysis_text: Text to analyze for insights
            original_query: Original research query
            search_function: Async function to perform searches
            llm_callable: Async LLM for analysis
            session_id: Session ID
            user_id: User ID
            language: Language code
            current_depth: Current recursion depth

        Returns:
            Deep dive results dictionary
        """
        if current_depth >= self.max_depth:
            logger.info(
                f"[DeepDive] Max depth {self.max_depth} reached, stopping recursion"
            )
            return {"insights": [], "explorations": []}

        try:
            logger.info(f"[DeepDive] Starting depth {current_depth + 1}/{self.max_depth}")

            # Step 1: Extract important insights
            insights = await self._extract_insights(
                analysis_text, original_query, llm_callable, language
            )

            self.stats["total_insights_identified"] += len(insights)
            logger.info(f"[DeepDive] Identified {len(insights)} potential insights")

            # Step 2: Filter by importance score
            important_insights = [
                i for i in insights
                if i.get("importance_score", 0) >= self.min_importance_score
            ]

            logger.info(
                f"[DeepDive] {len(important_insights)} insights meet importance threshold "
                f"(>= {self.min_importance_score})"
            )

            # Step 3: Limit number of insights to explore
            insights_to_explore = sorted(
                important_insights,
                key=lambda x: x.get("importance_score", 0),
                reverse=True
            )[:self.max_insights_per_level]

            # Step 4: Recursively explore each insight
            explorations = []
            for idx, insight in enumerate(insights_to_explore, 1):
                logger.info(
                    f"[DeepDive] Exploring insight {idx}/{len(insights_to_explore)}: "
                    f"{insight['summary'][:80]}..."
                )

                exploration = await self._explore_insight(
                    insight,
                    original_query,
                    search_function,
                    llm_callable,
                    session_id,
                    user_id,
                    language,
                    current_depth,
                )

                explorations.append(exploration)
                self.stats["insights_explored"] += 1

            # Update max depth reached
            self.stats["max_depth_reached"] = max(
                self.stats["max_depth_reached"], current_depth + 1
            )

            return {
                "depth": current_depth,
                "insights_identified": len(insights),
                "important_insights": len(important_insights),
                "insights_explored": len(insights_to_explore),
                "insights": insights_to_explore,
                "explorations": explorations,
            }

        except Exception as e:
            logger.error(f"[DeepDive] Error at depth {current_depth}: {e}")
            return {"insights": [], "explorations": [], "error": str(e)}

    async def _extract_insights(
        self,
        analysis_text: str,
        original_query: str,
        llm_callable: Callable,
        language: str,
    ) -> List[Dict[str, Any]]:
        """Extract important insights from analysis.

        Args:
            analysis_text: Text to analyze
            original_query: Original query
            llm_callable: LLM callable
            language: Language code

        Returns:
            List of insight dictionaries
        """
        try:
            # Build prompt based on language
            if language == "ko":
                prompt = f"""다음 분석 텍스트에서 더 깊이 탐구할 가치가 있는 중요한 인사이트를 식별하세요.

원래 질문: {original_query}

분석 내용:
{analysis_text[:3000]}

각 인사이트에 대해 다음 형식으로 작성하세요:
[중요도: 0-10점] 인사이트 요약

예시:
[9] 양자 컴퓨팅이 암호화에 미치는 영향
[8] AI 윤리 프레임워크의 국가별 차이
[7] 기후 변화가 농업 생산성에 미치는 복합적 영향

3-5개의 가장 중요한 인사이트만 선택하세요."""
            elif language == "ja":
                prompt = f"""以下の分析テキストから、さらに深く探求する価値のある重要な洞察を特定してください。

元の質問: {original_query}

分析内容:
{analysis_text[:3000]}

各洞察について次の形式で記述してください:
[重要度: 0-10点] 洞察の要約

例:
[9] 量子コンピューティングが暗号化に与える影響
[8] AI倫理フレームワークの国別の違い
[7] 気候変動が農業生産性に与える複合的影響

最も重要な洞察を3-5個だけ選択してください。"""
            else:  # English
                prompt = f"""Identify important insights from the following analysis that warrant deeper exploration.

Original Query: {original_query}

Analysis Content:
{analysis_text[:3000]}

For each insight, use this format:
[Importance: 0-10] Insight summary

Examples:
[9] Quantum computing's impact on cryptography
[8] Cross-country differences in AI ethics frameworks
[7] Complex effects of climate change on agricultural productivity

Select only the 3-5 most important insights."""

            from langchain_core.messages import HumanMessage
            response = await llm_callable([HumanMessage(content=prompt)])

            # Parse insights from response
            insights = []
            for line in response.content.strip().split('\n'):
                line = line.strip()
                if not line or len(line) < 10:
                    continue

                # Try to extract importance score and summary
                import re
                match = re.match(r'\[(\d+(?:\.\d+)?)\]\s*(.+)', line)
                if match:
                    score = float(match.group(1))
                    summary = match.group(2).strip()

                    insights.append({
                        "importance_score": score,
                        "summary": summary,
                        "source_text": line,
                    })

            return insights

        except Exception as e:
            logger.error(f"[DeepDive] Insight extraction error: {e}")
            return []

    async def _explore_insight(
        self,
        insight: Dict[str, Any],
        original_query: str,
        search_function: Callable,
        llm_callable: Callable,
        session_id: str,
        user_id: str,
        language: str,
        current_depth: int,
    ) -> Dict[str, Any]:
        """Explore a single insight in depth.

        Args:
            insight: Insight dictionary
            original_query: Original query
            search_function: Search function
            llm_callable: LLM callable
            session_id: Session ID
            user_id: User ID
            language: Language code
            current_depth: Current depth

        Returns:
            Exploration results
        """
        try:
            summary = insight["summary"]

            # Step 1: Generate targeted queries
            queries = await self._generate_deep_dive_queries(
                summary, original_query, llm_callable, language
            )

            logger.info(
                f"[DeepDive] Generated {len(queries)} queries for: {summary[:50]}..."
            )

            # Step 2: Execute searches
            search_results = []
            for query in queries[:10]:  # Limit to 10 queries
                try:
                    results = await search_function(query)
                    if results:
                        search_results.extend(results)
                except Exception as e:
                    logger.warning(f"[DeepDive] Search failed for '{query}': {e}")
                    continue

            self.stats["total_sources_collected"] += len(search_results)

            logger.info(
                f"[DeepDive] Collected {len(search_results)} sources for insight"
            )

            # Step 3: Analyze collected data
            sub_analysis = await self._analyze_deep_dive_data(
                summary, search_results, llm_callable, language
            )

            # Step 4: Recursive dive (if not at max depth)
            nested_exploration = None
            if current_depth + 1 < self.max_depth and sub_analysis:
                nested_exploration = await self.perform_deep_dive(
                    sub_analysis,
                    original_query,
                    search_function,
                    llm_callable,
                    session_id,
                    user_id,
                    language,
                    current_depth + 1,
                )

            return {
                "insight": insight,
                "queries_generated": len(queries),
                "sources_collected": len(search_results),
                "sub_analysis": sub_analysis,
                "nested_exploration": nested_exploration,
                "depth": current_depth + 1,
            }

        except Exception as e:
            logger.error(f"[DeepDive] Insight exploration error: {e}")
            return {
                "insight": insight,
                "error": str(e),
                "depth": current_depth + 1,
            }

    async def _generate_deep_dive_queries(
        self,
        insight_summary: str,
        original_query: str,
        llm_callable: Callable,
        language: str,
    ) -> List[str]:
        """Generate targeted queries for deep dive.

        Args:
            insight_summary: Insight to explore
            original_query: Original query
            llm_callable: LLM callable
            language: Language code

        Returns:
            List of search queries
        """
        try:
            if language == "ko":
                prompt = f"""다음 인사이트를 깊이 탐구하기 위한 검색 쿼리 5-10개를 생성하세요.

원래 질문: {original_query}
탐구할 인사이트: {insight_summary}

다양한 각도에서 접근하는 구체적인 검색 쿼리를 한 줄에 하나씩 작성하세요.
학술적, 실무적, 비판적 관점을 모두 포함하세요."""
            elif language == "ja":
                prompt = f"""次の洞察を深く探求するための検索クエリを5-10個生成してください。

元の質問: {original_query}
探求する洞察: {insight_summary}

さまざまな角度からアプローチする具体的な検索クエリを1行に1つずつ記述してください。
学術的、実務的、批判的な視点をすべて含めてください。"""
            else:  # English
                prompt = f"""Generate 5-10 search queries to deeply explore this insight.

Original Query: {original_query}
Insight to Explore: {insight_summary}

Create specific search queries approaching from different angles (academic, practical, critical perspectives).
One query per line."""

            from langchain_core.messages import HumanMessage
            response = await llm_callable([HumanMessage(content=prompt)])

            # Parse queries from response
            queries = [
                q.strip()
                for q in response.content.strip().split('\n')
                if q.strip() and len(q.strip()) > 10
            ]

            # Ensure we have at least one query
            if not queries:
                queries = [insight_summary]

            return queries[:10]  # Limit to 10

        except Exception as e:
            logger.error(f"[DeepDive] Query generation error: {e}")
            return [insight_summary]  # Fallback

    async def _analyze_deep_dive_data(
        self,
        insight_summary: str,
        sources: List[Dict[str, Any]],
        llm_callable: Callable,
        language: str,
    ) -> str:
        """Analyze collected data for deep dive.

        Args:
            insight_summary: Insight being explored
            sources: Collected sources
            llm_callable: LLM callable
            language: Language code

        Returns:
            Analysis text
        """
        try:
            if not sources:
                return ""

            # Sample sources for analysis
            sample_size = min(15, len(sources))
            sampled = sources[:sample_size]

            sources_text = "\n\n".join([
                f"Source {i+1}: {s.get('title', 'N/A')}\n{s.get('content', '')[:300]}"
                for i, s in enumerate(sampled)
            ])

            if language == "ko":
                prompt = f"""다음 인사이트에 대해 수집된 자료를 분석하세요:

인사이트: {insight_summary}

수집된 자료 ({len(sources)}개 중 {sample_size}개):
{sources_text}

주요 발견사항, 패턴, 그리고 추가 탐구가 필요한 영역을 포함한 심층 분석을 작성하세요."""
            elif language == "ja":
                prompt = f"""次の洞察について収集された資料を分析してください:

洞察: {insight_summary}

収集された資料 ({len(sources)}個中{sample_size}個):
{sources_text}

主な発見、パターン、そしてさらなる探求が必要な領域を含む詳細な分析を作成してください。"""
            else:  # English
                prompt = f"""Analyze the collected data for this insight:

Insight: {insight_summary}

Collected Sources ({sample_size} of {len(sources)}):
{sources_text}

Provide a deep analysis including key findings, patterns, and areas needing further exploration."""

            from langchain_core.messages import HumanMessage
            response = await llm_callable([HumanMessage(content=prompt)])

            return response.content.strip()

        except Exception as e:
            logger.error(f"[DeepDive] Data analysis error: {e}")
            return f"Analysis of {len(sources)} sources for: {insight_summary}"

    def get_stats(self) -> Dict[str, Any]:
        """Get deep dive statistics.

        Returns:
            Statistics dictionary
        """
        return {
            **self.stats,
            "exploration_rate": (
                self.stats["insights_explored"] / self.stats["total_insights_identified"] * 100
                if self.stats["total_insights_identified"] > 0 else 0
            ),
        }

    def synthesize_deep_dives(self, exploration_results: Dict[str, Any]) -> str:
        """Synthesize all deep dive explorations into summary.

        Args:
            exploration_results: Results from perform_deep_dive

        Returns:
            Synthesis text
        """
        try:
            explorations = exploration_results.get("explorations", [])
            if not explorations:
                return ""

            parts = ["## 🔬 Recursive Deep Dive Results\n"]

            for idx, exp in enumerate(explorations, 1):
                insight = exp.get("insight", {})
                summary = insight.get("summary", "Unknown")
                score = insight.get("importance_score", 0)
                sources = exp.get("sources_collected", 0)

                parts.append(
                    f"\n### Deep Dive {idx}: {summary}\n"
                    f"**Importance Score:** {score}/10\n"
                    f"**Sources Collected:** {sources}\n"
                )

                sub_analysis = exp.get("sub_analysis", "")
                if sub_analysis:
                    parts.append(f"\n{sub_analysis[:500]}...\n")

                # Include nested explorations
                nested = exp.get("nested_exploration")
                if nested and nested.get("explorations"):
                    parts.append(f"\n*Further nested exploration performed*\n")

            return "".join(parts)

        except Exception as e:
            logger.error(f"[DeepDive] Synthesis error: {e}")
            return "Deep dive synthesis pending"
