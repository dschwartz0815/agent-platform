import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Uuid

from app.db import Base


class MCPServer(Base):
    """
    An MCP server is an external reference. The platform invokes it; it does not host it.

    transport='http':  url is the SSE endpoint (e.g. http://host/sse)
    transport='stdio': command + args + env_vars describe how to spawn the subprocess.
                       e.g. command='python', args=['/path/to/server.py']

    env_vars is a dict of additional env vars to inject when spawning (stdio only).
    Secrets should be stored externally and referenced by name — do not put raw secrets here.
    """

    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 'http' | 'stdio'
    transport: Mapped[str] = mapped_column(String(16), nullable=False)

    # HTTP transport
    url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # stdio transport
    command: Mapped[str | None] = mapped_column(String(512), nullable=True)
    args: Mapped[list | None] = mapped_column(JSON, nullable=True)   # e.g. ["server.py", "--port", "0"]
    env_vars: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # extra env for spawn

    # Cached tool list — populated on registration and refreshable via /refresh-tools
    tools_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Catalog — 'private' (workspace-only) | 'catalog' (discoverable by all workspaces)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Lineage: set when this row was installed from a catalog entry in another workspace
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    # Ownership
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orgs.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
