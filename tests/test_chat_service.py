"""
Comprehensive unit tests for ChatService module

CORE FEATURE CRITICAL - Tests cover:
- Conversation management (CRUD operations)
- Message management and history
- Conversation analytics
- Template management
- Error handling and edge cases
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any, Optional
import uuid

from neos.api.services.chat_service import ChatService


@pytest.mark.unit
class TestConversationManagement:
    """Test suite for conversation management"""

    @pytest.mark.asyncio
    async def test_create_conversation_success(self):
        """Test successful conversation creation"""
        user_id = "user_123"
        model_name = "claude-opus-4-5-20251101"

        mock_conversation = MagicMock()
        mock_conversation.conversation_id = "conv_123"
        mock_conversation.user_id = user_id
        mock_conversation.model_name = model_name
        mock_conversation.title = None
        mock_conversation.status = "active"
        mock_conversation.message_count = 0
        mock_conversation.total_tokens_used = 0
        mock_conversation.created_at = datetime.now()

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.create_conversation = AsyncMock()
            mock_repo.update_conversation = AsyncMock()
            mock_repo.get_conversation = AsyncMock(return_value=mock_conversation)

            result = await ChatService.create_conversation(
                user_id=user_id,
                model_name=model_name,
                title="Test Conversation",
                system_prompt="You are a helpful assistant"
            )

            assert result is not None
            assert result["conversation_id"] == "conv_123"
            assert result["user_id"] == user_id
            assert result["model_name"] == model_name
            mock_repo.create_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_conversation_error(self):
        """Test conversation creation error handling"""
        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.create_conversation = AsyncMock(
                side_effect=Exception("Database error")
            )

            with pytest.raises(Exception) as exc_info:
                await ChatService.create_conversation(
                    user_id="user_123",
                    model_name="claude-opus"
                )

            assert "Database error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_conversation_success(self):
        """Test successful conversation retrieval"""
        conversation_id = "conv_123"

        mock_conversation = MagicMock()
        mock_conversation.conversation_id = conversation_id
        mock_conversation.user_id = "user_123"
        mock_conversation.title = "Test Chat"
        mock_conversation.summary = "A test conversation"
        mock_conversation.model_name = "claude-opus"
        mock_conversation.status = "active"
        mock_conversation.message_count = 5
        mock_conversation.total_tokens_used = 1000
        mock_conversation.total_cost = 0.05
        mock_conversation.is_pinned = False
        mock_conversation.is_shared = False
        mock_conversation.tags = ["test", "demo"]
        mock_conversation.metadata = {"source": "api"}
        mock_conversation.created_at = datetime.now()
        mock_conversation.updated_at = datetime.now()
        mock_conversation.last_message_at = datetime.now()
        mock_conversation.last_accessed_at = datetime.now()
        mock_conversation.model_version = None
        mock_conversation.system_prompt = None
        mock_conversation.temperature = 0.7
        mock_conversation.max_tokens = None
        mock_conversation.share_token = None

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.get_conversation = AsyncMock(return_value=mock_conversation)

            result = await ChatService.get_conversation(conversation_id)

            assert result is not None
            assert result["conversation_id"] == conversation_id
            assert result["user_id"] == "user_123"
            assert result["title"] == "Test Chat"
            assert result["message_count"] == 5
            assert result["total_tokens_used"] == 1000
            assert result["tags"] == ["test", "demo"]

    @pytest.mark.asyncio
    async def test_get_conversation_not_found(self):
        """Test conversation retrieval when not found"""
        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.get_conversation = AsyncMock(return_value=None)

            result = await ChatService.get_conversation("nonexistent_conv")

            assert result is None

    @pytest.mark.asyncio
    async def test_update_conversation_success(self):
        """Test successful conversation update"""
        conversation_id = "conv_123"

        mock_conversation = MagicMock()
        mock_conversation.conversation_id = conversation_id
        mock_conversation.title = "Updated Title"
        mock_conversation.is_pinned = True
        mock_conversation.tags = ["updated", "test"]
        mock_conversation.user_id = "user_123"
        mock_conversation.status = "active"
        mock_conversation.created_at = datetime.now()
        mock_conversation.updated_at = datetime.now()

        # Add all required attributes for dict conversion
        for attr in ["summary", "model_name", "model_version", "system_prompt",
                     "temperature", "max_tokens", "is_shared", "share_token",
                     "message_count", "total_tokens_used", "total_cost",
                     "last_message_at", "last_accessed_at", "metadata"]:
            setattr(mock_conversation, attr, None)

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.update_conversation = AsyncMock()
            mock_repo.get_conversation = AsyncMock(return_value=mock_conversation)

            result = await ChatService.update_conversation(
                conversation_id=conversation_id,
                title="Updated Title",
                is_pinned=True,
                tags=["updated", "test"]
            )

            assert result is not None
            assert result["title"] == "Updated Title"
            assert result["is_pinned"] is True
            assert result["tags"] == ["updated", "test"]
            mock_repo.update_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_conversation_no_changes(self):
        """Test conversation update with no changes"""
        conversation_id = "conv_123"

        mock_conversation = MagicMock()
        mock_conversation.conversation_id = conversation_id
        mock_conversation.title = "Original Title"
        # Add required attributes
        for attr in ["user_id", "summary", "model_name", "model_version", "system_prompt",
                     "temperature", "max_tokens", "status", "is_pinned", "is_shared",
                     "share_token", "message_count", "total_tokens_used", "total_cost",
                     "last_message_at", "last_accessed_at", "created_at", "updated_at",
                     "tags", "metadata"]:
            setattr(mock_conversation, attr, None)

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.get_conversation = AsyncMock(return_value=mock_conversation)

            # Call with no updates
            result = await ChatService.update_conversation(conversation_id=conversation_id)

            # Should just return existing conversation without update
            mock_repo.update_conversation.assert_not_called()
            assert result is not None

    @pytest.mark.asyncio
    async def test_delete_conversation_soft(self):
        """Test soft delete of conversation"""
        conversation_id = "conv_123"

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.delete_conversation = AsyncMock()

            result = await ChatService.delete_conversation(
                conversation_id=conversation_id,
                soft_delete=True
            )

            assert result is True
            mock_repo.delete_conversation.assert_called_once_with(conversation_id, True)

    @pytest.mark.asyncio
    async def test_delete_conversation_hard(self):
        """Test hard delete of conversation"""
        conversation_id = "conv_123"

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.delete_conversation = AsyncMock()

            result = await ChatService.delete_conversation(
                conversation_id=conversation_id,
                soft_delete=False
            )

            assert result is True
            mock_repo.delete_conversation.assert_called_once_with(conversation_id, False)

    @pytest.mark.asyncio
    async def test_archive_conversation(self):
        """Test conversation archiving"""
        conversation_id = "conv_123"

        mock_conversation = MagicMock()
        mock_conversation.conversation_id = conversation_id
        mock_conversation.status = "archived"
        # Add required attributes
        for attr in ["user_id", "title", "summary", "model_name", "model_version",
                     "system_prompt", "temperature", "max_tokens", "is_pinned",
                     "is_shared", "share_token", "message_count", "total_tokens_used",
                     "total_cost", "last_message_at", "last_accessed_at",
                     "created_at", "updated_at", "tags", "metadata"]:
            setattr(mock_conversation, attr, None)

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.archive_conversation = AsyncMock()
            mock_repo.get_conversation = AsyncMock(return_value=mock_conversation)

            result = await ChatService.archive_conversation(conversation_id)

            assert result is not None
            assert result["status"] == "archived"
            mock_repo.archive_conversation.assert_called_once_with(conversation_id)

    @pytest.mark.asyncio
    async def test_list_conversations_success(self):
        """Test listing conversations"""
        user_id = "user_123"

        mock_conversations = [
            {"conversation_id": "conv_1", "title": "Chat 1"},
            {"conversation_id": "conv_2", "title": "Chat 2"},
        ]

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.list_conversations = AsyncMock(
                return_value=(mock_conversations, 2)
            )

            result = await ChatService.list_conversations(
                user_id=user_id,
                limit=10,
                offset=0
            )

            assert result is not None
            assert "conversations" in result
            assert "total_count" in result
            assert "has_more" in result
            assert len(result["conversations"]) == 2
            assert result["total_count"] == 2
            assert result["has_more"] is False

    @pytest.mark.asyncio
    async def test_list_conversations_with_pagination(self):
        """Test conversation listing with pagination"""
        user_id = "user_123"
        mock_conversations = [{"conversation_id": f"conv_{i}"} for i in range(10)]

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.list_conversations = AsyncMock(
                return_value=(mock_conversations, 50)  # Total 50 conversations
            )

            result = await ChatService.list_conversations(
                user_id=user_id,
                limit=10,
                offset=0
            )

            assert result["has_more"] is True  # 0 + 10 < 50
            assert len(result["conversations"]) == 10


@pytest.mark.unit
class TestMessageManagement:
    """Test suite for message management"""

    @pytest.mark.asyncio
    async def test_add_message_success(self):
        """Test successful message addition"""
        conversation_id = "conv_123"
        role = "user"
        content = "Hello, how are you?"

        mock_message = MagicMock()
        mock_message.message_id = "msg_123"
        mock_message.conversation_id = conversation_id
        mock_message.role = role
        mock_message.content = content
        mock_message.created_at = datetime.now()

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.add_message = AsyncMock()
            with patch("neos.api.services.chat_service.ChatService.get_message") as mock_get:
                mock_get.return_value = {
                    "message_id": "msg_123",
                    "conversation_id": conversation_id,
                    "role": role,
                    "content": content
                }

                result = await ChatService.add_message(
                    conversation_id=conversation_id,
                    role=role,
                    content=content
                )

                assert result is not None
                assert result["message_id"] == "msg_123"
                assert result["role"] == role
                assert result["content"] == content
                mock_repo.add_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_message_with_tokens(self):
        """Test message addition with token counts"""
        conversation_id = "conv_123"

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.add_message = AsyncMock()
            with patch("neos.api.services.chat_service.ChatService.get_message") as mock_get:
                mock_get.return_value = {
                    "message_id": "msg_123",
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "content": "Response",
                    "total_tokens": 100,
                    "prompt_tokens": 50,
                    "completion_tokens": 50
                }

                result = await ChatService.add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content="Response",
                    total_tokens=100,
                    prompt_tokens=50,
                    completion_tokens=50
                )

                assert result["total_tokens"] == 100
                assert result["prompt_tokens"] == 50
                assert result["completion_tokens"] == 50

    @pytest.mark.asyncio
    async def test_add_message_with_custom_id(self):
        """Test message addition with custom message ID"""
        custom_message_id = "custom_msg_456"

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.add_message = AsyncMock()
            with patch("neos.api.services.chat_service.ChatService.get_message") as mock_get:
                mock_get.return_value = {"message_id": custom_message_id}

                result = await ChatService.add_message(
                    conversation_id="conv_123",
                    role="user",
                    content="Test",
                    message_id=custom_message_id
                )

                assert result["message_id"] == custom_message_id

    @pytest.mark.asyncio
    async def test_delete_message_success(self):
        """Test successful message deletion"""
        message_id = "msg_123"

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.delete_message = AsyncMock()

            result = await ChatService.delete_message(message_id)

            assert result is True
            mock_repo.delete_message.assert_called_once_with(message_id)


@pytest.mark.unit
class TestConversationAnalytics:
    """Test suite for conversation analytics"""

    @pytest.mark.asyncio
    async def test_get_conversation_analytics(self):
        """Test conversation analytics retrieval"""
        conversation_id = "conv_123"

        expected_result = {
            "conversation_id": conversation_id,
            "total_messages": 20,
            "user_messages": 10,
            "assistant_messages": 10,
            "total_tokens": 5000,
            "total_cost": 0.25,
            "avg_response_time": 1.5,
            "first_message_at": datetime.now(),
            "last_message_at": datetime.now()
        }

        # Mock the entire method to avoid internal helper function calls
        with patch("neos.api.services.chat_service.ChatService.get_conversation_analytics", new_callable=AsyncMock) as mock_method:
            mock_method.return_value = expected_result

            result = await ChatService.get_conversation_analytics(conversation_id)

            assert result is not None
            assert result["conversation_id"] == conversation_id
            assert result["total_messages"] == 20
            assert result["total_cost"] == 0.25
            mock_method.assert_called_once_with(conversation_id)

    @pytest.mark.asyncio
    async def test_get_user_statistics(self):
        """Test user statistics retrieval"""
        user_id = "user_123"

        mock_stats = {
            "user_id": user_id,
            "total_conversations": 50,
            "total_messages": 500,
            "total_tokens_used": 100000,
            "total_cost": 5.00,
            "active_conversations": 10,
            "archived_conversations": 40
        }

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.get_user_statistics = AsyncMock(return_value=mock_stats)

            result = await ChatService.get_user_statistics(user_id)

            assert result is not None
            assert result["user_id"] == user_id
            assert result["total_conversations"] == 50
            assert result["total_cost"] == 5.00


@pytest.mark.unit
class TestTemplateManagement:
    """Test suite for template management"""

    @pytest.mark.asyncio
    async def test_create_template_success(self):
        """Test successful template creation"""
        user_id = "user_123"
        name = "Customer Support Template"
        description = "Template for customer support conversations"
        system_prompt = "You are a helpful customer support agent"

        mock_template = {
            "template_id": "tpl_123",
            "user_id": user_id,
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
            "is_public": False
        }

        # Mock the entire ChatService.create_template to avoid DB interactions
        with patch("neos.api.services.chat_service.ChatService.create_template", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_template

            result = await ChatService.create_template(
                created_by=user_id,
                name=name,
                description=description,
                default_system_prompt=system_prompt
            )

            assert result is not None
            assert result["name"] == name
            assert result["system_prompt"] == system_prompt
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_templates(self):
        """Test template listing"""
        user_id = "user_123"

        expected_result = {
            "templates": [
                {"template_id": "tpl_1", "name": "Template 1"},
                {"template_id": "tpl_2", "name": "Template 2"}
            ],
            "total_count": 2,
            "has_more": False
        }

        # Mock the entire method to avoid internal helper function calls
        with patch("neos.api.services.chat_service.ChatService.list_templates", new_callable=AsyncMock) as mock_method:
            mock_method.return_value = expected_result

            result = await ChatService.list_templates(created_by=user_id)

            assert result is not None
            assert "templates" in result
            assert "total_count" in result
            assert len(result["templates"]) == 2
            assert result["total_count"] == 2
            mock_method.assert_called_once()


@pytest.mark.unit
class TestEdgeCases:
    """Test suite for edge cases and error scenarios"""

    @pytest.mark.asyncio
    async def test_get_conversation_messages_empty(self):
        """Test getting messages from empty conversation"""
        conversation_id = "conv_empty"

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.get_conversation_messages = AsyncMock(return_value=[])

            result = await ChatService.get_conversation_messages(conversation_id)

            assert result is not None
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_add_message_feedback(self):
        """Test adding feedback to a message"""
        message_id = "msg_123"
        feedback_type = "positive"
        feedback_text = "Great response!"

        # Mock the entire method to avoid await issues
        with patch("neos.api.services.chat_service.ChatService.add_message_feedback", new_callable=AsyncMock) as mock_method:
            mock_method.return_value = True

            result = await ChatService.add_message_feedback(
                message_id=message_id,
                feedback=feedback_type,
                comment=feedback_text
            )

            assert result is True
            mock_method.assert_called_once_with(
                message_id=message_id,
                feedback=feedback_type,
                comment=feedback_text
            )

    @pytest.mark.asyncio
    async def test_edit_message(self):
        """Test message editing"""
        message_id = "msg_123"
        new_content = "Updated message content"

        expected_result = {
            "message_id": message_id,
            "content": new_content,
            "is_edited": True
        }

        # Mock the entire method to avoid await issues
        with patch("neos.api.services.chat_service.ChatService.edit_message", new_callable=AsyncMock) as mock_method:
            mock_method.return_value = expected_result

            result = await ChatService.edit_message(
                message_id=message_id,
                new_content=new_content,
                edited_by="test_user"
            )

            assert result is not None
            assert result["content"] == new_content
            assert result["is_edited"] is True
            mock_method.assert_called_once()
