from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def identity() -> str:
    return uuid4().hex


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "request", "status", "complete", "confirm", "pause", "resume", "cancel", "clarify", "backchannel"
    ]
    query: str | None = Field(default=None, max_length=120)
    quantity: int | None = Field(default=None, strict=True, ge=1, le=1000)
    explicit: bool = False


class Item(BaseModel):
    sku: str
    name: str
    aliases: list[str]
    attributes: dict[str, str]
    bin: str
    available: int
    inventory_version: int = 1


class PickTask(BaseModel):
    task_id: str = Field(default_factory=identity)
    task_version: int = 1
    operation_id: str = Field(default_factory=identity)
    item: Item
    quantity: int = Field(ge=1, le=1000)
    status: Literal["requested", "looking_up", "ready", "awaiting_confirmation", "committed", "cancelled"] = (
        "requested"
    )


class Speech(BaseModel):
    response_id: str = Field(default_factory=identity)
    response_epoch: int
    task_version: int | None = None
    task_id: str | None = None
    text: str
    status: Literal["generated", "queued", "playing", "interrupted", "completed"] = "generated"
    substantive: bool = True
    allow_while_paused: bool = False
    delivered_estimate: str = "none"


class Confirmation(BaseModel):
    confirmation_id: str = Field(default_factory=identity)
    task_id: str
    task_version: int
    sku: str
    quantity: int
    response_id: str
    delivered: bool = False
    expires_at: float = 0


class Faults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lookup_delay_ms: int = Field(default=0, ge=0, le=10000)
    ignore_cancellation: bool = False
    fail_provider: Literal["lookup", "rime", "stt", "llm"] | None = None


class Session(BaseModel):
    session_id: str = Field(default_factory=identity)
    room: str = ""
    mode: Literal["fixture", "live"]
    owner_hash: str
    ended: bool = False
    paused: bool = False
    resolving: bool = False
    response_epoch: int = 0
    input_id: str | None = None
    worker_epoch: int = 0
    worker_id: str | None = None
    task: PickTask | None = None
    speech: Speech | None = None
    confirmation: Confirmation | None = None
    provider: dict = Field(default_factory=dict)
    faults: Faults = Field(default_factory=Faults)
    tool_states: dict[str, dict] = Field(default_factory=dict)
