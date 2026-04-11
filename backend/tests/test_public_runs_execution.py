"""End-to-end tests for POST /v1/run/{org}/{slug} — sync + stream + validation."""

import json
import uuid

from sqlalchemy import select

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.run import Run
from app.models.user import Org, User


async def _seed_graph_with_schema(db_session, input_schema=None):
    db_session.add(Org(id=DEV_ORG_ID, name="Acme", slug="acme"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    g = Graph(
        id=uuid.uuid4(),
        name="Test",
        slug="echo",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [{"key": "echo", "type": "llm", "config": {}}],
            "edges": [
                {"from": "__start__", "to": "echo", "condition": None},
                {"from": "echo", "to": "__end__", "condition": None},
            ],
        },
        input_schema=input_schema,
    )
    db_session.add(g)
    await db_session.flush()
    return g


async def _stub_stream(monkeypatch, events=None):
    if events is None:
        events = [
            {"event": "node_start", "node": "echo", "data": None},
            {"event": "node_end", "node": "echo", "data": {"message_text": "ok"}},
            {"event": "done", "node": None, "data": {}},
        ]

    async def fake_stream(*a, **kw):
        for evt in events:
            yield evt

    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)


async def _create_key(client) -> str:
    r = await client.post("/api/v1/api-keys", json={"name": "k", "scopes": ["*"]})
    return r.json()["key"]


async def test_public_sync_mode_returns_json(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {"hello": "world"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "run_id" in body
    assert body["status"] == "succeeded"
    # Sync mode returns accumulated output (message_text from the last node_end)
    assert "output" in body


async def test_public_sync_mode_persists_run_with_trigger(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {"hello": "world"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    run_id = uuid.UUID(r.json()["run_id"])

    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    assert run.trigger_source == "api_sync"
    assert run.status == "succeeded"


async def test_public_stream_mode_returns_sse(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}?mode=stream",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    events = []
    for line in r.text.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    assert events[0]["event"] == "run_started"
    assert any(e["event"] == "done" for e in events)


async def test_public_stream_mode_persists_with_stream_trigger(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}?mode=stream",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    run_id = None
    for line in r.text.split("\n"):
        if line.startswith("data: "):
            evt = json.loads(line[6:])
            if evt["event"] == "run_started":
                run_id = uuid.UUID(evt["data"]["run_id"])
                break

    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    assert run.trigger_source == "api_stream"


async def test_input_validation_failure_returns_422(client, db_session, monkeypatch):
    schema = {
        "type": "object",
        "required": ["title"],
        "properties": {"title": {"type": "string"}},
    }
    g = await _seed_graph_with_schema(db_session, input_schema=schema)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 422
    assert "title" in r.json()["error"]


async def test_version_pinning_via_at_suffix(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)

    pub = await client.post(f"/api/v1/graphs/{g.id}/publish", json={})
    assert pub.status_code == 201

    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}@v1",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    run_id = uuid.UUID(r.json()["run_id"])

    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    assert run.graph_version_id is not None


async def test_version_pin_to_missing_version_returns_404(client, db_session, monkeypatch):
    g = await _seed_graph_with_schema(db_session)
    await _stub_stream(monkeypatch)
    key = await _create_key(client)

    r = await client.post(
        f"/v1/run/acme/{g.slug}@v99",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 404
