"""
Run list + detail endpoints.

GET /api/v1/graphs/{graph_id}/runs       — paginated list of runs for a graph
GET /api/v1/runs/{run_id}                — full run detail with nested steps
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.graph import Graph
from app.models.run import Run
from app.schemas.run import RunOut, RunSummary, RunStepOut


router = APIRouter(tags=["runs"])


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
    db: AsyncSession = Depends(get_db),
):
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    query = select(Run).where(Run.graph_id == graph_id).order_by(Run.started_at.desc())
    if status:
        query = query.where(Run.status == status)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    runs = result.scalars().all()
    return [_to_summary(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Run).options(selectinload(Run.steps)).where(Run.id == run_id)
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
