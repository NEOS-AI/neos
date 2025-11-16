"""Cost optimization through intelligent caching and budget management.

Provides LLM response caching, budget tracking, and cost optimization strategies.
"""

from typing import Dict, Any, Optional, List, Tuple
import hashlib
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CostOptimizer:
    """Optimizes LLM costs through caching and budget management."""

    def __init__(
        self,
        budget_limit: float = 100.0,
        cache_ttl: int = 3600,  # 1 hour default
        max_cache_size: int = 1000,
    ):
        """Initialize cost optimizer.

        Args:
            budget_limit: Maximum budget in USD
            cache_ttl: Cache time-to-live in seconds
            max_cache_size: Maximum number of cached responses
        """
        self.budget_limit = budget_limit
        self.cache_ttl = cache_ttl
        self.max_cache_size = max_cache_size

        # Cache: {prompt_hash: (response, timestamp, cost, metadata)}
        self.prompt_cache: Dict[str, Tuple[str, float, float, Dict]] = {}

        # Similarity cache: {prompt_hash: [(similar_hash, similarity_score), ...]}
        self.similarity_index: Dict[str, List[Tuple[str, float]]] = {}

        # Budget tracking
        self.total_cost = 0.0
        self.budget_warnings = []

        # Statistics
        self.stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "total_calls": 0,
            "total_cost_saved": 0.0,
            "similarity_hits": 0,
            "budget_exceeded": False,
        }

    def get_cached_response(
        self,
        prompt: str,
        similarity_threshold: float = 0.95
    ) -> Optional[Dict[str, Any]]:
        """Get cached response if available.

        Args:
            prompt: Input prompt
            similarity_threshold: Minimum similarity for reuse

        Returns:
            Cached response dict or None
        """
        self.stats["total_calls"] += 1

        # Calculate prompt hash
        prompt_hash = self._hash_prompt(prompt)

        # Check for exact match
        if prompt_hash in self.prompt_cache:
            response, timestamp, cost, metadata = self.prompt_cache[prompt_hash]

            # Check if cache is still valid (TTL)
            if time.time() - timestamp < self.cache_ttl:
                self.stats["cache_hits"] += 1
                self.stats["total_cost_saved"] += cost
                logger.info(
                    f"[CostOptimizer] Cache HIT (exact) - Saved ${cost:.4f}"
                )
                return {
                    "response": response,
                    "cached": True,
                    "cache_type": "exact",
                    "cost_saved": cost,
                    "metadata": metadata,
                }
            else:
                # Expired - remove from cache
                del self.prompt_cache[prompt_hash]

        # Check for similar prompts (fuzzy matching)
        similar_response = self._find_similar_cached(prompt_hash, similarity_threshold)
        if similar_response:
            self.stats["similarity_hits"] += 1
            return similar_response

        # No cache hit
        self.stats["cache_misses"] += 1
        return None

    def cache_response(
        self,
        prompt: str,
        response: str,
        cost: float,
        metadata: Dict[str, Any] = None
    ) -> None:
        """Cache LLM response.

        Args:
            prompt: Input prompt
            response: LLM response
            cost: Cost of this call
            metadata: Optional metadata
        """
        prompt_hash = self._hash_prompt(prompt)
        timestamp = time.time()

        # Check cache size limit
        if len(self.prompt_cache) >= self.max_cache_size:
            self._evict_oldest()

        # Store in cache
        self.prompt_cache[prompt_hash] = (
            response,
            timestamp,
            cost,
            metadata or {}
        )

        logger.debug(
            f"[CostOptimizer] Cached response (hash: {prompt_hash[:8]}..., cost: ${cost:.4f})"
        )

    def track_cost(self, cost: float, phase: str = "unknown") -> bool:
        """Track cost and check budget.

        Args:
            cost: Cost to add
            phase: Research phase name

        Returns:
            True if within budget, False if exceeded
        """
        self.total_cost += cost

        # Check budget limit
        if self.total_cost > self.budget_limit:
            if not self.stats["budget_exceeded"]:
                self.stats["budget_exceeded"] = True
                warning = {
                    "timestamp": datetime.now().isoformat(),
                    "phase": phase,
                    "total_cost": self.total_cost,
                    "budget_limit": self.budget_limit,
                    "overage": self.total_cost - self.budget_limit,
                }
                self.budget_warnings.append(warning)
                logger.warning(
                    f"[CostOptimizer] ⚠️ Budget EXCEEDED! "
                    f"${self.total_cost:.2f} > ${self.budget_limit:.2f} "
                    f"(Overage: ${self.total_cost - self.budget_limit:.2f})"
                )
            return False

        # Warn at 80% and 90%
        usage_pct = (self.total_cost / self.budget_limit) * 100
        if usage_pct >= 90 and len(self.budget_warnings) < 2:
            logger.warning(
                f"[CostOptimizer] ⚠️ Budget at {usage_pct:.1f}% "
                f"(${self.total_cost:.2f} / ${self.budget_limit:.2f})"
            )
        elif usage_pct >= 80 and len(self.budget_warnings) < 1:
            logger.warning(
                f"[CostOptimizer] Budget at {usage_pct:.1f}% "
                f"(${self.total_cost:.2f} / ${self.budget_limit:.2f})"
            )

        return True

    def check_budget_available(self, estimated_cost: float = 0.0) -> bool:
        """Check if budget allows for additional cost.

        Args:
            estimated_cost: Estimated cost of next operation

        Returns:
            True if budget available
        """
        return (self.total_cost + estimated_cost) <= self.budget_limit

    def _hash_prompt(self, prompt: str) -> str:
        """Generate hash for prompt.

        Args:
            prompt: Input prompt

        Returns:
            SHA256 hash string
        """
        # Normalize prompt (lowercase, strip whitespace)
        normalized = prompt.lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()

    def _find_similar_cached(
        self,
        prompt_hash: str,
        threshold: float
    ) -> Optional[Dict[str, Any]]:
        """Find similar cached response using fuzzy matching.

        Args:
            prompt_hash: Hash of current prompt
            threshold: Similarity threshold

        Returns:
            Similar cached response or None
        """
        # Simple similarity check (can be enhanced with embeddings)
        # For now, just check if prompt hash prefix matches (first 16 chars)
        # This is a placeholder - in production, use proper similarity search

        prefix = prompt_hash[:16]

        for cached_hash, (response, timestamp, cost, metadata) in self.prompt_cache.items():
            # Check TTL
            if time.time() - timestamp >= self.cache_ttl:
                continue

            # Simple prefix matching (placeholder for proper similarity)
            if cached_hash[:16] == prefix and cached_hash != prompt_hash:
                # Calculate simple similarity (Jaccard for demonstration)
                similarity = self._simple_similarity(prompt_hash, cached_hash)

                if similarity >= threshold:
                    self.stats["cache_hits"] += 1
                    self.stats["total_cost_saved"] += cost
                    logger.info(
                        f"[CostOptimizer] Cache HIT (similar, {similarity:.2f}) - "
                        f"Saved ${cost:.4f}"
                    )
                    return {
                        "response": response,
                        "cached": True,
                        "cache_type": "similar",
                        "similarity": similarity,
                        "cost_saved": cost,
                        "metadata": metadata,
                    }

        return None

    def _simple_similarity(self, hash1: str, hash2: str) -> float:
        """Calculate simple character-level similarity.

        Args:
            hash1: First hash
            hash2: Second hash

        Returns:
            Similarity score (0-1)
        """
        # Character-level Jaccard similarity
        set1 = set(hash1)
        set2 = set(hash2)

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0

    def _evict_oldest(self) -> None:
        """Evict oldest cache entry when limit reached."""
        if not self.prompt_cache:
            return

        # Find oldest entry
        oldest_hash = min(
            self.prompt_cache.keys(),
            key=lambda h: self.prompt_cache[h][1]  # timestamp
        )

        del self.prompt_cache[oldest_hash]
        logger.debug(f"[CostOptimizer] Evicted oldest cache entry: {oldest_hash[:8]}...")

    def clear_cache(self) -> None:
        """Clear all cached responses."""
        cache_size = len(self.prompt_cache)
        self.prompt_cache.clear()
        self.similarity_index.clear()
        logger.info(f"[CostOptimizer] Cleared {cache_size} cached responses")

    def get_stats(self) -> Dict[str, Any]:
        """Get optimizer statistics.

        Returns:
            Statistics dictionary
        """
        total_calls = self.stats["total_calls"]
        cache_hits = self.stats["cache_hits"]

        hit_rate = (cache_hits / total_calls * 100) if total_calls > 0 else 0

        return {
            **self.stats,
            "cache_hit_rate": hit_rate,
            "cache_size": len(self.prompt_cache),
            "total_cost": self.total_cost,
            "budget_remaining": max(0, self.budget_limit - self.total_cost),
            "budget_usage_pct": (self.total_cost / self.budget_limit * 100)
                               if self.budget_limit > 0 else 0,
        }

    def get_summary(self) -> str:
        """Get human-readable summary.

        Returns:
            Summary string
        """
        stats = self.get_stats()

        summary = f"""
CostOptimizer Summary:
  Cache Hit Rate: {stats['cache_hit_rate']:.1f}%
  Total Calls: {stats['total_calls']}
  Cache Hits: {stats['cache_hits']} (Exact: {stats['cache_hits'] - stats['similarity_hits']}, Similar: {stats['similarity_hits']})
  Cache Misses: {stats['cache_misses']}
  Cost Saved: ${stats['total_cost_saved']:.2f}
  Total Cost: ${stats['total_cost']:.2f}
  Budget: ${self.budget_limit:.2f}
  Remaining: ${stats['budget_remaining']:.2f}
  Usage: {stats['budget_usage_pct']:.1f}%
  Budget Status: {'⚠️ EXCEEDED' if stats['budget_exceeded'] else '✅ OK'}
"""
        return summary.strip()

    def set_budget_limit(self, new_limit: float) -> None:
        """Update budget limit.

        Args:
            new_limit: New budget limit in USD
        """
        old_limit = self.budget_limit
        self.budget_limit = new_limit
        logger.info(
            f"[CostOptimizer] Budget limit updated: ${old_limit:.2f} → ${new_limit:.2f}"
        )

        # Check if now within budget
        if self.stats["budget_exceeded"] and self.total_cost <= new_limit:
            self.stats["budget_exceeded"] = False
            logger.info("[CostOptimizer] ✅ Back within budget")
