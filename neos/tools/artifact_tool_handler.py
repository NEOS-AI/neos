"""
Artifact Tool Handler

createDocument와 updateDocument 도구 실행 핸들러
"""

from typing import Dict, Any, AsyncGenerator
import uuid
from datetime import datetime

from neos.services.artifact_llm_service import artifact_llm_service
from neos.api.services.artifact_service import ArtifactService
from neos.utils.logger import get_logger
from neos.utils.cost_calculator import cost_calculator

logger = get_logger(__name__)


async def handle_create_document(
    tool_input: Dict[str, Any],
    user_id: str,
    db_session,
    conversation_id: str
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    createDocument 도구 실행

    Args:
        tool_input: 도구 입력 (title, kind)
        user_id: 사용자 ID
        db_session: 데이터베이스 세션
        conversation_id: 대화 ID

    Yields:
        스트리밍 이벤트:
        - artifact_meta: 문서 메타데이터
        - artifact_delta: 콘텐츠 델타
        - artifact_finish: 완료 신호
        - tool_result: 도구 실행 결과
    """
    try:
        title = tool_input.get("title", "")
        kind = tool_input.get("kind", "text")

        if not title:
            yield {
                "type": "error",
                "error": "Title is required for createDocument"
            }
            return

        # 문서 ID 생성
        document_id = str(uuid.uuid4())

        logger.info(f"Creating {kind} artifact: {title} (id: {document_id})")

        # 1. 메타데이터 전송
        yield {
            "type": "artifact_meta",
            "artifact_id": document_id,
            "artifact_title": title,
            "artifact_kind": kind
        }

        # 2. AI로 콘텐츠 생성 및 스트리밍
        full_content = ""
        usage_info = None
        cost_info = None

        # 타입에 따라 적절한 생성 함수 호출
        if kind == "text":
            stream = artifact_llm_service.stream_text_generation(
                prompt=f"Create a document about: {title}"
            )
        elif kind == "code":
            stream = artifact_llm_service.stream_code_generation(
                prompt=f"Create a Python code for: {title}"
            )
        elif kind == "sheet":
            stream = artifact_llm_service.stream_sheet_generation(
                prompt=f"Create a spreadsheet for: {title}"
            )
        else:
            yield {
                "type": "error",
                "error": f"Unsupported document kind: {kind}"
            }
            return

        async for chunk in stream:
            if chunk["type"] == "content":
                full_content += chunk["content"]
                # 콘텐츠 델타 전송
                yield {
                    "type": "artifact_delta",
                    "content": chunk["content"]
                }
            elif chunk["type"] == "complete":
                usage_info = chunk.get("usage")
                cost_info = chunk.get("cost")
                full_content = chunk.get("full_content", full_content)
            elif chunk["type"] == "error":
                yield {
                    "type": "error",
                    "error": chunk.get("error", "Unknown error")
                }
                return

        # 3. DB에 문서 저장
        artifact_service = ArtifactService(db_session)
        try:
            await artifact_service.create_document(
                user_id=user_id,
                document_id=document_id,
                title=title,
                content=full_content,
                kind=kind
            )
            logger.info(f"Artifact saved to database: {document_id}")
        except Exception as e:
            logger.error(f"Failed to save artifact to database: {e}")
            yield {
                "type": "error",
                "error": f"Failed to save document: {str(e)}"
            }
            return

        # 4. 비용 기록 (메시지와 연결하지 않고 별도로 기록)
        if usage_info and cost_info:
            try:
                await cost_calculator.record_artifact_cost(
                    artifact_id=document_id,
                    conversation_id=conversation_id,
                    provider="anthropic",
                    model_name=artifact_llm_service.model,
                    prompt_tokens=usage_info["prompt_tokens"],
                    completion_tokens=usage_info["completion_tokens"],
                    total_tokens=usage_info["total_tokens"],
                    cost_usd=cost_info["total_cost"]
                )
            except Exception as e:
                # 비용 기록 실패해도 계속 진행
                logger.warning(f"Failed to record artifact cost: {e}")

        # 5. 완료 신호 전송
        yield {
            "type": "artifact_finish",
            "artifact_id": document_id
        }

        # 6. Tool 실행 결과 반환
        yield {
            "type": "tool_result",
            "content": f"Created {kind} document: \"{title}\" (ID: {document_id})"
        }

    except Exception as e:
        logger.error(f"Error in handle_create_document: {e}")
        yield {
            "type": "error",
            "error": str(e)
        }


async def handle_update_document(
    tool_input: Dict[str, Any],
    user_id: str,
    db_session,
    conversation_id: str
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    updateDocument 도구 실행

    Args:
        tool_input: 도구 입력 (id, description)
        user_id: 사용자 ID
        db_session: 데이터베이스 세션
        conversation_id: 대화 ID

    Yields:
        스트리밍 이벤트
    """
    try:
        document_id = tool_input.get("id", "")
        description = tool_input.get("description", "")

        if not document_id or not description:
            yield {
                "type": "error",
                "error": "Document ID and description are required for updateDocument"
            }
            return

        logger.info(f"Updating artifact {document_id}: {description}")

        # 1. 기존 문서 조회
        artifact_service = ArtifactService(db_session)
        try:
            existing_doc = await artifact_service.get_latest_document(document_id, user_id)
        except Exception as e:
            logger.error(f"Failed to fetch document {document_id}: {e}")
            yield {
                "type": "error",
                "error": f"Document not found: {document_id}"
            }
            return

        current_content = existing_doc.content or ""
        kind = existing_doc.kind
        title = existing_doc.title

        # 2. 메타데이터 전송
        yield {
            "type": "artifact_meta",
            "artifact_id": document_id,
            "artifact_title": title,
            "artifact_kind": kind
        }

        # 3. AI로 업데이트된 콘텐츠 생성 및 스트리밍
        full_content = ""
        usage_info = None
        cost_info = None

        async for chunk in artifact_llm_service.update_artifact(
            current_content=current_content,
            description=description,
            kind=kind
        ):
            if chunk["type"] == "content":
                full_content += chunk["content"]
                # 콘텐츠 델타 전송
                yield {
                    "type": "artifact_delta",
                    "content": chunk["content"]
                }
            elif chunk["type"] == "complete":
                usage_info = chunk.get("usage")
                cost_info = chunk.get("cost")
                full_content = chunk.get("full_content", full_content)
            elif chunk["type"] == "error":
                yield {
                    "type": "error",
                    "error": chunk.get("error", "Unknown error")
                }
                return

        # 4. 새 버전으로 DB에 저장 (같은 ID, 다른 created_at)
        try:
            await artifact_service.create_document(
                user_id=user_id,
                document_id=document_id,  # 같은 ID 사용
                title=title,
                content=full_content,
                kind=kind
            )
            logger.info(f"Updated artifact saved as new version: {document_id}")
        except Exception as e:
            logger.error(f"Failed to save updated artifact: {e}")
            yield {
                "type": "error",
                "error": f"Failed to save updated document: {str(e)}"
            }
            return

        # 5. 비용 기록
        if usage_info and cost_info:
            try:
                await cost_calculator.record_artifact_cost(
                    artifact_id=document_id,
                    conversation_id=conversation_id,
                    provider="anthropic",
                    model_name=artifact_llm_service.model,
                    prompt_tokens=usage_info["prompt_tokens"],
                    completion_tokens=usage_info["completion_tokens"],
                    total_tokens=usage_info["total_tokens"],
                    cost_usd=cost_info["total_cost"]
                )
            except Exception as e:
                logger.warning(f"Failed to record artifact update cost: {e}")

        # 6. 완료 신호 전송
        yield {
            "type": "artifact_finish",
            "artifact_id": document_id
        }

        # 7. Tool 실행 결과 반환
        yield {
            "type": "tool_result",
            "content": f"Updated document: \"{title}\" (ID: {document_id})"
        }

    except Exception as e:
        logger.error(f"Error in handle_update_document: {e}")
        yield {
            "type": "error",
            "error": str(e)
        }


async def execute_artifact_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
    user_id: str,
    db_session,
    conversation_id: str
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    아티팩트 도구 실행 라우터

    Args:
        tool_name: 도구 이름 (createDocument, updateDocument)
        tool_input: 도구 입력
        user_id: 사용자 ID
        db_session: 데이터베이스 세션
        conversation_id: 대화 ID

    Yields:
        스트리밍 이벤트
    """
    if tool_name == "createDocument":
        async for event in handle_create_document(tool_input, user_id, db_session, conversation_id):
            yield event
    elif tool_name == "updateDocument":
        async for event in handle_update_document(tool_input, user_id, db_session, conversation_id):
            yield event
    else:
        yield {
            "type": "error",
            "error": f"Unknown artifact tool: {tool_name}"
        }
