"""
Chat LLM Service

채팅 기능을 위한 LLM 통합 서비스
실시간 스트리밍, 비용 추적, 대화 컨텍스트 관리
"""

from typing import Dict, Any, List, Optional, AsyncGenerator
import json
import time
import anthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import extract_text_from_response
from neos.utils.cost_calculator import cost_calculator
from neos.utils.logger import get_logger
from neos.services.context_optimizer import context_optimizer
from neos.config.model_routing import resolve_model
from neos.config.settings import settings
from neos.providers.anthropic import normalize_anthropic_request
from neos.tools.tool_search.search_tools_handler import SEARCH_TOOLS_TOOL

logger = get_logger(__name__)


def resolve_conversation_chat_model(model_name: str | None) -> str:
    """Resolve a stored conversation choice or the everyday chat role."""
    return resolve_model(
        config=settings.config.model_routing,
        provider="anthropic",
        role="everyday",
        conversation_model=model_name,
    ).model


class ChatLLMService:
    """채팅 LLM 서비스"""

    def __init__(self):
        self.default_provider = "anthropic"

    def _extract_provider_from_model(self, model_name: str) -> str:
        """모델의 provider를 결정한다.

        모델 카탈로그가 우선이다. 이름만 보던 예전 방식은 `gpt`/`claude`가
        들어 있지 않은 모델을 놓쳐 기본 provider로 잘못 보냈다.

        카탈로그는 allowlist가 아니므로, 모르는 이름은 예전 휴리스틱으로
        폴백한다 — 카탈로그 갱신 전에도 신종 모델을 쓸 수 있어야 한다.
        """
        from neos.config.model_config import provider_for_model

        catalogued = provider_for_model(model_name)
        if catalogued is not None:
            return catalogued

        lowered = model_name.lower()
        if "gpt" in lowered:
            return "openai"
        if "claude" in lowered:
            return "anthropic"
        return self.default_provider

    def _build_messages(
        self,
        conversation_messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> List:
        """대화 메시지를 LangChain 메시지 형식으로 변환"""
        messages = []

        # 시스템 프롬프트 추가
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))

        # 대화 메시지 변환
        for msg in conversation_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                messages.append(SystemMessage(content=content))

        return messages

    def _extract_usage_from_response(self, response: Any) -> Dict[str, int]:
        """응답에서 토큰 사용량 추출"""
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        # response_metadata에서 추출 (Anthropic/OpenAI)
        if hasattr(response, "response_metadata"):
            metadata = response.response_metadata

            # Anthropic 형식
            if "usage" in metadata:
                anthropic_usage = metadata["usage"]
                usage["prompt_tokens"] = anthropic_usage.get("input_tokens", 0)
                usage["completion_tokens"] = anthropic_usage.get("output_tokens", 0)
                usage["total_tokens"] = (
                    usage["prompt_tokens"] + usage["completion_tokens"]
                )

            # OpenAI 형식
            elif "token_usage" in metadata:
                token_usage = metadata["token_usage"]
                usage["prompt_tokens"] = token_usage.get("prompt_tokens", 0)
                usage["completion_tokens"] = token_usage.get("completion_tokens", 0)
                usage["total_tokens"] = token_usage.get("total_tokens", 0)

        return usage

    def _extract_finish_reason(self, response: Any) -> Optional[str]:
        """응답에서 finish_reason 추출"""
        if hasattr(response, "response_metadata"):
            metadata = response.response_metadata
            # Anthropic
            if "stop_reason" in metadata:
                return metadata["stop_reason"]
            # OpenAI
            if "finish_reason" in metadata:
                return metadata["finish_reason"]
        return None

    async def generate_response(
        self,
        conversation_id: str,
        message_id: str,
        conversation_messages: List[Dict[str, Any]],
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        workflow_type: str = "chat",
        enable_context_optimization: bool = True,
    ) -> Dict[str, Any]:
        """
        채팅 응답 생성 (비스트리밍)

        Returns:
            {
                "content": str,
                "model_name": str,
                "provider": str,
                "usage": {...},
                "cost": {...},
                "latency_ms": int,
                "finish_reason": str
            }
        """
        model = resolve_conversation_chat_model(model_name)
        provider = self._extract_provider_from_model(model)

        start_time = time.time()

        try:
            # 컨텍스트 최적화
            optimized_messages = conversation_messages
            optimization_stats = None

            if enable_context_optimization and settings.CONTEXT_OVERFLOW_DETECTION:
                optimized_messages, optimization_stats = await context_optimizer.check_and_optimize_context(
                    conversation_messages,
                    workflow_type=workflow_type
                )

                if optimization_stats and optimization_stats.get("optimizations_applied"):
                    logger.info(
                        f"[ChatLLM] Context optimized: {optimization_stats['original_tokens']} → "
                        f"{optimization_stats['optimized_tokens']} tokens, "
                        f"applied: {optimization_stats['optimizations_applied']}"
                    )

            # LLM 생성
            llm_params = {"model": model, "temperature": temperature}
            if max_tokens:
                llm_params["max_tokens"] = max_tokens

            llm = create_llm(provider=provider, **llm_params)

            # 메시지 구성
            messages = self._build_messages(optimized_messages, system_prompt)

            # LLM 호출
            response = await llm.ainvoke(messages)

            # 응답 처리 (handles thinking blocks properly)
            content = extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            finish_reason = self._extract_finish_reason(response)
            latency_ms = int((time.time() - start_time) * 1000)

            # 비용 계산 (기록은 호출자가 메시지 저장 후 수행)
            cost_info = await cost_calculator.calculate_cost(
                provider=provider,
                model_name=model,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
            )

            logger.info(
                f"Generated response: {len(content)} chars, "
                f"{usage['total_tokens']} tokens, "
                f"${cost_info['total_cost']:.6f}, "
                f"{latency_ms}ms"
            )

            result = {
                "content": content,
                "model_name": model,
                "provider": provider,
                "usage": usage,
                "cost": cost_info,
                "latency_ms": latency_ms,
                "finish_reason": finish_reason,
            }

            # 최적화 통계 추가
            if optimization_stats:
                result["context_optimization"] = optimization_stats

            return result

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Failed to generate response: {e}")
            raise

    async def generate_response_stream(
        self,
        conversation_id: str,
        message_id: str,
        conversation_messages: List[Dict[str, Any]],
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        workflow_type: str = "chat",
        enable_context_optimization: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        채팅 응답 스트리밍 생성

        Yields:
            {
                "type": "start" | "content" | "complete" | "error",
                "content": str (type=content인 경우),
                "usage": {...} (type=complete인 경우),
                "cost": {...} (type=complete인 경우),
                "error": str (type=error인 경우)
            }
        """
        model = resolve_conversation_chat_model(model_name)
        provider = self._extract_provider_from_model(model)

        start_time = time.time()
        full_content = ""
        usage_info = None
        finish_reason_value = None
        optimization_stats = None

        try:
            # 컨텍스트 최적화
            optimized_messages = conversation_messages

            if enable_context_optimization and settings.CONTEXT_OVERFLOW_DETECTION:
                optimized_messages, optimization_stats = await context_optimizer.check_and_optimize_context(
                    conversation_messages,
                    workflow_type=workflow_type
                )

                if optimization_stats and optimization_stats.get("optimizations_applied"):
                    logger.info(
                        f"[ChatLLM Stream] Context optimized: {optimization_stats['original_tokens']} → "
                        f"{optimization_stats['optimized_tokens']} tokens"
                    )

            # LLM 생성
            llm_params = {"model": model, "temperature": temperature, "streaming": True}
            if max_tokens:
                llm_params["max_tokens"] = max_tokens

            llm = create_llm(provider=provider, **llm_params)

            # 메시지 구성
            messages = self._build_messages(optimized_messages, system_prompt)

            # 시작 이벤트
            yield {"type": "start", "model": model, "provider": provider}

            # 스트리밍 호출
            async for chunk in llm.astream(messages):
                if hasattr(chunk, "content") and chunk.content:
                    content = chunk.content

                    # Handle thinking blocks (content is a list when extended thinking is enabled)
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") == "thinking":
                                    thinking_text = block.get("thinking", "")
                                    if thinking_text:
                                        yield {"type": "reasoning", "content": thinking_text}
                                elif block.get("type") == "text":
                                    text = block.get("text", "")
                                    if text:
                                        full_content += text
                                        yield {"type": "content", "content": text}
                            elif hasattr(block, "type"):
                                if block.type == "thinking":
                                    thinking_text = getattr(block, "thinking", "")
                                    if thinking_text:
                                        yield {"type": "reasoning", "content": thinking_text}
                                elif block.type == "text":
                                    text = getattr(block, "text", "")
                                    if text:
                                        full_content += text
                                        yield {"type": "content", "content": text}
                    else:
                        # Simple string content (no thinking blocks)
                        content_chunk = extract_text_from_response(chunk)
                        if content_chunk:
                            full_content += content_chunk
                            yield {"type": "content", "content": content_chunk}

                # 마지막 청크에서 usage 정보 추출
                if hasattr(chunk, "response_metadata"):
                    usage_info = self._extract_usage_from_response(chunk)
                    finish_reason_value = self._extract_finish_reason(chunk)

            # 스트리밍 완료 후 usage 정보가 없으면 추정
            if not usage_info or usage_info["total_tokens"] == 0:
                # 간단한 토큰 추정 (정확하지 않음)
                estimated_prompt_tokens = sum(
                    len(msg.get("content", "")) // 4 for msg in conversation_messages
                )
                estimated_completion_tokens = len(full_content) // 4
                usage_info = {
                    "prompt_tokens": estimated_prompt_tokens,
                    "completion_tokens": estimated_completion_tokens,
                    "total_tokens": estimated_prompt_tokens
                    + estimated_completion_tokens,
                }

            latency_ms = int((time.time() - start_time) * 1000)

            # 비용 계산 (기록은 호출자가 메시지 저장 후 수행)
            cost_info = await cost_calculator.calculate_cost(
                provider=provider,
                model_name=model,
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
            )

            logger.info(
                f"Stream completed: {len(full_content)} chars, "
                f"{usage_info['total_tokens']} tokens, "
                f"${cost_info['total_cost']:.6f}, "
                f"{latency_ms}ms"
            )

            # 완료 이벤트
            complete_event = {
                "type": "complete",
                "full_content": full_content,
                "model_name": model,
                "provider": provider,
                "usage": usage_info,
                "cost": cost_info,
                "latency_ms": latency_ms,
                "finish_reason": finish_reason_value,
            }

            # 최적화 통계 추가
            if optimization_stats:
                complete_event["context_optimization"] = optimization_stats

            yield complete_event

        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield {"type": "error", "error": str(e)}


    async def generate_response_stream_with_tools(
        self,
        conversation_id: str,
        message_id: str,
        conversation_messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Tool calling을 지원하는 채팅 응답 스트리밍 생성

        Anthropic SDK를 직접 사용합니다 (LangChain의 tool use 제약 회피)

        Args:
            conversation_id: 대화 ID
            message_id: 메시지 ID
            conversation_messages: 대화 메시지 목록
            tools: Anthropic tool 정의 목록
            model_name: 모델 이름
            system_prompt: 시스템 프롬프트
            temperature: Temperature
            max_tokens: 최대 토큰

        Yields:
            {
                "type": "start" | "content" | "tool_use" | "complete" | "error",
                "content": str (type=content인 경우),
                "tool_name": str (type=tool_use인 경우),
                "tool_input": dict (type=tool_use인 경우),
                "usage": {...} (type=complete인 경우),
                "cost": {...} (type=complete인 경우),
            }
        """
        model = resolve_conversation_chat_model(model_name)
        provider = self._extract_provider_from_model(model)
        start_time = time.time()
        full_content = ""
        usage_info = None

        try:
            if provider != "anthropic":
                async for event in self.generate_response_stream(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    conversation_messages=conversation_messages,
                    model_name=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    yield event
                return

            # Anthropic 클라이언트 초기화
            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

            # 메시지 형식 변환 (LangChain 형식에서 Anthropic 형식으로)
            anthropic_messages = []
            for msg in conversation_messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")

                if role in ["user", "assistant"]:
                    anthropic_messages.append({
                        "role": role,
                        "content": content
                    })

            # 시작 이벤트
            yield {"type": "start", "model": model, "provider": "anthropic"}

            # Anthropic SDK로 스트리밍 (tool calling 지원)
            stream_kwargs = normalize_anthropic_request(
                model,
                {
                    "model": model,
                    "messages": anthropic_messages,
                    "tools": tools if tools else None,
                    "system": system_prompt or "",
                    "temperature": temperature,
                    "max_tokens": max_tokens or 4096,
                },
                thinking_enabled=True,
            )
            async with client.messages.stream(**stream_kwargs) as stream:
                # 스트리밍 이벤트 처리
                async for event in stream:
                    if not hasattr(event, 'type'):
                        continue

                    # Content block 시작
                    if event.type == "content_block_start":
                        if hasattr(event, 'content_block') and hasattr(event.content_block, 'type'):
                            if event.content_block.type == "thinking":
                                # Thinking 블록 시작
                                yield {"type": "reasoning_start"}
                            elif event.content_block.type == "tool_use":
                                # Tool 호출 감지
                                tool_name = event.content_block.name
                                tool_id = event.content_block.id
                                logger.debug(f"Tool use started: {tool_name} (ID: {tool_id})")

                    # Content block 델타
                    elif event.type == "content_block_delta":
                        if hasattr(event, 'delta') and hasattr(event.delta, 'type'):
                            if event.delta.type == "thinking_delta":
                                # Thinking 블록 델타 → reasoning 이벤트
                                thinking_text = getattr(event.delta, 'thinking', '')
                                if thinking_text:
                                    yield {"type": "reasoning", "content": thinking_text}
                            elif event.delta.type == "text_delta":
                                # 텍스트 컨텐츠 델타
                                text = event.delta.text
                                full_content += text
                                yield {"type": "content", "content": text}
                            elif event.delta.type == "input_json_delta":
                                # Tool input 델타는 나중에 최종 메시지에서 합쳐짐
                                pass

                    # Content block 완료
                    elif event.type == "content_block_stop":
                        pass

                # 최종 메시지 가져오기
                final_message = await stream.get_final_message()

                # Usage 정보 추출
                usage_info = {
                    "prompt_tokens": final_message.usage.input_tokens,
                    "completion_tokens": final_message.usage.output_tokens,
                    "total_tokens": final_message.usage.input_tokens + final_message.usage.output_tokens
                }

                # Tool use 확인
                for content_block in final_message.content:
                    if content_block.type == "tool_use":
                        yield {
                            "type": "tool_use",
                            "tool_name": content_block.name,
                            "tool_input": content_block.input,
                            "tool_id": content_block.id
                        }
                    elif content_block.type == "text":
                        # 텍스트 컨텐츠 (이미 스트리밍됨)
                        pass

            latency_ms = int((time.time() - start_time) * 1000)

            # 비용 계산
            cost_info = await cost_calculator.calculate_cost(
                provider="anthropic",
                model_name=model,
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
            )

            logger.info(
                f"Tool-enabled stream completed: {len(full_content)} chars, "
                f"{usage_info['total_tokens']} tokens, "
                f"${cost_info['total_cost']:.6f}, "
                f"{latency_ms}ms"
            )

            # 완료 이벤트
            yield {
                "type": "complete",
                "full_content": full_content,
                "model_name": model,
                "provider": "anthropic",
                "usage": usage_info,
                "cost": cost_info,
                "latency_ms": latency_ms,
            }

        except Exception as e:
            logger.error(f"Tool-enabled stream error: {e}")
            yield {"type": "error", "error": str(e)}


    async def generate_response_stream_with_tool_search(
        self,
        conversation_id: str,
        message_id: str,
        conversation_messages: List[Dict[str, Any]],
        core_tools: List[Dict[str, Any]],
        search_handler: Any,
        tool_executor: Optional[Any] = None,
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        max_tool_rounds: int = 3,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Advanced Tool Search 패턴의 멀티턴 도구 호출 루프 스트리밍

        코어 도구 + search_tools만 초기 제공하고, search_tools 호출 시
        하이브리드 검색으로 도구를 발견하여 동적으로 추가한다.

        Args:
            conversation_id: 대화 ID
            message_id: 메시지 ID
            conversation_messages: 대화 메시지 목록
            core_tools: 코어 도구 정의 목록 (Anthropic format)
            search_handler: SearchToolsHandler 인스턴스
            tool_executor: 일반 도구 실행 콜백 (name, input) -> result dict
            model_name: 모델 이름
            system_prompt: 시스템 프롬프트
            temperature: Temperature
            max_tokens: 최대 토큰
            max_tool_rounds: 멀티턴 최대 라운드 수

        Yields:
            기존 generate_response_stream_with_tools()와 동일한 이벤트 형식
        """
        model = resolve_conversation_chat_model(model_name)
        provider = self._extract_provider_from_model(model)
        start_time = time.time()
        full_content = ""
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        try:
            if provider != "anthropic":
                async for event in self.generate_response_stream(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    conversation_messages=conversation_messages,
                    model_name=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    yield event
                return

            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

            # 1. 초기 도구 세트: 코어 도구 + search_tools
            active_tools_dicts = list(core_tools)
            active_tools_dicts.append(SEARCH_TOOLS_TOOL)

            # 메시지 변환
            anthropic_messages = []
            for msg in conversation_messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ["user", "assistant"]:
                    anthropic_messages.append({"role": role, "content": content})

            yield {"type": "start", "model": model, "provider": "anthropic"}

            round_count = 0

            while round_count < max_tool_rounds:
                round_count += 1

                # 2. Claude API 호출
                stream_kwargs = normalize_anthropic_request(
                    model,
                    {
                        "model": model,
                        "messages": anthropic_messages,
                        "tools": active_tools_dicts,
                        "system": system_prompt or "",
                        "temperature": temperature,
                        "max_tokens": max_tokens or 4096,
                    },
                    thinking_enabled=True,
                )
                async with client.messages.stream(**stream_kwargs) as stream:
                    async for event in stream:
                        if not hasattr(event, 'type'):
                            continue

                        if event.type == "content_block_start":
                            if hasattr(event, 'content_block') and hasattr(event.content_block, 'type'):
                                if event.content_block.type == "thinking":
                                    yield {"type": "reasoning_start"}
                                elif event.content_block.type == "tool_use":
                                    logger.debug(
                                        f"Tool use started: {event.content_block.name} "
                                        f"(round {round_count})"
                                    )

                        elif event.type == "content_block_delta":
                            if hasattr(event, 'delta') and hasattr(event.delta, 'type'):
                                if event.delta.type == "thinking_delta":
                                    thinking_text = getattr(event.delta, 'thinking', '')
                                    if thinking_text:
                                        yield {"type": "reasoning", "content": thinking_text}
                                elif event.delta.type == "text_delta":
                                    text = event.delta.text
                                    full_content += text
                                    yield {"type": "content", "content": text}

                    # 최종 메시지 가져오기
                    final_message = await stream.get_final_message()

                # Usage 누적
                total_usage["prompt_tokens"] += final_message.usage.input_tokens
                total_usage["completion_tokens"] += final_message.usage.output_tokens
                total_usage["total_tokens"] = (
                    total_usage["prompt_tokens"] + total_usage["completion_tokens"]
                )

                # 3. tool_use 블록 확인
                tool_uses = [
                    b for b in final_message.content if b.type == "tool_use"
                ]

                if not tool_uses:
                    break  # 도구 호출 없음 → 완료

                # 4. 각 tool_use 처리
                tool_results = []
                for tool_use in tool_uses:
                    if tool_use.name == "search_tools":
                        # search_tools 호출 → 하이브리드 검색
                        search_result = await search_handler.handle(tool_use.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": json.dumps(search_result, ensure_ascii=False),
                        })

                        # 검색된 도구를 active_tools에 추가
                        existing_names = {t["name"] for t in active_tools_dicts}
                        for found_tool in search_result.get("found_tools", []):
                            if found_tool["name"] not in existing_names:
                                active_tools_dicts.append({
                                    "name": found_tool["name"],
                                    "description": found_tool["description"],
                                    "input_schema": found_tool["input_schema"],
                                })
                                existing_names.add(found_tool["name"])

                        logger.info(
                            f"search_tools round {round_count}: "
                            f"found {len(search_result.get('found_tools', []))} tools, "
                            f"active tools now: {len(active_tools_dicts)}"
                        )
                    else:
                        # 일반 도구 호출
                        yield {
                            "type": "tool_use",
                            "tool_name": tool_use.name,
                            "tool_input": tool_use.input,
                            "tool_id": tool_use.id,
                        }

                        if tool_executor:
                            result = await tool_executor(tool_use.name, tool_use.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": json.dumps(result, ensure_ascii=False),
                            })
                        else:
                            # tool_executor 없음: 빈 결과라도 채워 Anthropic API 오류 방지.
                            # assistant content의 모든 tool_use에는 tool_result가 있어야 한다.
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": json.dumps(
                                    {"error": "tool_executor not provided"}, ensure_ascii=False
                                ),
                            })

                if not tool_results:
                    break

                # 5. assistant 응답 + tool_results를 messages에 추가
                def _serialize_content_block(b) -> dict:
                    if hasattr(b, 'model_dump'):
                        return b.model_dump()
                    block: dict = {"type": b.type}
                    if b.type == "text":
                        block["text"] = b.text
                    elif b.type == "tool_use":
                        block.update({"id": b.id, "name": b.name, "input": b.input})
                    elif b.type == "thinking":
                        block["thinking"] = getattr(b, "thinking", "")
                    return block

                anthropic_messages.append({
                    "role": "assistant",
                    "content": [_serialize_content_block(b) for b in final_message.content],
                })
                anthropic_messages.append({
                    "role": "user",
                    "content": tool_results,
                })

            latency_ms = int((time.time() - start_time) * 1000)

            # 비용 계산
            cost_info = await cost_calculator.calculate_cost(
                provider="anthropic",
                model_name=model,
                prompt_tokens=total_usage["prompt_tokens"],
                completion_tokens=total_usage["completion_tokens"],
            )

            logger.info(
                f"Tool search stream completed: {len(full_content)} chars, "
                f"{total_usage['total_tokens']} tokens, "
                f"${cost_info['total_cost']:.6f}, "
                f"{latency_ms}ms, {round_count} rounds"
            )

            yield {
                "type": "complete",
                "full_content": full_content,
                "model_name": model,
                "provider": "anthropic",
                "usage": total_usage,
                "cost": cost_info,
                "latency_ms": latency_ms,
                "tool_search_rounds": round_count,
            }

        except Exception as e:
            logger.error(f"Tool search stream error: {e}")
            yield {"type": "error", "error": str(e)}


# 전역 인스턴스
chat_llm_service = ChatLLMService()
