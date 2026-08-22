"""provider 서킷과 드레인의 내구 저장소 (마이그레이션 046 · CA8·CA11).

`ProviderHealthCircuit` 은 여전히 **판정의 유일한 구현**이다. 이 저장소가
하는 일은 그 판정의 재료(관측 창)를 프로세스 밖으로 실어 나르는 것뿐이다 --
비율 계산을 SQL 로 옮기면 판정이 두 곳에 생기고, 갈라진 쪽은 아무도 모른다.

관측 한 건의 처리는 **한 트랜잭션 안의 읽기-수정-쓰기**다:
행을 잠그고 → 창을 꺼내 서킷에 넣고 → `observe()` 한 번 → 결과를 다시 쓴다.
잠그지 않으면 두 워커의 관측이 서로를 덮어써서 창이 실제보다 짧아진다.
"""

from datetime import datetime

from sqlalchemy import text

from neos.coding.managed.health import (
    ProviderCircuitState,
    ProviderHealthCircuit,
    ProviderHealthRecord,
    ProviderHealthSnapshot,
    ProviderObservation,
    resolve_admission_health,
)
from neos.coding.persistence.postgres import SessionFactory


class PostgresProviderHealthStore:
    """`ProviderHealth` 프로토콜(`admission.py`)의 내구 구현.

    admission 이 보는 `state()` 는 드레인과 서킷을 합친 하나의 값이다 --
    합치는 규칙은 `resolve_admission_health()` 한 곳에 있다.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        circuit_factory,
        clock,
    ) -> None:
        self._session_factory = session_factory
        # 서킷은 **호출마다 새로 만든다.** 인스턴스에 들고 있으면 그 안의
        # 인메모리 창이 DB 의 창과 갈라지고, 어느 쪽이 진실인지 알 수 없게
        # 된다. 이 저장소에서 서킷은 순수 계산기다.
        self._circuit_factory = circuit_factory
        self._clock = clock

    async def state(
        self, provider: str, region: str
    ) -> ProviderCircuitState:
        return resolve_admission_health(await self.read(provider, region))

    async def read(
        self, provider: str, region: str
    ) -> ProviderHealthRecord | None:
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT provider, region, circuit_state,
                                   failure_window, drained, drained_at,
                                   drained_by
                              FROM coding_sandbox_provider_health
                             WHERE provider = :provider AND region = :region
                            """
                        ),
                        {"provider": provider, "region": region},
                    )
                ).one_or_none()
        return None if row is None else _record_from_row(row)

    async def observe(
        self, observation: ProviderObservation
    ) -> ProviderHealthSnapshot:
        """관측 한 건을 창에 반영하고 새 상태를 커밋한다.

        `FOR UPDATE` 로 행을 잠근 채 읽고 쓴다 -- 두 워커가 동시에 관측하면
        나중 쓰기가 앞 관측을 통째로 덮어써서 창이 실제보다 짧아지고, 짧은
        창은 `_failed_state()` 의 "창이 다 차야 판정한다" 규칙 때문에
        **장애를 영원히 판정하지 못한다.**

        드레인 컬럼은 건드리지 않는다. 정상 프로브 한 번이 운영자의 결정을
        지우면 안 된다(046 이 컬럼을 나눈 이유).
        """
        now = self._clock()
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT circuit_state, failure_window
                              FROM coding_sandbox_provider_health
                             WHERE provider = :provider AND region = :region
                               FOR UPDATE
                            """
                        ),
                        {
                            "provider": observation.provider,
                            "region": observation.region,
                        },
                    )
                ).one_or_none()
                circuit = self._circuit_factory()
                circuit.restore(
                    observation.provider,
                    observation.region,
                    failure_window=(
                        list(row.failure_window) if row is not None else []
                    ),
                    state=(
                        ProviderCircuitState(row.circuit_state)
                        if row is not None
                        else ProviderCircuitState.HEALTHY
                    ),
                )
                snapshot = circuit.observe(observation)
                window, state = circuit.export(
                    observation.provider, observation.region
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_sandbox_provider_health (
                            provider, region, circuit_state, failure_window,
                            drained, updated_at
                        ) VALUES (
                            :provider, :region, :circuit_state,
                            CAST(:failure_window AS BOOLEAN[]), FALSE, :now
                        )
                        ON CONFLICT (provider, region) DO UPDATE
                           SET circuit_state = EXCLUDED.circuit_state,
                               failure_window = EXCLUDED.failure_window,
                               version =
                                   coding_sandbox_provider_health.version + 1,
                               updated_at = EXCLUDED.updated_at
                        """
                    ),
                    {
                        "provider": observation.provider,
                        "region": observation.region,
                        "circuit_state": state.value,
                        "failure_window": list(window),
                        "now": now,
                    },
                )
        return snapshot

    async def set_drained(
        self,
        *,
        provider: str,
        region: str,
        drained: bool,
        operator_id: str | None = None,
    ) -> ProviderHealthRecord:
        """운영자 드레인을 **모든 프로세스가 보는 곳**에 쓴다 (CA11).

        서킷 상태와 창은 건드리지 않는다 -- 드레인은 관측이 아니라 결정이다.
        드레인을 풀면 서킷이 그동안 관측한 상태가 그대로 다시 보인다.
        """
        now = self._clock()
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            INSERT INTO coding_sandbox_provider_health (
                                provider, region, drained, drained_at,
                                drained_by, updated_at
                            ) VALUES (
                                :provider, :region, :drained, :drained_at,
                                :drained_by, :now
                            )
                            ON CONFLICT (provider, region) DO UPDATE
                               SET drained = EXCLUDED.drained,
                                   drained_at = EXCLUDED.drained_at,
                                   drained_by = EXCLUDED.drained_by,
                                   version =
                                       coding_sandbox_provider_health.version
                                       + 1,
                                   updated_at = EXCLUDED.updated_at
                         RETURNING provider, region, circuit_state,
                                   failure_window, drained, drained_at,
                                   drained_by
                            """
                        ),
                        {
                            "provider": provider,
                            "region": region,
                            "drained": drained,
                            # 046 의 CHECK 가 드레인 해제 시 두 값을 NULL 로
                            # 요구한다 -- 남겨 두면 "지금 드레인됐다"와
                            # "예전에 드레인된 적 있다"가 구별되지 않는다.
                            "drained_at": now if drained else None,
                            "drained_by": operator_id if drained else None,
                            "now": now,
                        },
                    )
                ).one()
        return _record_from_row(row)


def _record_from_row(row) -> ProviderHealthRecord:
    return ProviderHealthRecord(
        provider=str(row.provider),
        region=str(row.region),
        circuit_state=ProviderCircuitState(row.circuit_state),
        failure_window=tuple(row.failure_window or ()),
        drained=bool(row.drained),
        drained_at=row.drained_at,
        drained_by=row.drained_by,
    )


def create_provider_health_store(
    session_factory: SessionFactory,
    *,
    config,
    clock=None,
) -> PostgresProviderHealthStore:
    from datetime import UTC

    return PostgresProviderHealthStore(
        session_factory,
        circuit_factory=lambda: ProviderHealthCircuit.from_config(config),
        clock=clock or (lambda: datetime.now(UTC)),
    )
