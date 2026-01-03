"""결과 처리 및 통합 모듈"""

from typing import Dict, Any, List
from datetime import datetime

from ..state import AgentState


class ResultProcessor:
    """결과 통합 및 요약 처리"""

    def __init__(self):
        pass

    async def integrate_results(self, state: AgentState) -> Dict[str, Any]:
        """결과 통합"""
        print("[DEBUG] Starting result integration...")

        integrated_data = {
            "search_summary": self._summarize_search_results(state["search_results"]),
            "analysis_summary": self._summarize_analysis_results(state["analysis_results"]),
            "generation_summary": self._summarize_generation_results(state["generation_results"]),
            "total_sources": len(state["search_results"]),
            "confidence_scores": []
        }

        # 신뢰도 점수 계산
        confidence_scores = self._extract_confidence_scores(state["analysis_results"])
        integrated_data["confidence_scores"] = confidence_scores

        state["integrated_results"] = integrated_data

        print(f"[DEBUG] Result integration completed. Total sources: {integrated_data['total_sources']}")

        state["execution_steps"].append({
            "step": "result_integration",
            "result": "completed",
            "timestamp": datetime.now().isoformat()
        })

        return state

    def _summarize_search_results(self, results: List[Any]) -> Dict[str, Any]:
        """검색 결과 요약"""
        if not results:
            return {"count": 0, "sources": [], "avg_score": 0.0}

        sources = list(set([r.source for r in results if hasattr(r, 'source')]))
        scores = [float(r.score) for r in results if hasattr(r, 'score')]
        avg_score = float(sum(scores) / len(scores)) if scores else 0.0

        return {
            "count": len(results),
            "sources": sources,
            "avg_score": avg_score,
            "score_range": {
                "min": float(min(scores)) if scores else 0.0,
                "max": float(max(scores)) if scores else 0.0
            }
        }

    def _summarize_analysis_results(self, results: List[Any]) -> Dict[str, Any]:
        """분석 결과 요약"""
        if not results:
            return {"count": 0, "types": [], "total_insights": 0}

        types = list(set([r.analysis_type for r in results if hasattr(r, 'analysis_type')]))
        insights = [r.insights for r in results if hasattr(r, 'insights')]
        total_insights = sum([len(insight) for insight in insights if isinstance(insight, list)])

        return {
            "count": len(results),
            "types": types,
            "total_insights": total_insights,
            "avg_insights_per_analysis": float(total_insights / len(results)) if results else 0.0
        }

    def _summarize_generation_results(self, results: List[Any]) -> Dict[str, Any]:
        """생성 결과 요약"""
        if not results:
            return {"count": 0, "types": [], "total_size": 0}

        types = list(set([r.content_type for r in results if hasattr(r, 'content_type')]))
        sizes = [len(str(r.content)) for r in results if hasattr(r, 'content')]
        total_size = sum(sizes)

        return {
            "count": len(results),
            "types": types,
            "total_size": total_size,
            "avg_size": float(total_size / len(results)) if results else 0.0
        }

    def _extract_confidence_scores(self, analysis_results: List[Any]) -> List[float]:
        """분석 결과에서 신뢰도 점수 추출"""
        confidence_scores = []

        for analysis in analysis_results:
            if hasattr(analysis, 'confidence'):
                confidence_scores.append(float(analysis.confidence))
            elif isinstance(analysis, dict) and 'confidence' in analysis:
                confidence_scores.append(float(analysis['confidence']))

        return confidence_scores

    def get_integration_stats(self, state: AgentState) -> Dict[str, Any]:
        """통합 통계 정보 반환"""
        integrated_results = state.get("integrated_results", {})

        return {
            "total_search_results": integrated_results.get("total_sources", 0),
            "analysis_types": len(integrated_results.get("analysis_summary", {}).get("types", [])),
            "generation_types": len(integrated_results.get("generation_summary", {}).get("types", [])),
            "avg_confidence": float(
                sum(integrated_results.get("confidence_scores", [])) /
                len(integrated_results.get("confidence_scores", [1]))
            ),
            "processing_completeness": float(self._calculate_processing_completeness(state))
        }

    def _calculate_processing_completeness(self, state: AgentState) -> float:
        """처리 완성도 계산"""
        total_steps = len(state.get("required_agents", []))
        completed_steps = len([
            step for step in state.get("execution_steps", [])
            if "completed" in step.get("result", "")
        ])

        return float(completed_steps / total_steps) if total_steps > 0 else 0.0