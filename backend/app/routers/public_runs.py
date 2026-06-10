"""
Public run endpoints at /v1/run/{org}/{slug}.

Separate from /api/v1/* (management) so the public surface can evolve its own
versioning without breaking the management API.

Modes:
  - Default: sync — buffers SSE stream, returns {run_id, status, output} JSON
  - ?mode=stream: SSE passthrough — same event shape as the editor test endpoint

Version pinning: the slug path parameter accepts either "my-slug" or
"my-slug@v3". The @vN suffix is parsed out before graph lookup.

Auth: Authorization: Bearer ap_live_... handled by authenticate_api_key dep.
Scope: check_graph_scope raises 404 when the key lacks access.

Input validation: body.input is validated against graph.input_schema via
jsonschema. 422 on mismatch with {"error": "/path: reason"}.
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.engine.persistence import run_graph
from app.models.agent import Agent
from app.models.api_key import ApiKey
from app.models.graph import Graph, GraphVersion
from app.models.mcp_server import MCPServer
from app.models.user import Org
from app.schemas.execution import RunRequest
from app.security.auth import authenticate_api_key, check_graph_scope
from app.services.schema_validation import SchemaValidationError, validate_against_schema

router = APIRouter(prefix="/v1/run", tags=["public-runs"])


def _parse_slug_with_version(raw: str) -> tuple[str, int | None]:
    """
    Split 'my-slug@v3' into ('my-slug', 3). If no @vN suffix, version is None.
    """
    if "@v" in raw:
        base, _, v_str = raw.rpartition("@v")
        try:
            return base, int(v_str)
        except ValueError:
            return raw, None
    return raw, None


async def _load_definition(
    db: AsyncSession,
    graph: Graph,
    version: int | None,
) -> tuple[dict, uuid.UUID | None]:
    """Resolve the definition to execute, returning (definition, version_id | None)."""
    if version is None:
        return graph.definition_json, None
    v_result = await db.execute(
        select(GraphVersion).where(
            GraphVersion.graph_id == graph.id,
            GraphVersion.version == version,
        )
    )
    gv = v_result.scalar_one_or_none()
    if not gv:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")
    return gv.definition_json, gv.id


async def _collect_refs(
    db: AsyncSession, definition: dict, org_id: uuid.UUID
) -> tuple[dict, dict]:
    """Load MCP server + agent rows referenced in the definition.
    Refs resolve only within the owning workspace — definitions can never
    borrow another tenant's MCP servers or agents."""
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

    mcp_servers: dict[str, dict] = {}
    if mcp_server_ids:
        uuids = [uuid.UUID(s) for s in mcp_server_ids]
        result = await db.execute(
            select(MCPServer).where(MCPServer.id.in_(uuids), MCPServer.org_id == org_id)
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
            select(Agent).where(Agent.id.in_(uuids), Agent.org_id == org_id)
        )
        for ag in result.scalars().all():
            agents[str(ag.id)] = {
                "url": ag.url,
                "agent_type": ag.agent_type,
                "agent_card_json": ag.agent_card_json,
            }
    return mcp_servers, agents


@router.post("/{org_slug}/{graph_slug}")
async def public_run(
    org_slug: str,
    graph_slug: str,
    body: RunRequest,
    mode: str = Query(default="sync", pattern="^(sync|stream)$"),
    api_key: ApiKey = Depends(authenticate_api_key),
    db: AsyncSession = Depends(get_db),
):
    # 1. Parse optional @vN suffix from the slug
    slug, version = _parse_slug_with_version(graph_slug)

    # 2. Resolve the org
    org_result = await db.execute(select(Org).where(Org.slug == org_slug))
    org = org_result.scalar_one_or_none()
    if not org or org.id != api_key.org_id:
        raise HTTPException(status_code=404, detail="Graph not found")

    # 3. Resolve the graph
    graph_result = await db.execute(
        select(Graph).where(Graph.org_id == org.id, Graph.slug == slug)
    )
    graph = graph_result.scalar_one_or_none()
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    # 4. Scope check — raises 404 on mismatch to avoid enumeration
    check_graph_scope(api_key, graph.id)

    # 5. Input validation against input_schema (if present)
    try:
        validate_against_schema(body.input, graph.input_schema)
    except SchemaValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message)

    # 6. Load pinned version if @vN was given
    definition, graph_version_id = await _load_definition(db, graph, version)
    if not definition or not definition.get("nodes"):
        raise HTTPException(status_code=422, detail="Graph has no definition")

    # 7. Collect referenced agents / mcp servers
    mcp_servers, agents = await _collect_refs(db, definition, org.id)

    trigger_source = "api_stream" if mode == "stream" else "api_sync"

    if mode == "stream":
        async def event_stream():
            async for event in run_graph(
                db=db,
                graph=graph,
                graph_version_id=graph_version_id,
                trigger_source=trigger_source,
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

    # Sync mode: consume the generator fully, buffer the final output
    run_id: str | None = None
    final_output: dict | None = None
    final_error: str | None = None
    async for event in run_graph(
        db=db,
        graph=graph,
        graph_version_id=graph_version_id,
        trigger_source=trigger_source,
        run_input=body.input,
        mcp_servers=mcp_servers,
        agents=agents,
        definition=definition,
    ):
        kind = event.get("event")
        if kind == "run_started":
            run_id = event.get("data", {}).get("run_id")
        elif kind == "node_end":
            data = event.get("data") or {}
            if isinstance(data, dict):
                final_output = {k: v for k, v in data.items() if k != "last_usage"}
        elif kind == "error":
            final_error = str(event.get("data") or "Unknown error")

    if final_error:
        return {
            "run_id": run_id,
            "status": "failed",
            "error": final_error,
        }
    return {
        "run_id": run_id,
        "status": "succeeded",
        "output": final_output,
    }
