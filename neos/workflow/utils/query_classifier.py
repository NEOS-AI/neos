"""쿼리 분류 및 의도 파악 유틸리티"""

from typing import Dict, Any, List
from datetime import datetime

from neos.utils.embeddings import embedding_manager
from ..state import AgentState


class QueryClassifier:
    """쿼리 분류 및 의도 파악"""

    def __init__(self, config):
        self.config = config
        self.intent_keywords = {
            "comparison": ["비교", "compare", "차이", "difference", "vs", "대비"],
            "data_analysis": ["분석", "analyze", "통계", "statistics", "데이터", "data", "트렌드", "trend"],
            "generation": ["생성", "만들어", "create", "generate", "작성", "write"],
            "realtime_info": ["최신", "현재", "실시간", "current", "latest", "now", "today"],
            "task_execution": ["작업", "계획", "task", "plan", "실행", "execute", "수행"],
            "financial_analysis": ["주식", "stock", "투자", "investment", "전망", "outlook", "재무", "finance"],
            "technical_analysis": ["기술", "technology", "개발", "development", "프로그래밍", "programming"]
        }

    async def classify_query(self, state: AgentState) -> Dict[str, Any]:
        """쿼리 분류 및 의도 파악"""
        query = state["original_query"]
        print(f"[DEBUG] Starting query classification for: {query[:50]}...")

        try:
            # 쿼리 임베딩 생성
            await self._generate_embedding(state, query)

            # 쿼리 의도 분류
            intent = await self._classify_intent(query)
            state["query_intent"] = intent
            print(f"[DEBUG] Intent classified as: {intent}")

            # 필요한 에이전트들 결정
            required_agents = self._determine_required_agents(query, intent)
            state["required_agents"] = required_agents
            print(f"[DEBUG] Required agents: {required_agents}")

            # 분류 결과 저장
            classification_result = self._create_classification_result(intent, required_agents, query)
            state["query_classification"] = classification_result

        except Exception as e:
            print(f"[ERROR] Query classification failed: {e}")
            # 기본값 설정
            state["query_intent"] = "information_seeking"
            state["required_agents"] = ["knowledge_search", "realtime_info_search"]
            state["query_classification"] = self._create_fallback_classification()
            raise

        # 실행 단계 기록
        state["execution_steps"].append({
            "step": "query_classification",
            "result": "completed",
            "timestamp": datetime.utcnow().isoformat()
        })

        return state

    async def _generate_embedding(self, state: AgentState, query: str) -> None:
        """쿼리 임베딩 생성"""
        if not state.get("query_embedding"):
            print(f"[DEBUG] Generating embedding for query: {query[:50]}...")
            embedding = await embedding_manager.get_embedding(query)
            state["query_embedding"] = embedding
            print(f"[DEBUG] Embedding generated, length: {len(embedding) if embedding else 'None'}")

    async def _classify_intent(self, query: str) -> str:
        """쿼리 의도 분류"""
        query_lower = query.lower()
        print("[DEBUG] Classifying query intent...")

        # 키워드 매칭 점수 계산
        intent_scores = {}
        for intent, keywords in self.intent_keywords.items():
            score = sum(1 for keyword in keywords if keyword in query_lower)
            if score > 0:
                intent_scores[intent] = score

        # 가장 높은 점수의 의도 반환
        if intent_scores:
            best_intent = max(intent_scores, key=intent_scores.get)
            print(f"[DEBUG] Intent scores: {intent_scores}, selected: {best_intent}")
            return best_intent

        # 기본 의도
        return "information_seeking"

    def _determine_required_agents(self, query: str, intent: str) -> List[str]:
        """필요한 에이전트 결정"""
        agents = []

        # 기본적으로 지식 검색은 항상 포함
        agents.append("knowledge_search")

        # 의도에 따른 에이전트 추가
        if intent == "realtime_info":
            agents.extend(["realtime_info_search", "realtime_data_search"])
        elif intent == "data_analysis":
            agents.extend(["data_analysis", "realtime_data_search"])
        elif intent == "comparison":
            agents.extend(["comparative_analysis", "realtime_info_search"])
        elif intent == "financial_analysis":
            agents.extend(["realtime_data_search", "data_analysis", "comparative_analysis"])
        elif intent == "technical_analysis":
            agents.extend(["realtime_info_search", "data_analysis"])
        elif intent == "generation":
            agents.extend(self._determine_generation_agents(query))
        else:
            # 기본적인 정보 탐색
            agents.append("realtime_info_search")

        return list(set(agents))  # 중복 제거

    def _determine_generation_agents(self, query: str) -> List[str]:
        """생성 관련 에이전트 결정"""
        generation_agents = []

        if any(keyword in query.lower() for keyword in ["이미지", "image", "그림", "picture"]):
            generation_agents.append("image_generation")
        if any(keyword in query.lower() for keyword in ["파일", "file", "문서", "document"]):
            generation_agents.append("file_processing")
        if any(keyword in query.lower() for keyword in ["작업", "task", "계획", "plan"]):
            generation_agents.append("task_creation")
        if any(keyword in query.lower() for keyword in ["api", "데이터", "data", "연동", "integration"]):
            generation_agents.append("api_call")

        return generation_agents

    def _create_classification_result(self, intent: str, required_agents: List[str], query: str) -> Dict[str, Any]:
        """분류 결과 생성"""
        confidence = self._calculate_confidence(intent, query)

        return {
            "intent": intent,
            "required_agents": required_agents,
            "confidence": confidence,
            "timestamp": datetime.utcnow().isoformat(),
            "query_length": len(query),
            "agent_count": len(required_agents)
        }

    def _create_fallback_classification(self) -> Dict[str, Any]:
        """대체 분류 결과 생성"""
        return {
            "intent": "information_seeking",
            "required_agents": ["knowledge_search", "realtime_info_search"],
            "confidence": 0.5,
            "timestamp": datetime.utcnow().isoformat(),
            "fallback": True
        }

    def _calculate_confidence(self, intent: str, query: str) -> float:
        """분류 신뢰도 계산"""
        query_lower = query.lower()

        # 의도별 키워드 매칭 수
        if intent in self.intent_keywords:
            keywords = self.intent_keywords[intent]
            matches = sum(1 for keyword in keywords if keyword in query_lower)
            keyword_confidence = min(matches * 0.2, 0.8)
        else:
            keyword_confidence = 0.5

        # 쿼리 길이 보정
        length_factor = min(len(query) / 50, 1.0) * 0.2

        # 전체 신뢰도
        total_confidence = keyword_confidence + length_factor

        return min(max(total_confidence, 0.3), 0.95)  # 0.3 ~ 0.95 범위

    def get_classification_stats(self, state: AgentState) -> Dict[str, Any]:
        """분류 통계 정보"""
        classification = state.get("query_classification", {})

        return {
            "intent": classification.get("intent", "unknown"),
            "confidence": classification.get("confidence", 0.0),
            "agent_count": len(classification.get("required_agents", [])),
            "has_embedding": bool(state.get("query_embedding")),
            "query_length": len(state.get("original_query", "")),
            "classification_time": classification.get("timestamp", "")
        }

    def validate_classification(self, state: AgentState) -> bool:
        """분류 결과 검증"""
        classification = state.get("query_classification", {})

        # 필수 필드 확인
        required_fields = ["intent", "required_agents", "confidence"]
        if not all(field in classification for field in required_fields):
            return False

        # 신뢰도 범위 확인
        confidence = classification.get("confidence", 0)
        if not (0 <= confidence <= 1):
            return False

        # 에이전트 목록 확인
        agents = classification.get("required_agents", [])
        if not isinstance(agents, list) or len(agents) == 0:
            return False

        return True