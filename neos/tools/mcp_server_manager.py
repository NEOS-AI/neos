"""MCP 서버 관리 모듈"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
from sqlalchemy import select

from neos.database.connection import db_manager
from neos.database.workflow_models import MCPServer


logger = logging.getLogger(__name__)


class MCPServerManager:
    """MCP 서버 관리자"""

    @staticmethod
    async def register_server(
        name: str,
        url: str,
        server_type: str,
        description: str = "",
        config: Dict[str, Any] = None,
        capabilities: List[str] = None
    ) -> int:
        """MCP 서버 등록"""
        async with db_manager.get_session() as session:
            # 중복 확인
            result = await session.execute(
                select(MCPServer).where(MCPServer.name == name)
            )
            existing = result.scalar_one_or_none()

            if existing:
                raise ValueError(f"MCP server with name '{name}' already exists")

            # 새 서버 생성
            server = MCPServer(
                name=name,
                url=url,
                server_type=server_type,
                description=description,
                config=config or {},
                capabilities=capabilities or [],
                is_active=True
            )

            session.add(server)
            await session.commit()

            logger.info(f"Registered MCP server: {name} (ID: {server.id})")
            return server.id

    @staticmethod
    async def list_servers(
        server_type: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """MCP 서버 목록 조회"""
        async with db_manager.get_session() as session:
            query = select(MCPServer)

            if server_type:
                query = query.where(MCPServer.server_type == server_type)
            if is_active is not None:
                query = query.where(MCPServer.is_active == is_active)

            result = await session.execute(query)
            servers = result.scalars().all()

            return [
                {
                    "id": s.id,
                    "name": s.name,
                    "url": s.url,
                    "server_type": s.server_type,
                    "description": s.description,
                    "capabilities": s.capabilities,
                    "is_active": s.is_active,
                    "created_at": s.created_at.isoformat()
                }
                for s in servers
            ]

    @staticmethod
    async def get_server(server_id: int) -> Optional[Dict[str, Any]]:
        """특정 MCP 서버 조회"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(MCPServer).where(MCPServer.id == server_id)
            )
            server = result.scalar_one_or_none()

            if not server:
                return None

            return {
                "id": server.id,
                "name": server.name,
                "url": server.url,
                "server_type": server.server_type,
                "description": server.description,
                "config": server.config,
                "capabilities": server.capabilities,
                "is_active": server.is_active,
                "created_at": server.created_at.isoformat(),
                "updated_at": server.updated_at.isoformat()
            }

    @staticmethod
    async def get_server_by_name(name: str) -> Optional[Dict[str, Any]]:
        """이름으로 MCP 서버 조회"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(MCPServer).where(MCPServer.name == name)
            )
            server = result.scalar_one_or_none()

            if not server:
                return None

            return {
                "id": server.id,
                "name": server.name,
                "url": server.url,
                "server_type": server.server_type,
                "description": server.description,
                "config": server.config,
                "capabilities": server.capabilities,
                "is_active": server.is_active,
                "created_at": server.created_at.isoformat(),
                "updated_at": server.updated_at.isoformat()
            }

    @staticmethod
    async def update_server(
        server_id: int,
        url: Optional[str] = None,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[str]] = None,
        is_active: Optional[bool] = None
    ) -> bool:
        """MCP 서버 정보 업데이트"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(MCPServer).where(MCPServer.id == server_id)
            )
            server = result.scalar_one_or_none()

            if not server:
                return False

            if url is not None:
                server.url = url
            if description is not None:
                server.description = description
            if config is not None:
                server.config = config
            if capabilities is not None:
                server.capabilities = capabilities
            if is_active is not None:
                server.is_active = is_active

            server.updated_at = datetime.utcnow()
            await session.commit()

            logger.info(f"Updated MCP server: {server.name} (ID: {server_id})")
            return True

    @staticmethod
    async def delete_server(server_id: int) -> bool:
        """MCP 서버 삭제"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(MCPServer).where(MCPServer.id == server_id)
            )
            server = result.scalar_one_or_none()

            if not server:
                return False

            await session.delete(server)
            await session.commit()

            logger.info(f"Deleted MCP server: {server.name} (ID: {server_id})")
            return True

    @staticmethod
    async def toggle_server_status(server_id: int) -> Optional[bool]:
        """MCP 서버 활성화/비활성화 토글"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(MCPServer).where(MCPServer.id == server_id)
            )
            server = result.scalar_one_or_none()

            if not server:
                return None

            server.is_active = not server.is_active
            server.updated_at = datetime.utcnow()
            await session.commit()

            logger.info(f"Toggled MCP server status: {server.name} -> {server.is_active}")
            return server.is_active


# 전역 인스턴스
mcp_server_manager = MCPServerManager()
