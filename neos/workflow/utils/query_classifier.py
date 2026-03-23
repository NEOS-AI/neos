"""쿼리 분류 및 의도 파악 유틸리티

Phase 2.3: LLM 기반 분류 추가
- 기존 keyword 매칭에 LLM structured output 분류 추가
- LLM 실패 시 기존 keyword 기반으로 자동 fallback
- Circuit breaker 패턴으로 연속 실패 시 LLM 호출 중단
"""

import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime

import logging

from neos.config.settings import settings
from neos.utils.embeddings import embedding_manager
from neos.utils.language_detection import detect_language
from neos.utils.url_detector import has_urls, extract_urls

from ..enums import IntentType, ComplexityIndicator
from ..state import AgentState

logger = logging.getLogger(__name__)

# CR-P6-06: TASK_SCHEDULING AND 조건 — 오탐 방지용 집합 및 헬퍼
_SCHEDULING_TEMPORAL = {"매일", "매주", "매시간", "매월", "주기적으로", "every", "recurring"}
_SCHEDULING_ACTION = {"등록", "설정", "알림", "remind", "예약", "cron", "schedule", "등록해줘", "설정해줘"}


def _is_scheduling_intent(query: str) -> bool:
    """시간 표현 AND 등록 동작이 모두 있을 때만 스케줄 인텐트로 분류."""
    has_temporal = any(t in query for t in _SCHEDULING_TEMPORAL)
    has_action = any(a in query for a in _SCHEDULING_ACTION)
    return has_temporal and has_action


# LLM 분류용 프롬프트 (valid intent types 포함)
_VALID_INTENTS = [it.value for it in IntentType]

_LLM_CLASSIFICATION_PROMPT = """You are a query classification system. Analyze the user query and return a JSON object with the following fields:

- intent: one of {valid_intents}
- complexity: float 0.0-1.0 (how complex the query is)
- sub_topics: list of 1-5 specific sub-topics the query addresses
- required_capabilities: list of capabilities needed (e.g., "web_search", "data_analysis", "comparison", "realtime_data", "academic_search", "financial_data")
- confidence: float 0.0-1.0 (how confident you are in this classification)

Rules:
- "simple_conversation" for greetings, thanks, small talk
- "deep_research" for queries needing multi-source investigation, reports
- "comparison" for comparing two or more things
- "realtime_info" for current/latest/trending information
- "financial_analysis" for stocks, investments, finance
- "technical_analysis" for technology, programming, development
- "complex_analysis" for comprehensive multi-aspect analysis
- "data_analysis" for statistics, trends, data
- "youtube_search" for video/youtube related queries
- "generation" for creating content, images, files
- "task_execution" for planning, executing tasks

User query: {query}
{context_section}

Return ONLY a valid JSON object, no other text."""


class QueryClassifier:
    """쿼리 분류 및 의도 파악"""

    def __init__(self, config):
        self.config = config
        self.intent_keywords = {
            IntentType.SIMPLE.value: ["안녕", "hello", "hi", "hey", "감사", "thank", "고마워", "bye", "잘가", "좋은", "good"],
            IntentType.COMPARISON.value: ["비교", "compare", "차이", "difference", "vs", "대비"],
            IntentType.DATA_ANALYSIS.value: ["분석", "analyze", "통계", "statistics", "데이터", "data", "트렌드", "trend"],
            IntentType.GENERATION.value: ["생성", "만들어", "create", "generate", "작성", "write"],
            IntentType.REALTIME_INFO.value: ["최신", "현재", "실시간", "current", "latest", "now", "today"],
            IntentType.TASK_EXECUTION.value: ["작업", "계획", "task", "plan", "실행", "execute", "수행"],
            IntentType.FINANCIAL_ANALYSIS.value: ["주식", "stock", "투자", "investment", "전망", "outlook", "재무", "finance"],
            IntentType.TECHNICAL_ANALYSIS.value: ["기술", "technology", "개발", "development", "프로그래밍", "programming"],
            IntentType.COMPLEX_ANALYSIS.value: ["심층", "종합", "포괄적", "전반적", "심도있는", "detailed", "comprehensive", "in-depth"],
            IntentType.DEEP_RESEARCH.value: ["deep research", "심층 조사", "철저히", "깊이있게", "전문적인 분석", "리포트", "보고서", "detailed report", "연구"],
            IntentType.YOUTUBE_SEARCH.value: ["youtube", "유튜브", "video", "비디오", "영상", "tutorial", "튜토리얼", "watch", "시청"],
            # CR-P6-06: "매" 단독 접두사 제거 — "매출", "매각" 등 오탐 방지
            # AND 조건 검증은 _classify_intent()의 _is_scheduling_intent() 호출로 처리
            IntentType.TASK_SCHEDULING.value: [
                "매일", "매주", "매시간", "매월", "주기적으로", "recurring", "every",
                "cron", "schedule", "remind",
            ],
        }

        # 복잡한 쿼리 판별을 위한 키워드
        self.complexity_indicators = {
            ComplexityIndicator.MULTI_SUBJ.value: ["와", "과", "그리고", "and", ","],  # 여러 주제
            ComplexityIndicator.DEPTH_REQ.value: ["심층", "상세", "자세히", "깊이있는", "깊이있게", "detailed", "in-depth", "comprehensive", "철저히", "전문적"],
            ComplexityIndicator.COMPARISON_MULTI.value: ["비교", "compare", "차이", "vs"],  # 비교 분석
            ComplexityIndicator.MULTI_ASPECT.value: ["관점", "측면", "aspect", "perspective", "각도"],
        }


    async def classify_query(self, state: AgentState) -> Dict[str, Any]:
        """쿼리 분류 및 의도 파악 (LLM 우선, keyword fallback)

        Phase 2.3: LLM 기반 분류를 먼저 시도하고, 실패 시 keyword 기반으로 fallback.
        LLM 분류는 sub_topics, required_capabilities 등 풍부한 structured output을 제공합니다.
        """
        query = state["original_query"]
        print(f"[DEBUG] Starting query classification for: {query[:50]}...")

        # 대화 컨텍스트 확인
        conversation_context = state.get("conversation_context", "")
        if conversation_context:
            print(f"[DEBUG] Using conversation context (length: {len(conversation_context)} chars)")

        try:
            # 언어 감지
            detected_language = self._detect_language(query)
            state["detected_language"] = detected_language
            print(f"[DEBUG] Detected language: {detected_language}")

            # 쿼리 임베딩 생성
            await self._generate_embedding(state, query)

            # Phase 2.3: LLM 기반 분류 시도
            llm_result = None
            use_llm = getattr(settings, "QUERY_CLASSIFIER_USE_LLM", False)
            if use_llm and self._llm_circuit_ok():
                llm_result = await self._classify_with_llm(query, conversation_context)

            if llm_result:
                # LLM 분류 성공
                intent = llm_result["intent"]
                complexity_score = llm_result["complexity"]
                state["query_intent"] = intent
                print(f"[DEBUG] LLM classification: intent={intent}, complexity={complexity_score}")

                required_agents = self._determine_required_agents(query, intent, complexity_score)
                state["required_agents"] = required_agents

                classification_result = self._create_classification_result(
                    intent, required_agents, query, complexity_score
                )
                # LLM에서 제공하는 추가 정보 포함
                classification_result["sub_topics"] = llm_result.get("sub_topics", [])
                classification_result["required_capabilities"] = llm_result.get("required_capabilities", [])
                classification_result["classification_method"] = "llm"
                state["query_classification"] = classification_result
            else:
                # Keyword 기반 fallback
                complexity_score = self._analyze_query_complexity(query)
                print(f"[DEBUG] Query complexity score: {complexity_score}")

                intent = await self._classify_intent(query, complexity_score, conversation_context)
                state["query_intent"] = intent
                print(f"[DEBUG] Intent classified as: {intent}")

                required_agents = self._determine_required_agents(query, intent, complexity_score)
                state["required_agents"] = required_agents

                classification_result = self._create_classification_result(
                    intent, required_agents, query, complexity_score
                )
                classification_result["classification_method"] = "keyword"
                state["query_classification"] = classification_result

            print(f"[DEBUG] Required agents: {state['required_agents']}")

        except Exception as e:
            print(f"[ERROR] Query classification failed: {e}")
            state["query_intent"] = "information_seeking"
            state["required_agents"] = ["knowledge_search", "realtime_info_search"]
            state["query_classification"] = self._create_fallback_classification()
            raise

        # 실행 단계 기록
        state["execution_steps"].append({
            "step": "query_classification",
            "result": "completed",
            "timestamp": datetime.now().isoformat()
        })

        return state

    # ── Phase 2.3: LLM Classification ──────────────────────────────────

    def _llm_circuit_ok(self) -> bool:
        """LLM circuit breaker 상태 확인 (간단한 시간 기반)"""
        if not hasattr(self, "_llm_fail_count"):
            self._llm_fail_count = 0
            self._llm_last_fail = 0.0
        # 5회 연속 실패 시 60초 동안 LLM 호출 차단
        if self._llm_fail_count >= 5:
            if time.time() - self._llm_last_fail < 60:
                return False
            # 60초 후 half-open: 다시 시도
            self._llm_fail_count = 0
        return True

    async def _classify_with_llm(
        self, query: str, conversation_context: str = ""
    ) -> Optional[Dict[str, Any]]:
        """LLM을 사용한 structured query classification

        Fast/cheap 모델 (Haiku or GPT-4o-mini)을 사용합니다.
        Returns None on failure (caller falls back to keyword method).
        """
        try:
            from neos.utils.llm_factory import create_llm

            model = getattr(settings, "QUERY_CLASSIFIER_LLM_MODEL", "claude-haiku-4-5-20251001")
            timeout = getattr(settings, "QUERY_CLASSIFIER_LLM_TIMEOUT", 10)

            # 모델명으로 provider 결정
            if "claude" in model or "haiku" in model:
                provider = "anthropic"
            elif "gemini" in model:
                provider = "gemini"
            else:
                provider = "openai"

            llm = create_llm(
                provider=provider,
                model=model,
                temperature=0.0,
                max_tokens=500,
                request_timeout=timeout,
            )

            context_section = ""
            if conversation_context:
                context_section = f"\nConversation context: {conversation_context[:300]}"

            prompt = _LLM_CLASSIFICATION_PROMPT.format(
                valid_intents=", ".join(_VALID_INTENTS),
                query=query,
                context_section=context_section,
            )

            start = time.time()
            response = await llm.ainvoke(prompt)
            elapsed = time.time() - start
            print(f"[DEBUG] LLM classification completed in {elapsed:.2f}s")

            # 응답 파싱
            content = response.content if hasattr(response, "content") else str(response)
            result = self._parse_llm_classification(content)

            if result:
                # 성공 시 fail count 리셋
                self._llm_fail_count = 0
                return result
            else:
                self._llm_fail_count = getattr(self, "_llm_fail_count", 0) + 1
                self._llm_last_fail = time.time()
                return None

        except Exception as e:
            logger.warning(f"LLM query classification failed: {e}")
            self._llm_fail_count = getattr(self, "_llm_fail_count", 0) + 1
            self._llm_last_fail = time.time()
            return None

    def _parse_llm_classification(self, content: str) -> Optional[Dict[str, Any]]:
        """LLM 응답에서 JSON 추출 및 검증"""
        try:
            # JSON 블록 추출 (```json ... ``` 또는 직접 JSON)
            text = content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = json.loads(text)

            # 필수 필드 검증
            intent = result.get("intent", "")
            if intent not in _VALID_INTENTS:
                logger.warning(f"LLM returned invalid intent: {intent}")
                return None

            complexity = float(result.get("complexity", 0.5))
            complexity = max(0.0, min(1.0, complexity))

            return {
                "intent": intent,
                "complexity": complexity,
                "sub_topics": result.get("sub_topics", [])[:5],
                "required_capabilities": result.get("required_capabilities", []),
                "confidence": float(result.get("confidence", 0.7)),
            }
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse LLM classification response: {e}")
            return None

    def _detect_language(self, query: str) -> str:
        """사용자 쿼리의 주 언어 감지"""
        return detect_language(query)

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
        multiple_subjects_count = sum(1 for keyword in self.complexity_indicators[ComplexityIndicator.MULTI_SUBJ.value] if keyword in query_lower)
        if multiple_subjects_count >= 2:  # 2개 이상의 연결어
            complexity_score += 0.25

        # 3. 심층 분석 요구 키워드
        depth_keywords_count = sum(1 for keyword in self.complexity_indicators[ComplexityIndicator.DEPTH_REQ.value] if keyword in query_lower)
        if depth_keywords_count > 0:
            complexity_score += 0.2

        # 4. 비교 분석 키워드
        comparison_count = sum(1 for keyword in self.complexity_indicators[ComplexityIndicator.COMPARISON_MULTI.value] if keyword in query_lower)
        if comparison_count > 0 and multiple_subjects_count >= 1:  # 비교 + 여러 주제
            complexity_score += 0.15

        # 5. 다각도 분석 요구
        multi_aspect_count = sum(1 for keyword in self.complexity_indicators[ComplexityIndicator.MULTI_ASPECT.value] if keyword in query_lower)
        if multi_aspect_count > 0:
            complexity_score += 0.1

        # 최종 점수 (0.0 ~ 1.0 범위로 정규화)
        final_score = min(complexity_score, 1.0)
        print(f"[DEBUG] Complexity breakdown - length: {length_score:.2f}, multi_subject: {multiple_subjects_count}, depth: {depth_keywords_count}, comparison: {comparison_count}, multi_aspect: {multi_aspect_count}")

        return final_score

    async def _classify_intent(
        self,
        query: str,
        complexity_score: float = 0.0,
        conversation_context: str = ""
    ) -> str:
        """
        쿼리 의도 분류 (대화 컨텍스트 활용)

        대화 컨텍스트가 있는 경우, 쿼리를 더 정확하게 이해할 수 있습니다:
        - "그것의 가격은?" → 컨텍스트: "iPhone 15" → 가격 정보 검색
        - "비교해줘" → 컨텍스트: "GPT-4, Claude" → 비교 분석
        """
        query_lower = query.lower()
        print("[DEBUG] Classifying query intent...")

        # 컨텍스트가 있으면 쿼리와 결합하여 더 풍부한 분석
        if conversation_context:
            # TODO: 향후 LLM을 사용하여 컨텍스트 기반으로 쿼리 확장 가능
            # 현재는 단순히 키워드 매칭에 컨텍스트도 포함
            combined_text = f"{query} {conversation_context}"
            combined_lower = combined_text.lower()
            print("[DEBUG] Using combined text for intent classification (query + context)")
        else:
            combined_lower = query_lower

        # 키워드 매칭 점수 계산
        intent_scores = {}
        for intent, keywords in self.intent_keywords.items():
            score = sum(1 for keyword in keywords if keyword in combined_lower)
            if score > 0:
                intent_scores[intent] = score

        # 복잡도가 높으면 complex_analysis 의도 우선 고려
        if complexity_score >= 0.6:
            if IntentType.COMPLEX_ANALYSIS.value in intent_scores or any(intent in intent_scores for intent in [IntentType.FINANCIAL_ANALYSIS.value, IntentType.COMPARISON.value, IntentType.DATA_ANALYSIS.value]):
                print(f"[DEBUG] High complexity ({complexity_score:.2f}) detected, considering complex_analysis")
                intent_scores[IntentType.COMPLEX_ANALYSIS.value] = intent_scores.get(IntentType.COMPLEX_ANALYSIS.value, 0) + 2  # 가중치 부여

        # CR-P6-06: TASK_SCHEDULING은 시간 표현 AND 등록 동작이 모두 있을 때만 인정
        if IntentType.TASK_SCHEDULING.value in intent_scores:
            if not _is_scheduling_intent(combined_lower):
                del intent_scores[IntentType.TASK_SCHEDULING.value]

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

        # 0-0. 스케줄 등록 요청 (최우선 — 워크플로우에서 CronSkill로 직행)
        if intent == IntentType.TASK_SCHEDULING.value:
            return []  # graph.py에서 TASK_SCHEDULING 분기가 처리

        # 0-0. 간단한 대화인 경우 에이전트 불필요 (최우선)
        if intent == IntentType.SIMPLE.value:
            # 짧은 쿼리이고 복잡도가 낮으면 도구 없이 직접 응답
            if len(query) <= 50 and complexity_score < 0.3:
                print("[DEBUG] Simple conversation detected, no agents required")
                return []

        # 0-1. URL이 포함된 경우 적절한 에이전트 선택 (최우선)
        if has_urls(query):
            urls = extract_urls(query)
            print(f"[DEBUG] URLs detected in query: {urls}")
            # YouTube URL인 경우 youtube_search agent 사용 (API key 설정 시에만)
            if any("youtube.com" in url or "youtu.be" in url for url in urls):
                if settings.YOUTUBE_API_KEY:
                    print("[DEBUG] YouTube URL detected, using youtube_search agent")
                    agents.append("youtube_search")
                    return agents
                else:
                    logger.warning("YouTube URL detected but API key not configured, falling back to web_lookup")
                    print("[DEBUG] YouTube URL detected but no API key, falling back to web_lookup")
                    agents.append("web_lookup")
                    return agents
            print("[DEBUG] Using web_lookup agent for URL content extraction")
            agents.append("web_lookup")
            return agents

        # 0. Deep Research 활성화 조건 (최우선)
        query_lower = query.lower()

        # Deep Research 명시적 요청 또는 매우 높은 복잡도
        if intent == IntentType.DEEP_RESEARCH.value or complexity_score >= 0.75:
            print(f"[DEBUG] Deep research activated (intent: {intent}, complexity: {complexity_score:.2f})")
            agents.append(IntentType.DEEP_RESEARCH.value)
            return agents

        # 복잡한 분석 + 높은 복잡도 조합
        if intent == IntentType.COMPLEX_ANALYSIS.value and complexity_score >= 0.65:
            print(f"[DEBUG] Deep research activated for complex analysis (complexity: {complexity_score:.2f})")
            agents.append(IntentType.DEEP_RESEARCH.value)
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
        if intent == IntentType.COMPLEX_ANALYSIS.value:
            print("[DEBUG] Complex analysis intent detected, using multi_query_search agent")
            agents = ["multi_query_search"]
            return agents

        # 복잡도가 낮으면 기존 로직 사용
        # 기본적으로 지식 검색은 항상 포함
        agents.append("knowledge_search")

        # 의도에 따른 에이전트 추가
        if intent == IntentType.REALTIME_INFO.value:
            agents.extend(["realtime_info_search", "realtime_data_search"])
        elif intent == IntentType.DATA_ANALYSIS.value:
            agents.extend([IntentType.DATA_ANALYSIS.value, "realtime_data_search"])
        elif intent == IntentType.COMPARISON.value:
            agents.extend(["comparative_analysis", "realtime_info_search"])
        elif intent == IntentType.FINANCIAL_ANALYSIS.value:
            agents.extend(["realtime_data_search", IntentType.DATA_ANALYSIS.value, "comparative_analysis"])
        elif intent == IntentType.TECHNICAL_ANALYSIS.value:
            agents.extend(["realtime_info_search", IntentType.DATA_ANALYSIS.value])
        elif intent == IntentType.GENERATION.value:
            agents.extend(self._determine_generation_agents(query))
        elif intent == IntentType.YOUTUBE_SEARCH.value:
            if settings.YOUTUBE_API_KEY:
                agents.append("youtube_search")
            else:
                logger.warning("YouTube intent detected but API key not configured, falling back to realtime_info_search")
                agents.append("realtime_info_search")
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
            "timestamp": datetime.now().isoformat(),
            "query_length": len(query),
            "agent_count": len(required_agents)
        }

    def _create_fallback_classification(self) -> Dict[str, Any]:
        """대체 분류 결과 생성"""
        return {
            "intent": "information_seeking",
            "required_agents": ["knowledge_search", "realtime_info_search"],
            "confidence": 0.5,
            "timestamp": datetime.now().isoformat(),
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