"""Clustering engine for conversation analysis."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import hdbscan
import numpy as np
import umap
from sentence_transformers import SentenceTransformer
from sklearn.preprocessing import StandardScaler

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ClusterResult:
    """Result of clustering operation."""

    cluster_labels: np.ndarray
    probabilities: np.ndarray
    umap_embeddings: np.ndarray
    num_clusters: int
    noise_count: int


@dataclass
class EmbeddingResult:
    """Result of embedding generation."""

    embeddings: np.ndarray
    texts: List[str]
    dimension: int


class EmbeddingGenerator:
    """Generates embeddings for text using sentence transformers."""

    def __init__(self, model_name: Optional[str] = None):
        """Initialize the embedding generator.

        Args:
            model_name: Name of the sentence transformer model.
        """
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self._model: Optional[SentenceTransformer] = None

    @property
    def model(self) -> SentenceTransformer:
        """Lazy load the model."""
        if self._model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def generate(
        self,
        texts: List[str],
        batch_size: int = 32,
        show_progress: bool = True,
    ) -> EmbeddingResult:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of texts to embed.
            batch_size: Batch size for encoding.
            show_progress: Whether to show progress bar.

        Returns:
            EmbeddingResult with embeddings and metadata.
        """
        if not texts:
            return EmbeddingResult(
                embeddings=np.array([]),
                texts=[],
                dimension=0,
            )

        logger.info(f"Generating embeddings for {len(texts)} texts")
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
        )

        return EmbeddingResult(
            embeddings=embeddings,
            texts=texts,
            dimension=embeddings.shape[1] if len(embeddings.shape) > 1 else 0,
        )

    def generate_single(self, text: str) -> np.ndarray:
        """Generate embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.
        """
        return self.model.encode([text], convert_to_numpy=True)[0]


class ClusteringEngine:
    """Clustering engine using HDBSCAN and UMAP."""

    def __init__(
        self,
        min_cluster_size: Optional[int] = None,
        min_samples: Optional[int] = None,
        cluster_selection_epsilon: Optional[float] = None,
        umap_n_neighbors: Optional[int] = None,
        umap_min_dist: Optional[float] = None,
        umap_n_components: Optional[int] = None,
    ):
        """Initialize the clustering engine.

        Args:
            min_cluster_size: Minimum cluster size for HDBSCAN.
            min_samples: Minimum samples for HDBSCAN core points.
            cluster_selection_epsilon: Epsilon for cluster selection.
            umap_n_neighbors: Number of neighbors for UMAP.
            umap_min_dist: Minimum distance for UMAP.
            umap_n_components: Number of components for UMAP output.
        """
        self.min_cluster_size = min_cluster_size or settings.MIN_CLUSTER_SIZE
        self.min_samples = min_samples or settings.MIN_SAMPLES
        self.cluster_selection_epsilon = (
            cluster_selection_epsilon or settings.CLUSTER_SELECTION_EPSILON
        )
        self.umap_n_neighbors = umap_n_neighbors or settings.UMAP_N_NEIGHBORS
        self.umap_min_dist = umap_min_dist or settings.UMAP_MIN_DIST
        self.umap_n_components = umap_n_components or settings.UMAP_N_COMPONENTS

        self._umap_model: Optional[umap.UMAP] = None
        self._hdbscan_model: Optional[hdbscan.HDBSCAN] = None
        self._scaler = StandardScaler()

    def reduce_dimensions(
        self,
        embeddings: np.ndarray,
        n_components: Optional[int] = None,
        fit: bool = True,
    ) -> np.ndarray:
        """Reduce embedding dimensions using UMAP.

        Args:
            embeddings: High-dimensional embeddings.
            n_components: Target dimension (default: 2 for visualization).
            fit: Whether to fit the model or use existing.

        Returns:
            Reduced dimension embeddings.
        """
        if len(embeddings) == 0:
            return np.array([])

        n_components = n_components or self.umap_n_components

        # Adjust n_neighbors if we have fewer samples
        n_neighbors = min(self.umap_n_neighbors, len(embeddings) - 1)
        n_neighbors = max(2, n_neighbors)

        if fit or self._umap_model is None:
            self._umap_model = umap.UMAP(
                n_neighbors=n_neighbors,
                min_dist=self.umap_min_dist,
                n_components=n_components,
                metric="cosine",
                random_state=42,
            )
            logger.info(
                f"Fitting UMAP with n_neighbors={n_neighbors}, "
                f"n_components={n_components}"
            )
            reduced = self._umap_model.fit_transform(embeddings)
        else:
            reduced = self._umap_model.transform(embeddings)

        return reduced

    def cluster(
        self,
        embeddings: np.ndarray,
        min_cluster_size: Optional[int] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Cluster embeddings using HDBSCAN.

        Args:
            embeddings: Embeddings to cluster (can be full-dim or reduced).
            min_cluster_size: Override minimum cluster size.

        Returns:
            Tuple of (cluster_labels, probabilities).
        """
        if len(embeddings) == 0:
            return np.array([]), np.array([])

        min_cluster_size = min_cluster_size or self.min_cluster_size
        # Ensure min_cluster_size is not larger than the dataset
        min_cluster_size = min(min_cluster_size, len(embeddings))
        min_cluster_size = max(2, min_cluster_size)

        min_samples = min(self.min_samples, min_cluster_size)
        min_samples = max(1, min_samples)

        logger.info(
            f"Clustering {len(embeddings)} embeddings with "
            f"min_cluster_size={min_cluster_size}, min_samples={min_samples}"
        )

        self._hdbscan_model = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            cluster_selection_epsilon=self.cluster_selection_epsilon,
            metric="euclidean",
            cluster_selection_method="eom",
            prediction_data=True,
        )

        self._hdbscan_model.fit(embeddings)

        return self._hdbscan_model.labels_, self._hdbscan_model.probabilities_

    def fit_predict(
        self,
        embeddings: np.ndarray,
        reduce_first: bool = True,
        min_cluster_size: Optional[int] = None,
    ) -> ClusterResult:
        """Full clustering pipeline: reduce dimensions and cluster.

        Args:
            embeddings: Original embeddings.
            reduce_first: Whether to reduce dimensions before clustering.
            min_cluster_size: Override minimum cluster size.

        Returns:
            ClusterResult with all clustering outputs.
        """
        if len(embeddings) == 0:
            return ClusterResult(
                cluster_labels=np.array([]),
                probabilities=np.array([]),
                umap_embeddings=np.array([]),
                num_clusters=0,
                noise_count=0,
            )

        # Always generate UMAP coordinates for visualization
        umap_embeddings = self.reduce_dimensions(embeddings, n_components=2)

        # For clustering, optionally use higher-dimensional reduction
        if reduce_first and embeddings.shape[1] > 50:
            # Reduce to intermediate dimension for clustering
            cluster_embeddings = self.reduce_dimensions(
                embeddings, n_components=min(50, embeddings.shape[1]), fit=False
            )
        else:
            cluster_embeddings = embeddings

        # Perform clustering
        labels, probabilities = self.cluster(cluster_embeddings, min_cluster_size)

        # Count clusters and noise
        unique_labels = set(labels)
        num_clusters = len([l for l in unique_labels if l >= 0])
        noise_count = sum(1 for l in labels if l == -1)

        logger.info(
            f"Clustering complete: {num_clusters} clusters, {noise_count} noise points"
        )

        return ClusterResult(
            cluster_labels=labels,
            probabilities=probabilities,
            umap_embeddings=umap_embeddings,
            num_clusters=num_clusters,
            noise_count=noise_count,
        )

    def get_cluster_centroids(
        self,
        embeddings: np.ndarray,
        labels: np.ndarray,
    ) -> Dict[int, np.ndarray]:
        """Calculate centroids for each cluster.

        Args:
            embeddings: Original embeddings.
            labels: Cluster labels.

        Returns:
            Dictionary mapping cluster ID to centroid embedding.
        """
        centroids = {}
        unique_labels = set(labels)

        for label in unique_labels:
            if label == -1:  # Skip noise
                continue
            mask = labels == label
            cluster_embeddings = embeddings[mask]
            centroids[label] = np.mean(cluster_embeddings, axis=0)

        return centroids

    def get_cluster_statistics(
        self,
        embeddings: np.ndarray,
        labels: np.ndarray,
        umap_embeddings: np.ndarray,
    ) -> Dict[int, Dict[str, Any]]:
        """Calculate statistics for each cluster.

        Args:
            embeddings: Original embeddings.
            labels: Cluster labels.
            umap_embeddings: 2D UMAP coordinates.

        Returns:
            Dictionary with cluster statistics.
        """
        stats = {}
        unique_labels = set(labels)

        for label in unique_labels:
            if label == -1:
                continue

            mask = labels == label
            cluster_embeddings = embeddings[mask]
            cluster_umap = umap_embeddings[mask]

            stats[label] = {
                "size": int(np.sum(mask)),
                "centroid": np.mean(cluster_embeddings, axis=0).tolist(),
                "centroid_2d": np.mean(cluster_umap, axis=0).tolist(),
                "std": float(np.std(cluster_embeddings)),
                "bbox": {
                    "min_x": float(np.min(cluster_umap[:, 0])),
                    "max_x": float(np.max(cluster_umap[:, 0])),
                    "min_y": float(np.min(cluster_umap[:, 1])),
                    "max_y": float(np.max(cluster_umap[:, 1])),
                },
            }

        return stats


class SubClusteringEngine(ClusteringEngine):
    """Engine for recursive sub-clustering within existing clusters."""

    def __init__(self, **kwargs):
        """Initialize with smaller default cluster sizes for sub-clustering."""
        super().__init__(**kwargs)
        # Use smaller defaults for sub-clustering
        self.min_cluster_size = kwargs.get("min_cluster_size", 5)
        self.min_samples = kwargs.get("min_samples", 3)

    def subcluster(
        self,
        embeddings: np.ndarray,
        parent_label: int,
        max_depth: int = 3,
        current_depth: int = 0,
    ) -> List[Dict[str, Any]]:
        """Recursively subcluster a parent cluster.

        Args:
            embeddings: Embeddings belonging to the parent cluster.
            parent_label: Label of the parent cluster.
            max_depth: Maximum recursion depth.
            current_depth: Current depth in recursion.

        Returns:
            List of sub-cluster information dictionaries.
        """
        if current_depth >= max_depth or len(embeddings) < self.min_cluster_size * 2:
            return []

        result = self.fit_predict(embeddings, reduce_first=True)

        if result.num_clusters <= 1:
            return []

        subclusters = []
        for label in range(result.num_clusters):
            mask = result.cluster_labels == label
            sub_embeddings = embeddings[mask]

            subcluster_info = {
                "parent_label": parent_label,
                "label": label,
                "depth": current_depth + 1,
                "size": int(np.sum(mask)),
                "indices": np.where(mask)[0].tolist(),
                "centroid_2d": np.mean(result.umap_embeddings[mask], axis=0).tolist(),
                "children": [],
            }

            # Recursively subcluster if large enough
            if len(sub_embeddings) >= self.min_cluster_size * 2:
                subcluster_info["children"] = self.subcluster(
                    sub_embeddings,
                    parent_label=label,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                )

            subclusters.append(subcluster_info)

        return subclusters
