"""Minimum OpenAI-like and task contracts for the first UI integration spike."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=200)
    stream: bool = False


class TaskCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)


class TaskView(BaseModel):
    id: str
    state: Literal[
        "QUEUED", "RUNNING", "WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"
    ]
    prompt: str
    created_at: datetime
    updated_at: datetime
