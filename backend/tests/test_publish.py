"""End-to-end publish endpoint tests with DB + FastAPI client."""

import uuid

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.user import Org, User


async def _seed_basic(db_session):
    """Create the minimum rows needed for graph operations in tests."""
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(
        id=DEV_USER_ID,
        email="test@example.com",
        display_name="Test User",
        org_id=DEV_ORG_ID,
    ))
    graph = Graph(
        id=uuid.uuid4(),
        name="Test Graph",
        description="A graph for publish tests",
        slug="test-graph",
        version=1,
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [
                {"key": "greet", "type": "llm", "config": {"system_prompt": "Hi"}},
            ],
            "edges": [
                {"from": "__start__", "to": "greet", "condition": None},
                {"from": "greet", "to": "__end__", "condition": None},
            ],
        },
        input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
        output_schema={"type": "object"},
    )
    db_session.add(graph)
    await db_session.flush()
    return graph


async def test_publish_creates_version_1(client, db_session):
    graph = await _seed_basic(db_session)

    response = await client.post(
        f"/api/v1/graphs/{graph.id}/publish",
        json={"notes": "First release"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"] == 1
    assert body["notes"] == "First release"
    assert body["input_schema"] == {"type": "object", "properties": {"name": {"type": "string"}}}
    assert body["definition_json"]["nodes"][0]["key"] == "greet"


async def test_publish_increments_version(client, db_session):
    graph = await _seed_basic(db_session)

    r1 = await client.post(f"/api/v1/graphs/{graph.id}/publish", json={})
    assert r1.status_code == 201 and r1.json()["version"] == 1

    r2 = await client.post(f"/api/v1/graphs/{graph.id}/publish", json={"notes": "v2"})
    assert r2.status_code == 201 and r2.json()["version"] == 2


async def test_publish_updates_latest_pointer(client, db_session):
    graph = await _seed_basic(db_session)

    r = await client.post(f"/api/v1/graphs/{graph.id}/publish", json={})
    assert r.status_code == 201
    published_version_id = r.json()["id"]

    refreshed = await client.get(f"/api/v1/graphs/{graph.id}")
    assert refreshed.status_code == 200
    assert refreshed.json()["latest_published_version_id"] == published_version_id
    assert refreshed.json()["latest_version_number"] == 1


async def test_publish_empty_draft_rejected(client, db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="test@example.com",
                        display_name="Test User", org_id=DEV_ORG_ID))
    graph = Graph(
        id=uuid.uuid4(),
        name="Empty",
        slug="empty",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={"nodes": [], "edges": []},
    )
    db_session.add(graph)
    await db_session.flush()

    r = await client.post(f"/api/v1/graphs/{graph.id}/publish", json={})
    assert r.status_code == 422
    # Error body format: the app's exception handler returns {"error": ..., "request_id": ...}
    assert "at least one node" in r.json()["error"]


async def test_publish_graph_not_found(client):
    r = await client.post(
        f"/api/v1/graphs/{uuid.uuid4()}/publish",
        json={},
    )
    assert r.status_code == 404
