"""
통합 컨텍스트 레이어

모든 파이프라인의 결과를 통합하여 기존 워크플로우로 전달합니다.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from .base import (
    PipelineResult,
    InputType,
    PipelineContext
)


class UnifiedContextLayer:
    """
    통합 컨텍스트 레이어

    모든 파이프라인의 결과를 하나의 일관된 형식으로 변환하여
    기존 워크플로우(쿼리 분류기)에 전달합니다.
    """

    def __init__(self):
        self.context_history: List[Dict[str, Any]] = []

    def unify(
        self,
        pipeline_result: PipelineResult,
        original_context: PipelineContext
    ) -> Dict[str, Any]:
        """
        파이프라인 결과를 통합 컨텍스트로 변환

        Args:
            pipeline_result: 파이프라인 실행 결과
            original_context: 원본 파이프라인 컨텍스트

        Returns:
            기존 워크플로우와 호환되는 통합 컨텍스트
        """
        # 1. 기본 정보 구성
        unified = {
            # 기존 워크플로우 호환 필드
            "query": self._enhance_query(pipeline_result, original_context),
            "original_query": original_context.query,
            "user_id": original_context.user_id,
            "session_id": original_context.session_id,
            "detected_language": original_context.language,

            # 파이프라인 처리 결과
            "pipeline_metadata": {
                "input_type": pipeline_result.input_type.value,
                "processing_stage": pipeline_result.stage.value,
                "success": pipeline_result.success,
                "processing_time_ms": pipeline_result.processing_time_ms,
            },

            # 추출된 컨텐츠
            "extracted_content": {
                "text": pipeline_result.extracted_text,
                "data": pipeline_result.extracted_data,
                "metadata": pipeline_result.metadata,
            },

            # 분석 결과
            "analysis": pipeline_result.analysis,
            "insights": pipeline_result.insights,

            # 통합 컨텍스트 (LLM에게 전달할 내용)
            "unified_context": pipeline_result.unified_context,

            # 에러 정보
            "errors": [pipeline_result.error] if pipeline_result.error else [],
            "warnings": pipeline_result.warnings,

            # 타임스탬프
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 2. 입력 타입별 특수 처리
        unified = self._apply_type_specific_enhancements(unified, pipeline_result)

        # 3. 히스토리에 저장
        self.context_history.append({
            "session_id": original_context.session_id,
            "input_type": pipeline_result.input_type.value,
            "timestamp": unified["timestamp"],
            "query": original_context.query,
        })

        return unified

    def _enhance_query(
        self,
        pipeline_result: PipelineResult,
        original_context: PipelineContext
    ) -> str:
        """
        쿼리를 향상시켜 기존 워크플로우가 더 잘 이해할 수 있도록 합니다.

        텍스트가 아닌 입력의 경우, 추출된 텍스트와 메타데이터를 포함하여
        쿼리를 확장합니다.
        """
        if pipeline_result.input_type == InputType.TEXT:
            # 텍스트는 그대로 전달
            return original_context.query

        # 다른 타입들은 쿼리 + 추출된 내용으로 확장
        enhanced_parts = [f"User Query: {original_context.query}"]

        if pipeline_result.extracted_text:
            enhanced_parts.append(f"\nExtracted Content:\n{pipeline_result.extracted_text[:1000]}")

        if pipeline_result.insights:
            enhanced_parts.append(f"\nKey Insights:\n- " + "\n- ".join(pipeline_result.insights))

        return "\n".join(enhanced_parts)

    def _apply_type_specific_enhancements(
        self,
        unified: Dict[str, Any],
        pipeline_result: PipelineResult
    ) -> Dict[str, Any]:
        """입력 타입별 특수 처리"""

        input_type = pipeline_result.input_type

        if input_type == InputType.IMAGE:
            # 이미지: Vision 모델 호출 힌트 추가
            unified["requires_vision_model"] = True
            unified["image_base64"] = pipeline_result.metadata.get("image_base64")

        elif input_type == InputType.DOCUMENT:
            # 문서: 구조화된 데이터 추출 힌트
            unified["document_structure"] = pipeline_result.analysis.get("structure") if pipeline_result.analysis else None
            unified["has_tables"] = pipeline_result.metadata.get("has_tables", False)

        elif input_type == InputType.AUDIO:
            # 오디오: 전사 텍스트 강조
            unified["has_transcription"] = bool(pipeline_result.extracted_text)
            unified["audio_segments"] = pipeline_result.extracted_data.get("segments", [])

        elif input_type == InputType.MULTIMODAL:
            # 멀티모달: 크로스 레퍼런스 정보
            unified["is_multimodal"] = True
            if pipeline_result.analysis:
                unified["cross_references"] = pipeline_result.analysis.get("cross_references", {})

        return unified

    def create_workflow_state(
        self,
        unified_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        기존 워크플로우의 AgentState 포맷으로 변환

        Args:
            unified_context: 통합 컨텍스트

        Returns:
            AgentState 호환 딕셔너리
        """
        from ..state import AgentState

        # AgentState 초기화를 위한 데이터 구성
        state = {
            "user_id": unified_context.get("user_id", "unknown"),
            "session_id": unified_context.get("session_id", "unknown"),
            "original_query": unified_context.get("query", ""),
            "query_intent": None,
            "query_embedding": None,
            "detected_language": unified_context.get("detected_language"),

            # 쿼리 분류 결과 (아직 분류 전)
            "query_classification": None,
            "required_agents": [],

            # 각 에이전트 결과 (아직 실행 전)
            "search_results": [],
            "analysis_results": [],
            "generation_results": [],

            # 통합 및 검증
            "integrated_results": None,
            "quality_score": None,
            "quality_feedback": None,

            # 최종 응답
            "final_response": None,
            "response_metadata": unified_context.get("pipeline_metadata"),

            # 메타데이터
            "execution_start": datetime.now(timezone.utc),
            "execution_steps": [{
                "step": "pipeline_processing",
                "input_type": unified_context["pipeline_metadata"]["input_type"],
                "timestamp": unified_context.get("timestamp"),
            }],
            "errors": unified_context.get("errors", []),
            "retry_count": 0,

            # 성능 지표
            "execution_time_ms": unified_context["pipeline_metadata"].get("processing_time_ms"),
            "tokens_used": None,
            "api_calls_made": None,
        }

        # 파이프라인 처리 결과를 추가 컨텍스트로 저장
        state["pipeline_context"] = unified_context

        return state

    def get_history(
        self,
        session_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        컨텍스트 히스토리 조회

        Args:
            session_id: 특정 세션의 히스토리만 조회 (선택)
            limit: 최대 개수

        Returns:
            히스토리 리스트
        """
        history = self.context_history

        if session_id:
            history = [h for h in history if h["session_id"] == session_id]

        return history[-limit:]

    def clear_history(self, session_id: Optional[str] = None):
        """
        히스토리 삭제

        Args:
            session_id: 특정 세션만 삭제 (선택, None이면 전체 삭제)
        """
        if session_id:
            self.context_history = [
                h for h in self.context_history
                if h["session_id"] != session_id
            ]
        else:
            self.context_history = []
