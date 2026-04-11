import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.db import get_db
from app.models.agent import Agent
from app.models.graph import Graph, GraphEdge, GraphNode, GraphVersion
from app.models.mcp_server import MCPServer
from app.schemas.graph import (
    GraphCreate,
    GraphEdgeSchema,
    GraphNodeSchema,
    GraphOut,
    GraphPublishBody,
    GraphSummary,
    GraphUpdate,
    GraphVersionOut,
    GraphVersionSummary,
)
from app.services.publishing import PublishValidationError, validate_publishable

router = APIRouter(prefix="/graphs", tags=["graphs"])


def _graph_to_definition(nodes: list[GraphNode], edges: list[GraphEdge]) -> dict:
    """Build the denormalized definition_json from normalized rows."""
    return {
        "nodes": [
            {
                "key": n.node_key,
                "type": n.node_type,
                "label": n.label,
                "ref_id": str(n.ref_id) if n.ref_id else None,
                "config": n.config_json or {},
            }
            for n in nodes
        ],
        "edges": [
            {
                "from": e.source_node_key,
                "to": e.target_node_key,
                "condition": e.condition,
            }
            for e in edges
        ],
    }


async def _load_graph(graph_id: uuid.UUID, db: AsyncSession) -> Graph:
    result = await db.execute(
        select(Graph)
        .options(selectinload(Graph.nodes), selectinload(Graph.edges))
        .where(Graph.id == graph_id)
    )
    graph = result.scalar_one_or_none()
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")
    return graph


def _graph_out(graph: Graph, latest_version_number: int | None = None) -> GraphOut:
    return GraphOut(
        id=graph.id,
        name=graph.name,
        description=graph.description,
        slug=graph.slug,
        input_schema=graph.input_schema,
        output_schema=graph.output_schema,
        retention_days=graph.retention_days,
        version=graph.version,
        parent_graph_id=graph.parent_graph_id,
        created_by=graph.created_by,
        org_id=graph.org_id,
        definition_json=graph.definition_json,
        nodes=[
            GraphNodeSchema(
                id=n.id,
                node_key=n.node_key,
                node_type=n.node_type,
                label=n.label,
                ref_id=n.ref_id,
                position_x=n.position_x,
                position_y=n.position_y,
                config_json=n.config_json,
            )
            for n in graph.nodes
        ],
        edges=[
            GraphEdgeSchema(
                id=e.id,
                source_node_key=e.source_node_key,
                target_node_key=e.target_node_key,
                condition=e.condition,
            )
            for e in graph.edges
        ],
        created_at=graph.created_at,
        updated_at=graph.updated_at,
        latest_published_version_id=graph.latest_published_version_id,
        latest_version_number=latest_version_number,
    )


@router.get("/", response_model=list[GraphSummary])
async def list_graphs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Graph).order_by(Graph.updated_at.desc()))
    graphs = result.scalars().all()
    if not graphs:
        return []

    # Bulk-load the version numbers for any graphs that have a latest_published_version_id
    version_ids = [g.latest_published_version_id for g in graphs if g.latest_published_version_id]
    version_map: dict[uuid.UUID, int] = {}
    if version_ids:
        v_result = await db.execute(
            select(GraphVersion.id, GraphVersion.version).where(GraphVersion.id.in_(version_ids))
        )
        version_map = {row[0]: row[1] for row in v_result.all()}

    return [
        GraphSummary(
            id=g.id,
            name=g.name,
            description=g.description,
            slug=g.slug,
            input_schema=g.input_schema,
            output_schema=g.output_schema,
            retention_days=g.retention_days,
            test_examples=g.test_examples,
            version=g.version,
            parent_graph_id=g.parent_graph_id,
            created_by=g.created_by,
            org_id=g.org_id,
            created_at=g.created_at,
            updated_at=g.updated_at,
            latest_published_version_id=g.latest_published_version_id,
            latest_version_number=version_map.get(g.latest_published_version_id) if g.latest_published_version_id else None,
        )
        for g in graphs
    ]


@router.post("/", response_model=GraphOut, status_code=201)
async def create_graph(body: GraphCreate, db: AsyncSession = Depends(get_db)):
    graph = Graph(
        name=body.name,
        description=body.description,
        version=1,
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={},
    )
    db.add(graph)
    await db.flush()  # get graph.id

    nodes = [
        GraphNode(
            graph_id=graph.id,
            node_key=n.node_key,
            node_type=n.node_type,
            label=n.label,
            ref_id=n.ref_id,
            position_x=n.position_x,
            position_y=n.position_y,
            config_json=n.config_json,
        )
        for n in body.nodes
    ]
    edges = [
        GraphEdge(
            graph_id=graph.id,
            source_node_key=e.source_node_key,
            target_node_key=e.target_node_key,
            condition=e.condition,
        )
        for e in body.edges
    ]
    for row in nodes + edges:
        db.add(row)
    await db.flush()

    graph.definition_json = _graph_to_definition(nodes, edges)
    await db.flush()
    await db.refresh(graph)

    # Reload with relationships
    return _graph_out(await _load_graph(graph.id, db))


@router.get("/{graph_id}", response_model=GraphOut)
async def get_graph(graph_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    graph = await _load_graph(graph_id, db)
    latest_version_number = None
    if graph.latest_published_version_id:
        v_result = await db.execute(
            select(GraphVersion.version).where(GraphVersion.id == graph.latest_published_version_id)
        )
        latest_version_number = v_result.scalar_one_or_none()
    return _graph_out(graph, latest_version_number=latest_version_number)


@router.patch("/{graph_id}", response_model=GraphOut)
async def patch_graph(
    graph_id: uuid.UUID,
    body: GraphUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Partial update: slug, schemas, and other scalar fields. Does NOT touch nodes/edges."""
    graph = await _load_graph(graph_id, db)

    updates = body.model_dump(exclude_unset=True)

    # Slug uniqueness check within org
    if "slug" in updates and updates["slug"] is not None:
        dup = await db.execute(
            select(Graph).where(
                Graph.org_id == graph.org_id,
                Graph.slug == updates["slug"],
                Graph.id != graph.id,
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"slug '{updates['slug']}' already in use by another graph in this org",
            )

    PATCHABLE = {"name", "description", "slug", "input_schema", "output_schema", "retention_days"}
    for field, value in updates.items():
        if field in PATCHABLE:
            setattr(graph, field, value)

    graph.updated_at = datetime.now(timezone.utc)
    await db.flush()
    # Refresh all scalar columns from the DB (picks up the flushed values).
    await db.refresh(graph, attribute_names=["slug", "input_schema", "output_schema",
                                             "name", "description", "retention_days",
                                             "updated_at"])
    # Ensure relationships are populated (they were loaded by _load_graph at the top).
    # Re-use the already-loaded nodes/edges from the graph object; they haven't changed.

    latest_version_number = None
    if graph.latest_published_version_id:
        v_result = await db.execute(
            select(GraphVersion.version).where(GraphVersion.id == graph.latest_published_version_id)
        )
        latest_version_number = v_result.scalar_one_or_none()

    return _graph_out(graph, latest_version_number=latest_version_number)


@router.put("/{graph_id}", response_model=GraphOut)
async def update_graph(
    graph_id: uuid.UUID, body: GraphUpdate, db: AsyncSession = Depends(get_db)
):
    graph = await _load_graph(graph_id, db)

    if body.name is not None:
        graph.name = body.name
    if body.description is not None:
        graph.description = body.description

    if body.nodes is not None or body.edges is not None:
        # Delete existing rows and replace wholesale — simple, correct for demo
        for node in list(graph.nodes):
            await db.delete(node)
        for edge in list(graph.edges):
            await db.delete(edge)
        await db.flush()

        new_nodes = [
            GraphNode(
                graph_id=graph.id,
                node_key=n.node_key,
                node_type=n.node_type,
                label=n.label,
                ref_id=n.ref_id,
                position_x=n.position_x,
                position_y=n.position_y,
                config_json=n.config_json,
            )
            for n in (body.nodes or [])
        ]
        new_edges = [
            GraphEdge(
                graph_id=graph.id,
                source_node_key=e.source_node_key,
                target_node_key=e.target_node_key,
                condition=e.condition,
            )
            for e in (body.edges or [])
        ]
        for row in new_nodes + new_edges:
            db.add(row)
        await db.flush()

        graph.definition_json = _graph_to_definition(new_nodes, new_edges)

    graph.version += 1
    graph.updated_at = datetime.now(timezone.utc)
    await db.flush()

    return _graph_out(await _load_graph(graph.id, db))


@router.post("/{graph_id}/clone", response_model=GraphOut, status_code=201)
async def clone_graph(
    graph_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Fork a graph. The clone is owned by the dev user; real auth wires in user context."""
    source = await _load_graph(graph_id, db)

    clone = Graph(
        name=f"{source.name} (copy)",
        description=source.description,
        version=1,
        parent_graph_id=source.id,
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json=source.definition_json,
    )
    db.add(clone)
    await db.flush()

    for n in source.nodes:
        db.add(GraphNode(
            graph_id=clone.id,
            node_key=n.node_key,
            node_type=n.node_type,
            label=n.label,
            ref_id=n.ref_id,
            position_x=n.position_x,
            position_y=n.position_y,
            config_json=dict(n.config_json) if n.config_json else {},
        ))
    for e in source.edges:
        db.add(GraphEdge(
            graph_id=clone.id,
            source_node_key=e.source_node_key,
            target_node_key=e.target_node_key,
            condition=e.condition,
        ))
    await db.flush()

    return _graph_out(await _load_graph(clone.id, db))


@router.delete("/{graph_id}", status_code=204)
async def delete_graph(graph_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")
    await db.delete(graph)


@router.post(
    "/{graph_id}/publish",
    response_model=GraphVersionOut,
    status_code=201,
)
async def publish_graph(
    graph_id: uuid.UUID,
    body: GraphPublishBody,
    db: AsyncSession = Depends(get_db),
):
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    # Load known agent + mcp server ids for ref validation
    agent_result = await db.execute(select(Agent.id).where(Agent.org_id == graph.org_id))
    mcp_result = await db.execute(select(MCPServer.id).where(MCPServer.org_id == graph.org_id))
    known_agent_ids = {str(a) for (a,) in agent_result.all()}
    known_mcp_ids = {str(m) for (m,) in mcp_result.all()}

    try:
        validate_publishable(
            definition=graph.definition_json or {},
            known_agent_ids=known_agent_ids,
            known_mcp_server_ids=known_mcp_ids,
            input_schema=graph.input_schema,
            output_schema=graph.output_schema,
        )
    except PublishValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Determine next version number
    latest = await db.execute(
        select(func.max(GraphVersion.version)).where(GraphVersion.graph_id == graph.id)
    )
    next_version = (latest.scalar() or 0) + 1

    version = GraphVersion(
        graph_id=graph.id,
        version=next_version,
        definition_json=graph.definition_json,
        input_schema=graph.input_schema,
        output_schema=graph.output_schema,
        published_by=graph.created_by,  # placeholder until auth lands in Plan C
        notes=body.notes,
    )
    db.add(version)
    await db.flush()

    graph.latest_published_version_id = version.id
    await db.flush()
    await db.refresh(version)
    return version


@router.get(
    "/{graph_id}/versions",
    response_model=list[GraphVersionSummary],
)
async def list_graph_versions(
    graph_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")
    result = await db.execute(
        select(GraphVersion)
        .where(GraphVersion.graph_id == graph_id)
        .order_by(GraphVersion.version.desc())
    )
    return result.scalars().all()


@router.get(
    "/{graph_id}/versions/{version}",
    response_model=GraphVersionOut,
)
async def get_graph_version(
    graph_id: uuid.UUID,
    version: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GraphVersion).where(
            GraphVersion.graph_id == graph_id,
            GraphVersion.version == version,
        )
    )
    gv = result.scalar_one_or_none()
    if not gv:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")
    return gv
