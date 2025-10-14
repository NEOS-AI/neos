"""
멀티모달 처리 파이프라인

여러 타입의 입력을 동시에 처리하고 통합 분석합니다.
"""

from typing import Dict, Any, List, Optional
import asyncio

from .base import (
    BasePipeline,
    InputType,
    PipelineContext,
    PipelineResult,
    ProcessingStage,
    FileInput,
    PipelineRegistry
)


class MultiModalPipeline(BasePipeline):
    """
    멀티모달 처리 파이프라인

    여러 타입의 입력을 병렬로 처리하고 크로스 레퍼런스 분석을 수행합니다.
    """

    def __init__(self):
        super().__init__(name="MultiModalPipeline", input_type=InputType.MULTIMODAL)
        self.registry = PipelineRegistry()

    async def validate(self, context: PipelineContext) -> bool:
        """멀티모달 입력 검증"""
        if not context.files or len(context.files) < 2:
            return False

        # 각 파일이 유효한지 확인
        return True

    async def preprocess(self, context: PipelineContext) -> PipelineContext:
        """멀티모달 전처리 - 입력 그룹핑"""
        # 파일들을 타입별로 그룹핑
        grouped_files = self._group_files_by_type(context.files)
        context.additional_context["grouped_files"] = grouped_files

        return context

    async def extract(self, context: PipelineContext) -> PipelineResult:
        """멀티모달 정보 추출 - 병렬 처리"""
        grouped_files = context.additional_context.get("grouped_files", {})

        # 각 타입별로 적절한 파이프라인 호출 (병렬 처리)
        tasks = []
        for input_type, files in grouped_files.items():
            pipeline = self.registry.get(input_type)
            if pipeline:
                # 각 타입별 서브 컨텍스트 생성
                sub_context = PipelineContext(
                    query=context.query,
                    input_type=input_type,
                    files=files,
                    user_id=context.user_id,
                    session_id=context.session_id,
                    language=context.language,
                    preferences=context.preferences,
                    additional_context=context.additional_context
                )
                tasks.append(self._process_subpipeline(pipeline, sub_context))

        # 병렬 실행
        sub_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 결과 통합
        combined_result = self._combine_results(sub_results, context)

        return combined_result

    async def analyze(self, result: PipelineResult, context: PipelineContext) -> PipelineResult:
        """멀티모달 분석 - 크로스 레퍼런스"""
        # 크로스 레퍼런스 분석
        cross_analysis = self._cross_reference_analysis(result.extracted_data)

        result.analysis = {
            "input_types": list(result.extracted_data.keys()),
            "total_files": len(context.files),
            "cross_references": cross_analysis,
            "integration_quality": self._assess_integration_quality(result.extracted_data),
        }

        # 인사이트 생성
        insights = []
        insights.append(f"Multimodal input with {len(context.files)} files")
        insights.append(f"Types: {', '.join(result.extracted_data.keys())}")

        if cross_analysis.get("connections"):
            insights.append(f"Found {len(cross_analysis['connections'])} cross-references")

        result.insights = insights

        # 통합 컨텍스트 생성
        result.unified_context = self._create_unified_context(result, context)

        return result

    def _group_files_by_type(self, files: List[FileInput]) -> Dict[InputType, List[FileInput]]:
        """파일들을 타입별로 그룹핑"""
        from .router import InputRouter
        router = InputRouter()

        grouped = {}
        for file in files:
            file_type = router._classify_file(file)
            if file_type not in grouped:
                grouped[file_type] = []
            grouped[file_type].append(file)

        return grouped

    async def _process_subpipeline(self, pipeline: BasePipeline, context: PipelineContext) -> PipelineResult:
        """서브 파이프라인 처리"""
        try:
            result = await pipeline.process(context)
            return result
        except Exception as e:
            return PipelineResult(
                success=False,
                input_type=context.input_type,
                stage=ProcessingStage.FAILED,
                error=f"Subpipeline error: {str(e)}"
            )

    def _combine_results(self, sub_results: List[PipelineResult], context: PipelineContext) -> PipelineResult:
        """서브 결과들을 하나로 통합"""
        combined_text = []
        combined_data = {}
        combined_metadata = {}
        all_insights = []

        for result in sub_results:
            if isinstance(result, Exception):
                continue

            if result.success:
                # 텍스트 통합
                if result.extracted_text:
                    combined_text.append(result.extracted_text)

                # 데이터 통합
                input_type_name = result.input_type.value
                combined_data[input_type_name] = result.extracted_data

                # 메타데이터 통합
                combined_metadata[input_type_name] = result.metadata

                # 인사이트 통합
                all_insights.extend(result.insights)

        return PipelineResult(
            success=True,
            input_type=InputType.MULTIMODAL,
            stage=ProcessingStage.EXTRACTION,
            extracted_text="\n\n---\n\n".join(combined_text),
            extracted_data=combined_data,
            metadata=combined_metadata,
            insights=all_insights
        )

    def _cross_reference_analysis(self, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        크로스 레퍼런스 분석

        여러 모달리티 간의 연관성을 찾습니다.
        예: 이미지 속 텍스트와 문서 내용의 일치, 오디오 전사와 문서 내용 비교 등
        """
        connections = []

        # 간단한 키워드 기반 연결 찾기 (TODO: 더 정교한 분석 필요)
        texts = {}
        for modal_type, data in extracted_data.items():
            if isinstance(data, dict) and "text" in data:
                texts[modal_type] = data["text"]

        # 모든 페어별 비교
        modal_types = list(texts.keys())
        for i in range(len(modal_types)):
            for j in range(i + 1, len(modal_types)):
                type_a = modal_types[i]
                type_b = modal_types[j]

                # 간단한 단어 겹침 분석
                words_a = set(texts[type_a].lower().split()) if texts[type_a] else set()
                words_b = set(texts[type_b].lower().split()) if texts[type_b] else set()

                if words_a and words_b:
                    overlap = words_a & words_b
                    if len(overlap) > 5:  # 5개 이상 공통 단어
                        connections.append({
                            "source": type_a,
                            "target": type_b,
                            "connection_type": "keyword_overlap",
                            "strength": len(overlap) / max(len(words_a), len(words_b)),
                            "common_keywords": list(overlap)[:10]
                        })

        return {
            "connections": connections,
            "total_modalities": len(extracted_data),
            "has_cross_references": len(connections) > 0
        }

    def _assess_integration_quality(self, extracted_data: Dict[str, Any]) -> str:
        """통합 품질 평가"""
        quality_score = 0

        # 각 모달리티가 성공적으로 추출되었는지
        for data in extracted_data.values():
            if isinstance(data, dict) and data.get("text"):
                quality_score += 1

        if quality_score >= len(extracted_data):
            return "high"
        elif quality_score >= len(extracted_data) / 2:
            return "medium"
        else:
            return "low"

    def _create_unified_context(self, result: PipelineResult, context: PipelineContext) -> str:
        """통합 컨텍스트 생성"""
        sections = [f"**Multimodal Analysis Request**\n\n**Query**: {context.query}\n"]

        # 각 모달리티별 요약
        for modal_type, data in result.extracted_data.items():
            sections.append(f"\n### {modal_type.upper()} Content\n")

            if isinstance(data, dict):
                if "text" in data:
                    text_preview = data["text"][:200] if data["text"] else "No text"
                    sections.append(f"{text_preview}...\n")

        # 크로스 레퍼런스 요약
        if result.analysis and result.analysis.get("cross_references", {}).get("connections"):
            sections.append("\n### Cross-References\n")
            for conn in result.analysis["cross_references"]["connections"][:3]:
                sections.append(
                    f"- {conn['source']} ↔ {conn['target']}: "
                    f"{conn['connection_type']} (strength: {conn['strength']:.2f})\n"
                )

        return "".join(sections)
