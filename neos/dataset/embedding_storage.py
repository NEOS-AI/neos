"""임베딩 데이터셋 저장 및 내보내기"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from neos.config.settings import settings
from .embedding_collector import embedding_collector
from .embedding_models import EmbeddingRecord

logger = logging.getLogger(__name__)


class EmbeddingDatasetManager:
    """
    EmbeddingCollector 버퍼에서 레코드를 읽어 JSONL 파일로 저장합니다.
    include_embedding=False(기본)이면 벡터는 제외하고 메타데이터만 저장해 용량을 절약합니다.
    """

    def __init__(self, dataset_dir: Optional[Path] = None):
        self.dataset_dir = (dataset_dir or Path(settings.EMBEDDING_DATASET_DIR)).resolve()

    def _ensure_dir(self) -> None:
        self.dataset_dir.mkdir(parents=True, exist_ok=True)

    async def save_jsonl(self, include_embedding: bool = False) -> Path:
        """버퍼의 레코드를 JSONL 파일로 저장하고 저장된 경로를 반환합니다."""
        self._ensure_dir()
        records: List[EmbeddingRecord] = await embedding_collector.get_all()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = "full" if include_embedding else "meta"
        out_path = self.dataset_dir / f"embeddings_{timestamp}_{suffix}.jsonl"

        with open(out_path, "w", encoding="utf-8") as f:
            for rec in records:
                line = json.dumps(rec.to_dict(include_embedding=include_embedding), ensure_ascii=False)
                f.write(line + "\n")

        logger.info(f"임베딩 데이터셋 저장 완료: {out_path} ({len(records)}건)")
        return out_path


# 전역 싱글톤
embedding_dataset_manager = EmbeddingDatasetManager()
