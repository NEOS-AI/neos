"""임베딩 데이터셋 수집을 위한 데이터 모델"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import uuid
from datetime import datetime, timezone


@dataclass
class EmbeddingRecord:
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    provider: str = ""
    model: str = ""
    dimension: int = 0
    modality: str = "text"          # "text" | "image" | "video"
    mime_type: Optional[str] = None
    input_text: Optional[str] = None
    input_size_bytes: int = 0       # 이미지/영상 파일 크기 (바이트), 텍스트는 0
    embedding: Optional[List[float]] = None
    task_type: str = "retrieval_document"
    latency_ms: float = 0.0
    success: bool = True
    error_message: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def to_dict(self, include_embedding: bool = False) -> dict:
        d = {
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "provider": self.provider,
            "model": self.model,
            "dimension": self.dimension,
            "modality": self.modality,
            "mime_type": self.mime_type,
            "input_text": self.input_text,
            "input_size_bytes": self.input_size_bytes,
            "task_type": self.task_type,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }
        if include_embedding:
            d["embedding"] = self.embedding
        return d
