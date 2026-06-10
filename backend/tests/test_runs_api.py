"""Tests for GET /graphs/{id}/runs and GET /runs/{run_id} endpoints."""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.run import Run, RunStep
from app.models.user import Org, User


async def _seed_graph_and_runs(db_session, run_count=3):
    db_session.add(Org(id=DEV_ORG_ID, name="Test", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    g = Graph(
        id=uuid.uuid4(), name="G", slug="g",
        created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
        definition_json={"nodes": [], "edges": []},
    )
    db_session.add(g)
    await db_session.flush()

    runs = []
    for i in range(run_count):
        r = Run(
            graph_id=g.id,
            graph_version_id=None,
            trigger_source="editor_test",
            status="succeeded" if i % 2 == 0 else "failed",
            input_json={"index": i},
            output_json={"result": f"out-{i}"} if i % 2 == 0 else None,
            error_message=None if i % 2 == 0 else f"error {i}",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_ms=100 + i,
            token_usage={"input_tokens": 10, "output_tokens": 5,
                         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        )
        db_session.add(r)
        await db_session.flush()

        # Add a couple of steps per run
        for step_i, key in enumerate(["classify", "summarize"], start=1):
            step = RunStep(
                run_id=r.id,
                node_key=key,
                node_type="llm",
                status="succeeded",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                duration_ms=50,
                input_snapshot={"x": step_i},
                output_snapshot={"y": step_i * 2},
                token_usage={"input_tokens": 5, "output_tokens": 2,
                             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                step_order=step_i,
            )
            db_session.add(step)

        runs.append(r)

    await db_session.flush()
    return g, runs


async def test_list_runs_empty(client, db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="T", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    g = Graph(id=uuid.uuid4(), name="G", slug="g",
              created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
              definition_json={"nodes": [], "edges": []})
    db_session.add(g)
    await db_session.flush()

    r = await client.get(f"/api/v1/graphs/{g.id}/runs")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_runs_returns_summaries_newest_first(client, db_session):
    g, runs = await _seed_graph_and_runs(db_session)
    r = await client.get(f"/api/v1/graphs/{g.id}/runs")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3

    first = body[0]
    assert "id" in first
    assert first["graph_id"] == str(g.id)
    assert "trigger_source" in first
    assert first["trigger_source"] == "editor_test"
    assert "input_preview" in first
    assert "index" in first["input_preview"]


async def test_list_runs_filter_by_status(client, db_session):
    g, runs = await _seed_graph_and_runs(db_session)

    r_ok = await client.get(f"/api/v1/graphs/{g.id}/runs?status=succeeded")
    assert r_ok.status_code == 200
    assert all(x["status"] == "succeeded" for x in r_ok.json())

    r_bad = await client.get(f"/api/v1/graphs/{g.id}/runs?status=failed")
    assert r_bad.status_code == 200
    assert all(x["status"] == "failed" for x in r_bad.json())


async def test_list_runs_limit(client, db_session):
    g, runs = await _seed_graph_and_runs(db_session, run_count=5)
    r = await client.get(f"/api/v1/graphs/{g.id}/runs?limit=2")
    assert r.status_code == 200
    assert len(r.json()) == 2


async def test_get_run_detail_includes_steps(client, db_session):
    g, runs = await _seed_graph_and_runs(db_session, run_count=1)
    run_id = runs[0].id

    r = await client.get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(run_id)
    assert body["input_json"] == {"index": 0}
    assert len(body["steps"]) == 2
    assert body["steps"][0]["node_key"] == "classify"
    assert body["steps"][0]["step_order"] == 1
    assert body["steps"][1]["node_key"] == "summarize"
    assert body["steps"][1]["step_order"] == 2
    assert body["token_usage"]["input_tokens"] == 10


async def test_get_run_not_found(client, db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="T", slug="test"))
    await db_session.flush()
    r = await client.get(f"/api/v1/runs/{uuid.uuid4()}")
    assert r.status_code == 404
