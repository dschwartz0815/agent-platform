import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.card import try_fetch_agent_card
from app.config import DEV_ORG_ID, DEV_USER_ID
from app.db import get_db
from app.models.agent import Agent
from app.models.graph import Graph
from app.schemas.agent import AgentCreate, AgentOut, AgentUpdate

log = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


def _current_user_id() -> uuid.UUID:
    return DEV_USER_ID


def _current_org_id() -> uuid.UUID:
    return DEV_ORG_ID


@router.get("/", response_model=list[AgentOut])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent).order_by(Agent.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=AgentOut, status_code=201)
async def create_agent(body: AgentCreate, db: AsyncSession = Depends(get_db)):
    agent = Agent(
        **body.model_dump(),
        created_by=_current_user_id(),
        org_id=_current_org_id(),
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
async def get_agent(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID, body: AgentUpdate, db: AsyncSession = Depends(get_db)
):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await db.flush()
    await db.refresh(agent)
    return agent


@router.post("/{agent_id}/refresh-card", response_model=AgentOut)
async def refresh_agent_card(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Re-fetch and cache the A2A agent card from /.well-known/agent.json."""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
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
async def get_agent_usages(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Return a list of graphs that reference this agent by UUID in their node config.
    Scans Graph.definition_json — the denormalized snapshot the runner uses.
    Used by the UI to warn before deletion.
    """
    result = await db.execute(select(Graph))
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
async def delete_agent(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.delete(agent)
