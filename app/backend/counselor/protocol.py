"""Request payloads used by the authenticated voice bridge."""

from typing import Literal

from pydantic import BaseModel, Field


class Playback(BaseModel):
    response_id: str = Field(max_length=100)
    status: Literal["playing", "completed", "interrupted"]


class Provider(BaseModel):
    name: Literal["rime"] = "rime"
    status: Literal["connected", "active", "failed", "disconnected"]
    model: str | None = None
    speaker: str | None = None
    language: str | None = None
    endpoint: str | None = None
    error_category: str | None = None


class ProviderError(BaseModel):
    provider: Literal["stt", "llm", "rime"]
    category: str = Field(max_length=100)


class WorkerClaim(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)
