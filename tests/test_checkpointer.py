"""
Unit tests for PostgreSQL Checkpointer

Tests the distributed state management functionality
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from neos.workflow.checkpointer import PostgreSQLCheckpointer, get_checkpointer
from langgraph.checkpoint.base import Checkpoint


@pytest.fixture
async def mock_db_session():
    """Mock database session for testing"""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
async def checkpointer():
    """Create a test checkpointer instance"""
    with patch('neos.workflow.checkpointer.create_async_engine'):
        cp = PostgreSQLCheckpointer(
            database_url="postgresql+asyncpg://test:test@localhost/test_db",
            table_name="test_checkpoints"
        )
        cp._initialized = True  # Skip actual initialization
        return cp


@pytest.mark.unit
class TestPostgreSQLCheckpointer:
    """Test PostgreSQL checkpointer functionality"""

    def test_initialization(self):
        """Test checkpointer initialization"""
        cp = PostgreSQLCheckpointer(
            database_url="postgresql+asyncpg://test:test@localhost/test",
            pool_size=10,
            max_overflow=20,
            table_name="checkpoints"
        )

        assert cp.database_url == "postgresql+asyncpg://test:test@localhost/test"
        assert cp.pool_size == 10
        assert cp.max_overflow == 20
        assert cp.table_name == "checkpoints"
        assert not cp._initialized

    @pytest.mark.asyncio
    async def test_initialize(self, checkpointer):
        """Test database initialization"""
        with patch.object(checkpointer, 'engine', AsyncMock()):
            with patch('neos.workflow.checkpointer.sessionmaker'):
                checkpointer._initialized = False
                await checkpointer.initialize()
                assert checkpointer._initialized

    @pytest.mark.asyncio
    async def test_aput_new_checkpoint(self, checkpointer):
        """Test saving a new checkpoint"""
        config = {
            "configurable": {
                "thread_id": "test_thread_123"
            }
        }

        checkpoint = Checkpoint(
            v=1,
            id="checkpoint_1",
            ts=datetime.utcnow().isoformat(),
            channel_values={"state": "test_state"},
            channel_versions={"channel_1": 1},
            versions_seen={"thread_1": 1}
        )

        metadata = {"user_id": "test_user"}

        # Mock database session
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None  # No existing checkpoint
        mock_session.execute.return_value = mock_result

        with patch.object(checkpointer, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            result = await checkpointer.aput(config, checkpoint, metadata)

            assert isinstance(result, dict)
            assert "configurable" in result
            assert result["configurable"]["thread_id"] == "test_thread_123"
            assert result["configurable"]["checkpoint_id"] == checkpoint.id
            assert mock_session.execute.called

    @pytest.mark.asyncio
    async def test_aput_update_checkpoint(self, checkpointer):
        """Test updating an existing checkpoint"""
        config = {
            "configurable": {
                "thread_id": "test_thread_123"
            }
        }

        checkpoint = Checkpoint(
            v=1,
            id="checkpoint_1",
            ts=datetime.utcnow().isoformat(),
            channel_values={"state": "updated_state"},
            channel_versions={"channel_1": 2},
            versions_seen={"thread_1": 2}
        )

        # Mock existing checkpoint
        mock_session = AsyncMock(spec=AsyncSession)
        mock_existing = MagicMock()
        mock_existing.version = 1
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_existing
        mock_session.execute.return_value = mock_result

        with patch.object(checkpointer, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            result = await checkpointer.aput(config, checkpoint)

            assert isinstance(result, dict)
            assert "configurable" in result
            assert result["configurable"]["thread_id"] == "test_thread_123"
            assert mock_session.execute.called

    @pytest.mark.asyncio
    async def test_aget_existing_checkpoint(self, checkpointer):
        """Test retrieving an existing checkpoint"""
        config = {
            "configurable": {
                "thread_id": "test_thread_123"
            }
        }

        # Mock database response
        mock_row = MagicMock()
        mock_row.checkpoint_id = "checkpoint_1"
        mock_row.created_at = datetime.utcnow()
        mock_row.checkpoint_data = {
            "v": 1,
            "channel_values": {"state": "test_state"},
            "channel_versions": {"channel_1": 1},
            "versions_seen": {"thread_1": 1}
        }

        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result

        with patch.object(checkpointer, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            checkpoint = await checkpointer.aget(config)

            assert checkpoint is not None
            # Checkpoint may be dict or object
            if isinstance(checkpoint, dict):
                assert checkpoint["id"] == "checkpoint_1"
                assert checkpoint["v"] == 1
                assert checkpoint["channel_values"] == {"state": "test_state"}
            else:
                assert checkpoint.id == "checkpoint_1"
                assert checkpoint.v == 1
                assert checkpoint.channel_values == {"state": "test_state"}

    @pytest.mark.asyncio
    async def test_aget_no_checkpoint(self, checkpointer):
        """Test retrieving non-existent checkpoint"""
        config = {
            "configurable": {
                "thread_id": "nonexistent_thread"
            }
        }

        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        with patch.object(checkpointer, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            checkpoint = await checkpointer.aget(config)

            assert checkpoint is None

    @pytest.mark.asyncio
    async def test_alist_checkpoints(self, checkpointer):
        """Test listing checkpoints for a thread"""
        config = {
            "configurable": {
                "thread_id": "test_thread_123"
            }
        }

        # Mock multiple checkpoints
        mock_rows = [
            MagicMock(
                checkpoint_id=f"checkpoint_{i}",
                created_at=datetime.utcnow(),
                checkpoint_data={
                    "v": 1,
                    "channel_values": {"state": f"state_{i}"},
                    "channel_versions": {"channel_1": i},
                    "versions_seen": {"thread_1": i}
                }
            )
            for i in range(3)
        ]

        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = mock_rows
        mock_session.execute.return_value = mock_result

        with patch.object(checkpointer, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            checkpoints = await checkpointer.alist(config, limit=10)

            assert len(checkpoints) == 3
            # Checkpoints may be dicts or objects
            for cp in checkpoints:
                assert isinstance(cp, (dict, Checkpoint)) or hasattr(cp, 'v')

    @pytest.mark.asyncio
    async def test_delete_thread(self, checkpointer):
        """Test deleting all checkpoints for a thread"""
        thread_id = "test_thread_123"

        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.rowcount = 5  # 5 checkpoints deleted
        mock_session.execute.return_value = mock_result

        with patch.object(checkpointer, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            deleted = await checkpointer.delete_thread(thread_id)

            assert deleted is True
            assert mock_session.execute.called

    @pytest.mark.asyncio
    async def test_cleanup_old_checkpoints(self, checkpointer):
        """Test cleaning up old checkpoints"""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.rowcount = 10  # 10 old checkpoints deleted
        mock_session.execute.return_value = mock_result

        with patch.object(checkpointer, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            count = await checkpointer.cleanup_old_checkpoints(days=30)

            assert count == 10

    @pytest.mark.asyncio
    async def test_get_stats(self, checkpointer):
        """Test getting checkpointer statistics"""
        mock_session = AsyncMock(spec=AsyncSession)

        # Mock total checkpoints
        mock_total = MagicMock()
        mock_total.fetchall.return_value = [MagicMock() for _ in range(100)]

        # Mock unique threads
        mock_threads = MagicMock()
        mock_threads.fetchall.return_value = [MagicMock() for _ in range(20)]

        mock_session.execute.side_effect = [mock_total, mock_threads]

        with patch.object(checkpointer, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            stats = await checkpointer.get_stats()

            assert stats["total_checkpoints"] == 100
            assert stats["unique_threads"] == 20
            assert stats["table_name"] == "test_checkpoints"

    @pytest.mark.asyncio
    async def test_close(self, checkpointer):
        """Test closing database connections"""
        mock_engine = AsyncMock()
        checkpointer.engine = mock_engine

        await checkpointer.close()

        assert mock_engine.dispose.called
        assert not checkpointer._initialized

    def test_missing_thread_id(self, checkpointer):
        """Test error when thread_id is missing"""
        config = {"configurable": {}}

        with pytest.raises(ValueError, match="thread_id is required"):
            asyncio.run(checkpointer.aget(config))


@pytest.mark.unit
class TestCheckpointerGlobalInstance:
    """Test global checkpointer instance management"""

    @pytest.mark.asyncio
    async def test_get_checkpointer_singleton(self):
        """Test that get_checkpointer returns singleton"""
        with patch('neos.workflow.checkpointer.PostgreSQLCheckpointer') as mock_class:
            mock_instance = AsyncMock()
            mock_instance.initialize = AsyncMock()
            mock_class.return_value = mock_instance

            # Import fresh to reset module state
            from neos.workflow import checkpointer as cp_module
            cp_module._checkpointer = None

            cp1 = await cp_module.get_checkpointer()
            cp2 = await cp_module.get_checkpointer()

            # Should be same instance
            assert cp1 is cp2
            # Initialize should be called only once
            assert mock_instance.initialize.call_count == 1

    @pytest.mark.asyncio
    async def test_cleanup_checkpointer(self):
        """Test cleanup of global checkpointer"""
        from neos.workflow import checkpointer as cp_module

        # Set up mock checkpointer
        mock_cp = AsyncMock()
        mock_cp.close = AsyncMock()
        cp_module._checkpointer = mock_cp

        await cp_module.cleanup_checkpointer()

        assert mock_cp.close.called
        assert cp_module._checkpointer is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
