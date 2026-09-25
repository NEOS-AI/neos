"""ParentKind.UNIVER must land as enum + metrics + DB CHECK together."""

from pathlib import Path

import pytest

from neos.subagent.metrics import record_subagent_event
from neos.subagent.types import ParentKind

pytestmark = pytest.mark.no_db

_REPO = Path(__file__).resolve().parents[2]


def test_univer_is_a_parent_kind() -> None:
    assert ParentKind.UNIVER == "univer"
    assert {kind.value for kind in ParentKind} == {
        "coding",
        "deep_analysis",
        "workflow",
        "fsi",
        "univer",
    }


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


def test_metrics_keep_the_univer_label_instead_of_folding_it_into_coding() -> None:
    metrics = _Metrics()
    record_subagent_event(metrics, "subagent.cas_mismatch", {"parent_kind": "univer"})
    assert metrics.subagent_cas_mismatch_total.labels_seen == [{"parent_kind": "univer"}]


def test_the_migration_widens_the_parent_kind_check_to_every_enum_value() -> None:
    sql = (_REPO / "db/migrations/065_allow_univer_subagent_parent.sql").read_text()
    assert "subagent_runs_parent_kind_check" in sql
    for kind in ParentKind:
        assert f"'{kind.value}'" in sql


def test_the_migration_is_in_the_canonical_bootstrap_order_after_064() -> None:
    from scripts.verify_schema_bootstrap import bootstrap_order

    lines = bootstrap_order()
    created = lines.index("db/migrations/055_add_subagent_tables.sql")
    fsi = lines.index("db/migrations/064_allow_fsi_subagent_parent.sql")
    univer = lines.index("db/migrations/065_allow_univer_subagent_parent.sql")
    assert fsi > created
    assert univer > fsi
