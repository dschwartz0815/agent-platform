import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator


class MCPServerBase(BaseModel):
    name: str
    description: str | None = None
    transport: str  # 'http' | 'stdio'
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env_vars: dict[str, str] | None = None
    tags: list[str] | None = None

    @model_validator(mode="after")
    def check_transport_fields(self):
        if self.transport == "http" and not self.url:
            raise ValueError("url is required for HTTP transport")
        if self.transport == "stdio" and not self.command:
            raise ValueError("command is required for stdio transport")
        return self


class MCPServerCreate(MCPServerBase):
    pass


class MCPServerUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env_vars: dict[str, str] | None = None
    tags: list[str] | None = None


class MCPServerOut(MCPServerBase):
    id: uuid.UUID
    tools_json: list | None = None
    visibility: str = "private"
    published_at: datetime | None = None
    source_id: uuid.UUID | None = None
    created_by: uuid.UUID
    org_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
