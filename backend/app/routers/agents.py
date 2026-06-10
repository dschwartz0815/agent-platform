"""
Agent registry — workspace-scoped CRUD + catalog publishing.

Every endpoint resolves the caller's active workspace from their AD-group
memberships (see security/identity.py). Reads are filtered to that workspace;
writes require the 'editor' role; catalog publish/unpublish requires 'admin'.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.card import try_fetch_agent_card
from app.db import get_db
from app.models.agent import Agent
from app.models.graph import Graph
from app.schemas.agent import AgentCreate, AgentOut, AgentUpdate
from app.security.identity import WorkspaceContext, get_workspace_context, require_role

log = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


async def _load_agent(
    agent_id: uuid.UUID, ctx: WorkspaceContext, db: AsyncSession
) -> Agent:
    """Workspace-scoped fetch — rows in other workspaces surface as 404."""
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != ctx.workspace.id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/", response_model=list[AgentOut])
async def list_agents(
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Agent)
        .where(Agent.org_id == ctx.workspace.id)
        .order_by(Agent.created_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=AgentOut, status_code=201)
async def create_agent(
    body: AgentCreate,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    require_role(ctx, "editor")
    agent = Agent(
        **body.model_dump(),
        created_by=ctx.user.id,
        org_id=ctx.workspace.id,
    )
    db.add(agent)
    await db.flush()

    # Best-effort: fetch agent card for HTTP agents that have a URL
    if agent.agent_type == "http" and agent.url:
        card_url = agent.agent_card_url or agent.url
        card = await try_fetch_agent_card(card_url)
        if card:
            agent.agent_card_json = card
            if not agent.agent_card_url:
                agent.agent_card_url = card_url

    await db.flush()
    await db.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    return await _load_agent(agent_id, ctx, db)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    require_role(ctx, "editor")
    agent = await _load_agent(agent_id, ctx, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await db.flush()
    await db.refresh(agent)
    return agent


@router.post("/{agent_id}/publish", response_model=AgentOut)
async def publish_agent(
    agent_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    """Publish to the cross-workspace catalog (admin+)."""
    require_role(ctx, "admin")
    agent = await _load_agent(agent_id, ctx, db)
    agent.visibility = "catalog"
    agent.published_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(agent)
    return agent


@router.post("/{agent_id}/unpublish", response_model=AgentOut)
async def unpublish_agent(
    agent_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    """Remove from the catalog. Existing installs in other workspaces keep their copies."""
    require_role(ctx, "admin")
    agent = await _load_agent(agent_id, ctx, db)
    agent.visibility = "private"
    agent.published_at = None
    await db.flush()
    await db.refresh(agent)
    return agent


@router.post("/{agent_id}/refresh-card", response_model=AgentOut)
async def refresh_agent_card(
    agent_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    """Re-fetch and cache the A2A agent card from /.well-known/agent.json."""
    require_role(ctx, "editor")
    agent = await _load_agent(agent_id, ctx, db)
    if not agent.url:
        raise HTTPException(status_code=422, detail="Agent has no URL to fetch card from")

    card_url = agent.agent_card_url or agent.url
    card = await try_fetch_agent_card(card_url)
    if not card:
        raise HTTPException(status_code=502, detail="Failed to fetch agent card")

    agent.agent_card_json = card
    agent.agent_card_url = card_url
    await db.flush()
    await db.refresh(agent)
    return agent


@router.get("/{agent_id}/usages")
async def get_agent_usages(
    agent_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Return graphs in the active workspace that reference this agent by UUID.
    Scans Graph.definition_json — the denormalized snapshot the runner uses.
    Used by the UI to warn before deletion.
    """
    await _load_agent(agent_id, ctx, db)
    result = await db.execute(select(Graph).where(Graph.org_id == ctx.workspace.id))
    target = str(agent_id)
    usages: list[dict] = []
    for g in result.scalars().all():
        for node in (g.definition_json or {}).get("nodes", []):
            cfg = node.get("config") or {}
            if cfg.get("agent_id") == target:
                usages.append({
                    "graph_id": str(g.id),
                    "graph_name": g.name,
                    "node_key": node.get("key"),
                })
    return usages


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    require_role(ctx, "editor")
    agent = await _load_agent(agent_id, ctx, db)
    await db.delete(agent)
