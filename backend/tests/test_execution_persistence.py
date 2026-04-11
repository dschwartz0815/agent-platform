"""Tests that POST /graphs/{id}/run persists runs + steps via run_graph."""

import json
import uuid

from sqlalchemy import select

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph, GraphVersion
from app.models.run import Run
from app.models.user import Org, User


async def _seed(db_session, monkeypatch):
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="test@example.com",
                        display_name="Test User", org_id=DEV_ORG_ID))
    g = Graph(
        id=uuid.uuid4(),
        name="Test",
        slug="test",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [{"key": "echo", "type": "llm", "config": {}}],
            "edges": [
                {"from": "__start__", "to": "echo", "condition": None},
                {"from": "echo", "to": "__end__", "condition": None},
            ],
        },
    )
    db_session.add(g)
    await db_session.flush()

    # Stub stream_graph so we don't call Anthropic
    async def fake_stream(*args, **kwargs):
        yield {"event": "node_start", "node": "echo", "data": None}
        yield {"event": "node_end", "node": "echo", "data": {"message_text": "ok"}}
        yield {"event": "done", "node": None, "data": {}}

    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)
    return g


async def _drain_sse(response) -> list[dict]:
    """Consume an SSE streaming response body and parse its data: lines."""
    events = []
    text = response.text  # httpx already consumed the body
    for line in text.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


async def test_run_creates_persisted_run(client, db_session, monkeypatch):
    g = await _seed(db_session, monkeypatch)

    r = await client.post(
        f"/api/v1/graphs/{g.id}/run",
        json={"input": {"hello": "world"}},
    )
    assert r.status_code == 200
    events = await _drain_sse(r)

    # First event should be run_started
    assert events[0]["event"] == "run_started"
    run_id = uuid.UUID(events[0]["data"]["run_id"])

    # DB row should exist, succeeded, with editor_test trigger and null version_id
    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    assert run.graph_id == g.id
    assert run.graph_version_id is None  # draft run
    assert run.trigger_source == "editor_test"
    assert run.status == "succeeded"
    assert run.input_json == {"hello": "world"}


async def test_run_with_version_query_pins_graph_version_id(client, db_session, monkeypatch):
    g = await _seed(db_session, monkeypatch)

    # Publish v1 so we have a version to pin to
    pub = await client.post(f"/api/v1/graphs/{g.id}/publish", json={})
    assert pub.status_code == 201
    pub_body = pub.json()
    assert pub_body["version"] == 1

    r = await client.post(
        f"/api/v1/graphs/{g.id}/run?version=1",
        json={"input": {"hello": "world"}},
    )
    assert r.status_code == 200
    events = await _drain_sse(r)

    run_id = uuid.UUID(events[0]["data"]["run_id"])
    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()

    # Version id should match the published v1
    assert run.graph_version_id is not None
    assert str(run.graph_version_id) == pub_body["id"]


async def test_run_with_missing_version_returns_404(client, db_session, monkeypatch):
    g = await _seed(db_session, monkeypatch)

    r = await client.post(
        f"/api/v1/graphs/{g.id}/run?version=99",
        json={"input": {}},
    )
    assert r.status_code == 404
