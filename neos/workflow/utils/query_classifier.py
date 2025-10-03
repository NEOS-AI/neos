"""쿼리 분류 및 의도 파악 유틸리티"""

from typing import Dict, Any, List
from datetime import datetime
import re

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
            "technical_analysis": ["기술", "technology", "개발", "development", "프로그래밍", "programming"],
            "complex_analysis": ["심층", "종합", "포괄적", "전반적", "심도있는", "detailed", "comprehensive", "in-depth"],
            "deep_research": ["deep research", "심층 조사", "철저히", "깊이있게", "전문적인 분석", "리포트", "보고서", "detailed report", "연구"]
        }

        # 복잡한 쿼리 판별을 위한 키워드
        self.complexity_indicators = {
            "multiple_subjects": ["와", "과", "그리고", "and", ","],  # 여러 주제
            "depth_required": ["심층", "상세", "자세히", "깊이있는", "깊이있게", "detailed", "in-depth", "comprehensive", "철저히", "전문적"],
            "comparison_multiple": ["비교", "compare", "차이", "vs"],  # 비교 분석
            "multi_aspect": ["관점", "측면", "aspect", "perspective", "각도"],
        }

    async def classify_query(self, state: AgentState) -> Dict[str, Any]:
        """쿼리 분류 및 의도 파악"""
        query = state["original_query"]
        print(f"[DEBUG] Starting query classification for: {query[:50]}...")

        try:
            # 언어 감지
            detected_language = self._detect_language(query)
            state["detected_language"] = detected_language
            print(f"[DEBUG] Detected language: {detected_language}")

            # 쿼리 임베딩 생성
            await self._generate_embedding(state, query)

            # 쿼리 복잡도 분석
            complexity_score = self._analyze_query_complexity(query)
            print(f"[DEBUG] Query complexity score: {complexity_score}")

            # 쿼리 의도 분류
            intent = await self._classify_intent(query, complexity_score)
            state["query_intent"] = intent
            print(f"[DEBUG] Intent classified as: {intent}")

            # 필요한 에이전트들 결정 (복잡도 고려)
            required_agents = self._determine_required_agents(query, intent, complexity_score)
            state["required_agents"] = required_agents
            print(f"[DEBUG] Required agents: {required_agents}")

            # 분류 결과 저장 (복잡도 포함)
            classification_result = self._create_classification_result(intent, required_agents, query, complexity_score)
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

    def _detect_language(self, query: str) -> str:
        """사용자 쿼리의 주 언어 감지"""
        # 각 언어별 문자 수 카운트
        korean_chars = len(re.findall(r'[가-힣]', query))

        # 일본어: 히라가나, 가타카나, 한자 포함
        hiragana_chars = len(re.findall(r'[ぁ-ん]', query))
        katakana_chars = len(re.findall(r'[ァ-ヶー]', query))
        kanji_chars = len(re.findall(r'[一-龯]', query))

        # 일본어는 히라가나/가타카나가 있으면 확실
        japanese_chars = hiragana_chars + katakana_chars + kanji_chars
        has_kana = hiragana_chars > 0 or katakana_chars > 0

        # 중국어: 한자만 (일본어 가나가 없을 때)
        chinese_chars = kanji_chars if not has_kana else 0

        english_chars = len(re.findall(r'[a-zA-Z]', query))

        # 총 문자 수 (공백 제외)
        total_chars = len(re.findall(r'\S', query))

        if total_chars == 0:
            return 'en'  # 기본값

        # 일본어 확정: 히라가나나 가타카나가 있으면
        if has_kana and japanese_chars / total_chars >= 0.3:
            return 'ja'

        # 각 언어 비율 계산
        lang_ratios = {
            'ko': korean_chars / total_chars,
            'ja': japanese_chars / total_chars,
            'zh': chinese_chars / total_chars,
            'en': english_chars / total_chars
        }

        # 가장 높은 비율의 언어 선택 (최소 30% 이상)
        max_lang = max(lang_ratios, key=lang_ratios.get)
        max_ratio = lang_ratios[max_lang]

        # 30% 미만이면 영어로 기본 설정
        if max_ratio < 0.3:
            return 'en'

        return max_lang

    async def _generate_embedding(self, state: AgentState, query: str) -> None:
        """쿼리 임베딩 생성"""
        if not state.get("query_embedding"):
            print(f"[DEBUG] Generating embedding for query: {query[:50]}...")
            embedding = await embedding_manager.get_embedding(query)
            state["query_embedding"] = embedding
            print(f"[DEBUG] Embedding generated, length: {len(embedding) if embedding else 'None'}")

    def _analyze_query_complexity(self, query: str) -> float:
        """쿼리 복잡도 분석 (0.0 ~ 1.0)"""
        query_lower = query.lower()
        complexity_score = 0.0

        # 1. 쿼리 길이 (긴 쿼리 = 복잡함)
        length_score = min(len(query) / 100.0, 0.3)  # 최대 0.3
        complexity_score += length_score

        # 2. 여러 주제 포함 여부
        multiple_subjects_count = sum(1 for keyword in self.complexity_indicators["multiple_subjects"] if keyword in query_lower)
        if multiple_subjects_count >= 2:  # 2개 이상의 연결어
            complexity_score += 0.25

        # 3. 심층 분석 요구 키워드
        depth_keywords_count = sum(1 for keyword in self.complexity_indicators["depth_required"] if keyword in query_lower)
        if depth_keywords_count > 0:
            complexity_score += 0.2

        # 4. 비교 분석 키워드
        comparison_count = sum(1 for keyword in self.complexity_indicators["comparison_multiple"] if keyword in query_lower)
        if comparison_count > 0 and multiple_subjects_count >= 1:  # 비교 + 여러 주제
            complexity_score += 0.15

        # 5. 다각도 분석 요구
        multi_aspect_count = sum(1 for keyword in self.complexity_indicators["multi_aspect"] if keyword in query_lower)
        if multi_aspect_count > 0:
            complexity_score += 0.1

        # 최종 점수 (0.0 ~ 1.0 범위로 정규화)
        final_score = min(complexity_score, 1.0)
        print(f"[DEBUG] Complexity breakdown - length: {length_score:.2f}, multi_subject: {multiple_subjects_count}, depth: {depth_keywords_count}, comparison: {comparison_count}, multi_aspect: {multi_aspect_count}")

        return final_score

    async def _classify_intent(self, query: str, complexity_score: float = 0.0) -> str:
        """쿼리 의도 분류"""
        query_lower = query.lower()
        print("[DEBUG] Classifying query intent...")

        # 키워드 매칭 점수 계산
        intent_scores = {}
        for intent, keywords in self.intent_keywords.items():
            score = sum(1 for keyword in keywords if keyword in query_lower)
            if score > 0:
                intent_scores[intent] = score

        # 복잡도가 높으면 complex_analysis 의도 우선 고려
        if complexity_score >= 0.6:
            if "complex_analysis" in intent_scores or any(intent in intent_scores for intent in ["financial_analysis", "comparison", "data_analysis"]):
                print(f"[DEBUG] High complexity ({complexity_score:.2f}) detected, considering complex_analysis")
                intent_scores["complex_analysis"] = intent_scores.get("complex_analysis", 0) + 2  # 가중치 부여

        # 가장 높은 점수의 의도 반환
        if intent_scores:
            best_intent = max(intent_scores, key=intent_scores.get)
            print(f"[DEBUG] Intent scores: {intent_scores}, selected: {best_intent}")
            return best_intent

        # 기본 의도
        return "information_seeking"

    def _determine_required_agents(self, query: str, intent: str, complexity_score: float = 0.0) -> List[str]:
        """필요한 에이전트 결정 (복잡도 고려)"""
        agents = []

        # 0. Deep Research 활성화 조건 (최우선)
        query_lower = query.lower()

        # Deep Research 명시적 요청 또는 매우 높은 복잡도
        if intent == "deep_research" or complexity_score >= 0.75:
            print(f"[DEBUG] Deep research activated (intent: {intent}, complexity: {complexity_score:.2f})")
            agents.append("deep_research")
            return agents

        # 복잡한 분석 + 높은 복잡도 조합
        if intent == "complex_analysis" and complexity_score >= 0.65:
            print(f"[DEBUG] Deep research activated for complex analysis (complexity: {complexity_score:.2f})")
            agents.append("deep_research")
            return agents

        # 1. 복잡도가 높으면 (>= 0.5) 복합검색 에이전트 사용
        if complexity_score >= 0.5:
            print(f"[DEBUG] High complexity ({complexity_score:.2f}), using multi_query_search agent")
            agents.append("multi_query_search")
            # 복합검색 에이전트를 사용할 때는 다른 검색 에이전트는 불필요
            return agents

        # 2. 여러 기업/주제를 동시에 분석하는 경우 복합검색 사용
        connector_count = sum(1 for keyword in ["와", "과", "그리고", "and", ","] if keyword in query_lower)
        if connector_count >= 2:  # 2개 이상의 연결어가 있으면 복잡한 쿼리로 판단
            print(f"[DEBUG] Multiple subjects detected ({connector_count} connectors), using multi_query_search agent")
            agents.append("multi_query_search")
            return agents

        # 3. complex_analysis 의도면 복합검색 사용
        if intent == "complex_analysis":
            print(f"[DEBUG] Complex analysis intent detected, using multi_query_search agent")
            agents = ["multi_query_search"]
            return agents

        # 복잡도가 낮으면 기존 로직 사용
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

    def _create_classification_result(self, intent: str, required_agents: List[str], query: str, complexity_score: float = 0.0) -> Dict[str, Any]:
        """분류 결과 생성"""
        confidence = self._calculate_confidence(intent, query)

        return {
            "intent": intent,
            "required_agents": required_agents,
            "confidence": confidence,
            "complexity_score": complexity_score,
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