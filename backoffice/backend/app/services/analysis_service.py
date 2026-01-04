"""Service for managing analysis runs and pipeline execution."""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.analytics import (
    AnalysisRun,
    AnalysisStatus,
    Cluster,
    ConversationFacet,
)
from app.models.neos import Conversation, Message
from app.pipeline.clustering import ClusteringEngine, EmbeddingGenerator
from app.pipeline.facet_extractor import FacetExtractor, SimpleFacetExtractor
from app.pipeline.hierarchy_builder import HierarchyBuilder
from app.pipeline.privacy_filter import PrivacyFilter

logger = logging.getLogger(__name__)


class AnalysisService:
    """Service for running and managing analysis pipelines."""

    def __init__(self, db: AsyncSession):
        """Initialize the analysis service.

        Args:
            db: Database session.
        """
        self.db = db
        self.embedding_generator = EmbeddingGenerator()
        self.clustering_engine = ClusteringEngine()
        self.privacy_filter = PrivacyFilter()

    async def create_analysis_run(
        self,
        name: str,
        description: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        facet_types: Optional[List[str]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> AnalysisRun:
        """Create a new analysis run.

        Args:
            name: Name of the analysis run.
            description: Optional description.
            start_date: Start date for conversation filter.
            end_date: End date for conversation filter.
            facet_types: Types of facets to extract.
            config: Additional configuration.

        Returns:
            Created AnalysisRun.
        """
        run = AnalysisRun(
            run_id=str(uuid.uuid4()),
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            facet_types=facet_types or ["topic", "language", "task_type"],
            config=config or {},
            status=AnalysisStatus.PENDING,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_analysis_run(self, run_id: str) -> Optional[AnalysisRun]:
        """Get an analysis run by ID.

        Args:
            run_id: UUID of the analysis run.

        Returns:
            AnalysisRun or None.
        """
        result = await self.db.execute(
            select(AnalysisRun).where(AnalysisRun.run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_analysis_runs(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> List[AnalysisRun]:
        """List analysis runs.

        Args:
            limit: Maximum number of results.
            offset: Offset for pagination.
            status: Filter by status.

        Returns:
            List of AnalysisRun.
        """
        query = select(AnalysisRun).order_by(AnalysisRun.created_at.desc())

        if status:
            query = query.where(AnalysisRun.status == status)

        query = query.limit(limit).offset(offset)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _get_conversations(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 10000,
    ) -> List[Conversation]:
        """Get conversations from the database.

        Args:
            start_date: Filter by start date.
            end_date: Filter by end date.
            limit: Maximum conversations.

        Returns:
            List of Conversation.
        """
        query = select(Conversation).order_by(Conversation.created_at.desc())

        if start_date:
            query = query.where(Conversation.created_at >= start_date)
        if end_date:
            query = query.where(Conversation.created_at <= end_date)

        query = query.limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _get_messages_for_conversation(
        self, conversation_id: int
    ) -> List[Message]:
        """Get messages for a conversation.

        Args:
            conversation_id: Conversation ID.

        Returns:
            List of Message.
        """
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())

    async def run_analysis(
        self,
        run_id: str,
        use_llm_extraction: bool = True,
    ) -> AnalysisRun:
        """Execute the full analysis pipeline.

        Args:
            run_id: ID of the analysis run.
            use_llm_extraction: Whether to use LLM for facet extraction.

        Returns:
            Updated AnalysisRun.
        """
        run = await self.get_analysis_run(run_id)
        if not run:
            raise ValueError(f"Analysis run not found: {run_id}")

        try:
            # Update status
            run.status = AnalysisStatus.RUNNING
            run.started_at = datetime.now()
            run.current_stage = "fetching_conversations"
            await self.db.flush()

            # Fetch conversations
            conversations = await self._get_conversations(
                start_date=run.start_date,
                end_date=run.end_date,
                limit=run.config.get("max_conversations", settings.MAX_CONVERSATIONS_PER_RUN),
            )
            run.total_conversations = len(conversations)
            await self.db.flush()

            if not conversations:
                run.status = AnalysisStatus.COMPLETED
                run.completed_at = datetime.now()
                run.current_stage = "completed"
                await self.db.flush()
                return run

            # Stage 1: Extract facets
            run.current_stage = "extracting_facets"
            run.progress_percentage = 10.0
            await self.db.flush()

            facets_data = []
            summaries = []

            if use_llm_extraction and settings.ANTHROPIC_API_KEY:
                extractor = FacetExtractor()
            else:
                extractor = None
                simple_extractor = SimpleFacetExtractor()

            for i, conv in enumerate(conversations):
                messages = await self._get_messages_for_conversation(conv.id)
                message_dicts = [
                    {"role": m.role, "content": m.content} for m in messages
                ]

                if extractor:
                    facets = await extractor.extract_facets(message_dicts)
                    if facets:
                        facets_dict = facets.model_dump()
                    else:
                        facets_dict = simple_extractor.extract_facets(message_dicts)
                else:
                    facets_dict = simple_extractor.extract_facets(message_dicts)

                # Apply privacy filter
                facets_dict, is_private, privacy_reason = (
                    self.privacy_filter.process_conversation_facets(facets_dict)
                )

                facets_data.append({
                    "conversation_id": conv.id,
                    "user_id": conv.user_id,
                    "facets": facets_dict,
                    "is_private": is_private,
                    "privacy_reason": privacy_reason,
                })

                summary = facets_dict.get("summary", "")
                summaries.append(summary if summary else str(facets_dict.get("topic", "")))

                run.processed_conversations = i + 1
                run.progress_percentage = 10.0 + (30.0 * (i + 1) / len(conversations))

                if (i + 1) % 100 == 0:
                    await self.db.flush()

            # Stage 2: Generate embeddings
            run.current_stage = "generating_embeddings"
            run.progress_percentage = 40.0
            await self.db.flush()

            embedding_result = self.embedding_generator.generate(summaries)

            # Stage 3: Cluster
            run.current_stage = "clustering"
            run.progress_percentage = 60.0
            await self.db.flush()

            cluster_result = self.clustering_engine.fit_predict(
                embedding_result.embeddings,
                reduce_first=True,
            )

            # Stage 4: Build hierarchy
            run.current_stage = "building_hierarchy"
            run.progress_percentage = 75.0
            await self.db.flush()

            hierarchy_builder = HierarchyBuilder()
            hierarchy = await hierarchy_builder.build_hierarchy(
                cluster_result,
                [f["facets"] for f in facets_data],
                embedding_result.embeddings,
            )

            # Stage 5: Save results
            run.current_stage = "saving_results"
            run.progress_percentage = 85.0
            await self.db.flush()

            # Save conversation facets
            for i, data in enumerate(facets_data):
                conv_facet = ConversationFacet(
                    conversation_id=data["conversation_id"],
                    analysis_run_id=run.id,
                    facets=data["facets"],
                    summary_embedding=embedding_result.embeddings[i].tolist()
                    if i < len(embedding_result.embeddings)
                    else None,
                    umap_x=float(cluster_result.umap_embeddings[i][0])
                    if i < len(cluster_result.umap_embeddings)
                    else None,
                    umap_y=float(cluster_result.umap_embeddings[i][1])
                    if i < len(cluster_result.umap_embeddings)
                    else None,
                    is_private=data["is_private"],
                    privacy_reason=data["privacy_reason"],
                )
                self.db.add(conv_facet)

            # Save clusters from hierarchy
            await self._save_clusters_from_hierarchy(run.id, hierarchy)

            run.total_clusters = cluster_result.num_clusters
            run.status = AnalysisStatus.COMPLETED
            run.completed_at = datetime.now()
            run.current_stage = "completed"
            run.progress_percentage = 100.0
            await self.db.flush()

            return run

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            run.status = AnalysisStatus.FAILED
            run.error_message = str(e)
            run.error_count += 1
            await self.db.flush()
            raise

    async def _save_clusters_from_hierarchy(
        self,
        analysis_run_id: int,
        hierarchy: Dict[str, Any],
    ) -> None:
        """Save clusters from hierarchy to database.

        Args:
            analysis_run_id: ID of the analysis run.
            hierarchy: Hierarchical cluster structure.
        """

        async def save_node(
            node: Dict[str, Any],
            parent_id: Optional[int] = None,
        ) -> int:
            cluster = Cluster(
                cluster_id=node["id"],
                analysis_run_id=analysis_run_id,
                name=node["name"],
                description=node.get("description"),
                level=node["level"],
                parent_id=parent_id,
                path=node["path"],
                conversation_count=node["count"],
                keywords=node.get("keywords"),
                top_facets=node.get("facet_distribution"),
            )

            if node.get("centroid"):
                cluster.centroid_x = node["centroid"].get("x")
                cluster.centroid_y = node["centroid"].get("y")

            self.db.add(cluster)
            await self.db.flush()
            await self.db.refresh(cluster)

            for child in node.get("children", []):
                await save_node(child, cluster.id)

            return cluster.id

        await save_node(hierarchy)

    async def delete_analysis_run(self, run_id: str) -> bool:
        """Delete an analysis run and all associated data.

        Args:
            run_id: ID of the analysis run.

        Returns:
            True if deleted.
        """
        run = await self.get_analysis_run(run_id)
        if not run:
            return False

        await self.db.delete(run)
        await self.db.flush()
        return True

    async def get_analysis_statistics(self, run_id: str) -> Dict[str, Any]:
        """Get statistics for an analysis run.

        Args:
            run_id: ID of the analysis run.

        Returns:
            Statistics dictionary.
        """
        run = await self.get_analysis_run(run_id)
        if not run:
            return {}

        # Count clusters by level
        level_counts = await self.db.execute(
            select(Cluster.level, func.count(Cluster.id))
            .where(Cluster.analysis_run_id == run.id)
            .group_by(Cluster.level)
        )

        # Get facet distribution
        facet_result = await self.db.execute(
            select(ConversationFacet.facets)
            .where(ConversationFacet.analysis_run_id == run.id)
        )
        facets = list(facet_result.scalars().all())

        return {
            "run_id": run.run_id,
            "status": run.status,
            "total_conversations": run.total_conversations,
            "processed_conversations": run.processed_conversations,
            "total_clusters": run.total_clusters,
            "clusters_by_level": {str(level): count for level, count in level_counts},
            "progress": run.progress_percentage,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
