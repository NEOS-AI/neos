"""Service for managing and querying clusters."""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.analytics import Cluster, ConversationFacet
from app.pipeline.privacy_filter import PrivacyFilter

logger = logging.getLogger(__name__)


class ClusterService:
    """Service for cluster operations and queries."""

    def __init__(self, db: AsyncSession):
        """Initialize the cluster service.

        Args:
            db: Database session.
        """
        self.db = db
        self.privacy_filter = PrivacyFilter()

    async def get_cluster(
        self,
        cluster_id: str,
        include_children: bool = False,
    ) -> Optional[Cluster]:
        """Get a cluster by ID.

        Args:
            cluster_id: UUID of the cluster.
            include_children: Whether to load children.

        Returns:
            Cluster or None.
        """
        query = select(Cluster).where(Cluster.cluster_id == cluster_id)

        if include_children:
            query = query.options(selectinload(Cluster.children))

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_cluster_hierarchy(
        self,
        analysis_run_id: int,
        max_depth: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get full cluster hierarchy for an analysis run.

        Args:
            analysis_run_id: ID of the analysis run.
            max_depth: Maximum depth to return.

        Returns:
            List of root clusters with nested children.
        """
        # Get all clusters for this run
        result = await self.db.execute(
            select(Cluster)
            .where(Cluster.analysis_run_id == analysis_run_id)
            .where(Cluster.is_visible == True)
            .order_by(Cluster.level, Cluster.conversation_count.desc())
        )
        clusters = list(result.scalars().all())

        # Build hierarchy
        cluster_map = {c.id: c for c in clusters}
        roots = []

        for cluster in clusters:
            if cluster.parent_id is None:
                roots.append(self._cluster_to_dict(cluster, cluster_map, max_depth))

        return roots

    def _cluster_to_dict(
        self,
        cluster: Cluster,
        cluster_map: Dict[int, Cluster],
        max_depth: Optional[int] = None,
        current_depth: int = 0,
    ) -> Dict[str, Any]:
        """Convert cluster to dictionary with children.

        Args:
            cluster: Cluster object.
            cluster_map: Map of cluster ID to cluster.
            max_depth: Maximum depth.
            current_depth: Current depth.

        Returns:
            Dictionary representation.
        """
        result = {
            "id": cluster.cluster_id,
            "name": cluster.name,
            "description": cluster.description,
            "level": cluster.level,
            "path": cluster.path,
            "conversation_count": cluster.conversation_count,
            "unique_user_count": cluster.unique_user_count,
            "keywords": cluster.keywords,
            "top_facets": cluster.top_facets,
            "centroid": {
                "x": cluster.centroid_x,
                "y": cluster.centroid_y,
            } if cluster.centroid_x is not None else None,
            "children": [],
        }

        # Add children if not at max depth
        if max_depth is None or current_depth < max_depth:
            children = [
                c for c in cluster_map.values()
                if c.parent_id == cluster.id and c.is_visible
            ]
            children.sort(key=lambda c: -c.conversation_count)

            for child in children:
                result["children"].append(
                    self._cluster_to_dict(
                        child, cluster_map, max_depth, current_depth + 1
                    )
                )

        return result

    async def get_cluster_conversations(
        self,
        cluster_id: str,
        limit: int = 50,
        offset: int = 0,
        include_facets: bool = True,
    ) -> List[Dict[str, Any]]:
        """Get conversations in a cluster.

        Args:
            cluster_id: UUID of the cluster.
            limit: Maximum results.
            offset: Offset for pagination.
            include_facets: Whether to include facet data.

        Returns:
            List of conversation data.
        """
        cluster = await self.get_cluster(cluster_id)
        if not cluster:
            return []

        result = await self.db.execute(
            select(ConversationFacet)
            .where(ConversationFacet.cluster_id == cluster.id)
            .where(ConversationFacet.is_private == False)
            .limit(limit)
            .offset(offset)
        )
        facets = list(result.scalars().all())

        conversations = []
        for f in facets:
            conv_data = {
                "conversation_id": f.conversation_id,
                "umap_x": f.umap_x,
                "umap_y": f.umap_y,
            }
            if include_facets:
                conv_data["facets"] = f.facets

            conversations.append(conv_data)

        return conversations

    async def get_umap_data(
        self,
        analysis_run_id: int,
        sample_size: Optional[int] = 5000,
    ) -> List[Dict[str, Any]]:
        """Get UMAP coordinates for visualization.

        Args:
            analysis_run_id: ID of the analysis run.
            sample_size: Maximum points to return.

        Returns:
            List of UMAP data points.
        """
        query = (
            select(
                ConversationFacet.conversation_id,
                ConversationFacet.umap_x,
                ConversationFacet.umap_y,
                ConversationFacet.cluster_id,
                ConversationFacet.facets,
            )
            .where(ConversationFacet.analysis_run_id == analysis_run_id)
            .where(ConversationFacet.is_private == False)
            .where(ConversationFacet.umap_x.isnot(None))
        )

        if sample_size:
            query = query.order_by(func.random()).limit(sample_size)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "conversation_id": row.conversation_id,
                "x": row.umap_x,
                "y": row.umap_y,
                "cluster_id": row.cluster_id,
                "task_type": row.facets.get("task_type") if row.facets else None,
                "language": row.facets.get("language") if row.facets else None,
            }
            for row in rows
        ]

    async def get_facet_distribution(
        self,
        analysis_run_id: int,
        facet_name: str,
    ) -> Dict[str, int]:
        """Get distribution of a facet across the analysis.

        Args:
            analysis_run_id: ID of the analysis run.
            facet_name: Name of the facet.

        Returns:
            Distribution counts.
        """
        result = await self.db.execute(
            select(ConversationFacet.facets)
            .where(ConversationFacet.analysis_run_id == analysis_run_id)
        )
        facets_list = list(result.scalars().all())

        distribution: Dict[str, int] = {}
        for facets in facets_list:
            value = facets.get(facet_name) if facets else None
            if value:
                value_str = str(value)
                distribution[value_str] = distribution.get(value_str, 0) + 1

        return distribution

    async def search_clusters(
        self,
        analysis_run_id: int,
        query: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search clusters by name or keywords.

        Args:
            analysis_run_id: ID of the analysis run.
            query: Search query.
            limit: Maximum results.

        Returns:
            List of matching clusters.
        """
        search_term = f"%{query.lower()}%"

        result = await self.db.execute(
            select(Cluster)
            .where(Cluster.analysis_run_id == analysis_run_id)
            .where(Cluster.is_visible == True)
            .where(
                (func.lower(Cluster.name).like(search_term))
                | (func.lower(Cluster.description).like(search_term))
            )
            .order_by(Cluster.conversation_count.desc())
            .limit(limit)
        )
        clusters = list(result.scalars().all())

        return [
            {
                "id": c.cluster_id,
                "name": c.name,
                "description": c.description,
                "level": c.level,
                "conversation_count": c.conversation_count,
                "path": c.path,
            }
            for c in clusters
        ]

    async def get_trending_topics(
        self,
        analysis_run_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get trending topics based on cluster sizes.

        Args:
            analysis_run_id: ID of the analysis run.
            limit: Maximum topics.

        Returns:
            List of trending topics.
        """
        result = await self.db.execute(
            select(Cluster)
            .where(Cluster.analysis_run_id == analysis_run_id)
            .where(Cluster.is_visible == True)
            .where(Cluster.level == 1)  # Top-level clusters
            .order_by(Cluster.conversation_count.desc())
            .limit(limit)
        )
        clusters = list(result.scalars().all())

        return [
            {
                "name": c.name,
                "count": c.conversation_count,
                "keywords": c.keywords[:5] if c.keywords else [],
                "id": c.cluster_id,
            }
            for c in clusters
        ]

    async def compare_clusters(
        self,
        cluster_ids: List[str],
    ) -> Dict[str, Any]:
        """Compare multiple clusters.

        Args:
            cluster_ids: List of cluster IDs to compare.

        Returns:
            Comparison data.
        """
        clusters = []
        for cluster_id in cluster_ids:
            cluster = await self.get_cluster(cluster_id)
            if cluster:
                clusters.append(cluster)

        if not clusters:
            return {"error": "No clusters found"}

        comparison = {
            "clusters": [],
            "facet_comparison": {},
        }

        all_facet_keys = set()
        for cluster in clusters:
            cluster_data = {
                "id": cluster.cluster_id,
                "name": cluster.name,
                "conversation_count": cluster.conversation_count,
                "top_facets": cluster.top_facets or {},
            }
            comparison["clusters"].append(cluster_data)

            if cluster.top_facets:
                all_facet_keys.update(cluster.top_facets.keys())

        # Compare facet distributions
        for facet_key in all_facet_keys:
            comparison["facet_comparison"][facet_key] = {}
            for cluster in clusters:
                facets = cluster.top_facets or {}
                comparison["facet_comparison"][facet_key][cluster.cluster_id] = (
                    facets.get(facet_key, {})
                )

        return comparison
