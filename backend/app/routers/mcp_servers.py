import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.db import get_db
from app.engine.mcp_client import list_tools
from app.models.mcp_server import MCPServer
from app.schemas.mcp_server import MCPServerCreate, MCPServerOut, MCPServerUpdate

log = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


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
async def list_mcp_servers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MCPServer).order_by(MCPServer.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=MCPServerOut, status_code=201)
async def create_mcp_server(body: MCPServerCreate, db: AsyncSession = Depends(get_db)):
    server = MCPServer(
        **body.model_dump(),
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
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
async def get_mcp_server(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    server = await db.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


@router.patch("/{server_id}", response_model=MCPServerOut)
async def update_mcp_server(
    server_id: uuid.UUID, body: MCPServerUpdate, db: AsyncSession = Depends(get_db)
):
    server = await db.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(server, field, value)
    await db.flush()
    await db.refresh(server)
    return server


@router.get("/{server_id}/tools")
async def get_server_tools(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Return cached tool list. Use /refresh-tools to re-probe the server."""
    server = await db.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"tools": server.tools_json or []}


@router.post("/{server_id}/refresh-tools")
async def refresh_server_tools(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Re-probe the MCP server and update the cached tool list."""
    server = await db.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    tools = await _probe_tools(server)
    if tools is None:
        raise HTTPException(status_code=502, detail="Failed to probe MCP server")

    server.tools_json = tools
    await db.flush()
    await db.refresh(server)
    return {"tools": server.tools_json}


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    server = await db.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await db.delete(server)
