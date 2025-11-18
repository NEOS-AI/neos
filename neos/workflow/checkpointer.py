"""
PostgreSQL Checkpointer for LangGraph - Enterprise State Management

This module provides a distributed, persistent checkpointing solution for LangGraph
workflows, replacing the in-memory MemorySaver with a PostgreSQL-backed implementation
that enables horizontal scaling and state persistence across server restarts.

Features:
- Distributed state management
- Session persistence
- Horizontal scalability
- State recovery and replay
- Transaction support
"""

from typing import Any, Dict, Optional, List, Tuple
from datetime import datetime
import json
import asyncio
from contextlib import asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import (
    Column, String, Text, DateTime, Integer, select, delete,
    MetaData, Table, and_, desc
)
from sqlalchemy.dialects.postgresql import JSONB

from neos.config.settings import settings


class PostgreSQLCheckpointer(BaseCheckpointSaver):
    """
    PostgreSQL-backed checkpoint saver for LangGraph workflows.

    Provides enterprise-grade state management with:
    - Persistent storage across restarts
    - Support for horizontal scaling
    - Transaction safety
    - State versioning
    - Efficient querying and cleanup

    Usage:
        checkpointer = PostgreSQLCheckpointer(database_url)
        await checkpointer.initialize()

        workflow = StateGraph(AgentState)
        # ... add nodes
        graph = workflow.compile(checkpointer=checkpointer)
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        pool_size: int = 20,
        max_overflow: int = 40,
        table_name: str = "langgraph_checkpoints"
    ):
        """
        Initialize PostgreSQL checkpointer.

        Args:
            database_url: PostgreSQL connection URL (uses settings if None)
            pool_size: Connection pool size for concurrent workflows
            max_overflow: Maximum overflow connections
            table_name: Table name for storing checkpoints
        """
        self.database_url = database_url or settings.DATABASE_URL
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.table_name = table_name

        # Engine will be initialized in initialize()
        self.engine: Optional[AsyncEngine] = None
        self.SessionLocal = None
        self.metadata = MetaData()

        # Define checkpoint table schema
        self.checkpoints_table = Table(
            self.table_name,
            self.metadata,
            Column("thread_id", String(255), primary_key=True, index=True),
            Column("checkpoint_id", String(255), primary_key=True),
            Column("parent_checkpoint_id", String(255), nullable=True, index=True),
            Column("checkpoint_data", JSONB, nullable=False),
            Column("metadata", JSONB, nullable=True),
            Column("created_at", DateTime, default=datetime.utcnow, index=True),
            Column("version", Integer, default=1),
        )

        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self):
        """
        Initialize database engine and create tables.
        Must be called before using the checkpointer.
        """
        async with self._lock:
            if self._initialized:
                return

            # Create async engine
            self.engine = create_async_engine(
                self.database_url,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                echo=settings.DEBUG,
                pool_pre_ping=True,  # Verify connections before use
                pool_recycle=3600,   # Recycle connections after 1 hour
            )

            # Create session factory
            self.SessionLocal = sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )

            # Create tables if they don't exist
            async with self.engine.begin() as conn:
                await conn.run_sync(self.metadata.create_all)

            self._initialized = True
            print(f"[INFO] PostgreSQLCheckpointer initialized with table: {self.table_name}")

    @asynccontextmanager
    async def get_session(self):
        """Get database session with automatic cleanup."""
        if not self._initialized:
            await self.initialize()

        async with self.SessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def aget(
        self,
        config: Dict[str, Any],
    ) -> Optional[Checkpoint]:
        """
        Retrieve the latest checkpoint for a thread.

        Args:
            config: Configuration containing thread_id

        Returns:
            Checkpoint object or None if not found
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            raise ValueError("thread_id is required in config.configurable")

        async with self.get_session() as session:
            # Get the latest checkpoint for this thread
            stmt = (
                select(self.checkpoints_table)
                .where(self.checkpoints_table.c.thread_id == thread_id)
                .order_by(desc(self.checkpoints_table.c.created_at))
                .limit(1)
            )

            result = await session.execute(stmt)
            row = result.fetchone()

            if row is None:
                return None

            # Convert database row to Checkpoint object
            checkpoint_data = row.checkpoint_data

            return Checkpoint(
                v=checkpoint_data.get("v", 1),
                id=row.checkpoint_id,
                ts=row.created_at.isoformat(),
                channel_values=checkpoint_data.get("channel_values", {}),
                channel_versions=checkpoint_data.get("channel_versions", {}),
                versions_seen=checkpoint_data.get("versions_seen", {}),
            )

    async def aput(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Save a checkpoint to the database.

        Args:
            config: Configuration containing thread_id
            checkpoint: Checkpoint object to save
            metadata: Optional metadata to store with checkpoint

        Returns:
            Updated config with checkpoint information
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            raise ValueError("thread_id is required in config.configurable")

        checkpoint_id = checkpoint.id

        # Serialize checkpoint data
        checkpoint_data = {
            "v": checkpoint.v,
            "channel_values": checkpoint.channel_values,
            "channel_versions": checkpoint.channel_versions,
            "versions_seen": checkpoint.versions_seen,
        }

        async with self.get_session() as session:
            # Check if checkpoint exists
            stmt = select(self.checkpoints_table).where(
                and_(
                    self.checkpoints_table.c.thread_id == thread_id,
                    self.checkpoints_table.c.checkpoint_id == checkpoint_id
                )
            )
            result = await session.execute(stmt)
            existing = result.fetchone()

            if existing:
                # Update existing checkpoint
                update_stmt = (
                    self.checkpoints_table.update()
                    .where(
                        and_(
                            self.checkpoints_table.c.thread_id == thread_id,
                            self.checkpoints_table.c.checkpoint_id == checkpoint_id
                        )
                    )
                    .values(
                        checkpoint_data=checkpoint_data,
                        metadata=metadata or {},
                        version=existing.version + 1
                    )
                )
                await session.execute(update_stmt)
            else:
                # Insert new checkpoint
                insert_stmt = self.checkpoints_table.insert().values(
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=metadata.get("parent_checkpoint_id") if metadata else None,
                    checkpoint_data=checkpoint_data,
                    metadata=metadata or {},
                    created_at=datetime.utcnow(),
                    version=1
                )
                await session.execute(insert_stmt)

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id
            }
        }

    async def alist(
        self,
        config: Dict[str, Any],
        limit: Optional[int] = 10,
        before: Optional[str] = None,
    ) -> List[Checkpoint]:
        """
        List checkpoints for a thread.

        Args:
            config: Configuration containing thread_id
            limit: Maximum number of checkpoints to return
            before: Return checkpoints before this checkpoint_id

        Returns:
            List of Checkpoint objects
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            raise ValueError("thread_id is required in config.configurable")

        async with self.get_session() as session:
            stmt = (
                select(self.checkpoints_table)
                .where(self.checkpoints_table.c.thread_id == thread_id)
                .order_by(desc(self.checkpoints_table.c.created_at))
            )

            if before:
                # Get timestamp of 'before' checkpoint
                before_stmt = select(self.checkpoints_table.c.created_at).where(
                    and_(
                        self.checkpoints_table.c.thread_id == thread_id,
                        self.checkpoints_table.c.checkpoint_id == before
                    )
                )
                before_result = await session.execute(before_stmt)
                before_ts = before_result.scalar()

                if before_ts:
                    stmt = stmt.where(self.checkpoints_table.c.created_at < before_ts)

            if limit:
                stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            rows = result.fetchall()

            checkpoints = []
            for row in rows:
                checkpoint_data = row.checkpoint_data
                checkpoints.append(
                    Checkpoint(
                        v=checkpoint_data.get("v", 1),
                        id=row.checkpoint_id,
                        ts=row.created_at.isoformat(),
                        channel_values=checkpoint_data.get("channel_values", {}),
                        channel_versions=checkpoint_data.get("channel_versions", {}),
                        versions_seen=checkpoint_data.get("versions_seen", {}),
                    )
                )

            return checkpoints

    async def delete_thread(self, thread_id: str) -> bool:
        """
        Delete all checkpoints for a thread.

        Args:
            thread_id: Thread ID to delete

        Returns:
            True if checkpoints were deleted
        """
        async with self.get_session() as session:
            stmt = delete(self.checkpoints_table).where(
                self.checkpoints_table.c.thread_id == thread_id
            )
            result = await session.execute(stmt)
            return result.rowcount > 0

    async def cleanup_old_checkpoints(self, days: int = 30) -> int:
        """
        Clean up checkpoints older than specified days.

        Args:
            days: Number of days to retain checkpoints

        Returns:
            Number of checkpoints deleted
        """
        from datetime import timedelta

        cutoff_date = datetime.utcnow() - timedelta(days=days)

        async with self.get_session() as session:
            stmt = delete(self.checkpoints_table).where(
                self.checkpoints_table.c.created_at < cutoff_date
            )
            result = await session.execute(stmt)
            count = result.rowcount

            if count > 0:
                print(f"[INFO] Cleaned up {count} old checkpoints")

            return count

    async def get_stats(self) -> Dict[str, Any]:
        """
        Get checkpointer statistics.

        Returns:
            Dictionary with statistics
        """
        async with self.get_session() as session:
            # Total checkpoints
            total_stmt = select(self.checkpoints_table)
            total_result = await session.execute(total_stmt)
            total_checkpoints = len(total_result.fetchall())

            # Unique threads
            threads_stmt = select(self.checkpoints_table.c.thread_id).distinct()
            threads_result = await session.execute(threads_stmt)
            unique_threads = len(threads_result.fetchall())

            return {
                "total_checkpoints": total_checkpoints,
                "unique_threads": unique_threads,
                "table_name": self.table_name,
                "database_url": self.database_url.split("@")[-1],  # Hide credentials
            }

    async def close(self):
        """Close database connections."""
        if self.engine:
            await self.engine.dispose()
            self._initialized = False
            print("[INFO] PostgreSQLCheckpointer connections closed")


# Global checkpointer instance
_checkpointer: Optional[PostgreSQLCheckpointer] = None


async def get_checkpointer() -> PostgreSQLCheckpointer:
    """
    Get or create global checkpointer instance.

    Returns:
        Initialized PostgreSQLCheckpointer instance
    """
    global _checkpointer

    if _checkpointer is None:
        _checkpointer = PostgreSQLCheckpointer()
        await _checkpointer.initialize()

    return _checkpointer


async def cleanup_checkpointer():
    """Cleanup global checkpointer on application shutdown."""
    global _checkpointer

    if _checkpointer:
        await _checkpointer.close()
        _checkpointer = None
