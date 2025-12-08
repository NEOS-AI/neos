"""Hierarchical cluster builder with LLM-based naming."""

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import anthropic
import numpy as np

from app.core.config import settings
from app.pipeline.clustering import ClusterResult, EmbeddingGenerator

logger = logging.getLogger(__name__)


class ClusterNamer:
    """Generates names and summaries for clusters using LLM."""

    NAMING_PROMPT = """Analyze these conversation summaries from a cluster and generate a concise name and description.

Conversation summaries from this cluster:
{summaries}

Common keywords: {keywords}

Generate:
1. A short name (3-6 words) that captures the main theme
2. A brief description (1-2 sentences) explaining what users in this cluster are doing
3. A list of 3-5 representative keywords

IMPORTANT: The name and description must:
- Be generic enough to not reveal individual user information
- Not contain any personal names, company names, or specific identifiers
- Focus on the task type and domain, not specific details

Respond in JSON format:
{{"name": "...", "description": "...", "keywords": ["...", "...", "..."]}}"""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the cluster namer.

        Args:
            api_key: Anthropic API key.
        """
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.client = None
        if self.api_key:
            self.client = anthropic.Anthropic(api_key=self.api_key)

    async def generate_cluster_name(
        self,
        summaries: List[str],
        keywords: List[str],
        max_summaries: int = 20,
    ) -> Dict[str, Any]:
        """Generate name and description for a cluster.

        Args:
            summaries: List of conversation summaries in the cluster.
            keywords: Common keywords in the cluster.
            max_summaries: Maximum summaries to include in prompt.

        Returns:
            Dictionary with name, description, and keywords.
        """
        if not self.client:
            return self._fallback_naming(summaries, keywords)

        # Sample summaries if too many
        if len(summaries) > max_summaries:
            indices = np.random.choice(len(summaries), max_summaries, replace=False)
            summaries = [summaries[i] for i in indices]

        prompt = self.NAMING_PROMPT.format(
            summaries="\n".join(f"- {s}" for s in summaries),
            keywords=", ".join(keywords[:10]),
        )

        try:
            import json

            response = self.client.messages.create(
                model=settings.LLM_MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(text[json_start:json_end])

        except Exception as e:
            logger.error(f"Error generating cluster name: {e}")

        return self._fallback_naming(summaries, keywords)

    def _fallback_naming(
        self, summaries: List[str], keywords: List[str]
    ) -> Dict[str, Any]:
        """Fallback naming using keywords."""
        name = " ".join(keywords[:3]).title() if keywords else "Unnamed Cluster"
        return {
            "name": name,
            "description": f"Cluster containing {len(summaries)} conversations",
            "keywords": keywords[:5],
        }


class HierarchyBuilder:
    """Builds hierarchical cluster structure."""

    def __init__(
        self,
        namer: Optional[ClusterNamer] = None,
        max_depth: int = 4,
        min_subcluster_size: int = 50,
    ):
        """Initialize the hierarchy builder.

        Args:
            namer: ClusterNamer instance for generating names.
            max_depth: Maximum depth of hierarchy.
            min_subcluster_size: Minimum size for sub-clustering.
        """
        self.namer = namer or ClusterNamer()
        self.max_depth = max_depth
        self.min_subcluster_size = min_subcluster_size

    async def build_hierarchy(
        self,
        cluster_result: ClusterResult,
        facets_data: List[Dict[str, Any]],
        embeddings: np.ndarray,
    ) -> Dict[str, Any]:
        """Build hierarchical cluster structure.

        Args:
            cluster_result: Result from clustering engine.
            facets_data: List of facet dictionaries for each item.
            embeddings: Original embeddings.

        Returns:
            Hierarchical structure dictionary.
        """
        root = {
            "id": str(uuid.uuid4()),
            "name": "All Conversations",
            "description": "Root of the cluster hierarchy",
            "level": 0,
            "path": "/",
            "count": len(cluster_result.cluster_labels),
            "children": [],
            "metadata": {
                "total_clusters": cluster_result.num_clusters,
                "noise_count": cluster_result.noise_count,
            },
        }

        # Build top-level clusters
        labels = cluster_result.cluster_labels
        unique_labels = sorted(set(l for l in labels if l >= 0))

        for label in unique_labels:
            mask = labels == label
            cluster_facets = [f for f, m in zip(facets_data, mask) if m]
            cluster_embeddings = embeddings[mask]
            cluster_umap = cluster_result.umap_embeddings[mask]

            # Extract summaries and keywords for naming
            summaries = [
                f.get("summary", "") for f in cluster_facets if f.get("summary")
            ]
            all_keywords = []
            for f in cluster_facets:
                all_keywords.extend(f.get("keywords", []))

            # Count keyword frequencies
            keyword_counts = {}
            for kw in all_keywords:
                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
            top_keywords = sorted(keyword_counts.keys(), key=lambda k: -keyword_counts[k])

            # Generate name
            naming = await self.namer.generate_cluster_name(summaries, top_keywords)

            cluster_node = {
                "id": str(uuid.uuid4()),
                "label": label,
                "name": naming["name"],
                "description": naming["description"],
                "level": 1,
                "path": f"/{label}",
                "count": int(np.sum(mask)),
                "keywords": naming["keywords"],
                "centroid": {
                    "x": float(np.mean(cluster_umap[:, 0])),
                    "y": float(np.mean(cluster_umap[:, 1])),
                },
                "facet_distribution": self._compute_facet_distribution(cluster_facets),
                "children": [],
            }

            # Recursively build sub-clusters if large enough
            if len(cluster_embeddings) >= self.min_subcluster_size:
                cluster_node["children"] = await self._build_subclusters(
                    cluster_embeddings,
                    cluster_facets,
                    cluster_umap,
                    parent_path=cluster_node["path"],
                    current_depth=1,
                )

            root["children"].append(cluster_node)

        return root

    async def _build_subclusters(
        self,
        embeddings: np.ndarray,
        facets_data: List[Dict[str, Any]],
        umap_coords: np.ndarray,
        parent_path: str,
        current_depth: int,
    ) -> List[Dict[str, Any]]:
        """Recursively build sub-clusters.

        Args:
            embeddings: Embeddings for this cluster.
            facets_data: Facet data for items in this cluster.
            umap_coords: UMAP coordinates.
            parent_path: Path of parent cluster.
            current_depth: Current depth in hierarchy.

        Returns:
            List of sub-cluster nodes.
        """
        if current_depth >= self.max_depth:
            return []

        if len(embeddings) < self.min_subcluster_size * 2:
            return []

        from app.pipeline.clustering import SubClusteringEngine

        sub_engine = SubClusteringEngine(
            min_cluster_size=max(5, len(embeddings) // 20),
            min_samples=3,
        )

        result = sub_engine.fit_predict(embeddings, reduce_first=True)

        if result.num_clusters <= 1:
            return []

        children = []
        for label in range(result.num_clusters):
            mask = result.cluster_labels == label
            sub_facets = [f for f, m in zip(facets_data, mask) if m]
            sub_embeddings = embeddings[mask]
            sub_umap = result.umap_embeddings[mask]

            # Generate name
            summaries = [f.get("summary", "") for f in sub_facets if f.get("summary")]
            keywords = []
            for f in sub_facets:
                keywords.extend(f.get("keywords", []))

            keyword_counts = {}
            for kw in keywords:
                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
            top_keywords = sorted(
                keyword_counts.keys(), key=lambda k: -keyword_counts[k]
            )

            naming = await self.namer.generate_cluster_name(summaries, top_keywords)

            node = {
                "id": str(uuid.uuid4()),
                "label": label,
                "name": naming["name"],
                "description": naming["description"],
                "level": current_depth + 1,
                "path": f"{parent_path}/{label}",
                "count": int(np.sum(mask)),
                "keywords": naming["keywords"],
                "centroid": {
                    "x": float(np.mean(sub_umap[:, 0])),
                    "y": float(np.mean(sub_umap[:, 1])),
                },
                "facet_distribution": self._compute_facet_distribution(sub_facets),
                "children": [],
            }

            # Continue recursion
            if len(sub_embeddings) >= self.min_subcluster_size:
                node["children"] = await self._build_subclusters(
                    sub_embeddings,
                    sub_facets,
                    sub_umap,
                    parent_path=node["path"],
                    current_depth=current_depth + 1,
                )

            children.append(node)

        return children

    def _compute_facet_distribution(
        self, facets_data: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, int]]:
        """Compute distribution of facet values within a cluster.

        Args:
            facets_data: List of facet dictionaries.

        Returns:
            Distribution counts for each facet type.
        """
        distribution: Dict[str, Dict[str, int]] = {
            "task_type": {},
            "language": {},
            "domain": {},
            "intent": {},
            "complexity": {},
            "sentiment": {},
        }

        for facets in facets_data:
            for key in distribution.keys():
                value = facets.get(key)
                if value is not None:
                    value_str = str(value)
                    distribution[key][value_str] = distribution[key].get(value_str, 0) + 1

        return distribution

    def flatten_hierarchy(
        self, hierarchy: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Flatten hierarchical structure to a list.

        Args:
            hierarchy: Hierarchical structure.

        Returns:
            Flat list of all nodes.
        """
        nodes = []

        def traverse(node: Dict[str, Any], parent_id: Optional[str] = None):
            flat_node = {
                "id": node["id"],
                "parent_id": parent_id,
                "name": node["name"],
                "description": node.get("description"),
                "level": node["level"],
                "path": node["path"],
                "count": node["count"],
                "keywords": node.get("keywords", []),
                "centroid": node.get("centroid"),
                "facet_distribution": node.get("facet_distribution"),
            }
            nodes.append(flat_node)

            for child in node.get("children", []):
                traverse(child, node["id"])

        traverse(hierarchy)
        return nodes
