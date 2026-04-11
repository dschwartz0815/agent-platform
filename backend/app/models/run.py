"""
Run + RunStep ORM models.

A Run is one graph execution — editor test, sync API, streaming API, or async job.
Each Run has a sequence of RunStep rows, one per node executed, used to render
the waterfall detail view in the UI.

graph_version_id is nullable: draft runs (editor tests against the live canvas)
point at no version. Published-version runs reference the exact immutable snapshot
that was executed.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    graph_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False
    )
    graph_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("graph_versions.id", ondelete="SET NULL"), nullable=True
    )

    # 'editor_test' | 'api_sync' | 'api_stream' | 'api_async'
    trigger_source: Mapped[str] = mapped_column(String(32), nullable=False)
    # 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    input_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    steps: Mapped[list["RunStep"]] = relationship(
        "RunStep",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunStep.step_order",
    )


class RunStep(Base):
    __tablename__ = "run_steps"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 'running' | 'succeeded' | 'failed' | 'skipped'
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)

    run: Mapped["Run"] = relationship("Run", back_populates="steps")
