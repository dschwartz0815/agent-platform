import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Uuid

from app.db import Base


class Graph(Base):
    """
    A versioned graph definition. Each save bumps the version in-place (for demo).
    parent_graph_id tracks clone lineage.

    definition_json is a denormalized execution snapshot kept in sync with the
    graph_nodes / graph_edges rows on every save. The runner reads definition_json
    so it never needs to JOIN.
    """

    __tablename__ = "graphs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_graph_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("graphs.id"), nullable=True
    )

    # Ownership
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orgs.id"), nullable=False)

    # Denormalized execution definition — kept in sync by routers/graphs.py on every save
    definition_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    nodes: Mapped[list["GraphNode"]] = relationship(
        back_populates="graph", cascade="all, delete-orphan"
    )
    edges: Mapped[list["GraphEdge"]] = relationship(
        back_populates="graph", cascade="all, delete-orphan"
    )


class GraphNode(Base):
    """
    One node in the visual editor. node_key is the unique LangGraph node name within
    the graph (used in edges, must be stable across saves).

    node_type:
      'llm'      — direct Claude call (config: model, system_prompt)
      'agent'    — ReAct agent with MCP tools (config: model, system_prompt, mcp_server_ids)
      'mcp_tool' — call a single MCP tool (config: mcp_server_id, tool_name, arguments)
      'router'   — conditional routing (config: source_field, routes dict)

    ref_id is optional: points to an Agent or MCPServer row for context/display.
    """

    __tablename__ = "graph_nodes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    graph_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False
    )
    node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    # React Flow canvas position
    position_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    position_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Node-type-specific config
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    graph: Mapped["Graph"] = relationship(back_populates="nodes")


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    graph_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False
    )
    source_node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    target_node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Non-null only on conditional edges from a router node
    condition: Mapped[str | None] = mapped_column(String(128), nullable=True)

    graph: Mapped["Graph"] = relationship(back_populates="edges")
