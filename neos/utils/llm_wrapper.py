"""
LLM 래퍼 - 호출 추적 통합

LangChain LLM을 래핑하여 모든 호출을 자동으로 추적합니다.
"""

import time
import logging
from typing import Dict, Any, List, Optional, Union
from langchain_core.messages import BaseMessage
from langchain_core.language_models import BaseLanguageModel
from langchain_core.outputs import LLMResult

from neos.config.settings import settings
from neos.dataset.collector import create_llm_call_record

logger = logging.getLogger(__name__)


class TrackedLLM:
    """
    LLM 호출 추적 래퍼

    사용 예:
        llm = create_llm()
        tracked_llm = TrackedLLM(
            llm=llm,
            session_id=state["session_id"],
            user_id=state["user_id"],
            workflow_step="query_classifier",
            agent_name="classifier"
        )
        response = await tracked_llm.ainvoke(messages)
    """

    def __init__(
        self,
        llm: BaseLanguageModel,
        session_id: str = "",
        user_id: str = "",
        workflow_step: str = "",
        agent_name: Optional[str] = None,
        tags: Optional[List[str]] = None,
        custom_metadata: Optional[Dict[str, Any]] = None
    ):
        self.llm = llm
        self.session_id = session_id
        self.user_id = user_id
        self.workflow_step = workflow_step
        self.agent_name = agent_name
        self.tags = tags or []
        self.custom_metadata = custom_metadata or {}

        # LLM 설정 추출
        self.provider = self._extract_provider()
        self.model = getattr(llm, "model_name", getattr(llm, "model", "unknown"))
        self.temperature = settings.LLM_TEMPERATURE


    def _extract_provider(self) -> str:
        """LLM provider 추출"""
        llm_class = self.llm.__class__.__name__.lower()
        if "openai" in llm_class:
            return "openai"
        elif "anthropic" in llm_class or "claude" in llm_class:
            return "anthropic"
        else:
            return "unknown"

    def _extract_messages(self, messages: Union[List[BaseMessage], str]) -> List[Dict[str, Any]]:
        """메시지를 딕셔너리 형식으로 변환"""
        if isinstance(messages, str):
            return [{"role": "user", "content": messages}]

        result = []
        for msg in messages:
            if isinstance(msg, BaseMessage):
                result.append({
                    "role": msg.type if hasattr(msg, 'type') else "user",
                    "content": msg.content
                })
            elif isinstance(msg, dict):
                result.append(msg)
            else:
                result.append({"role": "user", "content": str(msg)})

        return result

    def _extract_usage(self, response: Any) -> Optional[Dict[str, int]]:
        """토큰 사용량 추출"""
        # LLMResult 객체인 경우
        if isinstance(response, LLMResult):
            if hasattr(response, 'llm_output') and response.llm_output:
                token_usage = response.llm_output.get('token_usage', {})
                if token_usage:
                    return {
                        "prompt_tokens": token_usage.get('prompt_tokens', 0),
                        "completion_tokens": token_usage.get('completion_tokens', 0),
                        "total_tokens": token_usage.get('total_tokens', 0)
                    }

        # AIMessage 객체인 경우
        if hasattr(response, 'response_metadata'):
            metadata = response.response_metadata
            if 'token_usage' in metadata:
                token_usage = metadata['token_usage']
                return {
                    "prompt_tokens": token_usage.get('prompt_tokens', 0),
                    "completion_tokens": token_usage.get('completion_tokens', 0),
                    "total_tokens": token_usage.get('total_tokens', 0)
                }
            # OpenAI 형식
            if 'usage' in metadata:
                usage = metadata['usage']
                return {
                    "prompt_tokens": usage.get('prompt_tokens', 0),
                    "completion_tokens": usage.get('completion_tokens', 0),
                    "total_tokens": usage.get('total_tokens', 0)
                }

        return None

    def _extract_output_text(self, response: Any) -> str:
        """응답 텍스트 추출"""
        if isinstance(response, str):
            return response
        elif hasattr(response, 'content'):
            return response.content
        elif isinstance(response, LLMResult):
            if response.generations and response.generations[0]:
                return response.generations[0][0].text
        return str(response)

    async def ainvoke(self, messages: Union[List[BaseMessage], str], **kwargs) -> Any:
        """비동기 LLM 호출 (추적 포함)"""
        start_time = time.time()

        try:
            # LLM 호출
            response = await self.llm.ainvoke(messages, **kwargs)

            # 실행 시간 계산
            latency_ms = (time.time() - start_time) * 1000

            # 입력 메시지 변환
            input_messages = self._extract_messages(messages)

            # 출력 텍스트 추출
            output_text = self._extract_output_text(response)

            # 토큰 사용량 추출
            usage = self._extract_usage(response)

            # 레코드 생성 및 저장
            create_llm_call_record(
                session_id=self.session_id,
                user_id=self.user_id,
                workflow_step=self.workflow_step,
                agent_name=self.agent_name,
                provider=self.provider,
                model=self.model,
                input_messages=input_messages,
                output_text=output_text,
                usage=usage,
                latency_ms=latency_ms,
                temperature=self.temperature,
                success=True,
                tags=self.tags,
                custom_metadata=self.custom_metadata
            )

            return response

        except Exception as e:
            # 에러 발생 시에도 기록
            latency_ms = (time.time() - start_time) * 1000

            create_llm_call_record(
                session_id=self.session_id,
                user_id=self.user_id,
                workflow_step=self.workflow_step,
                agent_name=self.agent_name,
                provider=self.provider,
                model=self.model,
                input_messages=self._extract_messages(messages),
                output_text="",
                latency_ms=latency_ms,
                temperature=self.temperature,
                success=False,
                error_message=str(e),
                tags=self.tags,
                custom_metadata=self.custom_metadata
            )

            raise

    def invoke(self, messages: Union[List[BaseMessage], str], **kwargs) -> Any:
        """동기 LLM 호출 (추적 포함)"""
        start_time = time.time()

        try:
            response = self.llm.invoke(messages, **kwargs)
            latency_ms = (time.time() - start_time) * 1000

            input_messages = self._extract_messages(messages)
            output_text = self._extract_output_text(response)
            usage = self._extract_usage(response)

            create_llm_call_record(
                session_id=self.session_id,
                user_id=self.user_id,
                workflow_step=self.workflow_step,
                agent_name=self.agent_name,
                provider=self.provider,
                model=self.model,
                input_messages=input_messages,
                output_text=output_text,
                usage=usage,
                latency_ms=latency_ms,
                temperature=self.temperature,
                success=True,
                tags=self.tags,
                custom_metadata=self.custom_metadata
            )

            return response

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000

            create_llm_call_record(
                session_id=self.session_id,
                user_id=self.user_id,
                workflow_step=self.workflow_step,
                agent_name=self.agent_name,
                provider=self.provider,
                model=self.model,
                input_messages=self._extract_messages(messages),
                output_text="",
                latency_ms=latency_ms,
                temperature=self.temperature,
                success=False,
                error_message=str(e),
                tags=self.tags,
                custom_metadata=self.custom_metadata
            )

            raise

    async def agenerate(self, messages: List[List[BaseMessage]], **kwargs) -> LLMResult:
        """배치 생성 (추적 포함)"""
        start_time = time.time()

        try:
            result = await self.llm.agenerate(messages, **kwargs)
            latency_ms = (time.time() - start_time) * 1000

            # 각 메시지 세트에 대해 개별 레코드 생성
            for msg_set in messages:
                input_messages = self._extract_messages(msg_set)

                create_llm_call_record(
                    session_id=self.session_id,
                    user_id=self.user_id,
                    workflow_step=self.workflow_step,
                    agent_name=self.agent_name,
                    provider=self.provider,
                    model=self.model,
                    input_messages=input_messages,
                    output_text="[batch generation]",
                    latency_ms=latency_ms,
                    temperature=self.temperature,
                    success=True,
                    tags=self.tags + ["batch"]
                )

            return result

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000

            create_llm_call_record(
                session_id=self.session_id,
                user_id=self.user_id,
                workflow_step=self.workflow_step,
                agent_name=self.agent_name,
                provider=self.provider,
                model=self.model,
                input_messages=[],
                output_text="",
                latency_ms=latency_ms,
                temperature=self.temperature,
                success=False,
                error_message=str(e),
                tags=self.tags + ["batch"]
            )

            raise


def create_tracked_llm(
    llm: BaseLanguageModel,
    session_id: str = "",
    user_id: str = "",
    workflow_step: str = "",
    agent_name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    custom_metadata: Optional[Dict[str, Any]] = None
) -> TrackedLLM:
    """
    추적 가능한 LLM 인스턴스 생성

    사용 예:
        from neos.utils.llm_factory import create_llm
        from neos.utils.llm_wrapper import create_tracked_llm

        base_llm = create_llm()
        tracked_llm = create_tracked_llm(
            llm=base_llm,
            session_id=state["session_id"],
            user_id=state["user_id"],
            workflow_step="search",
            agent_name="knowledge_search"
        )

        response = await tracked_llm.ainvoke(messages)
    """
    return TrackedLLM(
        llm=llm,
        session_id=session_id,
        user_id=user_id,
        workflow_step=workflow_step,
        agent_name=agent_name,
        tags=tags,
        custom_metadata=custom_metadata
    )