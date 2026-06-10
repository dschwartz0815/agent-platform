import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.engine.persistence import run_graph
from app.models.agent import Agent
from app.models.graph import Graph, GraphVersion
from app.models.mcp_server import MCPServer
from app.schemas.execution import RunRequest
from app.security.identity import WorkspaceContext, get_workspace_context

router = APIRouter(prefix="/graphs", tags=["execution"])


@router.post("/{graph_id}/run")
async def run_graph_endpoint(
    graph_id: uuid.UUID,
    body: RunRequest,
    version: int | None = Query(default=None, description="Pin to a specific published version"),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream graph execution as Server-Sent Events with full run persistence.

    Events emitted:
      data: {"event": "run_started", "node": null, "data": {"run_id": "..."}}
      data: {"event": "node_start", "node": "classify", "data": null}
      data: {"event": "node_end", "node": "classify", "data": {...}}
      data: {"event": "done", "node": null, "data": {}}
      data: {"event": "error", "node": null, "data": "..."}

    Query params:
      - version: if provided, executes the pinned graph_version.definition_json
        and tags the run with graph_version_id. If omitted, runs the live draft
        and leaves graph_version_id null.
    """
    graph = await db.get(Graph, graph_id)
    if not graph or graph.org_id != ctx.workspace.id:
        raise HTTPException(status_code=404, detail="Graph not found")

    # Resolve which definition to execute
    graph_version_id: uuid.UUID | None = None
    definition: dict
    if version is not None:
        v_result = await db.execute(
            select(GraphVersion).where(
                GraphVersion.graph_id == graph_id,
                GraphVersion.version == version,
            )
        )
        gv = v_result.scalar_one_or_none()
        if not gv:
            raise HTTPException(status_code=404, detail=f"Version {version} not found")
        graph_version_id = gv.id
        definition = gv.definition_json
    else:
        definition = graph.definition_json

    if not definition or not definition.get("nodes"):
        raise HTTPException(status_code=422, detail="Graph has no definition")

    # Collect MCP server / agent refs from the definition
    mcp_server_ids: set[str] = set()
    agent_ids: set[str] = set()
    for node in definition.get("nodes", []):
        cfg = node.get("config") or {}
        if sid := cfg.get("mcp_server_id"):
            mcp_server_ids.add(str(sid))
        for sid in cfg.get("mcp_server_ids") or []:
            mcp_server_ids.add(str(sid))
        if aid := cfg.get("agent_id"):
            agent_ids.add(str(aid))

    # Refs resolve only within the graph's own workspace — a definition can
    # never borrow another tenant's MCP servers or agents.
    mcp_servers: dict[str, dict] = {}
    if mcp_server_ids:
        uuids = [uuid.UUID(s) for s in mcp_server_ids]
        result = await db.execute(
            select(MCPServer).where(
                MCPServer.id.in_(uuids), MCPServer.org_id == graph.org_id
            )
        )
        for srv in result.scalars().all():
            mcp_servers[str(srv.id)] = {
                "transport": srv.transport,
                "url": srv.url,
                "command": srv.command,
                "args": srv.args,
                "env_vars": srv.env_vars,
            }

    agents: dict[str, dict] = {}
    if agent_ids:
        uuids = [uuid.UUID(s) for s in agent_ids]
        result = await db.execute(
            select(Agent).where(Agent.id.in_(uuids), Agent.org_id == graph.org_id)
        )
        for ag in result.scalars().all():
            agents[str(ag.id)] = {
                "url": ag.url,
                "agent_type": ag.agent_type,
                "agent_card_json": ag.agent_card_json,
            }

    async def event_stream():
        async for event in run_graph(
            db=db,
            graph=graph,
            graph_version_id=graph_version_id,
            trigger_source="editor_test",
            run_input=body.input,
            mcp_servers=mcp_servers,
            agents=agents,
            definition=definition,
        ):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
