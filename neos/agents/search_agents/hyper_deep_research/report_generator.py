"""Report Generation Module for HyperDeepResearch.

This module handles final report generation:
- Report structure planning
- Section generation
- Report assembly
- Metadata tracking
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from langchain_core.messages import HumanMessage

from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm, extract_text_from_response

from .prompts import ValidationPrompts, QueryGenerationPrompts


logger = logging.getLogger(__name__)


class ReportGenerator:
    """Handles final report generation."""
    
    def __init__(
        self,
        agent_name: str = "hyper_deep_research",
        repository: Optional[Any] = None,
    ):
        """Initialize report generator.
        
        Args:
            agent_name: Name of the agent for tracking
            repository: Optional repository for data storage
        """
        self.agent_name = agent_name
        self.repository = repository
    
    async def plan_report_structure(
        self,
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
    ) -> Dict[str, Any]:
        """Plan final report structure.
        
        Args:
            topic_analysis: Topic analysis result
            session_id: Session identifier
            user_id: User identifier
            language: Language code
            
        Returns:
            Report structure with sections
        """
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["report_structure"]
            )

            prompt = ValidationPrompts.get_report_structure_prompt(
                topic_analysis['original_query'], language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            sections = []
            for line in extract_text_from_response(response).strip().split('\n'):
                if '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 2:
                        sections.append({
                            "title": parts[0],
                            "purpose": parts[1] if len(parts) > 1 else "",
                            "content_type": parts[2] if len(parts) > 2 else ""
                        })

            return {"sections": sections[:12]}

        except Exception as e:
            logger.error(f"Report structure planning failed: {e}")
            return {"sections": [{"title": "Summary", "purpose": "Overview"}]}
    
    async def generate_section(
        self,
        section_info: Dict[str, Any],
        topic_analysis: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        validation: Dict[str, Any],
        critical_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
        total_sources: int,
    ) -> str:
        """Generate a final report section.
        
        Args:
            section_info: Section information (title, purpose)
            topic_analysis: Topic analysis result
            deep_analysis: Deep analysis result
            validation: Validation result
            critical_analysis: Critical analysis result
            session_id: Session identifier
            user_id: User identifier
            language: Language code
            total_sources: Total number of sources collected
            
        Returns:
            Section content
        """
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["final_section_generation"]
            )

            prompt = ValidationPrompts.get_final_section_prompt(
                section_info['title'],
                section_info.get('purpose', ''),
                topic_analysis['original_query'],
                deep_analysis['synthesis'],
                validation['report'],
                critical_analysis['full_analysis'],
                total_sources,
                language
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return extract_text_from_response(response).strip()

        except Exception as e:
            logger.error(f"Section generation failed: {e}")
            return f"Section {section_info['title']}: Content pending"
    
    async def synthesize_final_report(
        self,
        topic_analysis: Dict[str, Any],
        methodology: Dict[str, Any],
        deep_analysis: Dict[str, Any],
        validation: Dict[str, Any],
        critical_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
        report_id: str,
        metadata: Dict[str, Any],
    ) -> str:
        """Synthesize comprehensive final report.
        
        Args:
            topic_analysis: Topic analysis result
            methodology: Research methodology
            deep_analysis: Deep analysis result
            validation: Validation result
            critical_analysis: Critical analysis result
            session_id: Session identifier
            user_id: User identifier
            language: Language code
            report_id: Report identifier
            metadata: Research metadata
            
        Returns:
            Complete report as markdown string
        """
        # Plan report structure
        report_structure = await self.plan_report_structure(
            topic_analysis, session_id, user_id, language
        )

        # Generate sections
        final_sections = []
        section_order = 8

        for section_info in report_structure["sections"]:
            section_title = section_info["title"]
            print(f"[INFO] 📝 Generating section: {section_title}")

            section_content = await self.generate_section(
                section_info, topic_analysis, deep_analysis,
                validation, critical_analysis, session_id, user_id, language,
                metadata.get("total_sources_collected", 0)
            )

            # Store in repository if available
            if self.repository:
                section_id = await self.repository.create_section(
                    report_id, "final_report", section_order,
                    section_title, section_content, "completed"
                )
            else:
                section_id = f"section_{section_order}"

            final_sections.append({
                "section_id": section_id,
                "title": section_title,
                "content": section_content
            })

            section_order += 1

        # Assemble report
        return self.assemble_report(
            topic_analysis["original_query"],
            final_sections,
            report_id,
            metadata
        )
    
    def assemble_report(
        self,
        topic: str,
        sections: List[Dict[str, Any]],
        report_id: str,
        metadata: Dict[str, Any],
    ) -> str:
        """Assemble final report from sections.
        
        Args:
            topic: Research topic
            sections: List of report sections
            report_id: Report identifier
            metadata: Research metadata
            
        Returns:
            Assembled report as markdown string
        """
        unique_domains = metadata.get("unique_domains", set())
        unique_domains_count = (
            len(unique_domains) if isinstance(unique_domains, set) else unique_domains
        )
        
        parts = [
            f"# {topic}\n",
            "## HyperDeepResearch Comprehensive Report\n",
            f"\n**Report ID:** `{report_id}`\n",
            f"**Generated:** {datetime.utcnow().isoformat()}\n",
            "\n---\n",
            "\n## 📊 Research Statistics\n",
            f"- **Total Sources:** {metadata.get('total_sources_collected', 0)}\n",
            f"- **Total Queries:** {metadata.get('total_queries_executed', 0)}\n",
            f"- **Complex Searches:** {metadata.get('multi_query_searches', 0)}\n",
            f"- **Unique Domains:** {unique_domains_count}\n",
            f"- **Analysis Iterations:** {metadata.get('analysis_iterations_completed', 0)}\n",
            f"- **Critical Reviews:** {metadata.get('critical_reviews_completed', 0)}\n",
            f"- **Criticism Feedbacks:** {metadata.get('criticism_feedbacks_generated', 0)}\n",
            f"- **Additional Research Triggered:** {metadata.get('additional_research_triggered', 0)}\n",
            "\n---\n"
        ]

        for section in sections:
            parts.append(f"\n## {section['title']}\n")
            parts.append(f"\n{section['content']}\n")

        parts.append("\n---\n")
        parts.append(f"\n**Report ID: `{report_id}`**\n")

        return "".join(parts)


class CriticismProcessor:
    """Handles criticism feedback processing."""
    
    def __init__(
        self,
        criticism_agent: Any,
        repository: Optional[Any] = None,
        data_collector: Optional[Any] = None,
    ):
        """Initialize criticism processor.
        
        Args:
            criticism_agent: Criticism feedback agent
            repository: Optional repository for data storage
            data_collector: Optional data collector for additional research
        """
        self.criticism_agent = criticism_agent
        self.repository = repository
        self.data_collector = data_collector
        
        self.stats = {
            "feedbacks_generated": 0,
            "additional_research_triggered": 0,
        }
    
    async def process_criticism_feedback(
        self,
        section_type: str,
        section_title: str,
        section_content: str,
        topic: str,
        topic_analysis: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
        report_id: str,
        total_sources: int,
    ) -> None:
        """Get and process criticism feedback.
        
        Args:
            section_type: Type of section
            section_title: Title of section
            section_content: Content of section
            topic: Research topic
            topic_analysis: Topic analysis result
            session_id: Session identifier
            user_id: User identifier
            language: Language code
            report_id: Report identifier
            total_sources: Total sources collected
        """
        print(f"[INFO] 🔍 Requesting criticism feedback for: {section_title}")

        try:
            feedback = await self.criticism_agent.generate_feedback(
                topic=topic,
                section_type=section_type,
                section_content=section_content,
                research_context={
                    "sources_count": total_sources,
                    "research_questions": topic_analysis.get("research_questions", [])
                },
                session_id=session_id,
                user_id=user_id,
                language=language
            )

            self.stats["feedbacks_generated"] += 1

            # Record feedback
            if self.repository:
                await self.repository.record_criticism_feedback(
                    report_id, section_type, section_title, feedback
                )

            # Handle additional research if needed
            if self.criticism_agent.should_trigger_additional_research(feedback):
                print("[INFO] 🔄 Triggering additional research from feedback...")
                self.stats["additional_research_triggered"] += 1
                await self._conduct_feedback_research(feedback, section_type)

        except Exception as e:
            logger.error(f"Criticism feedback failed: {e}")
    
    async def _conduct_feedback_research(
        self,
        feedback: Dict[str, Any],
        section_type: str,
    ) -> List[Dict[str, Any]]:
        """Conduct additional research based on feedback."""
        if not self.data_collector:
            return []
            
        suggested_queries = feedback.get("suggested_queries", [])[:5]
        missing_perspectives = feedback.get("missing_perspectives", [])[:3]

        queries = suggested_queries + [
            f"{p} detailed analysis" for p in missing_perspectives
        ]

        if queries:
            results = await self.data_collector._search_batch_parallel(queries)
            return [item for sublist in results for item in sublist]
        
        return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get criticism processing statistics."""
        return self.stats.copy()


class QueryGenerator:
    """Handles query generation for gap analysis."""
    
    def __init__(self, agent_name: str = "hyper_deep_research"):
        """Initialize query generator.
        
        Args:
            agent_name: Name of the agent for tracking
        """
        self.agent_name = agent_name
    
    async def generate_gap_queries(
        self,
        gap: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> List[str]:
        """Generate queries for specific gap.
        
        Args:
            gap: Knowledge gap description
            session_id: Session identifier
            user_id: User identifier
            language: Language code
            
        Returns:
            List of queries to investigate the gap
        """
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.4, max_tokens=8000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["gap_query_generation"]
            )

            prompt = QueryGenerationPrompts.get_gap_query_prompt(gap, language)
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            queries = [
                q.strip() for q in extract_text_from_response(response).strip().split('\n')
                if q.strip() and len(q.strip()) > 5
            ]
            return queries[:5]

        except Exception as e:
            logger.error(f"Gap query generation failed: {e}")
            return [gap]
