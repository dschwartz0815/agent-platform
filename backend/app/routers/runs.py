"""
Run list + detail endpoints.

GET /api/v1/graphs/{graph_id}/runs       — paginated list of runs for a graph
GET /api/v1/runs/{run_id}                — full run detail with nested steps
POST /api/v1/graphs/{graph_id}/examples  — add a test example to a graph
DELETE /api/v1/graphs/{graph_id}/examples/{example_id} — remove a test example
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sqlalchemy.orm.attributes import flag_modified

from app.db import get_db
from app.models.graph import Graph
from app.models.run import Run
from app.schemas.run import ExampleCreate, ExampleOut, RunOut, RunSummary, RunStepOut
from app.security.identity import WorkspaceContext, get_workspace_context, require_role


router = APIRouter(tags=["runs"])


async def _load_graph_scoped(
    graph_id: uuid.UUID, ctx: WorkspaceContext, db: AsyncSession
) -> Graph:
    graph = await db.get(Graph, graph_id)
    if not graph or graph.org_id != ctx.workspace.id:
        raise HTTPException(status_code=404, detail="Graph not found")
    return graph


def _build_input_preview(input_json: dict) -> str:
    """First 60 chars of json-serialized input — used for table rows."""
    try:
        s = json.dumps(input_json, default=str)
    except (TypeError, ValueError):
        s = str(input_json)
    return s[:60] + ("…" if len(s) > 60 else "")


def _to_summary(run: Run) -> RunSummary:
    return RunSummary(
        id=run.id,
        graph_id=run.graph_id,
        graph_version_id=run.graph_version_id,
        trigger_source=run.trigger_source,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_ms=run.duration_ms,
        token_usage=run.token_usage,
        error_message=run.error_message,
        input_preview=_build_input_preview(run.input_json or {}),
    )


@router.get("/graphs/{graph_id}/runs", response_model=list[RunSummary])
async def list_graph_runs(
    graph_id: uuid.UUID,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    await _load_graph_scoped(graph_id, ctx, db)

    query = select(Run).where(Run.graph_id == graph_id).order_by(Run.started_at.desc())
    if status:
        query = query.where(Run.status == status)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    runs = result.scalars().all()
    return [_to_summary(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run)
        .options(selectinload(Run.steps))
        .join(Graph, Run.graph_id == Graph.id)
        .where(Run.id == run_id, Graph.org_id == ctx.workspace.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunOut(
        id=run.id,
        graph_id=run.graph_id,
        graph_version_id=run.graph_version_id,
        trigger_source=run.trigger_source,
        status=run.status,
        input_json=run.input_json,
        output_json=run.output_json,
        error_message=run.error_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_ms=run.duration_ms,
        token_usage=run.token_usage,
        steps=[RunStepOut.model_validate(s) for s in run.steps],
    )


@router.post(
    "/graphs/{graph_id}/examples",
    response_model=ExampleOut,
    status_code=201,
)
async def create_example(
    graph_id: uuid.UUID,
    body: ExampleCreate,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    require_role(ctx, "editor")
    graph = await _load_graph_scoped(graph_id, ctx, db)

    example = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "input": body.input,
        "output": body.output,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    existing = list(graph.test_examples or [])
    existing.append(example)
    graph.test_examples = existing
    flag_modified(graph, "test_examples")
    await db.flush()
    return example


@router.delete(
    "/graphs/{graph_id}/examples/{example_id}",
    status_code=204,
)
async def delete_example(
    graph_id: uuid.UUID,
    example_id: str,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: AsyncSession = Depends(get_db),
):
    require_role(ctx, "editor")
    graph = await _load_graph_scoped(graph_id, ctx, db)

    existing = list(graph.test_examples or [])
    filtered = [e for e in existing if e.get("id") != example_id]
    if len(filtered) == len(existing):
        raise HTTPException(status_code=404, detail="Example not found")

    graph.test_examples = filtered or None
    flag_modified(graph, "test_examples")
    await db.flush()
