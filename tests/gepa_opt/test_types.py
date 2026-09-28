"""PR1 types: candidates, engine config, proposer view, overlay status."""

from __future__ import annotations

import pytest

from neos.gepa_opt.types import (
    EngineConfig,
    ProposerView,
    validate_candidate,
    validate_overlay_status,
)


pytestmark = pytest.mark.no_db


def test_non_string_component_rejected():
    with pytest.raises(TypeError):
        validate_candidate({"system": 1})
    with pytest.raises(TypeError):
        validate_candidate({"system": None})
    assert validate_candidate({"system": "keep"}) == {"system": "keep"}


def test_merge_cannot_be_true():
    with pytest.raises(ValueError):
        EngineConfig(engine_label="gepa", pareto=True, merge=True)
    config = EngineConfig(engine_label="gepa", pareto=True)
    assert config.merge is False


def test_gepa_requires_pareto_true():
    with pytest.raises(ValueError):
        EngineConfig(engine_label="gepa", pareto=False)
    config = EngineConfig(engine_label="gepa", pareto=True)
    assert config.pareto is True
    assert config.component_cursor == 0


def test_not_gepa_requires_pareto_false():
    with pytest.raises(ValueError):
        EngineConfig(engine_label="not-gepa", pareto=True)
    config = EngineConfig(engine_label="not-gepa", pareto=False)
    assert config.pareto is False


def test_proposer_view_exposes_train_and_val_and_has_no_test():
    annotations = ProposerView.__annotations__
    assert "train" in annotations
    assert "val" in annotations
    assert "test" not in annotations
    names = dir(ProposerView)
    assert "train" in names
    assert "val" in names
    assert "test" not in names
    view = ProposerView(train=({"id": "a"},), val=({"id": "b"},))
    assert view.train[0]["id"] == "a"
    assert view.val[0]["id"] == "b"
    assert not hasattr(view, "test")


def test_overlay_status_only_staged_approved_archived():
    assert validate_overlay_status("staged") == "staged"
    assert validate_overlay_status("approved") == "approved"
    assert validate_overlay_status("archived") == "archived"
    for status in ("rejected", "queued", "STAGED", "", "approved "):
        with pytest.raises(ValueError):
            validate_overlay_status(status)
