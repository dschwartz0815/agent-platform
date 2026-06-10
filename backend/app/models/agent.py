import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Uuid

from app.db import Base


class Agent(Base):
    """
    An agent is an external reference — something this platform knows about and can invoke,
    but does not host. It is either a direct LLM call (type='llm') or an HTTP endpoint
    that accepts LangGraph-compatible requests (type='http').

    For LLM agents, model + system_prompt are the full config.
    For HTTP agents, url is the endpoint.
    """

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 'llm' | 'http'
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False, default="llm")

    # LLM agent fields
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # HTTP agent fields
    url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # A2A agent card — fetched from /.well-known/agent.json on registration
    agent_card_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_card_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Catalog — 'private' (workspace-only) | 'catalog' (discoverable by all workspaces)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Lineage: set when this row was installed from a catalog entry in another workspace
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    # Ownership — present from day 1 so real auth never needs a migration
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orgs.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
