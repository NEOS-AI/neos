"""Chat service helpers - dataclass to dict conversion utilities"""

from typing import Dict, Any, List
from neos.database.repositories.chat_repository import Message, Conversation, ConversationAnalytics, ConversationTemplate


def message_to_dict(message: Message) -> Dict[str, Any]:
    """Convert Message dataclass to dictionary"""
    return {
        "message_id": message.message_id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content,
        "content_type": message.content_type,
        "sequence_number": message.sequence_number,
        "parent_message_id": message.parent_message_id,
        "status": message.status,
        "model_name": message.model_name,
        "model_version": message.model_version,
        "prompt_tokens": message.prompt_tokens,
        "completion_tokens": message.completion_tokens,
        "total_tokens": message.total_tokens,
        "finish_reason": message.finish_reason,
        "tool_calls": message.tool_calls,
        "tool_results": message.tool_results,
        "attachments": message.attachments,
        "user_feedback": message.user_feedback,
        "feedback_comment": message.feedback_comment,
        "quality_score": message.quality_score,
        "created_at": message.created_at,
        "updated_at": message.updated_at,
        "completed_at": message.completed_at,
        "metadata": message.metadata
    }


def messages_to_dict_list(messages: List[Message]) -> List[Dict[str, Any]]:
    """Convert list of Message dataclasses to list of dictionaries"""
    return [message_to_dict(msg) for msg in messages]


def analytics_to_dict(analytics: ConversationAnalytics) -> Dict[str, Any]:
    """Convert ConversationAnalytics dataclass to dictionary"""
    return {
        "conversation_id": analytics.conversation_id,
        "analysis_period": analytics.analysis_period,
        "period_start": analytics.period_start,
        "period_end": analytics.period_end,
        "total_messages": analytics.total_messages,
        "user_messages": analytics.user_messages,
        "assistant_messages": analytics.assistant_messages,
        "total_tokens_used": analytics.total_tokens_used,
        "prompt_tokens_used": analytics.prompt_tokens_used,
        "completion_tokens_used": analytics.completion_tokens_used,
        "estimated_cost": analytics.estimated_cost,
        "average_response_time_ms": analytics.average_response_time_ms,
        "average_message_length": analytics.average_message_length,
        "average_quality_score": analytics.average_quality_score,
        "tools_used": analytics.tools_used,
        "tool_call_count": analytics.tool_call_count,
        "positive_feedback_count": analytics.positive_feedback_count,
        "negative_feedback_count": analytics.negative_feedback_count,
        "messages_edited_count": analytics.messages_edited_count,
        "created_at": analytics.created_at,
        "metadata": analytics.metadata
    }


def template_to_dict(template: ConversationTemplate) -> Dict[str, Any]:
    """Convert ConversationTemplate dataclass to dictionary"""
    return {
        "template_id": template.template_id,
        "name": template.name,
        "description": template.description,
        "category": template.category,
        "default_model": template.default_model,
        "default_system_prompt": template.default_system_prompt,
        "default_temperature": template.default_temperature,
        "default_settings": template.default_settings,
        "initial_messages": template.initial_messages,
        "is_public": template.is_public,
        "is_active": template.is_active,
        "created_by": template.created_by,
        "usage_count": template.usage_count,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
        "tags": template.tags,
        "metadata": template.metadata
    }


def templates_to_dict_list(templates: List[ConversationTemplate]) -> List[Dict[str, Any]]:
    """Convert list of ConversationTemplate dataclasses to list of dictionaries"""
    return [template_to_dict(tpl) for tpl in templates]
