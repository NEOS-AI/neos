"""
Artifact Tools for Anthropic Tool Use API

createDocument와 updateDocument 도구를 Anthropic의 tool use API 형식으로 정의합니다.
"""

from typing import Dict, Any


# createDocument 도구 정의
CREATE_DOCUMENT_TOOL: Dict[str, Any] = {
    "name": "createDocument",
    "description": "Create a document for a writing or content creation activity. Use this when the user asks you to create substantial content (>10 lines), code snippets, or content they will likely save/reuse like emails, essays, or spreadsheets.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "The title of the document. Should be concise and descriptive."
            },
            "kind": {
                "type": "string",
                "enum": ["text", "code", "sheet"],
                "description": "The type of document to create. 'text' for markdown documents, 'code' for Python code snippets, 'sheet' for CSV spreadsheets."
            }
        },
        "required": ["title", "kind"]
    }
}


# updateDocument 도구 정의
UPDATE_DOCUMENT_TOOL: Dict[str, Any] = {
    "name": "updateDocument",
    "description": "Update an existing document with the given description. Default to full document rewrites for major changes. Use targeted updates only for specific, isolated changes. Follow user instructions for which parts to modify. NEVER update a document immediately after creating it - always wait for user feedback first.",
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The ID of the document to update (UUID format)"
            },
            "description": {
                "type": "string",
                "description": "Description of what to update or how to improve the document"
            }
        },
        "required": ["id", "description"]
    }
}


# 모든 아티팩트 도구 목록
ARTIFACT_TOOLS = [
    CREATE_DOCUMENT_TOOL,
    UPDATE_DOCUMENT_TOOL
]


def get_artifact_tools() -> list[Dict[str, Any]]:
    """
    아티팩트 도구 목록 반환

    Returns:
        List[Dict[str, Any]]: Anthropic tool use API 형식의 도구 정의 목록
    """
    return ARTIFACT_TOOLS
