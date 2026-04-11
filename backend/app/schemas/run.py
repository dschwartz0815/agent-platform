"""Pydantic schemas for Run, RunStep, and test examples."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class RunStepOut(BaseModel):
    id: uuid.UUID
    node_key: str
    node_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    input_snapshot: dict | None = None
    output_snapshot: dict | None = None
    token_usage: dict | None = None
    error_message: str | None = None
    step_order: int

    model_config = {"from_attributes": True}


class RunSummary(BaseModel):
    """Lightweight listing — no snapshots or step details."""
    id: uuid.UUID
    graph_id: uuid.UUID
    graph_version_id: uuid.UUID | None = None
    trigger_source: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    token_usage: dict | None = None
    error_message: str | None = None
    input_preview: str  # first 60 chars of json.dumps(input_json)

    model_config = {"from_attributes": True}


class RunOut(BaseModel):
    """Full run detail including steps."""
    id: uuid.UUID
    graph_id: uuid.UUID
    graph_version_id: uuid.UUID | None = None
    trigger_source: str
    status: str
    input_json: dict
    output_json: dict | None = None
    error_message: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    token_usage: dict | None = None
    steps: list[RunStepOut] = []

    model_config = {"from_attributes": True}


class ExampleCreate(BaseModel):
    """Body for POST /graphs/{id}/examples."""
    name: str
    input: dict
    output: dict | None = None


class ExampleOut(BaseModel):
    """One saved test example, stored in graphs.test_examples jsonb."""
    id: str  # uuid as string
    name: str
    input: dict
    output: dict | None = None
    created_at: str  # ISO-8601 string
