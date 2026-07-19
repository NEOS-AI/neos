from datetime import datetime

from sqlalchemy import text

from neos.coding.persistence.postgres import SessionFactory
from neos.coding.sandbox.bindings import SandboxBinding


_COLUMNS = """
task_id, run_id, sandbox_id, provider, image_digest, workspace_revision,
latest_snapshot_id, health_state, mutation_count, version
"""


class PostgresSandboxBindingRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get(self, task_id: str) -> SandboxBinding | None:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(f"SELECT {_COLUMNS} FROM coding_sandbox_bindings WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
        return self._from_row(result.first())

    async def create(
        self, binding: SandboxBinding, *, now: datetime
    ) -> bool:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        INSERT INTO coding_sandbox_bindings
                            (task_id, run_id, sandbox_id, provider, image_digest,
                             workspace_revision, latest_snapshot_id, health_state,
                             mutation_count, version, created_at, updated_at)
                        VALUES
                            (:task_id, :run_id, :sandbox_id, :provider, :image_digest,
                             :workspace_revision, :latest_snapshot_id, :health_state,
                             :mutation_count, 1, :now, :now)
                        ON CONFLICT (task_id) DO NOTHING
                        RETURNING task_id
                        """
                    ),
                    self._params(binding, now=now),
                )
        return result.first() is not None

    async def replace(
        self,
        binding: SandboxBinding,
        *,
        expected_version: int,
        now: datetime,
    ) -> SandboxBinding | None:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        f"""
                        UPDATE coding_sandbox_bindings
                        SET run_id = :run_id,
                            sandbox_id = :sandbox_id,
                            provider = :provider,
                            image_digest = :image_digest,
                            workspace_revision = :workspace_revision,
                            latest_snapshot_id = :latest_snapshot_id,
                            health_state = :health_state,
                            mutation_count = :mutation_count,
                            version = version + 1,
                            updated_at = :now
                        WHERE task_id = :task_id AND version = :expected_version
                        RETURNING {_COLUMNS}
                        """
                    ),
                    {
                        **self._params(binding, now=now),
                        "expected_version": expected_version,
                    },
                )
        return self._from_row(result.first())

    async def delete(self, task_id: str, *, expected_version: int) -> bool:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        DELETE FROM coding_sandbox_bindings
                        WHERE task_id = :task_id AND version = :expected_version
                        RETURNING task_id
                        """
                    ),
                    {"task_id": task_id, "expected_version": expected_version},
                )
        return result.first() is not None

    @staticmethod
    def _params(binding: SandboxBinding, *, now: datetime) -> dict[str, object]:
        return {
            "task_id": binding.task_id,
            "run_id": binding.run_id,
            "sandbox_id": binding.sandbox_id,
            "provider": binding.provider,
            "image_digest": binding.image_digest,
            "workspace_revision": binding.workspace_revision,
            "latest_snapshot_id": binding.latest_snapshot_id,
            "health_state": binding.health_state,
            "mutation_count": binding.mutation_count,
            "now": now,
        }

    @staticmethod
    def _from_row(row) -> SandboxBinding | None:
        if row is None:
            return None
        return SandboxBinding(
            task_id=row[0],
            run_id=row[1],
            sandbox_id=row[2],
            provider=row[3],
            image_digest=row[4],
            workspace_revision=row[5],
            latest_snapshot_id=row[6],
            health_state=row[7],
            mutation_count=int(row[8]),
            version=int(row[9]),
        )
