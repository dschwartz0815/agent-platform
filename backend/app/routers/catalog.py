"""
Cross-workspace catalog for agents and MCP servers.

A registry entry is private to its workspace until an admin publishes it
(visibility='catalog'). Published entries are *discoverable* by every
workspace; consuming one means installing it — copying it into your own
workspace with `source_id` lineage — so each tenant owns and can audit its
own copy. The publisher's workspace can later change or unpublish its entry
without affecting installs.

GET  /api/v1/catalog                          — all published entries (agents + MCP servers)
POST /api/v1/catalog/agents/{id}/install      — copy a published agent into the active workspace
POST /api/v1/catalog/mcp-servers/{id}/install — copy a published MCP server

Publishing lives on the registry routers (POST /agents/{id}/publish etc.).
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.agent import Agent
from app.models.mcp_server import MCPServer
from app.models.user import Org
from app.schemas.agent import AgentOut
from app.schemas.mcp_server import MCPServerOut
from app.schemas.workspace import CatalogEntryOut
from app.security.identity import WorkspaceContext, get_workspace_context, require_role

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("", response_model=list[CatalogEntryOut])
async def list_catalog(
    entry_type: str | None = Query(default=None, pattern="^(agent|mcp_server)$"),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    entries: list[CatalogEntryOut] = []

    if entry_type in (None, "agent"):
        result = await db.execute(
            select(Agent, Org)
            .join(Org, Agent.org_id == Org.id)
            .where(Agent.visibility == "catalog")
            .order_by(Agent.published_at.desc())
        )
        for agent, org in result.all():
            entries.append(CatalogEntryOut(
                id=agent.id,
                entry_type="agent",
                name=agent.name,
                description=agent.description,
                tags=agent.tags,
                published_at=agent.published_at,
                workspace_id=org.id,
                workspace_name=org.name,
                workspace_slug=org.slug,
                owned_by_caller_workspace=org.id == ctx.workspace.id,
                agent_type=agent.agent_type,
                model=agent.model,
            ))

    if entry_type in (None, "mcp_server"):
        result = await db.execute(
            select(MCPServer, Org)
            .join(Org, MCPServer.org_id == Org.id)
            .where(MCPServer.visibility == "catalog")
            .order_by(MCPServer.published_at.desc())
        )
        for server, org in result.all():
            entries.append(CatalogEntryOut(
                id=server.id,
                entry_type="mcp_server",
                name=server.name,
                description=server.description,
                tags=server.tags,
                published_at=server.published_at,
                workspace_id=org.id,
                workspace_name=org.name,
                workspace_slug=org.slug,
                owned_by_caller_workspace=org.id == ctx.workspace.id,
                transport=server.transport,
                tool_count=len(server.tools_json) if server.tools_json else 0,
            ))

    entries.sort(key=lambda e: e.published_at or datetime.min.replace(tzinfo=timezone.utc),
                 reverse=True)
    return entries


@router.post("/agents/{agent_id}/install", response_model=AgentOut, status_code=201)
async def install_agent(
    agent_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    require_role(ctx, "editor")
    source = await db.get(Agent, agent_id)
    if not source or source.visibility != "catalog":
        raise HTTPException(status_code=404, detail="Catalog entry not found")
    if source.org_id == ctx.workspace.id:
        raise HTTPException(
            status_code=422, detail="Entry already belongs to this workspace"
        )

    copy = Agent(
        name=source.name,
        description=source.description,
        agent_type=source.agent_type,
        model=source.model,
        system_prompt=source.system_prompt,
        url=source.url,
        agent_card_url=source.agent_card_url,
        agent_card_json=source.agent_card_json,
        tags=source.tags,
        visibility="private",
        source_id=source.id,
        created_by=ctx.user.id,
        org_id=ctx.workspace.id,
    )
    db.add(copy)
    await db.flush()
    await db.refresh(copy)
    return copy


@router.post(
    "/mcp-servers/{server_id}/install", response_model=MCPServerOut, status_code=201
)
async def install_mcp_server(
    server_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    require_role(ctx, "editor")
    source = await db.get(MCPServer, server_id)
    if not source or source.visibility != "catalog":
        raise HTTPException(status_code=404, detail="Catalog entry not found")
    if source.org_id == ctx.workspace.id:
        raise HTTPException(
            status_code=422, detail="Entry already belongs to this workspace"
        )

    copy = MCPServer(
        name=source.name,
        description=source.description,
        transport=source.transport,
        url=source.url,
        command=source.command,
        args=list(source.args) if source.args else None,
        env_vars=dict(source.env_vars) if source.env_vars else None,
        tools_json=source.tools_json,
        tags=source.tags,
        visibility="private",
        source_id=source.id,
        created_by=ctx.user.id,
        org_id=ctx.workspace.id,
    )
    db.add(copy)
    await db.flush()
    await db.refresh(copy)
    return copy
