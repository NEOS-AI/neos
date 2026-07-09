"""SQLAlchemy models for the Deep Analysis Harness ledger."""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    REAL,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
)

from .connection import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DARun(Base):
    __tablename__ = "deep_analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "profile IN ('dev', 'default')",
            name="ck_deep_analysis_runs_profile",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_deep_analysis_runs_status",
        ),
    )

    id = Column(String(8), primary_key=True)
    root_question = Column(Text, nullable=False)
    profile = Column(String(20), nullable=False, default="default")
    status = Column(String(20), nullable=False, default="running")
    user_id = Column(
        String(255),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    # conversations is managed by the legacy raw-SQL chat repository and is
    # not present in Base.metadata. Migration 036 owns the database-level FK.
    conversation_id = Column(String(255), nullable=True)
    assistant_message_id = Column(String(255), nullable=True)
    report_path = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_now)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )


class DAQuestion(Base):
    __tablename__ = "deep_analysis_questions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "parent_id"],
            ["deep_analysis_questions.run_id", "deep_analysis_questions.id"],
        ),
        CheckConstraint(
            "status IN ('open', 'investigating', 'resolved', 'split', 'abandoned')",
            name="ck_deep_analysis_questions_status",
        ),
    )

    id = Column(String(8), primary_key=True)
    run_id = Column(
        String(8),
        ForeignKey("deep_analysis_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    parent_id = Column(String(8), nullable=True)
    text = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="open")
    depth = Column(Integer, nullable=False)
    value_est = Column(REAL, nullable=False)
    confidence = Column(REAL, nullable=False, default=0)
    spent_tokens = Column(Integer, nullable=False, default=0)
    cap_tokens = Column(Integer, nullable=False)
    fail_streak = Column(Integer, nullable=False, default=0)


class DAClaim(Base):
    __tablename__ = "deep_analysis_claims"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "hash",
            name="uq_deep_analysis_claims_run_hash",
        ),
        ForeignKeyConstraint(
            ["run_id", "question_id"],
            ["deep_analysis_questions.run_id", "deep_analysis_questions.id"],
        ),
        CheckConstraint(
            "status IN ('pending', 'verified', 'rejected', 'unverified')",
            name="ck_deep_analysis_claims_status",
        ),
    )

    id = Column(String(8), primary_key=True)
    run_id = Column(
        String(8),
        ForeignKey("deep_analysis_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    question_id = Column(String(8), nullable=False)
    text = Column(Text, nullable=False)
    hash = Column(String(16), nullable=False)
    status = Column(String(12), nullable=False, default="pending")
    confidence = Column(REAL, nullable=False)


class DABlob(Base):
    __tablename__ = "deep_analysis_blobs"

    run_id = Column(
        String(8),
        ForeignKey("deep_analysis_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    content_hash = Column(String(16), primary_key=True)
    url = Column(Text, nullable=False)
    http_status = Column(Integer, nullable=False)
    fetched_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_now)
    raw_text = Column(Text, nullable=True)


class DAEvidence(Base):
    __tablename__ = "deep_analysis_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "claim_id"],
            ["deep_analysis_claims.run_id", "deep_analysis_claims.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "raw_ref"],
            ["deep_analysis_blobs.run_id", "deep_analysis_blobs.content_hash"],
        ),
    )

    id = Column(String(8), primary_key=True)
    run_id = Column(
        String(8),
        ForeignKey("deep_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_id = Column(String(8), nullable=False)
    source_url = Column(Text, nullable=False)
    excerpt = Column(Text, nullable=False)
    raw_ref = Column(String(16), nullable=False)
    det_grade = Column(String(40), nullable=True)
    agent_grade = Column(String(20), nullable=True)


class DAFeedback(Base):
    __tablename__ = "deep_analysis_feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "claim_id"],
            ["deep_analysis_claims.run_id", "deep_analysis_claims.id"],
            ondelete="CASCADE",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(
        String(8),
        ForeignKey("deep_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_id = Column(String(8), nullable=False)
    code = Column(String(40), nullable=False)
    detail = Column(Text, nullable=False)
    salvage = Column(Text, nullable=True)
    attempt = Column(Integer, nullable=False)
    resolved = Column(Integer, nullable=False, default=0)


class DAEvent(Base):
    __tablename__ = "deep_analysis_events"

    seq = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(
        String(8),
        ForeignKey("deep_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    ts = Column(TIMESTAMP(timezone=True), nullable=False, default=_now)
    kind = Column(String(40), nullable=False)
    qid = Column(String(8), nullable=True)
    payload = Column(Text, nullable=False, default="{}")


__all__ = [
    "DARun",
    "DAQuestion",
    "DAClaim",
    "DABlob",
    "DAEvidence",
    "DAFeedback",
    "DAEvent",
]
