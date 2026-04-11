import uuid
from datetime import datetime

from pydantic import BaseModel


class GraphNodeSchema(BaseModel):
    """Wire format for a single node — used in both save and read."""

    id: uuid.UUID | None = None  # omit on create; backend assigns
    node_key: str
    node_type: str  # 'llm' | 'agent' | 'mcp_tool' | 'router'
    label: str
    ref_id: uuid.UUID | None = None
    position_x: float = 0.0
    position_y: float = 0.0
    config_json: dict = {}


class GraphEdgeSchema(BaseModel):
    id: uuid.UUID | None = None
    source_node_key: str
    target_node_key: str
    condition: str | None = None  # non-null only on conditional edges


class GraphBase(BaseModel):
    name: str
    description: str | None = None
    slug: str | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    retention_days: int = 30
    test_examples: list[dict] | None = None


class GraphCreate(GraphBase):
    nodes: list[GraphNodeSchema] = []
    edges: list[GraphEdgeSchema] = []


class GraphUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    slug: str | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    retention_days: int | None = None
    nodes: list[GraphNodeSchema] | None = None
    edges: list[GraphEdgeSchema] | None = None


class GraphOut(GraphBase):
    id: uuid.UUID
    version: int
    parent_graph_id: uuid.UUID | None
    created_by: uuid.UUID
    org_id: uuid.UUID
    definition_json: dict
    nodes: list[GraphNodeSchema]
    edges: list[GraphEdgeSchema]
    created_at: datetime
    updated_at: datetime
    latest_published_version_id: uuid.UUID | None = None
    latest_version_number: int | None = None  # derived, populated in router

    model_config = {"from_attributes": True}


class GraphSummary(GraphBase):
    """Lightweight listing — no nodes/edges payload."""

    id: uuid.UUID
    version: int
    parent_graph_id: uuid.UUID | None
    created_by: uuid.UUID
    org_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GraphVersionSummary(BaseModel):
    """Lightweight version info — for lists."""

    id: uuid.UUID
    version: int
    published_by: uuid.UUID
    published_at: datetime
    notes: str | None = None

    model_config = {"from_attributes": True}


class GraphVersionOut(BaseModel):
    """Full version record including frozen definition + schemas."""

    id: uuid.UUID
    graph_id: uuid.UUID
    version: int
    definition_json: dict
    input_schema: dict | None = None
    output_schema: dict | None = None
    published_by: uuid.UUID
    published_at: datetime
    notes: str | None = None

    model_config = {"from_attributes": True}


class GraphPublishBody(BaseModel):
    """Body for POST /graphs/{id}/publish."""

    notes: str | None = None
