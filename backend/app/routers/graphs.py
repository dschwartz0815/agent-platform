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
    return result.scalars().all()


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
