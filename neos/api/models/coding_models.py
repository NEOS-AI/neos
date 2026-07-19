from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CreateCodingTaskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)


class CodingTaskResponse(BaseModel):
    task_id: str
    status: str
    version: int
    last_seq: int
    created_at: datetime
    updated_at: datetime


class CodingEventResponse(BaseModel):
    v: int
    task_id: str
    seq: int
    event_id: str
    type: str
    ts: datetime
    payload: dict[str, Any]
    run_id: str | None = None
    turn_id: str | None = None
    tool_call_id: str | None = None
    checkpoint_id: str | None = None


class CodingEventListResponse(BaseModel):
    head_seq: int
    events: list[CodingEventResponse]


class CodingTaskSnapshotResponse(BaseModel):
    task: CodingTaskResponse
    head_seq: int
