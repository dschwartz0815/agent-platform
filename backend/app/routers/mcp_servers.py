"""
MCP server registry — workspace-scoped CRUD + catalog publishing.

Same tenancy rules as the agent registry: reads filtered to the active
workspace, writes require 'editor', catalog publish/unpublish requires 'admin'.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.engine.mcp_client import list_tools
from app.models.graph import Graph
from app.models.mcp_server import MCPServer
from app.schemas.mcp_server import MCPServerCreate, MCPServerOut, MCPServerUpdate
from app.security.identity import WorkspaceContext, get_workspace_context, require_role

log = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


async def _load_server(
    server_id: uuid.UUID, ctx: WorkspaceContext, db: AsyncSession
) -> MCPServer:
    """Workspace-scoped fetch — rows in other workspaces surface as 404."""
    server = await db.get(MCPServer, server_id)
    if not server or server.org_id != ctx.workspace.id:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


async def _probe_tools(server: MCPServer) -> list | None:
    """Best-effort tool list fetch. Returns None on failure."""
    try:
        tools = await list_tools(
            transport=server.transport,
            url=server.url,
            command=server.command,
            args=server.args,
            env_vars=server.env_vars,
        )
        log.info(
            "mcp_tools_discovered",
            extra={"server_id": str(server.id), "tool_count": len(tools)},
        )
        return tools
    except Exception as exc:
        log.warning(
            "mcp_tool_discovery_failed",
            extra={"server_id": str(server.id), "error": str(exc)},
        )
        return None


@router.get("/", response_model=list[MCPServerOut])
async def list_mcp_servers(
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MCPServer)
        .where(MCPServer.org_id == ctx.workspace.id)
        .order_by(MCPServer.created_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=MCPServerOut, status_code=201)
async def create_mcp_server(
    body: MCPServerCreate,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    require_role(ctx, "editor")
    server = MCPServer(
        **body.model_dump(),
        created_by=ctx.user.id,
        org_id=ctx.workspace.id,
    )
    db.add(server)
    await db.flush()

    # Best-effort: discover and cache tools on registration
    tools = await _probe_tools(server)
    if tools is not None:
        server.tools_json = tools

    await db.flush()
    await db.refresh(server)
    return server


@router.get("/{server_id}", response_model=MCPServerOut)
async def get_mcp_server(
    server_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    return await _load_server(server_id, ctx, db)


@router.patch("/{server_id}", response_model=MCPServerOut)
async def update_mcp_server(
    server_id: uuid.UUID,
    body: MCPServerUpdate,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    require_role(ctx, "editor")
    server = await _load_server(server_id, ctx, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(server, field, value)
    await db.flush()
    await db.refresh(server)
    return server


@router.post("/{server_id}/publish", response_model=MCPServerOut)
async def publish_mcp_server(
    server_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    """Publish to the cross-workspace catalog (admin+)."""
    require_role(ctx, "admin")
    server = await _load_server(server_id, ctx, db)
    server.visibility = "catalog"
    server.published_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(server)
    return server


@router.post("/{server_id}/unpublish", response_model=MCPServerOut)
async def unpublish_mcp_server(
    server_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    """Remove from the catalog. Existing installs in other workspaces keep their copies."""
    require_role(ctx, "admin")
    server = await _load_server(server_id, ctx, db)
    server.visibility = "private"
    server.published_at = None
    await db.flush()
    await db.refresh(server)
    return server


@router.get("/{server_id}/tools")
async def get_server_tools(
    server_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    """Return cached tool list. Use /refresh-tools to re-probe the server."""
    server = await _load_server(server_id, ctx, db)
    return {"tools": server.tools_json or []}


@router.post("/{server_id}/refresh-tools")
async def refresh_server_tools(
    server_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    """Re-probe the MCP server and update the cached tool list."""
    require_role(ctx, "editor")
    server = await _load_server(server_id, ctx, db)

    tools = await _probe_tools(server)
    if tools is None:
        raise HTTPException(status_code=502, detail="Failed to probe MCP server")

    server.tools_json = tools
    await db.flush()
    await db.refresh(server)
    return {"tools": server.tools_json}


@router.get("/{server_id}/usages")
async def get_mcp_server_usages(
    server_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Return graphs in the active workspace that reference this MCP server.
    Checks both config.mcp_server_id (scalar — used by mcp_tool nodes) and
    config.mcp_server_ids (list — used by ReAct agent nodes).
    """
    await _load_server(server_id, ctx, db)
    result = await db.execute(select(Graph).where(Graph.org_id == ctx.workspace.id))
    target = str(server_id)
    usages: list[dict] = []
    for g in result.scalars().all():
        for node in (g.definition_json or {}).get("nodes", []):
            cfg = node.get("config") or {}
            matched = False
            if cfg.get("mcp_server_id") == target:
                matched = True
            else:
                ids = cfg.get("mcp_server_ids") or []
                if isinstance(ids, list) and target in ids:
                    matched = True
            if matched:
                usages.append({
                    "graph_id": str(g.id),
                    "graph_name": g.name,
                    "node_key": node.get("key"),
                })
    return usages


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    require_role(ctx, "editor")
    server = await _load_server(server_id, ctx, db)
    await db.delete(server)
