"""MCP Server Manager - Improved version with better error handling"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import logging
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from neos.database.connection import db_manager
from neos.database.workflow_models import MCPServer


logger = logging.getLogger(__name__)


class MCPServerManager:
    """MCP 서버 관리자

    데이터베이스 기반 MCP 서버 등록 및 관리 기능을 제공합니다.
    """

    @staticmethod
    async def register_server(
        name: str,
        url: str,
        server_type: str,
        description: str = "",
        config: Dict[str, Any] = None,
        capabilities: List[str] = None,
    ) -> Optional[int]:
        """MCP 서버 등록

        Args:
            name: 서버 이름
            url: 서버 URL
            server_type: 서버 타입
            description: 서버 설명
            config: 서버 설정
            capabilities: 서버 기능 목록

        Returns:
            서버 ID (실패 시 None)

        Raises:
            ValueError: 이미 존재하는 서버명
        """
        try:
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
                    is_active=True,
                )

                session.add(server)
                await session.commit()
                await session.refresh(server)

                logger.info(f"Registered MCP server: {name} (ID: {server.id})")
                return server.id

        except ValueError:
            raise
        except IntegrityError as e:
            logger.error(f"Database integrity error while registering server: {e}")
            return None
        except SQLAlchemyError as e:
            logger.error(f"Database error while registering server: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while registering server: {e}")
            return None

    @staticmethod
    async def list_servers(
        server_type: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """MCP 서버 목록 조회

        Args:
            server_type: 서버 타입 필터
            is_active: 활성화 상태 필터

        Returns:
            서버 정보 리스트
        """
        try:
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
                        "created_at": s.created_at.isoformat() if s.created_at else None,
                    }
                    for s in servers
                ]

        except SQLAlchemyError as e:
            logger.error(f"Database error while listing servers: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error while listing servers: {e}")
            return []

    @staticmethod
    async def get_server(server_id: int) -> Optional[Dict[str, Any]]:
        """특정 MCP 서버 조회

        Args:
            server_id: 서버 ID

        Returns:
            서버 정보 (없으면 None)
        """
        try:
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
                    "created_at": server.created_at.isoformat() if server.created_at else None,
                    "updated_at": server.updated_at.isoformat() if server.updated_at else None,
                }

        except SQLAlchemyError as e:
            logger.error(f"Database error while getting server: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while getting server: {e}")
            return None

    @staticmethod
    async def get_server_by_name(name: str) -> Optional[Dict[str, Any]]:
        """이름으로 MCP 서버 조회

        Args:
            name: 서버 이름

        Returns:
            서버 정보 (없으면 None)
        """
        try:
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
                    "created_at": server.created_at.isoformat() if server.created_at else None,
                    "updated_at": server.updated_at.isoformat() if server.updated_at else None,
                }

        except SQLAlchemyError as e:
            logger.error(f"Database error while getting server by name: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while getting server by name: {e}")
            return None

    @staticmethod
    async def update_server(
        server_id: int,
        url: Optional[str] = None,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
    ) -> bool:
        """MCP 서버 정보 업데이트

        Args:
            server_id: 서버 ID
            url: 서버 URL
            description: 서버 설명
            config: 서버 설정
            capabilities: 서버 기능 목록
            is_active: 활성화 상태

        Returns:
            업데이트 성공 여부
        """
        try:
            async with db_manager.get_session() as session:
                result = await session.execute(
                    select(MCPServer).where(MCPServer.id == server_id)
                )
                server = result.scalar_one_or_none()

                if not server:
                    logger.warning(f"Server not found: ID={server_id}")
                    return False

                # 업데이트
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

                server.updated_at = datetime.now()
                await session.commit()

                logger.info(f"Updated MCP server: {server.name} (ID: {server_id})")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error while updating server: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while updating server: {e}")
            return False

    @staticmethod
    async def delete_server(server_id: int) -> bool:
        """MCP 서버 삭제

        Args:
            server_id: 서버 ID

        Returns:
            삭제 성공 여부
        """
        try:
            async with db_manager.get_session() as session:
                result = await session.execute(
                    select(MCPServer).where(MCPServer.id == server_id)
                )
                server = result.scalar_one_or_none()

                if not server:
                    logger.warning(f"Server not found: ID={server_id}")
                    return False

                server_name = server.name
                await session.delete(server)
                await session.commit()

                logger.info(f"Deleted MCP server: {server_name} (ID: {server_id})")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error while deleting server: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while deleting server: {e}")
            return False

    @staticmethod
    async def toggle_server_status(server_id: int) -> Optional[bool]:
        """MCP 서버 활성화/비활성화 토글

        Args:
            server_id: 서버 ID

        Returns:
            새로운 활성화 상태 (실패 시 None)
        """
        try:
            async with db_manager.get_session() as session:
                result = await session.execute(
                    select(MCPServer).where(MCPServer.id == server_id)
                )
                server = result.scalar_one_or_none()

                if not server:
                    logger.warning(f"Server not found: ID={server_id}")
                    return None

                server.is_active = not server.is_active
                server.updated_at = datetime.now()
                await session.commit()

                logger.info(
                    f"Toggled MCP server status: {server.name} -> {server.is_active}"
                )
                return server.is_active

        except SQLAlchemyError as e:
            logger.error(f"Database error while toggling server status: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while toggling server status: {e}")
            return None


# 전역 인스턴스
mcp_server_manager = MCPServerManager()
