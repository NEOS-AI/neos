"""Analysis Module for HyperDeepResearch.

This module handles analysis operations including:
- Topic analysis
- Research planning
- Deep analysis (iterative rounds)
- Gap analysis
- Cross-validation
- Critical analysis
"""

from typing import Dict, Any, List, Optional
import asyncio
import logging

from langchain_core.messages import HumanMessage

from neos.config.settings import settings
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm, extract_text_from_response

from .prompts import (
    TopicAnalysisPrompts,
    ResearchPlanningPrompts,
    AnalysisPrompts,
    ValidationPrompts,
)
from .utils import DataProcessor


logger = logging.getLogger(__name__)


class TopicAnalyzer:
    """Handles topic analysis operations."""
    
    def __init__(self, agent_name: str = "hyper_deep_research"):
        """Initialize topic analyzer.
        
        Args:
            agent_name: Name of the agent for tracking
        """
        self.agent_name = agent_name
    
    async def analyze_topic(
        self,
        query: str,
        session_id: str,
        user_id: str,
        language: str,
        event_logger: Optional[Any] = None,
        llm_tracker: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Analyze topic from multiple dimensions.
        
        Args:
            query: Research query
            session_id: Session identifier
            user_id: User identifier
            language: Language code
            event_logger: Optional event logger
            llm_tracker: Optional LLM usage tracker callback
            
        Returns:
            Topic analysis result
        """
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["topic_analysis"]
            )

            if event_logger:
                await event_logger.log_llm_call(
                    "topic_analysis",
                    "Analyzing topic from multiple dimensions",
                    estimated_tokens=3000
                )

            prompt = TopicAnalysisPrompts.get_prompt(query, language)
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            analysis_text = extract_text_from_response(response).strip()

            # Track LLM usage
            if llm_tracker:
                llm_tracker("topic_analysis", prompt, analysis_text)

            if event_logger:
                await event_logger.log_llm_complete(
                    "topic_analysis",
                    "Topic analysis completed",
                    actual_tokens=len(analysis_text)
                )

            return {
                "full_analysis": analysis_text,
                "research_questions": DataProcessor.extract_research_questions(analysis_text),
                "original_query": query
            }
            
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logger.error(
                f"Topic analysis timeout/cancelled after {settings.LLM_TIMEOUT}s: {e}. "
                f"Consider increasing LLM_TIMEOUT environment variable."
            )
            raise
        except Exception as e:
            error_msg = str(e)
            if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
                logger.error(
                    f"Topic analysis error (timeout): {e}. "
                    f"Current timeout: {settings.LLM_TIMEOUT}s. "
                    f"Consider increasing LLM_TIMEOUT environment variable."
                )
            else:
                logger.error(f"Topic analysis error: {e}")
            return {
                "full_analysis": f"Topic: {query}\n\nAnalysis pending.",
                "research_questions": [query],
                "original_query": query
            }


class ResearchPlanner:
    """Handles research planning operations."""
    
    def __init__(self, agent_name: str = "hyper_deep_research"):
        """Initialize research planner.
        
        Args:
            agent_name: Name of the agent for tracking
        """
        self.agent_name = agent_name
    
    async def plan_research(
        self,
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
        llm_tracker: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Create comprehensive research plan.

        Args:
            topic_analysis: Topic analysis result
            session_id: Session identifier
            user_id: User identifier
            language: Language code
            llm_tracker: Optional LLM usage tracker callback

        Returns:
            Research plan
        """
        try:
            # Use longer timeout for research planning operations
            llm = create_tracked_llm(
                llm=create_llm(
                    temperature=0.3,
                    max_tokens=8000,
                    timeout=settings.LLM_TIMEOUT_RESEARCH_PLANNING
                ),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["research_planning"]
            )

            prompt = ResearchPlanningPrompts.get_prompt(
                topic_analysis['full_analysis'], language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            plan_text = extract_text_from_response(response).strip()

            if llm_tracker:
                llm_tracker("research_planning", prompt, plan_text)

            return {
                "full_plan": plan_text,
                "search_strategies": DataProcessor.extract_search_strategies(plan_text)
            }

        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logger.error(
                f"Research planning timeout/cancelled after {settings.LLM_TIMEOUT_RESEARCH_PLANNING}s: {e}. "
                f"Consider increasing LLM_TIMEOUT_RESEARCH_PLANNING environment variable."
            )
            raise
        except Exception as e:
            error_msg = str(e)
            if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
                logger.error(
                    f"Research planning error (timeout): {e}. "
                    f"Current timeout: {settings.LLM_TIMEOUT_RESEARCH_PLANNING}s. "
                    f"Consider increasing LLM_TIMEOUT_RESEARCH_PLANNING environment variable."
                )
            else:
                logger.error(f"Research planning error: {e}")
            return {"full_plan": "Research plan pending", "search_strategies": []}


class DeepAnalyzer:
    """Handles deep analysis operations."""
    
    def __init__(
        self,
        agent_name: str = "hyper_deep_research",
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize deep analyzer.
        
        Args:
            agent_name: Name of the agent for tracking
            config: Optional configuration dictionary
        """
        self.agent_name = agent_name
        self.config = config or {"analysis_iterations": 3}
    
    async def perform_deep_analysis(
        self,
        topic_analysis: Dict[str, Any],
        initial_data: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
        metadata_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform iterative deep analysis.
        
        Args:
            topic_analysis: Topic analysis result
            initial_data: Initial data collection result
            session_id: Session identifier
            user_id: User identifier
            language: Language code
            metadata_tracker: Optional metadata dictionary to update
            
        Returns:
            Deep analysis result
        """
        analysis_rounds = []

        for round_num in range(self.config["analysis_iterations"]):
            print(f"[INFO] 🔬 Analysis Round {round_num + 1}/{self.config['analysis_iterations']}")

            previous_insights = (
                "\n\n".join([r["insights"] for r in analysis_rounds])
                if analysis_rounds
                else ""
            )

            round_analysis = await self._execute_analysis_round(
                round_num + 1, topic_analysis, initial_data,
                previous_insights, session_id, user_id, language
            )

            analysis_rounds.append(round_analysis)
            
            if metadata_tracker is not None:
                metadata_tracker["analysis_iterations_completed"] = (
                    metadata_tracker.get("analysis_iterations_completed", 0) + 1
                )

        # Synthesize all rounds
        synthesis = await self._synthesize_analysis_rounds(
            analysis_rounds, session_id, user_id, language
        )

        return {"rounds": analysis_rounds, "synthesis": synthesis}
    
    async def _execute_analysis_round(
        self,
        round_num: int,
        topic_analysis: Dict[str, Any],
        initial_data: Dict[str, Any],
        previous_insights: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> Dict[str, Any]:
        """Execute single analysis round."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=[f"analysis_round_{round_num}"]
            )

            prompt = AnalysisPrompts.get_iterative_analysis_prompt(
                round_num, topic_analysis['original_query'],
                initial_data['summary'], previous_insights, language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            return {"round": round_num, "insights": extract_text_from_response(response).strip()}

        except Exception as e:
            logger.error(f"Analysis round {round_num} failed: {e}")
            return {"round": round_num, "insights": f"Round {round_num} pending"}
    
    async def _synthesize_analysis_rounds(
        self,
        rounds: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str,
    ) -> str:
        """Synthesize all analysis rounds."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["analysis_synthesis"]
            )

            rounds_text = "\n\n".join([
                f"Round {r['round']}:\n{r['insights'][:800]}"
                for r in rounds
            ])

            prompt = AnalysisPrompts.get_synthesis_prompt(
                len(rounds), rounds_text, language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return extract_text_from_response(response).strip()

        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return "Analysis synthesis pending"


class GapAnalyzer:
    """Handles gap analysis and additional research."""
    
    def __init__(
        self,
        agent_name: str = "hyper_deep_research",
        data_collector: Optional[Any] = None,
    ):
        """Initialize gap analyzer.
        
        Args:
            agent_name: Name of the agent for tracking
            data_collector: Optional data collector for gap research
        """
        self.agent_name = agent_name
        self.data_collector = data_collector
    
    async def identify_knowledge_gaps(
        self,
        topic_analysis: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
    ) -> List[str]:
        """Identify knowledge gaps."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["gap_identification"]
            )

            prompt = AnalysisPrompts.get_gap_identification_prompt(
                topic_analysis['research_questions'],
                deep_analysis['synthesis'],
                language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            gaps = [
                g.strip() for g in extract_text_from_response(response).strip().split('\n')
                if g.strip() and len(g.strip()) > 10
            ]
            return gaps[:15]

        except Exception as e:
            logger.error(f"Gap identification failed: {e}")
            return []
    
    async def summarize_gap_investigation(
        self,
        gaps: List[str],
        sources: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str,
    ) -> str:
        """Summarize gap investigation."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["gap_summary"]
            )

            sources_sample = '\n'.join([
                f"- {s.get('title', '')}" for s in sources[:15]
            ])

            prompt = AnalysisPrompts.get_gap_summary_prompt(
                gaps, len(sources), sources_sample, language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return extract_text_from_response(response).strip()

        except Exception as e:
            logger.error(f"Gap summary failed: {e}")
            return f"Investigated {len(gaps)} gaps with {len(sources)} sources"


class ValidationAnalyzer:
    """Handles cross-validation and critical analysis."""
    
    def __init__(self, agent_name: str = "hyper_deep_research"):
        """Initialize validation analyzer.
        
        Args:
            agent_name: Name of the agent for tracking
        """
        self.agent_name = agent_name
    
    async def cross_validate_sources(
        self,
        sources: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str,
        clusters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Cross-validate sources with triangulation."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["cross_validation"]
            )

            sampled_sources = sources[:30] if len(sources) > 30 else sources
            sources_text = "\n\n".join([
                f"Source {i+1} ({s.get('url', 'N/A')}):\n"
                f"{s.get('title', '')}\n{s.get('content', '')[:300]}"
                for i, s in enumerate(sampled_sources)
            ])

            # Include cluster information
            cluster_info = ""
            if clusters:
                cluster_info = f"\n\nSemantic Clusters Identified: {len(clusters)}\n"
                for i, cluster in enumerate(clusters[:5], 1):
                    themes = ", ".join(cluster.get("themes", [])[:3])
                    cluster_info += (
                        f"- Cluster {i}: {cluster.get('size', 0)} sources on {themes}\n"
                    )

            prompt = ValidationPrompts.get_cross_validation_prompt(
                len(sampled_sources), sources_text + cluster_info, language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            return {
                "report": extract_text_from_response(response).strip(),
                "sources_analyzed": len(sampled_sources),
                "clusters_identified": len(clusters) if clusters else 0
            }
            
        except Exception as e:
            logger.error(f"Cross-validation failed: {e}")
            return {"report": "Cross-validation pending", "sources_analyzed": 0}
    
    async def perform_critical_analysis(
        self,
        topic_analysis: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        validation: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
        metadata_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform critical thinking and multi-perspective analysis."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.4, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["critical_thinking"]
            )

            prompt = ValidationPrompts.get_critical_thinking_prompt(
                topic_analysis['original_query'],
                deep_analysis['synthesis'][:1500],
                validation['report'][:1500],
                language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            if metadata_tracker is not None:
                metadata_tracker["critical_reviews_completed"] = (
                    metadata_tracker.get("critical_reviews_completed", 0) + 1
                )

            return {"full_analysis": extract_text_from_response(response).strip()}
            
        except Exception as e:
            logger.error(f"Critical analysis failed: {e}")
            return {"full_analysis": "Critical analysis pending"}


class DataSummarizer:
    """Handles data summarization operations."""
    
    def __init__(self, agent_name: str = "hyper_deep_research"):
        """Initialize data summarizer.
        
        Args:
            agent_name: Name of the agent for tracking
        """
        self.agent_name = agent_name
    
    async def summarize_collected_data(
        self,
        sources: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str,
    ) -> str:
        """Summarize collected data."""
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["data_summarization"]
            )

            sample = sources[:20]
            sources_sample = "\n\n".join([
                f"- {s.get('title', '')}: {s.get('content', '')[:300]}"
                for s in sample
            ])

            prompt = AnalysisPrompts.get_data_summary_prompt(
                len(sources), sources_sample, language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return extract_text_from_response(response).strip()

        except Exception as e:
            logger.error(f"Data summarization failed: {e}")
            return f"Collected {len(sources)} sources for analysis"
