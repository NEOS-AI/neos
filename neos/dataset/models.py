"""
LLM 호출 기록 데이터 모델
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from datetime import datetime
import uuid
import json


@dataclass
class LLMCallRecord:
    """LLM 호출 기록"""

    # 식별 정보
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # 워크플로우 컨텍스트
    session_id: str = ""
    user_id: str = ""
    workflow_step: str = ""  # query_classifier, search_orchestrator, etc.
    agent_name: Optional[str] = None  # knowledge_search, data_analysis, etc.

    # LLM 설정
    provider: str = ""  # openai, anthropic
    model: str = ""
    temperature: float = 0.7
    max_tokens: Optional[int] = None

    # 입력/출력
    input_messages: List[Dict[str, Any]] = field(default_factory=list)
    output_text: str = ""
    output_metadata: Dict[str, Any] = field(default_factory=dict)

    # 토큰 사용량
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    # 성능 메트릭
    latency_ms: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None

    # 추가 메타데이터
    tags: List[str] = field(default_factory=list)
    custom_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return asdict(self)

    def to_json(self) -> str:
        """JSON 문자열로 변환"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LLMCallRecord':
        """딕셔너리에서 생성"""
        return cls(**data)

    def to_training_format(self) -> Dict[str, Any]:
        """학습 데이터 형식으로 변환 (OpenAI fine-tuning format)"""
        if not self.input_messages:
            return {}

        return {
            "messages": self.input_messages + [
                {
                    "role": "assistant",
                    "content": self.output_text
                }
            ],
            "metadata": {
                "call_id": self.call_id,
                "timestamp": self.timestamp,
                "workflow_step": self.workflow_step,
                "agent_name": self.agent_name,
                "model": self.model,
                "tokens": {
                    "prompt": self.prompt_tokens,
                    "completion": self.completion_tokens,
                    "total": self.total_tokens
                }
            }
        }

    def to_anthropic_format(self) -> Dict[str, Any]:
        """Anthropic 형식으로 변환"""
        return {
            "prompt": "\n\n".join([
                f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                for msg in self.input_messages
            ]),
            "completion": self.output_text,
            "metadata": {
                "call_id": self.call_id,
                "timestamp": self.timestamp,
                "workflow_step": self.workflow_step,
                "agent_name": self.agent_name
            }
        }


@dataclass
class DatasetMetadata:
    """데이터셋 메타데이터"""

    dataset_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    name: str = "neos_llm_dataset"
    description: str = ""

    # 통계 정보
    total_records: int = 0
    total_sessions: int = 0
    total_users: int = 0

    # 워크플로우 단계별 통계
    step_counts: Dict[str, int] = field(default_factory=dict)
    agent_counts: Dict[str, int] = field(default_factory=dict)

    # 모델별 통계
    provider_counts: Dict[str, int] = field(default_factory=dict)
    model_counts: Dict[str, int] = field(default_factory=dict)

    # 토큰 사용량 통계
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0

    # 성능 통계
    average_latency_ms: float = 0.0
    success_rate: float = 0.0

    # 기간
    start_time: Optional[str] = None
    end_time: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return asdict(self)

    def to_json(self) -> str:
        """JSON 문자열로 변환"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def update_statistics(self, records: List[LLMCallRecord]) -> None:
        """레코드 리스트로부터 통계 업데이트"""
        if not records:
            return

        self.total_records = len(records)
        self.total_sessions = len(set(r.session_id for r in records if r.session_id))
        self.total_users = len(set(r.user_id for r in records if r.user_id))

        # 워크플로우 단계별 카운트
        self.step_counts = {}
        for record in records:
            if record.workflow_step:
                self.step_counts[record.workflow_step] = self.step_counts.get(record.workflow_step, 0) + 1

        # 에이전트별 카운트
        self.agent_counts = {}
        for record in records:
            if record.agent_name:
                self.agent_counts[record.agent_name] = self.agent_counts.get(record.agent_name, 0) + 1

        # 모델별 카운트
        self.provider_counts = {}
        self.model_counts = {}
        for record in records:
            if record.provider:
                self.provider_counts[record.provider] = self.provider_counts.get(record.provider, 0) + 1
            if record.model:
                self.model_counts[record.model] = self.model_counts.get(record.model, 0) + 1

        # 토큰 통계
        self.total_prompt_tokens = sum(r.prompt_tokens or 0 for r in records)
        self.total_completion_tokens = sum(r.completion_tokens or 0 for r in records)
        self.total_tokens = sum(r.total_tokens or 0 for r in records)

        # 성능 통계
        latencies = [r.latency_ms for r in records if r.latency_ms is not None]
        self.average_latency_ms = sum(latencies) / len(latencies) if latencies else 0.0

        successful = sum(1 for r in records if r.success)
        self.success_rate = successful / len(records) if records else 0.0

        # 기간
        timestamps = [r.timestamp for r in records if r.timestamp]
        if timestamps:
            self.start_time = min(timestamps)
            self.end_time = max(timestamps)