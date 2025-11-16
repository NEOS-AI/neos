"""Semantic clustering for source organization.

Groups similar sources together and identifies patterns using embeddings.
"""

from typing import Dict, Any, List, Optional, Tuple
import logging
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


class SemanticClusterer:
    """Clusters sources semantically using text embeddings."""

    def __init__(
        self,
        similarity_threshold: float = 0.75,
        min_cluster_size: int = 2,
        max_clusters: int = 20,
    ):
        """Initialize semantic clusterer.

        Args:
            similarity_threshold: Cosine similarity threshold for clustering
            min_cluster_size: Minimum sources per cluster
            max_clusters: Maximum number of clusters to create
        """
        self.similarity_threshold = similarity_threshold
        self.min_cluster_size = min_cluster_size
        self.max_clusters = max_clusters

        self.embeddings_cache = {}
        self.stats = {
            "sources_clustered": 0,
            "clusters_created": 0,
            "avg_cluster_size": 0.0,
        }

    async def cluster_sources(
        self,
        sources: List[Dict[str, Any]],
        embedding_function: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Cluster sources by semantic similarity.

        Args:
            sources: List of source dictionaries
            embedding_function: Optional function to generate embeddings

        Returns:
            List of cluster dictionaries
        """
        if not sources:
            return []

        try:
            logger.info(f"[SemanticClusterer] Clustering {len(sources)} sources...")

            # Generate embeddings
            embeddings = await self._generate_embeddings(sources, embedding_function)

            if not embeddings:
                logger.warning("[SemanticClusterer] No embeddings generated, using fallback")
                return self._fallback_clustering(sources)

            # Perform clustering
            clusters = self._hierarchical_clustering(sources, embeddings)

            # Analyze each cluster
            analyzed_clusters = []
            for cluster in clusters:
                analyzed = await self._analyze_cluster(cluster, embedding_function)
                analyzed_clusters.append(analyzed)

            self.stats["sources_clustered"] = len(sources)
            self.stats["clusters_created"] = len(analyzed_clusters)
            self.stats["avg_cluster_size"] = (
                len(sources) / len(analyzed_clusters) if analyzed_clusters else 0
            )

            logger.info(
                f"[SemanticClusterer] Created {len(analyzed_clusters)} clusters "
                f"(avg size: {self.stats['avg_cluster_size']:.1f})"
            )

            return analyzed_clusters

        except Exception as e:
            logger.error(f"[SemanticClusterer] Clustering error: {e}")
            return self._fallback_clustering(sources)

    async def _generate_embeddings(
        self,
        sources: List[Dict[str, Any]],
        embedding_function: Optional[Any] = None,
    ) -> List[np.ndarray]:
        """Generate embeddings for sources.

        Args:
            sources: List of sources
            embedding_function: Optional embedding function

        Returns:
            List of embedding vectors
        """
        try:
            embeddings = []

            for source in sources:
                # Combine title and content for embedding
                text = f"{source.get('title', '')} {source.get('content', '')[:500]}"

                # Check cache
                cache_key = hash(text[:200])
                if cache_key in self.embeddings_cache:
                    embeddings.append(self.embeddings_cache[cache_key])
                    continue

                # Generate embedding
                if embedding_function:
                    try:
                        embedding = await embedding_function(text)
                        self.embeddings_cache[cache_key] = embedding
                        embeddings.append(embedding)
                    except Exception as e:
                        logger.warning(f"[SemanticClusterer] Embedding error: {e}")
                        # Fallback to simple vector
                        embeddings.append(self._simple_text_vector(text))
                else:
                    # Use simple text-based vector
                    embedding = self._simple_text_vector(text)
                    self.embeddings_cache[cache_key] = embedding
                    embeddings.append(embedding)

            return embeddings

        except Exception as e:
            logger.error(f"[SemanticClusterer] Embedding generation error: {e}")
            return []

    def _simple_text_vector(self, text: str, dim: int = 100) -> np.ndarray:
        """Create simple text-based vector using character frequencies.

        This is a fallback when proper embeddings are unavailable.

        Args:
            text: Text to vectorize
            dim: Vector dimension

        Returns:
            Numpy array vector
        """
        # Use character-level features
        text_lower = text.lower()
        vector = np.zeros(dim)

        # Character frequency features
        for i, char in enumerate(text_lower[:dim]):
            vector[i] = ord(char) / 255.0

        # Word-level features (simple)
        words = text_lower.split()[:50]
        for i, word in enumerate(words):
            if i < dim // 2:
                vector[dim // 2 + i] = len(word) / 20.0

        # Normalize
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        return vector

    def _hierarchical_clustering(
        self,
        sources: List[Dict[str, Any]],
        embeddings: List[np.ndarray],
    ) -> List[List[Dict[str, Any]]]:
        """Perform hierarchical clustering.

        Args:
            sources: List of sources
            embeddings: List of embedding vectors

        Returns:
            List of clusters (each cluster is a list of sources)
        """
        try:
            n = len(sources)
            if n == 0:
                return []

            # Initialize each source as its own cluster
            clusters = [[i] for i in range(n)]
            cluster_embeddings = [emb.copy() for emb in embeddings]

            # Merge clusters until similarity threshold not met
            while len(clusters) > 1:
                # Find most similar pair
                max_sim = -1
                merge_pair = None

                for i in range(len(clusters)):
                    for j in range(i + 1, len(clusters)):
                        sim = self._cosine_similarity(
                            cluster_embeddings[i],
                            cluster_embeddings[j]
                        )

                        if sim > max_sim:
                            max_sim = sim
                            merge_pair = (i, j)

                # Check if we should merge
                if max_sim < self.similarity_threshold or merge_pair is None:
                    break

                # Merge clusters
                i, j = merge_pair
                clusters[i].extend(clusters[j])

                # Update embedding (average)
                cluster_embeddings[i] = (
                    cluster_embeddings[i] * len(clusters[i]) +
                    cluster_embeddings[j] * len(clusters[j])
                ) / (len(clusters[i]) + len(clusters[j]))

                # Remove merged cluster
                del clusters[j]
                del cluster_embeddings[j]

                # Limit number of clusters
                if len(clusters) <= self.max_clusters:
                    break

            # Convert indices to actual sources
            source_clusters = []
            for cluster_indices in clusters:
                cluster_sources = [sources[idx] for idx in cluster_indices]
                # Filter small clusters
                if len(cluster_sources) >= self.min_cluster_size:
                    source_clusters.append(cluster_sources)
                else:
                    # Add small clusters to unclustered
                    pass

            return source_clusters

        except Exception as e:
            logger.error(f"[SemanticClusterer] Clustering algorithm error: {e}")
            return [sources]  # Return all as one cluster

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Similarity score (0 to 1)
        """
        try:
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)

            if norm1 == 0 or norm2 == 0:
                return 0.0

            return float(dot_product / (norm1 * norm2))

        except Exception as e:
            logger.warning(f"[SemanticClusterer] Similarity calculation error: {e}")
            return 0.0

    async def _analyze_cluster(
        self,
        cluster_sources: List[Dict[str, Any]],
        embedding_function: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Analyze a cluster to extract theme and patterns.

        Args:
            cluster_sources: Sources in the cluster
            embedding_function: Optional embedding function

        Returns:
            Cluster analysis dictionary
        """
        try:
            # Extract representative source (highest quality if available)
            representative = max(
                cluster_sources,
                key=lambda s: s.get("quality_score", s.get("score", 0.5))
            )

            # Extract common themes
            themes = self._extract_themes(cluster_sources)

            # Calculate cluster statistics
            avg_quality = np.mean([
                s.get("quality_score", s.get("score", 0.5))
                for s in cluster_sources
            ])

            return {
                "size": len(cluster_sources),
                "sources": cluster_sources,
                "representative_source": representative,
                "themes": themes,
                "avg_quality": float(avg_quality),
                "summary": self._generate_cluster_summary(cluster_sources, themes),
            }

        except Exception as e:
            logger.error(f"[SemanticClusterer] Cluster analysis error: {e}")
            return {
                "size": len(cluster_sources),
                "sources": cluster_sources,
                "themes": [],
                "summary": "Cluster analysis pending",
            }

    def _extract_themes(self, sources: List[Dict[str, Any]]) -> List[str]:
        """Extract common themes from cluster sources.

        Args:
            sources: Sources in cluster

        Returns:
            List of theme strings
        """
        try:
            # Combine all titles and content
            all_text = " ".join([
                f"{s.get('title', '')} {s.get('content', '')[:200]}"
                for s in sources
            ]).lower()

            # Extract common words (simple keyword extraction)
            words = all_text.split()
            word_freq = defaultdict(int)

            # Filter stopwords (simple list)
            stopwords = {
                "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
                "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
                "been", "being", "have", "has", "had", "do", "does", "did", "will",
                "would", "should", "could", "may", "might", "can", "that", "this",
                "these", "those", "it", "its", "they", "them", "their",
            }

            for word in words:
                if len(word) > 4 and word not in stopwords:
                    word_freq[word] += 1

            # Get top themes
            top_themes = sorted(
                word_freq.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]

            return [theme for theme, _ in top_themes]

        except Exception as e:
            logger.warning(f"[SemanticClusterer] Theme extraction error: {e}")
            return []

    def _generate_cluster_summary(
        self,
        sources: List[Dict[str, Any]],
        themes: List[str],
    ) -> str:
        """Generate cluster summary.

        Args:
            sources: Sources in cluster
            themes: Extracted themes

        Returns:
            Summary string
        """
        theme_str = ", ".join(themes[:3]) if themes else "various topics"
        return (
            f"Cluster of {len(sources)} sources focusing on: {theme_str}"
        )

    def _fallback_clustering(
        self,
        sources: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Fallback clustering when embeddings fail.

        Groups by domain as simple heuristic.

        Args:
            sources: List of sources

        Returns:
            List of clusters
        """
        try:
            from urllib.parse import urlparse

            domain_clusters = defaultdict(list)

            for source in sources:
                url = source.get("url", "")
                if url:
                    domain = urlparse(url).netloc
                    domain_clusters[domain].append(source)
                else:
                    domain_clusters["unknown"].append(source)

            # Convert to cluster format
            clusters = []
            for domain, cluster_sources in domain_clusters.items():
                if len(cluster_sources) >= self.min_cluster_size:
                    clusters.append({
                        "size": len(cluster_sources),
                        "sources": cluster_sources,
                        "representative_source": cluster_sources[0],
                        "themes": [domain],
                        "summary": f"Sources from {domain}",
                        "avg_quality": 0.5,
                    })

            return clusters

        except Exception as e:
            logger.error(f"[SemanticClusterer] Fallback clustering error: {e}")
            return [{
                "size": len(sources),
                "sources": sources,
                "summary": "All sources (unclustered)",
            }]

    def get_stats(self) -> Dict[str, Any]:
        """Get clustering statistics.

        Returns:
            Statistics dictionary
        """
        return self.stats.copy()

    def identify_knowledge_gaps(
        self,
        clusters: List[Dict[str, Any]],
        expected_themes: List[str] = None,
    ) -> List[str]:
        """Identify knowledge gaps from cluster analysis.

        Args:
            clusters: List of cluster dictionaries
            expected_themes: Optional list of expected themes

        Returns:
            List of identified gaps
        """
        try:
            gaps = []

            # Check for missing expected themes
            if expected_themes:
                covered_themes = set()
                for cluster in clusters:
                    covered_themes.update(cluster.get("themes", []))

                for expected in expected_themes:
                    if not any(expected.lower() in theme.lower() for theme in covered_themes):
                        gaps.append(f"Missing coverage on: {expected}")

            # Check for underrepresented clusters
            if clusters:
                avg_size = np.mean([c.get("size", 0) for c in clusters])
                for cluster in clusters:
                    if cluster.get("size", 0) < avg_size * 0.5:
                        themes = cluster.get("themes", [])
                        if themes:
                            gaps.append(
                                f"Underrepresented topic: {', '.join(themes[:2])}"
                            )

            return gaps[:10]  # Limit to 10 gaps

        except Exception as e:
            logger.error(f"[SemanticClusterer] Gap identification error: {e}")
            return []
