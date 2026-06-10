"""Pydantic schemas for identity, workspaces, group mappings, and the catalog."""

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from app.models.user import ROLES


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    created_at: datetime
    # Caller's effective role in this workspace (derived from AD groups)
    role: str


class WorkspaceCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None
    # AD group granted the 'owner' role. Must be one of the caller's own
    # groups — otherwise they would create a workspace they can't access.
    owner_group: str

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or not all(c.isalnum() or c == "-" for c in v):
            raise ValueError("slug must be lowercase alphanumeric with hyphens")
        return v


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class GroupMappingOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    ad_group: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class GroupMappingCreate(BaseModel):
    ad_group: str
    role: str

    @field_validator("ad_group")
    @classmethod
    def group_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("ad_group must not be empty")
        return v

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}")
        return v


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    ad_groups: list[str]
    workspaces: list[WorkspaceOut]


class CatalogEntryOut(BaseModel):
    """A catalog listing — an agent or MCP server published by some workspace."""

    id: uuid.UUID
    entry_type: str  # 'agent' | 'mcp_server'
    name: str
    description: str | None = None
    tags: list[str] | None = None
    published_at: datetime | None = None
    # Where it lives
    workspace_id: uuid.UUID
    workspace_name: str
    workspace_slug: str
    owned_by_caller_workspace: bool
    # Type-specific summary fields
    agent_type: str | None = None
    model: str | None = None
    transport: str | None = None
    tool_count: int | None = None
