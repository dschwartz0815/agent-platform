import uuid
from datetime import datetime

from pydantic import BaseModel


class AgentBase(BaseModel):
    name: str
    description: str | None = None
    agent_type: str = "llm"
    model: str | None = None
    system_prompt: str | None = None
    url: str | None = None
    # A2A fields — callers can supply the card URL; the server fetches and validates it
    agent_card_url: str | None = None
    tags: list[str] | None = None


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    url: str | None = None
    agent_card_url: str | None = None
    tags: list[str] | None = None


class AgentOut(AgentBase):
    id: uuid.UUID
    agent_card_json: dict | None = None
    visibility: str = "private"
    tags: list[str] | None = None
    published_at: datetime | None = None
    source_id: uuid.UUID | None = None
    created_by: uuid.UUID
    org_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
