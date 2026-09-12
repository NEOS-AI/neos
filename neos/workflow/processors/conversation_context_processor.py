"""대화 히스토리 컨텍스트 처리 모듈

Phase 3 (OpenClaw Context Engine 분리) 리팩터:
- ContextAssemblyEngine이 메모리 토큰 예산·채널 포맷팅을 담당한다.
- 이 클래스는 대화 요약(LLM) + 주제 추출을 담당하는 얇은 오케스트레이터로 유지된다.
- assembled_context (새 필드), conversation_context (하위 호환 유지) 모두 반환한다.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
import json
import asyncio

from ..state import AgentState
from neos.config.settings import settings
from neos.utils.llm_factory import create_llm
from neos.memory.context_assembly import ContextAssemblyEngine

logger = logging.getLogger(__name__)

class ConversationContextProcessor:
    """
    대화 히스토리를 분석하여 컨텍스트를 추출하는 프로세서

    역할:
    1. 대화 흐름 분석: 히스토리에서 주요 주제와 맥락 파악
    2. 참조 해결: "그것", "이전에", "아까" 등의 대명사/참조 해결
    3. 컨텍스트 생성: 다른 노드들이 활용할 요약 컨텍스트 생성

    Args:
        context_engine: ContextAssemblyEngine 인스턴스. 단위 테스트에서 mock으로 교체 가능.
                        None이면 기본 인스턴스를 생성한다.
    """

    def __init__(self, context_engine: Optional[ContextAssemblyEngine] = None):
        self._context_engine = context_engine or ContextAssemblyEngine()
        self.max_tokens = settings.HISTORY_CONTEXT_MAX_TOKENS
        self.usage_level = settings.HISTORY_USAGE_LEVEL

    def _get_llm(self, temperature: float = 0.3, max_tokens: int = None):
        """
        LLM 인스턴스를 가져옵니다.

        LLMFactory의 다중 키 캐싱을 활용하여 (model, temperature, max_tokens) 조합별로
        인스턴스를 재사용합니다.
        """
        # 자동 워크로드 — 모델을 지정하지 않아 everyday 역할 기본값으로 해석된다
        return create_llm(
            temperature=temperature,
            max_tokens=max_tokens or self.max_tokens,
            use_cache=True  # LLMFactory 캐시 활용
        )

    async def process(self, state: AgentState) -> Dict[str, Any]:
        """
        대화 히스토리를 분석하여 conversation_context 생성

        Phase 3 변경사항:
        - memory_context(3계층 메모리)가 있으면 ContextAssemblyEngine에 위임하여
          토큰 예산·채널 포맷팅을 적용한 assembled_context를 생성한다.
        - conversation_context(하위 호환)와 assembled_context 모두 반환한다.

        Args:
            state: 현재 워크플로우 상태

        Returns:
            업데이트할 상태 필드들
        """
        logger.info("[ConversationContextProcessor] Starting conversation context processing...")

        # 히스토리 활용 여부 확인
        if not state.get("enable_history_context", False):
            logger.info("[ConversationContextProcessor] History context disabled, skipping...")
            return {}

        # 히스토리 확인
        chat_history = state.get("chat_history")
        if not chat_history:
            logger.info("[ConversationContextProcessor] No chat history available, skipping...")
            return {}

        logger.info(f"[ConversationContextProcessor] Processing {len(chat_history)} messages...")

        try:
            # 대화 컨텍스트 생성과 주제 추출을 병렬로 실행 (성능 최적화)
            logger.info("[ConversationContextProcessor] Running context generation and topic extraction in parallel...")

            context_task = self._generate_context(
                chat_history=chat_history,
                current_query=state["original_query"]
            )
            topics_task = self._extract_main_topics(chat_history)

            # 병렬 실행 (하나 실패해도 다른 것은 계속 진행)
            results = await asyncio.gather(
                context_task,
                topics_task,
                return_exceptions=True
            )

            # 결과 처리
            conversation_context = results[0] if not isinstance(results[0], Exception) else ""
            main_topics = results[1] if not isinstance(results[1], Exception) else []

            # 에러 발생 시 폴백 처리
            if isinstance(results[0], Exception):
                logger.error(f"[ConversationContextProcessor] Context generation failed: {results[0]}, using fallback")
                conversation_context = self._create_simple_context(chat_history)

            if isinstance(results[1], Exception):
                logger.warning(f"[ConversationContextProcessor] Topic extraction failed: {results[1]}, using empty list")

            # Phase 3: ContextAssemblyEngine으로 메모리 컨텍스트 조립
            # memory_context가 있으면 토큰 예산·채널 포맷팅을 적용한다.
            # channel_attachments는 메모리 유무와 무관하게 조립한다 (없으면 드롭됨).
            assembled_context_dict: Optional[Dict[str, Any]] = None
            memory_context = state.get("memory_context")
            channel_attachments = state.get("channel_attachments")
            has_memory = bool(memory_context and memory_context.get("has_context"))
            has_attachments = bool(channel_attachments)
            if has_memory or has_attachments:
                try:
                    channel_type = state.get("channel_type") or "api"
                    recursive_results = None
                    # ROMA 결과가 있으면 episodic에 병합
                    if state.get("recursive_task_tree"):
                        recursive_results = {
                            "final_response": state.get("final_response", ""),
                            "summary": str(state.get("recursive_task_tree", "")),
                        }

                    assembled = await self._context_engine.assemble(
                        user_id=state.get("user_id", ""),
                        query=state.get("original_query", ""),
                        memory_context=memory_context or {},
                        channel_type=channel_type,
                        max_tokens=settings.CONTEXT_MAX_TOKENS,
                        recursive_results=recursive_results,
                        channel_attachments=channel_attachments,
                    )
                    assembled_context_dict = assembled.trimmed

                    # 채널용으로 포맷된 메모리 컨텍스트를 conversation_context에 추가
                    if assembled.formatted:
                        conversation_context = (
                            f"{conversation_context}\n\n[메모리 컨텍스트]\n{assembled.formatted}"
                            if conversation_context
                            else assembled.formatted
                        )
                    logger.info(
                        f"[ConversationContextProcessor] Memory context assembled: "
                        f"token_estimate={assembled.token_estimate}, channel={channel_type}"
                    )
                except Exception as e:
                    logger.warning(f"[ConversationContextProcessor] ContextAssemblyEngine failed: {e}")

            # 메타데이터 생성
            history_metadata = {
                "total_messages": len(chat_history),
                "context_generated_at": datetime.now().isoformat(),
                "context_length": len(conversation_context),
                "main_topics": main_topics,
                "assembled_context_available": assembled_context_dict is not None,
            }

            logger.info(
                f"[ConversationContextProcessor] Context generated successfully. "
                f"Length: {len(conversation_context)} chars, Topics: {len(main_topics)}"
            )

            # 실행 단계 기록
            execution_step = {
                "step": "conversation_context_processing",
                "result": "completed",
                "timestamp": datetime.now().isoformat(),
                "metadata": {
                    "messages_processed": len(chat_history),
                    "context_length": len(conversation_context),
                    "assembled_context": assembled_context_dict is not None,
                }
            }

            update: Dict[str, Any] = {
                "conversation_context": conversation_context,
                "history_metadata": history_metadata,
                "execution_steps": state["execution_steps"] + [execution_step],
            }
            if assembled_context_dict is not None:
                update["assembled_context"] = assembled_context_dict

            return update

        except Exception as e:
            logger.error(f"[ConversationContextProcessor] Error processing context: {e}")

            # 에러 발생 시에도 기본 컨텍스트 제공
            fallback_context = self._create_fallback_context(chat_history)

            return {
                "conversation_context": fallback_context,
                "history_metadata": {
                    "total_messages": len(chat_history),
                    "error": str(e),
                    "fallback_used": True
                },
                "errors": state["errors"] + [f"Context processing error: {str(e)}"]
            }

    async def _generate_context(
        self,
        chat_history: List[Dict[str, Any]],
        current_query: str
    ) -> str:
        """
        LLM을 사용하여 대화 히스토리를 기반으로 컨텍스트 생성

        이 메서드는 채팅 히스토리를 분석하여 현재 쿼리를 이해하는 데 필요한
        컨텍스트를 생성합니다.

        구현 전략:
        - LLM 요약: 대화의 핵심 내용만 추출
        - 참조 해결: "그것", "이전에" 등을 구체적인 대상으로 치환
        - 현재 쿼리 관련성: 현재 질문과 관련된 맥락에 집중

        Args:
            chat_history: 대화 히스토리 (역순 - 최근 메시지가 앞)
            current_query: 현재 사용자 질문

        Returns:
            생성된 컨텍스트 문자열
        """
        if self.usage_level == "disabled":
            return ""

        # 사용 레벨에 따라 히스토리 길이 조정
        if self.usage_level == "summary_only":
            message_limit = 10
        else:  # "full"
            message_limit = min(len(chat_history), settings.MAX_HISTORY_MESSAGES)

        # 최근 메시지 선택
        recent_messages = chat_history[:message_limit]

        # 메시지가 너무 적으면 단순 연결
        if len(recent_messages) <= 2:
            return self._create_simple_context(recent_messages)

        # LLM을 사용하여 요약
        try:
            llm = self._get_llm(temperature=0.3, max_tokens=self.max_tokens)

            # 대화 히스토리를 텍스트로 변환 (시간순)
            conversation_text = self._format_history_for_llm(recent_messages)

            # 요약 프롬프트
            summary_prompt = f"""다음은 사용자와 AI의 대화 히스토리입니다. 현재 사용자의 새로운 질문을 이해하는 데 필요한 맥락을 간결하게 요약해주세요.

대화 히스토리:
{conversation_text}

현재 사용자 질문: {current_query}

요구사항:
1. 현재 질문과 관련된 이전 대화 내용만 포함
2. "그것", "이전에" 등의 참조를 구체적인 대상으로 치환
3. 핵심 주제와 맥락만 간결하게 요약 (3-5문장)
4. 불필요한 인사말이나 부차적인 내용은 제외

컨텍스트 요약:"""

            # LLM 호출
            response = await llm.ainvoke(summary_prompt)
            context = response.content.strip()

            logger.info(f"[ConversationContextProcessor] LLM summary generated: {len(context)} chars")
            return context

        except Exception as e:
            logger.error(f"[ConversationContextProcessor] LLM summarization failed: {e}, falling back to simple context")
            return self._create_simple_context(recent_messages)

    def _format_history_for_llm(self, messages: List[Dict[str, Any]]) -> str:
        """대화 히스토리를 LLM이 읽기 쉬운 형식으로 변환"""
        formatted_lines = []
        for msg in reversed(messages):  # 시간순 정렬
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            formatted_lines.append(f"{role}: {content}")
        return "\n".join(formatted_lines)

    def _create_simple_context(self, messages: List[Dict[str, Any]]) -> str:
        """단순 컨텍스트 생성 (LLM 없이)"""
        if not messages:
            return ""

        context_parts = []
        for msg in reversed(messages):  # 시간순 정렬
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            context_parts.append(f"{role}: {content}")

        context = "\n".join(context_parts)

        # 토큰 제한 확인 (간단한 문자 수 기반)
        max_chars = self.max_tokens * 4
        if len(context) > max_chars:
            context = context[:max_chars] + "..."

        return context

    async def _extract_main_topics(self, chat_history: List[Dict[str, Any]]) -> List[str]:
        """
        LLM을 사용하여 대화에서 주요 주제 추출

        Args:
            chat_history: 대화 히스토리

        Returns:
            주요 주제 목록
        """
        if not chat_history or len(chat_history) < 2:
            return []

        try:
            # 최근 10개 메시지만 분석
            recent_messages = chat_history[:min(10, len(chat_history))]
            conversation_text = self._format_history_for_llm(recent_messages)

            llm = self._get_llm(temperature=0.3, max_tokens=200)

            # 주제 추출 프롬프트
            topic_prompt = f"""다음 대화에서 논의된 주요 주제나 키워드를 3-5개 추출해주세요.

대화:
{conversation_text}

주제는 다음 형식으로 JSON 배열로 반환해주세요:
["주제1", "주제2", "주제3"]

주제:"""

            # LLM 호출
            response = await llm.ainvoke(topic_prompt)
            response_text = response.content.strip()

            # JSON 파싱 시도
            try:
                # JSON 형식에서 배열 추출
                if "[" in response_text and "]" in response_text:
                    json_start = response_text.index("[")
                    json_end = response_text.rindex("]") + 1
                    topics_json = response_text[json_start:json_end]
                    topics = json.loads(topics_json)
                    return topics[:5]  # 최대 5개
                else:
                    # JSON이 아니면 쉼표로 분리
                    topics = [t.strip() for t in response_text.split(",")]
                    return topics[:5]
            except json.JSONDecodeError:
                # JSON 파싱 실패 시 단순 분리
                topics = [t.strip() for t in response_text.split(",")]
                return topics[:5]

        except Exception as e:
            logger.warning(f"[ConversationContextProcessor] Topic extraction failed: {e}")
            return []

    def _create_fallback_context(self, chat_history: List[Dict[str, Any]]) -> str:
        """
        에러 발생 시 사용할 기본 컨텍스트 생성

        Args:
            chat_history: 대화 히스토리

        Returns:
            기본 컨텍스트 문자열
        """
        if not chat_history:
            return ""

        # 가장 최근 메시지만 포함
        latest = chat_history[0]
        return f"Previous message: {latest.get('role', 'user')}: {latest.get('content', '')}"
