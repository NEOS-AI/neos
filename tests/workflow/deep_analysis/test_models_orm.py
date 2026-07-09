import pytest
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from neos.database.deep_analysis_models import (
    DABlob,
    DAClaim,
    DAEvidence,
    DAEvent,
    DAFeedback,
    DAQuestion,
    DARun,
)


pytestmark = pytest.mark.no_db


def test_orm_tablenames_match_migration():
    assert DARun.__tablename__ == "deep_analysis_runs"
    assert DAQuestion.__tablename__ == "deep_analysis_questions"
    assert DAClaim.__tablename__ == "deep_analysis_claims"
    assert DABlob.__tablename__ == "deep_analysis_blobs"
    assert DAEvidence.__tablename__ == "deep_analysis_evidence"
    assert DAFeedback.__tablename__ == "deep_analysis_feedback"
    assert DAEvent.__tablename__ == "deep_analysis_events"


def test_claim_columns_and_run_scoped_hash_uniqueness():
    columns = {column.name for column in DAClaim.__table__.columns}
    constraints = DAClaim.__table__.constraints

    assert {
        "id",
        "run_id",
        "question_id",
        "text",
        "hash",
        "status",
        "confidence",
    } <= columns
    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns} == {"run_id", "hash"}
        for constraint in constraints
    )


def test_evidence_has_run_scoped_claim_and_blob_foreign_keys():
    foreign_keys = [
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in DAEvidence.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]

    assert (
        "deep_analysis_claims.run_id",
        "deep_analysis_claims.id",
    ) in foreign_keys
    assert (
        "deep_analysis_blobs.run_id",
        "deep_analysis_blobs.content_hash",
    ) in foreign_keys
