"""
Artifact LLM Service

아티팩트(문서, 코드, 스프레드시트) 생성을 위한 LLM 서비스
Anthropic SDK를 직접 사용하여 스트리밍 생성을 지원합니다.
"""

from typing import AsyncGenerator, Dict, Any, Optional
import time
import json

from neos.config.settings import settings
from neos.utils.anthropic_client import build_async_anthropic
from neos.utils.cost_calculator import cost_calculator
from neos.utils.logger import get_logger

logger = get_logger(__name__)


# 아티팩트 타입별 시스템 프롬프트
TEXT_PROMPT = """Write about the given topic. Markdown is supported. Use headings wherever appropriate.
Create well-structured, informative content that is easy to read and understand."""

CODE_PROMPT = """You are a Python code generator that creates self-contained, executable code snippets. When writing code:

1. Each snippet should be complete and runnable on its own
2. Prefer using print() statements to display outputs
3. Include helpful comments explaining the code
4. Keep snippets concise (generally under 15 lines)
5. Avoid external dependencies - use Python standard library
6. Handle potential errors gracefully
7. Return meaningful output that demonstrates the code's functionality
8. Don't use input() or other interactive functions
9. Don't access files or network resources
10. Don't use infinite loops

Examples of good snippets:

# Calculate factorial iteratively
def factorial(n):
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result

print(f"Factorial of 5 is: {factorial(5)}")"""

SHEET_PROMPT = """You are a spreadsheet creation assistant. Create a spreadsheet in CSV format based on the given prompt.
The spreadsheet should contain meaningful column headers and data.
Output ONLY the CSV data, nothing else."""


class ArtifactLLMService:
    """아티팩트 전용 LLM 서비스"""

    def __init__(self):
        self.model = settings.ARTIFACT_LLM_MODEL
        self.temperature = settings.ARTIFACT_LLM_TEMPERATURE
        self.max_tokens = settings.ARTIFACT_LLM_MAX_TOKENS
        self.client = build_async_anthropic()

    async def stream_text_generation(
        self,
        prompt: str,
        system_prompt: Optional[str] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        텍스트 아티팩트 스트리밍 생성 (Markdown)

        Args:
            prompt: 사용자 프롬프트
            system_prompt: 시스템 프롬프트 (기본값: TEXT_PROMPT)

        Yields:
            {
                "type": "start" | "content" | "complete" | "error",
                "content": str (type=content인 경우),
                "usage": {...} (type=complete인 경우),
                "cost": {...} (type=complete인 경우)
            }
        """
        start_time = time.time()
        full_content = ""
        usage_info = None

        try:
            # 시작 이벤트
            yield {"type": "start", "model": self.model}

            # Anthropic SDK로 스트리밍
            async with self.client.messages.stream(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                system=system_prompt or TEXT_PROMPT,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ) as stream:
                # 컨텐츠 스트리밍
                async for text in stream.text_stream:
                    if text:
                        full_content += text
                        yield {"type": "content", "content": text}

                # 최종 메시지에서 usage 정보 추출
                final_message = await stream.get_final_message()
                usage_info = {
                    "prompt_tokens": final_message.usage.input_tokens,
                    "completion_tokens": final_message.usage.output_tokens,
                    "total_tokens": final_message.usage.input_tokens + final_message.usage.output_tokens
                }

            latency_ms = int((time.time() - start_time) * 1000)

            # 비용 계산
            cost_info = await cost_calculator.calculate_cost(
                provider="anthropic",
                model_name=self.model,
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
            )

            logger.info(
                f"Text artifact generated: {len(full_content)} chars, "
                f"{usage_info['total_tokens']} tokens, "
                f"${cost_info['total_cost']:.6f}, "
                f"{latency_ms}ms"
            )

            # 완료 이벤트
            yield {
                "type": "complete",
                "full_content": full_content,
                "model_name": self.model,
                "provider": "anthropic",
                "usage": usage_info,
                "cost": cost_info,
                "latency_ms": latency_ms,
            }

        except Exception as e:
            logger.error(f"Text generation error: {e}")
            yield {"type": "error", "error": str(e)}

    async def stream_code_generation(
        self,
        prompt: str,
        language: str = "python"
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        코드 아티팩트 스트리밍 생성

        Args:
            prompt: 사용자 프롬프트
            language: 프로그래밍 언어 (현재는 Python만 지원)

        Yields:
            {
                "type": "start" | "content" | "complete" | "error",
                "content": str (type=content인 경우),
                "usage": {...} (type=complete인 경우),
                "cost": {...} (type=complete인 경우)
            }
        """
        start_time = time.time()
        full_content = ""
        usage_info = None

        try:
            # 시작 이벤트
            yield {"type": "start", "model": self.model, "language": language}

            # Anthropic SDK로 스트리밍
            async with self.client.messages.stream(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                system=CODE_PROMPT,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ) as stream:
                # 컨텐츠 스트리밍
                async for text in stream.text_stream:
                    if text:
                        full_content += text
                        yield {"type": "content", "content": text}

                # 최종 메시지에서 usage 정보 추출
                final_message = await stream.get_final_message()
                usage_info = {
                    "prompt_tokens": final_message.usage.input_tokens,
                    "completion_tokens": final_message.usage.output_tokens,
                    "total_tokens": final_message.usage.input_tokens + final_message.usage.output_tokens
                }

            latency_ms = int((time.time() - start_time) * 1000)

            # 비용 계산
            cost_info = await cost_calculator.calculate_cost(
                provider="anthropic",
                model_name=self.model,
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
            )

            logger.info(
                f"Code artifact generated: {len(full_content)} chars, "
                f"{usage_info['total_tokens']} tokens, "
                f"${cost_info['total_cost']:.6f}, "
                f"{latency_ms}ms"
            )

            # 완료 이벤트
            yield {
                "type": "complete",
                "full_content": full_content,
                "model_name": self.model,
                "provider": "anthropic",
                "usage": usage_info,
                "cost": cost_info,
                "latency_ms": latency_ms,
            }

        except Exception as e:
            logger.error(f"Code generation error: {e}")
            yield {"type": "error", "error": str(e)}

    async def stream_sheet_generation(
        self,
        prompt: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        스프레드시트 아티팩트 스트리밍 생성 (CSV)

        Args:
            prompt: 사용자 프롬프트

        Yields:
            {
                "type": "start" | "content" | "complete" | "error",
                "content": str (type=content인 경우),
                "usage": {...} (type=complete인 경우),
                "cost": {...} (type=complete인 경우)
            }
        """
        start_time = time.time()
        full_content = ""
        usage_info = None

        try:
            # 시작 이벤트
            yield {"type": "start", "model": self.model}

            # Anthropic SDK로 스트리밍
            async with self.client.messages.stream(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                system=SHEET_PROMPT,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ) as stream:
                # 컨텐츠 스트리밍
                async for text in stream.text_stream:
                    if text:
                        full_content += text
                        yield {"type": "content", "content": text}

                # 최종 메시지에서 usage 정보 추출
                final_message = await stream.get_final_message()
                usage_info = {
                    "prompt_tokens": final_message.usage.input_tokens,
                    "completion_tokens": final_message.usage.output_tokens,
                    "total_tokens": final_message.usage.input_tokens + final_message.usage.output_tokens
                }

            latency_ms = int((time.time() - start_time) * 1000)

            # 비용 계산
            cost_info = await cost_calculator.calculate_cost(
                provider="anthropic",
                model_name=self.model,
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
            )

            logger.info(
                f"Sheet artifact generated: {len(full_content)} chars, "
                f"{usage_info['total_tokens']} tokens, "
                f"${cost_info['total_cost']:.6f}, "
                f"{latency_ms}ms"
            )

            # 완료 이벤트
            yield {
                "type": "complete",
                "full_content": full_content,
                "model_name": self.model,
                "provider": "anthropic",
                "usage": usage_info,
                "cost": cost_info,
                "latency_ms": latency_ms,
            }

        except Exception as e:
            logger.error(f"Sheet generation error: {e}")
            yield {"type": "error", "error": str(e)}

    async def update_artifact(
        self,
        current_content: str,
        description: str,
        kind: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        기존 아티팩트 업데이트

        Args:
            current_content: 현재 콘텐츠
            description: 수정 내용 설명
            kind: 아티팩트 타입 (text, code, sheet)

        Yields:
            스트리밍 이벤트
        """
        # 타입별 프롬프트 선택
        media_type = "document"
        system_prompt = TEXT_PROMPT

        if kind == "code":
            media_type = "code snippet"
            system_prompt = CODE_PROMPT
        elif kind == "sheet":
            media_type = "spreadsheet"
            system_prompt = SHEET_PROMPT

        # 업데이트 프롬프트 구성
        update_prompt = f"""Improve the following contents of the {media_type} based on the given prompt.

Current content:
{current_content}

Instructions: {description}"""

        # 타입에 따라 적절한 생성 함수 호출
        if kind == "code":
            async for chunk in self.stream_code_generation(update_prompt):
                yield chunk
        elif kind == "sheet":
            async for chunk in self.stream_sheet_generation(update_prompt):
                yield chunk
        else:
            async for chunk in self.stream_text_generation(update_prompt, system_prompt):
                yield chunk


# 전역 인스턴스
artifact_llm_service = ArtifactLLMService()
