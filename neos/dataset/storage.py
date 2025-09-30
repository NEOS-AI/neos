"""
데이터셋 저장 및 관리

LLM 호출 레코드를 다양한 형식으로 저장하고 관리합니다.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import csv

from .models import LLMCallRecord, DatasetMetadata
from .collector import llm_call_collector

logger = logging.getLogger(__name__)


class DatasetManager:
    """데이터셋 관리자"""

    def __init__(self, base_path: str = "datasets"):
        """
        Args:
            base_path: 데이터셋 저장 기본 경로
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Dataset manager initialized with base path: {self.base_path}")

    def save_jsonl(
        self,
        records: Optional[List[LLMCallRecord]] = None,
        filename: Optional[str] = None,
        include_metadata: bool = True
    ) -> str:
        """
        JSONL 형식으로 저장 (각 줄이 하나의 JSON 객체)

        Args:
            records: 저장할 레코드 리스트 (None이면 collector의 모든 레코드)
            filename: 파일명 (None이면 자동 생성)
            include_metadata: 메타데이터 파일 함께 저장 여부

        Returns:
            저장된 파일 경로
        """
        if records is None:
            records = llm_call_collector.get_all_records()

        if not records:
            logger.warning("No records to save")
            return ""

        # 파일명 생성
        if filename is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"neos_llm_calls_{timestamp}.jsonl"

        filepath = self.base_path / filename

        # JSONL 저장
        with open(filepath, 'w', encoding='utf-8') as f:
            for record in records:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + '\n')

        logger.info(f"Saved {len(records)} records to {filepath}")

        # 메타데이터 저장
        if include_metadata:
            metadata = DatasetMetadata(
                name=filename.replace('.jsonl', ''),
                description=f"NEOS LLM calls dataset exported at {datetime.utcnow().isoformat()}"
            )
            metadata.update_statistics(records)

            metadata_path = filepath.with_suffix('.metadata.json')
            with open(metadata_path, 'w', encoding='utf-8') as f:
                f.write(metadata.to_json())

            logger.info(f"Saved metadata to {metadata_path}")

        return str(filepath)

    def save_json(
        self,
        records: Optional[List[LLMCallRecord]] = None,
        filename: Optional[str] = None,
        include_metadata: bool = True
    ) -> str:
        """
        JSON 형식으로 저장 (전체가 하나의 JSON 배열)

        Args:
            records: 저장할 레코드 리스트
            filename: 파일명
            include_metadata: 메타데이터 포함 여부

        Returns:
            저장된 파일 경로
        """
        if records is None:
            records = llm_call_collector.get_all_records()

        if not records:
            logger.warning("No records to save")
            return ""

        if filename is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"neos_llm_calls_{timestamp}.json"

        filepath = self.base_path / filename

        # 메타데이터 생성
        metadata = DatasetMetadata(
            name=filename.replace('.json', ''),
            description=f"NEOS LLM calls dataset exported at {datetime.utcnow().isoformat()}"
        )
        metadata.update_statistics(records)

        # JSON 구조 생성
        dataset = {
            "metadata": metadata.to_dict() if include_metadata else None,
            "records": [record.to_dict() for record in records]
        }

        # JSON 저장
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(dataset, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(records)} records to {filepath}")
        return str(filepath)

    def save_training_format(
        self,
        records: Optional[List[LLMCallRecord]] = None,
        filename: Optional[str] = None,
        format_type: str = "openai"
    ) -> str:
        """
        학습 데이터 형식으로 저장

        Args:
            records: 저장할 레코드 리스트
            filename: 파일명
            format_type: 형식 타입 ("openai" 또는 "anthropic")

        Returns:
            저장된 파일 경로
        """
        if records is None:
            records = llm_call_collector.get_all_records()

        if not records:
            logger.warning("No records to save")
            return ""

        if filename is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"neos_training_{format_type}_{timestamp}.jsonl"

        filepath = self.base_path / filename

        # 형식별 변환 및 저장
        with open(filepath, 'w', encoding='utf-8') as f:
            for record in records:
                if format_type == "openai":
                    training_data = record.to_training_format()
                elif format_type == "anthropic":
                    training_data = record.to_anthropic_format()
                else:
                    logger.error(f"Unknown format type: {format_type}")
                    continue

                if training_data:
                    f.write(json.dumps(training_data, ensure_ascii=False) + '\n')

        logger.info(f"Saved {len(records)} training records to {filepath}")
        return str(filepath)

    def save_csv(
        self,
        records: Optional[List[LLMCallRecord]] = None,
        filename: Optional[str] = None
    ) -> str:
        """
        CSV 형식으로 저장

        Args:
            records: 저장할 레코드 리스트
            filename: 파일명

        Returns:
            저장된 파일 경로
        """
        if records is None:
            records = llm_call_collector.get_all_records()

        if not records:
            logger.warning("No records to save")
            return ""

        if filename is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"neos_llm_calls_{timestamp}.csv"

        filepath = self.base_path / filename

        # CSV 필드 정의
        fieldnames = [
            'call_id', 'timestamp', 'session_id', 'user_id',
            'workflow_step', 'agent_name', 'provider', 'model',
            'temperature', 'prompt_tokens', 'completion_tokens',
            'total_tokens', 'latency_ms', 'success', 'error_message'
        ]

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()

            for record in records:
                row = record.to_dict()
                # 복잡한 필드 제외 (messages, metadata 등)
                row_simplified = {k: v for k, v in row.items() if k in fieldnames}
                writer.writerow(row_simplified)

        logger.info(f"Saved {len(records)} records to CSV: {filepath}")
        return str(filepath)

    def load_jsonl(self, filepath: str) -> List[LLMCallRecord]:
        """
        JSONL 파일에서 레코드 로드

        Args:
            filepath: 파일 경로

        Returns:
            레코드 리스트
        """
        records = []
        filepath = Path(filepath)

        if not filepath.exists():
            logger.error(f"File not found: {filepath}")
            return records

        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    record = LLMCallRecord.from_dict(data)
                    records.append(record)
                except Exception as e:
                    logger.error(f"Failed to parse line: {e}")

        logger.info(f"Loaded {len(records)} records from {filepath}")
        return records

    def load_json(self, filepath: str) -> tuple[List[LLMCallRecord], Optional[DatasetMetadata]]:
        """
        JSON 파일에서 레코드 및 메타데이터 로드

        Args:
            filepath: 파일 경로

        Returns:
            (레코드 리스트, 메타데이터)
        """
        filepath = Path(filepath)

        if not filepath.exists():
            logger.error(f"File not found: {filepath}")
            return [], None

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        records = []
        for record_data in data.get('records', []):
            try:
                record = LLMCallRecord.from_dict(record_data)
                records.append(record)
            except Exception as e:
                logger.error(f"Failed to parse record: {e}")

        metadata = None
        if 'metadata' in data and data['metadata']:
            try:
                metadata = DatasetMetadata(**data['metadata'])
            except Exception as e:
                logger.error(f"Failed to parse metadata: {e}")

        logger.info(f"Loaded {len(records)} records from {filepath}")
        return records, metadata

    def export_by_session(
        self,
        session_id: str,
        format: str = "jsonl"
    ) -> str:
        """
        특정 세션의 레코드만 내보내기

        Args:
            session_id: 세션 ID
            format: 출력 형식 (jsonl, json, csv)

        Returns:
            저장된 파일 경로
        """
        records = llm_call_collector.get_records(session_id=session_id)

        if not records:
            logger.warning(f"No records found for session: {session_id}")
            return ""

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"session_{session_id}_{timestamp}.{format}"

        if format == "jsonl":
            return self.save_jsonl(records, filename)
        elif format == "json":
            return self.save_json(records, filename)
        elif format == "csv":
            return self.save_csv(records, filename)
        else:
            logger.error(f"Unsupported format: {format}")
            return ""

    def export_by_agent(
        self,
        agent_name: str,
        format: str = "jsonl"
    ) -> str:
        """
        특정 에이전트의 레코드만 내보내기

        Args:
            agent_name: 에이전트 이름
            format: 출력 형식

        Returns:
            저장된 파일 경로
        """
        records = llm_call_collector.get_records(agent_name=agent_name)

        if not records:
            logger.warning(f"No records found for agent: {agent_name}")
            return ""

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"agent_{agent_name}_{timestamp}.{format}"

        if format == "jsonl":
            return self.save_jsonl(records, filename)
        elif format == "json":
            return self.save_json(records, filename)
        elif format == "csv":
            return self.save_csv(records, filename)
        else:
            logger.error(f"Unsupported format: {format}")
            return ""

    def export_by_workflow_step(
        self,
        workflow_step: str,
        format: str = "jsonl"
    ) -> str:
        """
        특정 워크플로우 단계의 레코드만 내보내기

        Args:
            workflow_step: 워크플로우 단계
            format: 출력 형식

        Returns:
            저장된 파일 경로
        """
        records = llm_call_collector.get_records(workflow_step=workflow_step)

        if not records:
            logger.warning(f"No records found for workflow step: {workflow_step}")
            return ""

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"step_{workflow_step}_{timestamp}.{format}"

        if format == "jsonl":
            return self.save_jsonl(records, filename)
        elif format == "json":
            return self.save_json(records, filename)
        elif format == "csv":
            return self.save_csv(records, filename)
        else:
            logger.error(f"Unsupported format: {format}")
            return ""

    def get_statistics(self) -> Dict[str, Any]:
        """저장된 데이터셋 통계"""
        all_records = llm_call_collector.get_all_records()

        if not all_records:
            return {"total_records": 0}

        metadata = DatasetMetadata()
        metadata.update_statistics(all_records)

        return metadata.to_dict()

    def list_datasets(self) -> List[Dict[str, Any]]:
        """저장된 데이터셋 파일 목록"""
        datasets = []

        for filepath in self.base_path.glob("*.json*"):
            if filepath.suffix in ['.json', '.jsonl']:
                stat = filepath.stat()
                datasets.append({
                    "name": filepath.name,
                    "path": str(filepath),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })

        return datasets


# 전역 데이터셋 매니저 인스턴스
dataset_manager = DatasetManager()