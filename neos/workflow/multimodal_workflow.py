"""
멀티모달 워크플로우 통합

기존 워크플로우와 새로운 파이프라인 시스템을 연결합니다.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from .pipelines import (
    InputRouter,
    TextPipeline,
    ImagePipeline,
    DocumentPipeline,
    AudioPipeline,
    MultiModalPipeline,
    UnifiedContextLayer,
    PipelineRegistry,
    InputType,
    FileInput
)
from .graph import MultiAgentWorkflow


class MultiModalWorkflow:
    """
    멀티모달 워크플로우

    파일 입력을 처리하고 기존 워크플로우와 통합합니다.
    """

    def __init__(self):
        # 파이프라인 레지스트리 초기화
        self._initialize_pipelines()

        # 컴포넌트 초기화
        self.router = InputRouter()
        self.unified_context_layer = UnifiedContextLayer()
        self.agent_workflow = MultiAgentWorkflow()

    def _initialize_pipelines(self):
        """파이프라인 등록"""
        registry = PipelineRegistry()

        # 각 파이프라인 인스턴스 생성 및 등록
        registry.register(InputType.TEXT, TextPipeline())
        registry.register(InputType.IMAGE, ImagePipeline())
        registry.register(InputType.DOCUMENT, DocumentPipeline())
        registry.register(InputType.AUDIO, AudioPipeline())
        registry.register(InputType.MULTIMODAL, MultiModalPipeline())

        print(f"[MultiModalWorkflow] Registered {len(registry.get_all())} pipelines")

    async def process(
        self,
        query: str,
        files: Optional[List[Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        멀티모달 입력을 처리합니다.

        Args:
            query: 사용자 쿼리
            files: 첨부 파일 정보 (선택)
                   [{"file_path": "...", "file_content": bytes, ...}]
            user_id: 사용자 ID
            session_id: 세션 ID
            **kwargs: 추가 컨텍스트

        Returns:
            최종 처리 결과
        """
        start_time = datetime.now(timezone.utc)

        try:
            # 1. 파일 입력 변환
            file_inputs = self._convert_files(files) if files else []

            # 2. 입력 라우팅
            context, pipeline = self.router.route(
                query=query,
                files=file_inputs,
                user_id=user_id,
                session_id=session_id,
                **kwargs
            )

            print(f"[MultiModalWorkflow] Routed to {context.input_type.value} pipeline")

            # 3. 파이프라인 실행 (파일이 있을 경우)
            if pipeline:
                pipeline_result = await pipeline.process(context)

                if not pipeline_result.success:
                    return {
                        "success": False,
                        "error": pipeline_result.error,
                        "stage": "pipeline_processing"
                    }

                # 4. 통합 컨텍스트 생성
                unified_context = self.unified_context_layer.unify(
                    pipeline_result=pipeline_result,
                    original_context=context
                )

                print(f"[MultiModalWorkflow] Unified context created for {context.input_type.value}")

                # 5. 워크플로우 상태 생성
                workflow_state = self.unified_context_layer.create_workflow_state(unified_context)

            else:
                # 파이프라인이 없으면 (TEXT만 해당) 직접 워크플로우 상태 생성
                workflow_state = {
                    "user_id": user_id or "unknown",
                    "session_id": session_id or "unknown",
                    "query": query,  # Added for execute_workflow compatibility
                    "original_query": query,
                    "detected_language": context.language,
                    "query_intent": None,
                    "query_embedding": None,
                    "query_classification": None,
                    "required_agents": [],
                    "search_results": [],
                    "analysis_results": [],
                    "generation_results": [],
                    "integrated_results": None,
                    "quality_score": None,
                    "quality_feedback": None,
                    "final_response": None,
                    "response_metadata": None,
                    "execution_start": datetime.now(timezone.utc),
                    "execution_steps": [],
                    "errors": [],
                    "retry_count": 0,
                    "execution_time_ms": None,
                    "tokens_used": None,
                    "api_calls_made": None,
                }

            # 6. 기존 워크플로우 실행
            print("[MultiModalWorkflow] Starting agent workflow...")
            final_result = await self.agent_workflow.execute_workflow(workflow_state)

            # 7. 실행 시간 계산
            end_time = datetime.now(timezone.utc)
            total_time_ms = (end_time - start_time).total_seconds() * 1000

            # 8. 최종 결과 반환
            return {
                "success": True,
                "result": final_result,
                "input_type": context.input_type.value,
                "processing_time_ms": total_time_ms,
                "timestamp": end_time.isoformat(),
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stage": "workflow_execution",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def _convert_files(self, files: List[Dict[str, Any]]) -> List[FileInput]:
        """
        딕셔너리 형태의 파일 정보를 FileInput 객체로 변환

        Args:
            files: 파일 정보 딕셔너리 리스트

        Returns:
            FileInput 객체 리스트
        """
        file_inputs = []

        for file_dict in files:
            file_input = FileInput(
                file_path=file_dict.get("file_path"),
                file_content=file_dict.get("file_content"),
                mime_type=file_dict.get("mime_type"),
                file_size=file_dict.get("file_size"),
                filename=file_dict.get("filename"),
                url=file_dict.get("url"),
            )
            file_inputs.append(file_input)

        return file_inputs

    def get_supported_types(self) -> List[str]:
        """지원하는 입력 타입 목록"""
        pipelines = self.router.get_available_pipelines()
        return [input_type.value for input_type in pipelines.keys()]

    def is_file_supported(self, filename: str) -> bool:
        """
        파일이 지원되는지 확인

        Args:
            filename: 파일명

        Returns:
            지원 여부
        """
        from pathlib import Path

        ext = Path(filename).suffix.lower()

        # 라우터의 확장자 매핑 확인
        return ext in self.router.EXTENSION_MAPPING


# 편의 함수
async def process_multimodal_query(
    query: str,
    files: Optional[List[Dict[str, Any]]] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    멀티모달 쿼리 처리 편의 함수

    Args:
        query: 사용자 쿼리
        files: 첨부 파일
        user_id: 사용자 ID
        session_id: 세션 ID
        **kwargs: 추가 컨텍스트

    Returns:
        처리 결과
    """
    workflow = MultiModalWorkflow()
    return await workflow.process(
        query=query,
        files=files,
        user_id=user_id,
        session_id=session_id,
        **kwargs
    )
