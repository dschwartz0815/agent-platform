import uuid
from typing import Any

from pydantic import BaseModel


class RunRequest(BaseModel):
    input: dict[str, Any]  # arbitrary user-provided input payload


class RunEvent(BaseModel):
    """Shape of each SSE data payload."""

    event: str  # 'token' | 'node_start' | 'node_end' | 'done' | 'error'
    node: str | None = None
    data: Any = None
