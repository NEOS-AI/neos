from datetime import datetime

from sqlalchemy import text

from neos.coding.domain.durability import ExecutionLease, StaleExecutionLease
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

    async def validate_fenced(
        self, *, lease: ExecutionLease, now: datetime
    ) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await self._require_current_lease(session, lease=lease, now=now)

    async def create_fenced(
        self,
        binding: SandboxBinding,
        *,
        lease: ExecutionLease,
        now: datetime,
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
                        SELECT
                            :task_id, :run_id, :sandbox_id, :provider, :image_digest,
                            :workspace_revision, :latest_snapshot_id, :health_state,
                            :mutation_count, 1, :now, :now
                        FROM coding_run_leases
                        WHERE task_id = :task_id
                          AND run_id = :lease_run_id
                          AND worker_id = :worker_id
                          AND fencing_token = :fencing_token
                          AND expires_at > :now
                        ON CONFLICT (task_id) DO NOTHING
                        RETURNING task_id
                        """
                    ),
                    self._fenced_params(binding, lease=lease, now=now),
                )
                if result.first() is not None:
                    return True
                await self._require_current_lease(session, lease=lease, now=now)
                return False

    async def replace_fenced(
        self,
        binding: SandboxBinding,
        *,
        expected_version: int,
        lease: ExecutionLease,
        now: datetime,
    ) -> SandboxBinding | None:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        f"""
                        UPDATE coding_sandbox_bindings AS binding
                        SET run_id = :run_id,
                            sandbox_id = :sandbox_id,
                            provider = :provider,
                            image_digest = :image_digest,
                            workspace_revision = :workspace_revision,
                            latest_snapshot_id = :latest_snapshot_id,
                            health_state = :health_state,
                            mutation_count = :mutation_count,
                            version = binding.version + 1,
                            updated_at = :now
                        WHERE binding.task_id = :task_id
                          AND binding.version = :expected_version
                          AND EXISTS (
                              SELECT 1 FROM coding_run_leases AS lease
                              WHERE lease.task_id = binding.task_id
                                AND lease.run_id = :lease_run_id
                                AND lease.worker_id = :worker_id
                                AND lease.fencing_token = :fencing_token
                                AND lease.expires_at > :now
                          )
                        RETURNING {_COLUMNS}
                        """
                    ),
                    {
                        **self._fenced_params(binding, lease=lease, now=now),
                        "expected_version": expected_version,
                    },
                )
                row = result.first()
                if row is not None:
                    return self._from_row(row)
                await self._require_current_lease(session, lease=lease, now=now)
                return None

    async def replace_admin(
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

    async def delete_admin(self, task_id: str, *, expected_version: int) -> bool:
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

    @classmethod
    def _fenced_params(
        cls,
        binding: SandboxBinding,
        *,
        lease: ExecutionLease,
        now: datetime,
    ) -> dict[str, object]:
        if binding.task_id != lease.task_id or binding.run_id != lease.run_id:
            raise StaleExecutionLease(binding.task_id)
        return {
            **cls._params(binding, now=now),
            "lease_run_id": lease.run_id,
            "worker_id": lease.worker_id,
            "fencing_token": lease.fencing_token,
        }

    @staticmethod
    async def _require_current_lease(session, *, lease: ExecutionLease, now: datetime):
        result = await session.execute(
            text(
                """
                SELECT 1 FROM coding_run_leases
                WHERE task_id = :task_id
                  AND run_id = :run_id
                  AND worker_id = :worker_id
                  AND fencing_token = :fencing_token
                  AND expires_at > :now
                FOR UPDATE
                """
            ),
            {
                "task_id": lease.task_id,
                "run_id": lease.run_id,
                "worker_id": lease.worker_id,
                "fencing_token": lease.fencing_token,
                "now": now,
            },
        )
        if result.first() is None:
            raise StaleExecutionLease(lease.task_id)

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
