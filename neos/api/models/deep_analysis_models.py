"""Pydantic contracts for the Deep Analysis Harness API."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DeepAnalysisRequest(BaseModel):
    question: str = Field(min_length=1)
    conversation_id: str | None = None
    profile: Literal["dev", "default"] = "dev"

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped


class DeepAnalysisJobResponse(BaseModel):
    """202 제출 응답. 실행자가 무엇이든 계약은 동일하다."""

    run_id: str
    status: str = "accepted"
    executor: str
    events_url: str

