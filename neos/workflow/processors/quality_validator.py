"""품질 검증 모듈"""

from typing import Dict, Any, List
from datetime import datetime

from ..state import AgentState


class QualityValidator:
    """워크플로우 결과 품질 검증"""

    def __init__(self, config):
        self.config = config

    async def validate_quality(self, state: AgentState) -> Dict[str, Any]:
        """품질 검증"""
        print("[DEBUG] Starting quality validation...")

        quality_metrics = {
            "completeness": self._calculate_completeness(state),
            "relevance": self._calculate_relevance(state),
            "coherence": self._calculate_coherence(state)
        }

        # 전체 품질 점수 계산
        overall_score = sum(quality_metrics.values()) / len(quality_metrics)

        state["quality_score"] = overall_score
        state["quality_feedback"] = self._generate_quality_feedback(quality_metrics)

        print(f"[DEBUG] Quality validation completed. Overall score: {overall_score:.2f}")
        print(f"[DEBUG] Quality metrics: {quality_metrics}")

        state["execution_steps"].append({
            "step": "quality_validation",
            "result": f"completed - score: {overall_score:.2f}",
            "timestamp": datetime.utcnow().isoformat()
        })

        return state

    def _calculate_completeness(self, state: AgentState) -> float:
        """완성도 계산"""
        required_agents = set(state["required_agents"])
        executed_agents = set()

        # 실행 단계에서 완료된 에이전트 추출
        for step in state["execution_steps"]:
            if "completed" in step.get("result", ""):
                step_name = step.get("step", "")
                if "orchestration" in step_name:
                    executed_agents.add(step_name.replace("_orchestration", ""))

        # 각 결과에서 실행된 에이전트 추출
        for result in state["search_results"] + state["analysis_results"] + state["generation_results"]:
            if hasattr(result, 'agent'):
                executed_agents.add(result.agent)
            elif hasattr(result, 'source'):
                executed_agents.add(result.source)

        if not required_agents:
            return 1.0

        # 기본 에이전트 타입별 완성도 계산
        agent_type_completion = {
            "search": len(state["search_results"]) > 0,
            "analysis": len(state["analysis_results"]) > 0,
            "generation": len(state["generation_results"]) > 0
        }

        completed_types = sum([1 for completed in agent_type_completion.values() if completed])
        total_required_types = len([agent for agent in required_agents if any(
            agent_type in agent for agent_type in agent_type_completion.keys()
        )])

        if total_required_types == 0:
            return 1.0

        return completed_types / max(total_required_types, len(agent_type_completion))

    def _calculate_relevance(self, state: AgentState) -> float:
        """관련성 계산"""
        search_scores = [r.score for r in state["search_results"] if hasattr(r, 'score')]

        if not search_scores:
            # 검색 결과가 없거나 점수가 없는 경우, 다른 지표로 평가
            if state["search_results"]:
                return 0.6  # 결과가 있으면 기본 점수
            else:
                return 0.3  # 결과가 없으면 낮은 점수

        avg_score = sum(search_scores) / len(search_scores)

        # 점수 분포 고려
        score_variance = sum([(score - avg_score) ** 2 for score in search_scores]) / len(search_scores)
        consistency_bonus = max(0, 0.1 - score_variance / 10)  # 점수가 일관될수록 보너스

        return min(1.0, avg_score + consistency_bonus)

    def _calculate_coherence(self, state: AgentState) -> float:
        """일관성 계산"""
        total_steps = len(state["execution_steps"])
        errors = len(state["errors"])

        if total_steps == 0:
            return 0.0

        # 기본 오류율 계산
        error_rate = errors / total_steps if total_steps > 0 else 1.0
        base_coherence = max(0.0, 1.0 - error_rate)

        # 실행 단계별 성공률 고려
        successful_steps = len([
            step for step in state["execution_steps"]
            if "completed" in step.get("result", "") and "failed" not in step.get("result", "")
        ])

        step_success_rate = successful_steps / total_steps if total_steps > 0 else 0.0

        # 두 지표의 가중 평균
        coherence_score = (base_coherence * 0.6) + (step_success_rate * 0.4)

        return min(1.0, coherence_score)

    def _generate_quality_feedback(self, metrics: Dict[str, float]) -> str:
        """품질 피드백 생성"""
        feedback_parts = []

        # 각 메트릭별 상세 피드백
        if metrics["completeness"] < 0.7:
            if metrics["completeness"] < 0.3:
                feedback_parts.append("대부분의 필요한 처리가 실행되지 않았습니다.")
            else:
                feedback_parts.append("일부 필요한 처리가 실행되지 않았습니다.")

        if metrics["relevance"] < 0.6:
            if metrics["relevance"] < 0.3:
                feedback_parts.append("검색 결과의 관련성이 매우 낮습니다.")
            else:
                feedback_parts.append("검색 결과의 관련성이 낮습니다.")

        if metrics["coherence"] < 0.8:
            if metrics["coherence"] < 0.5:
                feedback_parts.append("처리 과정에서 심각한 오류가 발생했습니다.")
            else:
                feedback_parts.append("처리 과정에서 일부 오류가 발생했습니다.")

        # 긍정적 피드백
        if not feedback_parts:
            overall_score = sum(metrics.values()) / len(metrics)
            if overall_score > 0.9:
                return "품질이 매우 우수합니다."
            else:
                return "품질이 우수합니다."

        return " ".join(feedback_parts)

    def should_regenerate(self, state: AgentState) -> str:
        """재생성 여부 결정"""
        quality_score = state.get("quality_score", 0.0)
        retry_count = state.get("retry_count", 0)

        # 최대 재시도 횟수 확인
        if retry_count >= self.config.MAX_RETRIES:
            print(f"[DEBUG] Max retries ({self.config.MAX_RETRIES}) reached, proceeding to response generation")
            return "proceed"

        # 품질 점수 확인
        if quality_score < self.config.MIN_QUALITY_SCORE:
            print(f"[DEBUG] Quality score {quality_score} < {self.config.MIN_QUALITY_SCORE}, retry {retry_count + 1}/{self.config.MAX_RETRIES}")
            state["retry_count"] = retry_count + 1
            return "regenerate"
        else:
            print(f"[DEBUG] Quality score {quality_score} >= {self.config.MIN_QUALITY_SCORE}, proceeding")
            return "proceed"

    def get_quality_report(self, state: AgentState) -> Dict[str, Any]:
        """상세 품질 보고서 생성"""
        quality_score = state.get("quality_score", 0.0)
        quality_feedback = state.get("quality_feedback", "")

        return {
            "overall_score": quality_score,
            "feedback": quality_feedback,
            "metrics": {
                "completeness": self._calculate_completeness(state),
                "relevance": self._calculate_relevance(state),
                "coherence": self._calculate_coherence(state)
            },
            "recommendations": self._generate_recommendations(state),
            "retry_count": state.get("retry_count", 0),
            "max_retries": self.config.MAX_RETRIES
        }

    def _generate_recommendations(self, state: AgentState) -> List[str]:
        """개선 권장사항 생성"""
        recommendations = []

        # 완성도 기반 권장사항
        completeness = self._calculate_completeness(state)
        if completeness < 0.7:
            recommendations.append("더 많은 에이전트를 활용하여 포괄적인 결과를 얻으세요.")

        # 관련성 기반 권장사항
        relevance = self._calculate_relevance(state)
        if relevance < 0.6:
            recommendations.append("검색 쿼리를 더 구체적으로 작성하거나 다른 키워드를 시도해보세요.")

        # 일관성 기반 권장사항
        coherence = self._calculate_coherence(state)
        if coherence < 0.8:
            recommendations.append("시스템 설정을 확인하고 네트워크 연결 상태를 점검하세요.")

        # 오류 기반 권장사항
        if len(state["errors"]) > 0:
            recommendations.append("발생한 오류를 확인하고 관련 설정을 조정하세요.")

        return recommendations