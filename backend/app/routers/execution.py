import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.engine.runner import stream_graph
from app.models.agent import Agent
from app.models.graph import Graph
from app.models.mcp_server import MCPServer
from app.schemas.execution import RunRequest

router = APIRouter(prefix="/graphs", tags=["execution"])


@router.post("/{graph_id}/run")
async def run_graph(
    graph_id: uuid.UUID,
    body: RunRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Stream graph execution as Server-Sent Events.

    Each event is a JSON line:
      data: {"event": "node_start", "node": "classify", "data": null}
      data: {"event": "token", "node": "classify", "data": "The risk is..."}
      data: {"event": "node_end", "node": "classify", "data": {"context": {...}}}
      data: {"event": "done", "node": null, "data": {}}
      data: {"event": "error", "node": null, "data": "...message..."}
    """
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    definition = graph.definition_json
    if not definition:
        raise HTTPException(status_code=422, detail="Graph has no definition")

    # Collect MCP server IDs referenced by any node
    mcp_server_ids: set[str] = set()
    agent_ids: set[str] = set()

    for node in definition.get("nodes", []):
        cfg = node.get("config", {})
        if sid := cfg.get("mcp_server_id"):
            mcp_server_ids.add(str(sid))
        for sid in cfg.get("mcp_server_ids", []):
            mcp_server_ids.add(str(sid))
        if aid := cfg.get("agent_id"):
            agent_ids.add(str(aid))

    # Load MCP servers
    mcp_servers: dict[str, dict] = {}
    if mcp_server_ids:
        uuids = [uuid.UUID(s) for s in mcp_server_ids]
        result = await db.execute(
            select(MCPServer).where(MCPServer.id.in_(uuids))
        )
        for srv in result.scalars().all():
            mcp_servers[str(srv.id)] = {
                "transport": srv.transport,
                "url": srv.url,
                "command": srv.command,
                "args": srv.args,
                "env_vars": srv.env_vars,
            }

    # Load A2A agents
    agents: dict[str, dict] = {}
    if agent_ids:
        uuids = [uuid.UUID(s) for s in agent_ids]
        result = await db.execute(
            select(Agent).where(Agent.id.in_(uuids))
        )
        for ag in result.scalars().all():
            agents[str(ag.id)] = {
                "url": ag.url,
                "agent_type": ag.agent_type,
                "agent_card_json": ag.agent_card_json,
            }

    async def event_stream():
        async for event in stream_graph(definition, mcp_servers, body.input, agents):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
