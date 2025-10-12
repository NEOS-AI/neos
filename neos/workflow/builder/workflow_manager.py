"""워크플로우 관리자"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy import select

from neos.database.connection import db_manager
from neos.database.workflow_models import CustomWorkflow, WorkflowStatus


class WorkflowManager:
    """워크플로우 관리자"""

    @staticmethod
    async def list_workflows(
        status: Optional[WorkflowStatus] = None,
        created_by: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """워크플로우 목록 조회"""
        async with db_manager.get_session() as session:
            query = select(CustomWorkflow)

            if status:
                query = query.where(CustomWorkflow.status == status)
            if created_by:
                query = query.where(CustomWorkflow.created_by == created_by)

            result = await session.execute(query)
            workflows = result.scalars().all()

            return [
                {
                    "id": w.id,
                    "name": w.name,
                    "description": w.description,
                    "status": w.status.value,
                    "created_by": w.created_by,
                    "execution_count": w.execution_count,
                    "created_at": w.created_at.isoformat(),
                    "nodes_count": len(w.nodes),
                    "tags": w.tags
                }
                for w in workflows
            ]

    @staticmethod
    async def get_workflow(workflow_id: int) -> Optional[Dict[str, Any]]:
        """특정 워크플로우 조회"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(CustomWorkflow).where(CustomWorkflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()

            if not workflow:
                return None

            return {
                "id": workflow.id,
                "name": workflow.name,
                "description": workflow.description,
                "status": workflow.status.value,
                "created_by": workflow.created_by,
                "config": workflow.config,
                "nodes": workflow.nodes,
                "edges": workflow.edges,
                "execution_count": workflow.execution_count,
                "last_executed_at": workflow.last_executed_at.isoformat() if workflow.last_executed_at else None,
                "created_at": workflow.created_at.isoformat(),
                "tags": workflow.tags
            }

    @staticmethod
    async def update_workflow_status(
        workflow_id: int,
        status: WorkflowStatus
    ) -> bool:
        """워크플로우 상태 업데이트"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(CustomWorkflow).where(CustomWorkflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()

            if not workflow:
                return False

            workflow.status = status
            workflow.updated_at = datetime.utcnow()
            await session.commit()
            return True

    @staticmethod
    async def delete_workflow(workflow_id: int) -> bool:
        """워크플로우 삭제"""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(CustomWorkflow).where(CustomWorkflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()

            if not workflow:
                return False

            await session.delete(workflow)
            await session.commit()
            return True
