"""K25′ -- `ParentKind.WORKFLOW` 가 코드·메트릭·스키마 세 곳에 같이 도착했는가.

"고침은 한 호출부에만 도착한다": 열거형만 늘리면 메트릭은 새 부모를 `coding`
라벨로 섞고, DB 는 첫 INSERT 에서 CHECK 위반을 낸다.
"""

from pathlib import Path

import pytest

from neos.subagent.metrics import record_subagent_event
from neos.subagent.types import ParentKind

pytestmark = pytest.mark.no_db

_REPO = Path(__file__).resolve().parents[2]


def test_workflow_is_a_parent_kind() -> None:
    assert ParentKind.WORKFLOW == "workflow"
    assert {kind.value for kind in ParentKind} == {"coding", "deep_analysis", "workflow"}


class _Counter:
    def __init__(self) -> None:
        self.labels_seen: list[dict] = []

    def labels(self, **labels):
        self.labels_seen.append(labels)
        return self

    def inc(self, *_args) -> None:
        return None


class _Metrics:
    def __init__(self) -> None:
        self.subagent_cas_mismatch_total = _Counter()


def test_metrics_keep_the_workflow_label_instead_of_folding_it_into_coding() -> None:
    metrics = _Metrics()
    record_subagent_event(metrics, "subagent.cas_mismatch", {"parent_kind": "workflow"})
    assert metrics.subagent_cas_mismatch_total.labels_seen == [{"parent_kind": "workflow"}]


def test_the_migration_widens_the_parent_kind_check_to_every_enum_value() -> None:
    sql = (_REPO / "db/migrations/058_allow_workflow_subagent_parent.sql").read_text()
    assert "subagent_runs_parent_kind_check" in sql
    for kind in ParentKind:
        assert f"'{kind.value}'" in sql


def test_the_migration_is_in_the_canonical_bootstrap_order_after_055() -> None:
    # 순서는 BOOTSTRAP_ORDER.txt 의 규칙에서 유도된다 (2026-09-20) -- 본문 대신 유도 결과.
    from scripts.verify_schema_bootstrap import bootstrap_order

    lines = bootstrap_order()
    created = lines.index("db/migrations/055_add_subagent_tables.sql")
    widened = lines.index("db/migrations/058_allow_workflow_subagent_parent.sql")
    assert widened > created
