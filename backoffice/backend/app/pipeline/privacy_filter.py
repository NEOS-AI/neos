"""Privacy protection mechanisms for analytics data."""

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


class PIIDetector:
    """Detects and masks Personally Identifiable Information."""

    # Common PII patterns
    EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
    PHONE_PATTERN = re.compile(
        r"\b(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
    )
    SSN_PATTERN = re.compile(r"\b\d{3}[-]?\d{2}[-]?\d{4}\b")
    CREDIT_CARD_PATTERN = re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")
    IP_ADDRESS_PATTERN = re.compile(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    )
    URL_WITH_PARAMS = re.compile(
        r"https?://[^\s]+\?[^\s]*(?:user|id|token|key|password|secret)[^\s]*"
    )

    # API key patterns
    API_KEY_PATTERNS = [
        re.compile(r"\b(sk-[a-zA-Z0-9]{20,})\b"),  # OpenAI
        re.compile(r"\b(AKIA[A-Z0-9]{16})\b"),  # AWS
        re.compile(r"\b(ghp_[a-zA-Z0-9]{36})\b"),  # GitHub
    ]

    # Name patterns (simplified)
    NAME_INDICATORS = [
        "my name is",
        "i am",
        "i'm",
        "call me",
        "signed",
        "regards",
        "sincerely",
    ]

    def __init__(self, enabled: bool = True):
        """Initialize the PII detector.

        Args:
            enabled: Whether PII detection is enabled.
        """
        self.enabled = enabled

    def detect_pii(self, text: str) -> List[Dict[str, Any]]:
        """Detect PII in text.

        Args:
            text: Text to analyze.

        Returns:
            List of detected PII with type and location.
        """
        if not self.enabled:
            return []

        detections = []

        # Check each pattern
        patterns = [
            (self.EMAIL_PATTERN, "email"),
            (self.PHONE_PATTERN, "phone"),
            (self.SSN_PATTERN, "ssn"),
            (self.CREDIT_CARD_PATTERN, "credit_card"),
            (self.IP_ADDRESS_PATTERN, "ip_address"),
            (self.URL_WITH_PARAMS, "sensitive_url"),
        ]

        for pattern, pii_type in patterns:
            for match in pattern.finditer(text):
                detections.append({
                    "type": pii_type,
                    "start": match.start(),
                    "end": match.end(),
                    "value": match.group(),
                })

        # Check API keys
        for pattern in self.API_KEY_PATTERNS:
            for match in pattern.finditer(text):
                detections.append({
                    "type": "api_key",
                    "start": match.start(),
                    "end": match.end(),
                    "value": match.group(),
                })

        return detections

    def mask_pii(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Mask PII in text.

        Args:
            text: Text to mask.

        Returns:
            Tuple of (masked_text, list of detections).
        """
        detections = self.detect_pii(text)
        if not detections:
            return text, []

        # Sort by position (reverse) to replace from end
        detections.sort(key=lambda x: x["start"], reverse=True)

        masked_text = text
        for detection in detections:
            mask = f"[{detection['type'].upper()}]"
            masked_text = (
                masked_text[: detection["start"]]
                + mask
                + masked_text[detection["end"]:]
            )

        return masked_text, detections

    def has_pii(self, text: str) -> bool:
        """Check if text contains PII.

        Args:
            text: Text to check.

        Returns:
            True if PII detected.
        """
        return len(self.detect_pii(text)) > 0


class KAnonymityFilter:
    """Implements k-anonymity for cluster privacy."""

    def __init__(
        self,
        min_users: Optional[int] = None,
        min_conversations: Optional[int] = None,
    ):
        """Initialize the k-anonymity filter.

        Args:
            min_users: Minimum unique users per visible cluster.
            min_conversations: Minimum conversations per visible cluster.
        """
        self.min_users = min_users or settings.PRIVACY_MIN_USERS_PER_CLUSTER
        self.min_conversations = (
            min_conversations or settings.PRIVACY_MIN_CONVERSATIONS_PER_CLUSTER
        )

    def validate_cluster(
        self,
        unique_users: int,
        conversation_count: int,
    ) -> Tuple[bool, Optional[str]]:
        """Validate if a cluster meets privacy requirements.

        Args:
            unique_users: Number of unique users in cluster.
            conversation_count: Number of conversations in cluster.

        Returns:
            Tuple of (is_valid, reason if invalid).
        """
        if unique_users < self.min_users:
            return False, f"Below minimum user threshold ({unique_users} < {self.min_users})"

        if conversation_count < self.min_conversations:
            return False, f"Below minimum conversation threshold ({conversation_count} < {self.min_conversations})"

        return True, None

    def filter_clusters(
        self,
        clusters: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Filter clusters by privacy requirements.

        Args:
            clusters: List of cluster dictionaries.

        Returns:
            Tuple of (visible_clusters, hidden_clusters).
        """
        visible = []
        hidden = []

        for cluster in clusters:
            is_valid, reason = self.validate_cluster(
                cluster.get("unique_user_count", 0),
                cluster.get("conversation_count", 0),
            )

            if is_valid:
                visible.append(cluster)
            else:
                hidden_cluster = cluster.copy()
                hidden_cluster["privacy_reason"] = reason
                hidden.append(hidden_cluster)

        logger.info(
            f"Privacy filter: {len(visible)} visible, {len(hidden)} hidden clusters"
        )
        return visible, hidden


class PrivacyFilter:
    """Main privacy filter combining all protection mechanisms."""

    def __init__(
        self,
        pii_detection_enabled: Optional[bool] = None,
        min_users_per_cluster: Optional[int] = None,
        min_conversations_per_cluster: Optional[int] = None,
    ):
        """Initialize the privacy filter.

        Args:
            pii_detection_enabled: Enable PII detection.
            min_users_per_cluster: K-anonymity user threshold.
            min_conversations_per_cluster: K-anonymity conversation threshold.
        """
        self.pii_detector = PIIDetector(
            enabled=pii_detection_enabled
            if pii_detection_enabled is not None
            else settings.PII_DETECTION_ENABLED
        )
        self.k_anonymity = KAnonymityFilter(
            min_users=min_users_per_cluster,
            min_conversations=min_conversations_per_cluster,
        )

    def process_conversation_facets(
        self,
        facets: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], bool, Optional[str]]:
        """Process facets and apply privacy protection.

        Args:
            facets: Extracted facets dictionary.

        Returns:
            Tuple of (processed_facets, is_private, privacy_reason).
        """
        processed = facets.copy()
        is_private = False
        privacy_reason = None

        # Check and mask summary
        if "summary" in processed:
            masked_summary, detections = self.pii_detector.mask_pii(processed["summary"])
            if detections:
                processed["summary"] = masked_summary
                is_private = True
                privacy_reason = f"PII detected in summary: {len(detections)} items"

        # Check keywords
        if "keywords" in processed:
            safe_keywords = []
            for kw in processed["keywords"]:
                if not self.pii_detector.has_pii(kw):
                    safe_keywords.append(kw)
            processed["keywords"] = safe_keywords

        return processed, is_private, privacy_reason

    def validate_cluster_summary(
        self,
        summary: str,
    ) -> Tuple[str, bool]:
        """Validate and sanitize cluster summary.

        Args:
            summary: Cluster summary text.

        Returns:
            Tuple of (sanitized_summary, is_safe).
        """
        masked, detections = self.pii_detector.mask_pii(summary)

        # Additional checks for overly specific information
        specificity_keywords = [
            "specifically",
            "in particular",
            "named",
            "called",
            "known as",
        ]

        is_safe = len(detections) == 0
        for keyword in specificity_keywords:
            if keyword.lower() in summary.lower():
                is_safe = False
                break

        return masked, is_safe

    def filter_hierarchy(
        self,
        hierarchy: Dict[str, Any],
        user_counts: Dict[str, int],
    ) -> Dict[str, Any]:
        """Apply privacy filtering to cluster hierarchy.

        Args:
            hierarchy: Full cluster hierarchy.
            user_counts: Dictionary mapping cluster ID to unique user count.

        Returns:
            Filtered hierarchy.
        """
        def filter_node(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            cluster_id = node.get("id", "")
            unique_users = user_counts.get(cluster_id, 0)
            conversation_count = node.get("count", 0)

            is_valid, reason = self.k_anonymity.validate_cluster(
                unique_users, conversation_count
            )

            if not is_valid:
                logger.debug(f"Hiding cluster {cluster_id}: {reason}")
                return None

            # Validate summary
            if node.get("description"):
                sanitized, is_safe = self.validate_cluster_summary(node["description"])
                if not is_safe:
                    node["description"] = sanitized

            # Filter children
            if node.get("children"):
                filtered_children = []
                for child in node["children"]:
                    filtered_child = filter_node(child)
                    if filtered_child:
                        filtered_children.append(filtered_child)
                node["children"] = filtered_children

            return node

        return filter_node(hierarchy.copy()) or hierarchy

    def anonymize_user_id(self, user_id: str) -> str:
        """Create anonymized user identifier.

        Args:
            user_id: Original user ID.

        Returns:
            Anonymized hash.
        """
        return hashlib.sha256(user_id.encode()).hexdigest()[:16]

    def get_aggregated_statistics(
        self,
        conversations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate privacy-safe aggregated statistics.

        Args:
            conversations: List of conversation data.

        Returns:
            Aggregated statistics.
        """
        unique_users: Set[str] = set()
        task_types: Dict[str, int] = {}
        languages: Dict[str, int] = {}
        domains: Dict[str, int] = {}

        for conv in conversations:
            facets = conv.get("facets", {})

            if conv.get("user_id"):
                unique_users.add(self.anonymize_user_id(conv["user_id"]))

            for key, counter in [
                ("task_type", task_types),
                ("language", languages),
                ("domain", domains),
            ]:
                value = facets.get(key)
                if value:
                    counter[value] = counter.get(value, 0) + 1

        return {
            "total_conversations": len(conversations),
            "unique_users": len(unique_users),
            "task_type_distribution": task_types,
            "language_distribution": languages,
            "domain_distribution": domains,
        }
