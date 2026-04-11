"""Version list + detail endpoint tests."""

import uuid

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.user import Org, User


async def _seed(db_session):
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
        slug="test-graph",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [{"key": "greet", "type": "llm", "config": {}}],
            "edges": [
                {"from": "__start__", "to": "greet", "condition": None},
                {"from": "greet", "to": "__end__", "condition": None},
            ],
        },
    )
    db_session.add(graph)
    await db_session.flush()
    return graph


async def test_list_versions_empty(client, db_session):
    graph = await _seed(db_session)
    r = await client.get(f"/api/v1/graphs/{graph.id}/versions")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_versions_after_publish(client, db_session):
    graph = await _seed(db_session)
    await client.post(f"/api/v1/graphs/{graph.id}/publish", json={"notes": "v1"})
    await client.post(f"/api/v1/graphs/{graph.id}/publish", json={"notes": "v2"})
    r = await client.get(f"/api/v1/graphs/{graph.id}/versions")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["version"] == 2 and body[0]["notes"] == "v2"
    assert body[1]["version"] == 1 and body[1]["notes"] == "v1"


async def test_get_version_detail(client, db_session):
    graph = await _seed(db_session)
    await client.post(f"/api/v1/graphs/{graph.id}/publish", json={"notes": "v1"})
    r = await client.get(f"/api/v1/graphs/{graph.id}/versions/1")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert body["notes"] == "v1"
    assert body["definition_json"]["nodes"][0]["key"] == "greet"


async def test_get_version_not_found(client, db_session):
    graph = await _seed(db_session)
    r = await client.get(f"/api/v1/graphs/{graph.id}/versions/99")
    assert r.status_code == 404
